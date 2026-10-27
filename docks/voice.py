"""Bowie's voice. With ELEVENLABS_API_KEY, replies are spoken by an ElevenLabs voice you pick in Settings > Voice
(design one in ElevenLabs Voice Design to give Bowie a voice of its own). With the Kokoro integration installed,
a natural voice runs on this computer: free, offline and private. Otherwise the browser's built-in speech is used.

Speech to text: the browser's speech recognition where it exists (Chrome, Edge), or faster-whisper on this
computer when it's installed (any browser, offline).
"""

import base64
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
import wave
from pathlib import Path

BASE = "https://api.elevenlabs.io/v1"
MODEL = "eleven_flash_v2_5"  # fast, made for live conversation
MAX_CHARS = 2500


class VoiceError(Exception):
    pass


def available() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


def _base() -> str:
    return os.environ.get("ELEVENLABS_BASE_URL", BASE).rstrip("/")


def _call(path: str, body: dict | None = None, accept: str = "application/json") -> bytes:
    req = urllib.request.Request(_base() + path, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"xi-api-key": os.environ.get("ELEVENLABS_API_KEY", ""),
                                          "Content-Type": "application/json", "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise VoiceError("ElevenLabs didn't accept ELEVENLABS_API_KEY")
        try:
            detail = json.loads(e.read()).get("detail")
            detail = detail.get("message") if isinstance(detail, dict) else detail
        except (json.JSONDecodeError, AttributeError):
            detail = e.reason
        raise VoiceError(f"ElevenLabs said no ({e.code}): {detail}")
    except urllib.error.URLError as e:
        raise VoiceError(f"couldn't reach ElevenLabs: {e.reason}")


def voices() -> list[dict]:
    data = json.loads(_call("/voices"))
    return [{"id": v["voice_id"], "name": v.get("name", ""), "category": v.get("category", ""),
             "preview": v.get("preview_url", ""), "labels": v.get("labels") or {}} for v in data.get("voices", [])]


def speak(text: str, voice_id: str) -> bytes:
    """MP3 audio of text in the chosen voice."""
    if not available():
        raise VoiceError("add ELEVENLABS_API_KEY to use an ElevenLabs voice")
    if not voice_id or not voice_id.replace("-", "").isalnum():
        raise VoiceError("pick a voice in Settings > Voice first")
    text = text.strip()[:MAX_CHARS]
    if not text:
        raise VoiceError("nothing to say")
    return _call(f"/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                 {"text": text, "model_id": os.environ.get("BOWERS_VOICE_MODEL", MODEL)}, accept="audio/mpeg")


# ---------------------------------------------------------------- Kokoro: a local voice (hexgrad/Kokoro-82M, Apache-2.0)
KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_NPM = "https://registry.npmjs.org/{0}/-/{0}-{1}.tgz"  # a mirror of the same weights, for networks that block GitHub downloads
KOKORO_NPM_SHA = "fbae9257e1e05ffc727e951ef9b9c98418e6d79f1c9b6b13bd59f5c9028a1478"
LOCAL_VOICES = {  # the friendliest English voices; any other Kokoro voice name works too
    "am_puck": "Puck (playful)", "am_michael": "Michael (warm)", "am_echo": "Echo (bright)", "am_eric": "Eric (calm)",
    "am_fenrir": "Fenrir (bold)", "af_heart": "Heart (warm)", "af_bella": "Bella (lively)", "af_nova": "Nova (clear)",
    "af_sky": "Sky (soft)", "bm_george": "George (British)", "bf_emma": "Emma (British)",
}
DEFAULT_LOCAL = "am_puck"
_kokoro = None
_kokoro_lock = threading.Lock()


def kokoro_dir() -> Path:
    return Path(os.environ.get("BOWERS_KOKORO_DIR") or Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "voices" / "kokoro")


def _kokoro_files():
    d = kokoro_dir()
    model = next((p for p in (d / "kokoro-v1.0.int8.onnx", d / "kokoro-v1.0.onnx", d / "kokoro.onnx") if p.is_file()), None)
    voices = next((p for p in (d / "voices-v1.0.bin", d / "voices.npz") if p.is_file()), None)
    return model, voices


def local_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("kokoro_onnx") is not None and all(_kokoro_files())


def local_voices() -> list[dict]:
    return [{"id": k, "name": v} for k, v in LOCAL_VOICES.items()] if local_available() else []


def speak_local(text: str, voice: str = DEFAULT_LOCAL, speed: float = 1.0) -> bytes:
    """WAV audio of text in a Kokoro voice, made on this computer."""
    global _kokoro
    if not local_available():
        raise VoiceError("install the Kokoro voice first (Integrations > Kokoro voice, or `bowers voices install`)")
    voice = voice or DEFAULT_LOCAL
    if not voice.replace("_", "").isalnum():
        raise VoiceError("unknown voice")
    text = text.strip()[:MAX_CHARS]
    if not text:
        raise VoiceError("nothing to say")
    with _kokoro_lock:
        if _kokoro is None:
            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(*map(str, _kokoro_files()))
        try:
            samples, rate = _kokoro.create(text, voice=voice, speed=max(0.5, min(2.0, speed)), lang="en-gb" if voice[0] == "b" else "en-us")
        except (KeyError, ValueError) as e:
            raise VoiceError(f"Kokoro couldn't speak that: {e}")
    import numpy as np
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _download(url: str, dest: Path, log) -> None:
    log(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    tmp.replace(dest)


def install_local(log=print) -> Path:
    """Fetch Kokoro's model and voices into ~/.docks/voices/kokoro (about 115 MB)."""
    global _kokoro
    d = kokoro_dir()
    d.mkdir(parents=True, exist_ok=True)
    if all(_kokoro_files()):
        log(f"Kokoro is already in {d}")
        return d
    try:
        _download(KOKORO_RELEASE + "kokoro-v1.0.int8.onnx", d / "kokoro-v1.0.int8.onnx", log)
        _download(KOKORO_RELEASE + "voices-v1.0.bin", d / "voices-v1.0.bin", log)
    except (urllib.error.URLError, OSError) as e:
        log(f"GitHub download failed ({e}); trying the npm mirror")
        _install_from_npm(d, log)
    _kokoro = None
    log(f"✓ Kokoro voice ready in {d}")
    return d


def _install_from_npm(d: Path, log) -> None:
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name, version in (("kokoro-q8-shards", "1.0.0"), ("kokoro-local-runtime", "0.1.0")):
            _download(KOKORO_NPM.format(name, version), tmp / f"{name}.tgz", log)
            with tarfile.open(tmp / f"{name}.tgz") as t:
                t.extractall(tmp / name, filter="data")
        parts = sorted((tmp / "kokoro-q8-shards" / "package").glob("kokoro-q8.part*.bin"), key=lambda p: int(p.stem.split("part")[1]))
        model = d / "kokoro.onnx"
        with open(model, "wb") as out:
            for p in parts:
                out.write(p.read_bytes())
        if hashlib.sha256(model.read_bytes()).hexdigest() != KOKORO_NPM_SHA:
            model.unlink()
            raise VoiceError("the downloaded Kokoro model didn't match its checksum")
        voices = {p.stem: np.fromfile(p, dtype=np.float32).reshape(-1, 1, 256)
                  for p in (tmp / "kokoro-local-runtime" / "package" / "voices").glob("*.bin")}
        np.savez(d / "voices.npz", **voices)


# ---------------------------------------------------------------- speech to text with faster-whisper (MIT)
_whisper = None
_whisper_lock = threading.Lock()


def stt_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("faster_whisper") is not None


def transcribe(data_url: str) -> str:
    """Text of a short recording (a data: URL from the browser's MediaRecorder)."""
    global _whisper
    if not stt_available():
        raise VoiceError("install faster-whisper for voice input in this browser (Integrations > faster-whisper)")
    head, _, b64 = data_url.partition(",")
    if not head.startswith("data:audio/") or not b64:
        raise VoiceError("expected an audio recording")
    audio = base64.b64decode(b64)
    if len(audio) > 15 * 1024 * 1024:
        raise VoiceError("recording too long")
    with _whisper_lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(os.environ.get("BOWERS_WHISPER_MODEL", "base"), device="auto", compute_type="int8")
        segments, _ = _whisper.transcribe(io.BytesIO(audio), vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
