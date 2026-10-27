"""Bowie's narration with Kokoro, sentence by sentence, with caption timings."""
import json, re, sys, wave
from pathlib import Path
import numpy as np
from kokoro_onnx import Kokoro

S = Path(__file__).parent
VOICE = sys.argv[1] if len(sys.argv) > 1 else "am_puck"
out = S / "audio"
out.mkdir(exist_ok=True)
sys.path.insert(0, str(S.parent))
from docks.voice import _kokoro_files  # the model from `bowers voices install`
k = Kokoro(*map(str, _kokoro_files()))
GAP, LEAD, TAIL = 0.28, 0.6, 0.9
only = sys.argv[2:]
timings = json.load(open(S / "timings.json")) if only else {}
for scene in json.load(open(S / "script.json")):
    if only and scene["id"] not in only:
        continue
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", scene["text"]) if s]
    chunks, cues, t, sr = [], [], LEAD, 24000
    for sent in sentences:
        audio, sr = k.create(sent, voice=VOICE, speed=1.0, lang="en-us")
        cues.append({"start": round(t, 2), "end": round(t + len(audio) / sr, 2), "text": sent})
        chunks += [audio, np.zeros(int(GAP * sr), np.float32)]
        t += len(audio) / sr + GAP
    full = np.concatenate([np.zeros(int(LEAD * sr), np.float32)] + chunks + [np.zeros(int(TAIL * sr), np.float32)])
    with wave.open(str(out / f"{scene['id']}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(full, -1, 1) * 32767).astype("<i2").tobytes())
    timings[scene["id"]] = {"duration": round(len(full) / sr, 2), "cues": cues}
    print(scene["id"], timings[scene["id"]]["duration"], flush=True)
    json.dump(timings, open(S / "timings.json", "w"), indent=1)
