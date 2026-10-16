import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace as NS

from docks.agent import Agent
from docks.web.server import Session, make_handler
from tests.test_docks import FakeClient, msg, tool_use


def start(tmp_path, responses):
    agent = Agent(root=tmp_path, client=FakeClient(responses))
    session = Session(agent)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(session, "tok", {"port": 1, "prefix": "/p/"}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return session, f"http://127.0.0.1:{server.server_port}"


def call(url, body=None, token="tok"):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"x-docks-token": token, "content-type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def wait_for(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_requires_token(tmp_path):
    _, url = start(tmp_path, [])
    try:
        call(url + "/api/state", token="nope")
        raise AssertionError("expected 401")
    except urllib.error.HTTPError as e:
        assert e.code == 401
    assert b"Docks" in urllib.request.urlopen(url + "/").read()  # the page itself holds no secrets


def test_chat_with_approval_over_http(tmp_path):
    session, url = start(tmp_path, [
        msg("tool_use", tool_use("t1", "write_file", path="index.html", content="<h1>hi</h1>")),
        msg("end_turn", NS(type="text", text="Done.")),
    ])
    assert call(url + "/api/chat", {"message": "make a page"})["ok"]
    wait_for(lambda: session.approvals)
    approval = next(e for e in session.history if e["type"] == "approval")
    assert approval["args"]["path"] == "index.html"
    call(url + "/api/approve", {"id": approval["id"], "answer": "yes"})
    wait_for(lambda: not session.busy)
    assert (tmp_path / "index.html").read_text() == "<h1>hi</h1>"
    assert "index.html" in call(url + "/api/files")["files"]
    assert call(url + "/api/file?path=index.html")["text"] == "<h1>hi</h1>"
    types = [e["type"] for e in session.history]
    assert types[0] == "user" and "tool_output" in types and types[-1] == "idle"


def test_stop_denies_pending_approval_and_discards_turn(tmp_path):
    session, url = start(tmp_path, [msg("tool_use", tool_use("t1", "bash", command="echo hi"))])
    call(url + "/api/chat", {"message": "run it"})
    wait_for(lambda: session.approvals)
    call(url + "/api/stop", {})
    wait_for(lambda: not session.busy)
    assert session.agent.messages == []
    assert any(e["type"] == "error" and "stopped" in e["text"] for e in session.history)


def test_file_api_stays_inside_project(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    _, url = start(tmp_path / "proj", [])
    try:
        call(url + "/api/file?path=../secret.txt")
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404
