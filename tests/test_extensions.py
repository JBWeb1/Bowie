"""Sessions, slash commands, plugins, hooks, skills, custom agents, modes, questions, background
helpers, retries and @mentions."""

import json
import sys
import threading
import time
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest

from docks import automode, plugins, sessions
from docks.agent import Agent
from docks.plugins import Extensions
from tests.test_docks import FakeClient, msg, tool_use


@pytest.fixture(autouse=True)
def homes(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path_factory.mktemp("docks-home")))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path_factory.mktemp("claude-home")))


class Display:
    """Records what the agent shows; answers questions and plan reviews as configured."""

    def __init__(self, answers=None, plan_decision=("approve", ""), confirm="yes"):
        self.events, self.answers, self.plan_decision, self.confirm_answer = [], answers, plan_decision, confirm

    def stream(self):
        return NS(handle=lambda e: None, finish=lambda: None)

    def __getattr__(self, name):
        return lambda *a, **k: self.events.append((name, a, k))

    def confirm(self, name, args):
        self.events.append(("confirm", (name,), {}))
        return self.confirm_answer

    def ask(self, questions):
        self.events.append(("ask", (questions,), {}))
        return self.answers

    def review_plan(self, plan):
        self.events.append(("review_plan", (plan,), {}))
        return self.plan_decision

    def names(self):
        return [e[0] for e in self.events]


def text(s):
    return NS(type="text", text=s)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------- sessions


def test_sessions_save_resume_and_continue(tmp_path):
    client = FakeClient([msg("tool_use", tool_use("t1", "write_file", path="a.txt", content="1")), msg("end_turn", text("Made a.txt"))])
    agent = Agent(root=tmp_path, client=client, auto_approve=True, save=True)
    agent.run("make a")
    agent.rename("first try")
    sid = agent.session_id
    listed = sessions.list_sessions(tmp_path)
    assert listed[0]["id"] == sid and listed[0]["name"] == "first try" and listed[0]["turns"] == 1
    assert sessions.find("first try", tmp_path) == sid and sessions.find(sid[:10], tmp_path) == sid

    client2 = FakeClient([msg("end_turn", text("Continuing."))])
    again = Agent(root=tmp_path, client=client2, save=True)
    again.resume(sid)
    assert again.last_text() == "Made a.txt"
    again.run("keep going")
    sent = client2.requests[0]["messages"]
    assert len(sent) == 5 and sent[1]["content"][0]["name"] == "write_file"  # history went back to the API as plain JSON
    json.dumps(sent)  # and it's serializable


# ---------------------------------------------------------------- commands and @mentions


def test_commands_arguments_inline_shell_and_project_safety(tmp_path, monkeypatch):
    write(plugins.docks_home() / "commands" / "greet.md",
          "---\ndescription: Say hi\nargument-hint: <name>\n---\nGreet $ARGUMENTS. Today: !`echo SHELL_RAN`")
    write(tmp_path / ".claude" / "commands" / "deploy" / "check.md", "Check $1 then $2. !`echo SHOULD_NOT_RUN`")
    ext = Extensions.load(tmp_path)
    assert {"greet", "deploy:check", "review", "feature", "commit"} <= set(ext.commands)
    body, cmd = ext.expand("/greet Ada Lovelace")
    assert body == "Greet Ada Lovelace. Today: SHELL_RAN" and cmd.source == "user"
    body, cmd = ext.expand("/deploy:check api web")
    assert body.startswith("Check api then web.") and "SHOULD_NOT_RUN" in body and "!`" in body  # project: not executed
    assert ext.expand("/nope") is None and ext.expand("not a command") is None

    client = FakeClient([msg("end_turn", text("hi"))])
    display = Display()
    Agent(root=tmp_path, client=client, ext=ext, display=display).run("/greet Bob")
    assert client.requests[0]["messages"][0]["content"] == "Greet Bob. Today: SHELL_RAN"
    assert ("notice", ("Running /greet",), {}) in display.events


