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


def start_mcp(root: Path, interactive: bool):
    """Start configured MCP servers. In a terminal, ask once before starting a project's own servers."""
    from .mcp import MCPError, MCPManager
    try:
        mgr = MCPManager(root)
    except MCPError as e:
        ui.warn(str(e))
        return None
    if not mgr.servers:
        return mgr
    mgr.start()
    for server in mgr.pending_approval():
        if not interactive:
            ui.warn(f"skipping project MCP server '{server.name}' (not approved yet; run docks in a terminal to approve)")
            continue
        what = server.spec.get("url") or " ".join([server.spec.get("command", ""), *server.spec.get("args", [])])
        answer = input(ui.yellow(f"This project wants to start MCP server '{server.name}': {what}\n  Allow? [y/N] "))
        if answer.strip().lower() in ("y", "yes"):
            mgr.approve(server.name)
    for server in mgr.servers.values():
        if server.status == "running":
            print(ui.dim(f"MCP: {server.name} ({len(server.tools)} tools)"))
        elif server.status == "error":
            ui.warn(f"MCP server '{server.name}' failed: {server.error}")
    return mgr


def image_block(path: str) -> dict:
    import base64
    import mimetypes
    kind = mimetypes.guess_type(path)[0] or "image/png"
    data = base64.b64encode(Path(path).expanduser().read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": kind, "data": data}}


def mcp_main(argv) -> int:
    from . import mcp
    parser = argparse.ArgumentParser(prog="docks mcp", description="Connect Docks to MCP servers.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="add a server: docks mcp add NAME -- COMMAND [ARGS...]  or  --url URL")
    add.add_argument("name")
    add.add_argument("--url", help="URL of a remote (streamable HTTP) MCP server")
    add.add_argument("--header", action="append", default=[], help="HTTP header, e.g. 'Authorization: Bearer ${TOKEN}'")
    add.add_argument("--env", action="append", default=[], help="environment variable for a local server, KEY=VALUE")
    add.add_argument("--scope", choices=["user", "project"], default="user",
                     help="user: ~/.docks/mcp.json (default); project: ./.mcp.json, shared with the repo")
    add.add_argument("command", nargs=argparse.REMAINDER, help="command that starts a local server (after --)")
    rm = sub.add_parser("remove", help="remove a server")
    rm.add_argument("name")
    rm.add_argument("--scope", choices=["user", "project"], default="user")
    sub.add_parser("list", help="show servers and their tools")
    parser.add_argument("-C", "--dir", default=".")
    args = parser.parse_args(argv)
    root = Path(args.dir).expanduser().resolve()
    path = lambda scope: mcp.user_config_path() if scope == "user" else mcp.project_config_path(root)

    if args.cmd == "add":
        command = [c for c in args.command if c != "--"]
        if bool(args.url) == bool(command):
            parser.error("give either --url URL or -- COMMAND [ARGS...]")
        if args.url:
            spec = {"type": "http", "url": args.url}
            if args.header:
                spec["headers"] = dict(h.split(":", 1) for h in args.header)
                spec["headers"] = {k.strip(): v.strip() for k, v in spec["headers"].items()}
        else:
            spec = {"command": command[0], "args": command[1:]}
            if args.env:
                spec["env"] = dict(e.split("=", 1) for e in args.env)
        mcp.write_server(path(args.scope), args.name, spec)
        print(ui.green(f"added '{args.name}' to {path(args.scope)}"))
        return 0
    if args.cmd == "remove":
        mcp.write_server(path(args.scope), args.name, None)
        print(f"removed '{args.name}'")
        return 0
    mgr = start_mcp(root, interactive=sys.stdin.isatty())
    if not mgr or not mgr.servers:
        print("No MCP servers yet. Add one, e.g.:\n  docks mcp add files -- npx -y @modelcontextprotocol/server-filesystem .")
        return 0
    for s in mgr.summary():
        mark = {"running": ui.green("●"), "error": ui.red("●")}.get(s["status"], ui.yellow("●"))
        print(f"{mark} {ui.bold(s['name'])} [{s['scope']}] {ui.dim(s['command'])}")
        if s["error"]:
            print(ui.red(f"    {s['error']}"))
        for t in s["tools"]:
            print(ui.dim(f"    - {t}"))
    mgr.close()
    return 0


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
    from .mcp import MCPManager
    mgr = MCPManager(root)
    mgr.start()  # project servers wait for approval in the browser
    serve(Agent(root=root, model=args.model, effort=args.effort, auto_approve=args.yolo, mcp=mgr),
          host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def install_github_main(argv) -> int:
    from .action import DEFAULT_SOURCE, install
    parser = argparse.ArgumentParser(prog="docks install-github",
                                     description="Add the @docks bot to a GitHub repo (as a GitHub Actions workflow).")
    parser.add_argument("-C", "--dir", default=".", help="the repo to set up")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="where the workflow installs Docks from")
    args = parser.parse_args(argv)
    path = install(Path(args.dir).expanduser().resolve(), args.source)
    print(ui.green(f"Wrote {path}"))
    print("""
Next steps:
  1. Add your Anthropic API key as a repo secret:
       gh secret set ANTHROPIC_API_KEY     (or Settings > Secrets and variables > Actions)
  2. Let Actions open pull requests:
       Settings > Actions > General > Workflow permissions >
       check "Allow GitHub Actions to create and approve pull requests"
  3. Commit and push .github/workflows/docks.yml
  4. Mention @docks in an issue or pull request, or label an issue "docks".

Optional: set the repo variable DOCKS_AUTO_REVIEW=true to review every new pull request,
and DOCKS_MODEL to pick the model.""")
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
    Agent(root=root, model=args.model, effort=args.effort, auto_approve=args.yolo,
          mcp=start_mcp(root, sys.stdin.isatty())).run(prompt)
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["router"]:
        from .router.cli import main as router_main
        return router_main(argv[1:])
    if argv[:1] == ["web"]:
        return web_main(argv[1:])
    if argv[:1] == ["mcp"]:
        return mcp_main(argv[1:])
    if argv[:1] == ["action"]:
        from .action import main as action_main
        return action_main(argv[1:])
    if argv[:1] == ["install-github"]:
        return install_github_main(argv[1:])
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
    parser.add_argument("-i", "--image", action="append", default=[],
                        help="attach an image (screenshot, mockup, design) to the task; repeatable")
    parser.add_argument("--version", action="version", version=f"docks {__version__}")
    args = parser.parse_args(argv)

    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")

    agent = Agent(root=root, model=args.model, effort=args.effort, auto_approve=args.yolo,
                  mcp=start_mcp(root, sys.stdin.isatty()))
    if args.prompt:
        text = " ".join(args.prompt)
        agent.run([*map(image_block, args.image), {"type": "text", "text": text}] if args.image else text)
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
