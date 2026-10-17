"""The agent loop: stream a turn from Claude, run its tools, repeat until done."""

import platform
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import anthropic

from . import memory
from . import ui as term
from .checkpoints import CheckpointError, Checkpoints
from .mcp import MCPError
from .procs import ProcessManager
from .tools import ToolError, _check, is_mutating, run_tool, tool_definitions

DEFAULT_MODEL = "claude-opus-5-5"
BETAS = [
    "server-side-fallback-2026-07-01",   # re-run declined requests on a fallback model
    "thinking-display-updates-2026-08-18",  # show progress notes between tool calls
    "compact-2026-01-12",  # summarize old context server-side so long sessions keep going
]
MAX_HELPERS = 4
NO_KEY = ("No API key was found, so Docks can't reach Claude. Get a key at https://console.anthropic.com, "
          "then set it before starting Docks: export ANTHROPIC_API_KEY=sk-ant-...  (or point ANTHROPIC_BASE_URL "
          "at Docks Router).")
MEMORY_FILES = ("DOCKS.md", "AGENTS.md", "CLAUDE.md")
MAX_JSON_RETRIES = 2
WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]


PROCESS_TOOLS = {
    "start_process": {
        "description": "Start a long-running command in the background, such as a dev server (npm run dev, "
                       "python -m http.server, uvicorn, flask run). Returns its first output and the local URL it "
                       "serves, which the user sees live in their preview. Use bash for commands that finish.",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    "process_logs": {
        "description": "Read recent output of a background process (to check for errors after a change).",
        "properties": {"process_id": {"type": "integer"}, "lines": {"type": "integer"}},
        "required": ["process_id"],
    },
    "stop_process": {
        "description": "Stop a background process.",
        "properties": {"process_id": {"type": "integer"}},
        "required": ["process_id"],
    },
}


AGENT_TOOLS = {
    "update_plan": {
        "description": "Show the user your plan as a checklist and keep it current. Use it for tasks with several "
                       "steps: write the plan before starting, then update statuses as you go. Send the full list "
                       "each time.",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
            "required": ["text", "status"]}}},
        "required": ["items"],
    },
    "delegate": {
        "description": "Hand a self-contained piece of work to a helper agent with its own fresh context and the "
                       "same tools. Call it several times in one response to run helpers in parallel, e.g. "
                       "research different parts of a codebase, or build independent features in separate files. "
                       "The helper sees only your prompt, so include everything it needs (goal, files, "
                       "constraints, what to report back). Its final report is returned to you.",
        "properties": {
            "description": {"type": "string", "description": "3-6 words shown to the user"},
            "prompt": {"type": "string"},
        },
        "required": ["description", "prompt"],
    },
}

HELPER_NOTE = """
You are a helper agent doing one part of a larger task for a lead agent. The user doesn't see your messages;
your final message is returned to the lead agent, so end with a complete, concise report: what you did or
found, with file paths and anything left undone. Stay within the task you were given.
"""


class TurnAborted(Exception):
    pass


SYSTEM_PROMPT = """You are Docks, an autonomous coding agent working in the user's terminal.
You can build anything the user asks for: apps, websites, scripts, APIs, games, tools.

How to work:
- Explore before changing things: list files, read the relevant code, check how the project builds and tests.
- Make real changes with your tools. Write complete, working code, not sketches or placeholders.
- Prefer edit_file for small changes to existing files and write_file for new files.
- After changing code, verify it: run it, build it, or run the tests, and fix what fails.
- Match the existing code style. Don't add features or refactors nobody asked for.
- For a new project, pick a sensible, mainstream stack unless the user specifies one, and include a README with how to run it.
- Ask the user only when a decision is genuinely theirs to make; otherwise use good defaults and say what you chose.
- To run a web app (Vite, Next.js, Flask, FastAPI, Express…), start its dev server with start_process. The user
  sees it live in their preview, so prefer real running apps to describing them. Check process_logs after changes.
- For static sites, an index.html at the project root shows in the preview without a server.
- If the user attaches images (screenshots, mockups, designs), build the UI to match them closely.
- Tools named mcp__<server>__<tool> come from MCP servers the user connected; use them when they fit the task.
- Use web_search and web_fetch to read current documentation when you're unsure how a library or API works.
- When you learn something worth keeping (a mistake you made, a fix that worked, a user preference,
  how this project builds), save it with the remember tool so future sessions do better.
- GitHub: when the user mentions an issue or pull request by number, read it with github_issue or github_pr.
  Do work on a feature branch, never commit straight to the default branch, never force-push, and open
  pull requests with create_pull_request. Write PR descriptions that explain what changed and why.
- Never run destructive commands (rm -rf outside the project, force pushes, dropping databases) unless the user asked.
- Finish with a short summary of what you did and how to run or check it.

Environment:
- Working directory: {cwd}
- Platform: {platform}
- Date: {date}
"""


