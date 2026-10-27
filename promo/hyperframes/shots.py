"""The shot list: per chapter, what Bowie does in the office, which real screens play, where the camera looks and where the cursor clicks.
Rects are in screen CSS px (the 1600x900 the app was captured at). Times are seconds in the chapter, or (beat index, offset)."""
import json
from pathlib import Path

import build_lib as L

T = json.load(open(Path(__file__).parent / "timings.json"))


def b(cid, i, edge="start"):
    return T[cid]["beats"][i][edge]


BEHIND = (232, 392, 380)   # Bowie standing on the desk beside the laptop, feet on the oak


def team_html(c):
    poses = ["analyzing", "create-video", "inspire", "solving", "research", "planning", "helping"]
    xs = [70, 330, 560, 1320, 1560, 1760, 210]
    out = []
    for i, (p, x) in enumerate(zip(poses, xs)):
        out.append(f'<img id="{c.k}-tm{i}" src="assets/bowie/{p}.png" alt="" style="position:absolute;left:{x}px;top:{470 + (i % 2) * 40}px;width:300px;height:300px">')
    return "".join(out)


def team_js(c):
    lines = []
    for i in range(7):
        t = 4.1 + i * 0.1
        lines.append(f'tl.fromTo("#{c.k}-tm{i}", {{ y: 420, scaleY: 0.8 }}, {{ y: 0, scaleY: 1, duration: 0.55, ease: "back.out(1.7)" }}, {t:.3f});')
        if i % 2 == 0:
            c.cue(t + 0.05, "pop", 0.3)
    return "\n".join(lines)


def shake_js(c, t0, t1):
    import random
    r = random.Random(4)
    out, t = [], t0
    while t < t1:
        dx, dy = r.uniform(-5, 5), r.uniform(-3, 3)
        out.append(f'tl.to(["#{c.k}-laptop", "#{c.k}-base"], {{ x: {dx:.1f}, y: {dy:.1f}, duration: 0.06, ease: "none" }}, {t:.3f});')
        t += 0.07
    out.append(f'tl.to(["#{c.k}-laptop", "#{c.k}-base"], {{ x: 0, y: 0, duration: 0.1 }}, {t:.3f});')
    return "\n".join(out)


def reel_overlay(c, t0, t1):
    """Sam's phone carries the finished reel in over the app, playing (a real HyperFrames render)."""
    k = c.k
    html = (f'<div id="{k}-rphone" class="clip" data-start="{t0:.3f}" data-duration="{t1 - t0:.3f}" '
            f'style="position:absolute;left:1290px;top:70px;width:440px;height:900px;border-radius:56px;background:#1C1C1E;box-shadow:0 40px 90px rgba(0,0,0,.55)"></div>'
            f'<video id="{k}-reel" class="clip" src="assets/media/lemon-lane-reel.mp4" muted playsinline data-start="{t0 + 0.55:.3f}" data-duration="{t1 - t0 - 0.85:.3f}" '
            f'style="position:absolute;left:1306px;top:86px;width:408px;height:868px;border-radius:44px;object-fit:cover"></video>')
    js = (f'tl.fromTo("#{k}-rphone", {{ y: 980, rotation: 6 }}, {{ y: 0, rotation: 0, duration: 0.6, ease: "expo.out" }}, {t0:.3f});\n'
          f'tl.to("#{k}-rphone", {{ y: 1000, duration: 0.3, ease: "power3.in" }}, {t1 - 0.32:.3f});')
    c.cue(t0 + 0.05, "whoosh-short", 0.35)
    return html, js


