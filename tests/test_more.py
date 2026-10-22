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
