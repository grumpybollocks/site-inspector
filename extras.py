#!/usr/bin/env python3
"""
Extra report features for Site Inspector:
  lessons()      - "what would I copy for my own site" score with concrete tips
  glossary()     - plain-English explanations of the terms that appear in a report
  diagram_svg()  - architecture flow picture (page -> API -> storage -> decoder -> engine -> GPU)
  timeline_html()- when each file arrived while the page loaded (waterfall)
  compare()      - side-by-side comparison of two saved inspections
  to_pdf()       - print a report to PDF
"""
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path

COMPRESSED_FORMATS = re.compile(r"binz|nxz|sog|laz|ctm|draco|compressed", re.I)
TEXT_FORMATS = re.compile(r"glTF JSON|Wavefront OBJ|X3D|VRML|Collada", re.I)


def _fit(text, n=24):
    """shorten to fit a diagram box"""
    text = str(text)
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _human(n):
    if not n:
        return "?"
    return f"{n/1048576:.1f} MB" if n >= 1048576 else f"{n/1024:.0f} KB" if n >= 1024 else f"{n} B"


def _max_age(cache):
    m = re.search(r"max-age=(\d+)", cache or "")
    return int(m.group(1)) if m else (10**9 if "immutable" in (cache or "") else 0)


# ---------------------------------------------------------------------------
def lessons(found, records, decoders):
    """Returns (score 0-100 or None, [(status, title, detail)]), status in ok / tip / info."""
    models = [r for r in records if r["kind"] == "model"]
    g = found.get("gpu") or {}
    out = []
    if not models and not g.get("draws"):
        return None, [("info", "Nothing to grade", "No 3D files or GPU drawing were seen on this page.")]

    if models:
        # only GEOMETRY decoders count here - a texture decoder (Basis/KTX2) says nothing about the mesh
        geo_dec = [d for d in decoders if re.search(r"Draco|Meshopt", d)]
        comp = bool(geo_dec) or any(COMPRESSED_FORMATS.search(r["format"]) for r in models)
        out.append(("ok" if comp else "tip", "Geometry compression",
                    "Geometry is compressed (" + (", ".join(geo_dec) or "compressed format") + ")." if comp else
                    "Geometry is sent uncompressed. Draco or Meshopt (glTF extensions) usually make it 5-10x smaller."))
        text = [r for r in models if TEXT_FORMATS.search(r["format"])]
        if text:
            gz = all(r["encoding"] not in ("none", "") for r in text)
            out.append(("ok" if gz else "tip", "Transfer compression of text formats",
                        "Text-based model files are sent gzip/brotli compressed." if gz else
                        "Text-based model files (glTF JSON / OBJ / X3D) are sent without gzip/brotli - enable it on the server."))
        cdn = [r for r in models if not r["cdn"].startswith("own web server")]
        out.append(("ok" if cdn else "tip", "CDN / object storage",
                    f"Files come from {', '.join(sorted({r['cdn'] for r in cdn}))} - close to the visitor, scales well." if cdn else
                    "Files come from the site's own web server. A CDN or object storage (S3, R2, Cloudflare) is faster worldwide."))
        cached = [r for r in models if _max_age(r["cache"]) >= 3600]
        out.append(("ok" if len(cached) == len(models) else "tip", "Browser caching",
                    "Model files may be cached by the browser for an hour or more." if len(cached) == len(models) else
                    "Some model files have short or no caching (Cache-Control). Versioned file names + long max-age avoid re-downloads."))
        total = sum(r["size"] for r in models)
        if total:
            out.append(("ok" if total < 10 * 1048576 else "tip", "Download size",
                        f"All model files together: {_human(total)}." +
                        ("" if total < 10 * 1048576 else " Over 10 MB - consider levels of detail (LOD) or streaming.")))
    tex_comp = any("Basis" in d or "KTX2" in d for d in decoders) or \
        any(r["kind"] == "texture" and "KTX2" in r["format"] for r in records)
    if (found.get("textures") or g.get("textures", 0) > 4):
        out.append(("ok" if tex_comp else "tip", "Texture compression",
                    "Textures use GPU-ready compression (KTX2/Basis) - less memory, faster upload." if tex_comp else
                    "Textures are plain JPEG/PNG. KTX2 (Basis Universal) keeps them compressed on the GPU too."))
    if g.get("frames"):
        dpf = g.get("draws_per_frame") or 0
        out.append(("ok" if dpf <= 300 else "tip", "Draw calls per frame",
                    ("Renders on demand - nothing is redrawn while the view is still." if not dpf else
                     f"~{dpf} draw calls per frame") + ("" if not dpf else " - efficient." if dpf <= 300 else
                    " - high; merge meshes or use instancing to lower CPU cost.") +
                    (f" Uses GPU instancing ({g.get('instanced', 0):,} instanced draws)." if g.get("instanced") else "")))
    if models:
        signed = any(r["signed"] != "no" for r in models)
        auth = any(r["auth"] != "none" for r in models)
        out.append(("info", "Access to the files",
                    "Signed, expiring links - the backend decides per request who may load a file." if signed else
                    "Files are sent with the visitor's login." if auth else
                    "Files are public URLs - anyone with the link can load them (normal for previews)."))
    graded = [s for s, _, _ in out if s in ("ok", "tip")]
    score = round(100 * graded.count("ok") / len(graded)) if graded else None
    return score, out


