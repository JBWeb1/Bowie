"""Signing in to a remote MCP server with OAuth, against a fake server that checks every step."""

import base64
import hashlib
import json
import os
import stat
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from docks import mcp, mcp_oauth


class FakeApp:
    """An MCP server at /mcp guarded by OAuth, plus its authorization server."""

    def __init__(self, dcr=True, iss_param=True):
        self.codes, self.tokens, self.registered = {}, {}, []
        self.token_requests, self.dcr, self.iss_param = [], dcr, iss_param
        self.expire_next = False
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, status=200, headers=None):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                if u.path == "/.well-known/oauth-protected-resource/mcp":
                    return self._json({"resource": outer.url + "/mcp", "authorization_servers": [outer.url],
                                       "scopes_supported": ["read", "write"]})
                if u.path == "/.well-known/oauth-authorization-server":
                    meta = {"issuer": outer.url, "authorization_endpoint": outer.url + "/authorize",
                            "token_endpoint": outer.url + "/token", "code_challenge_methods_supported": ["S256"],
                            "authorization_response_iss_parameter_supported": outer.iss_param}
                    if outer.dcr:
                        meta["registration_endpoint"] = outer.url + "/register"
                    return self._json(meta)
                if u.path == "/authorize":  # the person approves at once
                    assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
                    assert q["resource"] == outer.url + "/mcp" and q["scope"] == "read write"
                    code = "code-" + q["state"][:6]
                    outer.codes[code] = q
                    back = {"code": code, "state": outer.forced_state or q["state"]}
                    if outer.iss_param:
                        back["iss"] = outer.url
                    self.send_response(302)
                    self.send_header("location", q["redirect_uri"] + "?" + urllib.parse.urlencode(back))
                    self.end_headers()
                    return
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("content-length", 0)))
                u = urllib.parse.urlsplit(self.path)
                if u.path == "/register":
                    body = json.loads(raw)
                    outer.registered.append(body)
                    return self._json({"client_id": f"client-{len(outer.registered)}", **body}, 201)
                if u.path == "/token":
                    form = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
                    outer.token_requests.append(form)
                    if form["grant_type"] == "authorization_code":
                        asked = outer.codes.pop(form["code"], None)
                        challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                        if not asked or asked["code_challenge"] != challenge or form["resource"] != outer.url + "/mcp":
                            return self._json({"error": "invalid_grant"}, 400)
                    elif form["grant_type"] == "refresh_token" and form["refresh_token"] != "refresh-1":
                        return self._json({"error": "invalid_grant"}, 400)
                    token = f"token-{len(outer.token_requests)}"
                    outer.tokens[token] = True
                    return self._json({"access_token": token, "refresh_token": "refresh-1", "expires_in": 3600,
                                       "token_type": "Bearer"})
                if u.path == "/mcp":
                    auth = self.headers.get("authorization", "").removeprefix("Bearer ")
                    if auth not in outer.tokens or outer.expire_next:
                        outer.expire_next = False
                        outer.tokens.pop(auth, None)
                        return self._json({"error": "unauthorized"}, 401, {"www-authenticate":
                            f'Bearer resource_metadata="{outer.url}/.well-known/oauth-protected-resource/mcp"'})
                    msg = json.loads(raw)
                    if "id" not in msg:
                        self.send_response(202)
                        self.end_headers()
                        return
                    result = {"initialize": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "fake"}},
                              "tools/list": {"tools": [{"name": "search", "description": "Search pages",
                                                        "inputSchema": {"type": "object", "properties": {}}}]},
                              "tools/call": {"content": [{"type": "text", "text": "found 3 pages"}]}}[msg["method"]]
                    return self._json({"jsonrpc": "2.0", "id": msg["id"], "result": result})
                self._json({"error": "not found"}, 404)

        self.forced_state = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def browser(url):
    """What the person's browser does: open the sign-in page and follow the redirect back to Bowers."""
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(mcp, "user_config_path", lambda: tmp_path / "home" / "mcp.json")


def test_sign_in_then_use_tools_and_refresh(tmp_path):
    app = FakeApp()
    mgr = mcp.MCPManager(tmp_path)
    server = mgr.add("notes", {"type": "http", "url": app.url + "/mcp"})
    assert server.status == "needs-auth" and "resource_metadata" in server.www_authenticate
    login = mgr.start_login("notes")
    assert login.url.startswith(app.url + "/authorize?") and app.registered[0]["client_name"] == "Bowers"
    page = browser(login.url)
    assert "Connected" in page
    mgr.finish_login("notes", login, timeout=5)
    assert server.status == "running" and mgr.call("mcp__notes__search", {}) == ("found 3 pages", False)
    saved = json.loads(mcp_oauth.store_path().read_text())
    assert stat.S_IMODE(os.stat(mcp_oauth.store_path()).st_mode) == 0o600
    assert saved[app.url + "/mcp"]["tokens"]["refresh_token"] == "refresh-1"
    # an expired token is refreshed on its own
    app.expire_next = True
    assert mgr.call("mcp__notes__search", {})[0] == "found 3 pages"
    assert app.token_requests[-1]["grant_type"] == "refresh_token"
    # a new session reuses the saved sign-in
    again = mcp.MCPManager(tmp_path)
    again.start()
    assert again.servers["notes"].status == "running"
    assert mgr.logout("notes") and mcp_oauth.access_token(app.url + "/mcp") is None


