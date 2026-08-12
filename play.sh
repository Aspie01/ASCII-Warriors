#!/usr/bin/env sh
# ASCII Warriors launcher (Linux / macOS / BSD)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
    done
fi
if [ -z "$PY" ]; then
    echo "ASCII Warriors needs Python 3.9 or newer on your PATH." >&2
    exit 1
fi
cd "$DIR"
exec "$PY" -m ascii_warriors "$@"
