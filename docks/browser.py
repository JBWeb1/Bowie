"""A real browser Claude can drive, so it can check the apps it builds: open a page, click, type, take
screenshots (which Claude sees as images), and read console errors and failed requests.

Uses Playwright (`pip install playwright && playwright install chromium`). The browser lives in one worker
thread because Playwright's sync API only works from the thread that started it.
"""

import atexit
import base64
import glob
import json
import os
import platform
import queue
import shutil
import threading
from pathlib import Path

from .permissions import is_local_url

INSTALL = "The browser tool needs Playwright: pip install playwright && playwright install chromium"
VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844), "tablet": (820, 1180)}
ACTIONS = ["open", "click", "type", "press", "screenshot", "read", "console", "eval", "viewport", "close"]

SCHEMA = {
    "description": (
        "Drive a real browser to check web apps you build, like a person testing them. Open the dev server URL "
        "(from start_process) or an HTML file, then click, type and take screenshots; you see each screenshot. "
        "Every action also reports new console errors and failed network requests. Use it after building or "
        "changing UI to confirm it renders and works, on desktop and mobile. Actions: open (url), click (target), "
        "type (target, text, submit), press (key, e.g. Enter), screenshot (full_page), read (visible text and the "
        "clickable elements with selectors), console (all messages so far), eval (script: a JS expression), "
        "viewport (device: desktop|mobile|tablet, or width/height), close. target is a CSS selector or the "
        "visible text of a button, link or field."),
    "properties": {
        "action": {"type": "string", "enum": ACTIONS},
        "url": {"type": "string"},
        "target": {"type": "string"},
        "text": {"type": "string"},
        "submit": {"type": "boolean", "description": "press Enter after typing"},
        "key": {"type": "string"},
        "script": {"type": "string"},
        "full_page": {"type": "boolean"},
        "device": {"type": "string", "enum": list(VIEWPORTS)},
        "width": {"type": "integer"},
        "height": {"type": "integer"},
    },
    "required": ["action"],
}

ELEMENTS_JS = """() => {
  const out = [], seen = new Set();
  const visible = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const sel = e => {
    if (e.id) return '#' + CSS.escape(e.id);
    for (const a of ['data-testid', 'name', 'aria-label', 'placeholder'])
      if (e.getAttribute(a)) return `${e.tagName.toLowerCase()}[${a}="${e.getAttribute(a).replace(/"/g, '\\\\"')}"]`;
    return null; };
  for (const e of document.querySelectorAll('a,button,input,select,textarea,[role=button],[onclick],[contenteditable=true]')) {
    if (!visible(e) || out.length >= 60) continue;
    const label = (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.title || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
    const kind = e.tagName.toLowerCase() + (e.type && e.tagName === 'INPUT' ? `[${e.type}]` : '');
    const key = kind + label + sel(e); if (seen.has(key)) continue; seen.add(key);
    out.push({ kind, label, selector: sel(e) });
  }
  return out;
}"""


class BrowserError(Exception):
    pass


def _executables() -> list[str]:
    found = [os.environ.get(v) for v in ("DOCKS_BROWSER", "CHROME_PATH") if os.environ.get(v)]
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if base:
        found += [str(Path(base) / "chromium")]
        found += sorted(glob.glob(f"{base}/chromium-*/chrome-linux*/chrome"), reverse=True)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if shutil.which(name):
            found.append(shutil.which(name))
    if platform.system() == "Darwin":
        found += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    return [p for p in found if p and os.path.exists(p)]


