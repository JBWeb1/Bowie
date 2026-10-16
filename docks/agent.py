"""The agent loop: stream a turn from Claude, run its tools, repeat until done."""

import platform
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import anthropic

from . import ui
from .tools import ToolError, is_mutating, run_tool, tool_definitions

DEFAULT_MODEL = "claude-opus-5-5"
BETAS = [
    "server-side-fallback-2026-07-01",   # re-run declined requests on a fallback model
    "thinking-display-updates-2026-08-18",  # show progress notes between tool calls
]
MEMORY_FILES = ("DOCKS.md", "AGENTS.md", "CLAUDE.md")
MAX_JSON_RETRIES = 2


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
    return prompt


@dataclass
class Agent:
    root: Path
    model: str = DEFAULT_MODEL
    effort: str = "high"
    auto_approve: bool = False
    confirm: Callable[[str, dict], str] = ui.confirm_tool
    client: anthropic.Anthropic = field(default_factory=anthropic.Anthropic)
    messages: list = field(default_factory=list)
    always_allowed: set = field(default_factory=set)
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0})

    def __post_init__(self):
        self.system = build_system_prompt(self.root)
        self.tools = tool_definitions()

    def reset(self):
        self.messages.clear()

    def run(self, user_input: str) -> None:
        """Run one user turn to completion. On failure or interrupt, roll the history back."""
        turn_start = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})
        try:
            self._loop()
        except KeyboardInterrupt:
            ui.warn("interrupted; this turn was discarded")
            del self.messages[turn_start:]
        except TurnAborted as e:
            ui.error(str(e))
            del self.messages[turn_start:]
        except anthropic.APIError as e:
            ui.error(f"API error: {e}")
            del self.messages[turn_start:]

    def _loop(self) -> None:
        json_retries = 0
        while True:
            try:
                response = self._stream_once()
            except ValueError as e:  # tool input arrived as JSON the SDK couldn't parse
                json_retries += 1
                if json_retries > MAX_JSON_RETRIES:
                    raise TurnAborted(f"repeated malformed tool input: {e}")
                ui.warn("malformed tool input; retrying")
                continue

            self._track_usage(response.usage)
            stop = response.stop_reason

            if stop == "refusal":
                raise TurnAborted("Claude declined this request; the turn was discarded.")

            self.messages.append({"role": "assistant", "content": response.content})

            if stop == "pause_turn":
                continue
            if stop == "model_context_window_exceeded":
                ui.warn("context window is full; use /clear to start fresh")
                return

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if stop == "max_tokens":
                    ui.warn("response hit the output limit")
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
        printer = ui.StreamPrinter()
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
                printer.handle(event)
            response = stream.get_final_message()
        printer.finish()
        return response

    def _execute(self, block) -> dict:
        args = block.input
        ui.tool_call(block.name, args)
        if is_mutating(block.name) and not self.auto_approve and block.name not in self.always_allowed:
            answer = self.confirm(block.name, args)
            if answer == "always":
                self.always_allowed.add(block.name)
            elif answer != "yes":
                return _error_result(block.id, "The user declined this tool call. Ask what they want instead.")
        try:
            output = run_tool(self.root, block.name, args)
        except ToolError as e:
            ui.tool_output(str(e), is_error=True)
            return _error_result(block.id, str(e))
        except Exception as e:  # tool bugs shouldn't kill the session
            ui.tool_output(repr(e), is_error=True)
            return _error_result(block.id, f"{type(e).__name__}: {e}")
        ui.tool_output(output)
        return {"type": "tool_result", "tool_use_id": block.id, "content": output}

    def _track_usage(self, usage) -> None:
        self.usage["input"] += usage.input_tokens or 0
        self.usage["output"] += usage.output_tokens or 0
        self.usage["cache_read"] += usage.cache_read_input_tokens or 0


def _error_result(tool_use_id: str, message: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}

