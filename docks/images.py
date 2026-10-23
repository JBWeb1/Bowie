"""Image generation with OpenAI's GPT Image models: pictures for the apps and sites Bowers builds (heroes,
illustrations, icons, product shots, backgrounds), or edits of existing images.

    bowers image "a cozy coffee shop at dawn, watercolor" -o public/hero.png --size wide
    bowers image "make the sky purple" --edit public/hero.png

Needs OPENAI_API_KEY. Models: gpt-image-2.5-flare (fast, the default) and gpt-image-2.5-sunburst (more detail,
slower); pick with --detailed, DOCKS_IMAGE_MODEL, or the Images tab. Images are saved in the project
(assets/generated/ unless you choose a path), and a list of them is kept for the gallery.
"""

import base64
import hashlib
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FAST, DETAILED = "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"
SIZES = {"square": "1024x1024", "wide": "1536x1024", "tall": "1024x1536", "auto": "auto"}
QUALITIES = ("auto", "low", "medium", "high")
DEFAULT_DIR = "assets/generated"

SCHEMA = {
    "description": (
        "Create an image with OpenAI's image model and save it in the project: hero images, illustrations, icons, "
        "backgrounds, product shots, placeholders that look real. Write a specific prompt (subject, style, colors, "
        "composition, mood; exact text in quotes if the image must contain words). Use background transparent for "
        "logos and icons. To change an existing image, pass its path in edit. You see the result."),
    "properties": {
        "prompt": {"type": "string"},
        "path": {"type": "string", "description": "where to save it, e.g. public/hero.png (default assets/generated/<name>.png)"},
        "size": {"type": "string", "enum": list(SIZES)},
        "quality": {"type": "string", "enum": list(QUALITIES)},
        "background": {"type": "string", "enum": ["auto", "transparent", "opaque"]},
        "edit": {"type": "array", "items": {"type": "string"}, "description": "image paths to edit or use as references"},
        "detailed": {"type": "boolean", "description": "slower model with more fine detail"},
    },
    "required": ["prompt"],
}


class ImageError(Exception):
    pass


def available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def model(detailed: bool = False) -> str:
    return os.environ.get("DOCKS_IMAGE_MODEL") or (DETAILED if detailed else FAST)


def _base() -> str:
    return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _slug(prompt: str) -> str:
    words = re.findall(r"[a-z0-9]+", prompt.lower())[:6]
    return "-".join(words) or "image"


def gallery_path(root: Path) -> Path:
    key = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:16]
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "projects" / key / "images.json"


def gallery(root: Path) -> list[dict]:
    try:
        items = json.loads(gallery_path(root).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [i for i in items if (root / i["path"]).is_file()]  # files you deleted drop out


def _remember(root: Path, entries: list[dict]) -> None:
    path = gallery_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps((entries + gallery(root))[:500], indent=2) + "\n")


def forget(root: Path, rel: str, delete_file: bool = False) -> None:
    path = gallery_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([i for i in gallery(root) if i["path"] != rel], indent=2) + "\n")
    if delete_file:
        target = (root / rel).resolve()
        if target.is_relative_to(root.resolve()) and target.is_file():
            target.unlink()


def _post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                                          "Content-Type": "application/json"})
    return _send(req)


def _post_form(url: str, fields: dict, files: list[tuple[str, Path]]) -> dict:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, path in files:
        kind = mimetypes.guess_type(path.name)[0] or "image/png"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
                     f"Content-Type: {kind}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _send(req)


def _send(req) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read()).get("error", {}).get("message", "")
        except (json.JSONDecodeError, AttributeError):
            message = ""
        if e.code == 401:
            raise ImageError("OpenAI didn't accept OPENAI_API_KEY")
        raise ImageError(f"the image request failed ({e.code}): {message or e.reason}")
    except urllib.error.URLError as e:
        raise ImageError(f"couldn't reach OpenAI: {e.reason}")


def generate(root: Path, prompt: str, path: str = "", size: str = "auto", quality: str = "auto",
             background: str = "auto", n: int = 1, edit: list | None = None, detailed: bool = False) -> list[dict]:
    """Create (or edit) images and save them in the project. Returns [{path, prompt, model, ...}]."""
    if not available():
        raise ImageError("image generation needs an OpenAI API key: set OPENAI_API_KEY")
    prompt = prompt.strip()
    if not prompt:
        raise ImageError("describe the image you want")
    n = max(1, min(int(n or 1), 4))
    chosen = model(detailed)
    size = SIZES.get(size, size if re.fullmatch(r"\d+x\d+|auto", size or "") else "auto")
    options = {"model": chosen, "prompt": prompt, "n": n, "size": size,
               "quality": quality if quality in QUALITIES else "auto",
               "background": background if background in ("auto", "transparent", "opaque") else "auto"}
    sources = []
    for src in edit or []:
        p = (root / src).resolve() if not Path(src).is_absolute() else Path(src)
        if not p.is_file():
            raise ImageError(f"no image at {src}")
        sources.append(p)
    if sources:
        data = _post_form(f"{_base()}/images/edits", {k: str(v) for k, v in options.items()},
                          [("image[]", p) for p in sources])
    else:
        data = _post_json(f"{_base()}/images/generations", {**options, "output_format": "png"})
    images = [d.get("b64_json") for d in data.get("data", []) if d.get("b64_json")]
    if not images:
        raise ImageError("OpenAI returned no image")
    out = []
    for i, b64 in enumerate(images):
        if path:
            target = Path(path) if Path(path).is_absolute() else root / path
            if len(images) > 1:
                target = target.with_name(f"{target.stem}-{i + 1}{target.suffix or '.png'}")
        else:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            target = root / DEFAULT_DIR / f"{_slug(prompt)}-{stamp}{'-' + str(i + 1) if len(images) > 1 else ''}.png"
        if target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            target = target.with_suffix(".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(b64))
        try:
            rel = str(target.resolve().relative_to(root.resolve()))
        except ValueError:
            rel = str(target)
        out.append({"path": rel, "prompt": prompt, "model": chosen, "size": size, "edited": [str(s) for s in edit or []],
                    "created": time.time()})
    _remember(root, out)
    return out


def preview_block(path: Path, max_bytes: int = 3_500_000) -> dict | None:
    """The image as a content block Claude can look at (skipped if it's very large)."""
    data = path.read_bytes()
    if len(data) > max_bytes:
        return None
    kind = mimetypes.guess_type(path.name)[0] or "image/png"
    return {"type": "image", "source": {"type": "base64", "media_type": kind, "data": base64.b64encode(data).decode()}}
