"""Terminal output: streamed text, progress notes, tool calls, prompts."""

import json
import sys

COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def dim(t): return _c("2", t)
def bold(t): return _c("1", t)
def cyan(t): return _c("36", t)
def yellow(t): return _c("33", t)
def red(t): return _c("31", t)
def green(t): return _c("32", t)


def warn(msg: str) -> None:
    print(yellow(f"! {msg}"))


def error(msg: str) -> None:
    print(red(f"✗ {msg}"))


def _summarize_args(name: str, args: dict) -> str:
    if name == "bash":
        return args.get("command", "")
    if name in ("write_file", "edit_file", "read_file"):
        return args.get("path", "")
    return json.dumps(args, ensure_ascii=False)


def tool_call(name: str, args: dict) -> None:
    summary = _summarize_args(name, args)
    if len(summary) > 200:
        summary = summary[:200] + "…"
    print(cyan(f"● {name}") + dim(f"  {summary}"))


def tool_output(output: str, is_error: bool = False, max_lines: int = 8) -> None:
    lines = output.splitlines() or [""]
    shown = lines[:max_lines]
    if len(lines) > max_lines:
        shown.append(f"… ({len(lines) - max_lines} more lines)")
    for line in shown:
        print((red if is_error else dim)(f"  │ {line[:160]}"))


def confirm_tool(name: str, args: dict) -> str:
    if name == "write_file":
        preview = args.get("content", "")
        tool_output(preview, max_lines=15)
    elif name == "edit_file":
        tool_output("- " + args.get("old_string", "").replace("\n", "\n- "), max_lines=10)
        tool_output("+ " + args.get("new_string", "").replace("\n", "\n+ "), max_lines=10)
    try:
        answer = input(yellow(f"  allow {name}? [y]es / [n]o / [a]lways: ")).strip().lower()
    except EOFError:
        return "no"
    return {"y": "yes", "yes": "yes", "": "yes", "a": "always", "always": "always"}.get(answer, "no")


class StreamPrinter:
    """Prints streaming events: progress notes dimmed, answer text plain."""

    def __init__(self):
        self.mode = None  # "text" | "thinking"

    def _switch(self, mode: str) -> None:
        if self.mode != mode:
            if self.mode is not None:
                print()
            self.mode = mode

    def handle(self, event) -> None:
        if event.type == "text" and event.text:
            self._switch("text")
            print(event.text, end="", flush=True)
        elif event.type == "thinking" and event.thinking:
            self._switch("thinking")
            print(dim(event.thinking), end="", flush=True)
        elif event.type == "content_block_stop" and self.mode is not None:
            print()
            self.mode = None

    def finish(self) -> None:
        if self.mode is not None:
            print()
