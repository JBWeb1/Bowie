"""The agent loop: stream a turn from Claude, run its tools, repeat until done."""

import platform
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import anthropic

from . import memory
from . import ui as term
from .tools import ToolError, is_mutating, run_tool, tool_definitions

DEFAULT_MODEL = "claude-opus-5-5"
BETAS = [
    "server-side-fallback-2026-07-01",   # re-run declined requests on a fallback model
    "thinking-display-updates-2026-08-18",  # show progress notes between tool calls
]
MEMORY_FILES = ("DOCKS.md", "AGENTS.md", "CLAUDE.md")
MAX_JSON_RETRIES = 2
WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]


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
    display: object = field(default_factory=lambda: term.TerminalUI())  # where output goes
    confirm: Callable[[str, dict], str] | None = None  # overrides display.confirm
    client: anthropic.Anthropic = field(default_factory=anthropic.Anthropic)
    messages: list = field(default_factory=list)
    always_allowed: set = field(default_factory=set)
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0})

    def __post_init__(self):
        self.system = build_system_prompt(self.root)
        self.tools = tool_definitions() + (WEB_TOOLS if self.web else [])
        self.cancelled = threading.Event()

    def reset(self):
        self.messages.clear()

    def stop(self):
        """Cancel the running turn (safe to call from another thread)."""
        self.cancelled.set()

    def _check_cancel(self):
        if self.cancelled.is_set():
            raise TurnAborted("stopped; this turn was discarded")

    def run(self, user_input: str) -> None:
        """Run one user turn to completion. On failure or interrupt, roll the history back."""
        turn_start = len(self.messages)
        self.cancelled.clear()
        self.messages.append({"role": "user", "content": user_input})
        try:
            self._loop()
        except KeyboardInterrupt:
            self.display.warn("interrupted; this turn was discarded")
            del self.messages[turn_start:]
        except TurnAborted as e:
            self.display.error(str(e))
            del self.messages[turn_start:]
        except anthropic.APIError as e:
            self.display.error(f"API error: {e}")
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

            results = []
            for block in tool_uses:
                if stop == "max_tokens" and block is tool_uses[-1]:
                    # The last tool input was likely cut off mid-stream; don't run it.
                    results.append(_error_result(block.id, "Your tool input was cut off by the output limit. "
                                                            "Retry with smaller pieces (e.g. write the file in parts)."))
                    continue
                results.append(self._execute(block))
            self.messages.append({"role": "user", "content": results})

    def _stream_once(self):
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
        self.display.tool_call(block.name, args)
        if is_mutating(block.name) and not self.auto_approve and block.name not in self.always_allowed:
            answer = (self.confirm or self.display.confirm)(block.name, args)
            self._check_cancel()
            if answer == "always":
                self.always_allowed.add(block.name)
            elif answer != "yes":
                return _error_result(block.id, "The user declined this tool call. Ask what they want instead.")
        try:
            output = run_tool(self.root, block.name, args)
        except ToolError as e:
            self.display.tool_output(str(e), is_error=True)
            return _error_result(block.id, str(e))
        except Exception as e:  # tool bugs shouldn't kill the session
            self.display.tool_output(repr(e), is_error=True)
            return _error_result(block.id, f"{type(e).__name__}: {e}")
        self.display.tool_output(output)
        return {"type": "tool_result", "tool_use_id": block.id, "content": output}

    def _track_usage(self, usage) -> None:
        self.usage["input"] += usage.input_tokens or 0
        self.usage["output"] += usage.output_tokens or 0
        self.usage["cache_read"] += usage.cache_read_input_tokens or 0


def _error_result(tool_use_id: str, message: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}