# ---------------------------------------------------------------------------
GLOSSARY = [
    (r"CDN|CloudFront|Cloudflare|Fastly|Akamai|BunnyCDN", "CDN",
     "Content Delivery Network: copies of the files on servers around the world, so each visitor downloads from a nearby one."),
    (r"S3|Azure Blob|Google Cloud Storage", "Object storage",
     "Cloud 'buckets' that store files cheaply (Amazon S3, Azure Blob, Google Cloud Storage); usually put behind a CDN."),
    (r"glTF|GLB", "glTF / GLB",
     "The standard web 3D format ('JPEG of 3D'): meshes, materials, textures, animations. GLB is the single-file binary version."),
    (r"Draco", "Draco", "Google's geometry compression; shrinks meshes a lot, decoded in the browser by a WebAssembly decoder."),
    (r"Meshopt", "Meshopt", "Mesh compression/optimisation for glTF; very fast to decode, often combined with gzip/brotli."),
    (r"KTX2|Basis", "KTX2 / Basis Universal", "Texture format that stays compressed in GPU memory; one file works on every GPU."),
    (r"WebAssembly|wasm", "WebAssembly", "Fast compiled code running in the browser; used for decoders, physics and whole engines."),
    (r"signed", "Signed link", "A file URL with a signature and expiry time, created by the backend - access control for files on a CDN."),
    (r"CORS|\*", "CORS", "Header that says which other websites may load a file with JavaScript (Access-Control-Allow-Origin)."),
    (r"draw call", "Draw call", "One command to the GPU to draw a batch of triangles. Fewer, bigger batches = smoother."),
    (r"instanc", "GPU instancing", "Drawing many copies of the same mesh with ONE draw call (trees, bolts, crowds)."),
    (r"WebGPU", "WebGPU", "The new browser graphics API (successor to WebGL): lower overhead, compute shaders."),
    (r"WebGL", "WebGL", "The browser graphics API (based on OpenGL ES) used by almost every 3D site."),
    (r"shader", "Shader program", "Small GPU programs that position vertices and colour pixels; materials compile into these."),
    (r"three\.js", "three.js", "The most popular open-source JavaScript 3D library; many viewers (model-viewer, A-Frame) are built on it."),
    (r"Babylon", "Babylon.js", "Microsoft-backed open-source 3D engine for the web."),
    (r"OSG\.JS|Sketchfab", "Sketchfab engine", "Sketchfab's in-house WebGL engine (based on OSG.JS); streams its own compressed .binz files."),
    (r"progressive", "Progressive loading", "Low-resolution data first, sharper versions later, so something appears quickly."),
    (r"on demand", "On-demand rendering", "Redrawing only when something changes, instead of 60 times a second."),
    (r"Cache-Control|cach", "Caching", "Headers telling the browser how long it may reuse a downloaded file without asking again."),
    (r"API", "API", "The backend address the page asks for data (catalogue, model details) - usually returns JSON."),
]


def glossary(text):
    return [(term, expl) for pat, term, expl in GLOSSARY if re.search(pat, text, re.I)]


