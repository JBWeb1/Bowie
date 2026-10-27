"""An original score for "The Interview", performed by FluidSynth with the FluidR3 General MIDI soundfont (real sampled instruments).
100 BPM, 2.4 s a bar. The day sets the arrangement: light morning, a working-day groove, an evening with strings, the hire, the end."""
import random
import subprocess
import sys
from pathlib import Path

import mido

P = Path(__file__).parent
BPM, TPB = 100, 480
BEAT = 60 / BPM
BAR = 4 * BEAT
END = 446.63
rng = random.Random(11)

# chord progressions (root, chord tones as MIDI notes)
BRIGHT = [("C", [48, 60, 64, 67]), ("G/B", [47, 59, 62, 67]), ("Am", [45, 57, 60, 64]), ("F", [41, 57, 60, 65])]
WARM = [("F", [41, 57, 60, 65]), ("G", [43, 59, 62, 67]), ("Em", [40, 55, 59, 64]), ("Am", [45, 57, 60, 64])]


def section(t):
    """What plays at time t."""
    if t < 40.2:  return "morning"      # the phone, the interview
    if t < 242.9: return "day"          # code, creative, care, money, teach
    if t < 284.0: return "evening"      # Aether at 7:20 pm
    if t < 411.7: return "night"        # team, developers, organised, weaknesses, the post
    if t < 418.8: return "hired"        # "I'm hired!"
    if t < 424.0: return "lamp"         # lamp off, Sam sleeps
    if t < 439.2: return "rise"         # the end card builds
    return "final"                      # the mark lands, the chord rings out


tracks = {}
CH = {"piano": (0, 4), "bass": (1, 33), "pizz": (2, 45), "strings": (3, 48), "glock": (4, 9), "drums": (9, None), "pad": (5, 89)}


def note(part, t, n, dur, vel):
    tracks.setdefault(part, []).append((t, n, min(dur, END - t), max(1, min(127, int(vel)))))


bar_i = 0
t = 0.0
while t < END - 0.01:
    sec = section(t)
    prog = WARM if sec in ("evening", "night", "lamp") else BRIGHT
    name, chord = prog[bar_i % 4]
    root = chord[0]
    if sec == "final":  # one ringing C major chord, everyone
        for n in [36, 48, 60, 64, 67, 72, 76]:
            note("piano", t, n, 6.5, 92); note("strings", t, n + 12 if n < 60 else n, 7.0, 70)
        note("glock", t, 84, 3.0, 70); note("glock", t + 0.3, 88, 3.0, 60); note("glock", t + 0.6, 91, 3.0, 55)
        note("drums", t, 49, 2.0, 90); note("drums", t, 36, 0.4, 100)
        note("bass", t, 36, 6.5, 90)
        break
    # piano: off-beat chord stabs in the day, held chords in the evening
    if sec in ("day", "night", "rise", "hired"):
        for b in range(4):
            for k, n in enumerate(chord[1:]):
                note("piano", t + b * BEAT + BEAT / 2 + k * 0.008, n, BEAT * 0.45, (62 if sec == "night" else 66) + rng.randint(-5, 5))
    elif sec in ("morning", "evening", "lamp"):
        for k, n in enumerate(chord[1:]):
            note("piano", t + k * 0.03, n, BAR * 0.95, 54 if sec != "lamp" else 44)
        if sec == "morning":
            note("piano", t + 2 * BEAT, chord[1] + 12, BEAT * 1.5, 46)
    # bass
    if sec in ("day", "night", "rise", "hired"):
        for b, (off, dur) in enumerate([(0, 0.9), (1.5, 0.4), (2, 0.9), (3.5, 0.4)]):
            n = root if b % 2 == 0 else root + 7
            note("bass", t + off * BEAT, n, BEAT * dur, 84)
    elif sec == "evening":
        note("bass", t, root, BAR * 0.9, 70)
    # pizzicato arpeggio: the playful line (morning and day)
    if sec in ("morning", "day", "hired", "rise"):
        arp = [chord[1], chord[2], chord[3], chord[2] + 12 if chord[2] + 12 < 84 else chord[2]]
        for e in range(8):
            if sec == "morning" and e % 2:
                continue
            note("pizz", t + e * BEAT / 2, arp[e % 4] + 12, BEAT * 0.4, 58 + (6 if e % 4 == 0 else 0) + rng.randint(-4, 4))
    # strings: evening and night warmth
    if sec in ("evening", "night", "rise", "lamp"):
        for n in chord[1:]:
            note("strings", t, n, BAR, 46 if sec != "rise" else 58)
    # drums: brushed-feel kit
    if sec in ("day", "night", "hired", "rise"):
        for b in range(4):
            note("drums", t + b * BEAT, 36 if b in (0, 2) else 38, 0.2, (80 if b in (0, 2) else 58) + rng.randint(-6, 6))
            for h in range(2):
                note("drums", t + b * BEAT + h * BEAT / 2, 42, 0.1, 44 + (10 if h == 0 else 0) + rng.randint(-6, 6))
    elif sec == "evening" and bar_i % 2 == 0:
        note("drums", t, 51, 1.0, 40)
    # a glockenspiel sparkle at the start of each 8-bar phrase in the day
    if sec in ("day", "rise") and bar_i % 8 == 0:
        for k, n in enumerate([84, 88, 91]):
            note("glock", t + k * BEAT / 2, n, BEAT, 52)
    if sec == "hired" and t < 412.0:
        note("drums", t, 49, 2.0, 96)  # crash on the hire
    bar_i += 1
    t += BAR

# a short ride-cymbal swell into the final chord
for i in range(12):
    note("drums", 439.2 - 2.4 + i * 0.2, 51, 0.2, 40 + i * 4)

mid = mido.MidiFile(ticks_per_beat=TPB)
meta = mido.MidiTrack(); mid.tracks.append(meta)
meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)))
for part, evs in tracks.items():
    ch, prog = CH[part]
    tr = mido.MidiTrack(); mid.tracks.append(tr)
    if prog is not None:
        tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
    tr.append(mido.Message("control_change", channel=ch, control=91, value=50, time=0))  # a little room reverb
    msgs = []
    for (st, n, d, v) in evs:
        msgs.append((st, 1, mido.Message("note_on", channel=ch, note=n, velocity=v)))
        msgs.append((st + d, 0, mido.Message("note_off", channel=ch, note=n, velocity=0)))
    msgs.sort(key=lambda m: (m[0], m[1]))
    last = 0
    for st, _, m in msgs:
        tick = int(round(st / BEAT * TPB))
        tr.append(m.copy(time=max(0, tick - last))); last = max(last, tick)
mid.save(P / "assets/music/score.mid")
subprocess.run(["fluidsynth", "-ni", "-g", "0.7", "-r", "48000", "-F", str(P / "assets/music/score-raw.wav"),
                "/usr/share/sounds/sf2/FluidR3_GM.sf2", str(P / "assets/music/score.mid")], check=True, capture_output=True)
print("score", sum(len(v) for v in tracks.values()), "notes")
