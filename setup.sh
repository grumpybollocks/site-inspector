#!/usr/bin/env bash
# One-time setup: repo-local virtualenv + Playwright browsers.
#   ./setup.sh            create .venv, install requirements, download Chromium + Firefox for Playwright
#   ./setup.sh --desktop  also (re)create the two Desktop icons pointing at this checkout's .venv
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m playwright install chromium firefox
.venv/bin/python -W error::SyntaxWarning -c "import inspect_site, extras, gui, sketchfab" && echo "imports OK"
.venv/bin/python tests/test_offline.py

if [[ "${1:-}" == "--desktop" ]]; then
    here="$(pwd)"
    for mode in "" "--sketchfab"; do
        name="Site Inspector"; icon="applications-internet"; comment="Paste a link: see how the site stores and shows its 3D model"
        [[ -n "$mode" ]] && { name="Sketchfab Inspector"; icon="view-3d"; comment="Sketchfab link: model facts + how its viewer streams it"; }
        cat > "$HOME/Desktop/$name.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Comment=$comment
Exec=$here/.venv/bin/python $here/gui.py $mode
Path=$here
Icon=$icon
Terminal=false
EOF
        chmod +x "$HOME/Desktop/$name.desktop"
    done
    echo "Desktop icons updated."
fi
