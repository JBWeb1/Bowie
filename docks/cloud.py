"""Bowers Cloud: Bowie with no key and nothing to download, the way Claude and ChatGPT work.

You (the owner) run this server with one Anthropic key. People sign in from the Bowers app (`bowers login`, or
Settings > How should Bowie think? > Bowers Cloud); the app then sends its requests here with a Bowers Cloud token
instead of a key. The server checks the account, its credits and its rate limit, passes the request to Claude,
counts the tokens it used and takes that cost from the account. Prompts and code are passed through, never stored.

    bowers cloud serve [--host 0.0.0.0 --port 8790 --db cloud.db]   needs ANTHROPIC_API_KEY on the server
    bowers cloud invite [--credits 5]      an invite code worth US$5 of usage, for a new account
    bowers cloud users                     accounts, balances and usage
    bowers cloud credit EMAIL DOLLARS      add (or with a minus, take) usage credit
    bowers cloud pause | resume            stop or restart all requests (the kill switch)

It is built to serve the Bowers app only: Anthropic's terms let you build products on Claude for your customers,
not resell plain API access. Only Bowers' models are allowed, and the terms of service should say so.
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# US$ per million tokens: input, output, cache read, cache write (5-minute cache: 1.25 x input)
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0), "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125), "claude-fable-5-2": (8.0, 40.0, 0.20, 10.0),
    "claude-fable-5-1": (10.0, 50.0, 1.0, 12.5),
}
RATE_PER_MINUTE = 40
UPSTREAM = os.environ.get("BOWERS_CLOUD_UPSTREAM", "https://api.anthropic.com").rstrip("/")
TOKEN_PREFIX = "bwc_"
SCHEMA = """
create table if not exists users (id integer primary key, email text unique not null, name text, pw text not null,
  balance_micro integer not null default 0, status text not null default 'active', created integer);
create table if not exists tokens (sha256 text primary key, user_id integer not null, created integer, last_used integer);
create table if not exists usage (id integer primary key, user_id integer, ts integer, model text, input integer,
  cache_read integer, cache_write integer, output integer, cost_micro integer);
create table if not exists invites (code text primary key, credit_micro integer, created integer, used_by integer, used_at integer);
create table if not exists devices (device_code text primary key, user_code text unique, created integer,
  user_id integer, token text);
