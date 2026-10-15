#!/usr/bin/env python3
"""
Site Inspector - explains how a web page delivers and shows a 3D model.

Opens the link in a hidden Brave (separate temporary profile), watches every
network request while the page loads, asks the page which 3D viewer library it
runs, and writes an HTML report:
  - which viewer / engine draws the model (three.js, model-viewer, Babylon, ...)
  - which 3D file formats are loaded, how big, compressed how (Draco, Meshopt, KTX2)
  - where they are stored (host / CDN / storage service) and how they are protected
    (signed links, cookies/login, CORS, caching)
  - the API calls that feed the page (catalogue / metadata pattern)

It describes the architecture only: response bodies are never read or saved,
and model file links are shortened to host + format.

Usage: inspect_site.py <url>     (prints "Report: <path>" at the end)
"""
import re
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from playwright.sync_api import sync_playwright

BRAVE = "/usr/bin/brave"
REPORTS = Path(__file__).resolve().parent / "reports"
WAIT_AFTER_LOAD = 10  # seconds for viewers that load the model after the page

MODEL_EXT = {"glb": "glTF binary", "gltf": "glTF JSON", "bin": "glTF buffer", "drc": "Draco mesh",
             "obj": "Wavefront OBJ", "stl": "STL", "fbx": "FBX", "ply": "PLY", "3mf": "3MF",
             "usdz": "USDZ (Apple AR)", "usd": "USD", "splat": "Gaussian splat", "spz": "Gaussian splat",
             "ksplat": "Gaussian splat", "3dm": "Rhino", "dae": "Collada", "vox": "VOX",
             "osgjs": "Sketchfab scene (OSG.JS)", "binz": "Sketchfab geometry (compressed)",
             "mview": "Marmoset Viewer scene", "ifc": "IFC (BIM building model)", "xkt": "xeokit BIM geometry",
             "b3dm": "3D Tiles batched mesh", "i3dm": "3D Tiles instanced mesh", "pnts": "3D Tiles point cloud",
             "cmpt": "3D Tiles composite", "las": "LAS point cloud", "laz": "LAZ point cloud (compressed)",
             "e57": "E57 point cloud", "nxs": "Nexus multiresolution mesh (3DHOP)", "nxz": "Nexus mesh, compressed (3DHOP)",
             "ctm": "OpenCTM compressed mesh", "vrm": "VRM avatar (glTF)", "x3d": "X3D", "wrl": "VRML",
             "3ds": "3DS", "step": "STEP CAD", "stp": "STEP CAD", "iges": "IGES CAD", "igs": "IGES CAD",
             "sog": "Gaussian splat (compressed)", "dracomesh": "Draco mesh", "vtk": "VTK", "pcd": "PCD point cloud"}
TEXTURE_EXT = {"ktx2": "KTX2 GPU texture", "basis": "Basis texture", "hdr": "HDR environment",
               "exr": "EXR environment", "env": "Babylon environment"}
DECODERS = {"draco": "Draco geometry compression", "meshopt": "Meshopt compression",
            "basis_transcoder": "Basis/KTX2 texture compression", "ktx2": "KTX2 texture compression",
            "rhino3dm": "Rhino decoder", "ifc": "IFC (BIM) decoder"}
SIGNED_KEYS = re.compile(r"signature|x-amz-|expires|^exp$|token|^sig$|policy|key-pair-id|hdnts|^st$|^e$", re.I)

