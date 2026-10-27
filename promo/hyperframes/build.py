"""Write the HyperFrames project for "The Interview": index.html + one composition per chapter, from script.json, timings.json and the shots below."""
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image

import build_lib as L
from build_lib import W, H, j
from shots import CHAPTERS

P = Path(__file__).parent
script = {c["id"]: c for c in json.load(open(P / "script.json"))["chapters"]}
timings = json.load(open(P / "timings.json"))
order = [c["id"] for c in json.load(open(P / "script.json"))["chapters"]]

# grain, made once and seeded
if not (P / "assets/grain.png").exists():
    rng = np.random.default_rng(7)
    Image.fromarray((rng.normal(128, 40, (256, 256))).clip(0, 255).astype("uint8")).save(P / "assets/grain.png")

WHOOSH = ["whoosh", "whoosh-short"]
SFX_LEN = {k: v["duration"] for k, v in json.load(open(Path.home() / ".claude/skills/media-use/audio/assets/sfx/manifest.json")).items()}


def bt(cid, i, edge="start"):
    return timings[cid]["beats"][i][edge]


def product(c, cid, spec, t_in, t_out):
    """The real UI, full-bleed, with camera moves, screen swaps, the cursor and a peeking Bowie."""
    k = c.k
    shots = spec["shots"]
    names = []
    for s in shots:
        if s["screen"] not in names:
            names.append(s["screen"])
    imgs = "".join(f'<img id="{k}-sc{i}" class="{k}-sc" src="assets/screens/{n}.webp" alt="Bowers: {n}">' for i, n in enumerate(names))
    peek = spec.get("peek", [])
    peek_html = L.bowie_html(c, "pk", sorted({p for pk in peek for _, p in pk["plan"]})) if peek else ""
    c.css.append(f"""
  #{k}-prod {{ position:absolute; inset:0; overflow:hidden; background:#0b0d11; }}
  #{k}-cam {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; transform-origin:0 0; }}
  .{k}-sc {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; opacity:0; }}""")
    if peek:
        L.bowie_css(c, "pk", 40, H - 330, 380)
    c.html.append(f'<div id="{k}-prod" class="clip" data-start="{t_in:.3f}" data-duration="{t_out - t_in:.3f}"><div id="{k}-cam">{imgs}</div>'
                  f'{spec.get("prod_extra_html", "")}{peek_html}{L.cursor_html(c)}</div>')
    cur = None
    for n, s in enumerate(shots):
        t = s["t"]
        i = names.index(s["screen"])
        sc, x, y = L.focus(s.get("focus"))
        if n == 0:
            c.tw(f'tl.set("#{k}-sc{i}", {{ opacity: 1 }}, {t_in:.3f});')
            c.tw(f'tl.set("#{k}-cam", {{ scale: 1, x: 0, y: 0 }}, {t_in:.3f});')
            if s.get("focus"):
                L.cam(c, f"#{k}-cam", max(t, t_in + 0.25), s.get("dur", 0.8), sc, x, y)
            cur = i
            continue
        swap = s.get("swap", "move")
        if i != cur:
            if swap == "cut":  # a hard cut on the click: the new screen comes in slightly large and settles
                c.tw(f'tl.set("#{k}-sc{cur}", {{ opacity: 0 }}, {t:.3f}); tl.set("#{k}-sc{i}", {{ opacity: 1, x: 0, filter: "blur(0px)" }}, {t:.3f});')
                c.tw(f'tl.set("#{k}-cam", {{ scale: {sc * 1.04:.4f}, x: {x - 20}, y: {y - 12} }}, {t:.3f}); tl.to("#{k}-cam", {{ scale: {sc}, x: {x}, y: {y}, duration: 0.45, ease: "expo.out" }}, {t:.3f});')
            elif swap == "whip":
                c.tw(f'tl.to("#{k}-sc{cur}", {{ x: -260, filter: "blur(18px)", opacity: 0, duration: 0.16, ease: "power3.in" }}, {t - 0.16:.3f});')
                c.tw(f'tl.set("#{k}-sc{i}", {{ x: 260, filter: "blur(18px)", opacity: 1 }}, {t:.3f}); tl.to("#{k}-sc{i}", {{ x: 0, filter: "blur(0px)", duration: 0.2, ease: "power3.out" }}, {t:.3f});')
                c.tw(f'tl.set("#{k}-cam", {{ scale: {sc}, x: {x}, y: {y} }}, {t:.3f});')
                c.cue(t - 0.12, WHOOSH[n % 2], 0.35)
            else:  # blur swap on one stage: the app changes state
                c.tw(f'tl.to("#{k}-sc{cur}", {{ opacity: 0, filter: "blur(8px)", duration: 0.18, ease: "power2.in" }}, {t - 0.18:.3f});')
                c.tw(f'tl.set("#{k}-sc{i}", {{ opacity: 0, x: 0, filter: "blur(8px)" }}, {t:.3f}); tl.to("#{k}-sc{i}", {{ opacity: 1, filter: "blur(0px)", duration: 0.16, ease: "power2.out" }}, {t:.3f});')
                L.cam(c, f"#{k}-cam", t - 0.18, s.get("dur", 0.7), sc, x, y)
            cur = i
        else:
            L.cam(c, f"#{k}-cam", t, s.get("dur", 0.8), sc, x, y)
        if s.get("sfx"):
            c.cue(t + s.get("sfx_at", 0), s["sfx"], s.get("vol", 0.45))
    # the cursor works in frame px; a shot's cursor point is given in screen CSS px under that shot's camera
    moves = []
    for s in shots:
        for cu in s.get("cursor", []):
            sc, x, y = L.focus(s.get("focus"))
            fx, fy = x + sc * cu["x"] * L.SCREEN_SCALE - 8, y + sc * cu["y"] * L.SCREEN_SCALE - 5
            moves.append((cu["t"], round(fx, 1), round(fy, 1), cu.get("click", True)))
    L.cursor_js(c, moves)
    for pk in peek:
        L.bowie_act(c, "pk", pk["plan"], enter=(pk["plan"][0][0] - 0.15, 420), exit_=(pk["out"], 460) if pk.get("out") else None, breathe=False)
    return names


