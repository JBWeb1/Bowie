"""A step-by-step record of every session, for replay and export.

Each session writes ~/.docks/sessions/<id>.events.jsonl next to its saved conversation: your messages, Bowers'
replies, every tool call with its result and how long it took, what helpers did, and the observer's checks.
Replay it with `bowers replay` (or Replay in the browser's History) and export it as Markdown, HTML or JSON.
"""

import html
import json
import sys
import threading
import time
from pathlib import Path

from . import sessions

CLIP = 4000  # characters of each tool result kept in the log
_lock = threading.Lock()


def path(session_id: str) -> Path:
    return sessions.sessions_dir() / f"{session_id}.events.jsonl"


def clip(value, limit: int = CLIP):
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"… ({len(text) - limit} more characters)"


def append(session_id: str, event: dict) -> None:
    p = path(session_id)
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(event, default=str) + "\n")


def load(session_id: str) -> list[dict]:
    p = path(session_id)
    if not p.is_file():
        if not (sessions.sessions_dir() / f"{session_id}.json").is_file():
            raise FileNotFoundError(f"no saved session {session_id!r}")
        return []  # saved before Bowers kept event logs
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line cut off by a crash
    return out


# ---------------------------------------------------------------- describing events

def _args_line(args) -> str:
    if not isinstance(args, dict):
        return clip(args, 200)
    if isinstance(args.get("items"), list):
        done = sum(isinstance(i, dict) and i.get("status") == "done" for i in args["items"])
        return f"{done} of {len(args['items'])} steps done"
    for key in ("command", "path", "pattern", "url", "query", "description", "prompt"):
        if args.get(key):
            return clip(str(args[key]), 200)
    return clip(args, 200)


def describe(e: dict) -> tuple[str, str, str]:
    """(icon, headline, detail) for one event."""
    who = f"[{e['by']}] " if e.get("by") else ""
    k = e.get("kind")
    if k == "turn_start":
        return "›", "You", e.get("text", "")
    if k == "reply":
        return "◆", who + "Bowers", e.get("text", "")
    if k == "tool_call":
        return "⚙", f"{who}{e.get('name')}  {_args_line(e.get('args'))}", ""
    if k == "tool_result":
        mark = "✗" if not e.get("ok") else "✓"
        ms = e.get("ms")
        return mark, f"{who}{e.get('name')} {'failed' if not e.get('ok') else 'done'}" + (f" in {ms / 1000:.1f}s" if ms else ""), e.get("output", "")
    if k == "observer":
        lines = [f"- {f.get('kind', 'note')}: {f.get('text', '')}" + (f" → {f['action']}" if f.get("action") else "")
                 for f in e.get("findings", [])]
        return "◉", "Observer: " + e.get("summary", ""), "\n".join(lines)
    if k == "turn_end":
        return "■", "Turn finished" if e.get("ok", True) else "Turn stopped: " + e.get("error", ""), ""
    return "·", k or "event", clip({x: y for x, y in e.items() if x not in ("t", "kind")}, 500)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def counts(s: dict) -> str:
    return f"{plural(s['turns'], 'message')} · {plural(s['tool_calls'], 'action')} ({s['failed']} failed)"


def summary(events: list[dict]) -> dict:
    calls = [e for e in events if e.get("kind") == "tool_call"]
    return {"turns": sum(e.get("kind") == "turn_start" for e in events), "tool_calls": len(calls),
            "failed": sum(e.get("kind") == "tool_result" and not e.get("ok") for e in events),
            "start": events[0]["t"] if events else None, "end": events[-1]["t"] if events else None,
            "observer_concerns": sum(len(e.get("findings", [])) for e in events if e.get("kind") == "observer")}


# ---------------------------------------------------------------- export

def to_markdown(session: dict, events: list[dict]) -> str:
    s = summary(events)
    out = [f"# {session.get('name') or session.get('title') or session.get('id')}", "",
           f"Project `{session.get('root', '')}` · model {session.get('model', '')} · {counts(s)}", ""]
    for e in events:
        icon, head, detail = describe(e)
        stamp = time.strftime("%H:%M:%S", time.localtime(e.get("t", 0)))
        if e.get("kind") == "turn_start":
            out += ["---", "", f"**You** · {stamp}", "", detail, ""]
        elif e.get("kind") == "reply":
            out += [f"**{head}** · {stamp}", "", detail, ""]
        else:
            out.append(f"- `{stamp}` {icon} {head}")
            if detail:
                fence = "````" if "```" in detail else "```"
                out += ["", f"  {fence}", *("  " + line for line in detail.splitlines()), f"  {fence}", ""]
    return "\n".join(out) + "\n"


HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#f6f1ea;--card:#fffdf9;--fg:#2a2522;--muted:#7b716a;--line:#e7ddd2;--accent:#d06b46;--ok:#3f8f6b;--bad:#c2463a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1d1a18;--card:#27231f;--fg:#efe8e1;--muted:#a59a90;--line:#3a332d}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:24px 16px 120px}} h1{{font-size:22px;margin:0 0 4px}} .meta{{color:var(--muted);font-size:13px}}
.ev{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:8px 0}}
.ev.you{{border-left:4px solid var(--accent)}} .ev.observer{{border-left:4px solid #8a6bd0}} .ev.bad .h{{color:var(--bad)}}
.h{{font-weight:600;display:flex;gap:8px}} .h time{{margin-left:auto;color:var(--muted);font-weight:400;font-size:12px}}
pre{{white-space:pre-wrap;word-break:break-word;font-size:12.5px;background:var(--bg);padding:8px;border-radius:8px;max-height:320px;overflow:auto;margin:6px 0 0}}
.txt{{white-space:pre-wrap;margin-top:4px}} .hidden{{display:none}}
nav{{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;align-items:center}}
nav button{{border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:8px;padding:6px 12px;cursor:pointer}}
nav input{{flex:1;accent-color:var(--accent)}} nav span{{color:var(--muted);font-size:13px;min-width:70px;text-align:right}}
</style></head><body><main><h1>{title}</h1><div class="meta">{meta}</div>{body}</main>
<nav><button id="prev">◀</button><button id="play">Play</button><button id="next">▶</button><input type="range" id="pos" min="0" value="0"><span id="count"></span><button id="all">Show all</button></nav>
<script>
const evs=[...document.querySelectorAll('.ev')],pos=document.getElementById('pos'),count=document.getElementById('count');let timer=null;
pos.max=evs.length;function show(n){{n=Math.max(0,Math.min(evs.length,n));pos.value=n;evs.forEach((e,i)=>e.classList.toggle('hidden',i>=n));count.textContent=n+' / '+evs.length;if(n&&evs[n-1])evs[n-1].scrollIntoView({{block:'nearest'}})}}
document.getElementById('prev').onclick=()=>show(+pos.value-1);document.getElementById('next').onclick=()=>show(+pos.value+1);
document.getElementById('all').onclick=()=>show(evs.length);pos.oninput=()=>show(+pos.value);
document.getElementById('play').onclick=e=>{{if(timer){{clearInterval(timer);timer=null;e.target.textContent='Play';return}}if(+pos.value>=evs.length)show(0);e.target.textContent='Pause';timer=setInterval(()=>{{if(+pos.value>=evs.length){{clearInterval(timer);timer=null;e.target.textContent='Play';return}}show(+pos.value+1)}},700)}};
show(evs.length);
</script></body></html>
"""


def to_html(session: dict, events: list[dict]) -> str:
    s = summary(events)
    title = html.escape(session.get("name") or session.get("title") or session.get("id", "Session"))
    meta = html.escape(f"{session.get('root', '')} · {session.get('model', '')} · {counts(s)}")
    parts = []
    for e in events:
        icon, head, detail = describe(e)
        k = e.get("kind")
        cls = {"turn_start": "you", "observer": "observer"}.get(k, "") + (" bad" if k == "tool_result" and not e.get("ok") else "")
        stamp = time.strftime("%H:%M:%S", time.localtime(e.get("t", 0)))
        body = (f'<div class="txt">{html.escape(detail)}</div>' if k in ("turn_start", "reply")
                else f"<pre>{html.escape(detail)}</pre>" if detail else "")
        parts.append(f'<div class="ev {cls}"><div class="h"><span>{html.escape(icon)}</span><span>{html.escape(head)}</span>'
                     f"<time>{stamp}</time></div>{body}</div>")
    return HTML.format(title=title, meta=meta, body="\n".join(parts))


def export(session_id: str, fmt: str = "md") -> str:
    session = sessions.load(session_id)
    events = load(session_id)
    if fmt == "json":
        return json.dumps({"session": {k: session.get(k) for k in ("id", "name", "title", "root", "model", "created")},
                           "summary": summary(events), "events": events}, indent=2, default=str)
    if fmt == "html":
        return to_html(session, events)
    if fmt in ("md", "markdown"):
        return to_markdown(session, events)
    raise ValueError("export as md, html or json")


# ---------------------------------------------------------------- terminal replay

def replay(events: list[dict], out=None, step: bool = False, delay: float = 0.0) -> None:
    from . import ui
    out = out or sys.stdout
    for i, e in enumerate(events):
        icon, head, detail = describe(e)
        stamp = time.strftime("%H:%M:%S", time.localtime(e.get("t", 0)))
        k = e.get("kind")
        color = ui.bold if k in ("turn_start", "reply") else ui.red if k == "tool_result" and not e.get("ok") else ui.dim
        out.write(f"{ui.dim(stamp)} {icon} {color(head)}\n")
        if detail:
            lines = detail.splitlines()
            limit = 1000 if k in ("turn_start", "reply", "observer") else 6
            for line in lines[:limit]:
                out.write(f"           {line}\n")
            if len(lines) > limit:
                out.write(ui.dim(f"           … {len(lines) - limit} more lines\n"))
        out.flush()
        if step and i < len(events) - 1:
            try:
                if input(ui.dim("  [enter] next · q quit ")).strip().lower() == "q":
                    return
            except EOFError:
                return
        elif delay:
            time.sleep(delay)