def test_at_mentions_attach_files(tmp_path):
    write(tmp_path / "src" / "app.py", "print('app')\n")
    client = FakeClient([msg("end_turn", text("ok"))])
    Agent(root=tmp_path, client=client).run("explain @src/app.py and @src please, not @missing.py")
    content = client.requests[0]["messages"][0]["content"]
    assert content[0]["text"].startswith("explain")
    assert '<file path="src/app.py">\nprint(\'app\')' in content[1]["text"]
    assert content[2]["text"].startswith('<folder path="src">') and len(content) == 3


# ---------------------------------------------------------------- plugins, hooks, skills, agents


def make_plugin(folder):
    write(folder / ".claude-plugin" / "plugin.json", json.dumps({"name": "toolkit", "version": "1.2.0", "description": "Test kit"}))
    write(folder / "commands" / "hello.md", "---\ndescription: Hello\n---\nSay hello from ${CLAUDE_PLUGIN_ROOT}")
    write(folder / "agents" / "reviewer.md", "---\nname: reviewer\ndescription: Reviews code\ntools: Read, Grep\nmodel: haiku\n---\nYou review code strictly.")
    write(folder / "skills" / "styling" / "SKILL.md", "---\nname: styling\ndescription: How to style pages\n---\nUse a 4px grid.")
    write(folder / "skills" / "styling" / "palette.md", "colors")
    write(folder / "hooks" / "block.py", "import json,sys\nd=json.load(sys.stdin)\n"
          "if 'rm ' in d['tool_input'].get('command',''):\n  print('no deleting', file=sys.stderr); sys.exit(2)\n")
    write(folder / "hooks" / "hooks.json", json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": f"{sys.executable} ${{CLAUDE_PLUGIN_ROOT}}/hooks/block.py"}]}]}}))
    write(folder / ".mcp.json", json.dumps({"mcpServers": {"db": {"command": "${CLAUDE_PLUGIN_ROOT}/db-server"}}}))


def test_install_plugin_and_use_everything_it_ships(tmp_path):
    source = tmp_path / "market"
    make_plugin(source / "plugins" / "toolkit")
    assert plugins.install(str(source)) == ["toolkit"]
    assert plugins.installed_plugins()[0]["version"] == "1.2.0"
    project = tmp_path / "project"
    project.mkdir()
    ext = Extensions.load(project)
    installed = plugins.plugins_dir() / "toolkit"
    assert ext.expand("/toolkit:hello")[0] == f"Say hello from {installed}"
    assert ext.expand("/hello")[0] == f"Say hello from {installed}"  # short name works when unique
    assert ext.agents["reviewer"].tools == ["Read", "Grep"] and ext.agents["reviewer"].model == "claude-haiku-5-5"
    assert "Use a 4px grid." in ext.skills["styling"].load() and "palette.md" in ext.skills["styling"].load()
    assert ext.plugin_mcp == {"toolkit-db": {"command": f"{installed}/db-server"}}

    # The hook blocks destructive commands; other commands run.
    client = FakeClient([msg("tool_use", tool_use("t1", "bash", command="rm -rf build"),
                             tool_use("t2", "bash", command="echo safe")), msg("end_turn", text("done"))])
    agent = Agent(root=project, client=client, ext=ext, auto_approve=True)
    assert "styling: How to style pages" in agent.system and "reviewer: Reviews code" in agent.system
    agent.run("clean up")
    results = agent.messages[2]["content"]
    assert results[0]["is_error"] and "no deleting" in results[0]["content"]
    assert "safe" in results[1]["content"]

    plugins.set_enabled("toolkit", False)
    assert "toolkit:hello" not in Extensions.load(project).commands
    assert plugins.remove("toolkit") and not plugins.installed_plugins()


def test_project_hooks_need_approval_and_hook_outputs(tmp_path):
    log = tmp_path / "hook.log"
    hooks = {"hooks": {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo 'Team rule: use tabs'"}]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": "echo 'Branch: main'"}]}],
        "PreToolUse": [{"matcher": "Write|Edit", "hooks": [{"type": "command", "command":
            "echo '{\"hookSpecificOutput\": {\"permissionDecision\": \"allow\"}}'"}]}],
        "PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command":
            f"cat > {log}; echo '{{\"decision\": \"block\", \"reason\": \"run the formatter\"}}'"}]}],
        "Stop": [{"hooks": [{"type": "command", "command":
            f"test -f {tmp_path}/done || (touch {tmp_path}/done; echo 'tests not run yet' >&2; exit 2)"}]}],
    }}
    write(tmp_path / ".claude" / "settings.json", json.dumps(hooks))
    ext = Extensions.load(tmp_path)
    assert ext.hooks == [] and len(ext.pending_hooks) == 1  # a cloned repo's hooks don't run on their own
    ext.approve_hooks(ext.pending_hooks[0]["file"])
    assert len(ext.hooks) == 5 and len(Extensions.load(tmp_path).hooks) == 5  # approval is remembered

    client = FakeClient([msg("tool_use", tool_use("t1", "write_file", path="x.py", content="x=1\n")),
                         msg("end_turn", text("first stop")), msg("end_turn", text("really done"))])
    display = Display(confirm="no")  # would refuse, but the PreToolUse hook allows the write
    agent = Agent(root=tmp_path, client=client, ext=ext, display=display)
    agent.run("make x")
    first = client.requests[0]["messages"][0]["content"]
    assert "Branch: main" in first[1]["text"] and "Team rule: use tabs" in first[2]["text"]
    assert (tmp_path / "x.py").exists() and "confirm" not in display.names()
    assert "[hook feedback]\nrun the formatter" in agent.messages[2]["content"][0]["content"]
    assert json.loads(log.read_text())["tool_input"]["file_path"] == "x.py"  # Claude Code's field names
    assert "tests not run yet" in client.requests[2]["messages"][-1]["content"]  # the Stop hook kept it going
    assert agent.last_text() == "really done"