def chapter(cid, spec, prev_minutes):
    D = timings[cid]["duration"]
    c = L.Chapter(cid, D)
    k = c.k
    meta = script[cid]
    mins = L.minutes(meta["clock"], prev_minutes)
    sky = spec.get("sky") or L.sky_for(mins)
    night = sky == "night"
    L.office_css(c, sky, night)
    if meta.get("q"):
        zq = spec.get("zoom")
        q_out = spec.get("q_out") or ((timings[cid]["beats"][zq]["start"] - 0.75 if isinstance(zq, int) else zq) if zq is not None else None)
        L.question_js(c, meta["q"], spec.get("accent", meta["q"].split()[-1].strip("?")), at=0.35, out=q_out)
    msgs = [(b["start"], b["text"]) for b in timings[cid]["beats"] if b["kind"] == "msg"]
    L.phone_js(c, f"{meta['clock']}", msgs)
    L.clock_js(c, prev_minutes if prev_minutes is not None else mins, mins)
    ob = spec.get("office_bowie")  # Bowie behind the laptop (or wherever the chapter puts him)
    if ob:
        L.bowie_css(c, "ob", *ob.get("at", (760, 168, 400)))
    screens = spec.get("laptop_screens", [])
    back = spec.get("office_back_html", "")
    front = spec.get("office_front_html", "")
    back = back(c) if callable(back) else back
    front = front(c) if callable(front) else front
    office = L.office_html(c, screens=screens, laptop=spec.get("laptop", True), phone=True, lamp=spec.get("lamp", True),
                           extra_back=back, extra_front=front)
    office = office.replace(f'<h2 id="{k}-q"></h2>', f'<h2 id="{k}-q">{getattr(c, "qspans", "")}</h2>')
    office = office.replace(f'<div id="{k}-ptime"></div>', f'<div id="{k}-ptime">{c.phone_time}</div>')
    office = office.replace(f'<div id="{k}-bubs"></div>', f'<div id="{k}-bubs">{getattr(c, "phone_bubbles", "")}</div>')
    if ob:
        office = office.replace(f'<div id="{k}-bowie"></div>', L.bowie_html(c, "ob", sorted({p for _, p in ob["plan"]})))
    c.html.insert(0, f'<div id="{k}-office" class="clip" data-start="0" data-duration="{D:.3f}">{office}</div>')
    if ob:
        L.bowie_act(c, "ob", ob["plan"], enter=ob.get("enter"))
    # the office camera: push in on the phone while a text is read
    for b in timings[cid]["beats"]:
        if b["kind"] == "msg" and spec.get("phone_push", True):
            s, x, y = L.office_focus(L.PHONE)
            L.cam(c, f"#{k}-ocam", b["start"] - 0.35, 0.6, s, x, y)
            if not spec.get("hold_phone_after", False):
                L.cam(c, f"#{k}-ocam", b["end"] - 0.45, 0.6, 1, 0, 0)
    for line in spec.get("office_js", []):
        c.tw(line(c) if callable(line) else line)
    # into the laptop and back out
    zoom = spec.get("zoom")
    if zoom is not None:
        tz = bt(cid, zoom) - 0.75 if isinstance(zoom, int) else zoom
        s, x, y = L.laptop_zoom()
        c.tw(f'tl.to("#{k}-ocam", {{ scale: {s}, x: {x}, y: {y}, duration: 0.75, ease: "power3.in" }}, {tz:.3f});')
        c.cue(tz + 0.3, "whoosh", 0.4)
        t_in = tz + 0.75
        pull = spec.get("pull")
        t_out = (bt(cid, pull) if isinstance(pull, int) else pull) if pull is not None else D
        for sh in spec["shots"]:
            if isinstance(sh["t"], tuple):  # (beat index, offset)
                sh["t"] = bt(cid, sh["t"][0]) + sh["t"][1]
            for cu in sh.get("cursor", []):
                if isinstance(cu["t"], tuple):
                    cu["t"] = bt(cid, cu["t"][0]) + cu["t"][1]
        if spec["shots"][0]["t"] < t_in:
            spec["shots"][0]["t"] = t_in
        names = product(c, cid, spec, t_in, t_out)
        if pull is not None:
            last = names.index(spec["shots"][-1]["screen"])
            c.tw(f'tl.set("#{k}-ls0", {{ opacity: 0 }}, {t_out:.3f});')
            if len(screens) > 1:
                c.tw(f'tl.set("#{k}-ls1", {{ opacity: 1 }}, {t_out:.3f});')
            c.tw(f'tl.to("#{k}-ocam", {{ scale: 1, x: 0, y: 0, duration: 0.85, ease: "power3.out" }}, {t_out:.3f});')
            c.cue(t_out, "whoosh-short", 0.35)
    if screens:
        c.tw(f'tl.set("#{k}-ls0", {{ opacity: 1 }}, 0);')
    if spec.get("top_html"):
        c.html.append(spec["top_html"](c) if callable(spec["top_html"]) else spec["top_html"])
    if spec.get("css"):
        c.css.append(spec["css"](c) if callable(spec["css"]) else spec["css"])
    for line in spec.get("js", []):
        c.tw(line(c) if callable(line) else line)
    for t, name, vol in spec.get("sfx", []):
        c.cue(t if not isinstance(t, tuple) else bt(cid, t[0]) + t[1], name, vol)
    return c, mins


