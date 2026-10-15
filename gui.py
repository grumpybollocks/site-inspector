#!/usr/bin/env python3
"""Site Inspector - desktop window. Paste a link, press Inspect, read the result."""
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import sys

import inspect_site as core
import sketchfab

SKETCHFAB_MODE = "--sketchfab" in sys.argv

BG, CARD, TEXT, MUTED, ACCENT = "#14171c", "#1e2229", "#e8e6e1", "#9aa0a8", "#c8b089"


def open_path(path):
    subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        name = "Sketchfab Inspector" if SKETCHFAB_MODE else "Site Inspector"
        self.title(name)
        self.geometry("900x640")
        self.configure(bg=BG)
        self.last_report = None

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", background=CARD, foreground=TEXT, padding=8, borderwidth=0)
        style.map("TButton", background=[("active", "#2a2f37"), ("disabled", BG)],
                  foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, font=("sans", 11, "bold"))
        style.map("Accent.TButton", background=[("active", "#d8c29d"), ("disabled", "#5c5444")])
        style.configure("TProgressbar", background=ACCENT, troughcolor=CARD, borderwidth=0)

        tk.Label(self, text=name, bg=BG, fg=TEXT, font=("sans", 18, "bold")).pack(anchor="w", padx=20, pady=(18, 0))
        tk.Label(self, text=("Paste a Sketchfab model link: model facts from Sketchfab's Data API + how its viewer streams it."
                             if SKETCHFAB_MODE else
                             "Paste a link to a page with a 3D model: see how it is shown, stored and delivered."),
                 bg=BG, fg=MUTED).pack(anchor="w", padx=20)

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=20, pady=14)
        self.url = tk.Entry(row, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat", font=("sans", 12))
        self.url.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.url.bind("<Return>", lambda e: self.start())
        ttk.Button(row, text="Paste", command=self.paste).pack(side="left", padx=(0, 8))
        self.go = ttk.Button(row, text="Inspect", style="Accent.TButton", command=self.start)
        self.go.pack(side="left")

        self.bar = ttk.Progressbar(self, mode="indeterminate")
        self.bar.pack(fill="x", padx=20)
        self.status = tk.Label(self, text="Ready.", bg=BG, fg=MUTED, anchor="w")
        self.status.pack(fill="x", padx=20, pady=(4, 8))

        self.out = tk.Text(self, bg=CARD, fg=TEXT, relief="flat", wrap="word", font=("sans", 11),
                           padx=14, pady=12, state="disabled")
        self.out.tag_configure("h", foreground=ACCENT, font=("sans", 12, "bold"), spacing1=8)
        self.out.tag_configure("m", foreground=MUTED)
        self.out.pack(fill="both", expand=True, padx=20)

        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", padx=20, pady=14)
        self.open_btn = ttk.Button(btns, text="Open full report", command=self.open_report, state="disabled")
        self.open_btn.pack(side="left")
        ttk.Button(btns, text="Reports folder", command=lambda: open_path(core.REPORTS)).pack(side="left", padx=8)
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")

        self.write([("Tips", "h"),
                    ("• Works on most 3D sites: Sketchfab, three.js / model-viewer pages, product viewers.\n", None),
                    ("• Some sites (TurboSquid, Printables) block automated visits - the result will say so.\n", None),
                    ("• Each inspection takes about 20 seconds and runs in a hidden browser; your Brave is not touched.", None)])
        self.url.focus_set()

    # ---------------------------------------------------------------------
    def paste(self):
        try:
            self.url.delete(0, "end")
            self.url.insert(0, self.clipboard_get().strip())
        except tk.TclError:
            pass

    def write(self, parts):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        for text, tag in parts:
            self.out.insert("end", text + ("\n" if tag == "h" else ""), tag)
        self.out.configure(state="disabled")

    def start(self):
        link = self.url.get().strip()
        if not link.startswith(("http://", "https://")):
            self.status.configure(text="Please paste a full link starting with https://", fg="#e07a6a")
            return
        if SKETCHFAB_MODE and not sketchfab.uid_of(link):
            self.status.configure(text="That isn't a Sketchfab model link (sketchfab.com/3d-models/…)", fg="#e07a6a")
            return
        self.go.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.bar.start(12)
        self.status.configure(text="Inspecting… (about 20 seconds)", fg=MUTED)
        self.write([("Working…", "m")])
        threading.Thread(target=self.work, args=(link,), daemon=True).start()

    def work(self, link):
        try:
            extra = None
            if sketchfab.uid_of(link):
                try:
                    extra = sketchfab.facts(link)
                except Exception as e:
                    extra = [("Data API", [("error", str(e))])]
            found, records, decoders, apis, shot, secs = core.inspect(link)
            found["sketchfab"] = extra
            for sec, rows in extra or []:
                for k, v in rows:
                    if k == "Textures" and str(v).replace(",", "").isdigit():
                        found["api_textures"] = int(str(v).replace(",", ""))
            path = core.report(link, found, records, decoders, apis, shot, secs, extra)
            self.after(0, self.done, link, found, records, decoders, apis, path, secs, None)
        except Exception as e:  # show any failure in the window instead of dying silently
            self.after(0, self.done, link, None, None, None, None, None, 0, e)

    def done(self, link, found, records, decoders, apis, path, secs, err):
        self.bar.stop()
        self.go.configure(state="normal")
        if err:
            self.status.configure(text="Something went wrong.", fg="#e07a6a")
            self.write([("Error", "h"), (f"{type(err).__name__}: {err}", None)])
            return
        self.last_report = path
        self.open_btn.configure(state="normal")
        self.status.configure(text=f"Done in {secs:.0f}s · {found.get('title', '')[:80]}", fg=MUTED)
        parts = [("Summary", "h")]
        parts += [(f"• {line}\n", None) for line in core.summary(found, records, decoders)]
        for sec, rows in found.get("sketchfab") or []:
            parts.append((f"Sketchfab · {sec}", "h"))
            parts += [(f"• {k}: {v}\n", None) for k, v in rows]
        if found["libs"]:
            parts += [("How it is shown", "h")] + [(f"• {k}: {v}\n", None) for k, v in found["libs"].items()]
        models = [r for r in records if r["kind"] == "model"]
        if models:
            parts.append(("How it is stored", "h"))
            for r in models[:12]:
                parts.append((f"• {r['format']} · {core.human(r['size'])} · {r['cdn']} · {r['where']}\n"
                              f"   signed link: {r['signed']} · login sent: {r['auth']} · caching: {r['cache']}\n", None))
        if apis:
            parts += [("API calls", "h")] + [(f"• {k}\n", None) for k in list(apis)[:8]]
        parts.append(("\nFull details, screenshot and tables: press “Open full report”.", "m"))
        self.write(parts)

    def open_report(self):
        if self.last_report:
            open_path(self.last_report)


if __name__ == "__main__":
    App().mainloop()