def build_system_prompt(root: Path) -> str:
    prompt = SYSTEM_PROMPT.format(cwd=root, platform=platform.platform(), date=date.today())
    for name in MEMORY_FILES:
        f = root / name
        if f.is_file():
            prompt += f"\nProject instructions from {name}:\n{f.read_text()[:20_000]}\n"
            break
    lessons = memory.load(root)
    if lessons:
        prompt += f"\n{lessons}\n"
    return prompt


@dataclass
class Agent:
    root: Path
    model: str = DEFAULT_MODEL
    effort: str = "high"
    auto_approve: bool = False
    web: bool = True
    exclude_tools: tuple = ()  # tool names to leave out, e.g. when a runner handles PRs itself
    display: object = field(default_factory=lambda: term.TerminalUI())  # where output goes
    confirm: Callable[[str, dict], str] | None = None  # overrides display.confirm
    client: anthropic.Anthropic | None = None  # created from the environment if not given
    messages: list = field(default_factory=list)
    always_allowed: set = field(default_factory=set)
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0})
    mcp: object = None    # an mcp.MCPManager, already started
    procs: object = None  # a procs.ProcessManager; created if not given
    helper: bool = False  # a helper started by another agent's delegate tool

    def __post_init__(self):
        self.client_error = None
        if self.client is None:
            try:
                self.client = anthropic.Anthropic()
            except anthropic.AnthropicError as e:  # bad credentials setup: report it when a task runs
                self.client_error = e
        self.system = build_system_prompt(self.root)
        if self.helper:
            self.system += HELPER_NOTE
        if self.procs is None:
            self.procs = ProcessManager(self.root)
        self.checkpoints = Checkpoints(self.root)
        self.turns = []  # one entry per user turn: where it starts in messages, and the files before it
        self.plan = []
        self._confirm_lock = threading.Lock()
        self.refresh_tools()
        self.cancelled = threading.Event()

    def refresh_tools(self) -> None:
        """Rebuild the tool list (call after MCP servers start or stop)."""
        process_defs = [{"name": n, "description": spec["description"], "eager_input_streaming": True,
                         "input_schema": {"type": "object", "properties": spec["properties"],
                                          "required": spec["required"], "additionalProperties": False}}
                        for n, spec in PROCESS_TOOLS.items()]
        agent_defs = [{"name": n, "description": spec["description"], "eager_input_streaming": True,
                       "input_schema": {"type": "object", "properties": spec["properties"],
                                        "required": spec["required"], "additionalProperties": False}}
                      for n, spec in AGENT_TOOLS.items() if not (self.helper and n == "delegate")]
        mcp_defs = self.mcp.tool_definitions() if self.mcp else []
        self.tools = [t for t in tool_definitions() + process_defs + agent_defs + mcp_defs + (WEB_TOOLS if self.web else [])
                      if t["name"] not in self.exclude_tools]

    def _mutating(self, name: str) -> bool:
        if name in AGENT_TOOLS:
            return False  # a helper's own tool calls ask for approval as usual
        if name in PROCESS_TOOLS:
            return name == "start_process"
        if self.mcp and self.mcp.handles(name):
            return self.mcp.is_mutating(name)
        return is_mutating(name)

    def _run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        if name in AGENT_TOOLS:
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            _check(args, {"type": "object", **AGENT_TOOLS[name]}, "input")
            if name == "update_plan":
                self.plan = args["items"]
                self.display.plan(self.plan)
                return "plan updated", False
            return self._delegate(args["description"], args["prompt"])
        if name in PROCESS_TOOLS:
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            _check(args, {"type": "object", **PROCESS_TOOLS[name]}, "input")
            if name == "start_process":
                return self.procs.start(args["command"]), False
            if name == "process_logs":
                return self.procs.logs(args["process_id"], args.get("lines", 100)), False
            return self.procs.stop(args["process_id"]), False
        if self.mcp and self.mcp.handles(name):
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            try:
                return self.mcp.call(name, args)
            except MCPError as e:
                raise ToolError(str(e))
        return run_tool(self.root, name, args), False

    def last_text(self) -> str:
        """The text of Claude's final reply in the conversation (empty if the last turn failed)."""
        if not self.messages or self.messages[-1]["role"] != "assistant":
            return ""
        return "".join(getattr(b, "text", "") for b in self.messages[-1]["content"]
                       if getattr(b, "type", None) == "text").strip()

    def _delegate(self, description: str, prompt: str) -> tuple[str, bool]:
        helper = Agent(root=self.root, model=self.model, effort=self.effort, auto_approve=self.auto_approve,
                       web=self.web, exclude_tools=self.exclude_tools, client=self.client, mcp=self.mcp,
                       procs=self.procs, helper=True, always_allowed=self.always_allowed,
                       display=HelperDisplay(self.display, description), confirm=self._locked_confirm)
        helper.cancelled = self.cancelled  # stopping the lead agent stops its helpers
        helper.run(prompt)
        for key in self.usage:
            self.usage[key] += helper.usage[key]
        report = helper.last_text()
        if not report:
            return "The helper stopped before finishing and gave no report.", True
        return report, False

    def _locked_confirm(self, name: str, args: dict) -> str:
        with self._confirm_lock:  # helpers run in parallel; ask the user one question at a time
            return (self.confirm or self.display.confirm)(name, args)

    def reset(self):
        self.messages.clear()
        self.turns.clear()
        self.plan = []

    def rewind(self, turn: int) -> tuple[str, list[str]]:
        """Go back to just before user turn `turn` (0-based): restore files and drop that turn and later ones.

        Returns the text of that turn's message (to edit and resend) and the files that were restored."""
        if not 0 <= turn < len(self.turns):
            raise CheckpointError("no such turn")
        entry = self.turns[turn]
        if not entry["checkpoint"]:
            raise CheckpointError("there's no file snapshot for that point, so it can't be restored")
        restored = self.checkpoints.restore(entry["checkpoint"])
        del self.messages[entry["index"]:]
        del self.turns[turn:]
        return entry["text"], restored

    def stop(self):
        """Cancel the running turn (safe to call from another thread)."""
        self.cancelled.set()

    def _check_cancel(self):
        if self.cancelled.is_set():
            raise TurnAborted("stopped; this turn was discarded")

    def run(self, user_input: str | list) -> None:
        """Run one user turn to completion. On failure or interrupt, roll the history back.

        user_input is text, or a list of content blocks (e.g. images followed by text)."""
        turn_start = len(self.messages)
        if not self.helper:
            self.cancelled.clear()
            text = user_input if isinstance(user_input, str) else " ".join(
                b.get("text", "") for b in user_input if b.get("type") == "text")
            self.turns.append({"index": turn_start, "text": text,
                               "checkpoint": self.checkpoints.snapshot(text.splitlines()[0] if text else "task")})
        self.messages.append({"role": "user", "content": user_input})
        try:
            self._loop()
        except KeyboardInterrupt:
            self.display.warn("interrupted; this turn was discarded")
            del self.messages[turn_start:]
        except TurnAborted as e:
            self.display.error(str(e))
            del self.messages[turn_start:]
        except anthropic.AuthenticationError:
            self.display.error(NO_KEY.replace("No API key was found", "The API key was rejected"))
            del self.messages[turn_start:]
        except anthropic.APIError as e:
            self.display.error(f"API error: {e}")
            del self.messages[turn_start:]
        except anthropic.CredentialsError as e:  # e.g. a named profile that doesn't exist
            self.display.error(f"{NO_KEY} ({e})")
            del self.messages[turn_start:]
        except anthropic.AnthropicError as e:
            self.display.error(f"Error talking to Claude: {e}")
            del self.messages[turn_start:]
        except TypeError as e:
            if "authentication method" not in str(e):
                raise
            self.display.error(NO_KEY)  # the SDK found no credentials at all
            del self.messages[turn_start:]
        finally:
            self.display.turn_done(self.usage)

    def _loop(self) -> None:
        json_retries = 0
        while True:
            try:
                response = self._stream_once()
            except ValueError as e:  # tool input arrived as JSON the SDK couldn't parse
                json_retries += 1
                if json_retries > MAX_JSON_RETRIES:
                    raise TurnAborted(f"repeated malformed tool input: {e}")
                self.display.warn("malformed tool input; retrying")
                continue

            self._track_usage(response.usage)
            stop = response.stop_reason
            if any(getattr(b, "type", None) == "compaction" for b in response.content):
                self.display.notice("Summarized the earlier conversation to make room, and kept going.")

            if stop == "refusal":
                raise TurnAborted("Claude declined this request; the turn was discarded.")

            self.messages.append({"role": "assistant", "content": response.content})

            if stop == "pause_turn":
                continue
            if stop == "model_context_window_exceeded":
                self.display.warn("context window is full; use /clear to start fresh")
                return

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if stop == "max_tokens":
                    self.display.warn("response hit the output limit")
                return

            results = {}
            helpers = [b for b in tool_uses if b.name == "delegate"]
            for block in tool_uses:
                if stop == "max_tokens" and block is tool_uses[-1]:
                    # The last tool input was likely cut off mid-stream; don't run it.
                    results[block.id] = _error_result(block.id, "Your tool input was cut off by the output limit. "
                                                                "Retry with smaller pieces (e.g. write the file in parts).")
                elif block.name != "delegate":
                    results[block.id] = self._execute(block)
            todo = [b for b in helpers if b.id not in results]
            if todo:  # helpers run in parallel
                with ThreadPoolExecutor(max_workers=min(MAX_HELPERS, len(todo))) as pool:
                    for block, result in zip(todo, pool.map(self._execute, todo)):
                        results[block.id] = result
            self.messages.append({"role": "user", "content": [results[b.id] for b in tool_uses]})

    def _stream_once(self):
        if self.client is None:
            raise TurnAborted(f"{NO_KEY} ({self.client_error})")
        printer = self.display.stream()
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=64_000,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            thinking={"type": "adaptive", "display": "updates"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            context_management={"edits": [{"type": "compact_20260112"}]},
            fallbacks="default",
            betas=BETAS,
        ) as stream:
            for event in stream:
                self._check_cancel()
                printer.handle(event)
            response = stream.get_final_message()
        printer.finish()
        return response

    def _execute(self, block) -> dict:
        self._check_cancel()
        args = block.input
        self.display.tool_call(block.name, args, id=block.id)
        if self._mutating(block.name) and not self.auto_approve and block.name not in self.always_allowed:
            answer = self._locked_confirm(block.name, args)
            self._check_cancel()
            if answer == "always":
                self.always_allowed.add(block.name)
            elif answer != "yes":
                return _error_result(block.id, "The user declined this tool call. Ask what they want instead.")
        try:
            output, failed = self._run_tool(block.name, args)
        except ToolError as e:
            self.display.tool_output(str(e), is_error=True, id=block.id)
            return _error_result(block.id, str(e))
        except TurnAborted:
            raise
        except Exception as e:  # tool bugs shouldn't kill the session
            self.display.tool_output(repr(e), is_error=True, id=block.id)
            return _error_result(block.id, f"{type(e).__name__}: {e}")
        self.display.tool_output(output, is_error=failed, id=block.id)
        result = {"type": "tool_result", "tool_use_id": block.id, "content": output}
        return {**result, "is_error": True} if failed else result

    def _track_usage(self, usage) -> None:
        self.usage["input"] += usage.input_tokens or 0
        self.usage["output"] += usage.output_tokens or 0
        self.usage["cache_read"] += usage.cache_read_input_tokens or 0


def _error_result(tool_use_id: str, message: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}



class _QuietStream:
    def handle(self, event):
        pass

    def finish(self):
        pass


class HelperDisplay:
    """What a helper agent shows: its tool calls (labelled with the helper), not its streamed text."""

    def __init__(self, parent, name: str):
        self.parent, self.name = parent, name

    def stream(self):
        return _QuietStream()

    def tool_call(self, name, args, id=None):
        self.parent.tool_call(name, args, id=id, helper=self.name)

    def tool_output(self, output, is_error=False, id=None):
        self.parent.tool_output(output, is_error=is_error, id=id, helper=self.name)

    def warn(self, msg):
        self.parent.warn(f"{self.name}: {msg}")

    def error(self, msg):
        self.parent.warn(f"{self.name}: {msg}")

    def notice(self, msg):
        self.parent.notice(f"{self.name}: {msg}")

    def plan(self, items):
        pass  # the lead agent owns the plan

    def confirm(self, name, args):
        return self.parent.confirm(name, args)

    def turn_done(self, usage):
        pass
