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
BAD = (F / "demo-bad/index.html").read_text(); SITE = DEMO / "site/index.html"; GOOD = SITE.read_text(); SITE.write_text(BAD)
EV0 = [{"type": "user", "text": "Build a website for Lemon Lane, my lemonade delivery business: an order form and delivery times. Test it in a browser."},
 {"type": "tool_call", "id": "s1", "name": "read_file", "args": {"path": "README.md"}}, {"type": "tool_output", "id": "s1", "text": "# Lemon Lane"},
 {"type": "tool_call", "id": "s2", "name": "write_file", "args": {"path": "site/index.html", "content": "..."}}, {"type": "tool_output", "id": "s2", "text": "Wrote site/index.html"},
 {"type": "tool_call", "id": "s3", "name": "run_command", "args": {"command": "python -m http.server 5173 -d site"}}, {"type": "tool_output", "id": "s3", "text": "Serving on port 5173"},
 {"type": "tool_call", "id": "s4", "name": "browser", "args": {"action": "test", "url": "http://localhost:5173/"}}, {"type": "tool_output", "id": "s4", "text": "Page loaded."}]
EV = [{"type": "user", "text": "Write tomorrow's launch post for Lemon Lane. Keep it short and friendly."},
      {"type": "text", "id": "p1", "text": POST}, {"type": "idle"}]
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = b.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2); p = ctx.new_page()
    p.add_init_script("localStorage.setItem('bowers-onboarded','1'); localStorage.setItem('docks-theme','dark')")
    p.goto(url); p.wait_for_timeout(1500); p.evaluate("evs => evs.forEach(e => handle(e))", EV0); p.wait_for_timeout(1800); p.hover(".msg-user"); p.wait_for_timeout(400)
    Image.open(io.BytesIO(p.screenshot())).convert("RGB").save(F / "assets/screens/chat-bad-hover.webp", quality=90, method=5)
    SITE.write_text(GOOD)
    b.close()
srv.terminate()
