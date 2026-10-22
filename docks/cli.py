"""Command-line entry point: interactive REPL or one-shot prompt."""

import argparse
import os
import sys
from pathlib import Path

from . import __version__, ui
from .agent import DEFAULT_MODEL, Agent, mode_from_settings

HELP = """Commands:
  /help              show this help
  /clear             start a new conversation
  /mode [ask|auto|plan|yolo]  how Docks asks before changes (no argument: show the current mode)
  /plan              plan mode: research and propose a plan before changing anything
  /undo              undo the last task: put files back and forget it (repeat to go further back)
  /resume [name|id]  continue a saved conversation (no argument: list them)
  /sessions          list saved conversations for this project
  /rename <name>     name this conversation
  /bookmark          save Claude's last reply;  /bookmarks  list saved replies
  /copy              copy Claude's last reply to the clipboard
  /commands /agents /skills /hooks   show what's installed
  /model [NAME]      opus, fable, sonnet, haiku, codex or chatgpt
  /compact [focus]   summarize the conversation to free up room
  /context           what's filling the context window
  /memory            instruction files in use;  # <note> adds a line to one
  /output-style      explanatory, learning, concise or your own
  /security-review   check changes for security holes
  /doctor            check your setup
  /vim               vim keys on/off;  /statusline  show the status line
  /sandbox [on|off]  run commands in a sandbox (writes only inside the project)
  /permissions       show allow / ask / deny rules
  /allow RULE        never ask about it, e.g. /allow Bash(npm test:*)   (/ask and /deny too)
  /usage             token usage for this session
  /yolo              same as /mode yolo (toggle); shift+tab cycles modes
  /exit              quit
Any other /name runs that command (built-in, yours, or from a plugin). Mention files with @path.
Use the up arrow for earlier messages. End a line with \\ to keep typing on the next line."""


def start_mcp(root: Path, interactive: bool, extra: dict | None = None):
    """Start configured MCP servers. In a terminal, ask once before starting a project's own servers."""
    from .mcp import MCPError, MCPManager
    try:
        mgr = MCPManager(root, extra)
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


def _copy_to_clipboard(text: str) -> bool:
    import base64
    import shutil
    import subprocess
    for tool in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["clip.exe"]):
        if shutil.which(tool[0]):
            try:
                subprocess.run(tool, input=text, text=True, timeout=5, check=True)
                return True
            except (OSError, subprocess.SubprocessError):
                pass
    if sys.stdout.isatty():  # OSC 52: most terminals copy this, even over SSH
        sys.stdout.write(f"\033]52;c;{base64.b64encode(text.encode()).decode()}\a")
        sys.stdout.flush()
        return True
    return False


def _print_sessions(agent: Agent) -> None:
    import time as _time
    from . import sessions
    items = sessions.list_sessions(agent.root, limit=20)
    if not items:
        print(ui.dim("no saved conversations for this project yet"))
    for s_ in items:
        when = _time.strftime("%b %d %H:%M", _time.localtime(s_["updated"]))
        mark = ui.green("●") if s_["id"] == agent.session_id else " "
        print(f"{mark} {ui.bold(s_['name'][:60])}  {ui.dim(when + ' · ' + str(s_['turns']) + ' msgs · ' + s_['id'])}")


