import os, re, subprocess, sys, io
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image
F = Path(__file__).parent; DEMO = F.parent / "lemon-lane"
env = {**os.environ, "DOCKS_HOME": str(F.parent / "hfilm-home"), "BOWERS_NO_UPDATE_CHECK": "1", "PYTHONUNBUFFERED": "1"}
env.pop("ANTHROPIC_API_KEY", None)
srv = subprocess.Popen([sys.executable, "-m", "docks", "web", "--no-open", "--port", "8891", "-C", str(DEMO)], cwd="/home/user/bowie", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
url = None
while not url:
    m = re.search(r"(http://\S+#token=\S+)", srv.stdout.readline()); url = m and m.group(1)
POST = ("Here's tomorrow's launch post:\n\n> 🍋 **Lemon Lane is open!**\n> Fresh lemonade, squeezed every morning and delivered cold to your door.\n"
        "> Order by 2 pm and it's with you between 4 and 6.\n> Order here: lemonlane.example\n\nWant a shorter version for Instagram too?")
EV = [{"type": "user", "text": "Write tomorrow's launch post for Lemon Lane. Keep it short and friendly."},
      {"type": "text", "id": "p1", "text": POST}, {"type": "idle"}]
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = b.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2); p = ctx.new_page()
    p.add_init_script("localStorage.setItem('bowers-onboarded','1'); localStorage.setItem('docks-theme','dark')")
    p.goto(url); p.wait_for_timeout(1500); p.evaluate("evs => evs.forEach(e => handle(e))", EV); p.wait_for_timeout(1500)
    Image.open(io.BytesIO(p.screenshot())).convert("RGB").save(F / "assets/screens/chat-post.webp", quality=90, method=5)
    b.close()
srv.terminate()
