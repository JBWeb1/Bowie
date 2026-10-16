import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic
import pytest

from docks.agent import Agent
from docks.router import translate
from docks.router.config import load
from docks.router.server import make_handler
from docks.router.engine import Engine


class FakeUpstream:
    """Scripted provider. Each queued reply is (status, payload, headers) or a callable(body)."""

    def __init__(self, kind):
        self.kind, self.replies, self.requests = kind, [], []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
                status, payload, headers = outer.replies.pop(0) if outer.replies else outer.default(body)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                if isinstance(payload, list):  # SSE
                    self.send_header("content-type", "text/event-stream")
                    self.end_headers()
                    for item in payload:
                        self.wfile.write(item.encode())
                else:
                    data = json.dumps(payload).encode()
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def default(self, body):
        return 500, {"error": "no reply scripted"}, {}


def openai_sse(*chunks):
    return [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]


def anthropic_sse(*events):
    return [f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events]


def oa_chunk(delta, finish=None, usage=None):
    c = {"id": "x", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage:
        c = {"id": "x", "object": "chat.completion.chunk", "choices": [], "usage": usage}
    return c


OPENAI_TOOL_STREAM = openai_sse(
    oa_chunk({"role": "assistant", "content": "Let me check."}),
    oa_chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                              "function": {"name": "bash", "arguments": ""}}]}),
    oa_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"command": '}}]}),
    oa_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"echo routed"}'}}]}),
    oa_chunk({}, "tool_calls"),
    oa_chunk({}, usage={"prompt_tokens": 12, "completion_tokens": 7}),
)

OPENAI_TEXT_STREAM = openai_sse(oa_chunk({"content": "All done."}), oa_chunk({}, "stop"),
                                oa_chunk({}, usage={"prompt_tokens": 20, "completion_tokens": 3}))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path / "home"))
    ant, oai = FakeUpstream("anthropic"), FakeUpstream("openai")
    monkeypatch.setenv("FAKE_ANT_KEY", "ant-secret")
    monkeypatch.setenv("FAKE_OAI_KEY", "oai-secret")
    cfg = load(tmp_path / "missing.json")
    cfg["providers"] = {
        "fa": {"type": "anthropic", "base_url": ant.url, "api_key_env": "FAKE_ANT_KEY"},
        "fo": {"type": "openai", "base_url": oai.url + "/v1", "api_key_env": "FAKE_OAI_KEY"},
    }
    cfg["routes"] = {"code-best": {"strategy": "fallback", "targets": ["fa/claude-test", "fo/gpt-test"]},
                     "openai-only": {"strategy": "fallback", "targets": ["fo/gpt-test"]}}
    cfg["aliases"] = {}
    cfg["default_route"] = "code-best"
    cfg["max_wait_seconds"] = 5
    engine = Engine(cfg)
    router = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine, "router-key"))
    threading.Thread(target=router.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{router.server_port}"
    yield NSx(ant=ant, oai=oai, url=url, engine=engine)
    router.shutdown()


class NSx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def post(url, body, key="router-key"):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "authorization": f"Bearer {key}"})
    return urllib.request.urlopen(req)


def test_anthropic_sdk_through_router_to_openai_provider(setup):
    setup.oai.replies.append((200, OPENAI_TOOL_STREAM, {}))
    client = anthropic.Anthropic(base_url=setup.url, api_key="router-key", max_retries=0)
    tools = [{"name": "bash", "description": "run", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}}},
             {"type": "web_search_20260209", "name": "web_search"}]
    with client.messages.stream(model="openai-only", max_tokens=1000, tools=tools,
                                system="be brief", messages=[{"role": "user", "content": "hi"}]) as s:
        msg = s.get_final_message()
    assert msg.stop_reason == "tool_use"
    assert msg.content[0].text == "Let me check."
    assert msg.content[1].input == {"command": "echo routed"}
    sent = setup.oai.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer oai-secret"
    assert sent["body"]["model"] == "gpt-test"
    assert sent["body"]["messages"][0] == {"role": "system", "content": "be brief"}
    assert [t["function"]["name"] for t in sent["body"]["tools"]] == ["bash"]  # server tool dropped
    assert setup.engine.stats.snapshot()["totals"]["fo/gpt-test"]["output_tokens"] == 7


