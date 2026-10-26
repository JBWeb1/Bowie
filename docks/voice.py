"""Bowie's voice. With ELEVENLABS_API_KEY, replies are spoken by an ElevenLabs voice you pick in Settings > Voice
(design one in ElevenLabs Voice Design to give Bowie a voice of its own). Without it, the browser's built-in
speech is used, tuned to sound small and friendly.
"""

import json
import os
import urllib.error
import urllib.request

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
