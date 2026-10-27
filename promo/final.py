"""Title and credit cards, then the finished film: cards + scenes, music ducked under Bowie's voice."""
import json, os, subprocess
from pathlib import Path

P = Path(__file__).parent
FPS = 24
CARDS = {"00-open": ("open", 15.0), "99-credits": ("credits", 25.0)}


def card(name, mode, duration):
    from playwright.sync_api import sync_playwright
    out = P / "scenes" / f"{name}.mp4"
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
                           "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=mono",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                           "-shortest", str(out)], stdin=subprocess.PIPE)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get("BOWERS_CHROMIUM") or None, args=["--allow-file-access-from-files"])
        page = b.new_page(viewport={"width": 1920, "height": 1080})
        page.goto((P / "cards.html").as_uri())
        page.evaluate("([m, d]) => setup(m, d)", [mode, duration])
        page.wait_for_timeout(500)
        for f in range(int(duration * FPS)):
            page.evaluate("t => render(t)", f / FPS)
            ff.stdin.write(page.screenshot(type="jpeg", quality=92))
        b.close()
    ff.stdin.close(); ff.wait()


if __name__ == "__main__":
    for name, (mode, d) in CARDS.items():
        if not (P / "scenes" / f"{name}.mp4").exists():
            card(name, mode, d)
    order = ["00-open"] + [s["id"] for s in json.load(open(P / "script.json"))] + ["99-credits"]
    (P / "list.txt").write_text("".join(f"file 'scenes/{n}.mp4'\n" for n in order))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(P / "list.txt"), "-c", "copy", str(P / "joined.mp4")], check=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(P / "joined.mp4")],
                               capture_output=True, text=True).stdout)
    subprocess.run(["python", str(P / "music.py"), str(dur + 1), str(P / "music.wav")], check=True)
    # music sits low and ducks further whenever Bowie talks; louder on the title and credit cards
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(P / "joined.mp4"), "-i", str(P / "music.wav"), "-filter_complex",
                    "[0:a]aresample=48000,asplit=2[voice][key];[1:a]aresample=48000,volume=0.30[m];"
                    "[m][key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=600[duck];"
                    "[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    str(P / "Bowers-Promo-Starring-Bowie.mp4")], check=True)
    print("done", dur)
