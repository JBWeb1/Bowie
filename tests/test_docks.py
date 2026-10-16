from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docks.agent import Agent
from docks.tools import ToolError, run_tool


def msg(stop_reason, *blocks):
    usage = NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)
    return NS(stop_reason=stop_reason, content=list(blocks), usage=usage)


def tool_use(id, name, **input):
    return NS(type="tool_use", id=id, name=name, input=input)


class FakeClient:
    """Plays back scripted responses and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(stream=self.stream))

    @contextmanager
    def stream(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        response = self.responses.pop(0)
        yield _Stream(response)


class _Stream:
    def __init__(self, response):
        self.response = response

    def __iter__(self):
        return iter([])

    def get_final_message(self):
        return self.response


def test_tools_roundtrip(tmp_path: Path):
    run_tool(tmp_path, "write_file", {"path": "a/b.txt", "content": "hello\nworld\n"})
    assert "world" in run_tool(tmp_path, "read_file", {"path": "a/b.txt"})
    run_tool(tmp_path, "edit_file", {"path": "a/b.txt", "old_string": "world", "new_string": "docks"})
    assert (tmp_path / "a/b.txt").read_text() == "hello\ndocks\n"
    assert "a/b.txt:2" in run_tool(tmp_path, "grep", {"pattern": "docks"})
    assert "b.txt" in run_tool(tmp_path, "glob", {"pattern": "*.txt"})
    assert "exit code 0" in run_tool(tmp_path, "bash", {"command": "echo hi"})


def test_tool_validation(tmp_path: Path):
    with pytest.raises(ToolError):
        run_tool(tmp_path, "write_file", {"path": "x"})  # missing content
    with pytest.raises(ToolError):
        run_tool(tmp_path, "bash", {"command": "ls", "timeout": "soon"})
    (tmp_path / "f").write_text("x x")
    with pytest.raises(ToolError):
        run_tool(tmp_path, "edit_file", {"path": "f", "old_string": "x", "new_string": "y"})


def test_agent_loop_runs_tools_and_finishes(tmp_path: Path):
    client = FakeClient([
        msg("tool_use", tool_use("t1", "write_file", path="hi.py", content="print('hi')\n")),
        msg("tool_use", tool_use("t2", "bash", command="python3 hi.py")),
        msg("end_turn", NS(type="text", text="Done.")),
    ])
    agent = Agent(root=tmp_path, client=client, auto_approve=True)
    agent.run("make hi.py")
    assert (tmp_path / "hi.py").exists()
    results = agent.messages[-2]["content"]
    assert results[0]["tool_use_id"] == "t2" and "hi" in results[0]["content"]
    assert len(agent.messages) == 6  # user, (assistant, results) x2, assistant
    assert client.requests[0]["fallbacks"] == "default"


def test_declined_tool_and_refusal_rollback(tmp_path: Path):
    client = FakeClient([
        msg("tool_use", tool_use("t1", "bash", command="rm -rf /")),
        msg("end_turn", NS(type="text", text="ok")),
        msg("refusal"),
    ])
    agent = Agent(root=tmp_path, client=client, confirm=lambda name, args: "no")
    agent.run("do it")
    assert agent.messages[2]["content"][0]["is_error"]
    before = len(agent.messages)
    agent.run("something refused")
    assert len(agent.messages) == before  # refused turn rolled back
