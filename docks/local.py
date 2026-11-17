"""Bowers Local: AI that runs on this computer, free and private, with no API key.

Bowers talks to a local model server through Bowers Router, the same way it reaches OpenAI:

    Ollama      http://localhost:11434   (OLLAMA_HOST to change it)   https://ollama.com
    LM Studio   http://localhost:1234    (LMSTUDIO_URL to change it)  https://lmstudio.ai

`bowers local setup` downloads a coding model with Ollama and makes `bowers-coder` from it: the same model with a
32k context window, so Bowers' instructions, tools and your conversation fit (Ollama's default is much smaller and
it drops what doesn't fit without saying so). Pick a model yourself with BOWERS_LOCAL_MODEL, e.g. "qwen3-coder:30b"
or "lmstudio/qwen2.5-coder-7b-instruct".
"""

import json
import os
import shutil
import subprocess
import time
import urllib.request

CONTEXT = 32768
OWN = "bowers-coder"
# Ollama models in the order Bowers prefers them: good at code and at calling tools
PREFER = ("bowers-coder", "qwen3-coder", "qwen2.5-coder", "devstral", "gpt-oss", "qwen3", "llama3.1", "mistral-small",
          "llama3.2", "gemma3")
_cache = {"at": 0.0, "found": None}


def ollama_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip() or "http://localhost:11434"
    if not host.startswith("http"):
        host = "http://" + host
    return host.rstrip("/").replace("://0.0.0.0", "://localhost")


def lmstudio_url() -> str:
    return (os.environ.get("LMSTUDIO_URL") or "http://localhost:1234").rstrip("/")


def _get_json(url: str, timeout: float = 1.5):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"accept": "application/json"}), timeout=timeout) as r:
        return json.loads(r.read())


def ollama_models() -> list[str] | None:
    """Models pulled into Ollama, or None when Ollama isn't running."""
    try:
        return [m["name"] for m in _get_json(ollama_url() + "/api/tags").get("models", [])]
    except Exception:
        return None


def lmstudio_models() -> list[str] | None:
    try:
        return [m["id"] for m in _get_json(lmstudio_url() + "/v1/models").get("data", []) if "embed" not in m["id"]]
    except Exception:
        return None


def best(names: list[str]) -> str | None:
    for family in PREFER:
        for n in names:
            if n.split(":")[0].split("/")[-1] == family:
                return n
    return names[0] if names else None


def detect(fresh: bool = False) -> dict:
    """What's running here: {"target": "ollama/bowers-coder:latest" or None, "ollama": [...], "lmstudio": [...]}."""
    if not fresh and _cache["found"] is not None and time.monotonic() - _cache["at"] < 20:
        return _cache["found"]
    ol, lm = ollama_models(), lmstudio_models()
    pick = os.environ.get("BOWERS_LOCAL_MODEL", "").strip()
    target = None
    if pick:
        target = pick if pick.startswith(("ollama/", "lmstudio/")) else f"ollama/{pick}"
    elif ol:
        target = f"ollama/{best(ol)}"
    elif lm:
        target = f"lmstudio/{lm[0]}"
    found = {"target": target, "ollama": ol, "lmstudio": lm, "installed": bool(ollama_exe())}
    _cache.update(at=time.monotonic(), found=found)
    return found


def ollama_exe() -> str | None:
    """The ollama program, also where its installer puts it before a new window picks up PATH (Windows, Mac)."""
    found = shutil.which("ollama")
    if found:
        return found
    for path in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
                 "/Applications/Ollama.app/Contents/Resources/ollama", "/usr/local/bin/ollama"):
        if os.path.isfile(path):
            return path
    return None


def ready() -> bool:
    return problem() is None


def problem() -> str | None:
    """Why Bowers Local can't run right now, or None if it can."""
    d = detect()
    if d["target"]:
        return None
    if d["ollama"] == []:
        return "Ollama is running but has no models yet: run `bowers local setup` (downloads a free coding model, about 5 GB)"
    if d["installed"]:
        return "Ollama is installed but not running: open the Ollama app (or run `ollama serve`), then try again"
    return ("Ollama isn't installed (a free program that runs AI models on your computer): run `bowers local setup` "
            "to install it and a free model, or get it from https://ollama.com")


def recommended(ram_gb: float | None = None) -> str:
    """The coding model that fits this computer's memory."""
    ram_gb = ram_gb if ram_gb is not None else _ram_gb()
    if ram_gb and ram_gb >= 30:
        return "qwen2.5-coder:14b"
    if ram_gb and ram_gb < 12:
        return "qwen2.5-coder:3b"
    return "qwen2.5-coder:7b"


def _ram_gb() -> float | None:
    try:
        import psutil
        return psutil.virtual_memory().total / 2**30
    except Exception:
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return None


def modelfile(base: str) -> str:
    return f"FROM {base}\nPARAMETER num_ctx {CONTEXT}\n"


def setup(log=print, base: str | None = None) -> str:
    """Download a coding model with Ollama and make bowers-coder from it. Returns the model's router target."""
    exe = ollama_exe()
    if not exe:
        raise RuntimeError("install Ollama first: https://ollama.com/download "
                           "(Windows: winget install Ollama.Ollama; Mac: brew install ollama; "
                           "Linux: curl -fsSL https://ollama.com/install.sh | sh), then run this again")
    if ollama_models() is None:
        log("starting Ollama…")
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(30):
            time.sleep(1)
            if ollama_models() is not None:
                break
        else:
            raise RuntimeError("Ollama didn't start: open the Ollama app, then run this again")
    base = base or recommended()
    log(f"downloading {base} (this can take a while the first time)…")
    pulled = subprocess.run([exe, "pull", base], capture_output=True, text=True, errors="replace")
    if pulled.returncode:
        raise RuntimeError(f"couldn't download {base}: {(pulled.stderr or pulled.stdout).strip()[-300:]}")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "Modelfile")
        with open(path, "w") as f:
            f.write(modelfile(base))
        made = subprocess.run([exe, "create", OWN, "-f", path], capture_output=True, text=True, errors="replace")
        if made.returncode:
            raise RuntimeError(f"couldn't make {OWN}: {(made.stderr or made.stdout).strip()[-300:]}")
    log(f"made {OWN}: {base} with a {CONTEXT:,} token context")
    _cache["found"] = None
    return f"ollama/{OWN}:latest"


def status_lines() -> list[str]:
    d = detect(fresh=True)
    lines = [f"Ollama: {'running, ' + str(len(d['ollama'])) + ' model(s)' if d['ollama'] is not None else ('installed, not running' if d['installed'] else 'not installed')} ({ollama_url()})",
             f"LM Studio: {'running, ' + str(len(d['lmstudio'])) + ' model(s)' if d['lmstudio'] is not None else 'not running'} ({lmstudio_url()})"]
    lines.append(f"Bowers Local uses: {d['target']}" if d["target"] else f"Bowers Local: {problem()}")
    return lines
