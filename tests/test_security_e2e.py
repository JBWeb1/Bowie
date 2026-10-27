"""The web server's protections, and end-to-end runs: the page in a real browser, and (opt-in) a real model.

Real-model test: BOWERS_E2E=1 with ANTHROPIC_API_KEY set. It spends a few cents.
"""

import http.client
import json
import os
import threading
from http.server import ThreadingHTTPServer

import pytest

from docks.agent import Agent
from docks.web.server import CSP, LOCAL_HOSTS, Session, make_handler
from tests.test_docks import FakeClient, msg
from tests.test_extensions import Display, homes, text  # noqa: F401  (homes is an autouse fixture)


def serve(tmp_path, responses=()):
    session = Session(Agent(root=tmp_path, client=FakeClient(list(responses))))
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(session, "tok", {"port": 1, "prefix": "/p/"}, LOCAL_HOSTS))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return session, server.server_port


def request(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers={"x-docks-token": "tok", **(headers or {})})
    resp = conn.getresponse()
    return resp.status, dict(resp.getheaders()), resp.read()


def test_page_headers_and_split_files(tmp_path):
    _, port = serve(tmp_path)
    status, headers, body = request(port, "GET", "/")
    assert status == 200 and headers["content-security-policy"] == CSP and "frame-ancestors 'none'" in CSP
    assert headers["x-frame-options"] == "DENY" and headers["x-content-type-options"] == "nosniff"
    assert b"<script>" not in body and b'<script src="/app/core.js">' in body  # no inline script: CSP can be strict
    for name in ("core.js", "chat.js", "workspace.js", "pages.js", "bowers.js", "integrations.js", "app.css"):
        s, h, _ = request(port, "GET", "/app/" + name)
        assert s == 200 and h["cache-control"] == "no-cache", name
    assert request(port, "GET", "/app/../server.py")[0] == 404


def test_dns_rebinding_and_cross_site_requests_are_refused(tmp_path):
    _, port = serve(tmp_path)
    assert request(port, "GET", "/", {"host": "evil.example:80"})[0] == 421
    assert request(port, "GET", "/api/state", {"host": "attacker.test"})[0] == 421
    assert request(port, "POST", "/api/terminal", {"host": "attacker.test"}, {"command": "echo hi"})[0] == 421
    s, _, _ = request(port, "POST", "/api/terminal", {"origin": "https://evil.example", "content-type": "application/json"}, {"command": "echo hi"})
    assert s == 403
    s, _, body = request(port, "POST", "/api/terminal", {"origin": f"http://127.0.0.1:{port}", "host": f"127.0.0.1:{port}"}, {"command": "echo hi"})
    assert s == 200 and b"hi" in body
    assert request(port, "GET", "/api/state", {"x-docks-token": "wrong"})[0] == 401


def test_thumbnails_only_for_known_projects(tmp_path):
    secret = tmp_path / "elsewhere"
    secret.mkdir()
    (secret / "photo.png").write_bytes(b"\x89PNG" + b"0" * 5000)
    _, port = serve(tmp_path / "proj" if (tmp_path / "proj").mkdir() is None else tmp_path)
    assert request(port, "GET", f"/api/projects/thumb?root={secret}")[0] == 404


@pytest.mark.skipif(not __import__("importlib").util.find_spec("playwright"), reason="needs Playwright")
def test_every_page_loads_in_a_real_browser(tmp_path):
    from playwright.sync_api import sync_playwright
    session, port = serve(tmp_path, [msg("end_turn", text("Hello from Bowie!"))])
    exe = os.environ.get("BOWERS_TEST_CHROMIUM", "/opt/pw-browsers/chromium")
    errors = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=exe if exe and os.path.exists(exe) else None)
        except Exception as e:  # no browser installed for Playwright
            pytest.skip(f"no browser: {e}")
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and "Content Security Policy" in m.text and errors.append(m.text))
        page.add_init_script("localStorage.setItem('bowers-onboarded', '1')")
        page.goto(f"http://127.0.0.1:{port}/#token=tok")
        page.wait_for_timeout(800)
        page.evaluate("send('Build me a hello page')")
        page.wait_for_selector("text=Build me a hello page", timeout=10000)  # the message went through the API
        page.wait_for_selector("#status-text:text('Ready')", timeout=10000)   # and the turn finished
        for name in ("motion", "forge", "care", "labs", "integrations", "projects", "library", "tasks", "explore", "settings"):
            page.evaluate(f"showPage('{name}')")
            page.wait_for_timeout(250)
            assert not page.locator(f"#page-{name}").is_hidden(), name
        assert page.evaluate("md('> **Hi**\\n> there')") == "<blockquote><strong>Hi</strong><br>there</blockquote>"
        page.keyboard.press("Control+k")
        assert page.locator("#cmdk").is_visible()
        page.keyboard.press("Escape")
        page.click("#side-search")  # the simple sidebar: search opens the same palette
        assert page.locator("#cmdk").is_visible()
        browser.close()
    assert errors == []


@pytest.mark.skipif(not (os.environ.get("BOWERS_E2E") and os.environ.get("ANTHROPIC_API_KEY")),
                    reason="set BOWERS_E2E=1 and ANTHROPIC_API_KEY to run against a real model")
def test_real_model_builds_and_runs_a_script(tmp_path):
    agent = Agent(root=tmp_path, model="solace", mode="yolo", display=Display())
    agent.run("Write add.py that prints the sum of 2 and 3, run it, and tell me the output.")
    assert (tmp_path / "add.py").is_file()
    assert "5" in agent.last_text()


def test_update_check(monkeypatch, tmp_path):
    from http.server import BaseHTTPRequestHandler
    from docks import updater

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            data = json.dumps({"tag_name": "v9.1.0", "body": "New things", "html_url": "https://x",
                               "assets": [{"name": "Bowers-Setup-9.1.0.exe", "browser_download_url": "https://x/setup.exe"}]}).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("BOWERS_UPDATE_API", f"http://127.0.0.1:{srv.server_port}/latest")
    info = updater.check(force=True)
    assert info["newer"] and info["latest"] == "9.1.0" and info["installer"].endswith("setup.exe")
    assert updater.check()["newer"]  # cached for a day
    monkeypatch.setenv("BOWERS_NO_UPDATE_CHECK", "1")
    assert updater.check(force=True)["newer"] is False