def resume_html(c):
    k = c.k
    return (f'<div id="{k}-res" style="position:absolute;left:330px;top:800px;width:330px;height:250px;background:#FBF7EE;border-radius:6px;'
            f'box-shadow:0 12px 24px rgba(0,0,0,.28);padding:22px 26px;box-sizing:border-box;font-family:Inter,sans-serif;color:#1F1D1B">'
            f'<div style="font:900 34px Inter;letter-spacing:-1px">BOWIE</div><div data-layout-ignore style="font:600 16px Inter;color:#6b6157;margin-top:2px">Applying for: Your AI</div>'
            f'<div style="height:2px;background:#e4d9c6;margin:12px 0"></div><div data-layout-ignore style="font:700 15px Inter;color:#6b6157">Skills</div>'
            f'<div id="{k}-skill" style="font:900 34px Inter;color:#B5440F;letter-spacing:-1px;margin-top:4px">I do the work.</div></div>'
            f'<div id="{k}-scroll" data-layout-ignore style="position:absolute;left:1130px;top:-1500px;width:290px;height:1460px;background:#FBF7EE;border-radius:0 0 8px 8px;'
            f'box-shadow:0 18px 30px rgba(0,0,0,.3);padding:26px;box-sizing:border-box;font:600 22px/1.75 Inter;color:#7a6f63;overflow:hidden">'
            + "".join(f"Step {i}: read about websites<br>" if i % 3 else f"Step {i}: ask a forum<br>" for i in range(1, 49)) + "</div>")


def chair_html(c):
    k = c.k
    return (f'<div id="{k}-chair" style="position:absolute;left:690px;top:230px;width:540px;height:540px;border-radius:150px 150px 40px 40px;'
            f'background:#3A2A22;box-shadow:inset 0 0 0 10px #5A4234, 0 20px 40px rgba(0,0,0,.3)"></div>')


def chairfront_html(c):
    k = c.k
    return (f'<div id="{k}-chairf" style="position:absolute;left:690px;top:230px;width:540px;height:530px;border-radius:150px 150px 40px 40px;'
            f'background:#32241D;box-shadow:inset 0 0 0 10px #5A4234;transform-origin:50% 50%"></div>')


def shade_html(c):
    return (f'<div id="{c.k}-shade" style="position:absolute;inset:0;opacity:0;background:radial-gradient(ellipse 470px 300px at 960px 600px, '
            f'rgba(5,10,18,0) 0, rgba(5,10,18,.78) 75%)"></div>')