def slash(agent: Agent, text: str) -> bool:
    """Handle a built-in REPL command. Returns False if it isn't one (so it goes to the agent)."""
    from .checkpoints import CheckpointError
    cmd, _, arg = text.partition(" ")
    arg = arg.strip()
    if cmd in ("/exit", "/quit"):
        raise EOFError
    if cmd == "/help":
        print(HELP)
        if agent.ext.commands:
            print(ui.bold("\nAvailable commands:"))
            for c in sorted(agent.ext.commands.values(), key=lambda c: c.name):
                print(f"  /{c.name:<22} {ui.dim(c.description[:90])}")
    elif cmd == "/clear":
        agent.reset()
        print(ui.dim("conversation cleared"))
    elif cmd == "/usage":
        u = agent.usage
        print(ui.dim(f"input {u['input']:,} · cached {u['cache_read']:,} · output {u['output']:,} tokens"))
    elif cmd == "/undo":
        if not agent.turns:
            print(ui.dim("nothing to undo"))
            return True
        try:
            undone, restored = agent.rewind(len(agent.turns) - 1)
        except CheckpointError as e:
            ui.error(str(e))
            return True
        print(ui.green(f"undid: {undone[:80]}"))
        print(ui.dim(f"restored {len(restored)} file(s): {', '.join(restored[:8])}" if restored else "no files had changed"))
    elif cmd == "/yolo":
        agent.set_mode("ask" if agent.active_mode == "yolo" else "yolo")
        print(ui.dim(f"mode: {agent.active_mode}"))
    elif cmd in ("/mode", "/plan"):
        mode = "plan" if cmd == "/plan" else arg
        if mode == "next":
            from .agent import MODES
            mode = MODES[(MODES.index(agent.active_mode) + 1) % len(MODES)]
        if not mode:
            print(ui.dim(f"mode: {agent.active_mode}  (ask: confirm each change · auto: confirm only risky ones · "
                         "plan: plan first, change nothing · yolo: never ask)"))
            return True
        try:
            agent.set_mode(mode)
        except ValueError as e:
            ui.error(str(e))
            return True
        print(ui.dim(f"mode: {agent.active_mode}"))
    elif cmd == "/sessions" or (cmd == "/resume" and not arg):
        _print_sessions(agent)
        if cmd == "/resume":
            print(ui.dim("resume one with /resume <name or id>"))
    elif cmd == "/resume":
        from . import sessions
        sid = sessions.find(arg, agent.root) or sessions.find(arg)
        if not sid:
            ui.error(f"no saved conversation matches {arg!r}")
            return True
        data = agent.resume(sid)
        print(ui.green(f"resumed: {data.get('name') or data.get('title') or sid}") +
              ui.dim(f"  ({len(data.get('turns', []))} messages)"))
        last = agent.last_text()
        if last:
            print(ui.dim("last reply: " + last.splitlines()[0][:160]))
    elif cmd == "/rename":
        if not arg:
            ui.error("give a name: /rename <name>")
            return True
        agent.rename(arg)
        print(ui.dim(f"named this conversation {arg!r}"))
    elif cmd == "/bookmark":
        last = agent.last_text()
        if not last:
            print(ui.dim("nothing to bookmark yet"))
            return True
        agent.bookmark(last)
        print(ui.dim("bookmarked Claude's last reply (/bookmarks to see them)"))
    elif cmd == "/bookmarks":
        if not agent.bookmarks:
            print(ui.dim("no bookmarks in this conversation"))
        for i, b in enumerate(agent.bookmarks, 1):
            print(ui.bold(f"[{i}]") + " " + b["text"][:600] + ("…" if len(b["text"]) > 600 else ""))
    elif cmd == "/copy":
        last = agent.last_text()
        if not last:
            print(ui.dim("nothing to copy yet"))
        else:
            print(ui.dim("copied Claude's last reply" if _copy_to_clipboard(last) else "couldn't reach a clipboard"))
    elif cmd == "/commands":
        for c in sorted(agent.ext.commands.values(), key=lambda c: c.name):
            print(f"  /{c.name:<22} {ui.dim(f'[{c.source}] ' + c.description[:80])}")
    elif cmd == "/agents":
        if not agent.ext.agents:
            print(ui.dim("no custom helper types (add agents/*.md in ~/.docks, .claude or a plugin)"))
        for a in agent.ext.agents.values():
            print(f"  {ui.bold(a.name)}  {ui.dim(a.description[:100])}")
    elif cmd == "/skills":
        if not agent.ext.skills:
            print(ui.dim("no skills (add skills/<name>/SKILL.md in ~/.docks, .claude or a plugin)"))
        for sk in agent.ext.skills.values():
            print(f"  {ui.bold(sk.name)}  {ui.dim(sk.description[:100])}")
    elif cmd == "/model":
        from . import models
        if not arg:
            for c in models.choices():
                mark = ui.green("●") if c["id"] == agent.model else " "
                print(f"  {mark} {c['alias']:<8} {models.label(c['id']):<34} {ui.dim(c['note'])}")
            if agent.model not in [c["id"] for c in models.choices()]:
                print(f"  {ui.green('●')} {agent.model}")
            print(ui.dim("switch with /model NAME (or a full model ID); docks models update finds newer ones"))
            return True
        try:
            model = agent.set_model(arg)
        except ValueError as e:
            ui.error(str(e))
            return True
        print(ui.dim(f"model: {models.label(model)}"))
    elif cmd == "/compact":
        print(ui.dim("summarizing the conversation…"))
        try:
            summary = agent.compact(arg)
        except ValueError as e:
            ui.error(str(e))
            return True
        print(ui.green("conversation summarized") + ui.dim(f" ({len(summary):,} characters kept; earlier undo points are gone)"))
    elif cmd == "/context":
        print_context(agent)
    elif cmd == "/memory":
        from . import instructions
        if arg.startswith("edit"):
            scope = (arg.split() + ["project"])[1]
            path = instructions.note_path(agent.root, scope if scope in ("project", "local", "user") else "project")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
            import subprocess
            subprocess.call(f'{editor} "{path}"', shell=True)
            agent.reload_instructions()
            print(ui.dim(f"reloaded {path}"))
            return True
        shown = [*instructions.user_files(), instructions.project_file(agent.root), instructions.local_file(agent.root),
                 *sorted(agent._folders_read)]
        shown = [p_ for p_ in shown if p_]
        if not shown:
            print(ui.dim("no instruction files yet. Start a message with # to add one, or run /init"))
        for p_ in shown:
            print(f"  {p_}  {ui.dim(str(len(p_.read_text(errors='replace').splitlines())) + ' lines')}")
        print(ui.dim("/memory edit [project|local|user] opens one in your editor; # <note> adds a line"))
    elif cmd in ("/output-style", "/style"):
        if not arg:
            for name in ["default", *agent.ext.output_styles]:
                style = agent.ext.output_styles.get(name)
                mark = ui.green("●") if name == agent.output_style else " "
                print(f"  {mark} {name:<14} {ui.dim(style.description if style else 'Docks as usual')}")
            print(ui.dim("choose one with /output-style NAME"))
            return True
        try:
            agent.set_output_style(arg)
        except ValueError as e:
            ui.error(str(e))
            return True
        print(ui.dim(f"output style: {agent.output_style}"))
    elif cmd == "/doctor":
        from . import doctor
        print(doctor.report(doctor.check(agent.root, agent.ext, agent.mcp, agent)))
    elif cmd == "/vim":
        from . import terminal
        on = {"on": True, "off": False}.get(arg, agent.ext.settings.get("editorMode") != "vim")
        terminal.set_vim(agent, on)
        print(ui.dim(f"vim keys {'on' if on else 'off'} (saved in your settings)"))
    elif cmd == "/statusline":
        from . import terminal
        line = terminal.status_line(agent)
        print(line or ui.dim("the status line is hidden (statusLine type none)"))
        print(ui.dim('use your own: {"statusLine": {"type": "command", "command": "~/my-status.sh"}} in settings.json'))
    elif cmd == "/sandbox":
        from .sandbox import SandboxUnavailable
        want = {"on": True, "off": False}.get(arg, agent.sandbox is None)
        try:
            print(ui.dim(agent.set_sandbox(want)))
        except SandboxUnavailable as e:
            ui.error(str(e))
    elif cmd == "/permissions":
        rules = agent.ext.permissions.summary()
        if not any(rules.values()):
            print(ui.dim("no permission rules yet; add some with /allow, /ask or /deny, e.g. /allow Bash(npm test:*)"))
        for kind, color in (("deny", ui.red), ("ask", ui.yellow), ("allow", ui.green)):
            for r in rules[kind]:
                print(f"  {color(kind):<16} {r}")
        if agent.always_allowed:
            print(ui.dim(f"  always allowed this session: {', '.join(sorted(agent.always_allowed))}"))
    elif cmd in ("/allow", "/deny", "/ask"):
        from .permissions import parse
        if not arg or not parse(arg, agent.root):
            ui.error(f"give a rule, e.g. {cmd} Bash(npm test:*) · {cmd} Edit(src/**) · {cmd} Read(./.env)")
            return True
        path = agent.ext.save_rule(cmd[1:], arg)
        print(ui.dim(f"{cmd[1:]}: {arg}  (saved in {path.relative_to(agent.root)}, kept out of git)"))
    elif cmd == "/hooks":
        if not agent.ext.hooks and not agent.ext.pending_hooks:
            print(ui.dim("no hooks"))
        for h in agent.ext.hooks:
            print(f"  {ui.bold(h.event)} {h.matcher or '*'}  {ui.dim(h.command[:80] + '  [' + h.source + ']')}")
        for p_ in agent.ext.pending_hooks:
            print(ui.yellow(f"  waiting for approval: {p_['file']}"))
    else:
        return False
    return True


