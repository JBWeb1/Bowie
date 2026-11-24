"""Keys you give Bowers, kept in your computer's own secure store, so nobody has to type `setx` or paste a key into a chat.

    Windows   Credential Manager      macOS   Keychain      Linux   Secret Service (GNOME Keyring, KWallet)

Where none of those exists (a bare server), keys go in ~/.docks/keys.env, readable only by you. Bowers loads them
into its own environment when it starts; a key already set in the environment wins. Values are never shown again
or sent anywhere except to the service the key belongs to.
"""

import json
import os
import re
from pathlib import Path

SERVICE = "Bowers"
KNOWN = {
    "ANTHROPIC_API_KEY": "Claude (Anthropic): powers the Bowers models",
    "OPENAI_API_KEY": "OpenAI: images, Codex and ChatGPT models",
    "LTX_API_KEY": "Bowers Motion video (LTX)",
    "ELEVENLABS_API_KEY": "ElevenLabs voices for Bowie",
    "GEMINI_API_KEY": "Google Gemini, through Bowers Router",
    "DEEPSEEK_API_KEY": "DeepSeek, through Bowers Router",
    "OPENROUTER_API_KEY": "OpenRouter, through Bowers Router",
}
NAME = re.compile(r"[A-Z][A-Z0-9_]{2,63}")


class VaultError(ValueError):
    pass


def _home() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks"))


def _index_path() -> Path:
    return _home() / "vault.json"


def _file_path() -> Path:
    return _home() / "keys.env"


def _keyring():
    """The OS secure store, or None when this computer has none (or BOWERS_VAULT=file)."""
    if os.environ.get("BOWERS_VAULT") == "file":
        return None
    try:
        import keyring
        from keyring.backends import fail
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 1) <= 0:
            return None
        return keyring
    except Exception:
        return None


def where() -> str:
    kr = _keyring()
    return type(kr.get_keyring()).__name__ if kr else f"a private file ({_file_path()})"


def _names() -> list[str]:
    try:
        return [n for n in json.loads(_index_path().read_text()) if NAME.fullmatch(n)]
    except (OSError, ValueError):
        return []


def _write_names(names: list[str]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(set(names))))


def _read_file() -> dict:
    out = {}
    try:
        for line in _file_path().read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and NAME.fullmatch(name):
                out[name] = value
    except OSError:
        pass
    return out


def _write_file(values: dict) -> None:
    path = _file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # only you can read it
    with os.fdopen(fd, "w") as f:
        f.write("".join(f"{k}={v}\n" for k, v in sorted(values.items())))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def check(name: str, value: str) -> str:
    if not NAME.fullmatch(name or ""):
        raise VaultError("a key name is capitals, digits and _, like ANTHROPIC_API_KEY")
    value = (value or "").strip()
    if not 8 <= len(value) <= 4096 or any(c in value for c in "\r\n\0"):
        raise VaultError("that doesn't look like a key: paste the whole key, on one line")
    return value


def save(name: str, value: str) -> None:
    value = check(name, value)
    kr = _keyring()
    if kr:
        kr.set_password(SERVICE, name, value)
    else:
        values = _read_file()
        values[name] = value
        _write_file(values)
    _write_names(_names() + [name])
    os.environ[name] = value  # usable straight away
    os.environ["_BOWERS_VAULT_LOADED_" + name] = "1"


def get(name: str) -> str | None:
    kr = _keyring()
    try:
        value = kr.get_password(SERVICE, name) if kr else None
    except Exception:
        value = None
    return value or _read_file().get(name)


def forget(name: str) -> None:
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass
    values = _read_file()
    if values.pop(name, None) is not None:
        _write_file(values)
    _write_names([n for n in _names() if n != name])
    if os.environ.get("_BOWERS_VAULT_LOADED_" + name):
        os.environ.pop(name, None)
        os.environ.pop("_BOWERS_VAULT_LOADED_" + name, None)


def load_into_env() -> list[str]:
    """Put saved keys into this process's environment (a key already set there wins). Returns the names loaded."""
    loaded = []
    for name in _names():
        if os.environ.get(name):
            continue
        value = get(name)
        if value:
            os.environ[name] = value
            os.environ["_BOWERS_VAULT_LOADED_" + name] = "1"
            loaded.append(name)
    return loaded


def status() -> list[dict]:
    """Every known key and any saved one: whether it's set and where from. Never the value."""
    saved = set(_names())
    out = []
    for name in list(KNOWN) + sorted(saved - set(KNOWN)):
        from_vault = name in saved
        in_env = bool(os.environ.get(name)) and not os.environ.get("_BOWERS_VAULT_LOADED_" + name)
        out.append({"name": name, "label": KNOWN.get(name, "Saved key"), "set": in_env or from_vault,
                    "source": "environment" if in_env else ("Bowers vault" if from_vault else "")})
    return out
