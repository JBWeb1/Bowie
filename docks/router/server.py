"""HTTP front end: Anthropic- and OpenAI-compatible endpoints over the routing engine."""

import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import translate
from .engine import ClientError, Engine, Exhausted


def iter_sse(resp):
    """Parse an upstream SSE stream into JSON payloads."""
    data = []
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line:
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            continue
        if data:
            text, data = "\n".join(data), []
            if text == "[DONE]":
                return
            yield json.loads(text)
    if data and data[0] != "[DONE]":
        yield json.loads("\n".join(data))


def tap_usage(payloads, usage: dict):
    """Pass payloads through while recording token usage from either format."""
    for p in payloads:
        if p.get("type") == "message_start":
            u = p["message"].get("usage", {})
            usage["input_tokens"] = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
        elif p.get("type") == "message_delta":
            usage["output_tokens"] = p.get("usage", {}).get("output_tokens", 0)
        elif p.get("usage"):
            usage["input_tokens"] = p["usage"].get("prompt_tokens", 0)
            usage["output_tokens"] = p["usage"].get("completion_tokens", 0)
        yield p


def make_handler(engine: Engine, client_key: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DocksRouter/0.1"

        def log_message(self, fmt, *args):  # quiet; the dashboard has the log
            pass

        # ------------------------------------------------------- helpers

        def _send_json(self, status: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str, fmt: str) -> None:
            if fmt == "anthropic":
                kind = {401: "authentication_error", 503: "overloaded_error"}.get(status, "api_error")
                self._send_json(status, {"type": "error", "error": {"type": kind, "message": message}})
            else:
                self._send_json(status, {"error": {"message": message, "type": "router_error"}})

        def _authorized(self) -> bool:
            if not client_key:
                return True
            given = self.headers.get("x-api-key") or self.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(given.encode(), client_key.encode())

        def _start_sse(self) -> None:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()

        def _sse(self, data, event: str | None = None) -> None:
            out = (f"event: {event}\n" if event else "") + f"data: {data if isinstance(data, str) else json.dumps(data)}\n\n"
            self.wfile.write(out.encode())
            self.wfile.flush()

        # -------------------------------------------------------- routes

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/health":
                return self._send_json(200, {"ok": True})
            if path == "/":
                body = DASHBOARD.encode()
                self.send_response(200)
                self.send_header("content-type", "text/html; charset=utf-8")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            if not self._authorized():
                return self._error(401, "invalid router key", "openai")
            if path == "/api/stats":
                return self._send_json(200, {
                    **engine.stats.snapshot(), "cooldowns": engine.health.snapshot(),
                    "providers": {n: {"type": p.type, "available": p.available, "local": p.local}
                                  for n, p in engine.providers.items()}})
            if path == "/v1/models":
                return self._send_json(200, {"object": "list", "data": [
                    {"id": m, "object": "model", "type": "model", "display_name": m, "owned_by": "docks-router"}
                    for m in engine.models()]})
            self._error(404, "not found", "openai")

        def do_POST(self):
            path = self.path.split("?")[0]
            fmt = {"/v1/messages": "anthropic", "/v1/messages/count_tokens": "anthropic",
                   "/v1/chat/completions": "openai", "/chat/completions": "openai"}.get(path)
            if not fmt:
                return self._error(404, f"unsupported endpoint {path}", "openai")
            if not self._authorized():
                return self._error(401, "invalid router key", fmt)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            except json.JSONDecodeError:
                return self._error(400, "request body is not valid JSON", fmt)
            headers = {k.lower(): v for k, v in self.headers.items()}
            if path.endswith("count_tokens"):
                return self._count_tokens(body, headers)
            self._proxy(fmt, body, headers)

        def _count_tokens(self, body, headers):
            try:
                _, resp = engine.dispatch("anthropic", body, headers, path="/count_tokens")
                return self._send_json(200, json.loads(resp.read()))
            except (Exhausted, ClientError):
                # No Anthropic provider reachable: a rough estimate keeps clients working.
                return self._send_json(200, {"input_tokens": len(json.dumps(body)) // 4})

        def _proxy(self, fmt: str, body: dict, headers: dict):
            started = time.monotonic()
            requested = body.get("model", "")
            try:
                target, resp = engine.dispatch(fmt, body, headers)
            except ClientError as e:
                engine.stats.record(requested=requested, target=None, ok=False, status=e.status)
                self.send_response(e.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(e.body)))
                self.end_headers()
                return self.wfile.write(e.body)
            except Exhausted as e:
                engine.stats.record(requested=requested, target=None, ok=False, status=503, error=str(e)[:500])
                return self._error(503, str(e), fmt)

            upstream_fmt = target.provider.type
            usage = {"input_tokens": 0, "output_tokens": 0}
            ok = True
            try:
                with resp:
                    if body.get("stream"):
                        self._stream(fmt, upstream_fmt, resp, target, body, usage)
                    else:
                        self._respond(fmt, upstream_fmt, json.loads(resp.read()), target, usage)
            except (BrokenPipeError, ConnectionResetError):
                ok = False  # client went away
            except Exception as e:  # mid-stream upstream failure: too late to fail over
                ok = False
                try:
                    if fmt == "anthropic":
                        self._sse({"type": "error", "error": {"type": "api_error", "message": str(e)}}, "error")
                    else:
                        self._sse({"error": {"message": str(e)}})
                except OSError:
                    pass
            engine.stats.record(requested=requested, target=target.label, ok=ok, status=200 if ok else 502,
                                latency_s=round(time.monotonic() - started, 2), **usage)

        def _respond(self, fmt, upstream_fmt, data, target, usage):
            if fmt != upstream_fmt:
                data = (translate.openai_to_anthropic_response(data, target.model) if fmt == "anthropic"
                        else translate.anthropic_to_openai_response(data, target.model))
            u = data.get("usage") or {}
            usage["input_tokens"] = u.get("input_tokens", u.get("prompt_tokens", 0))
            usage["output_tokens"] = u.get("output_tokens", u.get("completion_tokens", 0))
            self._send_json(200, data)

        def _stream(self, fmt, upstream_fmt, resp, target, body, usage):
            payloads = tap_usage(iter_sse(resp), usage)
            self._start_sse()
            if fmt == "anthropic":
                events = (((p.get("type"), p) for p in payloads) if upstream_fmt == "anthropic"
                          else translate.openai_stream_to_anthropic(payloads, target.model))
                for name, data in events:
                    self._sse(data, name)
            else:
                include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
                chunks = (payloads if upstream_fmt == "openai"
                          else translate.anthropic_stream_to_openai(payloads, target.model, include_usage))
                for chunk in chunks:
                    self._sse(chunk)
                self._sse("[DONE]")

    return Handler


def serve(cfg: dict) -> None:
    engine = Engine(cfg)
    client_key = os.environ.get(cfg.get("client_key_env") or "", "") or None
    host, port = cfg.get("host", "127.0.0.1"), cfg.get("port", 8787)
    if host not in ("127.0.0.1", "localhost", "::1") and not client_key:
        raise SystemExit(f"refusing to listen on {host} without a client key; set {cfg.get('client_key_env')}")
    server = ThreadingHTTPServer((host, port), make_handler(engine, client_key))
    available = [n for n, p in engine.providers.items() if p.available and not p.local]
    print(f"Docks router listening on http://{host}:{port}")
    print(f"  providers with keys: {', '.join(available) or 'none'}  (+ local: ollama, lmstudio)")
    print(f"  routes: {', '.join(engine.routes)}   dashboard: http://{host}:{port}/")
    print(f"  client auth: {'on' if client_key else 'off (localhost only)'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


DASHBOARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Docks Router</title>
<style>
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--line:#e7e5e4;--ok:#15803d;--bad:#b91c1c;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--fg:#f5f5f4;--muted:#a8a29e;--line:#292524;--ok:#4ade80;--bad:#f87171;--card:#1c1917}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1100px;margin:auto}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 8px}.muted{color:var(--muted)}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%}td,th{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-weight:600;color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}input{padding:6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
</style></head><body>
<h1>Docks Router</h1><div class="muted" id="sub">loading…</div>
<p><input id="key" type="password" placeholder="router key (if set)" size="30"></p>
<h2>Providers</h2><div class="wrap"><table id="prov"></table></div>
<h2>Usage by target</h2><div class="wrap"><table id="tot"></table></div>
<h2>Recent requests</h2><div class="wrap"><table id="rec"></table></div>
<script>
const k=document.getElementById('key');try{k.value=localStorage.getItem('rk')||''}catch(e){}
k.onchange=()=>{try{localStorage.setItem('rk',k.value)}catch(e){}};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const row=(cells,tag='td')=>'<tr>'+cells.map(c=>`<${tag}>${c}</${tag}>`).join('')+'</tr>';
async function tick(){
 try{
  const r=await fetch('/api/stats',{headers:{'x-api-key':k.value}});
  if(!r.ok){document.getElementById('sub').textContent='enter the router key';return}
  const s=await r.json();
  document.getElementById('sub').textContent=`up ${Math.round(s.uptime_s/60)} min`;
  document.getElementById('prov').innerHTML=row(['provider','type','status','cooldown'],'th')+Object.entries(s.providers).map(([n,p])=>{
   const c=s.cooldowns[n];return row([esc(n),esc(p.type)+(p.local?' (local)':''),p.available?'<span class=ok>ready</span>':'<span class=muted>no key</span>',c?`<span class=bad>${c.cooldown_s}s</span> <span class=muted>${esc(c.last_error).slice(0,80)}</span>`:''])}).join('');
  document.getElementById('tot').innerHTML=row(['target','requests','errors','input tok','output tok','avg latency'],'th')+Object.entries(s.totals).map(([n,t])=>row([esc(n),t.requests,t.errors,t.input_tokens.toLocaleString(),t.output_tokens.toLocaleString(),(t.latency_s/Math.max(t.requests,1)).toFixed(1)+'s'])).join('');
  document.getElementById('rec').innerHTML=row(['time','requested','served by','status','tokens in/out','latency'],'th')+s.recent.map(e=>row([new Date(e.time*1000).toLocaleTimeString(),esc(e.requested),esc(e.target||'—'),e.ok?'<span class=ok>ok</span>':`<span class=bad>${e.status}</span>`,`${e.input_tokens||0} / ${e.output_tokens||0}`,e.latency_s!=null?e.latency_s+'s':''])).join('');
 }catch(e){document.getElementById('sub').textContent='router unreachable'}
}
tick();setInterval(tick,3000);
</script></body></html>"""
