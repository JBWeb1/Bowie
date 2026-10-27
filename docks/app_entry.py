"""The entry point of the installed Windows app (Bowers.exe): opens Bowers in its own window.

bowers-cli.exe (next to it) is the full command line: bowers-cli.exe doctor, bowers-cli.exe integrations, …
"""

import os
import subprocess
import sys


def _hide_console_windows() -> None:
    """A windowed app would flash a console for every command it runs; start them hidden instead."""
    if sys.platform != "win32":
        return
    base = subprocess.Popen

    class Popen(base):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
            super().__init__(*args, **kwargs)
    subprocess.Popen = Popen


def main() -> int:
    _hide_console_windows()
    if getattr(sys, "frozen", False):  # bundled: keep Bowers' own settings in the usual place
        os.environ.setdefault("BOWERS_INSTALLED_APP", "1")
    from .cli import main as cli_main
    args = sys.argv[1:]
    return cli_main(args if args and args[0] != "--app" else ["app", *args[1:]]) if args else cli_main(["app"])


if __name__ == "__main__":
    sys.exit(main())
