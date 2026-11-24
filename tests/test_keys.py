"""The key vault (keys kept in the OS secure store or a private file) and Bowers access keys."""

import json
import os
import stat
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from docks import accesskeys, vault
from docks.router.config import load
from docks.router.engine import Engine
from docks.router.server import make_handler


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKS_HOME", str(tmp_path))
    monkeypatch.setenv("BOWERS_VAULT", "file")  # no OS store in tests
    for name in vault.KNOWN:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv("_BOWERS_VAULT_LOADED_" + name, raising=False)
    return tmp_path


def test_vault_saves_loads_and_never_shows_values(home, monkeypatch):
    vault.save("ANTHROPIC_API_KEY", "  sk-ant-test-1234567890  ")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test-1234567890"
    assert next(k for k in vault.status() if k["name"] == "ANTHROPIC_API_KEY")["source"] == "Bowers vault"  # removable in Settings
    keys_file = home / "keys.env"
    assert stat.S_IMODE(keys_file.stat().st_mode) == 0o600  # only you can read it
    assert "sk-ant" not in (home / "vault.json").read_text()  # the index holds names only
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert vault.load_into_env() == ["ANTHROPIC_API_KEY"] and os.environ["ANTHROPIC_API_KEY"].startswith("sk-ant")
    row = next(k for k in vault.status() if k["name"] == "ANTHROPIC_API_KEY")
    assert row["set"] and row["source"] == "Bowers vault" and "sk-ant" not in json.dumps(vault.status())
    monkeypatch.setenv("OPENAI_API_KEY", "from-the-environment")
    assert vault.load_into_env() == [] and os.environ["OPENAI_API_KEY"] == "from-the-environment"  # the environment wins
    vault.forget("ANTHROPIC_API_KEY")
    assert "ANTHROPIC_API_KEY" not in os.environ and vault.get("ANTHROPIC_API_KEY") is None
    for bad in (("lower_case", "a-long-enough-key"), ("GOOD_NAME", "short"), ("GOOD_NAME", "two\nlines-of-key")):
        with pytest.raises(vault.VaultError):
            vault.save(*bad)


def test_access_keys_open_the_router_and_can_be_revoked(home):
    key = accesskeys.create("My phone")
    assert key.startswith("bwk_") and len(key) > 40
    stored = (home / "access-keys.json").read_text()
    assert key not in stored and stat.S_IMODE((home / "access-keys.json").stat().st_mode) == 0o600
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Engine(load(home / "none.json")), None, access_keys=True))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def call(token):
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/v1/messages", method="POST",
                                     data=json.dumps({"model": "nothing-here", "max_tokens": 5, "messages": []}).encode(),
                                     headers={"content-type": "application/json", "x-api-key": token})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code

    assert call("bwk_not-a-real-key") == 401
    assert call(key) != 401  # let in (it then finds no model, which is a different error)
    assert accesskeys.listing()[0]["last_used"]
    assert accesskeys.revoke(accesskeys.listing()[0]["id"]) and call(key) == 401
    server.shutdown()
