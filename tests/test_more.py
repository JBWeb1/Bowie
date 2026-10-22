"""Permission rules, sandboxing, the browser, code intelligence, worktrees, script mode, memory, output
styles, the status line and the other Claude Code-style extras."""

import json

from docks.agent import Agent, mode_from_settings
from docks.plugins import Extensions
from tests.test_docks import FakeClient, msg, tool_use
from tests.test_extensions import Display, homes, text, write  # noqa: F401  (homes is an autouse fixture)


def run_calls(tmp_path, calls, ext=None, mode="ask", confirm="no"):
    """Run one turn where Claude makes the given tool calls; return (agent, display, results by id)."""
    client = FakeClient([msg("tool_use", *[tool_use(f"t{i}", n, **a) for i, (n, a) in enumerate(calls)]),
                         msg("end_turn", text("done"))])
    display = Display(confirm=confirm)
    agent = Agent(root=tmp_path, client=client, ext=ext or Extensions.load(tmp_path), display=display, mode=mode)
    agent.run("go")
    results = {r["tool_use_id"]: r for r in agent.messages[2]["content"]}
    return agent, display, results


# ---------------------------------------------------------------- permission rules

def test_permission_rules_allow_ask_and_deny(tmp_path):
    write(tmp_path / ".env", "SECRET=1")
    user = {"permissions": {"allow": ["Bash(echo:*)", "Edit(src/**)"], "deny": ["Read(./.env)", "Bash(curl:*)"],
                            "ask": ["Bash(echo ask*)"]}}
    write(tmp_path / "home-settings.json", json.dumps(user))
    ext = Extensions.load(tmp_path)
    ext._load_settings(tmp_path / "home-settings.json", "user")
    agent, display, results = run_calls(tmp_path, [
        ("bash", {"command": "echo hi"}),                     # allowed by a rule: no question
        ("bash", {"command": "echo hi && touch made"}),       # only part of it is allowed: asks (and is refused)
        ("read_file", {"path": ".env"}),                      # denied even though reading never asks
        ("bash", {"command": "ls; curl example.com"}),        # a denied piece blocks the whole command
        ("write_file", {"path": "src/app.py", "content": "x"}),  # Edit(src/**) covers writes
        ("bash", {"command": "echo ask me"}),                 # ask beats allow
    ], ext=ext, mode="ask", confirm="no")
    assert "hi" in results["t0"]["content"] and not results["t0"].get("is_error")
    assert results["t1"]["is_error"] and not (tmp_path / "made").exists()
    assert results["t2"]["is_error"] and "Read(./.env)" in results["t2"]["content"]
    assert results["t3"]["is_error"] and "Bash(curl:*)" in results["t3"]["content"]
    assert (tmp_path / "src" / "app.py").read_text() == "x"
    assert results["t5"]["is_error"]
    asked = [e[1][0] for e in display.events if e[0] == "confirm"]
    assert asked == ["bash", "bash"]  # only the partly-allowed command and the ask rule


def test_ask_rules_ask_even_in_full_auto_and_deny_in_full_auto(tmp_path):
    write(tmp_path / ".claude" / "settings.local.json", json.dumps({"permissions": {"ask": ["Bash(git push:*)"],
                                                                                  "deny": ["Bash(rm:*)"]}}))
    ext = Extensions.load(tmp_path)  # ask/deny rules need no approval: they only take power away
    _, display, results = run_calls(tmp_path, [("bash", {"command": "git push origin main"}),
                                               ("bash", {"command": "rm -rf build"})], ext=ext, mode="yolo")
    assert [e[1][0] for e in display.events if e[0] == "confirm"] == ["bash"]
    assert results["t1"]["is_error"] and "Bash(rm:*)" in results["t1"]["content"]


def test_project_allow_rules_wait_for_approval(tmp_path):
    write(tmp_path / ".claude" / "settings.json", json.dumps({"permissions": {"allow": ["Bash"],
                                                                            "defaultMode": "bypassPermissions"}}))
    ext = Extensions.load(tmp_path)
    assert ext.permissions.allow == [] and ext.permissions.default_mode is None
    assert ext.pending_hooks[0]["name"] == "settings:settings.json"
    ext.approve_hooks(ext.pending_hooks[0]["file"])
    assert [r.text for r in ext.permissions.allow] == ["Bash"] and mode_from_settings(ext) == "yolo"
    assert Extensions.load(tmp_path).permissions.allow  # remembered


