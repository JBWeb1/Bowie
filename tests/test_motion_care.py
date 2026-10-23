"""Bowers Motion (LTX-2.5 video) against a fake LTX API, and Bowers Care's system checks."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from docks import care, cli, motion
from tests.test_docks import FakeClient, msg, tool_use
from tests.test_extensions import Display, homes, text  # noqa: F401  (homes is an autouse fixture)

VIDEO = b"\x00\x00\x00\x18ftypmp42fake-video-bytes"


class FakeLTX:
    def __init__(self, polls=2, fail=False):
        self.requests, self.polls, self.fail = [], polls, fail
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, status=200):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                assert self.headers["authorization"] == "Bearer ltx-test"
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append((self.path, body))
                self._json({"id": "job1", "created_at": "now"})

            def do_GET(self):
                if self.path == "/files/video.mp4":
                    self.send_response(200)
                    self.send_header("content-length", str(len(VIDEO)))
                    self.end_headers()
                    self.wfile.write(VIDEO)
                    return
                outer.requests.append((self.path, None))
                if outer.fail:
                    return self._json({"id": "job1", "status": "failed", "error": {"message": "prompt rejected"}})
                outer.polls -= 1
                if outer.polls > 0:
                    return self._json({"id": "job1", "status": "processing"})
                self._json({"id": "job1", "status": "completed", "result": {"video_url": outer.url + "/files/video.mp4"}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def ltx(monkeypatch):
    fake = FakeLTX()
    monkeypatch.setenv("LTX_API_KEY", "ltx-test")
    monkeypatch.setenv("LTX_BASE_URL", fake.url)
    monkeypatch.setattr(motion.time, "sleep", lambda s: None)
    return fake


def test_text_and_image_to_video(tmp_path, ltx):
    seen = []
    made = motion.generate(tmp_path, "a fox in the snow, slow push in", seconds=8, on_status=seen.append)
    assert ltx.requests[0] == ("/v2/text-to-video", {"prompt": "a fox in the snow, slow push in", "model": "ltx-2-5-fast",
                                                    "duration": 8, "resolution": "1920x1080"})
    assert ltx.requests[1][0] == "/v2/text-to-video/job1" and "processing" in seen and "downloading" in seen
    assert (tmp_path / made["path"]).read_bytes() == VIDEO and made["path"].startswith("assets/videos/a-fox-in-the-snow")
    assert motion.gallery(tmp_path)[0]["label"] == "Bowers Motion Fast"
    (tmp_path / "hero.png").write_bytes(b"\x89PNG fake")
    ltx.polls = 1
    made = motion.generate(tmp_path, "it starts to rain", image="hero.png", pro=True, seconds=6, aspect="9:16",
                           resolution="720p", sound=False, path="public/rain.mp4")
    path, body = ltx.requests[-2] if ltx.requests[-1][1] is None else ltx.requests[-1]
    assert path == "/v2/image-to-video" and body["image_uri"].startswith("data:image/png;base64,")
    assert body["model"] == "ltx-2-5-pro" and body["resolution"] == "720x1280" and body["generate_audio"] is False
    assert made["path"] == "public/rain.mp4" and len(motion.gallery(tmp_path)) == 2


def test_options_are_checked_before_spending_money(tmp_path, ltx):
    for kwargs, error in [({"pro": True, "resolution": "4k"}, "720p, 1080p"), ({"pro": True, "seconds": None}, "needs a length"),
                          ({"seconds": 7}, "6, 8, 10, 12"), ({"seconds": 16, "resolution": "4k"}, "longer than 10"),
                          ({"aspect": "4:3"}, "aspect")]:
        with pytest.raises(motion.MotionError, match=error):
            motion.generate(tmp_path, "x", **kwargs)
    assert ltx.requests == []
    motion.generate(tmp_path, "let the model choose", seconds=None)
    assert ltx.requests[0][1]["duration"] is None


def test_failed_job_and_missing_key(tmp_path, ltx, monkeypatch):
    ltx.fail = True
    with pytest.raises(motion.MotionError, match="prompt rejected"):
        motion.generate(tmp_path, "something")
    monkeypatch.delenv("LTX_API_KEY")
    with pytest.raises(motion.MotionError, match="LTX_API_KEY"):
        motion.generate(tmp_path, "something")


def test_agent_makes_a_video_and_cli(tmp_path, ltx, capsys):
    from docks.agent import Agent
    client = FakeClient([msg("tool_use", tool_use("v1", "generate_video", prompt="logo reveal", seconds=6)),
                         msg("end_turn", text("Made it."))])
    display = Display(confirm="yes")
    agent = Agent(root=tmp_path, client=client, display=display)
    assert "generate_video" in [t["name"] for t in agent.tools] and agent._mutating("generate_video")
    agent.run("make a logo video")
    assert "confirm" in display.names()  # it costs money, so it asks
    result = client.requests[1]["messages"][-1]["content"][0]["content"]
    assert "Saved assets/videos/logo-reveal" in result
    assert cli.main(["video", "waves at dusk", "-C", str(tmp_path), "--seconds", "10", "--aspect", "9:16"]) == 0
    assert "saved assets/videos/waves-at-dusk" in capsys.readouterr().out


def test_web_video_job(tmp_path, ltx):
    from tests.test_web import call, start, wait_for
    session, url = start(tmp_path, [])
    info = call(url + "/api/motion")
    assert info["available"] and info["limits"]["ltx-2-5-pro"]["durations"] == [6, 8, 10]
    job = call(url + "/api/motion/generate", {"prompt": "city at night", "seconds": 8, "image": "data:image/png;base64,iVBORw0K"})
    wait_for(lambda: session.motion_jobs[job["id"]]["status"] in ("done", "error"))
    done = session.motion_jobs[job["id"]]
    assert done["status"] == "done" and (tmp_path / done["video"]["path"]).is_file()
    assert done["video"]["image"].startswith("assets/uploads/motion-")
    assert any(e.get("type") == "motion" and e["status"] == "done" for e in session.history)
    assert len(call(url + "/api/motion")["videos"]) == 1


def test_system_check_is_read_only_and_cross_platform(tmp_path, monkeypatch):
    out = care.check(["overview", "processes"])
    assert "## overview" in out and "Memory:" in out and "## processes" in out
    snap = care.snapshot()
    assert snap["os"] and snap["disks"] and isinstance(snap["warnings"], list)
    monkeypatch.setattr(care, "SYSTEM", "Windows")
    argv = care.shell_argv("Get-Process")
    assert argv[-1] == "Get-Process" and "-NoProfile" in argv and care.shell_name() == "PowerShell"
    from docks.agent import Agent
    agent = Agent(root=tmp_path, client=FakeClient([]), display=Display())
    assert not agent._mutating("system_check") and "system_check" in [t["name"] for t in agent.tools]
    assert "Computer care" in agent.system
