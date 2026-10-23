"""Bowers Motion: video generation with Lightricks' LTX-2.5 (text to video, and image to video).

    bowers video "a fox running through snow at sunrise, cinematic" --seconds 8
    bowers video "the camera slowly pushes in" --image public/hero.png --pro

Needs LTX_API_KEY (from ltx.io). Uses the LTX API v2: a job is submitted, polled until it's done, and the MP4 is
downloaded into the project (assets/videos/ unless you choose a path). The videos have sound. Two models:
ltx-2-5-fast (quick, up to 4K and 20 seconds) and ltx-2-5-pro (best quality). LTX_BASE_URL points elsewhere.
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
from pathlib import Path

FAST, PRO = "ltx-2-5-fast", "ltx-2-5-pro"
MODELS = {FAST: "Bowers Motion Fast", PRO: "Bowers Motion Pro"}
ASPECTS = ("16:9", "9:16")
RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160)}
LIMITS = {  # what each model accepts (LTX-2.5 docs): resolutions, durations in seconds
    FAST: {"resolutions": ("720p", "1080p", "1440p", "4k"), "durations": (6, 8, 10, 12, 14, 16, 18, 20)},
    PRO: {"resolutions": ("720p", "1080p"), "durations": (6, 8, 10)},
}
LONG_LIMIT = ("720p", "1080p")  # 12 seconds and longer only at these sizes
DEFAULT_DIR = "assets/videos"
TIMEOUT = 20 * 60

SCHEMA = {
    "description": (
        "Create a video with sound (Bowers Motion, LTX-2.5) and save it in the project as MP4: product shots, "
        "hero loops, intros, social clips, scenes. Describe the shot like a director: subject, action, camera "
        "movement, lighting, style, sound. To animate a picture, pass its path in image (it becomes the first "
        "frame). Takes one to a few minutes. Costs money per second, so make one video unless asked for more."),
    "properties": {
        "prompt": {"type": "string"},
        "image": {"type": "string", "description": "a project image to start from (image to video)"},
        "seconds": {"type": "integer", "description": "6, 8 or 10 (fast also 12-20); omit to let the model choose"},
        "aspect": {"type": "string", "enum": list(ASPECTS)},
        "resolution": {"type": "string", "enum": list(RESOLUTIONS)},
        "pro": {"type": "boolean", "description": "the slower, highest-quality model"},
        "path": {"type": "string", "description": "where to save it, e.g. public/intro.mp4"},
    },
    "required": ["prompt"],
}


class MotionError(Exception):
    pass


def available() -> bool:
    return bool(os.environ.get("LTX_API_KEY"))


def _base() -> str:
    return os.environ.get("LTX_BASE_URL", "https://api.ltx.io").rstrip("/")


def _slug(prompt: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", prompt.lower())[:6]) or "video"


def gallery_path(root: Path) -> Path:
    key = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:16]
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "projects" / key / "videos.json"


def gallery(root: Path) -> list[dict]:
    try:
        items = json.loads(gallery_path(root).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [i for i in items if (root / i["path"]).is_file()]


def _remember(root: Path, entry: dict) -> None:
    path = gallery_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(([entry] + gallery(root))[:500], indent=2) + "\n")


def forget(root: Path, rel: str, delete_file: bool = False) -> None:
    path = gallery_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([i for i in gallery(root) if i["path"] != rel], indent=2) + "\n")
    target = (root / rel).resolve()
    if delete_file and target.is_relative_to(root.resolve()) and target.is_file():
        target.unlink()


def resolution_string(resolution: str, aspect: str) -> str:
    w, h = RESOLUTIONS[resolution]
    return f"{w}x{h}" if aspect == "16:9" else f"{h}x{w}"


def check_options(model: str, seconds, resolution: str, aspect: str) -> None:
    limits = LIMITS[model]
    if aspect not in ASPECTS:
        raise MotionError(f"aspect must be one of {', '.join(ASPECTS)}")
    if resolution not in limits["resolutions"]:
        raise MotionError(f"{MODELS[model]} makes {', '.join(limits['resolutions'])} videos")
    if seconds is None:
        if model == PRO:
            raise MotionError(f"{MODELS[PRO]} needs a length: {', '.join(map(str, limits['durations']))} seconds")
        return
    if seconds not in limits["durations"]:
        raise MotionError(f"{MODELS[model]} makes videos of {', '.join(map(str, limits['durations']))} seconds")
    if seconds > 10 and resolution not in LONG_LIMIT:
        raise MotionError("videos longer than 10 seconds can be 720p or 1080p")


def _request(method: str, url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": f"Bearer {os.environ['LTX_API_KEY']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            data = json.loads(raw)
            err = data.get("error")
            message = (err.get("message") if isinstance(err, dict) else err) or data.get("message") or data.get("detail") or ""
        except (json.JSONDecodeError, AttributeError):
            message = raw.decode(errors="replace")[:300]
        if e.code == 401:
            raise MotionError("LTX didn't accept LTX_API_KEY")
        if e.code == 402:
            raise MotionError("your LTX account is out of credits")
        raise MotionError(f"the video request failed ({e.code}): {message or e.reason}")
    except urllib.error.URLError as e:
        raise MotionError(f"couldn't reach LTX: {e.reason}")


def _image_uri(root: Path, image: str) -> str:
    if image.startswith(("http://", "https://", "ltx://", "data:")):
        return image
    p = Path(image) if Path(image).is_absolute() else root / image
    if not p.is_file():
        raise MotionError(f"no image at {image}")
    if p.stat().st_size > 15_000_000:
        raise MotionError("the image is over 15 MB; use a smaller one")
    kind = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{kind};base64,{base64.b64encode(p.read_bytes()).decode()}"


def generate(root: Path, prompt: str, image: str = "", seconds: int | None = 8, aspect: str = "16:9",
             resolution: str = "1080p", pro: bool = False, path: str = "", sound: bool = True,
             on_status=None, should_stop=None) -> dict:
    """Make a video and save it in the project. Returns {path, prompt, model, ...}.

    on_status(text) hears progress; should_stop() returning True cancels the wait."""
    if not available():
        raise MotionError("Bowers Motion needs an LTX API key: set LTX_API_KEY (get one at ltx.io)")
    prompt = prompt.strip()
    if not prompt:
        raise MotionError("describe the video you want")
    model = PRO if pro else FAST
    seconds = int(seconds) if seconds not in (None, "", 0, "auto") else None
    check_options(model, seconds, resolution, aspect)
    kind = "image-to-video" if image else "text-to-video"
    body = {"prompt": prompt, "model": model, "duration": seconds, "resolution": resolution_string(resolution, aspect)}
    if image:
        body["image_uri"] = _image_uri(root, image)
    if not sound:
        body["generate_audio"] = False
    say = on_status or (lambda text: None)
    job = _request("POST", f"{_base()}/v2/{kind}", body)
    job_id = job.get("id")
    if not job_id:
        raise MotionError("LTX didn't return a job id")
    say("queued")
    start, delay, status = time.monotonic(), 3.0, ""
    while True:
        if should_stop and should_stop():
            raise MotionError("stopped waiting for the video (LTX may still finish it)")
        if time.monotonic() - start > TIMEOUT:
            raise MotionError("the video took longer than 20 minutes; try again")
        time.sleep(delay)
        delay = min(delay * 1.3, 10)
        job = _request("GET", f"{_base()}/v2/{kind}/{job_id}")
        status = str(job.get("status", "")).lower()
        if status in ("completed", "succeeded", "success", "done"):
            break
        if status in ("failed", "error", "cancelled", "canceled", "rejected"):
            err = job.get("error")
            raise MotionError(f"LTX couldn't make the video: {(err.get('message') if isinstance(err, dict) else err) or status}")
        say(status or "working")
    url = (job.get("result") or {}).get("video_url") or job.get("video_url")
    if not url:
        raise MotionError("LTX finished but sent no video link")
    if path:
        target = Path(path) if Path(path).is_absolute() else root / path
    else:
        target = root / DEFAULT_DIR / f"{_slug(prompt)}-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
    target = target.with_suffix(".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    say("downloading")
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=300) as resp, target.open("wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        raise MotionError(f"couldn't download the video: {e}")
    try:
        rel = str(target.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(target)
    entry = {"path": rel, "prompt": prompt, "model": model, "label": MODELS[model], "seconds": seconds,
             "aspect": aspect, "resolution": resolution, "image": image if image and not image.startswith("data:") else "",
             "created": time.time(), "seconds_taken": round(time.monotonic() - start)}
    _remember(root, entry)
    return entry