def test_always_allow_remembers_a_narrow_rule_and_allow_command_saves_it(tmp_path):
    (tmp_path / ".git" / "info").mkdir(parents=True)
    agent, display, _ = run_calls(tmp_path, [("bash", {"command": "echo one"})], confirm="always")
    assert [r.text for r in agent.ext.permissions.allow] == ["Bash(echo one:*)"]
    assert "bash" not in agent.always_allowed  # not every shell command
    path = agent.ext.save_rule("allow", "Bash(npm test:*)")
    assert json.loads(path.read_text())["permissions"]["allow"] == ["Bash(npm test:*)"]
    assert ".claude/settings.local.json" in (tmp_path / ".git" / "info" / "exclude").read_text()
    assert [r.text for r in Extensions.load(tmp_path).permissions.allow] == ["Bash(npm test:*)"]  # trusted: we wrote it


def test_accept_edits_default_mode(tmp_path):
    write(plugin_home_settings(), json.dumps({"permissions": {"defaultMode": "acceptEdits"}}))
    ext = Extensions.load(tmp_path)
    assert mode_from_settings(ext) == "ask"
    _, display, results = run_calls(tmp_path, [("write_file", {"path": "a.txt", "content": "a"}),
                                               ("bash", {"command": "echo x"})], ext=ext, confirm="no")
    assert (tmp_path / "a.txt").exists() and results["t1"]["is_error"]


def plugin_home_settings():
    from docks.plugins import docks_home
    return docks_home() / "settings.json"


# ---------------------------------------------------------------- sandbox

import os  # noqa: E402

import pytest  # noqa: E402

from docks import sandbox as sandbox_mod  # noqa: E402


@pytest.mark.skipif(sandbox_mod.engine() is None, reason="no bubblewrap / sandbox-exec here")
def test_sandbox_limits_writes_hides_secrets_and_can_cut_network(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_key").write_text("PRIVATE")
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    write(project / ".claude" / "settings.local.json", json.dumps({"sandbox": {"enabled": True, "network": False}}))
    agent, display, results = run_calls(project, [
        ("bash", {"command": "echo ok > inside.txt && cat inside.txt"}),
        ("bash", {"command": f"echo bad > {outside}; touch /usr/docks-sandbox-test"}),
        ("bash", {"command": f"cat {home}/.ssh/id_key; ls {home}/.ssh | wc -l"}),
        ("bash", {"command": "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 53), 2)\" || echo NO-NET"}),
    ], mode="yolo")
    assert agent.sandbox is not None
    assert "ok" in results["t0"]["content"] and (project / "inside.txt").exists()
    assert not outside.exists()  # /tmp inside the sandbox is a private scratch space
    assert "Read-only file system" in results["t1"]["content"] and not os.path.exists("/usr/docks-sandbox-test")
    assert "PRIVATE" not in results["t2"]["content"]
    assert "NO-NET" in results["t3"]["content"]


def test_sandbox_auto_allows_commands_in_auto_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_mod, "engine", lambda: "bwrap")
    write(tmp_path / ".claude" / "settings.local.json", json.dumps({"sandbox": {"enabled": True}}))
    agent = Agent(root=tmp_path, client=FakeClient([]), display=Display(confirm="no"), mode="auto")
    ok, _ = agent._approved("bash", {"command": "some-tool --build"}, "t1", None)
    risky, _ = agent._approved("bash", {"command": "git push --force"}, "t2", None)
    assert ok and not risky


def test_settings_sandbox_that_cannot_run_blocks_work(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_mod, "engine", lambda: None)
    write(tmp_path / ".claude" / "settings.local.json", json.dumps({"sandbox": {"enabled": True}}))
    display = Display()
    agent = Agent(root=tmp_path, client=FakeClient([msg("end_turn", text("hi"))]), display=display)
    agent.run("hello")
    assert agent.messages == [] and any("sandbox" in str(e[1]) for e in display.events if e[0] == "error")


# ---------------------------------------------------------------- browser

from docks import agent as agent_mod  # noqa: E402