def test_custom_agent_type_for_helpers(tmp_path):
    write(plugins.docks_home() / "agents" / "explorer.md", "---\nname: explorer\ndescription: Maps code\ntools: Read, Glob, Grep\n---\nYou map codebases.")
    seen = {}

    class Client(FakeClient):
        def __init__(self):
            super().__init__([])
            self.beta = NS(messages=NS(stream=self.route))

        def route(self, **kw):
            if "You map codebases." in kw["system"]:
                seen["tools"] = sorted(t["name"] for t in kw["tools"])
                self.responses = [msg("end_turn", text("Found 3 modules."))]
            elif len(kw["messages"]) == 1:
                self.responses = [msg("tool_use", tool_use("d1", "delegate", description="Map it", prompt="map", agent="explorer"))]
            else:
                self.responses = [msg("end_turn", text("ok"))]
            return self.stream(**kw)

    agent = Agent(root=tmp_path, client=Client())
    agent.run("go")
    assert seen["tools"] == ["glob", "grep", "read_file", "update_plan"]
    assert agent.messages[2]["content"][0]["content"] == "Found 3 modules."


# ---------------------------------------------------------------- modes and questions


def test_plan_mode_blocks_changes_until_the_plan_is_approved(tmp_path):
    client = FakeClient([
        msg("tool_use", tool_use("t1", "write_file", path="a.txt", content="x")),
        msg("tool_use", tool_use("t2", "exit_plan_mode", plan="1. Write a.txt")),
        msg("tool_use", tool_use("t3", "write_file", path="a.txt", content="x")),
        msg("end_turn", text("done")),
    ])
    display = Display(plan_decision=("approve", ""))
    agent = Agent(root=tmp_path, client=client, display=display, mode="plan")
    agent.run("add a file")
    assert "Plan mode is on" in client.requests[0]["messages"][0]["content"][1]["text"]
    assert "Plan mode is on, so nothing can be changed" in agent.messages[2]["content"][0]["content"]
    assert "approved the plan" in agent.messages[4]["content"][0]["content"]
    assert agent.mode == "ask" and (tmp_path / "a.txt").exists()
    assert "confirm" in display.names()  # back in ask mode, the write still asked


def test_rejected_plan_returns_feedback(tmp_path):
    client = FakeClient([msg("tool_use", tool_use("t1", "exit_plan_mode", plan="Do X")), msg("end_turn", text("ok"))])
    agent = Agent(root=tmp_path, client=client, display=Display(plan_decision=("reject", "use Y instead")), mode="plan")
    agent.run("go")
    assert "use Y instead" in agent.messages[2]["content"][0]["content"] and agent.mode == "plan"


