#!/usr/bin/env bash
# Real-site regression (needs network + GPU, ~5-6 min). Compare the output with docs/TESTING.md.
#   bash tests/regression.sh            all sites
#   bash tests/regression.sh sketchfab  only lines whose URL contains "sketchfab"
cd "$(dirname "$(realpath "$0")")/.." || exit 1
PY=.venv/bin/python
[[ -x "$PY" ]] || PY="$HOME/cheeky/venv/bin/python"     # fallback used by the Desktop icons on AC130Tria
"$PY" -W error::SyntaxWarning -c "import inspect_site, extras, gui, sketchfab" || exit 1
"$PY" tests/test_offline.py >/dev/null || { echo "offline tests fail - fix those first"; exit 1; }

filter="${1:-}"
grep -vE '^\s*(#|$)' <<'EOF' | grep -i -- "$filter" | while read -r u; do
https://threejs.org/examples/webgl_loader_gltf.html
https://modelviewer.dev/examples/loading/
https://sketchfab.com/3d-models/akmn-8a32337fe2eb4d528f82021d44e13bc8
https://sandbox.babylonjs.com/?assetUrl=https://models.babylonjs.com/boombox.glb
https://3dviewer.net/#model=https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Duck/glTF-Binary/Duck.glb
https://eyes.nasa.gov/curiosity/
https://modely.cesnet.cz/en/
https://engine.needle.tools/samples/
https://bruno-simon.com/
https://playcanvas.com/
https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Duck/glTF-Binary/Duck.glb
EOF
  echo "######## $u"
  s=$(date +%s)
  timeout 300 "$PY" inspect_site.py "$u" 2>&1 | grep -v '^Report' | grep -vE '^\s*(Call log|- navigating|=====)' | head -7
  echo "   ($(( $(date +%s) - s ))s)"
done