PAGE = """<!doctype html><title>Counter</title>
<h1 id="count">0</h1><button onclick="inc()">Add one</button>
<input placeholder="Your name" id="name"><p id="hello"></p>
<script>
function inc() { const c = document.getElementById('count'); c.textContent = +c.textContent + 1; if (+c.textContent === 2) undefinedThing(); }
document.getElementById('name').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('hello').textContent = 'Hi ' + e.target.value; });
</script>"""


@pytest.mark.skipif(not agent_mod.HAS_PLAYWRIGHT, reason="Playwright isn't installed")
def test_browser_tool_drives_a_page_and_reports_errors(tmp_path):
    write(tmp_path / "index.html", PAGE)
    agent, display, results = run_calls(tmp_path, [
        ("browser", {"action": "open", "url": "index.html"}),
        ("browser", {"action": "click", "target": "Add one"}),
        ("browser", {"action": "click", "target": "Add one"}),
        ("browser", {"action": "type", "target": "Your name", "text": "Ada", "submit": True}),
        ("browser", {"action": "read"}),
        ("browser", {"action": "eval", "script": "document.getElementById('count').textContent"}),
        ("browser", {"action": "viewport", "device": "mobile"}),
        ("browser", {"action": "click", "target": "#missing"}),
        ("browser", {"action": "close"}),
    ], confirm="no")  # a local page never needs approval
    def texts(i):
        return " ".join(b["text"] for b in results[f"t{i}"]["content"] if b["type"] == "text")
    def has_image(i):
        return any(b["type"] == "image" for b in results[f"t{i}"]["content"])
    assert "title: 'Counter'" in texts(0) and has_image(0)
    assert "undefinedThing" not in texts(1) and "undefinedThing" in texts(2)  # the error shows up right after it happens
    assert has_image(1)
    assert "Hi Ada" in texts(4) and "Add one" in texts(4) and "#name" in texts(4)
    assert texts(5) == '"2"'
    assert "390x844" in texts(6) and has_image(6)
    assert results["t7"]["is_error"] and "read" in results["t7"]["content"]
    assert "confirm" not in display.names()
    assert any(e[0] == "tool_image" for e in display.events)


def test_browser_asks_before_clicking_on_other_sites(tmp_path):
    agent = Agent(root=tmp_path, client=FakeClient([]), display=Display(confirm="no"))
    agent.browser.url = "https://shop.example.com/cart"
    ok, _ = agent._approved("browser", {"action": "click", "target": "Buy now"}, "t1", None)
    agent.browser.url = "http://localhost:5173/"
    local, _ = agent._approved("browser", {"action": "click", "target": "Buy now"}, "t2", None)
    looking, _ = agent._approved("browser", {"action": "open", "url": "https://example.com"}, "t3", None)
    assert not ok and local and looking


# ---------------------------------------------------------------- code intelligence

import shutil  # noqa: E402


@pytest.mark.skipif(not shutil.which("pyright-langserver"), reason="pyright isn't installed")
def test_code_intel_and_errors_after_edits(tmp_path):
    write(tmp_path / "shapes.py", "def area(w: int, h: int) -> int:\n    return w * h\n")
    write(tmp_path / "main.py", "from shapes import area\n\nprint(area(2, 3))\n")
    agent, _, results = run_calls(tmp_path, [
        ("code_intel", {"action": "references", "path": "shapes.py", "symbol": "area"}),
        ("code_intel", {"action": "definition", "path": "main.py", "symbol": "area", "line": 3}),
        ("edit_file", {"path": "main.py", "old_string": "area(2, 3)", "new_string": "area('2', 3)"}),
        ("code_intel", {"action": "symbols", "path": "nope.py"}),
    ], mode="yolo")
    assert "reference(s)" in results["t0"]["content"] and "main.py:3" in results["t0"]["content"]
    assert results["t1"]["content"].startswith("shapes.py:1:")
    assert "error(s) in this file" in results["t2"]["content"] and "line 3" in results["t2"]["content"]
    assert results["t3"]["is_error"]
    assert any(t["name"] == "code_intel" for t in agent.tools)
    agent.lsp.shutdown()


def test_project_language_servers_need_approval(tmp_path):
    write(tmp_path / ".claude" / "settings.json", json.dumps({"lspServers": {"x": {"command": "sh", "extensionToLanguage": {".x": "x"}}}}))
    ext = Extensions.load(tmp_path)
    assert ext.lsp_servers == {}
    ext.approve_hooks(ext.pending_hooks[0]["file"])
    assert "x" in ext.lsp_servers