create table if not exists flags (name text primary key, value text);
"""


class CloudError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def cost_micro(model: str, usage: dict) -> int:
    """What a request cost, in millionths of a US dollar."""
    p_in, p_out, p_read, p_write = PRICES.get(model, PRICES["claude-opus-5-5"])
    return round(usage.get("input_tokens", 0) * p_in + usage.get("output_tokens", 0) * p_out
                 + usage.get("cache_read_input_tokens", 0) * p_read + usage.get("cache_creation_input_tokens", 0) * p_write)


def _hash_pw(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt.hex() + ":" + digest.hex()


def _check_pw(password: str, stored: str) -> bool:
    salt, _, _ = stored.partition(":")
    return hmac.compare_digest(_hash_pw(password, bytes.fromhex(salt)), stored)


class Store:
    """Accounts, tokens, credits and usage in one SQLite file."""

    def __init__(self, path: str):
        self.path, self.lock = path, threading.Lock()
        with self._db() as db:
            db.executescript(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def q(self, sql: str, args=(), one=False):
        with self.lock, self._db() as db:
            rows = db.execute(sql, args).fetchall()
        return (rows[0] if rows else None) if one else rows

    # accounts
    def invite(self, dollars: float) -> str:
        code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        self.q("insert into invites values (?, ?, ?, null, null)", (code, round(dollars * 1e6), int(time.time())))
        return code

    def sign_in(self, email: str, password: str, name: str = "", invite: str = "") -> sqlite3.Row:
        email = email.strip().lower()
        if "@" not in email or len(password) < 8:
            raise CloudError(400, "enter your email and a password of at least 8 characters")
        user = self.q("select * from users where email = ?", (email,), one=True)
        if user:
            if not _check_pw(password, user["pw"]):
                raise CloudError(401, "wrong email or password")
            return user
        code = self.q("select * from invites where code = ? and used_by is null", (invite.strip().upper(),), one=True)
        if not code:
            raise CloudError(403, "Bowers Cloud is invite-only for now: enter a valid invite code")
        with self.lock, self._db() as db:
            cur = db.execute("insert into users (email, name, pw, balance_micro, created) values (?, ?, ?, ?, ?)",
                             (email, name.strip()[:80], _hash_pw(password), code["credit_micro"], int(time.time())))
            db.execute("update invites set used_by = ?, used_at = ? where code = ?", (cur.lastrowid, int(time.time()), code["code"]))
        return self.q("select * from users where id = ?", (cur.lastrowid,), one=True)

    def new_token(self, user_id: int) -> str:
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        self.q("insert into tokens values (?, ?, ?, null)", (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time())))
        return token

    def user_for(self, token: str):
        if not token.startswith(TOKEN_PREFIX):
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        row = self.q("select users.* from tokens join users on users.id = tokens.user_id where tokens.sha256 = ?", (digest,), one=True)
        if row:
            self.q("update tokens set last_used = ? where sha256 = ?", (int(time.time()), digest))
        return row

    def charge(self, user_id: int, model: str, usage: dict) -> int:
        cost = cost_micro(model, usage)
        with self.lock, self._db() as db:
            db.execute("update users set balance_micro = balance_micro - ? where id = ?", (cost, user_id))
            db.execute("insert into usage (user_id, ts, model, input, cache_read, cache_write, output, cost_micro) values (?,?,?,?,?,?,?,?)",
                       (user_id, int(time.time()), model, usage.get("input_tokens", 0), usage.get("cache_read_input_tokens", 0),
                        usage.get("cache_creation_input_tokens", 0), usage.get("output_tokens", 0), cost))
        return cost

    def credit(self, email: str, dollars: float) -> None:
        if not self.q("select id from users where email = ?", (email.lower(),), one=True):
            raise CloudError(404, f"no account {email}")
        self.q("update users set balance_micro = balance_micro + ? where email = ?", (round(dollars * 1e6), email.lower()))

    def paused(self) -> bool:
        row = self.q("select value from flags where name = 'paused'", one=True)
        return bool(row and row["value"] == "1")

    def set_paused(self, on: bool) -> None:
        self.q("insert or replace into flags values ('paused', ?)", ("1" if on else "0",))

    # sign-in from the app: a code the person confirms in their browser
    def start_device(self) -> dict:
        device, user = secrets.token_urlsafe(24), f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        self.q("insert into devices values (?, ?, ?, null, null)", (device, user, int(time.time())))
        return {"device_code": device, "user_code": user, "expires_in": 900, "interval": 2}

    def approve_device(self, user_code: str, user_id: int) -> None:
        row = self.q("select * from devices where user_code = ? and user_id is null", (user_code.strip().upper(),), one=True)
        if not row or time.time() - row["created"] > 900:
            raise CloudError(400, "that sign-in code has expired: start again from the Bowers app")
        self.q("update devices set user_id = ?, token = ? where device_code = ?", (user_id, self.new_token(user_id), row["device_code"]))

    def poll_device(self, device_code: str) -> dict:
        row = self.q("select devices.*, users.email from devices left join users on users.id = devices.user_id where device_code = ?",
                     (device_code,), one=True)
        if not row or time.time() - row["created"] > 900:
            raise CloudError(400, "expired")
        if not row["token"]:
            return {"status": "pending"}
        self.q("update devices set token = '' where device_code = ?", (device_code,))  # handed over once
        if row["token"] == "":
            raise CloudError(400, "already used")
        return {"status": "ok", "token": row["token"], "email": row["email"]}

    def me(self, user) -> dict:
        used = self.q("select coalesce(sum(cost_micro), 0) c, count(*) n from usage where user_id = ? and ts > ?",
                      (user["id"], int(time.time()) - 30 * 86400), one=True)
        return {"email": user["email"], "name": user["name"], "balance_usd": round(user["balance_micro"] / 1e6, 4),
                "credits": max(0, user["balance_micro"] // 10_000), "requests_30d": used["n"], "spent_30d_usd": round(used["c"] / 1e6, 4)}


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>body{{font:15px/1.5 system-ui,sans-serif;background:#faf8f4;color:#1c1a17;display:grid;place-items:center;min-height:100vh;margin:0}}
main{{background:#fff;border:1px solid #e8e4da;border-radius:16px;padding:28px;width:min(400px,92vw)}}h1{{font-size:22px;margin:0 0 6px}}
label{{display:block;font-weight:600;font-size:13px;margin:12px 0 4px}}input{{width:100%;box-sizing:border-box;padding:9px 10px;border:1px solid #d7d2c6;border-radius:9px;font:inherit}}
button{{margin-top:16px;width:100%;padding:10px;border:0;border-radius:10px;background:#d9602a;color:#fff;font:600 15px system-ui}}p.m{{color:#7a756c;font-size:13px}}.err{{color:#c4321c}}</style></head>
<body><main>{body}</main></body></html>""".encode()


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def make_handler(store: Store, upstream_key: str, upstream: str = UPSTREAM):
    hits: dict[int, list[float]] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj).encode())

        def _error(self, status: int, message: str) -> None:
            kind = {401: "authentication_error", 402: "billing_error", 403: "permission_error", 429: "rate_limit_error"}.get(status, "api_error")
            self._json(status, {"type": "error", "error": {"type": kind, "message": message}})

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("content-length") or 0))

        def _user(self):
            token = self.headers.get("x-api-key") or self.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return store.user_for(token or "")

        def _activate_form(self, code: str, error: str = "") -> None:
            self._send(200 if not error else 400, _page("Sign in to Bowers Cloud", f"""<h1>Sign in to Bowers Cloud</h1>
<p class="m">Confirm the code shown in your Bowers app: <b>{_esc(code)}</b></p>{f'<p class="err">{_esc(error)}</p>' if error else ''}
<form method="post" action="/activate"><input type="hidden" name="code" value="{_esc(code)}">
<label>Email</label><input name="email" type="email" required autocomplete="email">
<label>Password</label><input name="password" type="password" required minlength="8" autocomplete="current-password">
<label>Your name (new accounts)</label><input name="name" autocomplete="name">
<label>Invite code (new accounts)</label><input name="invite" placeholder="ABCD-1234-EF56">
<button>Sign in</button></form>"""), "text/html; charset=utf-8")

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/health":
                return self._json(200, {"ok": True, "paused": store.paused()})
            if path == "/":
                return self._send(200, _page("Bowers Cloud", "<h1>Bowers Cloud</h1><p>Bowie with no key and nothing to download. "
                                              "Sign in from the Bowers app: Settings, How should Bowie think?, Bowers Cloud.</p>"),
                                  "text/html; charset=utf-8")
            if path == "/activate":
                return self._activate_form(urllib.parse.parse_qs(query).get("code", [""])[0])
            user = self._user()
            if not user:
                return self._error(401, "sign in to Bowers Cloud from the Bowers app")
            if path == "/me":
                return self._json(200, store.me(user))
            if path.startswith("/v1/models"):
                return self._forward("GET", path, None, user)
            self._error(404, "not found")

        def do_POST(self):
            path, _, query = self.path.partition("?")
            if path == "/auth/device":
                info = store.start_device()
                host = self.headers.get("host", "localhost")
                scheme = self.headers.get("x-forwarded-proto", "http")
                return self._json(200, {**info, "verify_url": f"{scheme}://{host}/activate?code={info['user_code']}"})
            if path == "/auth/token":
                try:
                    return self._json(200, store.poll_device(str(json.loads(self._body() or b"{}").get("device_code", ""))))
                except (CloudError, ValueError) as e:
                    return self._json(400, {"status": "error", "error": str(e)})
            if path == "/activate":
                form = {k: v[0] for k, v in urllib.parse.parse_qs(self._body().decode()).items()}
                try:
                    user = store.sign_in(form.get("email", ""), form.get("password", ""), form.get("name", ""), form.get("invite", ""))
                    store.approve_device(form.get("code", ""), user["id"])
                except CloudError as e:
                    return self._activate_form(form.get("code", ""), str(e))
                return self._send(200, _page("Signed in", "<h1>You're signed in</h1><p>Go back to Bowers: Bowie is ready.</p>"),
                                  "text/html; charset=utf-8")
            if path not in ("/v1/messages", "/v1/messages/count_tokens"):
                return self._error(404, "not found")
            user = self._user()
            if not user:
                return self._error(401, "sign in to Bowers Cloud from the Bowers app")
            if store.paused():
                return self._error(503, "Bowers Cloud is paused for a moment; Bowie can use Bowers Local meanwhile")
            if user["status"] != "active":
                return self._error(403, "this account is suspended; contact Bowers support")
            raw = self._body()
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self._error(400, "request body is not valid JSON")
            if body.get("model") not in PRICES:
                return self._error(400, f"Bowers Cloud runs Bowers' models only, not {body.get('model')!r}")
            if path.endswith("count_tokens"):
                return self._forward("POST", path + (f"?{query}" if query else ""), raw, user)
            if user["balance_micro"] <= 0:
                return self._error(402, "you're out of Bowers Cloud credits: top up, or switch Bowie to Bowers Local")
            now = time.time()
            recent = [t for t in hits.get(user["id"], []) if now - t < 60]
            if len(recent) >= RATE_PER_MINUTE:
                return self._error(429, "slow down a moment: too many requests this minute")
            hits[user["id"]] = recent + [now]
            self._forward("POST", path + (f"?{query}" if query else ""), raw, user, model=body["model"], stream=bool(body.get("stream")))

        def _forward(self, method, path, raw, user, model=None, stream=False):
            headers = {"x-api-key": upstream_key, "content-type": "application/json",
                       "anthropic-version": self.headers.get("anthropic-version", "2023-06-01")}
            if self.headers.get("anthropic-beta"):
                headers["anthropic-beta"] = self.headers["anthropic-beta"]
            req = urllib.request.Request(upstream + path, data=raw, headers=headers, method=method)
            try:
                resp = urllib.request.urlopen(req, timeout=900)
            except urllib.error.HTTPError as e:
                return self._send(e.code, e.read())
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                return self._error(502, f"couldn't reach Claude: {getattr(e, 'reason', e)}")
            usage: dict = {}
            with resp:
                if not stream:
                    data = resp.read()
                    if model:
                        try:
                            usage = json.loads(data).get("usage") or {}
                        except ValueError:
                            pass
                    self._send(resp.status, data, resp.headers.get("content-type", "application/json"))
                else:
                    self.send_response(resp.status)
                    self.send_header("content-type", "text/event-stream")
                    self.send_header("cache-control", "no-cache")
                    self.send_header("connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    try:
                        for line in resp:  # pass every byte through; read the usage on the way
                            self.wfile.write(line)
                            if line.startswith(b"data: {") and b"usage" in line:
                                try:
                                    event = json.loads(line[6:])
                                except ValueError:
                                    continue
                                u = (event.get("message") or {}).get("usage") if event.get("type") == "message_start" else event.get("usage")
                                for k, v in (u or {}).items():
                                    if isinstance(v, int):
                                        usage[k] = v
                            if line == b"\n":
                                self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # the app went away; what was used is still charged below
            if model and usage:
                store.charge(user["id"], model, usage)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8790, db: str = "cloud.db") -> None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("Bowers Cloud needs ANTHROPIC_API_KEY on the server (in the host's secret settings)")
    store = Store(db)
    server = ThreadingHTTPServer((host, port), make_handler(store, key))
    print(f"Bowers Cloud on http://{host}:{port}  (accounts in {db}; {'PAUSED' if store.paused() else 'taking requests'})")
    server.serve_forever()