DETECT_JS = r"""() => {
  const out = {};
  const T = window.THREE || null;
  if (window.__THREE__ || T) out['three.js'] = 'r' + (window.__THREE__ || (T && T.REVISION) || '?');
  if (customElements.get('model-viewer')) out['<model-viewer> (Google)'] = 'web component';
  if (window.BABYLON) out['Babylon.js'] = (BABYLON.Engine && BABYLON.Engine.Version) || '?';
  if (window.pc && window.pc.version) out['PlayCanvas'] = window.pc.version;
  if (window.Cesium) out['CesiumJS'] = Cesium.VERSION || '?';
  if (window.Sketchfab) out['Sketchfab Viewer API'] = 'script';
  if (window.createUnityInstance || window.UnityLoader) out['Unity WebGL'] = 'build';
  if (window.SPLAT || window.GaussianSplats3D) out['Gaussian splat viewer'] = 'script';
  if (window.v3d) out['Verge3D'] = (v3d.REVISION ? 'r' + v3d.REVISION : '?');
  if (customElements.get('spline-viewer')) out['Spline viewer'] = 'web component';
  if (customElements.get('needle-engine')) out['Needle Engine'] = 'web component';
  if (customElements.get('babylon-viewer')) out['Babylon viewer'] = 'web component';
  if (window.AFRAME) out['A-Frame (WebXR, on three.js)'] = AFRAME.version || '?';
  if (window.xeokit) out['xeokit (BIM viewer)'] = 'SDK';
  if (window.Potree) out['Potree (point clouds)'] = Potree.version ? JSON.stringify(Potree.version) : '?';
  if (window.marmoset) out['Marmoset Viewer'] = 'script';
  if (window.Presenter && window.Nexus) out['3DHOP'] = 'script';
  if (window.OV && window.OV.EmbeddedViewer) out['Online3DViewer'] = 'library';
  if (window.Module && window.Module.canvas && window.godot) out['Godot (WebAssembly)'] = 'export';
  if (/sketchfab\.com$/.test(location.host) && document.querySelector('canvas'))
    out["Sketchfab's own WebGL engine (built on OSG.JS)"] = 'in-house';
  const frames = [...document.querySelectorAll('iframe')].map(f => f.src).filter(Boolean);
  const embeds = frames.filter(s => /sketchfab|p3d\.in|vectary|spline\.design|clara\.io|myminifactory|3dviewer|matterport|kuula|3dvista|shapespark|marmoset|verge3d|needle\.tools|playcanv\.as|babylonjs|modelviewer|threedium|emersya|cappasity/i.test(s))
                       .map(s => new URL(s).host);
  let gl = 0, gl2 = 0;
  for (const c of document.querySelectorAll('canvas')) {
    if (c.getContext('webgl2')) gl2++; else if (c.getContext('webgl')) gl++;
  }
  const scripts = [...document.scripts].map(s => s.src).filter(Boolean)
     .filter(s => /three|babylon|model-viewer|playcanvas|cesium|draco|meshopt|unity|splat|viewer|webgl/i.test(s))
     .map(s => { const u = new URL(s); return u.host + '/' + u.pathname.split('/').pop(); });
  const txt = (document.body && document.body.innerText || '').slice(0, 3000);
  const blocked = /access (is )?(temporarily )?(restricted|denied)|just a moment|verify you are human|unusual activity|captcha|are you a robot/i.test(document.title + ' ' + txt);
  return {blocked, libs: out, embeds: [...new Set(embeds)], webgl: gl, webgl2: gl2, scripts: [...new Set(scripts)].slice(0, 15),
          title: document.title};
}"""


def ext_of(url):
    """file extension, looking through one compression layer: file.bin.gz -> bin"""
    name = urlsplit(url).path.rsplit("/", 1)[-1].lower()
    for z in (".gz", ".br", ".zst"):
        if name.endswith(z) and name.count(".") >= 2:
            name = name[: -len(z)]
    return name.rsplit(".", 1)[-1] if "." in name else ""


def short(url):
    """host + /…/*.ext - enough to explain the storage, not a working link."""
    u = urlsplit(url)
    e = ext_of(url)
    return f"{u.netloc}/…/*.{e}" if e else f"{u.netloc}/…"


def api_pattern(url):
    u = urlsplit(url)
    parts = ["{id}" if re.search(r"\d{3,}|[0-9a-f]{12,}|[0-9a-f]{8}-[0-9a-f]{4}", p, re.I) else p
             for p in u.path.split("/")]
    return u.netloc + "/".join(parts)


