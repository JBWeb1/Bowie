"""Bowers Cloud: sign in from the app, then Bowie runs on the owner's key, with credits, limits and a kill switch."""

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from docks import cloud
from docks.agent import Agent
from tests.test_extensions import Display
from tests.test_router import FakeUpstream, anthropic_sse

REPLY = anthropic_sse(
    {"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                                          "content": [], "usage": {"input_tokens": 1000, "cache_read_input_tokens": 5000,
                                                                   "cache_creation_input_tokens": 0, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi from the cloud"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 200}},
    {"type": "message_stop"})


@pytest.fixture
def cloud_server(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "BOWERS_CLOUD_TOKEN", "BOWERS_CLOUD_URL"):
        monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("_BOWERS_VAULT_LOADED_" + k, raising=False)
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BOWERS_VAULT", "file")
    upstream = FakeUpstream("anthropic")
    store = cloud.Store(str(tmp_path / "cloud.db"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), cloud.make_handler(store, "sk-owner-key", upstream=upstream.url))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield store, upstream, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    cloud.logout()


def activate(url, code, **form):
    data = urllib.parse.urlencode({"code": code, **form}).encode()
    try:
        return urllib.request.urlopen(urllib.request.Request(url + "/activate", data=data, method="POST")).read().decode()
    except urllib.error.HTTPError as e:
        return e.read().decode()


def api(url, path, token, body):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "x-api-key": token})
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code


def test_sign_in_and_bowie_runs_on_bowers_cloud(cloud_server, tmp_path):
    store, upstream, url = cloud_server
    invite = store.invite(1.00)
    info = cloud.start_login(url)
    assert "Invite" in activate(url, info["user_code"], email="sam@example.com", password="pw")  # too short: form again
    assert "invite-only" in activate(url, info["user_code"], email="sam@example.com", password="long-password", invite="WRONG")
    assert "signed in" in activate(url, info["user_code"], email="Sam@Example.com", password="long-password", name="Sam", invite=invite)
    assert cloud.login(url, log=lambda m: None, info=info, wait=10) == {"email": "sam@example.com"}
    assert cloud.signed_in() and os.environ["BOWERS_CLOUD_TOKEN"].startswith("bwc_")
    assert "invite-only" in activate(url, cloud.start_login(url)["user_code"], email="new@example.com", password="long-password",
                                     invite=invite)  # an invite works once

    upstream.replies.append((200, REPLY, {}))
    agent = Agent(root=tmp_path, display=Display(), model="opus")  # no key on this computer
    agent.run("hello")
    assert agent.messages[-1]["content"][-1].text == "Hi from the cloud"
    sent = upstream.requests[0]
    headers = {k.lower(): v for k, v in sent["headers"].items()}
    assert headers.get("x-api-key") == "sk-owner-key"  # the owner's key, never the person's token
    assert headers.get("anthropic-beta")  # Bowers' features pass through
    me = cloud.account()
    cost = cloud.cost_micro("claude-opus-5-5", {"input_tokens": 1000, "cache_read_input_tokens": 5000, "output_tokens": 200})
    assert cost == 1000 * 4 + 5000 * 0.2 + 200 * 20 and me["requests_30d"] == 1
    assert abs(me["balance_usd"] - (1.0 - cost / 1e6)) < 1e-6 and me["credits"] == 99


def test_cloud_refuses_what_it_should(cloud_server):
    store, upstream, url = cloud_server
    user = store.sign_in("a@example.com", "long-password", invite=store.invite(0.01))
    token = store.new_token(user["id"])
    body = {"model": "claude-opus-5-5", "max_tokens": 10, "messages": [{"role": "user", "content": "x"}]}
    assert api(url, "/v1/messages", "bwc_not-real", body) == 401
    assert api(url, "/v1/messages", token, {**body, "model": "gpt-5.5"}) == 400  # Bowers' models only: no plain API resale
    store.set_paused(True)
    assert api(url, "/v1/messages", token, body) == 503  # the kill switch
    store.set_paused(False)
    store.q("update users set balance_micro = 0 where id = ?", (user["id"],))
    assert api(url, "/v1/messages", token, body) == 402  # out of credits
    assert upstream.requests == []  # nothing reached Claude
    with pytest.raises(cloud.CloudError):
        store.sign_in("a@example.com", "wrong-password")
