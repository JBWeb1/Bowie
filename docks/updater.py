"""Updates: Bowers checks its GitHub releases (at most once a day) and offers the newer version.

The installed Windows app downloads the new Bowers-Setup.exe and runs it; a pip install updates with pip.
Set BOWERS_NO_UPDATE_CHECK=1 to turn checks off.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

REPO = os.environ.get("BOWERS_UPDATE_REPO", "JBWeb1/Bowie")


def api_url() -> str:
    return os.environ.get("BOWERS_UPDATE_API", f"https://api.github.com/repos/{REPO}/releases/latest")


def _cache() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "update.json"


def _ver(text: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3]) or (0,)


def installed_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def check(force: bool = False) -> dict:
    """{current, latest, newer, notes, url, installer}. Cached for a day; never raises."""
    info = {"current": __version__, "latest": None, "newer": False}
    if os.environ.get("BOWERS_NO_UPDATE_CHECK"):
        return info
    try:
        cached = json.loads(_cache().read_text())
        if not force and time.time() - cached.get("checked", 0) < 86400:
            return {**cached, "current": __version__, "newer": _ver(cached.get("latest") or "0") > _ver(__version__)}
    except (OSError, json.JSONDecodeError):
        pass
    try:
        req = urllib.request.Request(api_url(), headers={"Accept": "application/vnd.github+json", "User-Agent": "bowers-updater"})
        with urllib.request.urlopen(req, timeout=10) as r:
            rel = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # no release published yet
            return info
        return {**info, "error": f"couldn't check for updates (GitHub said {e.code})"}
    except Exception as e:  # offline
        return {**info, "error": f"couldn't check for updates ({type(e).__name__})"}
    setup = next((a["browser_download_url"] for a in rel.get("assets", []) if re.match(r"Bowers-Setup.*\.exe$", a.get("name", ""))), None)
    data = {"latest": rel.get("tag_name", "").lstrip("v"), "notes": (rel.get("body") or "")[:4000], "url": rel.get("html_url"),
            "installer": setup, "checked": time.time()}
    try:
        _cache().parent.mkdir(parents=True, exist_ok=True)
        _cache().write_text(json.dumps(data))
    except OSError:
        pass
    return {**data, "current": __version__, "newer": _ver(data["latest"] or "0") > _ver(__version__)}


def apply(log=print) -> str:
    """Install the newest version. Returns what happened."""
    info = check(force=True)
    if not info.get("newer"):
        return f"Bowers {__version__} is the newest version"
    if installed_app() and sys.platform == "win32":
        if not info.get("installer"):
            raise RuntimeError("the newest release has no Windows installer yet")
        target = Path(tempfile.gettempdir()) / f"Bowers-Setup-{info['latest']}.exe"
        log(f"downloading Bowers {info['latest']}…")
        urllib.request.urlretrieve(info["installer"], target)
        # The installer closes this app, updates it and starts it again.
        subprocess.Popen([str(target), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], close_fds=True)
        return f"installing Bowers {info['latest']}; it restarts by itself"
    src = f"git+https://github.com/{REPO}@v{info['latest']}"
    log(f"updating with pip from {src}…")
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", f"docks[browser,labs] @ {src}"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "pip failed")
    return f"updated to Bowers {info['latest']}; restart Bowers to use it"
