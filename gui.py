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

BG, PANEL, CARD, LINE = "#111418", "#181c22", "#1f242c", "#2b313b"
TEXT, MUTED, ACCENT, BLUE, ERR, OK = "#e8e6e1", "#9aa0a8", "#c8b089", "#7fa6c9", "#e07a6a", "#8fc79a"
FONT = "sans"


def open_path(path):
    subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Tile(tk.Frame):
    """Small result card: caption + value."""
    def __init__(self, parent, caption):
        super().__init__(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1, padx=12, pady=8)
        tk.Label(self, text=caption.upper(), bg=CARD, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
        self.value = tk.Label(self, text="—", bg=CARD, fg=TEXT, font=(FONT, 12, "bold"), anchor="w",
                              justify="left", wraplength=170)
        self.value.pack(anchor="w", fill="x")

    def set(self, text, color=TEXT):
        self.value.configure(text=text or "—", fg=color)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        name = "Sketchfab Inspector" if SKETCHFAB_MODE else "Site Inspector"
        self.title(name)
        self.geometry("1240x780")
        self.minsize(960, 620)
        self.configure(bg=BG)
        self.last_report = None
        self.busy = False
        self.ready_event = threading.Event()
        self.history = []
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self._style()

        # --- header ------------------------------------------------------------
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=22, pady=(18, 10))
        tk.Label(head, text="◆", bg=BG, fg=ACCENT, font=(FONT, 22)).pack(side="left", padx=(0, 10))
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text=name, bg=BG, fg=TEXT, font=(FONT, 19, "bold")).pack(anchor="w")
        tk.Label(titles, text=("Sketchfab model link → model facts from the Data API + how the viewer streams it"
                               if SKETCHFAB_MODE else
                               "Any page that shows a 3D model → how it is shown, where it is stored, how it is delivered"),
                 bg=BG, fg=MUTED, font=(FONT, 10)).pack(anchor="w")

        # --- input card -------------------------------------------------------
        card = tk.Frame(self, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", padx=22)
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", padx=14, pady=(14, 8))
        self.url = tk.Entry(row, bg=CARD, fg=TEXT, insertbackground=ACCENT, relief="flat", font=(FONT, 12),
                            highlightbackground=LINE, highlightcolor=ACCENT, highlightthickness=1)
        self.url.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 8))
        self.url.bind("<Return>", lambda e: self.start())
        ttk.Button(row, text="Paste", command=self.paste).pack(side="left", padx=(0, 8))
        self.go = ttk.Button(row, text="Inspect  ▶", style="Accent.TButton", command=self.start)
        self.go.pack(side="left")

        opt = tk.Frame(card, bg=PANEL)
        opt.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(opt, text="Browser", bg=PANEL, fg=MUTED).pack(side="left")
        self.browser = ttk.Combobox(opt, values=core.BROWSERS, state="readonly", width=10)
        self.browser.set("Auto")
        self.browser.pack(side="left", padx=(6, 18))
        self.assisted = tk.BooleanVar(value=False)
        tk.Checkbutton(opt, text="I'll open it myself  (for \"are you human\" checks)", variable=self.assisted,
                       bg=PANEL, fg=TEXT, selectcolor=CARD, activebackground=PANEL, activeforeground=TEXT,
                       highlightthickness=0, font=(FONT, 10)).pack(side="left")
        self.ready_btn = ttk.Button(opt, text="Page is ready – analyse", style="Accent.TButton", command=self.page_ready)

        # --- progress + status ------------------------------------------------
        self.bar = ttk.Progressbar(self, mode="determinate", value=0)
        self.bar.pack(fill="x", padx=22, pady=(10, 0))
        self.status = tk.Label(self, text="Ready. Paste a link and press Enter.", bg=BG, fg=MUTED, anchor="w",
                               justify="left", wraplength=1150, font=(FONT, 10))
        self.status.pack(fill="x", padx=22, pady=(4, 8))

        # --- bottom bar (packed before the body so it can never be pushed off-screen) ---
        btns = tk.Frame(self, bg=BG)
        btns.pack(side="bottom", fill="x", padx=22, pady=14)
        self.open_btn = ttk.Button(btns, text="Open full report", command=self.open_report, state="disabled")
        self.open_btn.pack(side="left")
        self.pdf_btn = ttk.Button(btns, text="Save as PDF", command=self.save_pdf, state="disabled")
        self.pdf_btn.pack(side="left", padx=8)
        ttk.Button(btns, text="Reports folder", command=lambda: open_path(core.REPORTS)).pack(side="left")
        ttk.Button(btns, text="Close", command=self.quit_app).pack(side="right")

        # --- body: results (left) + history (right) ----------------------------
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=22)

        left = tk.Frame(body, bg=BG)          # packed after the History panel, so History keeps its width
        tiles = tk.Frame(left, bg=BG)
        tiles.pack(fill="x", pady=(0, 10))
        self.t_engine, self.t_store = Tile(tiles, "3D engine"), Tile(tiles, "Storage / CDN")
        self.t_format, self.t_score = Tile(tiles, "File formats"), Tile(tiles, "Lessons score")
        for i, t in enumerate((self.t_engine, self.t_store, self.t_format, self.t_score)):
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            tiles.grid_columnconfigure(i, weight=1, uniform="tile")

        textwrap = tk.Frame(left, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        textwrap.pack(fill="both", expand=True)
        self.out = tk.Text(textwrap, bg=CARD, fg=TEXT, relief="flat", wrap="word", font=(FONT, 11),
                           padx=16, pady=12, state="disabled", spacing1=2, spacing3=2, highlightthickness=0)
        sb = ttk.Scrollbar(textwrap, command=self.out.yview)
        self.out.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.out.pack(side="left", fill="both", expand=True)
        self.out.tag_configure("h", foreground=ACCENT, font=(FONT, 12, "bold"), spacing1=12, spacing3=4)
        self.out.tag_configure("m", foreground=MUTED)
        self.out.tag_configure("ok", foreground=OK)
        self.out.tag_configure("tip", foreground=ACCENT)
        self.out.tag_configure("note", foreground=BLUE)

        side = tk.Frame(body, bg=PANEL, highlightbackground=LINE, highlightthickness=1, width=360)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(side, text="History", bg=PANEL, fg=ACCENT, font=(FONT, 12, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(side, text="double-click: open   ·   Ctrl+click two: compare", bg=PANEL, fg=MUTED,
                 font=(FONT, 8)).pack(anchor="w", padx=12)
        self.hist = tk.Listbox(side, bg=CARD, fg=TEXT, selectbackground=ACCENT, selectforeground=BG, relief="flat",
                               activestyle="none", selectmode="extended", highlightthickness=0, font=("monospace", 9),
                               borderwidth=0)
        self.hist.pack(fill="both", expand=True, padx=12, pady=8)
        self.hist.bind("<Double-Button-1>", lambda e: self.open_selected())
        hb = tk.Frame(side, bg=PANEL)
        hb.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(hb, text="Compare 2", command=self.compare_selected).pack(side="left")
        ttk.Button(hb, text="↻", width=3, command=self.load_history).pack(side="right")

        self.bind_all("<Control-o>", lambda e: self.open_report())
        self.write([("How to use", "h"),
                    ("Paste the link of any page that SHOWS a 3D model - a model page, product page, gallery, museum "
                     "object, portfolio. Galleries are explored automatically.\n", None),
                    ("Unknown engines are still described by the GPU catch-all (what the page sends to the graphics card).\n", None),
                    ("\"Are you human\" sites (Smithsonian, Printables, TurboSquid): tick “I'll open it myself”, pass the "
                     "check in the window that opens, then press “Page is ready – analyse”.\n", "note"),
                    ("Every report has an architecture diagram, a lessons score, a load timeline and a glossary. "
                     "Enter = inspect · Ctrl+O = open report.", "m")])
        self.load_history()
        self.prefill_from_clipboard()
        self.url.focus_set()

    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("TButton", background=CARD, foreground=TEXT, padding=(12, 8), borderwidth=0, font=(FONT, 10))
        st.map("TButton", background=[("active", LINE), ("disabled", BG)], foreground=[("disabled", MUTED)])
        st.configure("Accent.TButton", background=ACCENT, foreground=BG, font=(FONT, 11, "bold"), padding=(16, 8))
        st.map("Accent.TButton", background=[("active", "#d8c29d"), ("disabled", "#5c5444")])
        st.configure("TProgressbar", background=ACCENT, troughcolor=BG, borderwidth=0, thickness=4,
                     bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT)
        st.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=TEXT, arrowcolor=TEXT,
                     bordercolor=LINE, lightcolor=CARD, darkcolor=CARD)
        st.map("TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", TEXT)],
               selectbackground=[("readonly", CARD)], selectforeground=[("readonly", TEXT)],
               background=[("readonly", CARD), ("active", LINE)])
        st.configure("Vertical.TScrollbar", background=CARD, troughcolor=CARD, arrowcolor=MUTED, borderwidth=0)
        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)

    # --- small helpers -------------------------------------------------------
    def prefill_from_clipboard(self):
        try:
            clip = self.clipboard_get().strip()
        except tk.TclError:
            return
        if clip.startswith(("http://", "https://")) and " " not in clip and len(clip) < 2000:
            self.url.insert(0, clip)
            self.set_status("A link from your clipboard was filled in - press Enter to inspect it.", BLUE)

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
        self.out.yview_moveto(0)

    def set_status(self, text, color=MUTED):
        self.status.configure(text=text, fg=color)

    def clear_tiles(self):
        for t in (self.t_engine, self.t_store, self.t_format, self.t_score):
            t.set("…", MUTED)

    # --- history / compare ---------------------------------------------------
    def load_history(self):
        self.history = []
        if core.REPORTS.exists():
            for j in sorted(core.REPORTS.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):  # newest first
                try:
                    self.history.append((j, json.loads(j.read_text(encoding="utf-8"))))
                except Exception:
                    pass
        self.hist.delete(0, "end")
        for _, d in self.history:
            host = d.get("host", "")
            host = host if len(host) <= 24 else host[:23] + "…"
            score = d.get("score") if d.get("score") not in (None, "-") else ""
            self.hist.insert("end", f" {d.get('when', '')[5:]}  {host}  {score}")

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
        self.set_status(f"Comparison saved: {out.name}", OK)
        open_path(out)

    # --- inspection ------------------------------------------------------------
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
        self.clear_tiles()
        self.bar.configure(mode='indeterminate'); self.bar.start(12)
        self.set_status("Inspecting… (about 20–40 seconds, longer if it has to explore a gallery)")
        self.write([("Working…", "m")])
        self.ready_event.clear()
        threading.Thread(target=self.work, args=(link, self.assisted.get(), self.browser.get()), daemon=True).start()

    def waiting_for_user(self):
        self.bar.stop(); self.bar.configure(mode='determinate', value=0)
        self.set_status("A browser window opened. Browse normally, pass any human check, open the 3D view, "
                        "then press “Page is ready – analyse”. (Closing that window cancels.)", ACCENT)
        self.ready_btn.pack(side="right")

    def page_ready(self):
        self.ready_btn.pack_forget()
        self.bar.configure(mode='indeterminate'); self.bar.start(12)
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
        self.bar.stop(); self.bar.configure(mode='determinate', value=0)
        self.ready_btn.pack_forget()
        self.go.configure(state="normal")
        if err:
            self.set_status("Something went wrong.", ERR)
            for t in (self.t_engine, self.t_store, self.t_format, self.t_score):
                t.set("—", MUTED)
            self.write([("Error", "h"), (f"{type(err).__name__}: {err}", None)])
            return
        self.last_report = path
        self.open_btn.configure(state="normal")
        self.pdf_btn.configure(state="normal")
        self.set_status(f"Done in {secs:.0f}s with {found.get('browser', '?')} · {found.get('title', '')[:90]}", OK)

        models = [r for r in records if r["kind"] == "model"]
        score, tips = extras.lessons(found, records, decoders)
        engine = ", ".join(k.split(" (")[0] for k in found.get("libs", {})) or \
            ("blocked" if found.get("blocked") else "in-house / unknown" if core.shows_3d(found, records) else "none found")
        self.t_engine.set(engine, ERR if found.get("blocked") else TEXT)
        self.t_store.set(", ".join(sorted({r["cdn"] for r in models})) or "—")
        self.t_format.set(", ".join(sorted({r["format"].split(" (")[0] for r in models})) or "—")
        self.t_score.set(f"{score}/100" if score is not None else "—",
                         OK if (score or 0) >= 70 else ACCENT if score is not None else MUTED)

        parts = [("Summary", "h")]
        parts += [(f"• {line}\n", None) for line in core.summary(found, records, decoders)]
        if tips:
            parts.append(("Lessons for your own site", "h"))
            mark = {"ok": ("✔ ", "ok"), "tip": ("➜ ", "tip"), "info": ("• ", "note")}
            for s, t, d in tips:
                parts.append((f"{mark[s][0]}{t}: ", mark[s][1]))
                parts.append((f"{d}\n", None))
        for sec, rows in found.get("sketchfab") or []:
            parts.append((f"Sketchfab · {sec}", "h"))
            parts += [(f"• {k}: {v}\n", None) for k, v in rows]
        if models:
            parts.append(("How it is stored", "h"))
            for r in models[:12]:
                parts.append((f"• {r['format']} · {core.human(r['size'])} · {r['cdn']} · {r['where']}\n", None))
                parts.append((f"   signed link: {r['signed']} · login sent: {r['auth']} · caching: {r['cache']}\n", "m"))
        if apis:
            parts += [("API calls", "h")] + [(f"• {k}\n", None) for k in list(apis)[:8]]
        parts.append(("\nDiagram, timeline, glossary and screenshot: “Open full report” (Ctrl+O).", "m"))
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
                self.after(0, lambda: (self.set_status(f"PDF saved: {out}", OK), open_path(out)))
            except Exception as e:
                self.after(0, lambda: self.set_status(f"PDF failed: {e}", ERR))
        threading.Thread(target=run, daemon=True).start()

    def quit_app(self):
        self.ready_event.set()   # release an assisted run that is waiting, so its browser closes
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
