#!/usr/bin/env bash
# Pure-ASCII launcher: all logic lives in scripts/setup_offline.py
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys" >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "[X] Python 3.10+ not found."
    echo "    Install it from https://www.python.org/downloads/"
    exit 1
fi
exec "$PY" "$SCRIPT_DIR/scripts/setup_offline.py" "$@"
