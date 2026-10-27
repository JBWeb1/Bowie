"""Pieces shared by every chapter of the film: the office set, the camera, Bowie's acting, the cursor and sound cues."""
import json
import math

W, H = 1920, 1080
SCREEN_SCALE = 1.2            # captured screens are 1600x900 CSS px (at 2x), shown at 1920x1080
LAPTOP = (620, 404, 680, 383)  # the laptop's screen on the desk: x, y, w, h (16:9)
PHONE = (1452, 470, 290, 560)  # Sam's phone on its stand
ACCENT = "#FF6B2C"

SKY = {  # the window, by the hour
    "dawn": ("#CFE8F2", "#FFF1D2"), "morning": ("#AEDCF2", "#EAF6FB"), "noon": ("#9ED3F0", "#E4F4FB"),
    "afternoon": ("#A9D2EA", "#FCE7C4"), "evening": ("#FF9A62", "#C75B39"), "night": ("#13253A", "#0B1622"),
}


def minutes(clock: str, prev: int | None) -> int:
    """Minutes since midnight on a 12-hour clock that only moves forward through the day."""
    h, m = map(int, clock.split(":"))
    v = (h % 12) * 60 + m
    if prev is not None:
        while v < prev:
            v += 12 * 60
    return v


def sky_for(mins: int) -> str:
    h = (mins // 60) % 24
    return "dawn" if h < 9 else "morning" if h < 11 else "noon" if h < 14 else "afternoon" if h < 18 else "evening" if h < 20 else "night"


def focus(rect):
    """Camera transform (scale, x, y; origin top-left) that frames a rect given in screen CSS px."""
    if rect is None:
        return 1.0, 0.0, 0.0
    rx, ry, rw, rh = rect
    cx, cy = (rx + rw / 2) * SCREEN_SCALE, (ry + rh / 2) * SCREEN_SCALE
    s = min(W / (rw * SCREEN_SCALE), H / (rh * SCREEN_SCALE)) * 0.9
    s = max(1.0, min(1.9, s))
    x, y = W / 2 - s * cx, H / 2 - s * cy
    x = min(0.0, max(W - W * s, x)); y = min(0.0, max(H - H * s, y))
    return round(s, 4), round(x, 1), round(y, 1)


def office_focus(rect):
    """Camera on the office set framing a rect in frame px (for the phone and the résumé)."""
    rx, ry, rw, rh = rect
    s = min(W / rw, H / rh) * 0.82
    x, y = W / 2 - s * (rx + rw / 2), H / 2 - s * (ry + rh / 2)
    return round(s, 4), round(x, 1), round(y, 1)


def laptop_zoom():
    x, y, w, h = LAPTOP
    s = W / w
    return round(s, 4), round(-x * s, 1), round(-y * s, 1)


class Chapter:
    """Collects one chapter's markup, styles and timeline lines."""

    def __init__(self, cid, duration):
        self.cid, self.k, self.D = cid, cid.split("-")[0], duration
        self.html, self.css, self.js, self.sfx = [], [], [], []
        self.poses = {}

    def id(self, name):
        return f"{self.k}-{name}"

    def tw(self, line):
        self.js.append(line)

    def cue(self, t, name, vol=0.5):
        if 0 <= t < self.D:
            self.sfx.append((round(t, 3), name, vol))


def j(v):
    return json.dumps(v)


# ---------------------------------------------------------------- the office
def office_css(c: Chapter, sky: str, night: bool):
    a, b = SKY[sky]
    k = c.k
    c.css.append(f"""
  #{k}-ocam {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; transform-origin:0 0; }}
  #{k}-wall {{ position:absolute; inset:0; background:#2E6B66;
    background-image: repeating-linear-gradient(90deg, rgba(0,0,0,0) 0 158px, #285F5A 158px 160px); }}
  #{k}-grain {{ position:absolute; inset:0; background:url(assets/grain.png); opacity:.07; mix-blend-mode:overlay; }}
  #{k}-dado {{ position:absolute; left:0; right:0; top:600px; height:12px; background:#244F4B; box-shadow:0 3px 0 rgba(255,255,255,.05); }}
  #{k}-lower {{ position:absolute; left:0; right:0; top:612px; bottom:0; background:#28605B; }}
  #{k}-win {{ position:absolute; left:140px; top:90px; width:420px; height:330px; background:linear-gradient(180deg,{a},{b});
    border:18px solid #F2E8D8; box-shadow:0 10px 24px rgba(0,0,0,.22), inset 0 0 0 2px rgba(0,0,0,.06); overflow:hidden; }}
  #{k}-win::before {{ content:""; position:absolute; left:50%; top:0; bottom:0; width:12px; margin-left:-6px; background:#F2E8D8; }}
  #{k}-win::after {{ content:""; position:absolute; top:50%; left:0; right:0; height:12px; margin-top:-6px; background:#F2E8D8; }}
  #{k}-sill {{ position:absolute; left:120px; top:438px; width:460px; height:18px; background:#E8DCC8; border-radius:3px; box-shadow:0 6px 12px rgba(0,0,0,.2); }}
  #{k}-moon {{ position:absolute; left:300px; top:60px; width:54px; height:54px; border-radius:50%; background:#F4EBD0;
    box-shadow: inset -14px -6px 0 #D9CBA8; display:{'block' if night else 'none'}; }}
  #{k}-clock {{ position:absolute; left:1520px; top:110px; width:240px; height:240px; border-radius:50%; background:#F7EFE2;
    border:10px solid #1F1D1B; box-sizing:border-box; box-shadow:0 12px 26px rgba(0,0,0,.28); }}
  .{k}-tick {{ position:absolute; left:50%; top:8px; width:4px; height:16px; margin-left:-2px; background:#1F1D1B; transform-origin:2px 102px; }}
  #{k}-hh, #{k}-mm, #{k}-ss {{ position:absolute; left:50%; bottom:50%; transform-origin:50% 100%; border-radius:4px; }}
  #{k}-hh {{ width:10px; height:62px; margin-left:-5px; background:#1F1D1B; }}
  #{k}-mm {{ width:6px; height:92px; margin-left:-3px; background:#1F1D1B; }}
  #{k}-ss {{ width:2px; height:98px; margin-left:-1px; background:{ACCENT}; }}
  #{k}-pin {{ position:absolute; left:50%; top:50%; width:16px; height:16px; margin:-8px 0 0 -8px; border-radius:50%; background:#1F1D1B; }}
  #{k}-desk {{ position:absolute; left:0; right:0; top:760px; bottom:0; background:linear-gradient(180deg,#C08A55,#9A6A3C);
    box-shadow: inset 0 6px 0 #DDA772, 0 -2px 0 rgba(0,0,0,.25); }}
  #{k}-desk::after {{ content:""; position:absolute; inset:0; background:repeating-linear-gradient(178deg, rgba(255,255,255,0) 0 22px, rgba(90,55,25,.08) 22px 24px); }}
  #{k}-lamp {{ position:absolute; left:-70px; top:520px; width:240px; height:260px; }}
  #{k}-lamp .base {{ position:absolute; left:40px; bottom:0; width:150px; height:22px; border-radius:50% / 100% 100% 0 0; background:#B08540; box-shadow:0 10px 18px rgba(0,0,0,.35); }}
  #{k}-lamp .arm {{ position:absolute; left:108px; bottom:18px; width:12px; height:170px; background:#C99A4B; border-radius:6px; }}
  #{k}-lamp .shade {{ position:absolute; left:40px; top:20px; width:170px; height:90px; background:linear-gradient(180deg,#D7AE62,#A97C36);
    clip-path: polygon(22% 0, 78% 0, 100% 100%, 0 100%); }}
  #{k}-cone {{ position:absolute; left:-220px; top:600px; width:560px; height:470px; background:radial-gradient(ellipse at 50% 0%, rgba(255,214,150,.42), rgba(255,214,150,0) 70%);
    clip-path: polygon(30% 0, 52% 0, 100% 100%, 0 100%); display:{'block' if night else 'none'}; }}
  #{k}-laptop {{ position:absolute; left:{LAPTOP[0]-20}px; top:{LAPTOP[1]-20}px; width:{LAPTOP[2]+40}px; height:{LAPTOP[3]+40}px;
    background:#2B2D31; border-radius:18px; box-shadow:0 26px 50px rgba(0,0,0,.35); }}
  #{k}-screen {{ position:absolute; left:20px; top:20px; width:{LAPTOP[2]}px; height:{LAPTOP[3]}px; overflow:hidden; background:#0b0d11; }}
  #{k}-screen img {{ position:absolute; left:0; top:0; width:100%; height:100%; opacity:0; }}
  #{k}-base {{ position:absolute; left:{LAPTOP[0]-80}px; top:{LAPTOP[1]+LAPTOP[3]+20}px; width:{LAPTOP[2]+160}px; height:26px;
    background:linear-gradient(180deg,#3A3D43,#26282C); border-radius:4px 4px 16px 16px; box-shadow:0 14px 22px rgba(0,0,0,.38); }}
  #{k}-phone {{ position:absolute; left:{PHONE[0]}px; top:{PHONE[1]}px; width:{PHONE[2]}px; height:{PHONE[3]}px; background:#1C1C1E;
    border-radius:44px; box-shadow:0 26px 44px rgba(0,0,0,.4); }}
  #{k}-pscreen {{ position:absolute; left:12px; top:12px; right:12px; bottom:12px; border-radius:34px; background:#F5F5F7; overflow:hidden; }}
  #{k}-notch {{ position:absolute; left:50%; top:10px; width:96px; height:26px; margin-left:-48px; border-radius:14px; background:#1C1C1E; }}
  #{k}-ptime {{ position:absolute; left:0; right:0; top:52px; text-align:center; font:900 64px Inter, sans-serif; color:#1C1C1E; letter-spacing:-2px; }}
  #{k}-pwho {{ position:absolute; left:0; right:0; top:128px; text-align:center; font:700 18px Inter, sans-serif; color:#6E6E73; }}
  .{k}-bub {{ position:absolute; left:16px; right:24px; padding:14px 18px; border-radius:22px 22px 22px 6px; background:#E5E5EA; color:#111;
    font:600 26px/1.22 Inter, sans-serif; transform-origin:0 100%; }}
  #{k}-stand {{ position:absolute; left:{PHONE[0]+70}px; top:{PHONE[1]+PHONE[3]-10}px; width:150px; height:40px; background:#3A2B20; border-radius:8px 8px 4px 4px; box-shadow:0 10px 16px rgba(0,0,0,.35); }}
  #{k}-q {{ position:absolute; left:640px; top:96px; width:840px; font:900 98px/1.0 Inter, sans-serif; letter-spacing:-3px; color:#F7EFE2; }}
  #{k}-q span {{ display:inline-block; margin-right:22px; }}
  #{k}-q .acc {{ color:{ACCENT}; }}
""")


def office_html(c: Chapter, screens=(), laptop=True, phone=True, lamp=True, extra_back="", extra_front=""):
    k = c.k
    ticks = "".join(f'<div class="{k}-tick" id="{k}-tk{i}"></div>' for i in range(12))
    imgs = "".join(f'<img id="{k}-ls{i}" src="assets/screens/{s}.webp" alt="">' for i, s in enumerate(screens))
    lap = f'<div id="{k}-laptop"><div id="{k}-screen">{imgs}</div></div><div id="{k}-base"></div>' if laptop else ""
    ph = (f'<div id="{k}-stand"></div><div id="{k}-phone"><div id="{k}-pscreen"><div id="{k}-ptime"></div><div id="{k}-pwho" data-layout-ignore>Sam · Lemon Lane</div>'
          f'<div id="{k}-bubs"></div></div><div id="{k}-notch"></div></div>') if phone else ""
    lmp = (f'<div id="{k}-cone"></div><div id="{k}-lamp"><div class="shade"></div><div class="arm"></div><div class="base"></div></div>') if lamp else ""
    return f"""
  <div id="{k}-ocam">
    <div id="{k}-wall"></div><div id="{k}-lower"></div><div id="{k}-dado"></div>
    <div id="{k}-win"><div id="{k}-moon"></div></div><div id="{k}-sill"></div>
    <div id="{k}-clock">{ticks}<div id="{k}-hh"></div><div id="{k}-mm"></div><div id="{k}-ss"></div><div id="{k}-pin"></div></div>
    <h2 id="{k}-q"></h2>
    {extra_back}
    <div id="{k}-bowie"></div>
    <div id="{k}-desk"></div>
    {lmp}{lap}{ph}
    {extra_front}
    <div id="{k}-grain"></div>
  </div>"""


def clock_js(c: Chapter, m_from: int, m_to: int, spin=0.9):
    k = c.k
    for i in range(12):
        c.tw(f'tl.set("#{k}-tk{i}", {{ rotation: {i * 30} }}, 0);')
    h0, h1 = m_from * 0.5, m_to * 0.5
    mm0, mm1 = m_from * 6, m_to * 6
    c.tw(f'tl.fromTo("#{k}-hh", {{ rotation: {h0} }}, {{ rotation: {h1}, duration: {spin}, ease: "expo.out" }}, 0.05);')
    c.tw(f'tl.fromTo("#{k}-mm", {{ rotation: {mm0} }}, {{ rotation: {mm1}, duration: {spin}, ease: "expo.out" }}, 0.05);')
    c.tw(f'tl.fromTo("#{k}-ss", {{ rotation: 0 }}, {{ rotation: {round(6 * c.D)}, duration: {c.D}, ease: "none" }}, 0);')


def question_js(c: Chapter, text: str, accent_word: str, at=0.35, out=None):
    k = c.k
    words = text.split()
    spans = []
    for i, w in enumerate(words):
        cls = ' class="acc"' if w.strip("?.,!").lower() == accent_word.lower() else ""
        spans.append(f'<span id="{k}-qw{i}"{cls}>{w}</span>')
    c.qspans = "".join(spans)
    for i in range(len(words)):
        c.tw(f'tl.fromTo("#{k}-qw{i}", {{ opacity: 0, filter: "blur(8px)" }}, {{ opacity: 1, filter: "blur(0px)", duration: 0.14, ease: "power4.out" }}, {at + i * 0.08:.3f});')
    if out is not None:
        c.tw(f'tl.to("#{k}-q span", {{ opacity: 0, filter: "blur(8px)", duration: 0.2, ease: "power2.in", stagger: 0.03 }}, {out:.3f});')


def phone_js(c: Chapter, clock_text: str, msgs):
    """msgs: [(t, text)], each bubble pops in under the last; the camera pushes in to read it."""
    k = c.k
    bub, y = [], 168
    for i, (t, text) in enumerate(msgs):
        lines = max(1, math.ceil(len(text) / 15))
        bub.append(f'<div class="{k}-bub" id="{k}-b{i}" style="top:{y}px">{text}</div>')
        c.tw(f'tl.fromTo("#{k}-b{i}", {{ opacity: 0, scale: 0.7 }}, {{ opacity: 1, scale: 1, duration: 0.45, ease: "back.out(1.8)" }}, {t:.3f});')
        c.cue(t, "notification", 0.45)
        y += 30 + lines * 33
    c.phone_bubbles = "".join(bub)
    c.phone_time = clock_text


def cam(c: Chapter, target, t, dur, s, x, y, ease="power2.inOut"):
    c.tw(f'tl.to("{target}", {{ scale: {s}, x: {x}, y: {y}, duration: {dur}, ease: "{ease}" }}, {t:.3f});')


# ---------------------------------------------------------------- Bowie
def bowie_css(c: Chapter, rig, left, top, size):
    c.css.append(f"""
  #{c.k}-{rig} {{ position:absolute; left:{left}px; top:{top}px; width:{size}px; height:{size}px; }}
  #{c.k}-{rig} .bw {{ position:absolute; inset:0; transform-origin:50% 100%; }}
  #{c.k}-{rig} .bw img {{ position:absolute; left:0; top:0; width:100%; height:100%; opacity:0; }}""")


def bowie_html(c: Chapter, rig, poses):
    imgs = "".join(f'<img id="{c.k}-{rig}-{p}" src="assets/bowie/{p}.png" alt="Bowie">' for p in poses)
    return f'<div id="{c.k}-{rig}"><div class="bw" id="{c.k}-{rig}-bw">{imgs}</div></div>'


def bowie_act(c: Chapter, rig, plan, enter=None, exit_=None, breathe=True):
    """plan: [(t, pose)]. Each change: anticipation squash, swap, stretch, settle. enter/exit: (t, from_y)."""
    k = c.k
    bw = f"#{k}-{rig}-bw"
    first = True
    shown = set()
    for i, (t, pose) in enumerate(plan):
        img = f"#{k}-{rig}-{pose}"
        prev = plan[i - 1][1] if i else None
        if first:
            c.tw(f'tl.set("{img}", {{ opacity: 1 }}, {max(0, t):.3f});')
            first = False
        else:
            c.tw(f'tl.to("{bw}", {{ scaleY: 0.9, scaleX: 1.05, duration: 0.08, ease: "power2.in" }}, {t - 0.08:.3f});')
            c.tw(f'tl.set("#{k}-{rig}-{prev}", {{ opacity: 0 }}, {t:.3f});')
            c.tw(f'tl.set("{img}", {{ opacity: 1 }}, {t:.3f});')
            c.tw(f'tl.to("{bw}", {{ scaleY: 1.08, scaleX: 0.94, duration: 0.1, ease: "power2.out" }}, {t:.3f});')
            c.tw(f'tl.to("{bw}", {{ scaleY: 1, scaleX: 1, duration: 0.35, ease: "elastic.out(1, 0.5)" }}, {t + 0.1:.3f});')
        shown.add(pose)
    if enter:
        t, dy = enter
        entered = c.__dict__.setdefault("entered", set())
        if rig in entered:
            c.tw(f'tl.set("#{k}-{rig}", {{ y: {dy} }}, {t:.3f}); tl.to("#{k}-{rig}", {{ y: 0, duration: 0.6, ease: "back.out(1.5)" }}, {t:.3f});')
        else:
            c.tw(f'tl.fromTo("#{k}-{rig}", {{ y: {dy} }}, {{ y: 0, duration: 0.6, ease: "back.out(1.5)" }}, {t:.3f});')
            entered.add(rig)
        c.cue(t + 0.05, "pop", 0.35)
    if exit_:
        t, dy = exit_
        c.tw(f'tl.to("#{k}-{rig}", {{ y: {dy}, duration: 0.3, ease: "power3.in" }}, {t:.3f});')
    if breathe:  # idle breath: acting, not a title loop
        n = max(1, int(c.D / 2.8))
        c.tw(f'tl.fromTo("#{k}-{rig}", {{ rotation: -1.5 }}, {{ rotation: 1.5, duration: 1.4, ease: "sine.inOut", yoyo: true, repeat: {n * 2 - 1} }}, 0);')


# ---------------------------------------------------------------- the cursor
CURSOR_SVG = ('<svg viewBox="0 0 24 24" width="64" height="64"><path d="M4 2 L4 20 L9 15.5 L12.5 22 L15.5 20.6 L12.2 14.2 L19 14 Z" '
              'fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>')


def cursor_html(c: Chapter):
    return f'<div id="{c.k}-cur" style="position:absolute;left:0;top:0;width:64px;height:64px;opacity:0;z-index:20">{CURSOR_SVG}</div>'


def cursor_js(c: Chapter, moves):
    """moves: [(t, x, y, click)] in frame px. The cursor comes in for each action and leaves when the next is far off."""
    k = c.k
    if not moves:
        return
    shown = False
    for i, (t, x, y, click) in enumerate(moves):
        if not shown:
            c.tw(f'tl.set("#{k}-cur", {{ opacity: 1, x: {W + 40}, y: {H - 100} }}, {t - 0.6:.3f});')
            shown = True
        c.tw(f'tl.to("#{k}-cur", {{ x: {x}, y: {y}, duration: 0.55, ease: "power2.inOut" }}, {t - 0.55:.3f});')
        if click:
            c.tw(f'tl.to("#{k}-cur", {{ scale: 0.84, duration: 0.06, ease: "power2.in", transformOrigin: "12% 8%" }}, {t:.3f});')
            c.tw(f'tl.to("#{k}-cur", {{ scale: 1, duration: 0.12, ease: "power2.out" }}, {t + 0.06:.3f});')
            c.cue(t, "click", 0.6)
        nxt = moves[i + 1][0] if i + 1 < len(moves) else None
        if nxt is None or nxt - t > 2.5:
            c.tw(f'tl.to("#{k}-cur", {{ x: {W + 60}, y: {y + 160}, duration: 0.4, ease: "power3.in" }}, {t + 0.7:.3f}); tl.set("#{k}-cur", {{ opacity: 0 }}, {t + 1.12:.3f});')
            shown = False
    c.tw(f'tl.set("#{k}-cur", {{ opacity: 0 }}, 0);')