def test_ask_user_questions(tmp_path):
    q = [{"question": "Which framework?", "options": [{"label": "React (recommended)"}, {"label": "Vue"}]}]
    client = FakeClient([msg("tool_use", tool_use("t1", "ask_user", questions=q)), msg("end_turn", text("ok"))])
    agent = Agent(root=tmp_path, client=client, display=Display(answers=["Vue"]))
    agent.run("build")
    assert agent.messages[2]["content"][0]["content"] == "Q: Which framework?\nA: Vue"


def test_auto_mode_rules_and_classifier(tmp_path):
    assert automode.rule_verdict("edit_file", {"path": "src/a.py"}, tmp_path)[0] == "allow"
    assert automode.rule_verdict("write_file", {"path": "../outside.txt"}, tmp_path)[0] == "ask"
    assert automode.rule_verdict("bash", {"command": "npm test && git status"}, tmp_path)[0] == "allow"
    assert automode.rule_verdict("bash", {"command": "sudo rm -rf /"}, tmp_path)[0] == "ask"
    assert automode.rule_verdict("bash", {"command": "git push --force"}, tmp_path)[0] == "ask"
    assert automode.rule_verdict("create_pull_request", {}, tmp_path)[0] == "ask"
    assert automode.rule_verdict("bash", {"command": "docker compose up -d"}, tmp_path) is None

    judge = NS(messages=NS(create=lambda **kw: NS(content=[text("ALLOW: starts local containers")])))
    assert automode.classify(judge, "bash", {"command": "docker compose up -d"}, tmp_path) == ("allow", "starts local containers")
    broken = NS(messages=NS(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("down"))))
    assert automode.classify(broken, "bash", {"command": "docker compose up -d"}, tmp_path)[0] == "ask"

    client = FakeClient([msg("tool_use", tool_use("t1", "write_file", path="ok.txt", content="1"),
                             tool_use("t2", "bash", command="rm -rf ~/stuff")), msg("end_turn", text("ok"))])
    display = Display(confirm="no")
    Agent(root=tmp_path, client=client, display=display, mode="auto").run("go")
    assert (tmp_path / "ok.txt").exists()  # auto-approved
    assert display.names().count("confirm") == 1 and "auto_approved" in display.names()  # only the risky one asked


# ---------------------------------------------------------------- background helpers, retries


def test_background_helper_report_arrives_later(tmp_path):
    gate = threading.Event()

    class Client(FakeClient):
        def __init__(self):
            super().__init__([])
            self.beta = NS(messages=NS(stream=self.route))
            self.lead_calls = 0

        def route(self, **kw):
            if "helper agent" in kw["system"]:
                gate.wait(5)
                self.responses = [msg("end_turn", text("Background research done."))]
            else:
                self.lead_calls += 1
                if self.lead_calls == 1:
                    self.responses = [msg("tool_use", tool_use("d1", "delegate", description="Research", prompt="dig", background=True))]
                else:
                    self.responses = [msg("end_turn", text("ok"))]
            return self.stream(**kw)

    client = Client()
    finished = threading.Event()
    agent = Agent(root=tmp_path, client=client, display=Display(), on_background_done=finished.set)
    agent.run("start")
    assert "working in the background" in agent.messages[2]["content"][0]["content"]
    gate.set()
    assert finished.wait(5) and agent.has_background_reports()
    agent.run("what did it find?")
    content = client.requests[-1]["messages"][-1]["content"]
    assert any("Background research done." in b["text"] for b in content if b["type"] == "text")


def test_retries_when_claude_is_busy(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    errors = [anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request, headers={"retry-after": "0"}), body=None),
              anthropic.OverloadedError("busy", response=httpx2.Response(529, request=request, headers={"retry-after": "0"}), body=None)]
    client = FakeClient([msg("end_turn", text("finally"))])
    real = client.stream

    def flaky(**kw):
        if errors:
            raise errors.pop(0)
        return real(**kw)
    client.beta = NS(messages=NS(stream=flaky))
    display = Display()
    agent = Agent(root=tmp_path, client=client, display=display)
    agent.run("hi")
    assert agent.last_text() == "finally"
    notes = [e[1][0] for e in display.events if e[0] == "notice"]
    assert any("rate limit" in n for n in notes) and any("busy" in n for n in notes)
