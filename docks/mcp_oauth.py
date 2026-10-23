"""Signing in to remote MCP servers (Notion, Linear, Sentry, Stripe, ...) with OAuth, the way MCP specifies:

1. The server answers 401 and points to its protected-resource metadata (RFC 9728), which names its
   authorization server; that server's metadata (RFC 8414) gives the endpoints.
2. Bowers registers itself there (dynamic client registration, RFC 7591), or uses a client ID you configured.
3. Your browser opens the sign-in page. It's an authorization-code flow with PKCE (S256), a random state, the
   resource indicator (RFC 8707) and an issuer check (RFC 9207). The reply comes back to a tiny server on
   127.0.0.1 that only lives for the sign-in.
4. Tokens are saved in ~/.docks/mcp-auth.json (only you can read it) and refreshed when they expire.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CLIENT_NAME = "Bowers"


class OAuthError(Exception):
    pass


# ---------------------------------------------------------------- token store

def store_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "mcp-auth.json"


def _load() -> dict:
    try:
        return json.loads(store_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, 0o600)


def _key(server_url: str) -> str:
    return server_url.split("#")[0].rstrip("/")


def saved(server_url: str) -> dict:
    return _load().get(_key(server_url), {})


def _update(server_url: str, **fields) -> dict:
    data = _load()
    entry = {**data.get(_key(server_url), {}), **fields}
    data[_key(server_url)] = entry
    _save(data)
    return entry


def forget(server_url: str) -> bool:
    data = _load()
    gone = data.pop(_key(server_url), None) is not None
    _save(data)
    return gone


# ---------------------------------------------------------------- HTTP helpers

def _get_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "bowers"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None


def _post(url: str, fields: dict | None = None, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else urllib.parse.urlencode(fields or {}).encode()
    kind = "application/json" if body is not None else "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"content-type": kind, "accept": "application/json", "user-agent": "bowers"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise OAuthError(f"{url} answered {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise OAuthError(f"couldn't reach {url}: {e.reason}")


def _origin(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _path(url: str) -> str:
    return urllib.parse.urlsplit(url).path.rstrip("/")


# ---------------------------------------------------------------- discovery

def resource_metadata_url(www_authenticate: str) -> str | None:
    m = re.search(r'resource_metadata="([^"]+)"', www_authenticate or "")
    return m.group(1) if m else None


def discover(server_url: str, www_authenticate: str = "") -> dict:
    """{"resource": ..., "issuer": ..., "authorization_endpoint", "token_endpoint", "registration_endpoint", "scopes"}"""
    candidates = [resource_metadata_url(www_authenticate)] if resource_metadata_url(www_authenticate) else []
    candidates += [f"{_origin(server_url)}/.well-known/oauth-protected-resource{_path(server_url)}",
                   f"{_origin(server_url)}/.well-known/oauth-protected-resource"]
    prm = next((m for m in map(_get_json, dict.fromkeys(candidates)) if m), None)
    issuer = (prm or {}).get("authorization_servers", [_origin(server_url)])[0]  # older servers are their own
    meta = None
    for url in (f"{_origin(issuer)}/.well-known/oauth-authorization-server{_path(issuer)}",
                f"{_origin(issuer)}/.well-known/openid-configuration{_path(issuer)}",
                f"{issuer.rstrip('/')}/.well-known/openid-configuration"):
        meta = _get_json(url)
        if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
            break
        meta = None
    if not meta:
        raise OAuthError(f"{server_url} asks for sign-in but doesn't say where (no OAuth metadata found)")
    if "S256" not in meta.get("code_challenge_methods_supported", ["S256"]):
        raise OAuthError("the sign-in server doesn't support PKCE (S256), so Bowers won't use it")
    resource = (prm or {}).get("resource") or server_url
    return {"resource": resource, "issuer": meta.get("issuer", issuer),
            "authorization_endpoint": meta["authorization_endpoint"], "token_endpoint": meta["token_endpoint"],
            "registration_endpoint": meta.get("registration_endpoint"),
            "scopes": (prm or {}).get("scopes_supported") or [],
            "iss_param": bool(meta.get("authorization_response_iss_parameter_supported"))}


# ---------------------------------------------------------------- the sign-in flow

class _Callback:
    """A one-off web server on 127.0.0.1 that receives the sign-in reply."""

    def __init__(self, port: int = 0):
        self.result, self.done = {}, threading.Event()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                parts = urllib.parse.urlsplit(self.path)
                if parts.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                outer.result = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
                ok = "code" in outer.result
                page = (f"<!doctype html><meta charset=utf-8><title>Bowers</title><body style='font-family:system-ui;"
                        f"background:#f6f1eb;color:#1f1d1b;display:grid;place-items:center;height:100vh;margin:0'>"
                        f"<div style='text-align:center'><h2>{'Connected' if ok else 'Sign-in didn&#39;t finish'}</h2>"
                        f"<p>{'You can close this tab and go back to Bowers.' if ok else 'Go back to Bowers and try again.'}</p></div>")
                body = page.encode()
                self.send_response(200)
                self.send_header("content-type", "text/html; charset=utf-8")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                outer.done.set()

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        except OSError:
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)  # the saved port is taken: use another
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _client_for(server_url: str, info: dict, redirect_uri: str, configured: dict) -> dict:
    if configured.get("clientId"):
        return {"client_id": configured["clientId"], "client_secret": configured.get("clientSecret")}
    entry = saved(server_url)
    client = entry.get("client") or {}
    if client.get("client_id") and redirect_uri in client.get("redirect_uris", []) and entry.get("issuer") == info["issuer"]:
        return client
    if not info.get("registration_endpoint"):
        raise OAuthError("this server doesn't let apps register themselves; add a client ID for it: "
                         '"oauth": {"clientId": "..."} in its MCP settings')
    reg = _post(info["registration_endpoint"], body={
        "client_name": CLIENT_NAME, "redirect_uris": [redirect_uri], "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none",
        **({"scope": " ".join(info["scopes"])} if info["scopes"] else {})})
    if not reg.get("client_id"):
        raise OAuthError("registering with the sign-in server failed")
    client = {"client_id": reg["client_id"], "client_secret": reg.get("client_secret"), "redirect_uris": [redirect_uri]}
    _update(server_url, client=client, issuer=info["issuer"])
    return client


class Login:
    """One sign-in: open `url` in a browser, then wait() for the result."""

    def __init__(self, server_url: str, www_authenticate: str = "", configured: dict | None = None):
        self.server_url = server_url
        self.info = discover(server_url, www_authenticate)
        port = int((saved(server_url).get("callback_port") or 0))
        self.callback = _Callback(port)
        self.redirect_uri = f"http://127.0.0.1:{self.callback.port}/callback"
        _update(server_url, callback_port=self.callback.port)
        self.client = _client_for(server_url, self.info, self.redirect_uri, configured or {})
        self.verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        self.state = secrets.token_urlsafe(24)
        params = {"response_type": "code", "client_id": self.client["client_id"], "redirect_uri": self.redirect_uri,
                  "code_challenge": challenge, "code_challenge_method": "S256", "state": self.state,
                  "resource": self.info["resource"]}
        scopes = (configured or {}).get("scopes") or self.info["scopes"]
        if scopes:
            params["scope"] = " ".join(scopes)
        sep = "&" if "?" in self.info["authorization_endpoint"] else "?"
        self.url = self.info["authorization_endpoint"] + sep + urllib.parse.urlencode(params)

    def wait(self, timeout: float = 300) -> dict:
        try:
            if not self.callback.done.wait(timeout):
                raise OAuthError("sign-in timed out; start it again")
            reply = self.callback.result
        finally:
            self.callback.close()
        if reply.get("error"):
            raise OAuthError(f"sign-in was refused: {reply.get('error_description') or reply['error']}")
        if not secrets.compare_digest(reply.get("state", ""), self.state):
            raise OAuthError("the sign-in reply didn't match (state); nothing was saved")
        if reply.get("iss") and reply["iss"] != self.info["issuer"]:
            raise OAuthError("the sign-in reply came from a different server (issuer); nothing was saved")
        if self.info["iss_param"] and not reply.get("iss"):
            raise OAuthError("the sign-in reply didn't say who sent it (issuer); nothing was saved")
        tokens = _post(self.info["token_endpoint"], {
            "grant_type": "authorization_code", "code": reply.get("code", ""), "redirect_uri": self.redirect_uri,
            "client_id": self.client["client_id"], "code_verifier": self.verifier, "resource": self.info["resource"],
            **({"client_secret": self.client["client_secret"]} if self.client.get("client_secret") else {})})
        return _keep(self.server_url, tokens, self.info, self.client)


def _keep(server_url: str, tokens: dict, info: dict, client: dict) -> dict:
    if not tokens.get("access_token"):
        raise OAuthError("the sign-in server returned no access token")
    entry = {"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token") or saved(server_url).get("tokens", {}).get("refresh_token"),
             "expires_at": time.time() + float(tokens["expires_in"]) - 30 if tokens.get("expires_in") else None}
    _update(server_url, tokens=entry, token_endpoint=info["token_endpoint"], resource=info["resource"],
            client=client, issuer=info["issuer"])
    return entry


def access_token(server_url: str) -> str | None:
    """A usable token for this server: the saved one, refreshed if it has expired. None if you need to sign in."""
    entry = saved(server_url)
    tokens = entry.get("tokens") or {}
    if not tokens.get("access_token"):
        return None
    if tokens.get("expires_at") and time.time() > tokens["expires_at"]:
        return refresh(server_url)
    return tokens["access_token"]


def refresh(server_url: str) -> str | None:
    entry = saved(server_url)
    tokens, client = entry.get("tokens") or {}, entry.get("client") or {}
    if not tokens.get("refresh_token") or not entry.get("token_endpoint"):
        return None
    try:
        fresh = _post(entry["token_endpoint"], {
            "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client.get("client_id", ""),
            "resource": entry.get("resource", server_url),
            **({"client_secret": client["client_secret"]} if client.get("client_secret") else {})})
    except OAuthError:
        return None
    return _keep(server_url, fresh, {"token_endpoint": entry["token_endpoint"], "resource": entry.get("resource", server_url),
                                     "issuer": entry.get("issuer", "")}, client)["access_token"]
