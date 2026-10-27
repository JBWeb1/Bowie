"""Bowie's lines with Kokoro, one WAV per chapter, plus the time every beat starts (timings.json)."""
import json, sys, wave
from pathlib import Path
import numpy as np
from kokoro_onnx import Kokoro

P = Path(__file__).parent
KDIR = Path(sys.argv[1])
only = sys.argv[2:]
script = json.load(open(P / "script.json"))
k = Kokoro(str(KDIR / "kokoro-v1.0.int8.onnx"), str(KDIR / "voices-v1.0.bin"))
SR = 24000
GAP = 0.32          # breath between Bowie's lines
out = P / "assets" / "voice"; out.mkdir(parents=True, exist_ok=True)
tpath = P / "timings.json"
timings = json.load(open(tpath)) if (only and tpath.exists()) else {}

def hold(text):  # how long a message must stay on screen to be read
    return max(2.2, 0.5 + 0.3 * len(text.split())) + 0.4

for ch in script["chapters"]:
    if only and ch["id"] not in only:
        continue
    lead = 3.6 if ch.get("q") else 1.2      # the question card plays first
    t, pieces, beats = lead, [np.zeros(int(lead * SR), np.float32)], []
    for b in ch["beats"]:
        if "say" in b:
            a, _ = k.create(b["say"], voice=script["voice"], speed=1.0, lang="en-us")
            d = len(a) / SR
            beats.append({"kind": "say", "text": b["say"], "start": round(t, 3), "end": round(t + d, 3)})
            pieces += [a, np.zeros(int(GAP * SR), np.float32)]; t += d + GAP
        elif "pause" in b:  # the picture acts, nobody talks
            beats.append({"kind": "pause", "tag": b["tag"], "start": round(t, 3), "end": round(t + b["pause"], 3)})
            pieces.append(np.zeros(int(b["pause"] * SR), np.float32)); t += b["pause"]
        else:
            text = b.get("msg") or b.get("hud")
            d = hold(text)
            beats.append({"kind": "msg" if "msg" in b else "hud", "text": text, "start": round(t, 3), "end": round(t + d, 3)})
            pieces.append(np.zeros(int(d * SR), np.float32)); t += d
    tail = 1.4
    pieces.append(np.zeros(int(tail * SR), np.float32)); t += tail
    audio = np.concatenate(pieces)
    with wave.open(str(out / f"{ch['id']}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(audio * 0.92, -1, 1) * 32767).astype("<i2").tobytes())
    timings[ch["id"]] = {"duration": round(len(audio) / SR, 3), "lead": lead, "beats": beats}
    json.dump(timings, open(tpath, "w"), indent=1)
    print(ch["id"], timings[ch["id"]]["duration"], flush=True)
print("total", round(sum(v["duration"] for v in timings.values()) / 60, 2), "min")
