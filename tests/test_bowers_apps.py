"""Knowledge graph, Labs (math, arena, emotes), Bowie's voice, the terminal, app install, voice mode, Aether learning."""

import base64
import io
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS

import pytest

from docks import graph, labs, voice
from tests.test_docks import FakeClient, msg, tool_use
from tests.test_extensions import Display, homes, text  # noqa: F401  (homes is an autouse fixture)
from tests.test_web import call, start, wait_for


def png(color=(255, 107, 44, 255), size=(40, 30)) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_graph_maps_projects_and_code(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("from . import b\nfrom .c import thing\n")
    (tmp_path / "pkg" / "b.py").write_text("import pkg.c\n")
    (tmp_path / "pkg" / "c.py").write_text("thing = 1\n")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.js").write_text("import { x } from './util.js';\nconst y = require('./lib')\n")
    (tmp_path / "web" / "util.js").write_text("export const x = 1\n")
    (tmp_path / "web" / "lib.js").write_text("module.exports = 2\n")
    (tmp_path / "README.md").write_text("# hi\n")
    edges = {tuple(e) for e in graph.code_map(tmp_path)["edges"]}
    assert {("pkg/a.py", "pkg/b.py"), ("pkg/a.py", "pkg/c.py"), ("pkg/b.py", "pkg/c.py"),
            ("web/app.js", "web/util.js"), ("web/app.js", "web/lib.js")} <= edges
    data = graph.overview(tmp_path, None, "Josh")
    kinds = {n["kind"]: n for n in data["nodes"]}
    assert kinds["you"]["title"] == "Josh" and kinds["files"]["counts"]["code"] == 7
    assert kinds["knowledge"]["sub"] == "1 document" and data["stats"]["files"] == 8


def test_math_lab():
    pytest.importorskip("sympy")
    assert labs.solve_math("x^2 - 5x + 6 = 0")["text"] == "x = 2, 3"
    assert "cos(x)" in labs.solve_math("sin(x)", "diff")["text"]
    assert labs.solve_math("x^2-1", "factor")["text"] == "(x - 1)*(x + 1)"
    assert labs.solve_math("x^2 - 5x + 6 = 0", "factor")["text"] in ("(x - 3)*(x - 2)", "(x - 2)*(x - 3)")  # an equation works for every op
    framed = labs.solve_math("x^2 - 5x + 6", "plot")["points"]
    assert framed[0][0] < 2 < 3 < framed[-1][0] < 10  # the plot frames the roots
    pts = labs.solve_math("1/x", "plot")["points"]
    assert len(pts) == 401 and any(p[1] is None for p in pts)  # the gap at x = 0
    with pytest.raises(labs.LabError):
        labs.solve_math("__import__('os').system('ls')", "simplify")


def test_arena_battle_vote_and_board(tmp_path):
    asked = []

    def client_for(engine):
        def create(**kw):
            asked.append(kw["model"])
            return NS(content=[NS(type="text", text=f"answer from {kw['model']}")])
        return NS(messages=NS(create=create))
    out = labs.battle(client_for, "syntra", "solace", "Explain recursion")
    assert "answer from claude-opus" in out["a"]["text"] and "answer from claude-sonnet" in out["b"]["text"]
    assert labs.vote(out["id"], "a") == {"a": "syntra", "b": "solace"}
    board = labs.leaderboard()
    assert board[0] == {"model": "syntra", "wins": 1, "losses": 0, "ties": 0}
    with pytest.raises(labs.LabError):
        labs.battle(client_for, "syntra", "syntra", "x")


def test_emotes_and_uploads(tmp_path):
    pytest.importorskip("PIL")
    made = labs.make_emotes(tmp_path, png(), "my bowie.png")
    from PIL import Image
    sizes = {(s["platform"], s["size"]) for s in made["sizes"]}
    assert ("Twitch", 28) in sizes and ("Discord emoji", 128) in sizes and ("Telegram sticker", 512) in sizes
    first = Image.open(tmp_path / made["sizes"][0]["path"])
    assert first.size == (28, 28) and made["folder"].startswith("assets/emotes/my-bowie-")
    path = labs.save_upload(tmp_path, png(), "rooms")
    assert path.startswith("assets/rooms/") and (tmp_path / path).is_file()
    with pytest.raises(labs.LabError):
        labs.save_upload(tmp_path, "data:text/html;base64,PGI+", "x")


class FakeEleven:
    def __init__(self):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                assert self.headers["xi-api-key"] == "el-test"
                data = json.dumps({"voices": [{"voice_id": "bowie123", "name": "Bowie", "category": "generated"}]}).encode()
                self.send_response(200)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append((self.path, body))
                self.send_response(200)
                self.send_header("content-type", "audio/mpeg")
                self.end_headers()
                self.wfile.write(b"ID3fake-mp3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def test_bowies_voice(monkeypatch):
    fake = FakeEleven()
    assert not voice.available()
    with pytest.raises(voice.VoiceError, match="ELEVENLABS_API_KEY"):
        voice.speak("hi", "bowie123")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    monkeypatch.setenv("ELEVENLABS_BASE_URL", fake.url)
    assert voice.voices()[0]["id"] == "bowie123"
    assert voice.speak("Hello there!", "bowie123") == b"ID3fake-mp3"
    path, body = fake.requests[0]
    assert path.startswith("/text-to-speech/bowie123") and body["text"] == "Hello there!" and body["model_id"]
    with pytest.raises(voice.VoiceError):
        voice.speak("hi", "../etc")


def test_web_routes_for_the_new_pages(tmp_path, monkeypatch):
    session, url = start(tmp_path, [])
    (tmp_path / "main.py").write_text("import helper\n")
    (tmp_path / "helper.py").write_text("")
    g = call(url + "/api/graph")
    assert g["center"]["title"] == "Bowie" and ["main.py", "helper.py"] in g["code"]["edges"]
    assert "hello" in call(url + "/api/terminal", {"command": "echo hello"})["output"]
    assert call(url + "/api/care")["os"]
    v = call(url + "/api/voice")
    assert v["available"] is False and v["voices"] == [] and v["local"] is False and "stt" in v
    made = call(url + "/api/emotes", {"image": png(), "name": "x.png"})
    assert len(made["sizes"]) == 8
    # installing as an app: the manifest and service worker are public, assets come from subfolders
    with urllib.request.urlopen(url + "/manifest.webmanifest") as r:
        assert json.load(r)["display"] == "standalone"
    with urllib.request.urlopen(url + "/sw.js") as r:
        assert b"fetch" in r.read()
    with urllib.request.urlopen(url + "/assets/bowie/happy.webp") as r:
        assert r.headers["content-type"] == "image/webp"
    for bad in ("/assets/../server.py", "/assets/a/b/c.webp"):
        try:
            urllib.request.urlopen(url + bad)
            raise AssertionError(bad)
        except urllib.error.HTTPError as e:
            assert e.code == 404


def test_app_token_and_install_shortcuts(tmp_path, monkeypatch):
    from docks import cli
    from docks.web import server
    monkeypatch.setenv("HOME", str(tmp_path))
    first = server.app_token()
    assert first == server.app_token() and len(first) >= 20
    monkeypatch.setattr(cli.sys, "platform", "linux")
    (tmp_path / "Desktop").mkdir()
    assert cli.main(["install-app"]) == 0
    entry = (tmp_path / ".local/share/applications/bowers.desktop").read_text()
    assert "-m docks app" in entry and "app-512.png" in entry and (tmp_path / "Desktop/bowers.desktop").is_file()
    assert cli.main(["install-app", "--uninstall"]) == 0
    assert not (tmp_path / ".local/share/applications/bowers.desktop").exists()


def test_voice_mode_note_and_aether_learning(tmp_path):
    from docks.agent import Agent
    verdict = json.dumps({"summary": "One preference.", "findings": [
        {"kind": "remember", "text": "Prefers TypeScript", "action": "Use TypeScript for new code."}]})

    class Client(FakeClient):
        def __init__(self, responses):
            super().__init__(responses)
            self.messages = NS(create=lambda **kw: NS(content=[NS(type="text", text=verdict)]))
    client = Client([msg("tool_use", tool_use("w1", "write_file", path="a.ts", content="x")), msg("end_turn", text("Done."))])
    agent = Agent(root=tmp_path, client=client, model="aether", display=Display(confirm="yes"))
    agent.voice_turn = True
    agent.run("write a.ts, I like TypeScript")
    sent = client.requests[0]["messages"][0]["content"]
    assert any("<voice-mode>" in b.get("text", "") for b in sent if isinstance(b, dict))
    from docks import instructions
    notes = "".join(f.read_text() for f in instructions.user_files() if f.is_file())
    assert "Use TypeScript for new code." in notes and agent.observations == []
    assert "Use TypeScript for new code." in agent.system  # it knows from the next turn on


def test_builtin_agent_team(tmp_path):
    from docks.agent import Agent
    from docks.plugins import Extensions
    ext = Extensions.load(tmp_path)
    for name in ("codebase-cartographer", "video-producer", "trading-analyst", "reverse-engineer", "ui-designer", "learning-guide"):
        assert name in ext.agents and ext.agents[name].source == "builtin" and len(ext.agents[name].prompt) > 200
    assert "never place trades" in ext.agents["trading-analyst"].prompt
    assert "permission" in ext.agents["reverse-engineer"].prompt
    client = FakeClient([
        msg("tool_use", tool_use("d1", "delegate", description="Map the code", prompt="map it", agent="codebase-cartographer")),
        msg("end_turn", text("The map.")),   # the helper
        msg("end_turn", text("Here it is.")),
    ])
    agent = Agent(root=tmp_path, client=client, display=Display(confirm="yes"))
    assert "codebase-cartographer" in agent.system
    agent.run("explain this repo")
    helper_system = client.requests[1]["system"]
    assert "You map codebases" in (helper_system if isinstance(helper_system, str) else json.dumps(helper_system))


def test_local_voice_and_transcription(tmp_path, monkeypatch):
    """Kokoro speaks on this computer; faster-whisper turns a recording into text (both faked: no model downloads)."""
    import sys
    import types
    import numpy as np
    from docks import integrations
    calls = {}

    class Kokoro:
        def __init__(self, model, voices):
            calls["files"] = (model, voices)

        def create(self, text, voice, speed, lang):
            calls["said"] = (text, voice, lang)
            return np.zeros(2400, np.float32), 24000

    class WhisperModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, audio, vad_filter):
            assert audio.read() == b"RIFFfake"
            return [NS(text=" hey bowie"), NS(text=" what's next? ")], None
    monkeypatch.setitem(sys.modules, "kokoro_onnx", types.SimpleNamespace(Kokoro=Kokoro, __spec__=NS(name="kokoro_onnx")))
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModel))
    monkeypatch.setattr(voice, "_kokoro", None)
    monkeypatch.setattr(voice, "_whisper", None)
    import importlib.util
    real_find = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: NS(name=n) if n in ("kokoro_onnx", "faster_whisper") else real_find(n, *a))
    kdir = tmp_path / "kokoro"
    monkeypatch.setenv("BOWERS_KOKORO_DIR", str(kdir))
    assert not voice.local_available() and integrations.status(integrations.find("kokoro-voice")) == "not-installed"
    kdir.mkdir()
    (kdir / "kokoro-v1.0.int8.onnx").write_bytes(b"x")
    (kdir / "voices-v1.0.bin").write_bytes(b"x")
    assert voice.local_available() and integrations.status(integrations.find("kokoro-voice")) == "installed"
    session, url = start(tmp_path / "proj", [])
    info = call(url + "/api/voice")
    assert info["local"] and info["stt"] and info["local_voices"][0]["id"] == "am_puck"
    req = urllib.request.Request(url + "/api/voice/speak", data=json.dumps({"text": "Hello!", "engine": "local", "voice": "bm_george"}).encode(),
                                 headers={"x-docks-token": "tok", "content-type": "application/json"})
    with urllib.request.urlopen(req) as r:
        assert r.headers["content-type"] == "audio/wav"
        audio = r.read()
    assert audio[:4] == b"RIFF" and calls["said"] == ("Hello!", "bm_george", "en-gb")
    data = "data:audio/wav;base64," + base64.b64encode(b"RIFFfake").decode()
    assert call(url + "/api/voice/transcribe", {"audio": data})["text"] == "hey bowie what's next?"
    with pytest.raises(voice.VoiceError):
        voice.transcribe("data:text/html;base64,PGI+")
    with pytest.raises(voice.VoiceError):
        voice.speak_local("hi", "../x")
