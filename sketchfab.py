#!/usr/bin/env python3
"""
Sketchfab deep dive - public facts about a Sketchfab model from Sketchfab's
official Data API v3 (https://docs.sketchfab.com/data-api/v3/), no login needed.

Combined with the live viewer analysis in inspect_site.py this explains the
whole chain: what the model is (mesh/material/texture stats, licence), how the
platform publishes it (viewer, embed, protection) and how the viewer streams it.
"""
import json
import re
import urllib.request

API = "https://api.sketchfab.com/v3/models/{uid}"
UID = re.compile(r"sketchfab\.com/(?:3d-models/[^/?#]*-|models/)([0-9a-f]{32})")


def uid_of(url):
    m = UID.search(url)
    return m.group(1) if m else None


def fetch(uid):
    req = urllib.request.Request(API.format(uid=uid), headers={"User-Agent": "SiteInspector/1.0 (study project)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def facts(url):
    """Returns a list of (section, [(label, value), ...]) or None if not a Sketchfab model link."""
    uid = uid_of(url)
    if not uid:
        return None
    d = fetch(uid)
    num = lambda v: f"{v:,}" if isinstance(v, int) else (v if v not in (None, "") else "-")
    lic = (d.get("license") or {}).get("label") or "-"
    return [
        ("Model", [
            ("Name", d.get("name")), ("Author", (d.get("user") or {}).get("displayName")),
            ("Category", ", ".join(c["name"] for c in d.get("categories", [])) or "-"),
            ("Tags", ", ".join(t["name"] for t in d.get("tags", [])[:12]) or "-"),
            ("Published", (d.get("publishedAt") or "-")[:10]), ("Updated", (d.get("updatedAt") or "-")[:10]),
            ("Uploaded from", d.get("source") or "-"),
        ]),
        ("Geometry & materials", [
            ("Triangles (faces)", num(d.get("faceCount"))), ("Vertices", num(d.get("vertexCount"))),
            ("Materials", num(d.get("materialCount"))), ("Textures", num(d.get("textureCount"))),
            ("PBR workflow", d.get("pbrType") or "classic / none"),
            ("Animations", num(d.get("animationCount"))), ("Sounds", num(d.get("soundCount"))),
        ]),
        ("Publishing & rights", [
            ("Licence", lic), ("Downloadable by the author's choice", "yes" if d.get("isDownloadable") else "no"),
            ("Protected", "yes" if d.get("isProtected") else "no"),
            ("Age restricted", "yes" if d.get("isAgeRestricted") else "no"),
            ("Staff pick", (d.get("staffpickedAt") or "no")[:10]),
        ]),
        ("Popularity", [
            ("Views", num(d.get("viewCount"))), ("Likes", num(d.get("likeCount"))),
            ("Downloads", num(d.get("downloadCount"))), ("Comments", num(d.get("commentCount"))),
        ]),
        ("How Sketchfab publishes it", [
            ("Data API endpoint", f"api.sketchfab.com/v3/models/{{uid}}  (JSON, public)"),
            ("Embed URL pattern", "sketchfab.com/models/{uid}/embed  (iframe; options like ?autostart=1)"),
            ("Viewer", "Sketchfab's in-house WebGL engine (built on OSG.JS)"),
        ]),
    ]


if __name__ == "__main__":
    import sys
    for section, rows in facts(sys.argv[1]) or []:
        print(f"== {section}")
        for k, v in rows:
            print(f"  {k}: {v}")