# ---------------------------------------------------------------------------
def diagram_svg(found, records, decoders, apis):
    """Architecture flow drawn with what this inspection found."""
    models = [r for r in records if r["kind"] == "model"]
    g = found.get("gpu") or {}
    storage = ", ".join(sorted({r["cdn"] for r in models}))[:40] or "—"
    fmts = ", ".join(sorted({r["format"].split(" (")[0] for r in models}))[:40] or "no standard file"
    engine = ", ".join(k.split(" (")[0] for k in found.get("libs", {}))[:40] or "in-house / unknown"
    gpu = ("WebGPU" if g.get("webgpuDevice") else "WebGL") + (f" · ~{g['draws_per_frame']} draws/frame" if g.get("draws_per_frame") else "")
    boxes = [("Web page", found.get("title", "")[:34] or "—"),
             ("Storage / CDN", storage), ("Files", fmts),
             ("Decoder", ", ".join(d.split(" ")[0] for d in decoders)[:40] or "none needed"),
             ("3D engine", engine), ("GPU", gpu)]
    W, H, bw, bh, gap = 1240, 230, 180, 74, 32
    x0 = (W - (len(boxes) * bw + (len(boxes) - 1) * gap)) // 2
    y = 120
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="system-ui" font-size="12">',
             '<defs><marker id="a" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
             '<path d="M0,0 L10,4 L0,8 z" fill="#c8b089"/></marker></defs>']
    for i, (head, body) in enumerate(boxes):
        x = x0 + i * (bw + gap)
        parts.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="10" fill="#1e2229" stroke="#c8b089"/>'
                     f'<text x="{x + bw/2}" y="{y + 26}" fill="#c8b089" text-anchor="middle" font-weight="bold">{escape(head)}</text>'
                     f'<text x="{x + bw/2}" y="{y + 50}" fill="#e8e6e1" text-anchor="middle">{escape(_fit(body))}</text>')
        if i:
            parts.append(f'<line x1="{x - gap + 2}" y1="{y + bh/2}" x2="{x - 3}" y2="{y + bh/2}" stroke="#c8b089" '
                         f'stroke-width="2" marker-end="url(#a)"/>')
    # API box above, feeding the page
    ax = x0
    api_txt = f"{len(apis)} endpoint(s)" if apis else "none seen"
    parts.append(f'<rect x="{ax}" y="14" width="{bw}" height="60" rx="10" fill="#1e2229" stroke="#7fa6c9"/>'
                 f'<text x="{ax + bw/2}" y="38" fill="#7fa6c9" text-anchor="middle" font-weight="bold">API (JSON)</text>'
                 f'<text x="{ax + bw/2}" y="58" fill="#e8e6e1" text-anchor="middle">{escape(api_txt)}</text>'
                 f'<line x1="{ax + bw/2}" y1="76" x2="{ax + bw/2}" y2="{y - 4}" stroke="#7fa6c9" stroke-width="2" marker-end="url(#a)"/>'
                 f'<text x="{ax + bw/2 + 8}" y="{(76 + y)/2 + 4}" fill="#9aa0a8">catalogue / details</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
def timeline_html(records):
    """Waterfall of when 3D files / textures arrived (seconds after the page started loading)."""
    rows = sorted((r for r in records if r.get("t") is not None), key=lambda r: r["t"])[:40]
    if not rows:
        return "<p>no timing data</p>"
    tmax = max(r["t"] for r in rows) or 1
    out = ["<div style='font-size:12px'>"]
    for r in rows:
        left = 100 * r["t"] / tmax * 0.78
        out.append(f"<div style='display:flex;align-items:center;margin:2px 0'>"
                   f"<span style='width:46px;color:#9aa0a8'>{r['t']:.1f}s</span>"
                   f"<div style='flex:1;position:relative;height:16px'>"
                   f"<div style='position:absolute;left:{left:.1f}%;height:14px;width:{max(1.5, min(20, (r['size'] or 0) / 200000)):.1f}%;"
                   f"background:{'#c8b089' if r['kind'] == 'model' else '#7fa6c9'};border-radius:3px'></div>"
                   f"<span style='position:absolute;left:{min(left + 2, 80):.1f}%;padding-left:24px;white-space:nowrap'>"
                   f"{escape(r['format'])} · {_human(r['size'])}</span></div></div>")
    out.append("<p style='color:#9aa0a8'>Gold = model files, blue = textures. Bar width ~ file size.</p></div>")
    return "".join(out)


# ---------------------------------------------------------------------------
def compare(json_a, json_b, out_dir):
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (json_a, json_b))
    rows = [("Site", "host"), ("Page", "title"), ("Inspected", "when"), ("3D engine", "engine"),
            ("File formats", "formats"), ("Storage / CDN", "storage"), ("Model files", "model_files"),
            ("Model data", "model_bytes"), ("Textures loaded", "textures"), ("Compression", "compression"),
            ("Signed links", "signed"), ("Graphics API", "graphics_api"), ("GPU buffers", "gpu_buffers"),
            ("Draw calls / frame", "draws_per_frame"), ("Frame rate", "fps"), ("Instanced draws", "instanced"),
            ("WebAssembly modules", "wasm"), ("API endpoints", "api_count"), ("'Lessons' score", "score")]
    trs = "".join(f"<tr><th>{escape(lbl)}</th><td>{escape(str(a.get(k, '-')))}</td><td>{escape(str(b.get(k, '-')))}</td></tr>"
                  for lbl, k in rows)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Compare – {escape(a.get('host',''))} vs {escape(b.get('host',''))}</title>
