"""The step-by-step event log, replay and export, and the observer that checks each task's claims."""

import json
from types import SimpleNamespace as NS

from docks import cli, events, observer
from docks.agent import Agent
from tests.test_docks import FakeClient, msg, tool_use
from tests.test_extensions import Display, homes, text, write  # noqa: F401  (homes is an autouse fixture)

CONCERNS = {"summary": "One claim isn't backed up.", "findings": [
    {"kind": "unverified", "text": "The reply says tests pass, but no tests were run.", "action": "Run pytest."},
    {"kind": "remember", "text": "The person prefers tabs.", "action": "Use tabs for indentation."}]}


class ObservedClient(FakeClient):
    """A FakeClient that also answers the observer's separate request."""

    def __init__(self, responses, verdict):
        super().__init__(responses)
        self.verdict, self.observed = verdict, []
        self.messages = NS(create=self.create)

    def create(self, **kwargs):
        self.observed.append(kwargs)
        return NS(content=[NS(type="text", text=self.verdict)])


def build(tmp_path, verdict=json.dumps(CONCERNS), save=True):
    client = ObservedClient([
        msg("tool_use", tool_use("w1", "write_file", path="app.py", content="print('hi')\n")),
        msg("end_turn", text("Done. I wrote app.py and the tests pass.")),
    ], verdict)
    return Agent(root=tmp_path, client=client, display=Display(confirm="yes"), save=save), client


def test_log_and_observer_findings(tmp_path):
    agent, client = build(tmp_path)
    agent.run("write app.py, I prefer tabs")
    log = events.load(agent.session_id)
    assert [e["kind"] for e in log] == ["turn_start", "tool_call", "tool_result", "reply", "turn_end", "observer"]
    assert log[1]["mutating"] and log[2]["ok"] and log[3]["text"].startswith("Done.")
    # the observer saw the request, the reply, the actions and the new file
    sent = client.observed[0]["messages"][0]["content"]
    assert "I prefer tabs" in sent and "tests pass" in sent and "CALL write_file" in sent and "app.py" in sent
    assert [f["kind"] for f in agent.observations] == ["unverified", "remember"]
    assert "observer" in agent.display.names()
    prompt = observer.followup(agent.observations)
    assert "Run pytest" in prompt and "tabs" not in prompt  # notes to remember aren't work to redo


def test_observer_stays_quiet_when_not_needed(tmp_path):
    client = ObservedClient([msg("tool_use", tool_use("r1", "list_files")), msg("end_turn", text("Here they are."))], "{}")
    Agent(root=tmp_path, client=client, display=Display(confirm="yes")).run("what's here?")
    assert client.observed == []  # nothing changed, nothing to check
    agent, client = build(tmp_path / "b", verdict="I can't decide")  # unclear answers are dropped
    (tmp_path / "b").mkdir()
    agent.run("go")
    assert agent.observations == [] and len(client.observed) == 1
    write(tmp_path / "c" / ".docks" / "settings.json", json.dumps({"observer": False}))
    agent, client = build(tmp_path / "c")
    agent.run("go")
    assert client.observed == []


def test_helpers_steps_are_logged_under_their_name(tmp_path):
    client = ObservedClient([
        msg("tool_use", tool_use("d1", "delegate", description="Builder", prompt="write it")),
        msg("tool_use", tool_use("w1", "write_file", path="x.txt", content="x")),  # the helper
        msg("end_turn", text("wrote x.txt")),                                     # the helper's report
        msg("end_turn", text("All done.")),
    ], json.dumps({"summary": "Matches.", "findings": []}))
    agent = Agent(root=tmp_path, client=client, display=Display(confirm="yes"), save=True)
    agent.run("go")
    by = [(e["kind"], e.get("by")) for e in events.load(agent.session_id) if e["kind"].startswith("tool")]
    assert ("tool_call", "Builder") in by and ("tool_call", None) in by
    assert len(client.observed) == 1 and agent.observations == []  # a helper's edit is checked too


def test_export_and_replay(tmp_path, capsys):
    agent, _ = build(tmp_path)
    agent.run("write app.py")
    md = events.export(agent.session_id, "md")
    assert "**You**" in md and "write_file" in md and "Observer: One claim" in md
    page = events.export(agent.session_id, "html")
    assert page.startswith("<!doctype html>") and 'id="play"' in page
    data = json.loads(events.export(agent.session_id, "json"))
    assert data["summary"]["tool_calls"] == 1 and data["summary"]["observer_concerns"] == 2
    out = tmp_path / "log.html"
    assert cli.main(["replay", "-C", str(tmp_path), "--export", "html", "-o", str(out)]) == 0
    assert out.read_text() == page
    assert cli.main(["replay", agent.session_id[:12], "-C", str(tmp_path)]) == 0
    shown = capsys.readouterr().out
    assert "write_file" in shown and "1 action (0 failed)" in shown and "Observer" in shown


def test_web_replay_export_and_fix(tmp_path):
    import urllib.request
    from tests.test_web import call, start, wait_for
    session, url = start(tmp_path, [])
    agent = session.agent
    agent.save = True
    agent.client = agent.claude_client = ObservedClient([
        msg("tool_use", tool_use("w1", "write_file", path="app.py", content="x")),
        msg("end_turn", text("Done, tests pass.")),
        msg("end_turn", text("Ran the tests: 3 passed.")),  # after Fix it
    ], json.dumps(CONCERNS))
    agent.mode = "yolo"
    call(url + "/api/chat", {"message": "write app.py"})
    wait_for(lambda: not session.busy and any(e.get("type") == "observer" for e in session.history))
    ev = next(e for e in session.history if e.get("type") == "observer")
    assert ev["fixable"] and len(ev["findings"]) == 2
    log = call(url + "/api/sessions/events?id=" + agent.session_id)
    assert log["summary"]["tool_calls"] == 1 and log["events"][0]["text"] == "write app.py"
    req = urllib.request.Request(f"{url}/api/sessions/export?id={agent.session_id}&format=md", headers={"x-docks-token": "tok"})
    with urllib.request.urlopen(req) as resp:
        assert "attachment" in resp.headers["content-disposition"] and b"write_file" in resp.read()
    call(url + "/api/fix", {})
    wait_for(lambda: not session.busy and agent.last_text().startswith("Ran the tests"))
    assert "Run pytest" in agent.messages[-2]["content"][0]["text"] if isinstance(agent.messages[-2]["content"], list) \
        else "Run pytest" in agent.messages[-2]["content"]