def endcard(c):
    k, D = c.k, c.D
    code = [l.rstrip() for l in (Path(__file__).parent / "compositions/c02-code.html").read_text().splitlines() if l.startswith("tl.")][:14] \
        if (Path(__file__).parent / "compositions/c02-code.html").exists() else ["tl.to(...)"]
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = "".join(f'<div id="{k}-cl{i}" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{esc(s)}</div>' for i, s in enumerate(code))
    html = f"""
<div id="{k}-end" class="clip" data-start="0" data-duration="{D:.3f}" style="position:absolute;inset:0;background:#0B1622;overflow:hidden">
  <div id="{k}-flood" style="position:absolute;inset:0;background:#F7EFE2;opacity:0"></div>
  <div id="{k}-tile" style="position:absolute;left:250px;top:330px;width:1040px;height:230px;background:#fff;border-radius:28px;box-shadow:0 24px 60px rgba(60,35,20,.16);
       display:flex;align-items:center;gap:30px;padding:0 40px;box-sizing:border-box">
    <img src="assets/app-512.png" alt="Bowers" style="width:150px;height:150px;border-radius:32px">
    <div><div style="font:900 50px Inter;letter-spacing:-1.5px;color:#1F1D1B">Bowers-Setup-1.0.0.exe</div>
      <div style="font:600 30px Inter;color:#6b6157;margin-top:6px">The Windows installer · updates itself</div></div></div>
  <div id="{k}-os" style="position:absolute;left:250px;top:620px;font:900 84px Inter;letter-spacing:-3px;color:#1F1D1B">
    <span id="{k}-os0" style="display:inline-block;margin-right:40px">Windows</span><span id="{k}-os1" style="display:inline-block;margin-right:40px">Mac</span><span id="{k}-os2" style="display:inline-block">Linux</span></div>
  <div id="{k}-code" data-layout-ignore style="position:absolute;left:250px;top:170px;width:1420px;height:700px;background:#14171D;border-radius:26px;padding:44px 50px;box-sizing:border-box;
       font:500 27px/1.55 'JetBrains Mono', monospace;color:#C9D1D9;box-shadow:0 30px 70px rgba(0,0,0,.35);opacity:0">
    <div style="font:700 24px Inter;color:#8b919c;margin-bottom:18px">compositions/c02-code.html · the chapter you watched</div>{lines}</div>
  <img id="{k}-mark" src="assets/app-512.png" alt="Bowers" style="position:absolute;left:560px;top:380px;width:200px;height:200px;border-radius:44px;box-shadow:0 20px 40px rgba(60,35,20,.25)">
  <div id="{k}-word" style="position:absolute;left:800px;top:378px;font:900 188px/1 Inter;letter-spacing:-7px;color:#1F1D1B">Bowers</div>
  <div id="{k}-cta" style="position:absolute;left:806px;top:620px;padding:26px 44px;border-radius:18px;background:{L.ACCENT};color:#fff;font:800 44px Inter">Download Bowers</div>
  <div id="{k}-url" style="position:absolute;left:810px;top:745px;font:600 34px Inter;color:#6b6157">github.com/JBWeb1/Bowie</div>
  <div id="{k}-eb" style="position:absolute;left:1180px;top:300px;width:430px;height:430px"><div class="bw" id="{k}-eb-bw" style="position:absolute;inset:0;transform-origin:50% 100%">
    <img id="{k}-eb-save" src="assets/bowie/save.png" alt="Bowie" style="position:absolute;inset:0;width:100%;height:100%">
    <img id="{k}-eb-jumping" src="assets/bowie/jumping.png" alt="Bowie" style="position:absolute;inset:0;width:100%;height:100%;opacity:0">
    <img id="{k}-eb-waving" src="assets/bowie/waving.png" alt="Bowie" style="position:absolute;inset:0;width:100%;height:100%;opacity:0"></div></div>
</div>"""
    t1, t2 = b("c13-end", 1), b("c13-end", 2)
    js = [
        f'tl.to("#{k}-flood", {{ opacity: 1, duration: 0.45, ease: "power2.inOut" }}, 0.6);',
        f'tl.fromTo("#{k}-tile", {{ x: -900 }}, {{ x: 0, duration: 0.7, ease: "expo.out" }}, 1.1);',
        f'tl.fromTo("#{k}-eb", {{ y: 700 }}, {{ y: 0, duration: 0.6, ease: "back.out(1.5)" }}, 1.4);',
    ]
    c.cue(1.15, "whoosh-short", 0.35); c.cue(1.45, "pop", 0.35)
    for i, w in enumerate(("Windows", "Mac", "Linux")):
        tt = 6.9 + i * 0.35
        js.append(f'tl.fromTo("#{k}-os{i}", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.14, ease: "power4.out" }}, {tt:.2f});')
    # the code of the film itself
    js += [f'tl.to(["#{k}-tile", "#{k}-os"], {{ x: -1200, filter: "blur(16px)", duration: 0.25, ease: "power3.in" }}, {t1 - 0.2:.3f});',
           f'tl.to("#{k}-eb", {{ x: 900, duration: 0.3, ease: "power3.in" }}, {t1 - 0.2:.3f});',
           f'tl.fromTo("#{k}-code", {{ opacity: 0, scale: 0.94 }}, {{ opacity: 1, scale: 1, duration: 0.5, ease: "expo.out" }}, {t1:.3f});']
    c.cue(t1 - 0.15, "whoosh", 0.35)
    for i in range(len(code)):
        js.append(f'tl.fromTo("#{k}-cl{i}", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.05 }}, {t1 + 0.4 + i * 0.12:.2f});')
    c.cue(t1 + 0.4, "typing", 0.25)
    # the end card: the code folds away, Bowie carries the mark in and sets it down
    js += [f'tl.to("#{k}-code", {{ scale: 0.12, opacity: 0, x: -200, y: -10, duration: 0.45, ease: "power3.in" }}, {t2 - 0.3:.3f});',
           f'tl.set("#{k}-eb-save", {{ opacity: 0 }}, {t2 - 0.3:.3f}); tl.set("#{k}-eb-jumping", {{ opacity: 1 }}, {t2 - 0.3:.3f});',
           f'tl.set("#{k}-eb", {{ x: 900, y: -40 }}, {t2 - 0.3:.3f}); tl.to("#{k}-eb", {{ x: -140, y: -40, duration: 0.9, ease: "power2.inOut" }}, {t2 - 0.3:.3f});',
           f'tl.fromTo("#{k}-mark", {{ x: 760, y: -170, rotation: 12 }}, {{ x: -60, y: -40, rotation: -4, duration: 0.9, ease: "power2.inOut" }}, {t2 - 0.3:.3f});',
           f'tl.to("#{k}-mark", {{ x: 0, y: 0, rotation: 0, duration: 0.45, ease: "back.out(2.2)" }}, {t2 + 0.6:.3f});',
           f'tl.to("#{k}-eb", {{ x: -1090, y: 60, duration: 0.6, ease: "power2.inOut" }}, {t2 + 0.8:.3f});',
           f'tl.set("#{k}-eb-jumping", {{ opacity: 0 }}, {t2 + 1.3:.3f}); tl.set("#{k}-eb-waving", {{ opacity: 1 }}, {t2 + 1.3:.3f});',
           f'tl.fromTo("#{k}-eb-bw", {{ scaleY: 0.9 }}, {{ scaleY: 1, duration: 0.4, ease: "elastic.out(1, 0.5)" }}, {t2 + 1.3:.3f});',
           f'tl.fromTo("#{k}-word", {{ clipPath: "inset(0 100% 0 0)" }}, {{ clipPath: "inset(0 0% 0 0)", duration: 0.55, ease: "power3.out" }}, {t2 + 0.95:.3f});',
           f'tl.fromTo("#{k}-cta", {{ opacity: 0, y: 24 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "expo.out" }}, {t2 + 1.6:.3f});',
           f'tl.fromTo("#{k}-url", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.4, ease: "power2.out" }}, {t2 + 2.0:.3f});',
           f'tl.set(["#{k}-mark", "#{k}-word", "#{k}-cta", "#{k}-url"], {{ opacity: 0 }}, 0);',
           f'tl.set("#{k}-mark", {{ opacity: 1 }}, {t2 - 0.3:.3f}); tl.set("#{k}-word", {{ opacity: 1 }}, {t2 + 0.95:.3f});']
    c.cue(t2 + 0.62, "impact-bass-1", 0.5); c.cue(t2 + 1.62, "pop", 0.3)
    return html, "\n".join(js)