def test_tampered_reply_is_rejected(tmp_path):
    app = FakeApp()
    app.forced_state = "not-the-state"
    mgr = mcp.MCPManager(tmp_path)
    mgr.add("notes", {"type": "http", "url": app.url + "/mcp"})
    login = mgr.start_login("notes")
    browser(login.url)
    with pytest.raises(mcp.MCPError, match="state"):
        mgr.finish_login("notes", login, timeout=5)
    assert app.token_requests == []  # the code was never exchanged


def test_servers_without_registration_need_a_client_id(tmp_path):
    app = FakeApp(dcr=False, iss_param=False)
    mgr = mcp.MCPManager(tmp_path)
    mgr.add("notes", {"type": "http", "url": app.url + "/mcp"})
    with pytest.raises(mcp.MCPError, match="client ID"):
        mgr.start_login("notes")
    mgr.add("notes", {"type": "http", "url": app.url + "/mcp", "oauth": {"clientId": "my-app"}})
    login = mgr.start_login("notes")
    assert "client_id=my-app" in login.url
    browser(login.url)
    assert mgr.finish_login("notes", login, timeout=5).status == "running"


def test_catalog_specs_and_listing(tmp_path, monkeypatch):
    from docks import mcp_catalog
    ids = [a["id"] for a in mcp_catalog.APPS]
    assert len(ids) == len(set(ids)) and mcp_catalog.find("NOTION")["auth"] == "oauth"
    fs = mcp_catalog.find("filesystem")
    spec = mcp_catalog.build_spec(fs, {"path": "~/notes"})
    assert spec["args"][-1] == os.path.expanduser("~/notes") and fs["spec"]["args"][-1] == "{path}"
    assert mcp_catalog.build_spec(fs)["args"][-1] == os.path.expanduser("~/Documents")
    monkeypatch.setattr(mcp_catalog.shutil, "which", lambda name: None)
    assert "Node.js" in mcp_catalog.missing_tool(fs) and mcp_catalog.missing_tool(mcp_catalog.find("notion")) is None
    for source in ("featured", "community"):  # featured apps first, then the community list; each grouped by category
        cats = [a["category"] for a in mcp_catalog.listing() if a["source"] == source]
        assert all(c == cats[i - 1] or c not in cats[:i] for i, c in enumerate(cats))
    assert {a["status"] for a in mcp_catalog.listing()} == {"not-connected"}


def test_connect_and_sign_in_from_the_browser_page(tmp_path, monkeypatch):
    from docks import mcp_catalog
    from tests.test_web import call, start, wait_for
    app = FakeApp()
    notion = {**mcp_catalog.find("notion"), "spec": {"type": "http", "url": app.url + "/mcp"}}
    monkeypatch.setattr(mcp_catalog, "APPS", [notion, *[a for a in mcp_catalog.APPS if a["id"] != "notion"]])
    session, url = start(tmp_path, [])
    out = call(url + "/api/mcp/connect", {"app": "notion"})
    assert next(a for a in out["apps"] if a["id"] == "notion")["status"] == "needs-auth"
    login = call(url + "/api/mcp/login", {"name": "notion"})
    assert call(url + "/api/mcp/apps")["logins"]["notion"]["status"] == "waiting"
    assert "Connected" in browser(login["url"])
    wait_for(lambda: session.mcp_logins["notion"]["status"] == "connected")
    assert "mcp__notion__search" in [t["name"] for t in session.agent.tools]
    wait_for(lambda: any(e.get("type") == "mcp_login" for e in session.history))
    call(url + "/api/mcp/logout", {"name": "notion"})
    assert next(a for a in call(url + "/api/mcp/apps")["apps"] if a["id"] == "notion")["status"] == "needs-auth"
    call(url + "/api/mcp/remove", {"name": "notion"})
    assert "notion" not in json.loads(mcp.user_config_path().read_text()).get("mcpServers", {})


def test_cli_connect_signs_in(tmp_path, monkeypatch, capsys):
    from docks import cli, mcp_catalog
    app = FakeApp()
    notion = {**mcp_catalog.find("notion"), "spec": {"type": "http", "url": app.url + "/mcp"}}
    monkeypatch.setattr(mcp_catalog, "APPS", [notion])
    monkeypatch.setattr("webbrowser.open", lambda u: threading.Thread(target=browser, args=(u,), daemon=True).start())
    assert cli.main(["mcp", "connect", "notion", "-C", str(tmp_path)]) == 0
    assert "signed in to notion" in capsys.readouterr().out
    assert cli.main(["mcp", "apps", "-C", str(tmp_path)]) == 0
    assert "connected" in capsys.readouterr().out