class Browser:
    def __init__(self, root: Path):
        self.root = root
        self.url = ""
        self._jobs: queue.Queue = queue.Queue()
        self._thread = None
        self._pw = self._browser = self._page = None
        self._messages = []   # every console message, page error and failed request
        self._unseen = 0      # how many of them Claude hasn't been told about yet
        self._viewport = VIEWPORTS["desktop"]
        atexit.register(self.shutdown)

    # -- the worker thread

    def _call(self, fn, *args):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._work, daemon=True, name="docks-browser")
            self._thread.start()
        done = queue.Queue()
        self._jobs.put((fn, args, done))
        ok, value = done.get()
        if not ok:
            raise value
        return value

    def _work(self):
        while True:
            fn, args, done = self._jobs.get()
            if fn is None:
                done.put((True, None))
                return
            try:
                done.put((True, fn(*args)))
            except Exception as e:  # handed back to the caller's thread
                done.put((False, e))

    # -- browser setup (worker thread only)

    def _ensure(self):
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserError(INSTALL)
        self._pw = sync_playwright().start()
        errors = []
        for options in [{}] + [{"executable_path": p} for p in _executables()] + [{"channel": "chrome"}]:
            try:
                self._browser = self._pw.chromium.launch(headless=True, **options)
                break
            except Exception as e:
                errors.append(str(e).splitlines()[0])
        if self._browser is None:
            self._pw.stop()
            self._pw = None
            raise BrowserError(f"{INSTALL}\n(couldn't start Chromium: {errors[0] if errors else 'unknown error'})")
        self._new_page()

    def _new_page(self):
        width, height = self._viewport
        mobile = width < 600
        context = self._browser.new_context(viewport={"width": width, "height": height}, is_mobile=mobile,
                                            has_touch=mobile, device_scale_factor=2 if mobile else 1)
        self._page = context.new_page()
        self._page.on("console", lambda m: self._note(m.type, m.text) if m.type in ("error", "warning", "log", "info") else None)
        self._page.on("pageerror", lambda e: self._note("pageerror", str(e)))
        self._page.on("requestfailed", lambda r: self._note("requestfailed", f"{r.method} {r.url} ({r.failure})"))
        self._page.on("response", lambda r: self._note("http", f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)

    def _note(self, kind, text):
        self._messages.append((kind, text[:500]))
        self._messages = self._messages[-300:]

    # -- actions (worker thread only)

    def _resolve_url(self, url: str) -> str:
        if "://" in url or url.startswith(("about:", "data:")):
            return url
        if url.startswith(("localhost", "127.0.0.1")) or url.split("/")[0].count(":") == 1 and url[0].isdigit():
            return "http://" + url
        path = (self.root / url).resolve()
        if path.exists():
            return path.as_uri()
        return "http://" + url

    def _locate(self, target: str):
        page = self._page
        candidates = []
        if any(c in target for c in "#.[>=:") or target.split()[0] in ("button", "a", "input", "form", "select", "textarea"):
            candidates.append(page.locator(target))
        candidates += [page.get_by_role("button", name=target), page.get_by_role("link", name=target),
                       page.get_by_label(target), page.get_by_placeholder(target), page.get_by_text(target)]
        for loc in candidates:
            try:
                if loc.count() > 0:
                    visible = [loc.nth(i) for i in range(min(loc.count(), 10)) if loc.nth(i).is_visible()]
                    return visible[0] if visible else loc.first
            except Exception:
                continue
        raise BrowserError(f"nothing on the page matches {target!r}; use read to see the clickable elements")

    def _settle(self):
        try:
            self._page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        self._page.wait_for_timeout(250)

    def _shot(self, full_page=False) -> dict:
        data = self._page.screenshot(type="jpeg", quality=70, full_page=bool(full_page))
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(data).decode()}}

    def _do(self, args: dict) -> tuple[str, bool]:
        action = args["action"]
        if action == "close":
            self._close()
            return "browser closed", False
        if action == "viewport":
            if args.get("device"):
                self._viewport = VIEWPORTS[args["device"]]
            elif args.get("width") and args.get("height"):
                self._viewport = (args["width"], args["height"])
            else:
                raise BrowserError("viewport needs device, or width and height")
            if self._page is not None:
                url = self._page.url
                self._page.context.close()
                self._new_page()
                if url and url != "about:blank":
                    self._page.goto(url, wait_until="load", timeout=30000)
                    self._settle()
            return f"viewport is now {self._viewport[0]}x{self._viewport[1]}", True
        self._ensure()
        page = self._page
        if action == "open":
            if not args.get("url"):
                raise BrowserError("open needs a url")
            response = page.goto(self._resolve_url(args["url"]), wait_until="load", timeout=30000)
            self._settle()
            status = f" (HTTP {response.status})" if response is not None else ""
            return f"opened {page.url}{status} · title: {page.title()!r}", True
        if action == "click":
            self._locate(self._need(args, "target")).click(timeout=5000)
            self._settle()
            return f"clicked {args['target']!r} · now at {page.url}", True
        if action == "type":
            field = self._locate(self._need(args, "target"))
            field.fill(args.get("text", ""), timeout=5000)
            if args.get("submit"):
                field.press("Enter")
            self._settle()
            return f"typed into {args['target']!r}" + (" and pressed Enter" if args.get("submit") else ""), True
        if action == "press":
            page.keyboard.press(self._need(args, "key"))
            self._settle()
            return f"pressed {args['key']}", True
        if action == "screenshot":
            return f"{page.url} · {self._viewport[0]}x{self._viewport[1]}", True
        if action == "read":
            text = page.inner_text("body")[:6000] if page.url != "about:blank" else ""
            elements = page.evaluate(ELEMENTS_JS)
            lines = [f"{e['kind']:<16} {e['label']!r:<40} {e['selector'] or ''}" for e in elements]
            return (f"{page.url} · title {page.title()!r}\n\nVisible text:\n{text or '(none)'}\n\n"
                    f"Clickable elements (target them by selector or label):\n" + ("\n".join(lines) or "(none)")), False
        if action == "console":
            self._unseen = len(self._messages)
            return "\n".join(f"[{k}] {t}" for k, t in self._messages) or "(no console messages yet)", False
        if action == "eval":
            value = page.evaluate(self._need(args, "script"))
            return json.dumps(value, default=str)[:20000], False
        raise BrowserError(f"unknown action {action!r}")

    @staticmethod
    def _need(args, key):
        if not args.get(key):
            raise BrowserError(f"{args['action']} needs {key}")
        return args[key]

    def _run(self, args: dict) -> list:
        summary, with_shot = self._do(args)
        blocks = [{"type": "text", "text": summary}]
        fresh = [(k, t) for k, t in self._messages[self._unseen:] if k in ("error", "pageerror", "requestfailed", "http")]
        self._unseen = len(self._messages)
        if fresh:
            blocks[0]["text"] += "\n\nProblems since the last action:\n" + "\n".join(f"[{k}] {t}" for k, t in fresh[-30:])
        if (with_shot or args.get("action") == "screenshot") and self._page is not None:
            blocks.append(self._shot(args.get("full_page")))
        self.url = self._page.url if self._page is not None else ""
        return blocks

    def _close(self):
        try:
            if self._browser is not None:
                self._browser.close()
            if self._pw is not None:
                self._pw.stop()
        finally:
            self._browser = self._page = self._pw = None
            self.url = ""

    # -- public

    def run(self, args: dict) -> list:
        """Do one action; returns tool_result content blocks (text, plus a screenshot for most actions)."""
        return self._call(self._run, args)

    def needs_ok(self, args: dict) -> bool:
        """Clicking or typing on someone else's site can change things there, so it asks. Local apps don't."""
        if args.get("action") in ("click", "type", "press", "eval"):
            return bool(self.url) and not is_local_url(self.url)
        return False

    def shutdown(self):
        if self._thread is not None and self._thread.is_alive():
            try:
                self._call(self._close)
                self._call(None)
            except Exception:
                pass

