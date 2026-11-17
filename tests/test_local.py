"""Bowers Local: a model on this computer (Ollama / LM Studio), reached through Bowers Router, with no API key."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from docks import doctor, local, models
from docks.agent import Agent
from docks.router.config import load
from docks.router.engine import Engine
from tests.test_extensions import Display
from tests.test_router import OPENAI_TEXT_STREAM, OPENAI_TOOL_STREAM


class FakeOllama:
    """Answers like Ollama: its model list, and OpenAI-style chat completions (scripted)."""

    def __init__(self, names):
        self.names, self.replies, self.requests = names, [], []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, payload, sse=False):
                self.send_response(200)
                self.send_header("content-type", "text/event-stream" if sse else "application/json")
                self.end_headers()
                self.wfile.write("".join(payload).encode() if sse else json.dumps(payload).encode())

            def do_GET(self):
                if self.path == "/api/tags":
                    return self._send({"models": [{"name": n} for n in outer.names]})
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append({"path": self.path, "body": body})
                self._send(outer.replies.pop(0), sse=True)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def dead_port() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def no_keys(monkeypatch, tmp_path):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "DOCKS_ROUTER_URL", "OPENAI_API_KEY",
              "BOWERS_LOCAL_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LMSTUDIO_URL", dead_port())
    monkeypatch.setattr(local, "_cache", {"at": 0.0, "found": None})
    monkeypatch.setitem(models._router, "url", None)
    return monkeypatch


def test_no_key_runs_on_the_local_model_through_the_router(no_keys, tmp_path):
    ollama = FakeOllama(["llama3.2:3b", "bowers-coder:latest"])
    no_keys.setenv("OLLAMA_HOST", ollama.url)
    ollama.replies += [OPENAI_TOOL_STREAM, OPENAI_TEXT_STREAM]
    agent = Agent(root=tmp_path, display=Display(), auto_approve=True)
    assert agent.profile == "local" and agent.model == "ollama/bowers-coder:latest"
    assert agent.model_label == "Bowers Local 1"
    agent.run("say routed")
    first, second = ollama.requests
    assert first["path"] == "/v1/chat/completions" and first["body"]["model"] == "bowers-coder:latest"
    tool_msg = next(m for m in second["body"]["messages"] if m["role"] == "tool")
    assert "routed" in tool_msg["content"] and agent.messages[-1]["content"][-1].text == "All done."
    assert any(line[1] == "API key" and "Bowers Local" in line[2] for line in doctor.check(tmp_path, online=False))


def test_nothing_running_says_how_to_set_it_up(no_keys, tmp_path):
    no_keys.setenv("OLLAMA_HOST", dead_port())
    no_keys.setattr(local, "ollama_exe", lambda: None)
    assert "bowers local setup" in local.problem()
    agent = Agent(root=tmp_path, display=Display(), model="local")
    assert agent.model == "local" and "bowers local setup" in agent.model_error
    assert agent.profile == "local"
    no_keys.setattr(local, "ollama_exe", lambda: "/usr/bin/ollama")
    local._cache["found"] = None
    assert "not running" in local.problem()


def test_a_local_model_never_fails_over_to_a_paid_one(no_keys, tmp_path):
    no_keys.setenv("ANTHROPIC_API_KEY", "sk-test")
    engine = Engine(load(tmp_path / "missing.json"))
    assert [t.label for t in engine.resolve("ollama/bowers-coder:latest")] == ["ollama/bowers-coder:latest"]
    assert len(engine.resolve("claude-opus-5-5")) > 1  # cloud models still fail over as before


def test_picks_a_good_model_and_sizes_it():
    assert local.best(["llama3.2:3b", "qwen2.5-coder:7b", "gemma3:4b"]) == "qwen2.5-coder:7b"
    assert local.best(["bowers-coder:latest", "qwen3-coder:30b"]) == "bowers-coder:latest"
    assert local.best(["something-else:1b"]) == "something-else:1b"
    assert local.recommended(8) == "qwen2.5-coder:3b" and local.recommended(16) == "qwen2.5-coder:7b"
    assert local.recommended(64) == "qwen2.5-coder:14b"
    assert local.modelfile("qwen2.5-coder:7b") == "FROM qwen2.5-coder:7b\nPARAMETER num_ctx 32768\n"
    assert models.resolve("ollama") in ("local",) or models.is_local(models.resolve("ollama"))


def test_free_apis_need_no_key(tmp_path):
    from docks import resources, tools
    apis = resources.search("weather", "public-apis")
    assert apis and all(a["source"] == "public-apis" for a in apis)
    assert "public-apis" in resources.SOURCES and resources.count() > 6000
    out = tools.run_tool(tmp_path, "find_free_api", {"query": "currency exchange"})
    assert "Currency" in out and "http" in out
