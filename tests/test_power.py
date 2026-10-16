"""Long sessions (compaction), undo checkpoints, the plan checklist, and parallel helper agents."""

import subprocess
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from docks.agent import HELPER_NOTE, Agent
from tests.test_docks import FakeClient, msg, tool_use


@pytest.fixture(autouse=True)
def home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path_factory.mktemp("docks-home")))


class Recorder:
    """A display that records what the agent shows."""

    def __init__(self):
        self.events = []

    def stream(self):
        return NS(handle=lambda e: None, finish=lambda: None)

    def __getattr__(self, name):
        return lambda *a, **k: self.events.append((name, a, k))

    def confirm(self, name, args):
        return "yes"


def test_requests_enable_compaction_and_report_it(tmp_path):
    compacted = msg("end_turn", NS(type="compaction", content="summary"), NS(type="text", text="ok"))
    client = FakeClient([compacted])
    display = Recorder()
    Agent(root=tmp_path, client=client, display=display).run("hi")
    req = client.requests[0]
    assert "compact-2026-01-12" in req["betas"]
    assert req["context_management"] == {"edits": [{"type": "compact_20260112"}]}
    assert any(e[0] == "notice" and "Summarized" in e[1][0] for e in display.events)


def test_undo_restores_files_and_conversation(tmp_path):
    git = lambda *a: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=tmp_path,
                                    check=True, capture_output=True, text=True).stdout
    git("init", "-q")
    (tmp_path / "app.py").write_text("v0\n")
    git("add", "-A")
    git("commit", "-qm", "mine")
    client = FakeClient([
        msg("tool_use", tool_use("t1", "write_file", path="app.py", content="v1\n")),
        msg("end_turn", NS(type="text", text="one")),
        msg("tool_use", tool_use("t2", "write_file", path="new/deep/file.txt", content="x")),
        msg("tool_use", tool_use("t3", "edit_file", path="app.py", old_string="v1", new_string="v2")),
        msg("end_turn", NS(type="text", text="two")),
    ])
    agent = Agent(root=tmp_path, client=client, auto_approve=True)
    agent.run("first change")
    agent.run("second change")
    assert (tmp_path / "app.py").read_text() == "v2\n" and (tmp_path / "new/deep/file.txt").exists()

    text, restored = agent.rewind(1)
    assert text == "second change"
    assert sorted(restored) == ["app.py", "new/deep/file.txt"]
    assert (tmp_path / "app.py").read_text() == "v1\n"
    assert not (tmp_path / "new").exists()  # created files and their empty folders are removed
    assert len(agent.messages) == 4 and len(agent.turns) == 1

    agent.rewind(0)
    assert (tmp_path / "app.py").read_text() == "v0\n" and agent.messages == []
    # The project's own git history and index were never touched.
    assert git("log", "--format=%s").split() == ["mine"]
    assert git("status", "--porcelain") == ""


def test_plan_tool_updates_display(tmp_path):
    items = [{"text": "Scaffold app", "status": "done"}, {"text": "Add login", "status": "in_progress"}]
    client = FakeClient([msg("tool_use", tool_use("t1", "update_plan", items=items)),
                         msg("end_turn", NS(type="text", text="ok"))])
    display = Recorder()
    agent = Agent(root=tmp_path, client=client, display=display)
    agent.run("big job")
    assert ("plan", (items,), {}) in display.events and agent.plan == items


class RoutingClient:
    """Answers lead and helper agents by who is asking, so parallel helpers get the right replies."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.beta = NS(messages=NS(stream=self.stream))
        self.helper_tools = None

    @contextmanager
    def stream(self, **kw):
        messages = kw["messages"]
        first = messages[0]["content"]
        if HELPER_NOTE in kw["system"]:
            self.helper_tools = [t["name"] for t in kw["tools"]]
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.3)  # long enough that parallel helpers overlap
            with self.lock:
                self.active -= 1
            name = "a.txt" if "part A" in first else "b.txt"
            if len(messages) == 1:
                response = msg("tool_use", tool_use("h1", "write_file", path=name, content=name))
            else:
                response = msg("end_turn", NS(type="text", text=f"Wrote {name}."))
        elif len(messages) == 1:
            response = msg("tool_use",
                           tool_use("d1", "delegate", description="Build part A", prompt="Do part A"),
                           tool_use("d2", "delegate", description="Build part B", prompt="Do part B"))
        else:
            response = msg("end_turn", NS(type="text", text="Both parts done."))
        yield NS(__iter__=lambda self: iter([]), get_final_message=lambda: response)


class _Stream:
    def __init__(self, response):
        self.response = response

    def __iter__(self):
        return iter([])

    def get_final_message(self):
        return self.response


def test_helpers_run_in_parallel_and_report_back(tmp_path):
    client = RoutingClient()
    real_stream = client.stream

    @contextmanager
    def stream(**kw):
        with real_stream(**kw) as s:
            yield _Stream(s.get_final_message())

    client.beta = NS(messages=NS(stream=stream))
    display = Recorder()
    agent = Agent(root=tmp_path, client=client, display=display, auto_approve=True)
    agent.run("build both parts")
    assert (tmp_path / "a.txt").read_text() == "a.txt" and (tmp_path / "b.txt").read_text() == "b.txt"
    results = agent.messages[2]["content"]
    assert [r["content"] for r in results] == ["Wrote a.txt.", "Wrote b.txt."]  # in call order
    assert client.max_active == 2  # they really ran at the same time
    assert "delegate" not in client.helper_tools  # helpers can't spawn helpers
    helper_calls = [e for e in display.events if e[0] == "tool_call" and e[2].get("helper")]
    assert {e[2]["helper"] for e in helper_calls} == {"Build part A", "Build part B"}
    assert agent.usage["input"] == 60  # lead (2 calls) + helpers (2 calls each), 10 tokens per call


def test_store_inside_project_is_never_snapshotted(tmp_path, monkeypatch):
    # e.g. running Docks in a folder that contains its own data folder
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path / ".config" / "docks"))
    client = FakeClient([msg("tool_use", tool_use("t1", "write_file", path="a.txt", content="1")),
                         msg("end_turn", NS(type="text", text="ok"))])
    agent = Agent(root=tmp_path, client=client, auto_approve=True)
    agent.run("make a")
    _, restored = agent.rewind(0)
    assert restored == ["a.txt"] and not (tmp_path / "a.txt").exists()
    assert (tmp_path / ".config" / "docks" / "checkpoints").is_dir()  # store survived the restore