C = {}

# 8:02 am, Sam's phone. Bowie pops up in front of it.
C["c00-open"] = {
    "laptop": False, "lamp": False, "phone_push": False, "sky": "dawn",
    "office_js": [lambda c: 'tl.set("#c00-ocam", { scale: %s, x: %s, y: %s }, 0);' % L.office_focus(L.PHONE),
                  lambda c: 'tl.to("#c00-ocam", { scale: 1, x: 0, y: 0, duration: 1.0, ease: "power2.inOut" }, %.3f);' % (b("c00-open", 3) - 0.3)],
    "top_html": lambda c: L.bowie_html(c, "pop", ["hello", "waving"]),
    "css": lambda c: f"#{c.k}-pop {{ position:absolute; left:1060px; top:600px; width:560px; height:560px; }} #{c.k}-pop .bw {{ position:absolute; inset:0; transform-origin:50% 100%; }} #{c.k}-pop .bw img {{ position:absolute; inset:0; width:100%; height:100%; opacity:0; }}",
    "js": [lambda c: (L.bowie_act(c, "pop", [(b("c00-open", 2) - 0.1, "hello"), (b("c00-open", 3), "waving")], enter=(b("c00-open", 2) - 0.3, 640)) or "")],
}

# 9:00, the interview: the chair spins, the résumé, the long list, the laptop.
C["c01-interview"] = {
    "laptop_screens": ["home-ask"], "lamp": False, "sky": "morning", "phone_push": True,
    "office_back_html": chair_html, "office_front_html": lambda c: chairfront_html(c) + resume_html(c),
    "office_bowie": {"at": (705, 250, 510), "plan": [(1.25, "happy"), (b("c01-interview", 2), "hello"), (b("c01-interview", 5), "thinking"),
                     (b("c01-interview", 6), "coding"), (b("c01-interview", 6) + 0.95, "debugging"), (b("c01-interview", 6) + 1.75, "save"),
                     (b("c01-interview", 8), "excited")]},
    "office_js": [
        'tl.fromTo("#c01-chairf", { scaleX: 1 }, { scaleX: 0, duration: 0.24, ease: "power2.in" }, 1.0);',
        'tl.fromTo("#c01-ob", { scaleX: 0 }, { scaleX: 1, duration: 0.26, ease: "power2.out" }, 1.24);',
        'tl.to(["#c01-ob", "#c01-chair"], { scaleX: -1, duration: 0.22, ease: "power2.in" }, 5.05); tl.to(["#c01-ob", "#c01-chair"], { scaleX: 1, duration: 0.3, ease: "power2.out" }, 5.27);',
        lambda c: 'tl.to("#c01-ocam", { scale: %s, x: %s, y: %s, duration: 0.7, ease: "power2.inOut" }, %.3f);' % (*L.office_focus((330, 790, 340, 270)), b("c01-interview", 2) + 1.2),
        lambda c: 'tl.fromTo("#c01-skill", { scale: 1.5, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.35, ease: "back.out(2)" }, %.3f);' % b("c01-interview", 3),
        lambda c: 'tl.to("#c01-ocam", { scale: 1, x: 0, y: 0, duration: 0.7, ease: "power2.inOut" }, %.3f);' % (b("c01-interview", 5) - 0.2),
        lambda c: 'tl.to("#c01-scroll", { y: 1200, duration: 0.8, ease: "expo.out" }, %.3f); tl.to("#c01-scroll", { y: 1500, duration: 3.5, ease: "none" }, %.3f);' % (b("c01-interview", 5) + 0.6, b("c01-interview", 5) + 1.4),
        lambda c: 'tl.to("#c01-scroll", { y: -400, duration: 0.35, ease: "power3.in" }, %.3f);' % (b("c01-interview", 6) - 0.2),
        lambda c: 'tl.fromTo(["#c01-laptop", "#c01-base"], { x: 1300 }, { x: 0, duration: 0.8, ease: "expo.out" }, %.3f);' % (b("c01-interview", 8) + 0.5),
        'tl.set("#c01-skill", { opacity: 0 }, 0);',
    ],
    "sfx": [(1.0, "whoosh-short", 0.35), (5.05, "whoosh", 0.3), ((3, 0), "pop", 0.4), ((5, 0.6), "whoosh-short", 0.3), ((8, 0.5), "whoosh-short", 0.35)],
}

