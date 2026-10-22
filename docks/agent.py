"""The agent loop: stream a turn from Claude, run its tools, repeat until done."""

import itertools
import platform
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import anthropic

from . import automode, memory, sessions
from . import ui as term
from .checkpoints import CheckpointError, Checkpoints
from .mcp import MCPError
from .plugins import TOOL_ALIASES, Extensions, hook_tool_input
from .procs import ProcessManager
from .tools import ToolError, _check, is_mutating, run_tool, tool_definitions

DEFAULT_MODEL = "claude-opus-5-5"
BETAS = [
    "server-side-fallback-2026-07-01",   # re-run declined requests on a fallback model
    "thinking-display-updates-2026-08-18",  # show progress notes between tool calls
    "compact-2026-01-12",  # summarize old context server-side so long sessions keep going
]
MAX_HELPERS = 4
MAX_RETRIES = 6
MAX_STOP_HOOK_ROUNDS = 3
MODES = ("ask", "auto", "plan", "yolo")
NO_KEY = ("No API key was found, so Docks can't reach Claude. Get a key at https://console.anthropic.com, "
          "then set it before starting Docks: export ANTHROPIC_API_KEY=sk-ant-...  (or point ANTHROPIC_BASE_URL "
          "at Docks Router).")
MEMORY_FILES = ("DOCKS.md", "AGENTS.md", "CLAUDE.md")
MAX_JSON_RETRIES = 2
MAX_MENTION_BYTES = 100_000
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
                       "constraints, what to report back). Its final report is returned to you. Set background "
                       "to keep working while it runs; its report then arrives automatically later. Set agent "
                       "to use one of the specialized helper types listed in your instructions.",
        "properties": {
            "description": {"type": "string", "description": "3-6 words shown to the user"},
            "prompt": {"type": "string"},
            "agent": {"type": "string", "description": "optional helper type"},
            "background": {"type": "boolean"},
        },
        "required": ["description", "prompt"],
    },
    "ask_user": {
        "description": "Ask the user one to four multiple-choice questions when a decision is genuinely theirs "
                       "(scope, behavior, look, trade-offs) and guessing could waste their time. Offer 2-4 clear "
                       "options per question, put your recommended option first and say so in its label. The user "
                       "can also type their own answer. Don't use it for things you can find out yourself.",
        "properties": {"questions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "header": {"type": "string", "description": "1-3 word label"},
                "options": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}, "description": {"type": "string"}},
                    "required": ["label"]}},
                "multi_select": {"type": "boolean"},
            },
            "required": ["question", "options"]}}},
        "required": ["questions"],
    },
    "exit_plan_mode": {
        "description": "Only in plan mode: when you've researched enough and your plan is ready, present it here "
                       "(markdown: what you'll change, file by file, and how you'll verify it). The user approves "
                       "it or asks for changes. You may only change files after approval.",
        "properties": {"plan": {"type": "string"}},
        "required": ["plan"],
    },
    "load_skill": {
        "description": "Load a skill: expert instructions for a kind of task. Load the matching skill before doing "
                       "a task it covers; the list of skills is in your instructions.",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}
QUIET_TOOLS = {"update_plan", "load_skill"}  # never need approval and change nothing

HELPER_NOTE = """
You are a helper agent doing one part of a larger task for a lead agent. The user doesn't see your messages;
your final message is returned to the lead agent, so end with a complete, concise report: what you did or
found, with file paths and anything left undone. Stay within the task you were given.
"""

PLAN_MODE_NOTE = ("<system-reminder>Plan mode is on. Research and plan only: read files, search, run read-only "
                  "commands, and ask questions if needed, but don't create, edit or delete files or run commands "
                  "that change anything. When your plan is ready, present it with exit_plan_mode.</system-reminder>")


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
- Ask the user only when a decision is genuinely theirs to make; use ask_user for that. Otherwise use good
  defaults and say what you chose.
- To run a web app (Vite, Next.js, Flask, FastAPI, Express…), start its dev server with start_process. The user
  sees it live in their preview, so prefer real running apps to describing them. Check process_logs after changes.
