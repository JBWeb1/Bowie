"""A soft, upbeat ambient bed for the promo: warm pads, a light plucked arpeggio and a gentle pulse."""
import sys, wave
import numpy as np

SR = 44100
seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 620
BPM, BEAT = 96, 60 / 96
bar = 4 * BEAT
note = lambda n: 440 * 2 ** ((n - 69) / 12)
# Cmaj9 - Am9 - Fmaj9 - G6/9, voiced warm
CHORDS = [[48, 55, 64, 67, 71, 74], [45, 52, 60, 64, 67, 71], [41, 48, 57, 60, 64, 67], [43, 50, 59, 62, 64, 69]]
n = int(seconds * SR)
out = np.zeros((n, 2), np.float32)
rng = np.random.default_rng(7)

def pad(freqs, dur):
    t = np.arange(int(dur * SR)) / SR
    env = np.minimum(1, t / 1.2) * np.minimum(1, (dur - t) / 1.4).clip(0)
    sig = np.zeros_like(t)
    for f in freqs:
        for det in (-0.12, 0.12):
            sig += np.sin(2 * np.pi * f * (1 + det / 100) * t + rng.uniform(0, 6)) * 0.6 + 0.15 * np.sin(4 * np.pi * f * t)
    return sig * env / len(freqs)

def pluck(f, dur=0.9):
    t = np.arange(int(dur * SR)) / SR
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) + 0.1 * np.sin(6 * np.pi * f * t)) * np.exp(-t * 5.5)

def thump(dur=0.35):
    t = np.arange(int(dur * SR)) / SR
    return np.sin(2 * np.pi * (55 + 50 * np.exp(-t * 30)) * t) * np.exp(-t * 11)

i, k = 0, 0
while i * bar < seconds:
    start = int(i * bar * SR)
    ch = CHORDS[i % 4]
    p = pad([note(m) for m in ch], bar + 1.4) * 0.22
    end = min(n, start + len(p)); out[start:end, 0] += p[:end - start]; out[start:end, 1] += p[:end - start]
    arp = ch[2:] + [ch[3] + 12]
    for s in range(8):  # eighth-note arpeggio, panned left and right
        at = int((i * bar + s * BEAT / 2) * SR)
        if at >= n:
            break
        pl = pluck(note(arp[(s + k) % len(arp)] + 12)) * 0.07
        e = min(n, at + len(pl)); pan = 0.5 + 0.35 * np.sin(s)
        out[at:e, 0] += pl[:e - at] * (1 - pan); out[at:e, 1] += pl[:e - at] * pan
    if 2 <= (i // 8) % 4:  # a soft pulse in some sections
        for b in range(4):
            at = int((i * bar + b * BEAT) * SR)
            if at < n:
                th = thump() * 0.16; e = min(n, at + len(th)); out[at:e] += th[:e - at, None]
    bass = pad([note(ch[0] - 12)], bar) * 0.25
    end = min(n, start + len(bass)); out[start:end] += bass[:end - start, None]
    i += 1; k += 1
# simple stereo echo, fade in and out
d = int(BEAT * 0.75 * SR)
out[d:, 0] += out[:-d, 1] * 0.25; out[d:, 1] += out[:-d, 0] * 0.25
t = np.arange(n) / SR
out *= np.minimum(1, t / 3)[:, None] * np.minimum(1, (seconds - t) / 5).clip(0)[:, None]
out /= np.abs(out).max() * 1.12
with wave.open(sys.argv[2] if len(sys.argv) > 2 else "music.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((out * 32767).astype("<i2").tobytes())
