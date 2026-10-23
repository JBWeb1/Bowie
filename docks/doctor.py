"""`bowers doctor` / `/doctor`: check the setup and say how to fix what's wrong."""

import importlib.metadata
import json
import os
import shutil
import sys
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def check(root: Path, ext=None, mcp=None, agent=None, online: bool = True) -> list[tuple[str, str, str]]:
    """(status, what, detail) for each check."""
    from . import lsp, sandbox
    from .plugins import Extensions, claude_home, docks_home
    ext = ext or Extensions.load(root)
    out = []

    py = sys.version_info
    out.append((OK if py >= (3, 10) else FAIL, "Python", f"{py.major}.{py.minor}.{py.micro}"
                + ("" if py >= (3, 10) else " (Bowers needs 3.10 or newer)")))
    sdk = _version("anthropic")
    out.append((OK if sdk else FAIL, "Anthropic SDK", sdk or "not installed: pip install anthropic"))

    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base = os.environ.get("ANTHROPIC_BASE_URL")
    if not key and not base:
        out.append((FAIL, "API key", "ANTHROPIC_API_KEY isn't set; get a key at https://console.anthropic.com"))
    elif online:
        try:
            import anthropic
            client = agent.client if agent is not None and agent.client is not None else anthropic.Anthropic()
            model = agent.model if agent is not None else "claude-opus-5-5"
            info = client.models.retrieve(model)
            window = getattr(info, "max_input_tokens", None)
            out.append((OK, "API key", f"works{' (via ' + base + ')' if base else ''}; {model}"
                                       + (f" has a {window:,} token window" if window else "")))
        except TypeError:  # the SDK found no credentials at all
            out.append((FAIL, "API key", "no API key found: set ANTHROPIC_API_KEY (get one at https://console.anthropic.com)"))
        except Exception as e:
            name = type(e).__name__
            hint = "the key was rejected" if "Authentication" in name else "couldn't reach the API"
            first = next((l.strip() for l in str(e).splitlines() if l.strip()), "")
            out.append((FAIL, "API key", f"{hint} ({name}: {first[:120]})"))
    else:
        out.append((OK, "API key", "set (not tested)"))

    from . import models
    problem = models.check_openai("codex")
    out.append((WARN if problem else OK, "Codex / ChatGPT", problem or
                f"ready ({models.current('codex')} and {models.current('chatgpt')} through Bowers Router)"))

    for tool, why in (("git", "undo, worktrees, GitHub features"), ("node", "JavaScript projects"),
                      ("rg", "faster search (optional)")):
        found = shutil.which(tool)
        out.append((OK if found else WARN, tool, found or f"not found; needed for {why}"))

    if _version("playwright"):
        from .browser import _executables
        detail = "Playwright installed" + ("" if _executables() else "; if the browser won't start: playwright install chromium")
        out.append((OK, "Browser tool", detail))
    else:
        out.append((WARN, "Browser tool", "off: pip install playwright && playwright install chromium (lets Claude test the UI it builds)"))

    servers = lsp.LSPManager(root, ext.lsp_servers).specs
    if servers:
        out.append((OK, "Code intelligence", ", ".join(f"{s.command[0]} ({' '.join(sorted(s.extensions))})" for s in servers)))
    else:
        out.append((WARN, "Code intelligence", "no language servers found; e.g. npm i -g pyright typescript-language-server typescript"))

    engine = sandbox.engine()
    wanted = isinstance(ext.settings.get("sandbox"), dict) and ext.settings["sandbox"].get("enabled")
    out.append((OK if engine else (FAIL if wanted else WARN), "Sandbox",
                f"available ({engine})" + (", on in settings" if wanted else "") if engine else sandbox.unavailable_reason()))

    for path in (claude_home() / "settings.json", docks_home() / "settings.json", root / ".claude" / "settings.json",
                 root / ".claude" / "settings.local.json", root / ".docks" / "settings.json",
                 docks_home() / "keybindings.json"):
        if path.is_file():
            try:
                json.loads(path.read_text())
            except json.JSONDecodeError as e:
                out.append((FAIL, "Settings", f"{path} isn't valid JSON: {e}"))
    for pending in ext.pending_hooks:
        out.append((WARN, "Needs approval", f"{pending['file']} (start Bowers in a terminal, or approve it in the browser)"))
    if ext.plugins:
        out.append((OK, "Plugins", ", ".join(ext.plugins)))

    if mcp is not None:
        for server in mcp.servers.values():
            status = {"running": OK, "needs-approval": WARN}.get(server.status, FAIL)
            detail = f"{len(server.tools)} tools" if server.status == "running" else (server.error or server.status)
            out.append((status, f"MCP {server.name}", detail))

    home = docks_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".doctor"
        probe.write_text("ok")
        probe.unlink()
        out.append((OK, "Bowers home", str(home)))
    except OSError as e:
        out.append((FAIL, "Bowers home", f"can't write to {home}: {e}"))
    return out


def report(results: list[tuple[str, str, str]]) -> str:
    from . import ui
    marks = {OK: ui.green("✓"), WARN: ui.yellow("!"), FAIL: ui.red("✗")}
    lines = [f"  {marks[s]} {ui.bold(what):<30} {detail}" for s, what, detail in results]
    fails = sum(1 for s, _, _ in results if s == FAIL)
    warns = sum(1 for s, _, _ in results if s == WARN)
    lines.append("")
    lines.append(ui.green("Everything needed is working.") if not fails else ui.red(f"{fails} problem(s) to fix."))
    if warns:
        lines.append(ui.dim(f"{warns} optional thing(s) are off; they make Bowers better but aren't required."))
    return "\n".join(lines)