# ---------------------------------------------------------------- worktrees

import subprocess  # noqa: E402

from docks import worktrees  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


def test_worktrees_create_list_merge_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t"); monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t"); monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    git(tmp_path, "init", "-q")
    write(tmp_path / "a.txt", "1")
    git(tmp_path, "add", "."); git(tmp_path, "commit", "-qm", "init")
    tree = worktrees.create(tmp_path, "feature x")
    assert tree.name == "feature-x" and (tree / "a.txt").exists()
    assert worktrees.create(tree, "feature x") == tree  # from inside, it finds the same one
    write(tree / "b.txt", "2")
    [info] = worktrees.list_worktrees(tmp_path)
    assert info["changed_files"] == 1 and info["branch"] == "docks/feature-x"
    assert git(tmp_path, "status", "--porcelain") == ""  # the worktree folder stays out of the main checkout
    assert "merged docks/feature-x" in worktrees.merge(tmp_path, "feature-x")
    assert (tmp_path / "b.txt").read_text() == "2"
    assert worktrees.remove(tmp_path, "feature-x") == "removed feature-x"
    assert worktrees.list_worktrees(tmp_path) == []
    with pytest.raises(worktrees.WorktreeError):
        worktrees.merge(tmp_path, "nope")


# ---------------------------------------------------------------- hooks, memory, compact, context, styles

def test_more_hook_events(tmp_path):
    log = tmp_path / "events.log"
    hook = lambda name: [{"hooks": [{"type": "command", "command": f"cat >> {log}; echo >> {log}"}]}]  # noqa: E731
    spec = {e: hook(e) for e in ("Notification", "SessionEnd", "PreCompact")}
    spec["SubagentStop"] = [{"hooks": [{"type": "command", "command":
        f"test -f {tmp_path}/once || (touch {tmp_path}/once; echo 'also list the tests' >&2; exit 2)"}]}]
    write(plugin_home_settings(), json.dumps({"hooks": spec}))
    client = FakeClient([
        msg("tool_use", tool_use("d1", "delegate", description="look", prompt="look around")),
        msg("end_turn", text("helper report")),          # the helper's first answer
        msg("end_turn", text("helper report + tests")),  # after SubagentStop sent it back
        msg("tool_use", tool_use("w1", "write_file", path="a.txt", content="a")),
        msg("end_turn", text("done")),
        msg("end_turn", text("Summary: wrote a.txt")),   # /compact
    ])
    display = Display(confirm="yes")
    agent = Agent(root=tmp_path, client=client, display=display)
    agent.run("go")
    assert "helper report + tests" in agent.messages[2]["content"][0]["content"]
    agent.compact("keep file names")
    agent.reset()
    events = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert [e.get("hook_event_name") or ("message" in e and "Notification") or ("trigger" in e and "PreCompact")
            or ("reason" in e and "SessionEnd") for e in events] == ["Notification", "PreCompact", "SessionEnd"]
    assert "permission" in events[0]["message"] and events[1]["custom_instructions"] == "keep file names"
    assert events[2]["reason"] == "clear"


def test_compact_replaces_history_with_a_summary(tmp_path):
    client = FakeClient([msg("end_turn", text("first answer")), msg("end_turn", text("Summary: user wants a todo app"))])
    agent = Agent(root=tmp_path, client=client, display=Display())
    agent.run("build a todo app")
    summary = agent.compact()
    assert summary == "Summary: user wants a todo app" and len(agent.messages) == 2
    assert "user wants a todo app" in agent.messages[0]["content"]
    asked = client.requests[1]
    assert asked["tool_choice"] == {"type": "none"} and "Summarize" in asked["messages"][-1]["content"]


