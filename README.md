# Site Inspector

Study tool: paste a link to a web page that shows a 3D model, and get a report on
**how the model is made visible, how it is stored, and how it is delivered**.

Two desktop apps share this code:
- **Site Inspector** (`gui.py`) - universal: any site with a live 3D view.
- **Sketchfab Inspector** (`gui.py --sketchfab`) - adds model facts from Sketchfab's official
  Data API v3 (geometry, materials, textures, licence, popularity) to the live analysis.

## What it reports
1. **Client side** - the engine/viewer (three.js, `<model-viewer>`, Babylon.js, PlayCanvas, Verge3D,
   Spline, Needle, A-Frame, xeokit, Potree, Marmoset, 3DHOP, Online3DViewer, Unity, Sketchfab...) and WebGL use.
2. **Files** - format (glTF/GLB, OBJ, STL, 3MF, USDZ, splats, 3D Tiles, point clouds, IFC, Sketchfab .binz...),
   size, transfer compression, CDN / storage (CloudFront, S3, Cloudflare, Fastly, GCS, Azure...),
   signed links, login, CORS, caching, plus texture images.
3. **Catch-all (any engine, even unknown/in-house)** - a probe injected before the site's own code counts
   what reaches the GPU: WebGL/WebGPU contexts, geometry buffers + bytes, textures, shader programs /
   pipelines, draw calls per frame, fps, GPU instancing, WebAssembly modules, web workers. Counts only, no data.
4. **Compression decoders** - Draco, Meshopt, KTX2/Basis (WebAssembly).
5. **API calls** feeding the page (catalogue/metadata), telemetry filtered out.
6. Screenshot of what the page showed.

## Report extras (good for presentations)
- **Architecture at a glance** - auto-drawn diagram: API -> page -> storage/CDN -> files -> decoder -> 3D engine -> GPU.
- **Lessons for your own site** - score /100 + tips: geometry compression, transfer compression, CDN, caching,
  download size, texture compression (KTX2), draw calls / instancing, access to files.
- **Load timeline** - when each model file / texture arrived (waterfall, bar width ~ size).
- **Glossary** - plain-English explanation of every term that appears in the report.
- **History + Compare** - every run is saved (`reports/*.json`); pick 2 in the window -> side-by-side table.
- **Save as PDF** - landscape A4, to hand in.

## Browsers
`Auto` (Brave if installed, else Playwright's Chromium), `Brave`, `Chromium`, `Firefox` (Gecko engine - Playwright's
build: `venv/bin/python -m playwright install chromium firefox`). Command line: `--browser=Firefox`.

## How it works
`inspect_site.py` opens the link in a hidden Brave (separate temporary profile, real GPU so sites
serve live 3D), records network responses (metadata only), wakes lazy viewers (scroll, "View in 3D"/"Play"
buttons, canvas click - never follows links), asks every frame which engine it runs, then writes
`reports/<host>-<time>.html`.

**Assisted mode** (tick "I'll open it myself", or `inspect_site.py --assisted <url>`): for sites with an
"are you human" check. A visible Brave window opens with its own profile (`~/.cache/site-inspector-profile`,
never your real Brave profile); you browse and pass the check yourself, then press "Page is ready – analyse".

It is an architecture report only: response bodies are never read or saved and file links are
shortened to host + format. Sites that block automated visits (bot protection) are reported as such
and are not worked around.

## Run
```
python -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python gui.py              # universal window
venv/bin/python gui.py --sketchfab  # Sketchfab window
venv/bin/python inspect_site.py [--assisted] [--browser=Firefox] <url>   # command line
```
Requires Brave at `/usr/bin/brave` (edit `BRAVE` in `inspect_site.py` for Chrome/Chromium).

## Tested (2026-10-16)
| Site | Result |
|---|---|
| Sketchfab | in-house OSG.JS engine, .binz scene + geometry on CloudFront, progressive textures |
| threejs.org examples / 3dviewer.net | three.js, GLB on Fastly |
| modelviewer.dev | model-viewer on three.js, GLB, Meshopt |
| Babylon.js sandbox | Babylon.js 9.30, GLB on Azure Blob Storage |
| bruno-simon.com | three.js r183 on **WebGPU**, Draco + Basis + Rapier physics WASM, ~131 draws/frame, 36k instanced |
| playcanvas.com | engine name hidden -> identified by the GPU catch-all (1.1k buffers, 2k instanced draws) |
| Printables, TurboSquid | block the hidden browser -> use assisted mode |
