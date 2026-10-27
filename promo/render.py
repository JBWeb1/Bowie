"""Render each promo scene frame by frame (Playwright) and encode it with its narration (ffmpeg)."""
import json, os, subprocess, sys, wave
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np

P = Path(__file__).parent
FPS = 24
EXTRA = {
    "01-intro": {"chip": "Welcome", "orbit": ["Builds apps", "Writes code", "Tests in a browser", "Makes videos", "Creates images", "Fixes your PC",
                                          "Trading research", "Math tutor", "Talks out loud", "Remembers you", "28 helpers", "73 integrations"]},
    "02-home": {"chip": "Home", "shots": ["dark-home", "light-home"], "points": ["Plain-language requests", "Quick starts", "Images, GitHub, models"]},
    "03-chat": {"chip": "Build", "shots": ["dark-chat"], "pan": 1, "points": ["Reads and writes files", "Runs and tests in a browser", "Live preview + Deploy", "Undo any change"]},
    "04-safety": {"chip": "Safety", "shots": ["dark-settings", "light-settings"], "points": ["Ask / auto / plan modes", "Allow and deny rules", "Sandboxed commands", "Hooks held for approval"]},
    "05-models": {"chip": "Models", "shots": ["dark-cmdk"], "points": ["Solace: fast", "Syntra: powerful", "Aether: Jarvis mode", "Ctrl+K anywhere"]},
    "06-aether": {"chip": "Aether", "shots": ["dark-hud"], "points": ["Talk with your voice", "“Hey Bowie” hands free", "Voice studio", "Learns your preferences"]},
    "07-graph": {"chip": "Aether", "shots": ["dark-graph"], "points": ["Projects, files, memories", "Code import map", "Ask about any node"]},
    "08-motion": {"chip": "Create", "shots": ["dark-motion", "light-motion"], "points": ["Text to video, with sound", "Up to 4K, any aspect", "Image to video", "Highlight clipper"]},
    "09-forge": {"chip": "Create", "shots": ["light-forge", "dark-forge"], "points": ["Logos, posters, thumbnails", "Edit your photos", "Matching brand sets"]},
    "10-care": {"chip": "Care", "shots": ["light-care", "dark-care"], "points": ["Health check", "Plain-English fixes", "Windows, Mac, Linux"]},
    "11-labs": {"chip": "Labs", "shots": ["dark-lab-math", "dark-lab-trading", "dark-lab-arena", "dark-lab-studio3d", "dark-lab-emotes", "dark-labs"],
                "points": ["Math Lab", "Trading Desk (research only)", "Model Arena", "3D, emotes, audits, CI"]},
    "12-agents": {"chip": "Team", "shots": ["dark-agents"], "points": ["28 specialist helpers", "Hand off and check work", "Reports back to you"]},
    "13-integrations": {"chip": "Integrations", "shots": ["dark-integrations", "light-integrations", "dark-lab-skills"], "points": ["73 open-source projects", "One-click install", "No restart needed", "Hooks stay off until approved"]},
    "14-projects": {"chip": "Organized", "shots": ["light-projects", "dark-tasks", "dark-library"], "points": ["Projects", "Background tasks", "Library", "Memory"]},
    "15-github": {"chip": "Developers", "shots": ["light-explore", "dark-settings"], "points": ["GitHub PRs and checks", "Language servers", "MCP apps", "Full terminal"]},
    "16-windows": {"chip": "Install", "shots": ["dark-home"], "points": ["Bowers-Setup.exe", "Start menu + desktop", "One-click updates", "Mac and Linux too"]},
    "17-why": {"chip": "Why Bowie", "checks": ["Builds and tests, not just answers", "Makes the video and the thumbnail", "Fixes the laptop and explains why", "Remembers what you like", "Honest about limits", "Asks before anything risky", "One place instead of ten tools"]},
    "18-outro": {"chip": "Thanks!", "cta": True},
}


def envelope(path, duration):
    with wave.open(str(path)) as w:
        sr = w.getframerate(); a = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    n = int(duration * FPS); hop = sr // FPS
    env = np.array([np.sqrt(np.mean(a[i * hop:(i + 1) * hop] ** 2)) if i * hop < len(a) else 0 for i in range(n)])
    return np.convolve(env, np.ones(3) / 3, "same")  # a little smoothing


def render(job):
    from playwright.sync_api import sync_playwright
    scene, timing, out = job
    wav = P / "audio" / f"{scene['id']}.wav"
    D = timing["duration"]; n = int(D * FPS); env = envelope(wav, D)
    cues = timing["cues"]
    if scene["id"] == "17-why":  # the checklist lands with the narration
        scene["checkAt"] = [cues[min(i + 2, len(cues) - 1)]["start"] for i in range(len(scene["checks"]))]
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-", "-i", str(wav),
                           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                           "-shortest", str(out)], stdin=subprocess.PIPE)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get("BOWERS_CHROMIUM") or None, args=["--allow-file-access-from-files"])
        page = b.new_page(viewport={"width": 1920, "height": 1080})
        page.goto((P / "scene.html").as_uri())
        page.evaluate("s => setup(s)", {**scene, "duration": D})
        page.wait_for_timeout(500)
        for f in range(n):
            t = f / FPS
            cue = next((c["text"] for c in cues if c["start"] - 0.15 <= t <= c["end"] + 0.25), "")
            page.evaluate("([t, a, c]) => render(t, a, c)", [t, float(env[f]), cue])
            ff.stdin.write(page.screenshot(type="jpeg", quality=92))
        b.close()
    ff.stdin.close(); ff.wait()
    return scene["id"], D


if __name__ == "__main__":
    script = json.load(open(P / "script.json")); timings = json.load(open(P / "timings.json"))
    only = sys.argv[1:]
    (P / "scenes").mkdir(exist_ok=True)
    jobs = []
    for i, s in enumerate(script):
        if only and s["id"] not in only:
            continue
        scene = {**s, **EXTRA[s["id"]], "index": f"{i + 1:02d}", "total": len(script)}
        scene.setdefault("shots", [])
        jobs.append((scene, timings[s["id"]], P / "scenes" / f"{s['id']}.mp4"))
    with ProcessPoolExecutor(4) as ex:
        for sid, d in ex.map(render, jobs):
            print("rendered", sid, d, flush=True)
