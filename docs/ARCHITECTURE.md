# Architecture

## Data flow
```
URL ─► inspect_smart() ─► inspect()
          │                 1. open_browser()      Brave / Playwright Chromium / Firefox; hidden, or visible+own profile (assisted)
          │                 2. add_init_script(GPU_PROBE_JS)   counts WebGL/WebGPU calls in EVERY frame, before site code runs
          │                 3. ctx.on("response", on_response) classify() each response → records / decoders / apis / images
          │                 4. goto(url); wait WAIT_AFTER_LOAD (or wait for the user's "ready" in assisted mode)
          │                 5. analyse(page): wake_viewers() → DETECT_JS (main + iframes) → gpu_stats() (2 s sample)
          │                 6. no 3D on the page? → follow up to 3 `candidates` (same site, same session) and re-analyse
          │                 7. screenshot, close; textures = images from the same hosts as model files
          ▼
 (found, records, decoders, apis, shot, secs, final_url)
          │
          ├─► summary()            plain-English bullet lines (CLI + GUI + report)
          ├─► extras.lessons()     score /100 + tips
          └─► report()             reports/<host>-<time>.html  +  .json (extras.run_summary, used by History/Compare)
```

## Return values of `inspect()`
`found` (dict):
| key | meaning |
|---|---|
| `libs` | `{engine name: version}` from DETECT_JS (three.js, Babylon.js, Verge3D, model-viewer, …) |
| `embeds` | hosts of embedded 3D iframes (sketchfab, matterport, …) |
| `webgl`, `webgl2` | canvases whose context the GPU probe saw (`canvas.__siCtx`) |
| `gpu` | probe counters: `ctx`, `buffers`, `bufferBytes`, `textures`, `programs`, `draws`, `instanced`, `frames`, `fps`, `draws_per_frame` (None if no frames), `webgpu`, `webgpuDevice`, `wasm`, `workers` |
| `blocked` | bot-check page detected (title, or short page about the check) |
| `candidates` | same-site links that look like model pages (keywords or thumbnail grid) |
| `explored_from`, `final_url` | gallery exploring: where we started / the page really analysed |
| `direct_file` | the pasted link itself is a 3D file (format label) |
| `wasm` | `{wasm file name: size}` |
| `textures` | list of image sizes from the model storage hosts |
| `fallback` | an API path ending in `fallback` was seen (Sketchfab still-image mode) |
| `browser`, `title`, `scripts` | browser used, page title, viewer-looking script names |
| GUI/CLI add: `sketchfab` (Data API sections), `api_textures` | |

`records` (list of dicts, one per 3D file / texture file, de-duplicated by URL):
`kind` (model|texture), `format`, `where` (shortened `host/…/*.ext`), `size`, `encoding`, `cdn`, `cache`,
`cors`, `signed` (query keys like X-Amz-Signature or "no"), `auth` (none|cookies|Authorization header),
`via` (fetch/xhr/…), `status`, `ctype`, `t` (seconds after start).

`decoders`: `{label: host}` (Draco, Meshopt, Basis/KTX2, IFC, Rhino). `apis`: `{pattern with {id}: HTTP status}`.

## How to extend
| Task | Where | Notes |
|---|---|---|
| New 3D engine | `DETECT_JS` (inspect_site.py) | add `if (window.X) out['Name'] = version;`. If it is built on three.js and sets `__THREE__`, `delete out['three.js']` (see Verge3D). |
| New file format | `MODEL_EXT` / `TEXTURE_EXT` | key = extension without dot; `ext_of()` already looks through `.gz/.br/.zst` |
| New decoder | `DECODERS` | key is a regex matched against the FILE NAME only (avoid short words: `ifc` needed boundaries) |
| New CDN / storage | `cdn_of()` | detect by response headers, most specific first |
| New embedded viewer host | regex in DETECT_JS `embeds` | |
| Telemetry noise in APIs | `TELEMETRY` regex | |
| New lesson / tip | `extras.lessons()` | append `("ok"|"tip"|"info", title, detail)`; only ok/tip are scored |
| New glossary term | `extras.GLOSSARY` | `(regex that must appear in the report text, term, explanation)` |
| Platform with an official public API (like Sketchfab) | new module like `sketchfab.py` returning `[(section, [(label, value)])]`, passed as `extra` to `report()` | public metadata only |
| GUI | `gui.py` `App.done()` fills tiles + text; colours/fonts at the top | test with the screenshot trick in TESTING.md |

## Design decisions (why things are the way they are)
- **Real GPU first** (`GPU_ARGS`): with software rendering Sketchfab serves a still-image "fallback" instead of 3D.
- **GPU probe instead of engine lists only**: any engine must call WebGL/WebGPU, so counts describe unknown engines too.
- **DETECT_JS never calls `getContext()`**: that would create new contexts and distort the counts; it reads `canvas.__siCtx`.
- **Worker is wrapped with a Proxy**, not a function, so `instanceof Worker` and subclasses keep working on the page.
- **Gallery exploring stays in the same browser session**, so a human check passed in assisted mode remains valid.
- **Zero frames sampled** can mean on-demand rendering OR rendering in a worker — reports say both.