def approve_project_hooks(agent: Agent) -> None:
    import json as _json
    for pending in list(agent.ext.pending_hooks):
        what = ("settings that let Docks act without asking" if pending["name"].startswith("settings:")
                else "hooks that run commands automatically")
        print(ui.yellow(f"This project has {what} in {pending['file']}:"))
        print(ui.dim(_json.dumps(pending["spec"], indent=2)[:1200]))
        if input(ui.yellow("  Allow them? [y/N] ")).strip().lower() in ("y", "yes"):
            agent.ext.approve_hooks(pending["file"])


def repl(agent: Agent) -> None:
    import time
    from . import terminal
    for note in terminal.setup_keys(agent):  # also turns on arrow keys and history for input()
        ui.warn(note)
    if terminal.notifications_on(agent):
        agent.display.alert = terminal.notify
    agent.on_background_done = lambda: print(ui.dim("\n· a background helper finished; its report goes with your next message"))
    approve_project_hooks(agent)
    print(ui.bold(f"Docks {__version__}") + ui.dim(f"  {agent.model} · {agent.root} · mode: {agent.active_mode}"))
    print(ui.dim("Tell me what to build. /help for commands.\n"))
    try:
        while True:
            line = terminal.status_line(agent)
            if line:
                print(line)
            try:
                text = read_prompt()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not text:
                continue
            if text.startswith("#") and not text.startswith("#!"):
                save_note(agent, text)
                continue
            if text.startswith("/"):
                try:
                    if slash(agent, text):
                        continue
                except EOFError:
                    return
                if not agent.ext.find_command(text.split()[0][1:]):
                    ui.error(f"unknown command {text.split()[0]} (see /help)")
                    continue
            started = time.monotonic()
            agent.run(text)
            if time.monotonic() - started > terminal.LONG_TASK and terminal.notifications_on(agent):
                terminal.notify("finished: " + text.splitlines()[0][:80])
            print()
    finally:
        agent.end_session("exit")