C["c02-code"] = {
    "laptop_screens": ["home-ask", "chat-good"], "accent": "code", "zoom": 0, "pull": 13,
    "office_bowie": {"at": BEHIND, "plan": [(0, "coding"), (b("c02-code", 13) + 0.2, "celebrating")]},
    "shots": [
        {"t": 0, "screen": "home-ask"},
        {"t": (0, 1.0), "screen": "home-ask", "focus": [538, 388, 762, 120], "cursor": [{"t": (0, 6.3), "x": 1267, "y": 477}]},
        {"t": (0, 6.45), "screen": "chat-steps", "swap": "cut", "focus": [292, 87, 670, 250]},
        {"t": (4, 0), "screen": "chat-steps", "focus": [292, 150, 670, 170]},
        {"t": (5, -0.1), "screen": "chat-bad", "swap": "blur", "focus": [975, 140, 625, 560]},
        {"t": (7, 0.4), "screen": "chat-bad-hover", "swap": "blur", "focus": [250, 60, 700, 200], "cursor": [{"t": (7, 5.0), "x": 361, "y": 114}]},
        {"t": (7, 5.7), "screen": "chat-steps", "swap": "blur", "focus": [292, 87, 670, 250]},
        {"t": (9, -0.15), "screen": "chat-good", "swap": "blur", "focus": [975, 150, 625, 560], "sfx": "chime", "vol": 0.35},
        {"t": (11, 0), "screen": "chat-good"},
        {"t": (11, 3.0), "screen": "chat-good", "focus": [960, 55, 520, 60]},
        {"t": (12, -0.2), "screen": "chat-good", "focus": [1250, 60, 350, 140], "cursor": [{"t": (12, 1.0), "x": 1546, "y": 127}], "sfx": "chime", "sfx_at": 1.15, "vol": 0.4},
    ],
    "peek": [{"plan": [(b("c02-code", 5) - 0.1, "surprised"), (b("c02-code", 6), "sad")], "out": b("c02-code", 7) + 0.3},
             {"plan": [(b("c02-code", 9) + 0.2, "happy")], "out": b("c02-code", 11) - 0.2}],
}

