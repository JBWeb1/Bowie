"""Bowers Labs: Math Lab (SymPy), Model Arena, and Emote Maker.

Math needs `pip install sympy` (optional). Emotes need Pillow (installed with Bowers' browser extra, or
`pip install pillow`). The arena uses the models Bowers already has.
"""

import base64
import io
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

# ---------------------------------------------------------------- Math Lab

class LabError(Exception):
    pass


def _sympy():
    try:
        import sympy
        return sympy
    except ImportError:
        raise LabError("Math Lab needs SymPy: run  pip install sympy  (or press Explain steps to have Bowers solve it)")


def _parse(sp, text: str):
    from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application, parse_expr,
                                            standard_transformations)
    if len(text) > 500 or re.search(r"__|import|lambda|exec|eval|open\(|\bos\b|\bsys\b", text):
        raise LabError("that doesn't look like math")
    tr = standard_transformations + (implicit_multiplication_application, convert_xor)
    names = {"e": sp.E, "pi": sp.pi, "ln": sp.log}
    try:
        return parse_expr(text, transformations=tr, local_dict=names, evaluate=True)
    except Exception as e:
        raise LabError(f"couldn't read that: {e}")


def solve_math(expr: str, op: str = "solve") -> dict:
    sp = _sympy()
    text = expr.strip()
    for word in ("solve", "simplify", "differentiate", "derivative of", "integrate", "integral of", "factor", "expand", "plot"):
        if text.lower().startswith(word + " "):
            text = text[len(word):].strip()
    if "=" in text and op == "solve":
        left, right = text.split("=", 1)
        eq = sp.Eq(_parse(sp, left), _parse(sp, right))
        target = eq.lhs - eq.rhs
    else:
        target = _parse(sp, text)
    syms = sorted(target.free_symbols, key=lambda s: s.name)
    x = next((s for s in syms if s.name == "x"), syms[0] if syms else sp.Symbol("x"))
    if op == "solve":
        sol = sp.solve(target, x)
        out = f"{x} = " + ", ".join(sp.sstr(s) for s in sol) if sol else "no solutions found"
        latex = ", ".join(f"{sp.latex(x)} = {sp.latex(s)}" for s in sol)
    elif op == "simplify":
        r = sp.simplify(target); out, latex = sp.sstr(r), sp.latex(r)
    elif op == "diff":
        r = sp.diff(target, x); out, latex = f"d/d{x} = {sp.sstr(r)}", f"\\frac{{d}}{{d{sp.latex(x)}}} = {sp.latex(sp.simplify(r))}"
    elif op == "integrate":
        r = sp.integrate(target, x); out, latex = f"∫ d{x} = {sp.sstr(r)} + C", f"\\int {sp.latex(target)}\\,d{sp.latex(x)} = {sp.latex(r)} + C"
    elif op == "factor":
        r = sp.factor(target); out, latex = sp.sstr(r), sp.latex(r)
    elif op == "expand":
        r = sp.expand(target); out, latex = sp.sstr(r), sp.latex(r)
    elif op == "plot":
        f = sp.lambdify(x, target, modules=["math"])
        pts = []
        for i in range(401):
            xv = -10 + i * 0.05
            try:
                yv = float(f(xv))
                pts.append([round(xv, 3), yv if math.isfinite(yv) and abs(yv) < 1e6 else None])
            except (ValueError, ZeroDivisionError, OverflowError, TypeError):
                pts.append([round(xv, 3), None])
        return {"text": f"y = {sp.sstr(target)}", "latex": f"y = {sp.latex(target)}", "points": pts}
    else:
        raise LabError("pick solve, simplify, diff, integrate, factor, expand or plot")
    return {"text": out, "latex": latex}


# ---------------------------------------------------------------- Model Arena

def arena_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "arena.json"


