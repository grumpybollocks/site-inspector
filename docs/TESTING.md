# Testing

| You changed… | Run |
|---|---|
| anything | `python -W error::SyntaxWarning -c "import inspect_site, extras, gui, sketchfab"` |
| classify / ext_of / cdn_of / summary / lessons / report HTML | `.venv/bin/python tests/test_offline.py` (no network, ~2 s) |
| DETECT_JS, GPU probe, wake, gallery explore, browser launch | offline tests + 2-3 sites below |
| gui.py | offline tests + the GUI screenshot check below |
| before a PR | `bash tests/regression.sh` (all sites, ~5-6 min) |

## Reference sites and what they should report (2026-10-16)
| URL | Expected |
|---|---|
| https://threejs.org/examples/webgl_loader_gltf.html | three.js r18x, 1 glTF binary on Fastly |
| https://modelviewer.dev/examples/loading/ | three.js + `<model-viewer>`, GLB on Fastly, Meshopt |
| https://sketchfab.com/3d-models/akmn-8a32337fe2eb4d528f82021d44e13bc8 | Sketchfab in-house engine, .binz on CloudFront, renders on demand |
| https://sandbox.babylonjs.com/?assetUrl=https://models.babylonjs.com/boombox.glb | Babylon.js 9.x, GLB on Azure Blob Storage |
| https://3dviewer.net/#model=https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Duck/glTF-Binary/Duck.glb | three.js, GLB on Fastly, no frames sampled |
| https://eyes.nasa.gov/curiosity/ | Verge3D (not also "three.js"), CloudFront, ~200 draws/frame |
| https://modely.cesnet.cz/en/ | gallery → explores to an object page → in-house engine via GPU catch-all |
| https://engine.needle.tools/samples/ | gallery → explores → Needle Engine on three.js, Draco + Basis |
| https://bruno-simon.com/ | three.js on **WebGPU**, Draco/Basis/Rapier wasm |
| https://playcanvas.com/ | engine name hidden → GPU catch-all, heavy instancing |
| https://3d.si.edu/collections/featured | Cloudflare → `blocked`; assisted mode needs a human |
| https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Duck/glTF-Binary/Duck.glb | "this link points straight at a 3D file" |

Numbers (buffers, fps, sizes) vary between runs; engine, formats, storage and the explore behaviour should not.

## GUI screenshot check (KDE Wayland, Tk runs on XWayland)
```python
import subprocess, gui
app = gui.App(); app.url.insert(0, "https://modelviewer.dev/examples/loading/"); app.after(500, app.start)
def check():
    if app.busy: return app.after(500, check)
    app.update(); subprocess.run(["import", "-window", app.wm_frame(), "/tmp/gui.png"]); app.destroy()
app.after(1500, check); app.mainloop()
```
Then look at `/tmp/gui.png`: tiles filled, bottom buttons visible, history shows scores, nothing cut off.

## Assisted mode without a human (flow test only)
Call `inspect_smart(url, assisted=True, ready=ev, on_waiting=lambda: threading.Timer(30, ev.set).start())`.
It opens a VISIBLE window. Real human checks (Cloudflare on 3d.si.edu) will still report `blocked` — that is correct.