def test_failover_on_rate_limit_then_cooldown(setup):
    setup.ant.replies.append((429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
                              {"retry-after": "30"}))
    setup.oai.replies += [(200, {"choices": [{"message": {"content": "from openai"}, "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 2}}, {})] * 2
    client = anthropic.Anthropic(base_url=setup.url, api_key="router-key", max_retries=0)
    for _ in range(2):
        msg = client.messages.create(model="code-best", max_tokens=100, messages=[{"role": "user", "content": "x"}])
        assert msg.content[0].text == "from openai"
    assert len(setup.ant.requests) == 1  # second call skipped the cooling provider
    assert setup.engine.health.snapshot()["fa"]["cooldown_s"] > 20


def test_waits_for_recovery_instead_of_failing(setup):
    for upstream in (setup.ant, setup.oai):
        upstream.replies.append((429, {"error": "limited"}, {"retry-after": "1"}))
    setup.ant.replies.append((200, {"id": "m", "type": "message", "role": "assistant", "model": "claude-test",
                                    "content": [{"type": "text", "text": "recovered"}], "stop_reason": "end_turn",
                                    "usage": {"input_tokens": 1, "output_tokens": 1}}, {}))
    started = time.monotonic()
    data = json.load(post(setup.url + "/v1/chat/completions",
                          {"model": "code-best", "messages": [{"role": "user", "content": "x"}]}))
    assert data["choices"][0]["message"]["content"] == "recovered"
    assert time.monotonic() - started >= 0.9


def test_openai_client_streams_from_anthropic_provider(setup):
    setup.ant.replies.append((200, anthropic_sse(
        {"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant", "model": "c",
                                              "content": [], "usage": {"input_tokens": 9, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "tu1", "name": "read", "input": {}}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"path":"a"}'}},
        {"type": "content_block_stop", "index": 2},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
        {"type": "message_stop"}), {}))
    resp = post(setup.url + "/v1/chat/completions", {
        "model": "fa/claude-test", "stream": True, "stream_options": {"include_usage": True}, "temperature": 0.2,
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "go"},
                     {"role": "assistant", "content": None, "tool_calls": [{"id": "c0", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
                     {"role": "tool", "tool_call_id": "c0", "content": "file"}],
        "tools": [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}]})
    lines = [l[6:] for l in resp.read().decode().splitlines() if l.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(l) for l in lines[:-1]]
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks if c["choices"])
    args = "".join(tc["function"].get("arguments", "") for c in chunks if c["choices"]
                   for tc in c["choices"][0]["delta"].get("tool_calls", []))
    assert text == "Hi" and json.loads(args) == {"path": "a"}
    assert [c["choices"][0]["finish_reason"] for c in chunks if c["choices"]][-1] == "tool_calls"
    assert chunks[-1]["usage"] == {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}
    sent = setup.ant.requests[0]["body"]
    assert sent["system"] == "sys" and "temperature" not in sent
    assert sent["messages"][2] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c0", "content": "file"}]}


def test_bad_request_is_not_retried_and_auth_required(setup):
    setup.ant.replies.append((400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}, {}))
    with pytest.raises(urllib.error.HTTPError) as e:
        post(setup.url + "/v1/messages", {"model": "code-best", "max_tokens": 5, "messages": []})
    assert e.value.code == 400 and not setup.oai.requests
    with pytest.raises(urllib.error.HTTPError) as e:
        post(setup.url + "/v1/messages", {"model": "code-best"}, key="wrong")
    assert e.value.code == 401


def test_docks_agent_runs_through_router_on_openai_provider(setup, tmp_path):
    setup.oai.replies += [(200, OPENAI_TOOL_STREAM, {}), (200, OPENAI_TEXT_STREAM, {})]
    client = anthropic.Anthropic(base_url=setup.url, api_key="router-key", max_retries=0)
    agent = Agent(root=tmp_path, client=client, model="openai-only", auto_approve=True)
    agent.run("say routed")
    second = setup.oai.requests[1]["body"]["messages"]
    tool_msg = next(m for m in second if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1" and "routed" in tool_msg["content"]
    assert agent.messages[-1]["content"][-1].text == "All done."


def test_request_translation_roundtrip():
    body = {"system": [{"type": "text", "text": "S"}], "max_tokens": 64000, "stream": True,
            "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}},
                                                      {"type": "text", "text": "look"}]}]}
    out = translate.anthropic_to_openai_request(body, "m", max_tokens_cap=8192)
    assert out["max_tokens"] == 8192 and out["stream_options"] == {"include_usage": True}
    assert out["messages"][1]["content"][0]["image_url"]["url"] == "data:image/png;base64,AAA"
    back = translate.openai_to_anthropic_request(out, "c")
    assert back["messages"][0]["content"][0]["source"] == {"type": "base64", "media_type": "image/png", "data": "AAA"}


def test_does_not_wait_on_errors_that_wont_clear(setup):
    setup.ant.replies.append((401, {"error": "bad key"}, {}))
    setup.oai.replies.append((402, {"error": {"message": "insufficient_quota"}}, {}))
    started = time.monotonic()
    with pytest.raises(urllib.error.HTTPError) as e:
        post(setup.url + "/v1/chat/completions", {"model": "code-best", "messages": [{"role": "user", "content": "x"}]})
    assert e.value.code == 503 and time.monotonic() - started < 2
    assert "fa/claude-test" in json.load(e.value)["error"]["message"]
