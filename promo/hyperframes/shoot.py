"""Real screens of Bowers for the film, at 2x (3200x1800), in the states each chapter needs."""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

F = Path(__file__).parent
DEMO = F.parent / "lemon-lane"
OUT = F / "assets" / "screens"; OUT.mkdir(parents=True, exist_ok=True)
SITE = DEMO / "site" / "index.html"
GOOD = SITE.read_text()
env = {**os.environ, "DOCKS_HOME": str(F.parent / "hfilm-home"), "BOWERS_NO_UPDATE_CHECK": "1", "PYTHONUNBUFFERED": "1",
       "BOWERS_KOKORO_DIR": str(F.parent / "kv")}
env.pop("ANTHROPIC_API_KEY", None)
srv = subprocess.Popen([sys.executable, "-m", "docks", "web", "--no-open", "--port", "8890", "-C", str(DEMO)],
                       cwd="/home/user/bowie", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
url = None
while not url:
    m = re.search(r"(http://\S+#token=\S+)", srv.stdout.readline()); url = m and m.group(1)

ASK = "Build a website for Lemon Lane, my lemonade delivery business: an order form and delivery times. Test it in a browser."
STEPS = [
    {"type": "user", "text": ASK},
    {"type": "tool_call", "id": "s1", "name": "read_file", "args": {"path": "README.md"}},
    {"type": "tool_output", "id": "s1", "text": "# Lemon Lane"},
    {"type": "tool_call", "id": "s2", "name": "write_file", "args": {"path": "site/index.html", "content": "..."}},
    {"type": "tool_output", "id": "s2", "text": "Wrote site/index.html"},
    {"type": "tool_call", "id": "s3", "name": "run_command", "args": {"command": "python -m http.server 5173 -d site"}},
    {"type": "tool_output", "id": "s3", "text": "Serving on port 5173"},
    {"type": "tool_call", "id": "s4", "name": "browser", "args": {"action": "test", "url": "http://localhost:5173/"}},
]
DONE = [
    {"type": "tool_output", "id": "s4", "text": "Page loaded. Order form found. 0 console errors."},
    {"type": "text", "id": "a1", "text": "Done! **Lemon Lane** has its page:\n\n- an order form with size, delivery time and address\n- delivery times up front: order by 2 pm, at your door 4–6 pm\n- checked in a real browser: it loads and there are **no console errors**\n\nWant me to deploy it?"},
    {"type": "idle"},
]

def shot(page, name, wait=700):
    page.wait_for_timeout(wait)
    from PIL import Image; import io
    Image.open(io.BytesIO(page.screenshot())).convert("RGB").save(OUT / f"{name}.webp", quality=90, method=5)
    print("shot", name, flush=True)

def stage(page, events):
    page.evaluate("evs => evs.forEach(e => handle(e))", events)

with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=os.environ.get("BOWERS_CHROMIUM") or "/opt/pw-browsers/chromium")
    def fresh(theme="dark"):
        ctx = b.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        p = ctx.new_page()
        p.add_init_script(f"localStorage.setItem('bowers-onboarded','1'); localStorage.setItem('docks-theme','{theme}'); localStorage.setItem('bowie-voice-engine','local')")
        p.goto(url); p.wait_for_timeout(1500)
        return ctx, p
    # the build, with the rejected first try
    SITE.write_text((F / "demo-bad" / "index.html").read_text())
    ctx, page = fresh()
    page.fill("#input", ASK); shot(page, "home-ask")
    page.fill("#input", "")
    stage(page, STEPS); shot(page, "chat-steps", 1500)
    stage(page, DONE[:1]); shot(page, "chat-bad", 1800)
    ctx.close()
    SITE.write_text(GOOD)
    ctx, page = fresh()
    stage(page, STEPS + DONE); shot(page, "chat-good", 1800)
    page.keyboard.press("Control+k"); page.wait_for_timeout(300); page.keyboard.type("care"); shot(page, "cmdk")
    page.keyboard.press("Escape")
    for name in ("motion", "forge", "care", "integrations", "projects", "tasks", "library", "explore"):
        page.evaluate(f"showPage('{name}')"); page.evaluate("window.scrollTo(0,0); document.querySelectorAll('.page, main, #main').forEach(e => e.scrollTop = 0)"); shot(page, name)
    page.evaluate("showPage('integrations')"); page.fill("#int-search", "video"); page.dispatch_event("#int-search", "input"); shot(page, "integrations-video")
    page.evaluate("showPage('labs')"); page.evaluate("window.scrollTo(0,0)"); shot(page, "labs")
    page.evaluate("openLab('trading')"); page.fill("#tr-sym", "KO"); page.evaluate("document.getElementById('lab-pane').scrollIntoView()"); shot(page, "lab-trading")
    page.evaluate("openLab('math')"); page.fill("#mx", "x^2 - 5x + 6 = 0"); page.click("#mgo"); page.evaluate("document.getElementById('lab-pane').scrollIntoView()"); shot(page, "lab-math-solve", 1500)
    page.select_option("#mop", "factor"); page.click("#mgo"); page.evaluate("document.getElementById('lab-pane').scrollIntoView()"); shot(page, "lab-math-factor", 1500)
    page.fill("#mx", "x^2 - 5x + 6"); page.select_option("#mop", "plot"); page.click("#mgo"); page.evaluate("document.getElementById('lab-pane').scrollIntoView()"); shot(page, "lab-math-plot", 1500)
    page.evaluate("showPage('labs')"); page.evaluate("document.getElementById('agents-grid').scrollIntoView()"); shot(page, "agents")
    page.evaluate("showPage('settings')"); page.click("[data-st=tools]"); shot(page, "settings-safety")
    page.click("[data-st=voice]"); shot(page, "settings-voice", 1500)
    page.evaluate("$('model').value='aether'; saveSettings()"); page.wait_for_timeout(800)
    page.evaluate("showPage('graph')"); shot(page, "graph", 2500)
    page.evaluate("showPage('home'); openHud()"); page.wait_for_timeout(1200)
    page.evaluate("hudLine(\"Hey Bowie, what's left today?\", 'me'); hudLine('Just the launch post. Everything else is done.', 'ai')"); shot(page, "hud")
    ctx.close()
    ctx, page = fresh("light")
    for name in ("home", "care", "motion"):
        page.evaluate(f"showPage('{name}')"); shot(page, f"light-{name}")
    ctx.close()
    # the finished site on its own, for the laptop at midnight and the phone
    ctx = b.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
    p = ctx.new_page(); p.goto(SITE.as_uri()); shot(p, "site-lemon-lane", 600)
    ctx.close(); b.close()
srv.terminate()
