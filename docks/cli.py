"""Command-line entry point: interactive REPL or one-shot prompt."""

import argparse
import os
import sys
from pathlib import Path

from . import __version__, ui
from .agent import DEFAULT_MODEL, Agent

HELP = """Commands:
  /help     show this help
  /clear    start a new conversation
  /usage    show token usage for this session
  /yolo     toggle auto-approval of file writes and shell commands
  /exit     quit
End a line with \\ to keep typing on the next line."""


def read_prompt() -> str:
    lines = []
    while True:
        line = input(ui.bold("› ") if not lines else "  ")
        if line.endswith("\\"):
            lines.append(line[:-1])
            continue
        lines.append(line)
        return "\n".join(lines).strip()


def repl(agent: Agent) -> None:
    print(ui.bold(f"Docks {__version__}") + ui.dim(f"  {agent.model} · {agent.root}"))
    print(ui.dim("Tell me what to build. /help for commands.\n"))
    while True:
        try:
            text = read_prompt()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text.startswith("/"):
            cmd = text.split()[0]
            if cmd in ("/exit", "/quit"):
                return
            elif cmd == "/clear":
                agent.reset()
                print(ui.dim("conversation cleared"))
            elif cmd == "/usage":
                u = agent.usage
                print(ui.dim(f"input {u['input']:,} · cached {u['cache_read']:,} · output {u['output']:,} tokens"))
            elif cmd == "/yolo":
                agent.auto_approve = not agent.auto_approve
                print(ui.dim(f"auto-approve {'on' if agent.auto_approve else 'off'}"))
            else:
                print(HELP)
            continue
        agent.run(text)
        print()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["router"]:
        from .router.cli import main as router_main
        return router_main(argv[1:])
    parser = argparse.ArgumentParser(prog="docks", description="An AI coding agent that builds anything.")
    parser.add_argument("prompt", nargs="*", help="run this task once and exit (omit for interactive mode)")
    parser.add_argument("-C", "--dir", default=".", help="project directory to work in")
    parser.add_argument("-m", "--model", default=os.environ.get("DOCKS_MODEL", DEFAULT_MODEL))
    parser.add_argument("-e", "--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("-y", "--yolo", action="store_true", help="run tools without asking for approval")
    parser.add_argument("--version", action="version", version=f"docks {__version__}")
    args = parser.parse_args(argv)

    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")

    agent = Agent(root=root, model=args.model, effort=args.effort, auto_approve=args.yolo)
    if args.prompt:
        agent.run(" ".join(args.prompt))
        return 0
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            agent.run(piped)
        return 0
    repl(agent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
