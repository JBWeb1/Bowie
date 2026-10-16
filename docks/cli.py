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


def web_main(argv) -> int:
    parser = argparse.ArgumentParser(prog="docks web", description="Use Docks from your browser.")
    parser.add_argument("-C", "--dir", default=".", help="project directory to work in")
    parser.add_argument("-m", "--model", default=os.environ.get("DOCKS_MODEL", DEFAULT_MODEL))
    parser.add_argument("-e", "--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("-y", "--yolo", action="store_true", help="run tools without asking for approval")
    parser.add_argument("--host", default="127.0.0.1", help="interface to listen on (default: this machine only)")
    parser.add_argument("--port", type=int, default=8788, help="app port; the preview uses the next one")
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = parser.parse_args(argv)
    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")
    from .web.server import serve
    serve(Agent(root=root, model=args.model, effort=args.effort, auto_approve=args.yolo),
          host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def clone_main(argv) -> int:
    from . import github
    parser = argparse.ArgumentParser(prog="docks clone", description="Clone a GitHub repo and start Docks in it.")
    parser.add_argument("repo", help="owner/repo or a GitHub URL")
    parser.add_argument("dir", nargs="?", help="where to clone (default: the repo name)")
    parser.add_argument("--web", action="store_true", help="open it in the browser UI")
    args = parser.parse_args(argv)
    spec = github.parse_repo(args.repo)
    if not spec:
        parser.error(f"not a GitHub repository: {args.repo}")
    dest = Path(args.dir or spec.split("/")[1]).resolve()
    print(ui.dim(f"cloning {spec} into {dest}…"))
    try:
        github.clone(spec, dest)
    except github.GitHubError as e:
        ui.error(str(e))
        return 1
    return web_main(["-C", str(dest)]) if args.web else main(["-C", str(dest)])


def github_task_main(argv) -> int:
    from . import github
    parser = argparse.ArgumentParser(prog=f"docks {argv[0]}")
    if argv[0] != "pr":
        parser.add_argument("number", type=int, help="issue number" if argv[0] == "fix" else "pull request number")
    parser.add_argument("-C", "--dir", default=".")
    parser.add_argument("-m", "--model", default=os.environ.get("DOCKS_MODEL", DEFAULT_MODEL))
    parser.add_argument("-e", "--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("-y", "--yolo", action="store_true", help="run tools without asking for approval")
    args = parser.parse_args(argv[1:])
    root = Path(args.dir).expanduser().resolve()
    prompt = {"fix": lambda: github.fix_issue_prompt(args.number),
              "review": lambda: github.review_pr_prompt(args.number),
              "pr": github.open_pr_prompt}[argv[0]]()
    Agent(root=root, model=args.model, effort=args.effort, auto_approve=args.yolo).run(prompt)
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["router"]:
        from .router.cli import main as router_main
        return router_main(argv[1:])
    if argv[:1] == ["web"]:
        return web_main(argv[1:])
    if argv[:1] == ["clone"]:
        return clone_main(argv[1:])
    if argv[:1] in (["fix"], ["review"], ["pr"]):
        return github_task_main(argv)
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