C["c03-creative"] = {
    "laptop_screens": ["motion"], "accent": "creative", "zoom": 2,
    "office_bowie": {"at": BEHIND, "plan": [(0, "designing"), (b("c03-creative", 1), "excited")]},
    "shots": [
        {"t": 0, "screen": "motion"},
        {"t": (2, 1.0), "screen": "motion", "focus": [280, 390, 1290, 320]},
        {"t": (2, 4.2), "screen": "motion", "focus": [280, 660, 900, 50]},
        {"t": (2, 7.3), "screen": "motion", "focus": [280, 600, 1290, 80]},
        {"t": (3, 0), "screen": "integrations-video", "swap": "whip", "focus": [283, 508, 300, 209]},
        {"t": (4, 0), "screen": "integrations-video"},
        {"t": (6, 0), "screen": "motion-photo", "swap": "whip", "focus": [299, 170, 1237, 390]},
    ],
}


def c03_reel(c):
    html, js = reel_overlay(c, b("c03-creative", 4) - 0.2, b("c03-creative", 6) - 0.1)
    c.html.append(html)
    return js


C["c03-creative"]["js"] = [c03_reel]

C["c04-care"] = {
    "laptop_screens": ["motion"], "accent": "fix", "zoom": 2, "pull": b("c04-care", 5, "end") + 0.2,
    "office_bowie": {"at": BEHIND, "plan": [(0, "curious"), (b("c04-care", 0), "surprised"), (b("c04-care", 1), "fixing"), (b("c04-care", 5, "end") + 0.4, "happy")]},
    "office_js": [lambda c: shake_js(c, b("c04-care", 0), b("c04-care", 1) + 0.5)],
    "shots": [
        {"t": 0, "screen": "motion"},
        {"t": (2, 0.45), "screen": "care", "swap": "whip"},
        {"t": (2, 2.0), "screen": "care", "focus": [280, 430, 1275, 105]},
        {"t": (3, 0), "screen": "care", "focus": [280, 548, 900, 70], "cursor": [{"t": (4, 0.1), "x": 545, "y": 583}], "sfx": "chime", "sfx_at": 3.3, "vol": 0.35},
        {"t": (5, 0.1), "screen": "care", "focus": [280, 635, 1275, 215]},
        {"t": (5, 6.5), "screen": "care", "focus": [280, 855, 1275, 45]},
        {"t": (5, 9.6), "screen": "care"},
    ],
}