def cdn_of(headers):
    h = {k.lower(): v for k, v in headers.items()}
    srv = h.get("server", "").lower()
    if "x-amz-cf-id" in h or "cloudfront" in h.get("via", "").lower(): return "Amazon CloudFront"
    if "cf-ray" in h or srv == "cloudflare": return "Cloudflare"
    if "x-goog-generation" in h or "x-guploader-uploadid" in h or "google" in srv: return "Google Cloud Storage"
    if "x-amz-request-id" in h or srv == "amazons3": return "Amazon S3"
    if "x-ms-request-id" in h or "windows-azure" in srv: return "Azure Blob Storage"
    if "x-served-by" in h and "cache-" in h.get("x-served-by", ""): return "Fastly"
    if "akamai" in srv or "x-akamai-transformed" in h: return "Akamai"
    if "x-bunny" in " ".join(h) or "bunnycdn" in srv: return "BunnyCDN"
    if "x-vercel-id" in h: return "Vercel"
    if "x-nf-request-id" in h: return "Netlify"
    return h.get("server", "") or "unknown"


TELEMETRY = re.compile(r"sentry|google-analytics|googletagmanager|doubleclick|segment\.|hotjar|mixpanel|amplitude|"
                       r"clarity\.ms|facebook|datadog|newrelic|/collect|/track|/beacon|/views$", re.I)


def classify(url, ctype):
    e = ext_of(url)
    low = url.lower()
    name = urlsplit(url).path.rsplit("/", 1)[-1].lower()
    if e == "binz":
        return "model", ("Sketchfab geometry (compressed .binz)" if name.startswith("model_file")
                         else "Sketchfab scene graph (compressed .binz)")
    if e in MODEL_EXT or ctype.startswith("model/"):
        return "model", MODEL_EXT.get(e, ctype)
    if e in TEXTURE_EXT:
        return "texture", TEXTURE_EXT[e]
    for key, label in DECODERS.items():
        if key in low and (e in ("js", "wasm") or "wasm" in ctype or "javascript" in ctype):
            return "decoder", label
    if TELEMETRY.search(low):
        return None, None
    if ("json" in ctype and e != "json") or "/api/" in low or "graphql" in low:
        return "api", "JSON API"
    return None, None


def sketchfab_embed(url):
    """Sketchfab model pages only load the 3D scene after 'Play'. The official embed
    URL with autostart=1 starts the viewer straight away (documented embed option)."""
    m = re.search(r"sketchfab\.com/(?:3d-models/[^/?#]*-|models/)([0-9a-f]{32})", url)
    return f"https://sketchfab.com/models/{m.group(1)}/embed?autostart=1&ui_infos=0" if m else url


WAKE_JS = r"""() => {
  // 1) scroll through the page so lazy-loaded viewers start
  window.scrollTo(0, document.body.scrollHeight / 2); window.scrollTo(0, 0);
  // 2) press buttons that start a 3D view. Never follow links to other pages.
  const want = /(view|open|show|load|launch|start|explore|see)\s*(in\s*)?(3d|model|viewer|ar)|^\s*3d\s*(view)?\s*$|3d\s*view|^\s*play\s*$|click to (load|view|interact)|tap to (load|view)/i;
  const els = [...document.querySelectorAll('button,[role=button],a[href^="#"],a:not([href]),div[onclick],span[onclick]')];
  let n = 0;
  for (const el of els) {
    const label = (el.innerText || el.getAttribute('aria-label') || el.title || '').trim().slice(0, 60);
    const r = el.getBoundingClientRect();
    if (n < 3 && label && want.test(label) && r.width > 0 && r.height > 0) { el.click(); n++; }
  }
  // 3) report the biggest canvas so Python can click it (some viewers start on click)
  let best = null;
  for (const c of document.querySelectorAll('canvas')) {
    const r = c.getBoundingClientRect();
    if (r.width * r.height > 40000 && (!best || r.width * r.height > best.w * best.h))
      best = {x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height};
  }
  return {clicked: n, canvas: best};
}"""