def write(c):
    body = "\n".join(c.html)
    js = "\n".join(c.js)
    (P / "compositions" / f"{c.cid}.html").write_text(f"""<template>
<style>
  #root {{ position:absolute; inset:0; overflow:hidden; background:#2E6B66; font-family:Inter, sans-serif; }}
{''.join(c.css)}
</style>
<div id="root" data-composition-id="{c.cid}" data-width="{W}" data-height="{H}">
{body}
</div>
<script>
const tl = gsap.timeline({{ paused: true }});
{js}
window.__timelines["{c.cid}"] = tl;
</script>
</template>
""")


def main():
    (P / "compositions").mkdir(exist_ok=True)
    hosts, audio, t, prev, lanes = [], [], 0.0, None, []
    sfx_n = 0
    for cid in order:
        spec = CHAPTERS[cid]
        c, prev = chapter(cid, spec, prev)
        write(c)
        D = timings[cid]["duration"]
        hosts.append(f'<div id="{cid}" data-composition-id="{cid}" data-composition-src="compositions/{cid}.html" data-start="{t:.3f}" '
                     f'data-duration="{D:.3f}" data-track-index="1" data-track-kind="graphics" data-width="{W}" data-height="{H}"></div>')
        audio.append(f'<audio id="vo-{c.k}" class="clip" src="assets/voice/{cid}.wav" data-start="{t:.3f}" data-duration="{D:.3f}" data-track-index="2" data-volume="1"></audio>')
        for (st, name, vol) in sorted(c.sfx):
            sfx_n += 1
            a, d = t + st, min(SFX_LEN[name], c.D - st)
            lane = next(i for i in range(len(lanes) + 1) if i == len(lanes) or lanes[i] <= a)
            if lane == len(lanes):
                lanes.append(0)
            lanes[lane] = a + d + 0.01
            audio.append(f'<audio id="fx{sfx_n}" class="clip" src="assets/sfx/{name}.mp3" data-start="{a:.3f}" data-duration="{d:.3f}" data-track-index="{3 + lane}" data-volume="{vol}"></audio>')
        t += D
    total = round(t, 3)
    (P / "index.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><title>Bowers: The Interview</title>
<script src="assets/gsap.min.js"></script>
<style>html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:#2E6B66;font-family:Inter,sans-serif}}</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="{W}" data-height="{H}">
{chr(10).join(hosts)}
{chr(10).join(audio)}
</div>
<script>window.__timelines = window.__timelines || {{}}; window.__timelines["main"] = gsap.timeline({{ paused: true }});</script>
</body></html>
""")
    print("film", total, "s", sfx_n, "effects")


if __name__ == "__main__":
    main()