- For static sites, an index.html at the project root shows in the preview without a server.
- If the user attaches images (screenshots, mockups, designs), build the UI to match them closely.
- Files the user mentions with @path are attached to their message.
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


def build_system_prompt(root: Path, ext: Extensions | None = None) -> str:
    prompt = SYSTEM_PROMPT.format(cwd=root, platform=platform.platform(), date=date.today())
    for name in MEMORY_FILES:
        f = root / name
        if f.is_file():
            prompt += f"\nProject instructions from {name}:\n{f.read_text()[:20_000]}\n"
            break
    lessons = memory.load(root)
    if lessons:
        prompt += f"\n{lessons}\n"
    if ext and ext.skills:
        prompt += "\nSkills (load the matching one with load_skill before doing a task it covers):\n" + "\n".join(
            f"- {s.name}: {s.description}" for s in ext.skills.values()) + "\n"
    if ext and ext.agents:
        prompt += "\nSpecialized helper types for delegate's agent parameter:\n" + "\n".join(
            f"- {a.name}: {a.description}" for a in ext.agents.values()) + "\n"
    return prompt


def _block(b, name, default=None):
    return b.get(name, default) if isinstance(b, dict) else getattr(b, name, default)


@dataclass
class Agent:
    root: Path
    model: str = DEFAULT_MODEL
    effort: str = "high"
    auto_approve: bool = False   # same as mode "yolo"; kept for convenience
    mode: str = "ask"            # ask | auto | plan | yolo
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
    ext: Extensions | None = None  # commands, agents, skills and hooks; loaded if not given
    agent_type: object = None      # a plugins.AgentType, for specialized helpers
    save: bool = False             # keep this conversation in ~/.docks/sessions
    session_id: str = ""
    on_background_done: Callable | None = None  # called when a background helper finishes while idle

    def __post_init__(self):
        self.client_error = None
        if self.client is None:
            try:
                self.client = anthropic.Anthropic()
            except anthropic.AnthropicError as e:  # bad credentials setup: report it when a task runs
                self.client_error = e
        if self.ext is None:
            self.ext = Extensions.load(self.root)
        self.system = build_system_prompt(self.root, self.ext)
        if self.helper:
            self.system += HELPER_NOTE
        if self.agent_type is not None:
            self.system += f"\nYour role ({self.agent_type.name}):\n{self.agent_type.prompt}\n"
        if self.procs is None:
            self.procs = ProcessManager(self.root)
        self.checkpoints = Checkpoints(self.root)
        self.turns = []  # one entry per user turn: where it starts in messages, and the files before it
        self.plan = []
        self.bookmarks = []
        self.session_id = self.session_id or sessions.new_id()
        self.session_name = ""
        self.created = time.time()
        self._confirm_lock = threading.Lock()
        self._background = queue.Queue()     # finished background helper reports
        self._background_running = 0
        self._ids = itertools.count(1)
        self._running = False
        self._session_started = False
        self.refresh_tools()
        self.cancelled = threading.Event()

    # ------------------------------------------------------------- tools

    def refresh_tools(self) -> None:
        """Rebuild the tool list (call after MCP servers start or stop)."""
        def define(name, spec):
            return {"name": name, "description": spec["description"], "eager_input_streaming": True,
                    "input_schema": {"type": "object", "properties": spec["properties"],
                                     "required": spec["required"], "additionalProperties": False}}
        process_defs = [define(n, s) for n, s in PROCESS_TOOLS.items()]
        agent_defs = [define(n, s) for n, s in AGENT_TOOLS.items()
                      if not (self.helper and n in ("delegate", "exit_plan_mode"))
                      and not (n == "load_skill" and not self.ext.skills)]
        mcp_defs = self.mcp.tool_definitions() if self.mcp else []
        tools = [t for t in tool_definitions() + process_defs + agent_defs + mcp_defs + (WEB_TOOLS if self.web else [])
                 if t["name"] not in self.exclude_tools]
        allowed = self.agent_type.tools if self.agent_type is not None else None
        if allowed:  # a specialized helper limited to some tools (Claude Code or Docks names both work)
            tools = [t for t in tools if t["name"] in allowed or TOOL_ALIASES.get(t["name"]) in allowed
                     or t["name"] in QUIET_TOOLS]
        self.tools = tools

    @property
    def active_mode(self) -> str:
        return "yolo" if self.auto_approve else self.mode

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        self.mode = mode
        self.auto_approve = mode == "yolo"

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
            return self._agent_tool(name, args)
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

    def _agent_tool(self, name: str, args: dict) -> tuple[str, bool]:
        if name == "update_plan":
            self.plan = args["items"]
            self.display.plan(self.plan)
            return "plan updated", False
        if name == "delegate":
            return self._delegate(args["description"], args["prompt"], args.get("agent"), args.get("background", False))
        if name == "load_skill":
            skill = self.ext.skills.get(args["name"])
            if not skill:
                raise ToolError(f"no skill named {args['name']!r}; available: {', '.join(self.ext.skills) or 'none'}")
            return skill.load(), False
        if name == "ask_user":
            ask = getattr(self.display, "ask", None)
            if ask is None:
                return "No one can answer questions right now. Choose sensible defaults and say what you chose.", False
            with self._confirm_lock:
                answers = ask(args["questions"])
            if answers is None:
                return "The user dismissed the questions. Choose sensible defaults, or ask in plain text.", False
            return "\n\n".join(f"Q: {q['question']}\nA: {a}" for q, a in zip(args["questions"], answers)), False
        if name == "exit_plan_mode":
            if self.active_mode != "plan":
                return "Plan mode isn't on; go ahead with the work.", False
            review = getattr(self.display, "review_plan", None)
            decision, feedback = review(args["plan"]) if review else ("approve", "")
            if decision == "approve_auto":
                self.set_mode("auto")
                return "The user approved the plan and turned on auto mode. Carry it out now.", False
            if decision == "approve":
                self.set_mode("ask")
                return "The user approved the plan. Carry it out now.", False
            return f"The user wants changes to the plan before you start: {feedback or '(no details)'}. " \
                   "Revise it and present it again with exit_plan_mode.", False
        raise ToolError(f"unknown tool {name}")

    def last_text(self) -> str:
        """The text of Claude's final reply in the conversation (empty if the last turn failed)."""
        if not self.messages or self.messages[-1]["role"] != "assistant":
            return ""
        return "".join(_block(b, "text", "") or "" for b in self.messages[-1]["content"]
                       if _block(b, "type") == "text").strip()

    # ------------------------------------------------------------- helpers

    def _make_helper(self, description: str, agent_name: str | None):
        agent_type = None
        if agent_name:
            agent_type = self.ext.agents.get(agent_name)
            if agent_type is None:
                raise ToolError(f"no helper type {agent_name!r}; available: {', '.join(self.ext.agents) or 'none'}")
        helper = Agent(root=self.root, model=(agent_type.model if agent_type and agent_type.model else self.model),
                       effort=self.effort, auto_approve=self.auto_approve, mode=self.mode if self.mode != "plan" else "ask",
                       web=self.web, exclude_tools=self.exclude_tools, client=self.client, mcp=self.mcp,
                       procs=self.procs, helper=True, always_allowed=self.always_allowed, ext=self.ext,
                       agent_type=agent_type, display=HelperDisplay(self.display, description),
                       confirm=self._locked_confirm)
        helper.cancelled = self.cancelled  # stopping the lead agent stops its helpers
        return helper

    def _delegate(self, description: str, prompt: str, agent_name: str | None = None,
                  background: bool = False) -> tuple[str, bool]:
        helper = self._make_helper(description, agent_name)
        if background:
            hid = next(self._ids)
            self._background_running += 1

            def work():
                report, failed = self._run_helper(helper, prompt)
                self._background.put((hid, description, report, failed))
                self._background_running -= 1
                self.display.notice(f"Background helper finished: {description}")
                if not self._running and self.on_background_done:
                    self.on_background_done()
            threading.Thread(target=work, daemon=True).start()
            return (f"Helper #{hid} ({description}) is working in the background. Its report will be delivered to "
                    "you automatically when it finishes; carry on with other work meanwhile."), False
        return self._run_helper(helper, prompt)

    def _run_helper(self, helper: "Agent", prompt: str) -> tuple[str, bool]:
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

    def _take_background_reports(self) -> list[dict]:
        blocks = []
        while True:
            try:
                hid, description, report, failed = self._background.get_nowait()
            except queue.Empty:
                return blocks
            status = "failed" if failed else "finished"
            blocks.append({"type": "text", "text": f"<background-helper id=\"{hid}\" description=\"{description}\" "
                                                   f"status=\"{status}\">\n{report}\n</background-helper>"})

    def has_background_reports(self) -> bool:
        return not self._background.empty()

    # ------------------------------------------------------------- session state

    def reset(self):
        self.messages.clear()
        self.turns.clear()
        self.plan = []
        self.bookmarks = []
        self.session_id = sessions.new_id()
        self.session_name = ""
        self.created = time.time()
        self._session_started = False

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
        self.save_session()
        return entry["text"], restored

    def bookmark(self, text: str) -> None:
        self.bookmarks.append({"text": text, "time": time.time()})
        self.save_session()

    def session_data(self) -> dict:
        title = next((t["text"].splitlines()[0][:80] for t in self.turns if t["text"].strip()), "")
        return {"id": self.session_id, "name": self.session_name, "title": title, "root": str(self.root),
                "model": self.model, "created": self.created, "messages": sessions.plain(self.messages),
                "turns": self.turns, "plan": self.plan, "bookmarks": self.bookmarks, "usage": self.usage}

    def save_session(self) -> None:
        if self.save and not self.helper and self.messages:
            sessions.save(self.session_data())

    def resume(self, session_id: str) -> dict:
        """Load a saved conversation into this agent."""
        data = sessions.load(session_id)
        self.session_id, self.session_name = data["id"], data.get("name", "")
        self.messages = data["messages"]
        self.turns, self.plan = data.get("turns", []), data.get("plan", [])
        self.bookmarks, self.created = data.get("bookmarks", []), data.get("created", time.time())
        self.usage = {**self.usage, **data.get("usage", {})}
        self._session_started = True
        return data

    def rename(self, name: str) -> None:
        self.session_name = name.strip()
        self.save_session()

    # ------------------------------------------------------------- running

    def stop(self):
        """Cancel the running turn (safe to call from another thread)."""
        self.cancelled.set()

    def _check_cancel(self):
        if self.cancelled.is_set():
            raise TurnAborted("stopped; this turn was discarded")

    def _expand_mentions(self, text: str) -> list[dict]:
        """@path mentions of files or folders in the project become attached text blocks."""
        blocks, seen = [], set()
        for m in re.finditer(r"(?<![\w@/])@([\w./~-]+[\w/])", text):
            rel = m.group(1)
            path = (self.root / rel).resolve()
            if rel in seen or not path.is_relative_to(self.root.resolve()) or not path.exists():
                continue
            seen.add(rel)
            if path.is_dir():
                entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir() if not p.name.startswith("."))
                blocks.append({"type": "text", "text": f"<folder path=\"{rel}\">\n" + "\n".join(entries[:300]) + "\n</folder>"})
            else:
                data = path.read_bytes()[:MAX_MENTION_BYTES]
                try:
                    content = data.decode()
                except UnicodeDecodeError:
                    continue
                blocks.append({"type": "text", "text": f"<file path=\"{rel}\">\n{content}\n</file>"})
            if len(blocks) >= 10:
                break
        return blocks

    def run(self, user_input: str | list) -> None:
        """Run one user turn to completion. On failure or interrupt, roll the history back.

        user_input is text, or a list of content blocks (e.g. images followed by text). Text starting with
        /name runs that command; @path mentions attach files."""
        turn_start = len(self.messages)
        text = user_input if isinstance(user_input, str) else " ".join(
            b.get("text", "") for b in user_input if b.get("type") == "text")
        self._running = True
        try:
            if not self.helper:
                self.cancelled.clear()
                expanded = self.ext.expand(text) if isinstance(user_input, str) else None
                if expanded:
                    user_input, cmd = expanded
                    self.display.notice(f"Running /{cmd.name}")
            extra = self._turn_context(text) if not self.helper else []
            if extra is None:
                return  # a hook blocked the prompt
            if not self.helper:
                self.turns.append({"index": turn_start, "text": text,
                                   "checkpoint": self.checkpoints.snapshot(text.splitlines()[0] if text else "task")})
            if extra:
                base = [{"type": "text", "text": user_input}] if isinstance(user_input, str) else list(user_input)
                user_input = base + extra
            self.messages.append({"role": "user", "content": user_input})
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
            self._running = False
            self.save_session()
            self.display.turn_done(self.usage)

    def _turn_context(self, text: str) -> list[dict] | None:
        """Extra blocks for this user turn: hook context, @mentions, mode reminders, background reports.
        None means a UserPromptSubmit hook blocked the prompt."""
        extra = []
        if self.ext.hooks:
            if not self._session_started:
                start = self.ext.run_hooks("SessionStart", {"source": "startup", "session_id": self.session_id})
                if start.context:
                    extra.append({"type": "text", "text": f"<session-context>\n{start.context}\n</session-context>"})
            submit = self.ext.run_hooks("UserPromptSubmit", {"prompt": text, "session_id": self.session_id})
            if submit.block:
                self.display.error(f"A hook blocked this message: {submit.reason or 'no reason given'}")
                return None
            if submit.context:
                extra.append({"type": "text", "text": f"<hook-context>\n{submit.context}\n</hook-context>"})
        self._session_started = True
        extra += self._expand_mentions(text)
        if self.active_mode == "plan":
            extra.append({"type": "text", "text": PLAN_MODE_NOTE})
        extra += self._take_background_reports()
        return extra

    def _loop(self) -> None:
        json_retries = 0
        stop_rounds = 0
        while True:
            reports = self._take_background_reports()
            if reports:  # helpers that finished while we worked: hand their reports over now
                last = self.messages[-1]
                content = last["content"] if isinstance(last["content"], list) else [{"type": "text", "text": last["content"]}]
                last["content"] = content + reports
            try:
                response = self._stream_with_retries()
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
                if self.ext.hooks and stop_rounds < MAX_STOP_HOOK_ROUNDS and not self.helper:
                    verdict = self.ext.run_hooks("Stop", {"stop_hook_active": stop_rounds > 0,
                                                          "session_id": self.session_id})
                    if verdict.block and verdict.reason:
                        stop_rounds += 1
                        self.display.notice(f"A hook asked Docks to keep going: {verdict.reason}")
                        self.messages.append({"role": "user", "content": f"<system-reminder>Before finishing: "
                                              f"{verdict.reason}</system-reminder>"})
                        continue
                return

            results = {}
            helpers = [b for b in tool_uses if b.name == "delegate" and not (isinstance(b.input, dict) and b.input.get("background"))]
            for block in tool_uses:
                if stop == "max_tokens" and block is tool_uses[-1]:
                    # The last tool input was likely cut off mid-stream; don't run it.
                    results[block.id] = _error_result(block.id, "Your tool input was cut off by the output limit. "
                                                                "Retry with smaller pieces (e.g. write the file in parts).")
                elif block not in helpers:
                    results[block.id] = self._execute(block)
            todo = [b for b in helpers if b.id not in results]
            if todo:  # helpers run in parallel
                with ThreadPoolExecutor(max_workers=min(MAX_HELPERS, len(todo))) as pool:
                    for block, result in zip(todo, pool.map(self._execute, todo)):
                        results[block.id] = result
            self.messages.append({"role": "user", "content": [results[b.id] for b in tool_uses]})

    def _stream_with_retries(self):
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._stream_once()
            except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.OverloadedError,
                    anthropic.ServiceUnavailableError, anthropic.APIConnectionError) as e:
                if attempt == MAX_RETRIES or isinstance(e, anthropic.AuthenticationError):
                    raise
                delay = _retry_after(e) or min(60, 2 ** (attempt + 1))
                reason = "rate limit reached" if isinstance(e, anthropic.RateLimitError) else \
                         "connection problem" if isinstance(e, anthropic.APIConnectionError) else "Claude is busy"
                self.display.notice(f"{reason}; trying again in {delay:.0f}s ({attempt + 1}/{MAX_RETRIES})")
                end = time.monotonic() + delay
                while time.monotonic() < end:
                    self._check_cancel()
                    time.sleep(min(0.2, max(0.0, end - time.monotonic())))

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

    def _approved(self, name: str, args: dict, call_id: str, hook_decision: str | None) -> tuple[bool, str]:
        """Whether a tool call may run, asking the user if needed. Returns (ok, message if not)."""
        if hook_decision == "allow":
            return True, ""
        if not self._mutating(name):
            return True, ""
        mode = self.active_mode
        if mode == "plan":
            return False, ("Plan mode is on, so nothing can be changed yet. Finish researching and present your "
                           "plan with exit_plan_mode.")
        if hook_decision != "ask":
            if mode == "yolo" or name in self.always_allowed:
                return True, ""
            if mode == "auto":
                verdict, reason = automode.classify(self.client, name, args, self.root)
                if verdict == "allow":
                    note = getattr(self.display, "auto_approved", None)
                    if note:
                        note(call_id, reason)
                    return True, ""
        answer = self._locked_confirm(name, args)
        self._check_cancel()
        if answer == "always":
            self.always_allowed.add(name)
        elif answer != "yes":
            return False, "The user declined this tool call. Ask what they want instead."
        return True, ""

    def _execute(self, block) -> dict:
        self._check_cancel()
        args = block.input
        self.display.tool_call(block.name, args, id=block.id)
        decision = None
        if self.ext.hooks and isinstance(args, dict):
            pre = self.ext.run_hooks("PreToolUse", {"tool_name": TOOL_ALIASES.get(block.name, block.name),
                                                    "tool_input": hook_tool_input(block.name, args),
                                                    "session_id": self.session_id}, tool=block.name)
            if pre.block or pre.decision == "deny":
                message = f"A hook blocked this: {pre.reason or 'no reason given'}"
                self.display.tool_output(message, is_error=True, id=block.id)
                return _error_result(block.id, message)
            decision = pre.decision
        ok, why = self._approved(block.name, args if isinstance(args, dict) else {}, block.id, decision)
        if not ok:
            self.display.tool_output(why, is_error=True, id=block.id)
            return _error_result(block.id, why)
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
        if self.ext.hooks and isinstance(args, dict):
            post = self.ext.run_hooks("PostToolUse", {"tool_name": TOOL_ALIASES.get(block.name, block.name),
                                                      "tool_input": hook_tool_input(block.name, args),
                                                      "tool_response": output[:20_000], "session_id": self.session_id},
                                      tool=block.name)
            feedback = "\n".join(x for x in (post.reason if post.block else "", post.context) if x)
            if feedback:
                output = f"{output}\n\n[hook feedback]\n{feedback}"
        self.display.tool_output(output, is_error=failed, id=block.id)
        result = {"type": "tool_result", "tool_use_id": block.id, "content": output}
        return {**result, "is_error": True} if failed else result

    def _track_usage(self, usage) -> None:
        self.usage["input"] += usage.input_tokens or 0
        self.usage["output"] += usage.output_tokens or 0
        self.usage["cache_read"] += usage.cache_read_input_tokens or 0


def _retry_after(error) -> float | None:
    response = getattr(error, "response", None)
    try:
        value = response.headers.get("retry-after") if response is not None else None
        return min(120.0, float(value)) if value else None
    except (TypeError, ValueError):
        return None


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

    def ask(self, questions):
        ask = getattr(self.parent, "ask", None)
        return ask(questions) if ask else None

    def auto_approved(self, call_id, reason):
        note = getattr(self.parent, "auto_approved", None)
        if note:
            note(call_id, reason)

    def turn_done(self, usage):
        pass
