import json
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS

import pytest

from docks import mcp
from docks.agent import Agent
from tests.test_docks import FakeClient, msg, tool_use

STDIO_SERVER = r'''
import json, sys
print("starting up (not JSON, should be ignored)", flush=True)
def send(m): sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m or "method" not in m:
        continue
    method, i = m["method"], m["id"]
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": 900, "method": "ping"})  # server-to-client request
        send({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
              "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "tools/list":
        if not m["params"].get("cursor"):
            send({"jsonrpc": "2.0", "id": i, "result": {"tools": [{"name": "add", "description": "Add numbers",
                  "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
                  "annotations": {"readOnlyHint": True}}], "nextCursor": "p2"}})
        else:
            send({"jsonrpc": "2.0", "id": i, "result": {"tools": [{"name": "deploy.site", "description": "Deploy",
                  "inputSchema": {"type": "object"}}]}})
    elif method == "tools/call":
        a = m["params"]["arguments"]
        if m["params"]["name"] == "add":
            send({"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": str(a["a"] + a["b"])}]}})
        else:
            send({"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": "no credentials"}], "isError": True}})
'''


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path / "home"))
    script = tmp_path / "fake_mcp.py"
    script.write_text(STDIO_SERVER)
    project = tmp_path / "project"
    project.mkdir()
    return NS(tmp=tmp_path, script=script, project=project)


def test_stdio_server_tools_and_calls(home):
    mcp.write_server(mcp.user_config_path(), "calc", {"command": sys.executable, "args": [str(home.script)]})
    mgr = mcp.MCPManager(home.project)
    mgr.start()
    try:
        assert mgr.summary()[0]["status"] == "running"
        names = [d["name"] for d in mgr.tool_definitions()]
        assert names == ["mcp__calc__add", "mcp__calc__deploy_site"]  # both pages; name sanitized
        assert mgr.call("mcp__calc__add", {"a": 2, "b": 3}) == ("5", False)
        assert mgr.call("mcp__calc__deploy_site", {}) == ("no credentials", True)
        assert not mgr.is_mutating("mcp__calc__add") and mgr.is_mutating("mcp__calc__deploy_site")
    finally:
        mgr.close()


def test_project_servers_need_approval(home):
    mcp.write_server(mcp.project_config_path(home.project), "calc", {"command": sys.executable, "args": [str(home.script)]})
    mgr = mcp.MCPManager(home.project)
    mgr.start()
    assert [s.name for s in mgr.pending_approval()] == ["calc"] and not mgr.tool_definitions()
    mgr.approve("calc")
    assert mgr.tool_definitions()
    mgr.close()
    again = mcp.MCPManager(home.project)  # approval is remembered for this exact config
    again.start()
    assert again.summary()[0]["status"] == "running"
    again.close()
    mcp.write_server(mcp.project_config_path(home.project), "calc", {"command": "rm", "args": ["-rf", "/"]})
    changed = mcp.MCPManager(home.project)  # a changed command needs approval again
    changed.start()
    assert changed.summary()[0]["status"] == "needs-approval"


def test_broken_server_reports_error(home):
    mcp.write_server(mcp.user_config_path(), "nope", {"command": "definitely-not-a-real-command-xyz"})
    mgr = mcp.MCPManager(home.project)
    mgr.start()
    s = mgr.summary()[0]
    assert s["status"] == "error" and "could not start" in s["error"]


def test_http_server_with_sse_and_session(home, monkeypatch):
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            m = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append((m.get("method"), self.headers.get("mcp-session-id"), self.headers.get("authorization")))
            if "id" not in m:
                self.send_response(202)
                self.end_headers()
                return
            if m["method"] == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "h"}}
            elif m["method"] == "tools/list":
                result = {"tools": [{"name": "search", "inputSchema": {"type": "object"}}]}
            else:
                result = {"content": [{"type": "text", "text": "found 3 docs"}]}
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("mcp-session-id", "sess-1")
            self.end_headers()
            self.wfile.write(f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': result})}\n\n".encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("DOCS_TOKEN", "abc")
    mcp.write_server(mcp.user_config_path(), "docs", {"type": "http", "url": f"http://127.0.0.1:{server.server_port}/mcp",
                                                       "headers": {"Authorization": "Bearer ${DOCS_TOKEN}"}})
    mgr = mcp.MCPManager(home.project)
    mgr.start()
    assert mgr.call("mcp__docs__search", {"q": "x"}) == ("found 3 docs", False)
    assert seen[0] == ("initialize", None, "Bearer abc")
    assert all(sid == "sess-1" for _, sid, _ in seen[1:])  # session id carried after initialize
    server.shutdown()


def test_agent_uses_mcp_tool(home):
    mcp.write_server(mcp.user_config_path(), "calc", {"command": sys.executable, "args": [str(home.script)]})
    mgr = mcp.MCPManager(home.project)
    mgr.start()
    client = FakeClient([msg("tool_use", tool_use("t1", "mcp__calc__add", a=20, b=22)),
                         msg("end_turn", NS(type="text", text="42"))])
    agent = Agent(root=home.project, client=client, mcp=mgr)  # read-only tool: no approval needed
    assert "mcp__calc__add" in [t["name"] for t in agent.tools]
    agent.run("what is 20 + 22")
    assert agent.messages[2]["content"][0]["content"] == "42"
    mgr.close()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_background_dev_server(tmp_path):
    (tmp_path / "index.html").write_text("<h1>live</h1>")
    port = _free_port()
    seen = []
    client = FakeClient([
        msg("tool_use", tool_use("t1", "start_process", command=f"{sys.executable} -u -m http.server {port} --bind 127.0.0.1")),
        msg("end_turn", NS(type="text", text="Running.")),
    ])
    agent = Agent(root=tmp_path, client=client, auto_approve=True)
    agent.procs.on_change = seen.append
    agent.run("serve it")
    try:
        out = agent.messages[2]["content"][0]["content"]
        assert f"http://localhost:{port}/" in out and "preview" in out
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/").read() == b"<h1>live</h1>"
        assert seen and seen[0]["url"] == f"http://localhost:{port}/"
        assert agent.procs.list()[0]["running"]
    finally:
        agent.procs.stop_all()
    time.sleep(0.3)
    assert not agent.procs.list()[0]["running"]


def test_crashing_process_reports_exit(tmp_path):
    agent = Agent(root=tmp_path, client=FakeClient([]))
    out = agent.procs.start("echo boom >&2; exit 3", wait=5)
    assert "exited with code 3" in out and "boom" in out
