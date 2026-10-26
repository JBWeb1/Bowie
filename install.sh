#!/bin/sh
# Install Bowers on Linux or macOS and add it to your app launcher.
#   curl -fsSL https://raw.githubusercontent.com/JBWeb1/Docks/main/install.sh | sh
set -e
SOURCE="${BOWERS_SOURCE:-git+https://github.com/JBWeb1/Docks}"
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Bowers needs Python 3.10 or newer: https://www.python.org/downloads/"; exit 1; }
if command -v pipx >/dev/null 2>&1; then
  pipx install --force "docks[browser,labs] @ $SOURCE"
else
  "$PY" -m pip install --user --upgrade "docks[browser,labs] @ $SOURCE" || "$PY" -m pip install --user --break-system-packages --upgrade "docks[browser,labs] @ $SOURCE"
fi
bowers install-app 2>/dev/null || "$PY" -m docks install-app
echo
echo "Bowers is installed. Start it from your app launcher, or run: bowers app"
echo "Set ANTHROPIC_API_KEY in your shell profile (optional: OPENAI_API_KEY, LTX_API_KEY, ELEVENLABS_API_KEY)."
