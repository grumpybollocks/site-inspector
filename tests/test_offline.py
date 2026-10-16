#!/usr/bin/env python3
"""
Offline tests: no network, no browser, ~1-2 s. Run after EVERY change:
    .venv/bin/python tests/test_offline.py
Each test pins down a behaviour (several are regressions of real bugs fixed before - see the comments).
"""
import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extras                 # noqa: E402
import inspect_site as core   # noqa: E402
import sketchfab              # noqa: E402

JS = "application/javascript"


def rec(**kw):
    """a 'record' like inspect() produces, with sane defaults"""
    r = {"kind": "model", "format": "glTF binary", "where": "cdn.example.com/…/*.glb", "status": 200,
         "ctype": "model/gltf-binary", "size": 2_000_000, "encoding": "none", "cdn": "Amazon CloudFront",
         "cache": "max-age=86400", "cors": "*", "signed": "no", "auth": "none", "via": "fetch", "t": 1.2}
    r.update(kw)
    return r


def found(**kw):
    """a 'found' dict like inspect() produces, with sane defaults"""
    f = {"libs": {"three.js": "r186"}, "embeds": [], "webgl": 0, "webgl2": 1, "scripts": [], "title": "Test page",
         "blocked": False, "candidates": [], "browser": "Brave (hidden)", "wasm": {}, "textures": [],
         "fallback": False, "direct_file": None,
         "gpu": {"ctx": {"webgl2": 1}, "buffers": 30, "bufferBytes": 500_000, "textures": 10, "programs": 5,
                 "draws": 300, "instanced": 0, "frames": 120, "fps": 60, "draws_per_frame": 2,
                 "webgpu": False, "webgpuDevice": False, "wasm": 0, "workers": 0}}
    f.update(kw)
    return f


# --- URL helpers --------------------------------------------------------------------------
def test_ext_of_looks_through_compression():
    assert core.ext_of("https://x/a/model_file.bin.gz") == "bin"
    assert core.ext_of("https://x/a/file.osgjs.gz") == "osgjs"
    assert core.ext_of("https://x/a/model.glb?v=3") == "glb"
    assert core.ext_of("https://x/a/") == ""


def test_short_never_returns_a_working_link():
    s = core.short("https://cdn.example.com/private/abc123/scene.glb?X-Amz-Signature=deadbeef")
    assert s == "cdn.example.com/…/*.glb" and "Signature" not in s and "abc123" not in s


def test_api_pattern_hides_ids():
    assert core.api_pattern("https://api.x.com/v3/models/8a32337fe2eb4d528f82021d44e13bc8") == "api.x.com/v3/models/{id}"


def test_sketchfab_links():
    u = "https://sketchfab.com/3d-models/akmn-8a32337fe2eb4d528f82021d44e13bc8"
    assert sketchfab.uid_of(u) == "8a32337fe2eb4d528f82021d44e13bc8"
    assert core.sketchfab_embed(u).endswith("/embed?autostart=1&ui_infos=0")
    assert core.sketchfab_embed("https://example.com/") == "https://example.com/"


# --- classification ---------------------------------------------------------------------
def test_decoders_match_file_names_only():
    # regression: "specific.js" / "pacific-app.js" used to be reported as an IFC (BIM) decoder
    assert core.classify("https://x/static/specific.js", JS) == (None, None)
    assert core.classify("https://x/js/pacific-app.js", JS) == (None, None)
    assert core.classify("https://x/libs/web-ifc.wasm", "application/wasm")[1] == "IFC (BIM) decoder"
    assert core.classify("https://x/draco/draco_decoder.wasm", "application/wasm")[1] == "Draco geometry compression"
    assert core.classify("https://x/basis_transcoder.js", JS)[1] == "Basis/KTX2 texture compression"


def test_model_formats_and_sketchfab_binz():
    assert core.classify("https://x/a.glb", "") == ("model", "glTF binary")
    assert core.classify("https://x/scan.laz", "")[0] == "model"
    assert "geometry" in core.classify("https://media.sketchfab.com/x/model_file.binz", "")[1]
    assert "scene graph" in core.classify("https://media.sketchfab.com/x/file.binz", "")[1]


def test_telemetry_is_not_an_api():
    assert core.classify("https://o1.ingest.sentry.io/api/123/envelope/", "application/json") == (None, None)
    assert core.classify("https://x.com/api/models/42", "application/json") == ("api", "JSON API")


def test_cdn_detection():
    assert core.cdn_of({"x-amz-cf-id": "a"}) == "Amazon CloudFront"
    assert core.cdn_of({"cf-ray": "a"}) == "Cloudflare"
    assert core.cdn_of({"x-ms-request-id": "a"}) == "Azure Blob Storage"
    assert core.cdn_of({"server": "nginx/1.24.0"}) == "own web server (nginx/1.24.0)"