def wake_viewers(page):
    """Universal: start viewers that wait for scrolling / a button / a click.
    Returns True if anything was triggered."""
    triggered = False
    for fr in page.frames:
        try:
            r = fr.evaluate(WAKE_JS)
            triggered |= r["clicked"] > 0
            if fr is page.main_frame and r["canvas"]:
                page.mouse.click(r["canvas"]["x"], r["canvas"]["y"])
                page.mouse.move(r["canvas"]["x"] + 40, r["canvas"]["y"] + 20)
                triggered = True
        except Exception:
            pass
    return triggered


def inspect(url):
    records, decoders, apis, images = [], {}, {}, []
    url = sketchfab_embed(url)
    with sync_playwright() as p:
        # Real GPU first: sites like Sketchfab test the browser and serve a still image
        # instead of live 3D when they only get software rendering.
        try:
            browser = p.chromium.launch(executable_path=BRAVE, headless=True,
                                        args=["--use-angle=vulkan", "--enable-features=Vulkan",
                                              "--ignore-gpu-blocklist", "--enable-gpu"])
        except Exception:
            browser = p.chromium.launch(executable_path=BRAVE, headless=True,
                                        args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                              "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        def on_response(resp):
            try:
                req = resp.request
                ctype = (resp.headers.get("content-type") or "").split(";")[0].lower()
                size = int(resp.headers.get("content-length") or 0)
                if req.resource_type == "image":
                    images.append((urlsplit(resp.url).netloc, size))
                    return
                kind, label = classify(resp.url, ctype)
                if not kind and req.resource_type in ("fetch", "xhr") and size > 50_000 and \
                        ("octet-stream" in ctype or "binary" in ctype or not ctype):
                    kind, label = "model", "custom binary (probably geometry)"
                if not kind:
                    return
                if kind == "decoder":
                    decoders[label] = urlsplit(resp.url).netloc
                    return
                if kind == "api":
                    if req.resource_type in ("fetch", "xhr"):
                        apis.setdefault(api_pattern(resp.url), resp.status)
                    return
                rh = req.headers
                q = parse_qs(urlsplit(resp.url).query)
                records.append({
                    "kind": kind, "format": label, "where": short(resp.url),
                    "status": resp.status, "ctype": ctype or "-",
                    "size": size,
                    "encoding": resp.headers.get("content-encoding", "none"),
                    "cdn": cdn_of(resp.headers),
                    "cache": resp.headers.get("cache-control", "-"),
                    "cors": resp.headers.get("access-control-allow-origin", "-"),
                    "signed": ", ".join(sorted(k for k in q if SIGNED_KEYS.search(k))) or "no",
                    "auth": ("Authorization header" if "authorization" in rh else
                             "cookies" if "cookie" in rh else "none"),
                    "via": req.resource_type,
                })
            except Exception:
                pass

        page.on("response", on_response)
        t0 = time.time()
        try:
            page.goto(url, wait_until="load", timeout=60000)
        except Exception as e:
            print(f"Page load problem: {e}", file=sys.stderr)
        page.wait_for_timeout(WAIT_AFTER_LOAD * 1000)
        if wake_viewers(page):
            page.wait_for_timeout(8000)  # give a just-started viewer time to fetch its files
        try:
            found = page.evaluate(DETECT_JS)
            for fr in page.frames[1:]:
                try:
                    sub = fr.evaluate(DETECT_JS)
                    found["libs"].update(sub["libs"]); found["webgl"] += sub["webgl"]; found["webgl2"] += sub["webgl2"]
                    found["scripts"] = list(dict.fromkeys(found["scripts"] + sub["scripts"]))[:15]
                except Exception:
                    pass
        except Exception:
            found = {"blocked": False, "libs": {}, "embeds": [], "webgl": 0, "webgl2": 0, "scripts": [], "title": ""}
        shot = REPORTS / f"shot-{int(t0)}.png"
        REPORTS.mkdir(exist_ok=True)
        try:
            page.screenshot(path=str(shot))
        except Exception:
            shot = None
        browser.close()
    # textures = images served from the same hosts as the model files
    model_hosts = {r["where"].split("/")[0] for r in records}
    found["textures"] = [s for h, s in images if h in model_hosts]
    found["fallback"] = any(k.rstrip("/").endswith("fallback") for k in apis)
    return found, records, decoders, apis, shot, time.time() - t0


def human(n):
    if not n:
        return "streamed / unknown"
    return f"{n/1048576:.1f} MB" if n >= 1048576 else f"{n/1024:.0f} KB" if n >= 1024 else f"{n} bytes"


def summary(found, records, decoders):
    lines = []
    if found.get("blocked"):
        return ["This site blocked automated inspection (bot-protection / 'are you human' page), so nothing about "
                "its 3D delivery could be seen. Open the page in your own browser and use F12 > Network instead."]
    libs = found["libs"]
    if libs:
        lines.append("Drawn with " + ", ".join(f"{k} {v}" for k, v in libs.items()) + ".")
    elif found["embeds"]:
        lines.append("The 3D view is an embedded third-party viewer: " + ", ".join(found["embeds"]) +
                     " (the model lives on that service, not on this site).")
    elif found["webgl"] or found["webgl2"]:
        lines.append("A WebGL canvas is active, but the engine hides its name (bundled/minified build).")
    else:
        lines.append("No WebGL canvas or known 3D viewer found - the model may load only after a click, "
                     "or this page shows images/video instead of live 3D.")
    models = [r for r in records if r["kind"] == "model"]
    if models:
        fmts = sorted({r["format"] for r in models})
        cdns = sorted({r["cdn"] for r in models})
        lines.append(f"{len(models)} model file(s) loaded as {', '.join(fmts)}, stored on {', '.join(cdns)}.")
        if any(r["signed"] != "no" for r in models):
            lines.append("Files are served through signed, expiring links (access decided per request by the backend).")
        if any(r["auth"] != "none" for r in models):
            lines.append("File requests carry the visitor's login (cookies/token).")
    elif libs or found["webgl"] or found["webgl2"]:
        lines.append("No standard 3D file was requested - geometry is likely in a custom/obfuscated format, "
                     "packed in a .bin or streamed in chunks.")
    tex = found.get("textures") or []
    if tex:
        sized = [t for t in tex if t]
        rng = f" ({human(min(sized))} to {human(max(sized))})" if sized else ""
        lines.append(f"{len(tex)} texture image(s){rng} loaded from the same storage as the model.")
        api_tex = found.get("api_textures")
        if isinstance(api_tex, int) and api_tex and len(tex) > api_tex:
            lines.append(f"The platform lists {api_tex} textures but the viewer fetched {len(tex)} images, so textures "
                         "arrive in several resolutions - progressive loading (low-res first, sharper later).")
    if found.get("fallback") and not models:
        lines.append("The site served its 'fallback' (a still image instead of live 3D) because it judged this "
                     "browser unable to run the 3D viewer - a capability check worth mentioning.")
    if decoders:
        lines.append("Compression: " + ", ".join(decoders) + " (decoded in the browser with WebAssembly).")
    return lines


def report(url, found, records, decoders, apis, shot, secs, extra=None):
    """extra = [(section, [(label, value), ...]), ...] e.g. Sketchfab Data API facts"""
    host = urlsplit(url).netloc
    extra_html = "".join(
        f"<h2>Sketchfab · {escape(sec)}</h2><table>" +
        "".join(f"<tr><th style='width:280px'>{escape(str(k))}</th><td>{escape(str(v))}</td></tr>" for k, v in rows) +
        "</table>" for sec, rows in (extra or []))
    rows = "".join(
        f"<tr><td>{escape(r['kind'])}</td><td>{escape(r['format'])}</td><td><code>{escape(r['where'])}</code></td>"
        f"<td>{human(r['size'])}</td><td>{escape(r['encoding'])}</td><td>{escape(r['cdn'])}</td>"
        f"<td>{escape(r['signed'])}</td><td>{escape(r['auth'])}</td><td>{escape(r['cors'])}</td>"
        f"<td>{escape(r['cache'])}</td><td>{escape(r['via'])}</td></tr>" for r in records)
    li = lambda xs: "".join(f"<li>{escape(x)}</li>" for x in xs) or "<li>none found</li>"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Inspector – {escape(host)}</title>
<style>body{{font-family:system-ui;background:#14171c;color:#e8e6e1;margin:24px;max-width:1300px}}
h1{{font-size:22px}} h2{{font-size:16px;color:#c8b089;margin-top:28px}} code{{color:#9fd3ff}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border:1px solid #2f3540;padding:6px;text-align:left;vertical-align:top}}
th{{background:#1e2229}} .sum li{{margin:6px 0;font-size:15px}} img{{max-width:100%;border:1px solid #2f3540;margin-top:8px}}
.muted{{color:#9aa0a8;font-size:13px}}</style></head><body>
<h1>How <code>{escape(host)}</code> delivers its 3D model</h1>
<p class="muted">{escape(found.get('title',''))} · inspected {datetime.now():%Y-%m-%d %H:%M} in {secs:.0f}s · {escape(url)}</p>
<h2>Summary</h2><ul class="sum">{li(summary(found, records, decoders))}</ul>
{extra_html}
<h2>1 · How it is made visible (client side)</h2>
<ul>{li([f"{k}: {v}" for k, v in found['libs'].items()])}</ul>
<p>WebGL canvases: {found['webgl']} WebGL1, {found['webgl2']} WebGL2 · Embedded viewers: {escape(', '.join(found['embeds']) or 'none')}</p>
<p class="muted">Viewer-related scripts: {escape(', '.join(found['scripts']) or 'none detected')}</p>
<h2>2 · How it is stored and delivered (files)</h2>
<table><tr><th>Type</th><th>Format</th><th>Stored at</th><th>Size</th><th>Transfer compression</th><th>CDN / storage</th>
<th>Signed link</th><th>Login sent</th><th>CORS</th><th>Caching</th><th>Loaded via</th></tr>{rows or '<tr><td colspan=11>No 3D files or textures seen</td></tr>'}</table>
<h2>3 · Compression decoders</h2><ul>{li([f"{k} (from {v})" for k, v in decoders.items()])}</ul>
<h2>4 · API calls feeding the page (catalogue / metadata)</h2><ul>{li([f"{k}  → HTTP {v}" for k, v in list(apis.items())[:30]])}</ul>
<h2>What the page looked like</h2>{f'<img src="{shot.name}">' if shot else '<p>no screenshot</p>'}
<p class="muted">Architecture report only: file contents are not read or saved, and file links are shortened to host + format.</p>
</body></html>"""
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"{re.sub(r'[^a-zA-Z0-9.]+', '_', host)}-{datetime.now():%Y%m%d-%H%M%S}.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].startswith(("http://", "https://")):
        sys.exit("Usage: inspect_site.py <http(s) link>")
    found, records, decoders, apis, shot, secs = inspect(sys.argv[1])
    for line in summary(found, records, decoders):
        print(line)
    extra = None
    try:
        import sketchfab
        extra = sketchfab.facts(sys.argv[1])
        for sec, rows in extra or []:
            for k, v in rows:
                if k == "Textures" and str(v).replace(",", "").isdigit():
                    found["api_textures"] = int(str(v).replace(",", ""))
    except Exception as e:
        print(f"(Sketchfab API not available: {e})", file=sys.stderr)
    print(f"Report: {report(sys.argv[1], found, records, decoders, apis, shot, secs, extra)}")