def test_instruction_files_imports_folders_and_notes(tmp_path, monkeypatch):
    from docks import instructions
    from docks.plugins import docks_home
    write(docks_home() / "DOCKS.md", "Always answer in British English.")
    write(tmp_path / "CLAUDE.md", "Use pnpm.\nSee @docs/style.md for style.\n```\n@ignored.md\n```")
    write(tmp_path / "docs" / "style.md", "Tabs, not spaces.")
    write(tmp_path / "ignored.md", "SHOULD NOT APPEAR")
    write(tmp_path / "api" / "AGENTS.md", "API handlers must validate input.")
    write(tmp_path / "api" / "users.py", "x = 1\n")
    (tmp_path / ".git" / "info").mkdir(parents=True)
    agent, _, results = run_calls(tmp_path, [("read_file", {"path": "api/users.py"}),
                                             ("read_file", {"path": "api/users.py"})])
    assert "British English" in agent.system and "Use pnpm" in agent.system and "Tabs, not spaces" in agent.system
    assert "SHOULD NOT APPEAR" not in agent.system
    assert "validate input" in results["t0"]["content"] and "validate input" not in results["t1"]["content"]
    path = instructions.add_note(tmp_path, "# run tests with pnpm test", "project")
    assert path.name == "CLAUDE.md" and path.read_text().endswith("- run tests with pnpm test\n")
    local = instructions.add_note(tmp_path, "my api key lives in 1password", "local")
    assert local.name == "DOCKS.local.md" and "DOCKS.local.md" in (tmp_path / ".git" / "info" / "exclude").read_text()
    agent.reload_instructions()
    assert "pnpm test" in agent.system and "1password" in agent.system


def test_context_report_and_output_styles(tmp_path):
    agent, _, _ = run_calls(tmp_path, [("bash", {"command": "echo " + "x" * 4000})], mode="yolo")
    report = agent.context_report()
    assert report["parts"]["Tool results"] > 900 and report["measured"] > 0
    assert set(agent.ext.output_styles) >= {"explanatory", "learning", "concise"}
    agent.set_output_style("learning")
    assert "TODO(human)" in agent.system
    with pytest.raises(ValueError):
        agent.set_output_style("nope")
    write(tmp_path / ".claude" / "settings.local.json", json.dumps({"outputStyle": "concise"}))
    assert "Output style (Concise)" in Agent(root=tmp_path, client=FakeClient([]), display=Display()).system


def test_script_mode_refuses_what_needs_approval(tmp_path):
    import io
    from docks import script
    client = FakeClient([msg("tool_use", tool_use("b1", "bash", command="echo ok"), tool_use("b2", "bash", command="rm x")),
                         msg("end_turn", text("finished"))])
    write(plugin_home_settings(), json.dumps({"permissions": {"allow": ["Bash(echo:*)"]}}))
    agent = Agent(root=tmp_path, client=client)
    out = io.StringIO()
    assert script.run(agent, "do it", "stream-json", out=out) == 0
    events = [json.loads(l) for l in out.getvalue().splitlines()]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "init" and kinds[-1] == "result" and "permission_denied" in kinds
    assert events[-1]["result"] == "finished" and events[-1]["denied"][0]["rule"] == "Bash(rm x:*)"
    refused = client.requests[1]["messages"][-1]["content"][1]["content"]
    assert "non-interactive" in refused


def test_status_line_keys_and_notifications(tmp_path):
    import io
    from docks import terminal
    write(tmp_path / ".claude" / "settings.local.json", json.dumps({}))
    agent = Agent(root=tmp_path, client=FakeClient([]), display=Display())
    assert "mode ask" in terminal.status_line(agent)
    agent.ext.settings["statusLine"] = {"type": "command", "command": "python3 -c \"import json,sys; d=json.load(sys.stdin); print('MY', d['mode'], d['model']['id'])\""}
    assert terminal.status_line(agent) == f"MY ask {agent.model}"
    agent.ext.settings["statusLine"] = {"type": "none"}
    assert terminal.status_line(agent) == ""
    assert terminal._key("ctrl+g") == r"\C-g" and terminal._key("alt+r") == r"\er" and terminal._key("shift+tab") == r"\e[Z"
    assert terminal._key("ctrl+enter") is None

    class TTY(io.StringIO):
        def isatty(self):
            return True
    out = TTY()
    terminal.notify("needs you; now", out=out)
    assert out.getvalue().startswith("\x07\x1b]9;Docks: needs you, now\x07")
    quiet = io.StringIO()
    terminal.notify("x", out=quiet)
    assert quiet.getvalue() == ""  # not a terminal: nothing


# ---------------------------------------------------------------- models: Fable and Codex