def save_note(agent: Agent, text: str) -> None:
    """'# use pnpm, not npm' -> a line in an instruction file, used from now on."""
    from . import instructions
    note = text.lstrip("#").strip()
    if not note:
        return
    try:
        where = input(ui.yellow(f"  Remember for [p]roject ({instructions.note_path(agent.root, 'project').name}, "
                                f"shared), [l]ocal (just you, this project), or [u]ser (all projects)? ")).strip().lower()
    except EOFError:
        return
    scope = {"l": "local", "local": "local", "u": "user", "user": "user"}.get(where, "project")
    path = instructions.add_note(agent.root, note, scope)
    agent.reload_instructions()
    print(ui.dim(f"  remembered in {path}"))


def print_context(agent: Agent) -> None:
    report = agent.context_report()
    window, measured = report["window"], report["measured"]
    total = measured or report["estimated"]
    print(ui.bold("Context") + ui.dim(f"  {total:,} tokens" + (f" of {window:,} ({total / window:.0%})" if window else "")
                                     + ("" if measured else " (estimated: no request sent yet)")))
    width = 40
    for name, n in sorted(report["parts"].items(), key=lambda kv: -kv[1]):
        if n <= 0:
            continue
        share = n / max(report["estimated"], 1)
        print(f"  {name:<30} {'█' * max(1, round(share * width)):<{width}} {ui.dim(f'~{n:,}')}")
    print(ui.dim("Long sessions are summarized automatically; /compact does it now, /clear starts over."))