# --- GPU probe / JS sanity (static checks; the JS itself runs in tests/regression.sh) -------
def test_probe_keeps_worker_a_real_constructor():
    # regression: Worker was replaced by a plain function -> broke `instanceof Worker` / subclassing on sites
    assert "new Proxy(window.Worker" in core.GPU_PROBE_JS


def test_detect_js_does_not_create_contexts():
    # regression: DETECT_JS called getContext() and created extra WebGL contexts on unused canvases
    import re
    code = re.sub(r"//[^\n]*", "", core.DETECT_JS)        # ignore the explanatory comments
    assert ".getContext(" not in code and "__siCtx" in code


def test_blocked_check_ignores_recaptcha_footers():
    # regression: any page mentioning "captcha" was reported as blocked
    js = core.DETECT_JS
    assert "txt.length < 1500" in js and "gate.test(document.title)" in js


# --- summary ------------------------------------------------------------------------------
def test_summary_normal_page():
    lines = core.summary(found(), [rec()], {"Meshopt compression": "x"})
    text = " ".join(lines)
    assert "three.js r186" in text and "Amazon CloudFront" in text and "Meshopt" in text


def test_summary_blocked_hidden_vs_assisted():
    hidden = " ".join(core.summary(found(blocked=True), [], {}))
    assisted = " ".join(core.summary(found(blocked=True, browser="Brave (visible, assisted)"), [], {}))
    assert "I'll open it myself" in hidden
    assert "complete the check" in assisted


def test_summary_direct_file():
    assert "points straight at a 3D file" in core.summary(found(direct_file="glTF binary"), [], {})[0]


def test_summary_zero_frames_is_not_a_guess():
    g = dict(found()["gpu"], frames=0, fps=0, draws_per_frame=None)
    text = " ".join(core.summary(found(gpu=g), [rec()], {}))
    assert "renders only when you interact, or off the main thread" in text
    assert "renders on demand" not in text.lower().replace("renders only", "")


def test_summary_on_demand_when_frames_but_no_draws():
    g = dict(found()["gpu"], draws_per_frame=0)
    assert "renders on demand" in " ".join(core.summary(found(gpu=g), [rec()], {}))


def test_summary_progressive_textures_only_with_proof():
    f = found(textures=[1000, 50_000, 900_000], api_textures=2)
    assert "progressive loading" in " ".join(core.summary(f, [rec()], {}))
    f = found(textures=[1000, 50_000], api_textures=None)
    assert "progressive" not in " ".join(core.summary(f, [rec()], {}))


# --- extras -------------------------------------------------------------------------------
def test_lessons_texture_decoder_is_not_geometry_compression():
    # regression: a Basis/KTX2 (texture) decoder made the geometry lesson pass
    _, tips = extras.lessons(found(), [rec()], {"Basis/KTX2 texture compression": "x"})
    geo = [t for t in tips if t[1] == "Geometry compression"][0]
    assert geo[0] == "tip"
    _, tips = extras.lessons(found(), [rec()], {"Draco geometry compression": "x"})
    assert [t for t in tips if t[1] == "Geometry compression"][0][0] == "ok"


def test_lessons_score_range_and_nothing_case():
    score, _ = extras.lessons(found(), [rec()], {})
    assert 0 <= score <= 100
    g = dict(found()["gpu"], draws=0)
    assert extras.lessons(found(gpu=g), [], {})[0] is None


def test_no_prices_anywhere():
    # owner's rule: this is a study tool - no prices in any output
    facts_src = (ROOT / "sketchfab.py").read_text()
    assert "price" not in facts_src.lower()


def test_glossary_diagram_timeline():
    assert ("CDN" in [t for t, _ in extras.glossary("served by Amazon CloudFront")])
    svg = extras.diagram_svg(found(), [rec()], {}, {"api.x/{id}": 200})
    assert svg.startswith("<svg") and "Amazon CloudFront" in svg and "1 endpoint(s)" in svg
    assert "glTF binary" in extras.timeline_html([rec()])


def test_report_html_json_and_compare():
    with tempfile.TemporaryDirectory() as d:
        old = core.REPORTS
        core.REPORTS = Path(d)
        try:
            out = core.report("https://example.com/model", found(), [rec()], {}, {"example.com/api/{id}": 200}, None, 3.0)
            html = out.read_text()
            for section in ("Architecture at a glance", "Lessons for your own site", "Load timeline", "Glossary"):
                assert section in html, section
            data = json.loads(out.with_suffix(".json").read_text())
            assert data["host"] == "example.com" and data["formats"] == "glTF binary"
            out2 = core.report("https://other.org/x", found(), [rec(cdn="Fastly")], {}, {}, None, 2.0)
            cmp = extras.compare(out.with_suffix(".json"), out2.with_suffix(".json"), d)
            assert "example.com" in cmp.read_text() and "other.org" in cmp.read_text()
        finally:
            core.REPORTS = old


# --- runner -------------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except Exception:
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
