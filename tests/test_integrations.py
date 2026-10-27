"""Integrations: installing plugins, skill packs, apps, templates and tools from the catalog (with local repos)."""

import json
import subprocess
import sys

import pytest

from docks import integrations as I
from docks import plugins
from tests.test_extensions import homes  # noqa: F401  (homes is an autouse fixture)


def git_repo(path, files):
    path.mkdir(parents=True)
    for name, text in files.items():
        f = path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=path, check=True)
    return path


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("BOWERS_APPS", str(tmp_path / "apps"))
    monkeypatch.setattr(I, "E", [])
    return tmp_path


def entry(**kw):
    I.add(**kw)
    return I.E[-1]


def test_plugin_hooks_stay_off_until_approved(catalog):
    repo = git_repo(catalog / "pack", {
        ".claude-plugin/plugin.json": json.dumps({"name": "pack"}),
        "skills/tidy/SKILL.md": "---\nname: tidy\ndescription: Tidy code\n---\nTidy it.",
        "hooks/hooks.json": json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}),
    })
    entry(id="pack", name="Pack", kind="plugin", repo=str(repo))
    I.install("pack", log=lambda t: None)
    assert I.status(I.find("pack")) == "installed"
    ext = plugins.Extensions.load(catalog)
    assert "tidy" in ext.skills and not [h for h in ext.hooks if h.event == "SessionStart"]
    assert I.held_hooks("pack")[0]["command"] == "echo hi"
    I.enable_hooks("pack")
    assert [h for h in plugins.Extensions.load(catalog).hooks if h.event == "SessionStart"]
    assert I.remove("pack") and I.status(I.find("pack")) == "not-installed"


def test_skill_repos_marketplace_entries_and_agent_libraries(catalog):
    skills = git_repo(catalog / "skills-only", {"one/SKILL.md": "---\nname: one\ndescription: x\n---\n", "deep/two/SKILL.md": "---\nname: two\ndescription: y\n---\n",
                                               "node_modules/bad/SKILL.md": "---\nname: bad\n---\n"})
    market = git_repo(catalog / "market", {".claude-plugin/marketplace.json": json.dumps({"plugins": [{"name": "styles", "source": "./skills", "skills": ["./look"], "description": "d"}]}),
                                          "skills/look/SKILL.md": "---\nname: look\ndescription: z\n---\n"})
    agents = git_repo(catalog / "agency", {"engineering/frontend.md": "---\nname: frontend-dev\ndescription: Builds UIs\n---\nYou build UIs.",
                                          "README.md": "# The agency\n"})
    for id_, repo in (("skills-only", skills), ("market", market), ("agency", agents)):
        entry(id=id_, name=id_, kind="plugin", repo=str(repo))
        I.install(id_, log=lambda t: None)
    ext = plugins.Extensions.load(catalog)
    assert {"one", "two", "look"} <= set(ext.skills) and "bad" not in ext.skills
    assert "frontend-dev" in ext.agents and ext.agents["frontend-dev"].source.startswith("plugin:")


def test_app_install_steps_status_and_run(catalog):
    repo = git_repo(catalog / "app-src", {".env.example": "KEY=\n", "serve.py": "print('serving')\n"})
    py = f'"{sys.executable}"'
    entry(id="demo-app", name="Demo App", kind="app", url=str(repo), needs=["git"],
          steps=[{"env": ".env.example"}, {"write": ".env.local", "text": "API=https://example.test\n"},
                 f"{py} -c \"open('built.txt','w').write('ok')\""], run=f"{py} serve.py", open_url="http://localhost:9")
    e = I.find("demo-app")
    lines = []
    I.install("demo-app", log=lines.append)
    where = I.app_dir(e)
    assert (where / ".env").is_file() and (where / "built.txt").read_text() == "ok" and I.status(e) == "installed"
    assert (where / ".env.local").read_text() == "API=https://example.test\n" and any("write .env.local" in x for x in I.plan(e))
    assert any(line.startswith("$ ") for line in lines)
    info = I.run("demo-app")
    I.RUNNING["demo-app"].wait(timeout=20)
    assert "serving" in open(info["log"]).read()
    assert "Demo App at" in I.system_note() and "start:" in I.system_note()
    I.remove("demo-app")
    assert not where.exists()


