"""Screenshots of every Bowers page for the promo video."""
import os, re, subprocess, sys, time, json
from pathlib import Path
from playwright.sync_api import sync_playwright

S = Path(__file__).parent
OUT = S / "shots"
OUT.mkdir(exist_ok=True)
DEMO = S / "demo"
if not DEMO.exists():  # a small project for the screens to show
    for name, text in {"site/index.html": "<!doctype html><title>Lemon Lane</title><h1>Lemon Lane</h1><p>Fresh lemonade, delivered.</p>",
                       "site/app.js": "console.log('cart')", "server.py": "import api, db\n", "api.py": "import db\n", "db.py": "rows = []\n",
                       "README.md": "# Lemon Lane\n"}.items():
        (DEMO / name).parent.mkdir(parents=True, exist_ok=True); (DEMO / name).write_text(text)
    subprocess.run("git init -q && git add -A && git -c user.email=demo@example.com -c user.name=Demo commit -qm start", shell=True, cwd=DEMO)
env = {**os.environ, "DOCKS_HOME": str(S / "home"), "BOWERS_NO_UPDATE_CHECK": "1", "PYTHONUNBUFFERED": "1"}
env.pop("ANTHROPIC_API_KEY", None)
srv = subprocess.Popen([sys.executable, "-m", "docks", "web", "--no-open", "--port", "8860", "-C", str(S / "demo")],
                       cwd=str(S.parent), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
url = None
for _ in range(60):
    line = srv.stdout.readline()
    m = re.search(r"(http://\S+#token=\S+)", line)
    if m:
        url = m.group(1); break
assert url, "no url"

CHAT = [
    {"type": "user", "text": "Build me a landing page for Lemon Lane with an order form, then test it in a browser."},
    {"type": "tool_call", "id": "t1", "name": "read_file", "args": {"path": "site/index.html"}},
    {"type": "tool_output", "id": "t1", "text": "<!doctype html>..."},
    {"type": "tool_call", "id": "t2", "name": "write_file", "args": {"path": "site/order.html", "content": "..."}},
    {"type": "tool_output", "id": "t2", "text": "Wrote site/order.html (84 lines)"},
    {"type": "tool_call", "id": "t3", "name": "run_command", "args": {"command": "python -m http.server 5173"}},
    {"type": "tool_output", "id": "t3", "text": "Serving on port 5173"},
    {"type": "tool_call", "id": "t4", "name": "browser", "args": {"action": "test", "url": "http://localhost:5173/order.html"}},
    {"type": "tool_output", "id": "t4", "text": "Form submits, 0 console errors, Lighthouse 98"},
    {"type": "text", "id": "a1", "text": "Done! **Lemon Lane** now has a bright landing page and an order form.\n\n- `site/order.html` with name, size and delivery time\n- Checked it in a real browser: the form submits and there are **no console errors**\n- Lighthouse score: **98**\n\nWant me to deploy it, or add online payments next?"},
    {"type": "idle"},
]

def shot(page, name):
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("shot", name, flush=True)

with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=os.environ.get("BOWERS_CHROMIUM") or None)
    for theme in ("dark", "light"):
        ctx = b.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1.2)
        page = ctx.new_page()
        page.add_init_script(f"localStorage.setItem('bowers-onboarded','1'); localStorage.setItem('docks-theme','{theme}')")
        page.goto(url)
        page.wait_for_timeout(1500)
        shot(page, f"{theme}-home")
        if theme == "light":
            for name in ("motion", "forge", "care", "integrations", "library", "explore", "settings", "projects", "tasks"):
                page.evaluate(f"showPage('{name}')"); shot(page, f"light-{name}")
            ctx.close(); continue
        page.evaluate(f"(evs => evs.forEach(e => handle(e)))({json.dumps(CHAT)})")
        shot(page, "dark-chat")
        page.keyboard.press("Control+k"); page.wait_for_timeout(300); page.keyboard.type("mot"); shot(page, "dark-cmdk"); page.keyboard.press("Escape")
        for name in ("motion", "forge", "care", "labs", "integrations", "library", "explore", "settings", "projects", "tasks"):
            page.evaluate(f"showPage('{name}')"); shot(page, f"dark-{name}")
        page.evaluate("window.scrollTo(0,0)")
        for lab in ("trading", "math", "arena", "emotes", "studio3d", "skills"):
            page.evaluate(f"showPage('labs'); openLab('{lab}')"); shot(page, f"dark-lab-{lab}")
        page.evaluate("showPage('labs')"); page.evaluate("document.getElementById('agents-grid').scrollIntoView()"); shot(page, "dark-agents")
        page.evaluate("fetch('/api/settings',{method:'POST',headers:{'content-type':'application/json','x-docks-token':TOKEN},body:JSON.stringify({model:'aether'})})") if False else None
        # Aether: the knowledge graph and the voice HUD
        page.evaluate("$('model').value='aether'; saveSettings()"); page.wait_for_timeout(800)
        page.evaluate("showPage('graph')"); page.wait_for_timeout(2500); shot(page, "dark-graph")
        page.evaluate("showPage('home'); openHud()"); page.wait_for_timeout(1200); shot(page, "dark-hud")
        ctx.close()
    b.close()
srv.terminate()
