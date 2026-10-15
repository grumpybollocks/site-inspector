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
import json
import re
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from playwright.sync_api import sync_playwright

BRAVE = "/usr/bin/brave"
BROWSERS = ["Auto", "Brave", "Chromium", "Firefox"]   # Chromium/Firefox = Playwright's own builds
REPORTS = Path(__file__).resolve().parent / "reports"
WAIT_AFTER_LOAD = 10  # seconds for viewers that load the model after the page

MODEL_EXT = {"glb": "glTF binary", "gltf": "glTF JSON", "bin": "binary buffer (.bin, usually glTF)", "drc": "Draco mesh",
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
  if (window.v3d) { delete out['three.js']; out['Verge3D (built on a three.js fork)'] = (v3d.REVISION ? 'r' + v3d.REVISION : '?'); }
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
  // read the context type the GPU probe recorded - never call getContext() here, that would
  // create a brand-new context on unused canvases and distort the numbers
  let gl = 0, gl2 = 0;
  for (const c of document.querySelectorAll('canvas')) {
    const t = c.__siCtx || '';
    if (t === 'webgl2') gl2++; else if (/webgl/.test(t)) gl++;
  }
  const scripts = [...document.scripts].map(s => s.src).filter(Boolean)
     .filter(s => /three|babylon|model-viewer|playcanvas|cesium|draco|meshopt|unity|splat|viewer|webgl/i.test(s))
     .map(s => { const u = new URL(s); return u.host + '/' + u.pathname.split('/').pop(); });
  const txt = (document.body && document.body.innerText || '').slice(0, 3000);
  const blocked = /access (is )?(temporarily )?(restricted|denied)|just a moment|verify you are human|unusual activity|captcha|are you a robot/i.test(document.title + ' ' + txt);
  // links on this site that look like a single model's page (used when this page itself shows no 3D)
  const norm = h => h.split('#')[0].replace(/\/+$/, '');
  const here = norm(location.href);
  const site = location.hostname.replace(/^www\./, '');
  const want = /(model|3d|object|objekt|item|sample|viewer|detail|artifact|artefact|scan|asset|product|exhibit|specimen|example|showcase)/i;
  const skip = /(login|signin|sign-in|signup|register|cart|checkout|account|privacy|cookie|terms|contact|about|faq|help|blog|news|search|tags?\/|category|mailto:|javascript:|\.(pdf|zip|jpg|png)$)/i;
  // tier 1: links whose address says "model / object / 3d / sample ..."
  // tier 2 (any wording, e.g. /wardrobe.html): links that wrap a thumbnail image = a gallery grid
  const home = /^\/?([a-z]{2}(-[a-z]{2})?\/?)?(index\.html?|home\/?)?$/i;   // "/", "/en/", "/index.html"
  const seen = new Set(), candidates = [];
  for (const a of document.querySelectorAll('a[href]')) {
    let u; try { u = new URL(a.href); } catch (e) { continue; }
    const href = u.href.split('#')[0];
    if (!/^https?:/.test(u.protocol) || !u.hostname.endsWith(site) || norm(href) === here || seen.has(norm(href))) continue;
    if (skip.test(href) || home.test(u.pathname)) continue;
    const thumb = !!a.querySelector('img,picture,canvas,video') ||
                  /url\(/.test(getComputedStyle(a).backgroundImage || '');
    const keyword = want.test(u.pathname + u.search);
    if (!keyword && !thumb) continue;
    seen.add(norm(href));
    const score = (keyword ? 3 : 0) + (thumb ? 2 : 0) + Math.min(u.pathname.split('/').filter(Boolean).length, 4) / 4;
    candidates.push({href, score});
  }
  candidates.sort((x, y) => y.score - x.score);
  return {candidates: candidates.slice(0, 5).map(c => c.href), blocked, libs: out, embeds: [...new Set(embeds)], webgl: gl, webgl2: gl2, scripts: [...new Set(scripts)].slice(0, 15),
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
    return f"own web server ({h['server']})" if h.get("server") else "own web server"


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


# CATCH-ALL: runs in every frame before the site's own code. Whatever engine a site uses,
# it must hand geometry and textures to WebGL/WebGPU to draw them, so counting those calls
# describes ANY 3D site, even an unknown in-house engine. Only counts and sizes are kept,
# never the data itself.
GPU_PROBE_JS = r"""(() => {
  if (window.__si) return;
  const S = window.__si = {ctx: {}, buffers: 0, bufferBytes: 0, textures: 0, programs: 0,
                           draws: 0, instanced: 0, frames: 0, webgpu: false, webgpuDevice: false, wasm: 0, workers: 0};
  const gc = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, ...a) {
    const c = gc.call(this, type, ...a);
    if (c && /webgl|webgpu/i.test(type) && !this.__siCtx) { this.__siCtx = type; S.ctx[type] = (S.ctx[type] || 0) + 1; }
    return c;
  };
  if (window.OffscreenCanvas) {
    const og = OffscreenCanvas.prototype.getContext;
    OffscreenCanvas.prototype.getContext = function (type, ...a) {
      const c = og.call(this, type, ...a);
      if (c && /webgl|webgpu/i.test(type)) S.ctx['offscreen ' + type] = (S.ctx['offscreen ' + type] || 0) + 1;
      return c;
    };
  }
  const size = d => typeof d === 'number' ? d : (d && d.byteLength) || 0;
  for (const C of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {
    if (!C) continue;
    const p = C.prototype, wrap = (name, fn) => { const o = p[name]; if (o) p[name] = function (...a) { fn(a); return o.apply(this, a); }; };
    wrap('bufferData', a => { S.buffers++; S.bufferBytes += size(a[1]); });
    wrap('texImage2D', () => S.textures++);
    wrap('texImage3D', () => S.textures++);
    wrap('compressedTexImage2D', () => S.textures++);
    wrap('texStorage2D', () => S.textures++);
    wrap('linkProgram', () => S.programs++);
    wrap('drawElements', () => S.draws++);
    wrap('drawArrays', () => S.draws++);
    wrap('drawElementsInstanced', () => { S.draws++; S.instanced++; });
    wrap('drawArraysInstanced', () => { S.draws++; S.instanced++; });
  }
  if (navigator.gpu && navigator.gpu.requestAdapter) {
    const ra = navigator.gpu.requestAdapter.bind(navigator.gpu);
    navigator.gpu.requestAdapter = (...a) => { S.webgpu = true; return ra(...a).then(ad => {
      if (ad) { const rd = ad.requestDevice.bind(ad); ad.requestDevice = (...b) => { S.webgpuDevice = true; return rd(...b); }; }
      return ad; }); };
  }
  // WebGPU: the newer graphics API - same idea, different calls
  const wrapP = (C, name, fn) => { if (C && C.prototype[name]) { const o = C.prototype[name];
    C.prototype[name] = function (...a) { try { fn(a); } catch (e) {} return o.apply(this, a); }; } };
  wrapP(window.GPUDevice, 'createBuffer', a => { S.buffers++; S.bufferBytes += (a[0] && a[0].size) || 0; });
  wrapP(window.GPUDevice, 'createTexture', () => S.textures++);
  wrapP(window.GPUDevice, 'createRenderPipeline', () => S.programs++);
  wrapP(window.GPUDevice, 'createRenderPipelineAsync', () => S.programs++);
  for (const E of [window.GPURenderPassEncoder, window.GPURenderBundleEncoder]) {
    wrapP(E, 'draw', a => { S.draws++; if (a[1] > 1) S.instanced++; });
    wrapP(E, 'drawIndexed', a => { S.draws++; if (a[1] > 1) S.instanced++; });
    wrapP(E, 'drawIndirect', () => S.draws++);
    wrapP(E, 'drawIndexedIndirect', () => S.draws++);
  }
  for (const k of ['instantiate', 'instantiateStreaming', 'compile', 'compileStreaming']) {
    const o = WebAssembly[k]; if (o) WebAssembly[k] = function (...a) { S.wasm++; return o.apply(this, a); };
  }
  const W = window.Worker; if (W) window.Worker = function (...a) { S.workers++; return new W(...a); };
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = cb => raf(t => { S.frames++; return cb(t); });
})();"""

GPU_READ_JS = "() => window.__si ? JSON.parse(JSON.stringify(window.__si)) : null"


def gpu_stats(page):
    """Sum the probe counters over all frames, and measure draw calls per frame over 2 s."""
    def total():
        t = {"ctx": {}, "buffers": 0, "bufferBytes": 0, "textures": 0, "programs": 0, "draws": 0,
             "instanced": 0, "frames": 0, "webgpu": False, "webgpuDevice": False, "wasm": 0, "workers": 0}
        for fr in page.frames:
            try:
                s = fr.evaluate(GPU_READ_JS)
            except Exception:
                s = None
            if not s:
                continue
            for k, v in s.items():
                if k == "ctx":
                    for ck, cv in v.items():
                        t["ctx"][ck] = t["ctx"].get(ck, 0) + cv
                elif isinstance(v, bool):
                    t[k] = t[k] or v
                else:
                    t[k] += v
        return t
    a = total()
    page.wait_for_timeout(2000)
    b = total()
    frames = b["frames"] - a["frames"]
    b["fps"] = round(frames / 2)
    # no frames seen = rendering off the main thread (worker / OffscreenCanvas / XR): per-frame unknown
    b["draws_per_frame"] = round((b["draws"] - a["draws"]) / frames) if frames else None
    b["frames"] = frames
    return b


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


GPU_ARGS = ["--use-angle=vulkan", "--enable-features=Vulkan", "--ignore-gpu-blocklist", "--enable-gpu"]
SOFT_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
# Assisted mode keeps its own profile (never the user's real Brave profile), so a human check
# the user passes there is remembered for next time.
ASSISTED_PROFILE = Path.home() / ".cache" / "site-inspector-profile"


def open_browser(p, which, assisted):
    """Returns (browser or None, context, name used). 'Auto' = Brave if installed, else Playwright Chromium."""
    which = (which or "Auto").capitalize()
    if which == "Auto":
        which = "Brave" if Path(BRAVE).exists() else "Chromium"
    if which == "Firefox":
        kind, opts = p.firefox, {}
    else:
        kind = p.chromium
        opts = {"executable_path": BRAVE} if which == "Brave" else {}
    if assisted:   # visible window, own profile per browser (never the user's real profile)
        prof = ASSISTED_PROFILE / which.lower()
        prof.mkdir(parents=True, exist_ok=True)
        extra = {} if which == "Firefox" else {"args": GPU_ARGS}
        return None, kind.launch_persistent_context(str(prof), headless=False, no_viewport=True, **opts, **extra), which
    # Real GPU first: sites like Sketchfab test the browser and serve a still image
    # instead of live 3D when they only get software rendering.
    if which == "Firefox":
        browser = kind.launch(headless=True)
    else:
        try:
            browser = kind.launch(headless=True, args=GPU_ARGS, **opts)
        except Exception:
            browser = kind.launch(headless=True, args=SOFT_ARGS, **opts)
    return browser, browser.new_context(viewport={"width": 1400, "height": 900}), which


def inspect(url, assisted=False, ready=None, on_waiting=None, browser_name="Auto"):
    """assisted=True: open a VISIBLE browser, the user browses / passes any human check
    themselves, and the analysis starts when `ready` (threading.Event) is set."""
    records, decoders, apis, images = [], {}, {}, []
    seen = set()
    url = sketchfab_embed(url)
    with sync_playwright() as p:
        t0 = time.time()
        browser, ctx, used = open_browser(p, browser_name, assisted)
        ctx.add_init_script(GPU_PROBE_JS)   # catch-all GPU probe, injected into every frame of every tab
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        wasm = {}

        def on_response(resp):
            try:
                req = resp.request
                ctype = (resp.headers.get("content-type") or "").split(";")[0].lower()
                size = int(resp.headers.get("content-length") or 0)
                if req.resource_type == "image":
                    images.append((urlsplit(resp.url).netloc, size))
                    return
                if "wasm" in ctype or ext_of(resp.url) == "wasm":
                    wasm[urlsplit(resp.url).path.rsplit("/", 1)[-1][:60]] = size
                kind, label = classify(resp.url, ctype)
                if not kind and req.resource_type in ("fetch", "xhr") and size > 50_000 and \
                        ("octet-stream" in ctype or "binary" in ctype or not ctype):
                    kind, label = "model", "custom binary (probably geometry)"
                if not kind:
                    return
                if kind == "decoder":
                    decoders[label] = urlsplit(resp.url).netloc
                    return
                if resp.url in seen:      # the same file requested twice = one file
                    return
                seen.add(resp.url)
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
                    "t": round(time.time() - t0, 2),   # seconds after start, for the load timeline
                })
            except Exception:
                pass

        ctx.on("response", on_response)   # all tabs, so it also follows wherever the user clicks
        try:
            page.goto(url, wait_until="load", timeout=60000)
        except Exception as e:
            print(f"Page load problem: {e}", file=sys.stderr)
        if assisted:
            if on_waiting:
                on_waiting()
            closed = False
            for _ in range(1800):              # the user says "page is ready" (max 30 min)
                if ready is None or ready.wait(timeout=1):
                    break
                if not ctx.pages:              # user closed the browser window instead
                    closed = True
                    break
            if closed:
                ctx.close()
                if browser:
                    browser.close()
                raise RuntimeError("The browser window was closed before “Page is ready” was pressed.")
            page = ctx.pages[-1]               # analyse the tab they ended on
            page.wait_for_timeout(3000)
        else:
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
            found = {"candidates": [], "blocked": False, "libs": {}, "embeds": [], "webgl": 0, "webgl2": 0, "scripts": [], "title": ""}
        try:
            found["gpu"] = gpu_stats(page)
        except Exception:
            found["gpu"] = None
        found["wasm"] = wasm
        k, fmt = classify(url, "")
        found["direct_file"] = fmt if k == "model" else None   # the link itself is a 3D file, not a page
        found["browser"] = used + (" (visible, assisted)" if assisted else " (hidden)")
        shot = REPORTS / f"shot-{int(t0)}.png"
        REPORTS.mkdir(exist_ok=True)
        try:
            page.screenshot(path=str(shot))
        except Exception:
            shot = None
        ctx.close()
        if browser:
            browser.close()
    # textures = images served from the same hosts as the model files
    model_hosts = {r["where"].split("/")[0] for r in records}
    found["textures"] = [s for h, s in images if h in model_hosts]
    found["fallback"] = any(k.rstrip("/").endswith("fallback") for k in apis)
    return found, records, decoders, apis, shot, time.time() - t0


def shows_3d(found, records):
    g = found.get("gpu") or {}
    return bool(found.get("libs") or found.get("embeds") or found.get("webgl") or found.get("webgl2")
                or g.get("draws") or g.get("buffers") or any(r["kind"] == "model" for r in records))


def inspect_smart(url, assisted=False, ready=None, on_waiting=None, browser_name="Auto", on_status=None):
    """inspect(), and if the pasted page is a gallery / index with no 3D on it, open the most
    model-looking page linked from it on the same site and inspect that instead (up to 3 tries)."""
    result = inspect(url, assisted, ready, on_waiting, browser_name)
    found, records = result[0], result[1]
    if assisted or found.get("blocked") or found.get("direct_file") or shows_3d(found, records):
        return result + (url,)
    same = lambda a, b: a.split("#")[0].rstrip("/") == b.split("#")[0].rstrip("/")
    cands = [c for c in (found.get("candidates") or []) if not same(c, url)][:3]
    for cand in cands:
        if on_status:
            on_status(f"No 3D on that page - it looks like a gallery. Trying a model page on the same site: {cand}"
                      if cand == cands[0] else f"No 3D there either. Trying another one: {cand}")
        r2 = inspect(cand, False, None, None, browser_name)
        if shows_3d(r2[0], r2[1]):
            r2[0]["explored_from"] = url
            return r2 + (cand,)
    return result + (url,)


def human(n):
    if not n:
        return "streamed / unknown"
    return f"{n/1048576:.1f} MB" if n >= 1048576 else f"{n/1024:.0f} KB" if n >= 1024 else f"{n} bytes"


def gpu_active(found):
    g = found.get("gpu")
    return bool(g and (g["buffers"] or g["draws"] or g["webgpuDevice"]))


def summary(found, records, decoders):
    lines = []
    if found.get("blocked"):
        return ["This site blocked automated inspection (bot-protection / 'are you human' page), so nothing about "
                "its 3D delivery could be seen. Open the page in your own browser and use F12 > Network instead."]
    if found.get("explored_from"):
        lines.append(f"The link you pasted ({found['explored_from']}) is a gallery/index page with no 3D on it, so the "
                     "inspector opened a model page linked from it on the same site and analysed that one.")
    if found.get("direct_file"):
        return [f"This link points straight at a 3D file ({found['direct_file']}), not at a web page. Paste the link "
                "of the page that SHOWS the model (model page, product page, viewer) to see how a site displays and "
                "delivers it."]
    libs = found["libs"]
    if libs:
        lines.append("Drawn with " + ", ".join(f"{k} {v}" for k, v in libs.items()) + ".")
    elif found["embeds"]:
        lines.append("The 3D view is an embedded third-party viewer: " + ", ".join(found["embeds"]) +
                     " (the model lives on that service, not on this site).")
    elif found["webgl"] or found["webgl2"] or gpu_active(found):
        lines.append("Unknown or in-house 3D engine (no public library name) - identified by the GPU catch-all below.")
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
        rng = "" if not sized else f" ({human(min(sized))})" if min(sized) == max(sized) else \
            f" ({human(min(sized))} to {human(max(sized))})"
        lines.append(f"{len(tex)} texture image(s){rng} loaded from the same storage as the model.")
        api_tex = found.get("api_textures")
        if isinstance(api_tex, int) and api_tex and len(tex) > api_tex:
            lines.append(f"The platform lists {api_tex} textures but the viewer fetched {len(tex)} images, so textures "
                         "arrive in several resolutions - progressive loading (low-res first, sharper later).")
    if found.get("fallback") and not models:
        lines.append("The site served its 'fallback' (a still image instead of live 3D) because it judged this "
                     "browser unable to run the 3D viewer - a capability check worth mentioning.")
    g = found.get("gpu")
    if gpu_active(found):
        api = "WebGPU" if g["webgpuDevice"] else "WebGL"
        per_frame = (f"~{g['draws_per_frame']} draw calls per frame at ~{g['fps']} fps" if g.get("frames")
                     else "rendering runs off the main thread (worker/OffscreenCanvas), so per-frame numbers are not visible")
        lines.append(f"GPU catch-all ({api}): {g['buffers']} geometry/data buffers ({human(g['bufferBytes'])}) and "
                     f"{g['textures']} textures uploaded, {g['programs']} shader programs/pipelines, " + per_frame
                     + (f", {g['instanced']} instanced draws (GPU instancing)" if g["instanced"] else "") + ".")
        if g["draws"] and g.get("frames") and not g["draws_per_frame"]:
            lines.append("It renders on demand: the scene is redrawn only when the view changes, not every frame "
                         "(saves battery and GPU while the model sits still).")
    if found.get("wasm"):
        lines.append("WebAssembly modules (decoders / engine core): " + ", ".join(found["wasm"]) + ".")
    if decoders:
        lines.append("Compression: " + ", ".join(decoders) + " (decoded in the browser with WebAssembly).")
    return lines


def gpu_table(found):
    g = found.get("gpu")
    if not g:
        return "<p>no data</p>"
    rows = [("Graphics contexts", ", ".join(f"{k} ×{v}" for k, v in g["ctx"].items()) or "none"),
            ("WebGPU", "device created" if g["webgpuDevice"] else "adapter requested only" if g["webgpu"] else "not used"),
            ("Geometry / data buffers uploaded", f"{g['buffers']:,}  ({human(g['bufferBytes'])})"),
            ("Textures uploaded", f"{g['textures']:,}"), ("Shader programs linked", f"{g['programs']:,}"),
            ("Draw calls per frame", (f"~{g['draws_per_frame']:,}" if g.get("frames") else "n/a (renders off the main thread)")
             + f"  (instanced draws total: {g['instanced']:,})"),
            ("Frame rate while inspected", f"~{g['fps']} fps"),
            ("WebAssembly modules", f"{g['wasm']} instantiated · files: " + (", ".join(found.get('wasm') or {}) or "none")),
            ("Web workers started", f"{g['workers']}")]
    return "<table>" + "".join(f"<tr><th style='width:280px'>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows) + "</table>"


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
    import extras
    sum_lines = summary(found, records, decoders)
    score, tips = extras.lessons(found, records, decoders)
    icon = {"ok": "✅", "tip": "💡", "info": "ℹ️"}
    lessons_html = (f"<p style='font-size:18px'>Score: <b style='color:#c8b089'>{score}/100</b> "
                    f"<span class='muted'>(how many good practices this site uses)</span></p>" if score is not None else "") + \
        "<table>" + "".join(f"<tr><th style='width:280px'>{icon[st]} {escape(t)}</th><td>{escape(d)}</td></tr>"
                            for st, t, d in tips) + "</table>"
    text_for_terms = " ".join(sum_lines) + " " + " ".join(f"{r['format']} {r['cdn']} {r['signed']} {r['cors']}" for r in records) \
        + " " + " ".join(decoders) + " " + " ".join(found.get("libs", {})) + (" API" if apis else "") + " draw call shader"
    gloss_html = "<table>" + "".join(f"<tr><th style='width:220px'>{escape(t)}</th><td>{escape(e)}</td></tr>"
                                     for t, e in extras.glossary(text_for_terms)) + "</table>"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Inspector – {escape(host)}</title>
<style>body{{font-family:system-ui;background:#14171c;color:#e8e6e1;margin:24px;max-width:1300px}}
h1{{font-size:22px}} h2{{font-size:16px;color:#c8b089;margin-top:28px}} code{{color:#9fd3ff}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border:1px solid #2f3540;padding:6px;text-align:left;vertical-align:top}}
th{{background:#1e2229}} .sum li{{margin:6px 0;font-size:15px}} img{{max-width:100%;border:1px solid #2f3540;margin-top:8px}}
.muted{{color:#9aa0a8;font-size:13px}}</style></head><body>
<h1>How <code>{escape(host)}</code> delivers its 3D model</h1>
<p class="muted">{escape(found.get('title',''))} · inspected {datetime.now():%Y-%m-%d %H:%M} in {secs:.0f}s · {escape(url)}</p>
<p class="muted">Browser used: {escape(found.get('browser', '?'))}</p>
<h2>Architecture at a glance</h2>{extras.diagram_svg(found, records, decoders, apis)}
<h2>Summary</h2><ul class="sum">{li(sum_lines)}</ul>
<h2>Lessons for your own site</h2>{lessons_html}
{extra_html}
<h2>1 · How it is made visible (client side)</h2>
<ul>{li([f"{k}: {v}" for k, v in found['libs'].items()])}</ul>
<p>WebGL canvases: {found['webgl']} WebGL1, {found['webgl2']} WebGL2 · Embedded viewers: {escape(', '.join(found['embeds']) or 'none')}</p>
<p class="muted">Viewer-related scripts: {escape(', '.join(found['scripts']) or 'none detected')}</p>
<h2>2 · How it is stored and delivered (files)</h2>
<table><tr><th>Type</th><th>Format</th><th>Stored at</th><th>Size</th><th>Transfer compression</th><th>CDN / storage</th>
<th>Signed link</th><th>Login sent</th><th>CORS</th><th>Caching</th><th>Loaded via</th></tr>{rows or '<tr><td colspan=11>No 3D files or textures seen</td></tr>'}</table>
<h2>Catch-all · what the GPU received (works for any engine)</h2>
{gpu_table(found)}
<h2>Load timeline</h2>{extras.timeline_html(records)}
<h2>3 · Compression decoders</h2><ul>{li([f"{k} (from {v})" for k, v in decoders.items()])}</ul>
<h2>4 · API calls feeding the page (catalogue / metadata)</h2><ul>{li([f"{k}  → HTTP {v}" for k, v in list(apis.items())[:30]])}</ul>
<h2>Glossary (terms used in this report)</h2>{gloss_html}
<h2>What the page looked like</h2>{f'<img src="{shot.name}">' if shot else '<p>no screenshot</p>'}
<p class="muted">Architecture report only: file contents are not read or saved, and file links are shortened to host + format.</p>
</body></html>"""
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"{re.sub(r'[^a-zA-Z0-9.]+', '_', host)}-{datetime.now():%Y%m%d-%H%M%S}.html"
    out.write_text(html, encoding="utf-8")
    # flat facts for the History list and Compare
    out.with_suffix(".json").write_text(
        json.dumps(extras.run_summary(url, host, found, records, decoders, apis, score, out), indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    assisted = "--assisted" in sys.argv[1:]
    bname = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--browser=")), "Auto")
    args = [a for a in sys.argv[1:] if a != "--assisted" and not a.startswith("--browser=")]
    if len(args) != 1 or not args[0].startswith(("http://", "https://")):
        sys.exit("Usage: inspect_site.py [--assisted] [--browser=Auto|Brave|Chromium|Firefox] <http(s) link>")
    sys.argv[1:] = args
    if assisted:
        import threading
        ev = threading.Event()
        found, records, decoders, apis, shot, secs = inspect(
            args[0], assisted=True, ready=ev, browser_name=bname,
            on_waiting=lambda: (input("Browse / pass any check in the window, then press Enter here... "), ev.set()))
    else:
        found, records, decoders, apis, shot, secs, used_url = inspect_smart(args[0], browser_name=bname, on_status=print)
        args[0] = used_url
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
    print(f"Report: {report(args[0], found, records, decoders, apis, shot, secs, extra)}")