def test_model_choices_fable_and_codex(tmp_path, monkeypatch):
    from docks import models
    agent = Agent(root=tmp_path, client=FakeClient([]), display=Display(), model="fable")
    assert agent.model == "claude-fable-5-1"
    assert {t["type"] for t in agent.tools if t["name"] in ("web_search", "web_fetch")} == {"web_search_20250305", "web_fetch_20250910"}
    agent.set_model("opus")
    assert {t["type"] for t in agent.tools if t["name"] == "web_search"} == {"web_search_20260209"}

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOCKS_ROUTER_URL", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        agent.set_model("codex")
    assert agent.model == "claude-opus-5-5"

    # A direct Anthropic client switches to the router for Codex, and back for Claude.
    import anthropic
    direct = anthropic.Anthropic(api_key="x")
    router = object()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(models, "router_client", lambda model: router)
    agent = Agent(root=tmp_path, client=direct, display=Display(), model="codex")
    assert agent.client is router and agent.model == "codex"
    assert not any(t["name"] == "web_search" for t in agent.tools)  # no server-side web tools elsewhere
    agent.set_model("sonnet")
    assert agent.client is direct and agent.model == "claude-sonnet-5-5"


def test_router_offers_codex_and_fable_routes(tmp_path, monkeypatch):
    from docks.router.config import load
    monkeypatch.setenv("DOCKS_CODEX_MODEL", "gpt-test-codex")
    cfg = load(tmp_path / "missing.json")
    assert cfg["routes"]["codex"]["targets"][0] == "openai/gpt-test-codex"
    assert cfg["routes"]["fable"]["targets"][0] == "anthropic/claude-fable-5-1"


def test_codex_runs_through_the_in_process_router(tmp_path, monkeypatch):
    """Codex with only an OpenAI key: Docks starts the router itself and talks OpenAI's format to it."""
    import anthropic
    from docks import models
    from docks.router import config
    from tests.test_router import OPENAI_TEXT_STREAM, FakeUpstream
    oai = FakeUpstream("openai")
    oai.replies.append((200, OPENAI_TEXT_STREAM, {}))
    real_load = config.load

    def fake_load(path=None):
        cfg = real_load(tmp_path / "missing.json")
        cfg["providers"] = {"openai": {"type": "openai", "base_url": oai.url + "/v1", "api_key_env": "OPENAI_API_KEY"}}
        cfg["fallback_to_default"] = False
        return cfg
    monkeypatch.setattr(config, "load", fake_load)
    monkeypatch.setattr(models, "_router", {"url": None, "engine": None})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("DOCKS_ROUTER_URL", raising=False)
    agent = Agent(root=tmp_path, client=anthropic.Anthropic(api_key="x"), display=Display(), model="codex")
    agent.run("hello")
    sent = oai.requests[0]["body"]
    assert sent["model"] == models.codex_model() and agent.last_text() == "All done."


def test_models_update_to_the_newest_in_each_family(tmp_path, monkeypatch):
    import datetime
    from types import SimpleNamespace as NS
    from docks import models
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOCKS_FABLE_MODEL", raising=False)
    monkeypatch.setenv("DOCKS_SONNET_MODEL", "claude-sonnet-5-5")  # pinned: never moves
    day = lambda d: datetime.datetime(2026, 1, d, tzinfo=datetime.timezone.utc)  # noqa: E731
    listing = [NS(id="claude-fable-5-1", created_at=day(1)), NS(id="claude-fable-6", created_at=day(9)),
               NS(id="claude-opus-5-5", created_at=day(2)), NS(id="claude-sonnet-6", created_at=day(9)),
               NS(id="claude-mythos-6", created_at=day(20))]
    client = NS(models=NS(list=lambda limit: listing))
    changes, notes = models.update(client)
    assert changes == {"fable": ("claude-fable-5-1", "claude-fable-6")}
    assert models.resolve("fable") == "claude-fable-6" and models.resolve("sonnet") == "claude-sonnet-5-5"
    assert any("OpenAI" in n for n in notes)
    assert models.update_in_background({}, anthropic_client=client) is None  # checked today already
    assert models._family_of_openai("gpt-5.3-codex") == "codex" and models._family_of_openai("gpt-5.5") == "chatgpt"
    assert models._family_of_openai("gpt-5.5-mini") is None and models._family_of_openai("codex-mini-latest") is None
    assert models.resolve("gpt") == "chatgpt" and models.label("chatgpt").startswith("ChatGPT model")


# ---------------------------------------------------------------- GitHub connection, PR watching, context repos