def _arena() -> dict:
    try:
        return json.loads(arena_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {"battles": {}, "votes": []}


def _save_arena(data: dict) -> None:
    arena_path().parent.mkdir(parents=True, exist_ok=True)
    data["battles"] = dict(list(data["battles"].items())[-200:])
    arena_path().write_text(json.dumps(data, indent=1))


def _answer(client_for, model_name: str, prompt: str) -> dict:
    from . import models
    prof = models.PROFILES.get(model_name)
    engine = models.resolve(prof["engine"] if prof else model_name)
    started = time.monotonic()
    try:
        resp = client_for(engine).messages.create(model=engine, max_tokens=2500,
                                                  messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") or "" for b in resp.content)
        return {"text": text, "seconds": round(time.monotonic() - started, 1)}
    except Exception as e:
        return {"text": "", "error": f"{type(e).__name__}: {e}"}


def battle(client_for, a: str, b: str, prompt: str) -> dict:
    """Ask two models the same prompt (in parallel). Model names stay hidden until you vote."""
    from concurrent.futures import ThreadPoolExecutor
    if not prompt.strip():
        raise LabError("write a prompt first")
    if a == b:
        raise LabError("pick two different models")
    with ThreadPoolExecutor(2) as pool:
        ra, rb = pool.map(lambda m: _answer(client_for, m, prompt), (a, b))
    bid = uuid.uuid4().hex[:10]
    data = _arena()
    data["battles"][bid] = {"a": a, "b": b, "prompt": prompt[:2000], "time": time.time()}
    _save_arena(data)
    return {"id": bid, "a": ra, "b": rb}


def vote(bid: str, winner: str) -> dict:
    data = _arena()
    battle_ = data["battles"].get(bid)
    if not battle_ or winner not in ("a", "b", "tie"):
        raise LabError("that battle isn't open any more")
    data["votes"].append({"a": battle_["a"], "b": battle_["b"], "winner": winner, "time": time.time()})
    _save_arena(data)
    return {"a": battle_["a"], "b": battle_["b"]}


def leaderboard() -> list[dict]:
    board = {}
    for v in _arena()["votes"]:
        for side in ("a", "b"):
            row = board.setdefault(v[side], {"model": v[side], "wins": 0, "losses": 0, "ties": 0})
            if v["winner"] == "tie":
                row["ties"] += 1
            elif v["winner"] == side:
                row["wins"] += 1
            else:
                row["losses"] += 1
    return sorted(board.values(), key=lambda r: (r["wins"] - r["losses"], r["wins"]), reverse=True)


# ---------------------------------------------------------------- Emote Maker

EMOTE_SIZES = [("Twitch", 28), ("Twitch", 56), ("Twitch", 112), ("Discord emoji", 128), ("Discord sticker", 320),
               ("Slack", 128), ("YouTube", 48), ("Telegram sticker", 512)]


def decode_image(data: str) -> bytes:
    head, _, b64 = data.partition(",")
    if not head.startswith("data:image/") or not b64:
        raise LabError("send a PNG, JPEG or WebP image")
    raw = base64.b64decode(b64)
    if len(raw) > 8_000_000:
        raise LabError("the image is over 8 MB")
    return raw


def make_emotes(root: Path, data: str, name: str = "emote") -> dict:
    try:
        from PIL import Image
    except ImportError:
        raise LabError("Emote Maker needs Pillow: run  pip install pillow")
    img = Image.open(io.BytesIO(decode_image(data))).convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)  # trim empty space so the emote fills its square
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    slug = "-".join(re.findall(r"[a-z0-9]+", Path(name).stem.lower())[:4]) or "emote"
    folder = root / "assets" / "emotes" / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for platform, size in EMOTE_SIZES:
        target = folder / f"{platform.lower().replace(' ', '-')}-{size}.png"
        square.resize((size, size), Image.LANCZOS).save(target, optimize=True)
        out.append({"platform": platform, "size": size, "path": str(target.relative_to(root))})
    return {"folder": str(folder.relative_to(root)), "sizes": out}


def save_upload(root: Path, data: str, folder: str = "uploads") -> str:
    raw = decode_image(data)
    kind = data[5:data.index(";")] if ";" in data[:40] else "image/png"
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(kind)
    if not ext:
        raise LabError("send a PNG, JPEG or WebP image")
    folder = re.sub(r"[^\w-]", "", folder) or "uploads"
    target = root / "assets" / folder / f"{uuid.uuid4().hex[:10]}{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return str(target.relative_to(root))
