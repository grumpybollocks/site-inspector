# AGENTS.md — Site Inspector (read this first)

Short on purpose: local agents have small context windows. Open the files in `docs/` only when a task needs them.

## What this is
A study tool. Paste a link to a web page that SHOWS a 3D model → report on **how the model is displayed
(engine), where it is stored (CDN/storage), how it is delivered (format, compression, signed links, API)**.
Desktop apps: "Site Inspector" (`gui.py`) and "Sketchfab Inspector" (`gui.py --sketchfab`).

## Hard rules (do not change without the owner asking)
1. **Architecture report only.** Never read or save response bodies, never output a working file URL
   (`short()` shortens to `host/…/*.ext`), never add a "download the model" feature.
2. **No bot-protection bypass.** No stealth plugins, fake fingerprints, copied cookies. Blocked sites → assisted
   mode (a human passes the check in a visible window).
3. **No prices** anywhere in reports or UI.
4. Keep explanations true: if two causes are possible, say both (see the zero-frames wording in `summary()`).

## Files
| File | Role |
|---|---|
| `inspect_site.py` | core: browser launch, network capture, GPU probe, gallery explore, summary, HTML report, CLI |
| `extras.py` | lessons score, glossary, SVG diagram, load timeline, compare, PDF |
| `sketchfab.py` | Sketchfab Data API v3 facts (public, no key) |
| `gui.py` | tkinter window (tiles, history, compare, PDF, assisted mode) |
| `tests/test_offline.py` | fast unit tests, NO network/browser — run after every change |
| `tests/regression.sh` | real sites, ~5 min, needs network + GPU |
| `docs/ARCHITECTURE.md` | data flow, the `found` / `record` dicts, how to add engines/formats/CDNs/lessons |
| `docs/TESTING.md` | which test for which change, expected results, GUI screenshot trick |
| `docs/TROUBLESHOOTING.md` | known gotchas (Sketchfab fallback, Cloudflare, Playwright versions, worktrees) |

## Commands
```bash
./setup.sh                                   # one-time: .venv + Playwright browsers
.venv/bin/python tests/test_offline.py       # 1-2 s, must pass before every commit
.venv/bin/python inspect_site.py <url>       # one inspection, prints summary + report path
.venv/bin/python inspect_site.py --browser=Firefox <url>
.venv/bin/python gui.py                      # the window
bash tests/regression.sh                     # full real-site check (slow)
```
(The Desktop icons currently use `~/cheeky/venv/bin/python`, which has the same Playwright 1.63.0.)

## Workflow
- Small, focused changes. After editing: `python -W error::SyntaxWarning -c "import inspect_site, extras, gui, sketchfab"`
  then `tests/test_offline.py`. Touching detection/network code → also run 2-3 sites from `tests/regression.sh`.
- JS lives in Python raw strings (`DETECT_JS`, `GPU_PROBE_JS`, `WAKE_JS`): use `r"""..."""`, single backslashes.
- `reports/` is git-ignored output. Never commit it.
- Git: branch + PR on `grumpybollocks/site-inspector` (private). Commit messages explain WHY.