def test_templates_tools_prereqs_and_failures(catalog, monkeypatch):
    from docks.web import library
    monkeypatch.setattr(library, "projects_home", lambda: catalog / "projects")
    repo = git_repo(catalog / "tpl", {"package.json": "{}"})
    entry(id="tpl", name="Starter", kind="template", url=str(repo), needs=["git"], steps=[])
    I.install("tpl", log=lambda t: None)
    assert (catalog / "projects" / "Starter" / "package.json").is_file() and I.status(I.find("tpl")) == "installed"
    entry(id="needs-docker", name="Needs Docker", kind="app", url=str(repo), needs=["docker"])
    monkeypatch.setattr(I, "_which", lambda c: c != "docker" and bool(__import__("shutil").which(c)))
    with pytest.raises(I.InstallError, match="needs docker first"):
        I.install("needs-docker", log=lambda t: None)
    entry(id="broken", name="Broken", kind="tool", steps=[f'"{sys.executable}" -c "import sys; sys.exit(3)"'])
    with pytest.raises(I.InstallError, match="exit 3"):
        I.install("broken", log=lambda t: None)
    entry(id="fine", name="Fine", kind="tool", steps=[f'"{sys.executable}" -c "print(1)"'])
    I.install("fine", log=lambda t: None)
    assert I.status(I.find("fine")) == "installed"
    called = []
    monkeypatch.setattr(I, "_test_hook", lambda log: called.append(log("fetched")) , raising=False)
    entry(id="model", name="Model", kind="tool", check="call:docks.integrations:_test_ready",
          steps=[{"py": "json-already-there", "module": "json"}, {"call": "docks.integrations:_test_hook", "say": "fetch the model"}])
    monkeypatch.setattr(I, "_test_ready", lambda: bool(called), raising=False)
    assert I.status(I.find("model")) == "not-installed" and "fetch the model" in I.plan(I.find("model"))
    lines = []
    I.install("model", log=lines.append)
    assert called and "json-already-there is already available" in lines and I.status(I.find("model")) == "installed"
    monkeypatch.setattr(I, "_test_hook", lambda log: 1 / 0, raising=False)
    with pytest.raises(I.InstallError, match="couldn't fetch the model"):
        I.install("model", log=lambda t: None)


def test_real_catalog_is_consistent():
    import importlib
    real = importlib.reload(I)
    ids = [e["id"] for e in real.E]
    assert len(ids) == len(set(ids)) and len(ids) > 60
    from docks.plugins import Extensions
    from pathlib import Path
    agents = Extensions.load(Path("/nonexistent")).agents
    for e in real.E:
        assert e["kind"] in ("plugin", "collection", "tool", "system", "app", "template", "library", "link"), e["id"]
        assert not e["agent"] or e["agent"] in agents, e["id"]
        assert e["url"].startswith(("https://", "/")), e["id"]
        assert all(n in real.PREREQS for n in e["needs"]), e["id"]
        if e["kind"] not in ("link", "plugin", "collection"):
            assert e["steps"] or e["kind"] == "template", e["id"]
    assert "system_prompts_leaks" in real.NOT_INSTALLED


def test_web_install_reports_progress(catalog, tmp_path):
    from tests.test_web import call, start, wait_for
    repo = git_repo(catalog / "webpack", {".claude-plugin/plugin.json": json.dumps({"name": "webpack"}),
                                          "agents/helper.md": "---\nname: web-helper\ndescription: Helps\n---\nHelp."})
    entry(id="webpack", name="Web Pack", kind="plugin", repo=str(repo))
    session, url = start(tmp_path / "proj", [])
    assert call(url + "/api/integrations")["items"][0]["status"] == "not-installed"
    call(url + "/api/integrations/install", {"id": "webpack"})
    wait_for(lambda: any(e.get("type") == "integration" and e.get("done") for e in session.history), timeout=30)
    done = [e for e in session.history if e.get("type") == "integration" and e.get("done")][0]
    assert done["error"] is None and "web-helper" in session.agent.ext.agents  # loaded without a restart
    assert "web-helper" in session.agent.system