class FakeGitHub:
    """Just enough of the GitHub API for the account, repo, branch and PR features."""

    def __init__(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        self.prs = {7: {"state": "open", "merged": False, "checks": "in_progress", "reviews": [], "comments": 0}}
        self.device_polls = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj, status=200, headers=None):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length", 0)))
                if self.path == "/login/device/code":
                    return self._send({"device_code": "dc", "user_code": "ABCD-1234", "verification_uri": "https://example/device", "interval": 0})
                if self.path == "/login/oauth/access_token":
                    outer.device_polls += 1
                    return self._send({"error": "authorization_pending"} if outer.device_polls < 2 else {"access_token": "gho_device"})

            def do_GET(self):
                auth = self.headers.get("authorization", "")
                if auth not in ("Bearer good", "Bearer gho_device"):
                    return self._send({"message": "Bad credentials"}, 401)
                p = self.path.split("?")[0]
                pr = outer.prs[7]
                routes = {
                    "/user": ({"login": "ada", "name": "Ada", "avatar_url": ""}, {"x-oauth-scopes": "repo, workflow"}),
                    "/user/repos": ([{"full_name": "ada/app", "private": True, "description": "My app", "default_branch": "main",
                                      "pushed_at": "", "language": "Python", "html_url": "https://github.com/ada/app"}], {}),
                    "/repos/ada/app": ({"default_branch": "main"}, {}),
                    "/repos/ada/app/branches": ([{"name": "main", "protected": True}, {"name": "feature"}], {}),
                    "/repos/ada/app/pulls/7": ({"number": 7, "title": "Add login", "user": {"login": "ada"}, "state": pr["state"],
                                                "merged": pr["merged"], "draft": False, "head": {"ref": "feature", "sha": "abc"},
                                                "base": {"ref": "main"}, "html_url": "https://github.com/ada/app/pull/7",
                                                "comments": pr["comments"], "review_comments": 0}, {}),
                    "/repos/ada/app/pulls/7/reviews": (pr["reviews"], {}),
                    "/repos/ada/app/commits/abc/check-runs": ({"check_runs": [{"status": "completed", "conclusion": "success"}]
                                                               if pr["checks"] == "success" else [{"status": "in_progress"}]}, {}),
                    "/repos/ada/app/commits/abc/status": ({"statuses": []}, {}),
                }
                obj, headers = routes.get(p, ({"message": "not found"}, {}))
                self._send(obj, 200 if p in routes else 404, headers)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def test_github_connect_repos_branches_and_watch(tmp_path, monkeypatch):
    import os
    import stat
    from docks import github, pr_watch
    fake = FakeGitHub()
    monkeypatch.setattr(github, "API", fake.url)
    monkeypatch.setattr(github, "WEB", fake.url)
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(github.shutil, "which", lambda _: None)
    assert github.whoami() is None
    with pytest.raises(github.GitHubError, match="didn't accept"):
        github.save_token("bad")
    info = github.save_token("good")
    assert info["login"] == "ada" and stat.S_IMODE(os.stat(github.account_path()).st_mode) == 0o600
    assert github.whoami()["source"] == "docks" and github.token() == "good"
    assert github.my_repos()[0]["repo"] == "ada/app"
    assert github.branches("ada/app") == {"default": "main", "branches": [{"name": "main", "protected": True},
                                                                         {"name": "feature", "protected": False}]}
    # watching a PR reports what changed
    pr_watch.watch("ada/app", 7)
    assert pr_watch.check_once() == []
    fake.prs[7].update(checks="success", reviews=[{"state": "APPROVED", "user": {"login": "bob"}}], comments=2)
    [update] = pr_watch.check_once()
    assert update["changes"] == ["checks passed on ada/app#7", "ada/app#7: approved", "2 new comments on ada/app#7"]
    fake.prs[7].update(state="closed", merged=True)
    assert pr_watch.check_once()[0]["changes"][0] == "ada/app#7 was merged"
    assert pr_watch.watched() == []  # finished PRs stop being watched
    # signing in through GitHub's device flow
    github.logout()
    monkeypatch.setenv("DOCKS_GITHUB_CLIENT_ID", "client-1")
    flow = github.start_device_login()
    assert flow["user_code"] == "ABCD-1234"
    assert github.poll_device_login(flow) is None
    assert github.poll_device_login(flow)["login"] == "ada" and github.token() == "gho_device"


