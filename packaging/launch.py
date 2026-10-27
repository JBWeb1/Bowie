"""Entry point for the bundled app: Bowers.exe opens the app window, bowers-cli.exe is the command line."""
import os
import sys

if __name__ == "__main__":
    if "cli" in os.path.basename(sys.executable).lower():
        from docks.cli import main
        sys.exit(main())
    from docks.app_entry import main
    sys.exit(main())
