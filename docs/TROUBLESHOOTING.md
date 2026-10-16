# Troubleshooting / known gotchas

| Symptom | Cause | Fix |
|---|---|---|
| Sketchfab shows no model files, an API path ends in `fallback` | browser had only software rendering, Sketchfab served a still image | keep `GPU_ARGS` (Vulkan ANGLE); don't switch headless to SwiftShader |
| "blocked" on TurboSquid / Printables / 3d.si.edu | real bot protection (Cloudflare etc.) | assisted mode; the human passes the check. Do NOT add stealth / cookie copying |
| "blocked" on a normal page | `blocked` regex too loose | `blocked` must only use the title or a short (<1500 chars) page — check DETECT_JS |
| Engine shows "three.js" + "Verge3D" | Verge3D sets `window.__THREE__` | delete `three.js` when `window.v3d` exists |
| `.bin` labelled glTF wrongly | `.bin` is generic | label says "usually glTF"; don't claim more |
| Playwright: "Executable doesn't exist" | browser builds don't match the Playwright version | `.venv/bin/python -m playwright install chromium firefox` (pinned 1.63.0 in requirements.txt) |
| Firefox headless: no WebGPU | expected | use Auto/Brave/Chromium for WebGPU sites |
| Gallery explore tries the gallery itself | trailing slash (`/x/` vs `/x`) | URLs are normalised with `rstrip("/")` in JS and Python — keep it |
| Assisted run hangs | user never pressed "ready" | closing the visible window cancels; max wait 30 min |
| GUI buttons pushed off-screen | pack order | bottom bar is packed `side="bottom"` BEFORE the expanding body |
| History panel too narrow | pack order | History (`side`) is packed before the results (`left`) |

## Background Claude/agent sessions on this repo
Claude Code background sessions must edit inside a git worktree (`.claude/worktrees/…`, ignored by git). Its guard
rejects shell commands that mix `git` with `$VARIABLES` in program position — use absolute paths or a script file.

## Machine facts (AC130Tria)
- Python for the Desktop icons: `~/cheeky/venv/bin/python` (Playwright 1.63.0). `setup.sh` makes a repo-local `.venv`.
- Brave at `/usr/bin/brave`; Playwright Chromium + Firefox in `~/.cache/ms-playwright`.
- Assisted-mode profiles: `~/.cache/site-inspector-profile/<browser>` (never the user's real Brave profile).
- GPU: RX 9060 XT (RDNA4, Mesa RADV, Vulkan ANGLE works headless).