def test_context_repos_are_read_only_references(tmp_path, monkeypatch):
    from docks import context_repos
    source = tmp_path / "lib"
    source.mkdir()
    git(source, "init", "-q")
    write(source / "README.md", "Shared helpers")
    git(source, "add", ".")
    git(source, "commit", "-qm", "init")
    project = tmp_path / "project"
    project.mkdir()

    def fake_clone(repo, branch, dest):
        git(tmp_path, "clone", "-q", str(source), str(dest))
    monkeypatch.setattr(context_repos, "_clone", fake_clone)
    item = context_repos.add(project, "acme/lib")
    assert item["present"] and (context_repos.folder("acme/lib") / "README.md").exists()
    assert not (project / ".docks").exists()  # the list lives in Docks' own folder
    agent, _, results = run_calls(project, [
        ("read_file", {"path": str(context_repos.folder("acme/lib") / "README.md")}),
        ("write_file", {"path": str(context_repos.folder("acme/lib") / "README.md"), "content": "changed"}),
    ], mode="yolo")
    assert "acme/lib" in agent.system and "Shared helpers" in results["t0"]["content"]
    assert results["t1"]["is_error"] and "Blocked by the permission rule" in results["t1"]["content"]
    assert context_repos.remove(project, "acme/lib") and context_repos.items(project) == []


# ---------------------------------------------------------------- image generation

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a2e40000000049454e44ae426082")


class FakeOpenAIImages:
    def __init__(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import base64
        import threading
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["content-length"]))
                kind = self.headers.get("content-type", "")
                body = json.loads(raw) if kind.startswith("application/json") else {"multipart": raw}
                outer.requests.append({"path": self.path, "body": body, "auth": self.headers.get("authorization")})
                if "bad" in str(body.get("prompt", "")):
                    data, status = {"error": {"message": "Your prompt was rejected"}}, 400
                else:
                    n = int(body.get("n", 1)) if "n" in body else 1
                    data, status = {"data": [{"b64_json": base64.b64encode(PNG).decode()} for _ in range(n)]}, 200
                out = json.dumps(data).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(out)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"


def test_images_generate_edit_gallery_and_tool(tmp_path, monkeypatch):
    from docks import images
    fake = FakeOpenAIImages()
    monkeypatch.setenv("OPENAI_BASE_URL", fake.url)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert not images.available()
    with pytest.raises(images.ImageError, match="OPENAI_API_KEY"):
        images.generate(tmp_path, "a cat")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    made = images.generate(tmp_path, "A cozy coffee shop, watercolor", size="wide", n=2)
    assert [m["path"].startswith("assets/generated/a-cozy-coffee-shop-watercolor") for m in made] == [True, True]
    sent = fake.requests[0]
    assert sent["path"] == "/v1/images/generations" and sent["auth"] == "Bearer sk-test"
    assert sent["body"]["model"] == images.FAST and sent["body"]["size"] == "1536x1024" and sent["body"]["n"] == 2
    assert (tmp_path / made[0]["path"]).read_bytes() == PNG
    edited = images.generate(tmp_path, "make it night", path="public/hero.png", edit=[made[0]["path"]], detailed=True)
    assert edited[0]["path"] == "public/hero.png" and fake.requests[1]["path"] == "/v1/images/edits"
    assert images.DETAILED.encode() in fake.requests[1]["body"]["multipart"] and PNG in fake.requests[1]["body"]["multipart"]
    assert [i["path"] for i in images.gallery(tmp_path)][0] == "public/hero.png"
    images.forget(tmp_path, "public/hero.png", delete_file=True)
    assert not (tmp_path / "public/hero.png").exists() and len(images.gallery(tmp_path)) == 2
    with pytest.raises(images.ImageError, match="rejected"):
        images.generate(tmp_path, "bad idea")

    agent, display, results = run_calls(tmp_path, [("generate_image", {"prompt": "logo for Docks", "path": "logo.png",
                                                                       "background": "transparent"})], confirm="yes")
    blocks = results["t0"]["content"]
    assert blocks[0]["text"].startswith("Saved logo.png") and blocks[1]["type"] == "image"
    assert [e[1][0] for e in display.events if e[0] == "confirm"] == ["generate_image"]  # costs money: it asks
    assert fake.requests[-1]["body"]["background"] == "transparent"
