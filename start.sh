#!/usr/bin/env bash
# =====================================================================
#  SkyWatch first-run bootstrap + launcher (Linux/macOS).
#  Run from a terminal:    ./start.sh
#  Forwards extra args to python -m skywatch.
# =====================================================================
set -e

cd "$(dirname "$0")"

echo
echo "============================================================"
echo " SkyWatch launcher"
echo "============================================================"

# --- 1. Locate Python (>= 3.10) ---
PYEXE=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
            PYEXE="$cand"
            break
        fi
    fi
done
if [ -z "$PYEXE" ]; then
    echo "[X] Python 3.10 or newer is required."
    echo "    Install via your package manager or https://www.python.org/downloads/"
    exit 1
fi
echo "[OK] Found Python:"
"$PYEXE" --version

# --- 2. Create venv if missing ---
if [ ! -x ".venv/bin/python" ]; then
    echo "[..] Creating virtual environment in .venv ..."
    "$PYEXE" -m venv .venv
fi
VENVPY=".venv/bin/python"
echo "[OK] Virtual environment: .venv"

# --- 3. Install / refresh dependencies if requirements.txt is newer
#        than the marker file. ---
MARKER=".venv/skywatch.installed"
NEED_INSTALL=0
if [ ! -f "$MARKER" ]; then
    NEED_INSTALL=1
elif [ "requirements.txt" -nt "$MARKER" ]; then
    NEED_INSTALL=1
fi

if [ "$NEED_INSTALL" = "1" ]; then
    echo "[..] Installing dependencies from requirements.txt ..."
    "$VENVPY" -m pip install --upgrade pip >/dev/null
    "$VENVPY" -m pip install -r requirements.txt
    echo "installed" > "$MARKER"
    echo "[OK] Dependencies installed."
else
    echo "[OK] Dependencies up to date."
fi

# --- 4. Sanity-check the bundled tools dir for the host platform ---
case "$(uname -s)" in
    Linux*)   PLAT="linux64" ;;
    Darwin*)  if [ "$(uname -m)" = "arm64" ]; then PLAT="darwin-arm64"; else PLAT="darwin-x64"; fi ;;
    *)        PLAT="" ;;
esac
if [ -n "$PLAT" ] && [ -d "tools/$PLAT" ]; then
    echo "[OK] Bundled tools detected: tools/$PLAT/"
else
    echo "[!!] No tools/$PLAT/ folder. RTL-SDR features will fall back to"
    echo "     anything on your system PATH (rtl_fm, rtl_ais, librtlsdr)."
fi

# --- 5. Launch ---
echo
echo "============================================================"
echo " Launching SkyWatch.  Open http://localhost:8080"
echo " (Ctrl+C stops the server.)"
echo "============================================================"
echo
exec "$VENVPY" -m skywatch "$@"