def plugin_main(argv) -> int:
    from . import plugins
    parser = argparse.ArgumentParser(prog="docks plugin", description="Install and manage plugins "
                                     "(Claude Code plugin format: commands, agents, skills, hooks, MCP servers).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    inst = sub.add_parser("install", help="install from owner/repo, a git URL or a local folder")
    inst.add_argument("source")
    inst.add_argument("--plugin", help="from a repo with several plugins, install only this one")
    sub.add_parser("list", help="show installed plugins")
    for name in ("remove", "enable", "disable"):
        sub.add_parser(name).add_argument("name")
    args = parser.parse_args(argv)
    if args.cmd == "install":
        print(ui.dim(f"installing from {args.source}…"))
        try:
            names = plugins.install(args.source, args.plugin)
        except ValueError as e:
            ui.error(str(e))
            return 1
        print(ui.green(f"installed: {', '.join(names)}"))
        print(ui.dim("Plugins can run commands (hooks) on your machine; only install ones you trust."))
        return 0
    if args.cmd == "list":
        items = plugins.installed_plugins()
        if not items:
            print(ui.dim("no plugins yet; try: docks plugin install anthropics/claude-code --plugin commit-commands"))
        for p_ in items:
            state = ui.green("enabled") if p_["enabled"] else ui.yellow("disabled")
            print(f"{ui.bold(p_['name'])} {ui.dim(p_['version'])} [{state}]  {ui.dim(p_['description'][:90])}")
        return 0
    if args.cmd == "remove":
        ok = plugins.remove(args.name)
        print(f"removed {args.name}" if ok else f"no plugin named {args.name}")
        return 0 if ok else 1
    plugins.set_enabled(args.name, args.cmd == "enable")
    print(f"{args.name} {args.cmd}d")
    return 0


def sessions_main(argv) -> int:
    parser = argparse.ArgumentParser(prog="docks sessions", description="List saved conversations.")
    parser.add_argument("-C", "--dir", default=".")
    parser.add_argument("--all", action="store_true", help="every project, not just this one")
    args = parser.parse_args(argv)
    import time as _time
    from . import sessions
    root = Path(args.dir).expanduser().resolve()
    items = sessions.list_sessions(None if args.all else root)
    if not items:
        print(ui.dim("no saved conversations yet"))
    for s_ in items:
        when = _time.strftime("%b %d %H:%M", _time.localtime(s_["updated"]))
        where = f" · {s_['root']}" if args.all else ""
        print(f"{ui.bold(s_['name'][:60])}  {ui.dim(when + ' · ' + str(s_['turns']) + ' msgs · ' + s_['id'] + where)}")
    return 0


def _split_rules(text: str) -> list[str]:
    """'Bash(git diff:*) Edit,Read' -> each rule (spaces inside parentheses stay)."""
    rules, depth, current = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch in " ," and depth == 0:
            if current.strip():
                rules.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        rules.append(current.strip())
    return rules


WORKTREE_HELP = "work in a git worktree of its own (a separate copy on branch docks/NAME); no NAME picks one"


def use_worktree(root: Path, name: str | None) -> Path:
    """The folder to work in: root itself, or the named worktree (created if needed)."""
    if name is None:
        return root
    from .worktrees import WorktreeError, create
    try:
        path = create(root, name)
    except WorktreeError as e:
        ui.error(str(e))
        raise SystemExit(1)
    print(ui.dim(f"worktree: {path}  (branch docks/{path.name}; merge it later with: docks worktree merge {path.name})"))
    return path


def models_main(argv) -> int:
    from . import models
    parser = argparse.ArgumentParser(prog="docks models", description="The models Docks uses for each short name.")
    parser.add_argument("cmd", nargs="?", choices=["list", "update"], default="list",
                        help="list (default), or update: switch each name to the newest model you have access to")
    args = parser.parse_args(argv)
    if args.cmd == "update":
        print(ui.dim("asking Anthropic and OpenAI which models are available…"))
        changes, notes = models.update()
        checked = not any(n.startswith("no provider could be checked") for n in notes)
        if changes:
            print(ui.green(models.describe_changes(changes)))
        elif checked:
            print(ui.dim("already on the newest models"))
        for note in notes:
            print(ui.dim(f"  ({note})"))
    for c in models.choices():
        pinned = os.environ.get(models._env_name(c["alias"]))
        print(f"  {c['alias']:<8} {c['label']:<38} {ui.dim(('pinned by ' + models._env_name(c['alias'])) if pinned else c['note'])}")
    return 0


def start_model_updates(agent, notify) -> None:
    """Check for newer models once a day in the background; tell the person if a short name moved."""
    from . import models
    models.update_in_background(agent.ext.settings, lambda changes: notify(
        "newer models found: " + models.describe_changes(changes) + " (used from your next session or /model)"),
        agent.claude_client if models.is_direct_anthropic(agent.claude_client) else None)


def worktree_main(argv) -> int:
    from .worktrees import WorktreeError, create, list_worktrees, merge, remove
    parser = argparse.ArgumentParser(prog="docks worktree", description="Parallel tasks in separate git worktrees.")
    parser.add_argument("-C", "--dir", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="worktrees and what's in them")
    for name, text in (("new", "create one"), ("merge", "merge its branch into your current branch"),
                       ("remove", "delete it"), ("path", "print its folder")):
        p = sub.add_parser(name, help=text)
        p.add_argument("name", nargs="?" if name == "new" else None, default="")
        if name == "remove":
            p.add_argument("--force", action="store_true", help="also throw away uncommitted or unmerged work")
    args = parser.parse_args(argv)
    root = Path(args.dir).expanduser().resolve()
    try:
        if args.cmd == "list":
            trees = list_worktrees(root)
            if not trees:
                print(ui.dim("no worktrees yet; start one with: docks -w NAME"))
            for t in trees:
                print(f"{ui.bold(t['name']):<28} {ui.dim(t['branch'])}  "
                      f"{t['commits_ahead']} commit(s) ahead · {t['changed_files']} uncommitted file(s)")
        elif args.cmd == "new":
            print(create(root, args.name))
        elif args.cmd == "path":
            from .worktrees import path_of, repo_root
            print(path_of(repo_root(root), args.name))
        elif args.cmd == "merge":
            print(ui.green(merge(root, args.name)))
        elif args.cmd == "remove":
            print(remove(root, args.name, args.force))
    except WorktreeError as e:
        ui.error(str(e))
        return 1
    return 0


def web_main(argv) -> int:
    parser = argparse.ArgumentParser(prog="docks web", description="Use Docks from your browser.")
    parser.add_argument("-C", "--dir", default=".", help="project directory to work in")
    parser.add_argument("-m", "--model", default=os.environ.get("DOCKS_MODEL", "opus"),
                        help="opus (default), fable, sonnet, haiku, codex, chatgpt, or a model ID")
    parser.add_argument("-e", "--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("-y", "--yolo", action="store_true", help="run tools without asking for approval")
    parser.add_argument("--host", default="127.0.0.1", help="interface to listen on (default: this machine only)")
    parser.add_argument("--port", type=int, default=8788, help="app port; the preview uses the next one")
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    parser.add_argument("-w", "--worktree", nargs="?", const="", metavar="NAME", help=WORKTREE_HELP)
    args = parser.parse_args(argv)
    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")
    root = use_worktree(root, args.worktree)
    from .web.server import serve
    from .mcp import MCPManager
    from .plugins import Extensions
    ext = Extensions.load(root)
    mgr = MCPManager(root, ext.plugin_mcp)
    mgr.start()  # project servers wait for approval in the browser
    agent = Agent(root=root, model=args.model, effort=args.effort, auto_approve=args.yolo, mcp=mgr, ext=ext, save=True,
                  mode=mode_from_settings(ext))
    start_model_updates(agent, lambda text: print(ui.dim(text)))
    serve(agent, host=args.host, port=args.port, open_browser=not args.no_open)
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
    parser.add_argument("-m", "--model", default=os.environ.get("DOCKS_MODEL", "opus"),
                        help="opus (default), fable, sonnet, haiku, codex, chatgpt, or a model ID")
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
    if argv[:1] in (["plugin"], ["plugins"]):
        return plugin_main(argv[1:])
    if argv[:1] == ["sessions"]:
        return sessions_main(argv[1:])
    if argv[:1] == ["models"]:
        return models_main(argv[1:])
    if argv[:1] == ["doctor"]:
        from . import doctor
        from .plugins import Extensions
        root = Path(argv[2] if argv[1:2] == ["-C"] and len(argv) > 2 else ".").resolve()
        from .mcp import MCPManager
        mgr = MCPManager(root, Extensions.load(root).plugin_mcp)
        mgr.start()
        results = doctor.check(root, mcp=mgr)
        print(doctor.report(results))
        return 1 if any(r[0] == doctor.FAIL for r in results) else 0
    if argv[:1] in (["worktree"], ["worktrees"]):
        return worktree_main(argv[1:])
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
    parser.add_argument("-m", "--model", default=os.environ.get("DOCKS_MODEL", "opus"),
                        help="opus (default), fable, sonnet, haiku, codex, chatgpt, or a model ID")
    parser.add_argument("-e", "--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("-y", "--yolo", action="store_true", help="run tools without asking for approval")
    parser.add_argument("-i", "--image", action="append", default=[],
                        help="attach an image (screenshot, mockup, design) to the task; repeatable")
    parser.add_argument("--mode", choices=["ask", "auto", "plan", "yolo"], default=None,
                        help="ask: confirm each change (default) · auto: confirm only risky ones · "
                             "plan: plan first · yolo: never ask")
    parser.add_argument("--plan", action="store_true", help="start in plan mode")
    parser.add_argument("-w", "--worktree", nargs="?", const="", metavar="NAME", help=WORKTREE_HELP)
    parser.add_argument("--sandbox", action="store_true",
                        help="run shell commands in a sandbox: writes only inside the project, secrets hidden")
    parser.add_argument("-r", "--resume", nargs="?", const="", metavar="NAME_OR_ID",
                        help="continue a saved conversation (no value: list them)")
    parser.add_argument("-c", "--continue", dest="cont", action="store_true",
                        help="continue the most recent conversation in this project")
    parser.add_argument("-p", "--print", action="store_true",
                        help="script mode: run the task with nobody to ask, print only the answer, exit")
    parser.add_argument("--output-format", choices=["text", "json", "stream-json"], default="text",
                        help="with -p: text (just the answer), json (one result object), stream-json (events, one per line)")
    parser.add_argument("--allow", "--allowedTools", dest="allow", action="append", default=[], metavar="RULE",
                        help="permission rule to allow without asking, e.g. 'Bash(npm test:*)' or Edit; repeatable")
    parser.add_argument("--deny", "--disallowedTools", dest="deny", action="append", default=[], metavar="RULE",
                        help="permission rule to always refuse; repeatable")
    parser.add_argument("--version", action="version", version=f"docks {__version__}")
    args = parser.parse_args(argv)
    script_out = None
    if args.print:  # keep stdout for the answer alone; setup messages go to stderr
        script_out, sys.stdout = sys.stdout, sys.stderr

    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")
    root = use_worktree(root, args.worktree)

    from . import sessions
    from .plugins import Extensions
    ext = Extensions.load(root)
    for kind in ("allow", "deny"):  # rules from the command line, for this run only
        ext.permissions.add(kind, [r for arg in getattr(args, kind) for r in _split_rules(arg)], root)
    agent = Agent(root=root, model=args.model, effort=args.effort, auto_approve=args.yolo, ext=ext, save=True,
                  mode="plan" if args.plan else args.mode or mode_from_settings(ext),
                  mcp=start_mcp(root, sys.stdin.isatty() and not args.print, ext.plugin_mcp))
    if not args.print:
        start_model_updates(agent, lambda text: print(ui.dim(f"\n· {text}")))
    if args.sandbox and agent.sandbox is None:
        from .sandbox import SandboxUnavailable
        try:
            print(ui.dim(agent.set_sandbox(True)))
        except SandboxUnavailable as e:
            ui.error(str(e))
            return 1
    if args.resume == "" and not args.cont:
        _print_sessions(agent)
        print(ui.dim("resume one with: docks --resume <name or id>"))
        return 0
    if args.resume or args.cont:
        recent = sessions.list_sessions(root, limit=1)
        sid = (sessions.find(args.resume, root) or sessions.find(args.resume)) if args.resume else \
            (recent[0]["id"] if recent else None)
        if not sid:
            ui.error("no saved conversation to continue" if args.cont else f"no saved conversation matches {args.resume!r}")
            return 1
        data = agent.resume(sid)
        print(ui.dim(f"resumed: {data.get('name') or data.get('title') or sid}"))
    if args.print:
        from . import script
        text = " ".join(args.prompt)
        piped = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
        if piped:
            text = f"{text}\n\n<stdin>\n{piped}\n</stdin>" if text else piped
        if not text:
            ui.error("give a task: docks -p \"...\" (or pipe one in)")
            return 2
        prompt = [*map(image_block, args.image), {"type": "text", "text": text}] if args.image else text
        return script.run(agent, prompt, args.output_format, out=script_out)
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
