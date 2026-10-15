#!/usr/bin/env python3
"""Site Inspector - desktop window. Paste a link, press Inspect, read the result."""
import json
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

import extras
import inspect_site as core
import sketchfab

SKETCHFAB_MODE = "--sketchfab" in sys.argv

BG, CARD, TEXT, MUTED, ACCENT, ERR = "#14171c", "#1e2229", "#e8e6e1", "#9aa0a8", "#c8b089", "#e07a6a"


def open_path(path):
    subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        name = "Sketchfab Inspector" if SKETCHFAB_MODE else "Site Inspector"
        self.title(name)
        self.geometry("1180x720")
        self.minsize(900, 560)
        self.configure(bg=BG)
        self.last_report = None
        self.busy = False
        self.ready_event = threading.Event()
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", background=CARD, foreground=TEXT, padding=8, borderwidth=0)
        style.map("TButton", background=[("active", "#2a2f37"), ("disabled", BG)], foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, font=("sans", 11, "bold"))
        style.map("Accent.TButton", background=[("active", "#d8c29d"), ("disabled", "#5c5444")])
        style.configure("TProgressbar", background=ACCENT, troughcolor=CARD, borderwidth=0)
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=TEXT, arrowcolor=TEXT)
        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)

        tk.Label(self, text=name, bg=BG, fg=TEXT, font=("sans", 18, "bold")).pack(anchor="w", padx=20, pady=(18, 0))
        tk.Label(self, text=("Paste a Sketchfab model link: model facts from Sketchfab's Data API + how its viewer streams it."
                             if SKETCHFAB_MODE else
                             "Paste a link to a page with a 3D model: see how it is shown, stored and delivered."),
                 bg=BG, fg=MUTED).pack(anchor="w", padx=20)

        # --- link row --------------------------------------------------------
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=20, pady=(14, 6))
        self.url = tk.Entry(row, bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat", font=("sans", 12))
        self.url.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.url.bind("<Return>", lambda e: self.start())
        ttk.Button(row, text="Paste", command=self.paste).pack(side="left", padx=(0, 8))
        self.go = ttk.Button(row, text="Inspect", style="Accent.TButton", command=self.start)
        self.go.pack(side="left")

        # --- options row -----------------------------------------------------
        opt = tk.Frame(self, bg=BG)
        opt.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(opt, text="Browser:", bg=BG, fg=MUTED).pack(side="left")
        self.browser = ttk.Combobox(opt, values=core.BROWSERS, state="readonly", width=10)
        self.browser.set("Auto")
        self.browser.pack(side="left", padx=(6, 16))
        self.assisted = tk.BooleanVar(value=False)
        tk.Checkbutton(opt, text="I'll open it myself (sites with an \"are you human\" check)",
                       variable=self.assisted, bg=BG, fg=TEXT, selectcolor=CARD, activebackground=BG,
                       activeforeground=TEXT, highlightthickness=0).pack(side="left")
        self.ready_btn = ttk.Button(opt, text="Page is ready – analyse", style="Accent.TButton", command=self.page_ready)

        self.bar = ttk.Progressbar(self, mode="indeterminate")
        self.bar.pack(fill="x", padx=20)
        self.status = tk.Label(self, text="Ready.", bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=1100)
        self.status.pack(fill="x", padx=20, pady=(4, 8))

        # --- body: results (left) + history (right) -------------------------
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=20)
        self.out = tk.Text(body, bg=CARD, fg=TEXT, relief="flat", wrap="word", font=("sans", 11),
                           padx=14, pady=12, state="disabled")
        self.out.tag_configure("h", foreground=ACCENT, font=("sans", 12, "bold"), spacing1=8)
        self.out.tag_configure("m", foreground=MUTED)
        self.out.tag_configure("big", foreground=ACCENT, font=("sans", 14, "bold"))
        self.out.pack(side="left", fill="both", expand=True)

        side = tk.Frame(body, bg=BG, width=300)
        side.pack(side="right", fill="y", padx=(12, 0))
        tk.Label(side, text="History", bg=BG, fg=ACCENT, font=("sans", 12, "bold")).pack(anchor="w")
        tk.Label(side, text="double-click = open · select 2 = compare", bg=BG, fg=MUTED).pack(anchor="w")
        self.hist = tk.Listbox(side, bg=CARD, fg=TEXT, selectbackground=ACCENT, selectforeground=BG, relief="flat",
                               activestyle="none", selectmode="extended", width=38, highlightthickness=0)
        self.hist.pack(fill="both", expand=True, pady=6)
        self.hist.bind("<Double-Button-1>", lambda e: self.open_selected())
        hb = tk.Frame(side, bg=BG)
        hb.pack(fill="x")
        ttk.Button(hb, text="Compare 2", command=self.compare_selected).pack(side="left")
        ttk.Button(hb, text="Refresh", command=self.load_history).pack(side="right")
        self.history = []

        # --- bottom buttons --------------------------------------------------
        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", padx=20, pady=14)
        self.open_btn = ttk.Button(btns, text="Open full report", command=self.open_report, state="disabled")
        self.open_btn.pack(side="left")
        self.pdf_btn = ttk.Button(btns, text="Save as PDF", command=self.save_pdf, state="disabled")
        self.pdf_btn.pack(side="left", padx=8)
        ttk.Button(btns, text="Reports folder", command=lambda: open_path(core.REPORTS)).pack(side="left")
        ttk.Button(btns, text="Close", command=self.quit_app).pack(side="right")

        self.write([("Tips", "h"),
                    ("• Works on most 3D sites. Unknown engines are still described by the GPU catch-all.\n", None),
                    ("• Browser: Auto uses Brave if installed, otherwise the built-in Chromium. Firefox = different engine (Gecko).\n", None),
                    ("• \"Are you human\" sites (TurboSquid, Printables): tick “I'll open it myself”, pass the check in the "
                     "window that opens, then press “Page is ready – analyse”.\n", None),
                    ("• Each report has an architecture diagram, a 'lessons' score, a load timeline and a glossary - "
                     "good material for presentations. “Save as PDF” to hand in.", None)])
        self.load_history()
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

    def set_status(self, text, color=MUTED):
        self.status.configure(text=text, fg=color)

    # --- history / compare -------------------------------------------------
    def load_history(self):
        self.history = []
        if core.REPORTS.exists():
            for j in sorted(core.REPORTS.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):  # newest first
                try:
                    d = json.loads(j.read_text(encoding="utf-8"))
                    self.history.append((j, d))
                except Exception:
                    pass
        self.hist.delete(0, "end")
        for _, d in self.history:
            self.hist.insert("end", f"{d.get('when', '')[5:]}  {d.get('host', '')}  {d.get('score', '')}")

    def open_selected(self):
        sel = self.hist.curselection()
        if sel:
            open_path(self.history[sel[0]][1]["report"])

    def compare_selected(self):
        sel = self.hist.curselection()
        if len(sel) != 2:
            self.set_status("Select exactly 2 inspections in History (Ctrl+click), then press Compare 2.", ERR)
            return
        out = extras.compare(self.history[sel[0]][0], self.history[sel[1]][0], core.REPORTS)
        self.set_status(f"Comparison saved: {out.name}")
        open_path(out)

    # --- inspection ---------------------------------------------------------
    def start(self):
        if self.busy:
            return
        link = self.url.get().strip()
        if not link.startswith(("http://", "https://")):
            self.set_status("Please paste a full link starting with https://", ERR)
            return
        if SKETCHFAB_MODE and not sketchfab.uid_of(link):
            self.set_status("That isn't a Sketchfab model link (sketchfab.com/3d-models/…)", ERR)
            return
        self.busy = True
        self.go.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.pdf_btn.configure(state="disabled")
        self.bar.start(12)
        self.set_status("Inspecting… (about 20–30 seconds)")
        self.write([("Working…", "m")])
        self.ready_event.clear()
        threading.Thread(target=self.work, args=(link, self.assisted.get(), self.browser.get()), daemon=True).start()

    def waiting_for_user(self):
        self.bar.stop()
        self.set_status("A browser window opened. Browse normally, pass any human check, open the 3D view, "
                        "then press “Page is ready – analyse”. (Closing that window cancels.)", ACCENT)
        self.ready_btn.pack(side="right")

    def page_ready(self):
        self.ready_btn.pack_forget()
        self.bar.start(12)
        self.set_status("Analysing the page you opened…")
        self.ready_event.set()

    def work(self, link, assisted, browser_name):
        try:
            extra = None
            if sketchfab.uid_of(link):
                try:
                    extra = sketchfab.facts(link)
                except Exception as e:
                    extra = [("Data API", [("error", str(e))])]
            found, records, decoders, apis, shot, secs, link = core.inspect_smart(
                link, assisted=assisted, ready=self.ready_event, browser_name=browser_name,
                on_waiting=lambda: self.after(0, self.waiting_for_user),
                on_status=lambda t: self.after(0, self.set_status, t, ACCENT))
            found["sketchfab"] = extra
            for sec, rows in extra or []:
                for k, v in rows:
                    if k == "Textures" and str(v).replace(",", "").isdigit():
                        found["api_textures"] = int(str(v).replace(",", ""))
            path = core.report(link, found, records, decoders, apis, shot, secs, extra)
            self.after(0, self.done, found, records, decoders, apis, path, secs, None)
        except Exception as e:  # show any failure in the window instead of dying silently
            self.after(0, self.done, None, None, None, None, None, 0, e)

    def done(self, found, records, decoders, apis, path, secs, err):
        self.busy = False
        self.bar.stop()
        self.ready_btn.pack_forget()
        self.go.configure(state="normal")
        if err:
            self.set_status("Something went wrong.", ERR)
            self.write([("Error", "h"), (f"{type(err).__name__}: {err}", None)])
            return
        self.last_report = path
        self.open_btn.configure(state="normal")
        self.pdf_btn.configure(state="normal")
        self.set_status(f"Done in {secs:.0f}s with {found.get('browser', '?')} · {found.get('title', '')[:80]}")
        score, tips = extras.lessons(found, records, decoders)
        parts = []
        if score is not None:
            parts.append((f"Lessons score: {score}/100\n", "big"))
        parts.append(("Summary", "h"))
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
        if tips:
            mark = {"ok": "✔", "tip": "➜", "info": "•"}
            parts += [("Lessons for your own site", "h")] + [(f"{mark[s]} {t}: {d}\n", None) for s, t, d in tips]
        if apis:
            parts += [("API calls", "h")] + [(f"• {k}\n", None) for k in list(apis)[:8]]
        parts.append(("\nDiagram, timeline, glossary and screenshot: press “Open full report”.", "m"))
        self.write(parts)
        self.load_history()

    def open_report(self):
        if self.last_report:
            open_path(self.last_report)

    def save_pdf(self):
        if not self.last_report:
            return
        self.set_status("Saving PDF…")
        report = self.last_report

        def run():
            try:
                out = extras.to_pdf(report)
                self.after(0, lambda: (self.set_status(f"PDF saved: {out}"), open_path(out)))
            except Exception as e:
                self.after(0, lambda: self.set_status(f"PDF failed: {e}", ERR))
        threading.Thread(target=run, daemon=True).start()

    def quit_app(self):
        self.ready_event.set()   # release an assisted run that is waiting, so its browser closes
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