# ---------------------------------------------------------------- the app side: sign in, sign out, the client

def start_login(url: str) -> dict:
    """Ask a Bowers Cloud for a sign-in code: {"user_code", "verify_url", "device_code", ...}."""
    url = url.strip().rstrip("/")
    if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise CloudError(400, "a Bowers Cloud address starts with https://")
    req = urllib.request.Request(url + "/auth/device", data=b"{}", method="POST", headers={"content-type": "application/json"})
    try:
        return {**json.loads(urllib.request.urlopen(req, timeout=30).read()), "url": url}
    except (urllib.error.URLError, ValueError, OSError) as e:
        raise CloudError(502, f"couldn't reach Bowers Cloud at {url}: {getattr(e, 'reason', e)}")


def login(url: str, open_browser=None, log=print, wait: float = 900, info: dict | None = None) -> dict:
    """Sign this computer in to a Bowers Cloud; keeps the token in the vault. Returns {"email": ...}."""
    from . import vault
    info = info or start_login(url)
    url = info["url"]
    log(f"Confirm this code in your browser: {info['user_code']}\n  {info['verify_url']}")
    if open_browser:
        open_browser(info["verify_url"])
    end = time.time() + min(wait, info.get("expires_in", 900))
    while time.time() < end:
        time.sleep(info.get("interval", 2))
        poll = urllib.request.Request(url + "/auth/token", data=json.dumps({"device_code": info["device_code"]}).encode(),
                                      method="POST", headers={"content-type": "application/json"})
        try:
            got = json.loads(urllib.request.urlopen(poll, timeout=30).read())
        except urllib.error.HTTPError as e:
            raise CloudError(e.code, json.loads(e.read() or b"{}").get("error", "sign-in failed"))
        if got.get("status") == "ok":
            vault.save("BOWERS_CLOUD_URL", url)
            vault.save("BOWERS_CLOUD_TOKEN", got["token"])
            return {"email": got.get("email")}
    raise CloudError(408, "sign-in timed out: try again")


def logout() -> None:
    from . import vault
    for name in ("BOWERS_CLOUD_TOKEN", "BOWERS_CLOUD_URL"):
        vault.forget(name)
        os.environ.pop(name, None)


def signed_in() -> bool:
    return bool(os.environ.get("BOWERS_CLOUD_TOKEN") and os.environ.get("BOWERS_CLOUD_URL"))


def client_settings() -> dict:
    """How the app reaches Claude: your own key or endpoint first, else Bowers Cloud, else nothing."""
    if any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")):
        return {}
    if signed_in():
        return {"base_url": os.environ["BOWERS_CLOUD_URL"], "api_key": os.environ["BOWERS_CLOUD_TOKEN"]}
    return {}


def account() -> dict | None:
    """This computer's Bowers Cloud account (balance and use), or None."""
    if not signed_in():
        return None
    req = urllib.request.Request(os.environ["BOWERS_CLOUD_URL"].rstrip("/") + "/me",
                                 headers={"x-api-key": os.environ["BOWERS_CLOUD_TOKEN"]})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception:
        return None