C["c05-money"] = {
    "laptop_screens": ["lab-trading"], "accent": "Lunch", "zoom": 2, "pull": b("c05-money", 4, "end") + 0.2,
    "office_bowie": {"at": BEHIND, "plan": [(0, "research"), (b("c05-money", 1), "excited"), (b("c05-money", 4, "end") + 0.4, "thinking")]},
    "shots": [
        {"t": 0, "screen": "lab-trading"},
        {"t": (2, 0.6), "screen": "lab-trading", "focus": [280, 83, 1275, 150]},
        {"t": (3, 0.2), "screen": "lab-trading", "focus": [280, 83, 1275, 150], "cursor": [{"t": (3, 1.6), "x": 740, "y": 202, "click": False}]},
        {"t": (4, 0), "screen": "lab-trading", "focus": [295, 145, 700, 40]},
    ],
}

C["c06-teach"] = {
    "laptop_screens": ["lab-math-solve"], "accent": "teach", "zoom": 1, "hold_phone_after": True,
    "office_bowie": {"at": BEHIND, "plan": [(0, "reading"), (b("c06-teach", 0) + 1.2, "solving")]},
    "shots": [
        {"t": 0, "screen": "lab-math-solve"},
        {"t": (1, 0.3), "screen": "lab-math-solve", "focus": [290, 100, 1260, 150]},
        {"t": (2, -0.1), "screen": "lab-math-factor", "swap": "blur", "focus": [290, 100, 1260, 150]},
        {"t": (3, 1.6), "screen": "lab-math-plot", "swap": "blur", "focus": [300, 250, 1240, 350]},
        {"t": (5, 0), "screen": "labs", "swap": "whip"},
        {"t": (5, 1.6), "screen": "labs", "focus": [280, 80, 1290, 300]},
        {"t": (5, 6.8), "screen": "labs", "focus": [280, 330, 1290, 300]},
    ],
}

C["c07-listen"] = {
    "laptop_screens": ["hud"], "accent": "listen", "zoom": 0,
    "office_bowie": {"at": BEHIND, "plan": [(0, "listening")]},
    "shots": [
        {"t": 0, "screen": "hud"},
        {"t": (1, -0.2), "screen": "hud", "focus": [417, 492, 767, 92]},
        {"t": (3, 0), "screen": "settings-voice", "swap": "whip", "focus": [280, 200, 762, 383]},
        {"t": (4, 0), "screen": "hud", "swap": "whip"},
        {"t": (5, 0), "screen": "graph", "swap": "whip"},
        {"t": (5, 2.2), "screen": "graph", "focus": [280, 160, 960, 610]},
    ],
    "peek": [{"plan": [(b("c07-listen", 4) + 0.3, "thinking"), (b("c07-listen", 4) + 3.0, "love")], "out": b("c07-listen", 5) - 0.3}],
}

C["c08-team"] = {
    "laptop_screens": ["agents"], "accent": "others", "zoom": 6.2, "office_back_html": team_html,
    "office_bowie": {"at": BEHIND, "plan": [(0, "collaborating")]},
    "office_js": [team_js],
    "shots": [
        {"t": 0, "screen": "agents"},
        {"t": (1, 2.0), "screen": "agents", "focus": [280, 100, 1300, 330]},
        {"t": (1, 5.5), "screen": "agents", "focus": [280, 420, 1300, 330]},
        {"t": (4, 0), "screen": "integrations-video", "swap": "whip", "focus": [283, 267, 1275, 450]},
        {"t": (4, 7.0), "screen": "integrations", "swap": "whip"},
    ],
}

C["c09-dev"] = {
    "laptop_screens": ["chat-good"], "accent": "developers", "zoom": 0,
    "office_bowie": {"at": BEHIND, "plan": [(0, "coding")]},
    "shots": [
        {"t": 0, "screen": "chat-good"},
        {"t": (1, 0.2), "screen": "chat-good", "focus": [1100, 50, 260, 60]},
        {"t": (2, 0), "screen": "forge", "swap": "whip", "focus": [270, 180, 500, 340]},
        {"t": (3, 0), "screen": "forge"},
        {"t": (3, 2.8), "screen": "forge", "focus": [1200, 180, 380, 340]},
    ],
}