<style>body{{font-family:system-ui;background:#14171c;color:#e8e6e1;margin:24px;max-width:1200px}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #2f3540;padding:8px;text-align:left;vertical-align:top}}
th{{background:#1e2229;width:220px}} thead th{{color:#c8b089}}</style></head><body>
<h1>Side-by-side: {escape(a.get('host',''))} vs {escape(b.get('host',''))}</h1>
<table><thead><tr><th></th><th>{escape(a.get('host',''))}</th><th>{escape(b.get('host',''))}</th></tr></thead>{trs}</table>
<p style="color:#9aa0a8">Full reports: <a style="color:#c8b089" href="{escape(Path(a['report']).name)}">{escape(a['host'])}</a> ·
<a style="color:#c8b089" href="{escape(Path(b['report']).name)}">{escape(b['host'])}</a></p></body></html>"""
    out = Path(out_dir) / f"compare-{datetime.now():%Y%m%d-%H%M%S}.html"
    out.write_text(html, encoding="utf-8")
    return out


def run_summary(url, host, found, records, decoders, apis, score, report_path):
    """Flat facts saved next to each report (used by history + compare)."""
    models = [r for r in records if r["kind"] == "model"]
    g = found.get("gpu") or {}
    return {
        "url": url, "host": host, "title": found.get("title", ""), "when": f"{datetime.now():%Y-%m-%d %H:%M}",
        "engine": ", ".join(found.get("libs", {})) or ("blocked" if found.get("blocked") else "in-house / unknown"),
        "formats": ", ".join(sorted({r["format"] for r in models})) or "-",
        "storage": ", ".join(sorted({r["cdn"] for r in models})) or "-",
        "model_files": len(models), "model_bytes": _human(sum(r["size"] for r in models)),
        "textures": len(found.get("textures") or []), "compression": ", ".join(decoders) or "-",
        "signed": "yes" if any(r["signed"] != "no" for r in models) else "no",
        "graphics_api": ("WebGPU" if g.get("webgpuDevice") else "WebGL") if g.get("draws") or g.get("buffers") else "-",
        "gpu_buffers": f"{g.get('buffers', 0):,} ({_human(g.get('bufferBytes', 0))})",
        "draws_per_frame": g.get("draws_per_frame", "-"), "fps": g.get("fps", "-"), "instanced": g.get("instanced", 0),
        "wasm": ", ".join(found.get("wasm") or {}) or "-", "api_count": len(apis),
        "score": f"{score}/100" if score is not None else "-", "report": str(report_path),
    }


# ---------------------------------------------------------------------------
def to_pdf(report_path):
    """Print an HTML report to PDF with Playwright's bundled Chromium (headless)."""
    from playwright.sync_api import sync_playwright
    report_path = Path(report_path)
    out = report_path.with_suffix(".pdf")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(report_path.resolve().as_uri(), wait_until="load")
        pg.emulate_media(media="screen")
        pg.pdf(path=str(out), format="A4", landscape=True, print_background=True,
               margin={"top": "10mm", "bottom": "10mm", "left": "8mm", "right": "8mm"})
        b.close()
    return out
