"""Script mode (`docks -p`): run one task without a person at the keyboard, for CI, git hooks, cron jobs or
other programs.

    docks -p "fix the failing test" --allow "Bash(npm test:*)" --allow Edit
    cat error.log | docks -p "why does this fail?"
    docks -p "list the TODOs" --output-format json | jq -r .result

Output formats:
- text (default): only the final answer on stdout.
- json: one object at the end: {"type": "result", "result", "is_error", "session_id", "num_turns", "duration_ms",
  "usage", "denied"}.
- stream-json: one JSON object per line as things happen: init, text, tool_use, tool_result, notice, warning,
  error, permission_denied, then the result object.

Nobody can approve anything, so tool calls that would ask are refused (and reported). Allow what the task
needs with --allow RULE (repeatable), a mode (--mode auto, -y), or permission rules in settings.json.
"""

import json
import sys
import time

from .permissions import suggest_rule


class _Printer:
    def __init__(self, display):
        self.display = display

    def handle(self, event):
        if event.type == "content_block_stop":
            block = event.content_block
            if block.type == "text" and block.text:
                self.display.emit({"type": "text", "text": block.text})
            elif block.type == "server_tool_use":
                self.display.emit({"type": "tool_use", "id": block.id, "name": block.name,
                                   "input": block.input if isinstance(block.input, dict) else {}})

    def finish(self):
        pass


class ScriptDisplay:
    declined_message = ("This is a non-interactive run and this action isn't allowed in it. Don't retry it; "
                        "finish what you can without it and say in your final answer what was blocked.")

    def __init__(self, out, fmt: str = "text", err=None):
        self.out, self.fmt, self.err = out, fmt, err or sys.stderr
        self.errors, self.denied, self.turns = [], [], 0

    def emit(self, event: dict) -> None:
        if self.fmt == "stream-json":
            self.out.write(json.dumps(event, default=str) + "\n")
            self.out.flush()

    def stream(self):
        self.turns += 1
        return _Printer(self)

    def tool_call(self, name, args, id=None, helper=None):
        self.emit({"type": "tool_use", "id": id, "name": name, "input": args})

    def tool_output(self, output, is_error=False, id=None, helper=None):
        self.emit({"type": "tool_result", "id": id, "is_error": is_error, "content": output[:20000]})

    def notice(self, msg):
        self.emit({"type": "notice", "message": msg})

    def warn(self, msg):
        self.emit({"type": "warning", "message": msg})
        if self.fmt == "text":
            print(f"docks: warning: {msg}", file=self.err)

    def error(self, msg):
        self.errors.append(msg)
        self.emit({"type": "error", "message": msg})

    def plan(self, items):
        self.emit({"type": "plan", "items": items})

    def confirm(self, name, args):
        rule = suggest_rule(name, args if isinstance(args, dict) else {})
        self.denied.append({"tool": name, "input": args, "rule": rule})
        self.emit({"type": "permission_denied", "tool": name, "input": args, "suggested_rule": rule})
        if self.fmt == "text":
            print(f"docks: refused {name} (nobody to approve it; allow it with --allow '{rule}' or -y)", file=self.err)
        return "no"

    def ask(self, questions):
        return None  # nobody to answer: Claude proceeds on its own judgment

    def review_plan(self, plan):
        return "reject", ("This is a non-interactive run, so nothing may be changed. End your turn now with the "
                          "complete plan as your final answer.")

    def auto_approved(self, call_id, reason):
        self.emit({"type": "notice", "message": f"auto-approved: {reason}"})

    def turn_done(self, usage):
        pass


def run(agent, prompt, fmt: str = "text", out=None) -> int:
    """Run one task with a ScriptDisplay; write the result. Returns the process exit code."""
    out = out or sys.stdout
    display = ScriptDisplay(out, fmt)
    agent.display = display
    started = time.monotonic()
    display.emit({"type": "init", "session_id": agent.session_id, "model": agent.model, "cwd": str(agent.root),
                  "mode": agent.active_mode, "tools": [t["name"] for t in agent.tools]})
    agent.run(prompt)
    result = agent.last_text() if not display.errors else ""
    is_error = bool(display.errors)
    summary = {"type": "result", "subtype": "error" if is_error else "success", "is_error": is_error,
               "result": result if not is_error else "\n".join(display.errors), "session_id": agent.session_id,
               "num_turns": display.turns, "duration_ms": int((time.monotonic() - started) * 1000),
               "usage": dict(agent.usage), "denied": display.denied}
    if fmt == "text":
        if is_error:
            print("docks: " + "\n".join(display.errors), file=display.err)
        else:
            out.write(result + ("\n" if result and not result.endswith("\n") else ""))
    else:
        out.write(json.dumps(summary, default=str) + "\n")
    out.flush()
    return 1 if is_error else 0