C["c10-organised"] = {
    "laptop_screens": ["projects"], "accent": "organised", "zoom": 0,
    "office_bowie": {"at": BEHIND, "plan": [(0, "planning")]},
    "shots": [
        {"t": 0, "screen": "projects"},
        {"t": (0, 0.8), "screen": "projects", "focus": [270, 170, 400, 320]},
        {"t": (1, 0), "screen": "explore", "swap": "whip", "focus": [270, 420, 1300, 300]},
        {"t": (2, 0), "screen": "library", "swap": "whip", "focus": [270, 200, 520, 300]},
        {"t": (3, 0.1), "screen": "cmdk", "swap": "cut", "focus": [480, 95, 640, 200], "sfx": "key-press", "vol": 0.5},
        {"t": (3, 4.4), "screen": "light-home", "swap": "blur"},
    ],
}

C["c11-weakness"] = {
    "laptop_screens": ["settings-safety"], "accent": "weaknesses", "zoom": 1,
    "office_bowie": {"at": BEHIND, "plan": [(0, "thinking"), (b("c11-weakness", 0), "curious")]},
    "shots": [
        {"t": 0, "screen": "settings-safety"},
        {"t": (1, 0.4), "screen": "settings-safety", "focus": [280, 190, 1000, 230]},
        {"t": (2, 0), "screen": "integrations-video", "swap": "whip", "focus": [283, 267, 305, 217]},
        {"t": (2, 3.8), "screen": "motion-photo", "swap": "whip", "focus": [299, 340, 700, 60]},
    ],
}

C["c11b-post"] = {
    "laptop_screens": ["chat-post"], "accent": "post", "zoom": 1, "pull": 3,
    "office_bowie": {"at": BEHIND, "plan": [(0, "writing"), (b("c11b-post", 3) + 0.2, "thankyou")]},
    "shots": [
        {"t": 0, "screen": "chat-post"},
        {"t": (1, 0.6), "screen": "chat-post", "focus": [290, 140, 620, 200]},
        {"t": (2, 1.6), "screen": "chat-post"},
    ],
}

C["c12-hired"] = {
    "laptop_screens": ["site-lemon-lane"], "sky": "night",
    "office_front_html": shade_html,
    "office_bowie": {"at": BEHIND, "plan": [(0, "curious"), (b("c12-hired", 1), "surprised"), (b("c12-hired", 1) + 0.9, "celebrating"),
                                            (b("c12-hired", 3), "happy"), (b("c12-hired", 4) + 0.7, "nap")]},
    "office_js": [
        lambda c: 'tl.to("#c12-ob", { y: -150, duration: 0.3, ease: "power2.out" }, %.3f); tl.to("#c12-ob", { y: 0, duration: 0.45, ease: "bounce.out" }, %.3f);' % (b("c12-hired", 1) + 0.9, b("c12-hired", 1) + 1.2),
        lambda c: 'tl.to("#c12-cone", { opacity: 0, duration: 0.12 }, %.3f); tl.to("#c12-shade", { opacity: 1, duration: 0.45, ease: "power2.inOut" }, %.3f);' % (b("c12-hired", 4), b("c12-hired", 4)),
        lambda c: 'tl.to("#c12-mm", { rotation: "+=12", duration: 0.5, ease: "expo.out" }, %.3f); tl.to("#c12-hh", { rotation: "+=1", duration: 0.5, ease: "expo.out" }, %.3f);' % (b("c12-hired", 4) + 1.6, b("c12-hired", 4) + 1.6),
    ],
    "sfx": [((1, 0.95), "sparkle", 0.45), ((4, 0), "click-soft", 0.6)],
}

C["c13-end"] = {"laptop": False, "lamp": False, "sky": "night", "phone_push": False}


def c13_end(c):
    html, js = endcard(c)
    c.html.append(html)
    return js


C["c13-end"]["js"] = [c13_end]

CHAPTERS = C
