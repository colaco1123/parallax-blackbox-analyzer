"""Tkinter user interface for the Parallax Blackbox Analyzer."""

from __future__ import annotations

import datetime as _dt
import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from types import SimpleNamespace
from tkinter import filedialog, messagebox, ttk

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates  # noqa: E402
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from parallax_bb import APP_NAME, __version__  # noqa: E402
from parallax_bb import analysis, decoder, logdata  # noqa: E402
from parallax_bb.config import Settings  # noqa: E402
from parallax_bb.presets import PRESET_BY_KEY, PRESETS, Panel, Series, available_presets, resolve_panels  # noqa: E402
from parallax_bb.theme import MONO_FONT, UI_FONT, apply_style, set_windows_titlebar  # noqa: E402

FILETYPES = [
    ("Blackbox logs and CSV", "*.TXT *.txt *.BBL *.bbl *.BFL *.bfl *.csv *.CSV"),
    ("Raw blackbox logs", "*.TXT *.txt *.BBL *.bbl *.BFL *.bfl"),
    ("Decoded / telemetry CSV", "*.csv *.CSV"),
    ("All files", "*.*"),
]

DISPLAY_POINTS = 5000


class Toolbar(NavigationToolbar2Tk):
    # Drop the subplot-configuration button; layout is handled automatically.
    toolitems = [t for t in NavigationToolbar2Tk.toolitems if t[0] not in ("Subplots",)]


class App:
    def __init__(self, root: tk.Tk, initial_path: str | None = None):
        self.root = root
        self.settings = Settings()
        self.pal = apply_style(root, self.settings["theme"])
        root.title(f"{APP_NAME} {__version__}")
        root.geometry("1500x940")
        root.minsize(1100, 700)

        self.q: queue.Queue = queue.Queue()
        self.busy = 0
        self.raw_path = None
        self.entries: list = []        # session descriptors for the tree
        self.session: logdata.Session | None = None
        self.lines: list = []          # dicts: line, x, y, ax, label, column, panel
        self.data_axes: list = []
        self.cursor_lines: list = []
        self.x_base = 0.0              # date number of t=0 in clock mode
        self.x_is_clock = False
        self._xlim_job = None
        self._motion_job = None
        self._replot_job = None
        self._last_motion = None
        self.custom_selected: set = set(self.settings.get("custom_columns", []))
        self.visible_range = (0.0, 0.0)

        self._build_menu()
        self._build_layout()
        self._bind_keys()
        set_windows_titlebar(root, self.settings["theme"] == "dark")
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(50, self._poll_queue)
        self.set_status("Open a blackbox log (.TXT / .BBL) or a CSV to begin.  Ctrl+O")
        if initial_path:
            root.after(200, lambda: self.open_path(initial_path))

    # ------------------------------------------------------------------ layout

    def _build_menu(self):
        m = tk.Menu(self.root)
        fm = tk.Menu(m, tearoff=False)
        fm.add_command(label="Open log...", accelerator="Ctrl+O", command=self.browse)
        self.recent_menu = tk.Menu(fm, tearoff=False)
        fm.add_cascade(label="Open recent", menu=self.recent_menu)
        fm.add_separator()
        fm.add_command(label="Save plot image...", accelerator="Ctrl+S", command=self.save_plot)
        fm.add_command(label="Export visible range to CSV...", accelerator="Ctrl+E",
                       command=self.export_visible)
        fm.add_separator()
        fm.add_command(label="Show decoded CSV folder", command=self.show_decoded_folder)
        fm.add_command(label="Clear decode cache...", command=self.clear_cache)
        fm.add_separator()
        fm.add_command(label="Exit", command=self._on_close)
        m.add_cascade(label="File", menu=fm)

        vm = tk.Menu(m, tearoff=False)
        self.theme_var = tk.StringVar(value=self.settings["theme"])
        vm.add_radiobutton(label="Dark theme", value="dark", variable=self.theme_var, command=self.toggle_theme)
        vm.add_radiobutton(label="Light theme", value="light", variable=self.theme_var, command=self.toggle_theme)
        vm.add_separator()
        vm.add_command(label="Redraw", accelerator="F5", command=self.replot)
        vm.add_command(label="Reset zoom", accelerator="Home", command=self.reset_zoom)
        m.add_cascade(label="View", menu=vm)

        hm = tk.Menu(m, tearoff=False)
        hm.add_command(label="Keyboard shortcuts", command=self.show_shortcuts)
        hm.add_command(label="About", command=self.show_about)
        m.add_cascade(label="Help", menu=hm)
        self.root.config(menu=m)
        self._refresh_recent_menu()

    def _build_layout(self):
        pal = self.pal
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(16, 10))
        header.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(header, text="PARALLAX", style="Accent.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text=" Blackbox Analyzer", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Open log...", style="Accent.TButton", command=self.browse).pack(side=tk.RIGHT)
        self.theme_btn = ttk.Button(header, text=self._theme_btn_text(), command=self._flip_theme)
        self.theme_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self.file_lbl = ttk.Label(header, text="No log loaded", style="File.TLabel")
        self.file_lbl.pack(side=tk.LEFT, padx=(18, 0))

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        status = ttk.Frame(self.root, style="Header.TFrame", padding=(12, 4))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_lbl = ttk.Label(status, text="", style="Status.TLabel")
        self.status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=160)

        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        side = ttk.Frame(pane, style="Side.TFrame", padding=(14, 12), width=350)
        side.pack_propagate(False)
        pane.add(side, weight=0)
        main = ttk.Frame(pane, padding=(6, 4, 6, 0))
        pane.add(main, weight=1)

        self._build_sidebar(side)
        self._build_tabs(main)

    def _section(self, parent, text):
        ttk.Label(parent, text=text.upper(), style="Section.TLabel").pack(anchor=tk.W, pady=(10, 4))

    def _build_sidebar(self, side):
        pal = self.pal
        self._section(side, "Flight sessions")
        tree_frame = ttk.Frame(side, style="Side.TFrame")
        tree_frame.pack(fill=tk.X)
        self.tree = ttk.Treeview(tree_frame, columns=("dur", "start", "note"), show="tree headings",
                                 height=7, selectmode="browse")
        self.tree.heading("#0", text="LOG")
        self.tree.heading("dur", text="LENGTH")
        self.tree.heading("start", text="T+BOOT")
        self.tree.heading("note", text="NOTE")
        self.tree.column("#0", width=52, stretch=False)
        self.tree.column("dur", width=70, anchor=tk.E, stretch=False)
        self.tree.column("start", width=72, anchor=tk.E, stretch=False)
        self.tree.column("note", width=96, stretch=True)
        self.tree.tag_configure("short", foreground=pal["faint"])
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_session_select)

        self.hide_short_var = tk.BooleanVar(value=self.settings["hide_short"])
        ttk.Checkbutton(side, text=f"Hide sessions under {self.settings['short_threshold_s']:g} s",
                        variable=self.hide_short_var, command=self._on_hide_short).pack(anchor=tk.W, pady=(6, 0))
        self.session_lbl = ttk.Label(side, text="", style="Muted.TLabel", wraplength=310, justify=tk.LEFT)
        self.session_lbl.pack(anchor=tk.W, fill=tk.X, pady=(6, 0))

        self._section(side, "View")
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(side, textvariable=self.preset_var, state="readonly",
                                         values=[p.name for p in PRESETS])
        self.preset_combo.pack(fill=tk.X)
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_change)
        self.preset_desc = ttk.Label(side, text="", style="Muted.TLabel", wraplength=310, justify=tk.LEFT)
        self.preset_desc.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))
        self._set_preset(self.settings.get("preset", "overview"))

        opts = ttk.Frame(side, style="Side.TFrame")
        opts.pack(fill=tk.X, pady=(8, 0))
        self.x_mode_var = tk.StringVar(value=self.settings["x_mode"])
        ttk.Label(opts, text="Time axis", style="Side.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(opts, text="Elapsed s", value="elapsed", variable=self.x_mode_var,
                        command=self._on_option).grid(row=0, column=1, sticky=tk.W, padx=(10, 0))
        ttk.Radiobutton(opts, text="Clock", value="clock", variable=self.x_mode_var,
                        command=self._on_option).grid(row=0, column=2, sticky=tk.W, padx=(8, 0))
        self.modes_var = tk.BooleanVar(value=self.settings["show_modes"])
        self.events_var = tk.BooleanVar(value=self.settings["show_events"])
        ttk.Checkbutton(opts, text="Flight mode strip", variable=self.modes_var,
                        command=self._on_option).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        ttk.Checkbutton(opts, text="Log events", variable=self.events_var,
                        command=self._on_option).grid(row=1, column=2, sticky=tk.W, pady=(6, 0), padx=(8, 0))

        # custom column picker
        self.custom_frame = ttk.Frame(side, style="Side.TFrame")
        self._section(self.custom_frame, "Columns")
        lay = ttk.Frame(self.custom_frame, style="Side.TFrame")
        lay.pack(fill=tk.X, pady=(0, 4))
        self.layout_var = tk.StringVar(value=self.settings["layout"])
        ttk.Radiobutton(lay, text="Stacked", value="stacked", variable=self.layout_var,
                        command=self._on_option).pack(side=tk.LEFT)
        ttk.Radiobutton(lay, text="Overlay", value="overlay", variable=self.layout_var,
                        command=self._on_option).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(lay, text="Clear", command=self._clear_custom, padding=(8, 2)).pack(side=tk.RIGHT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refresh_column_list())
        ent = ttk.Entry(self.custom_frame, textvariable=self.search_var)
        ent.pack(fill=tk.X, pady=(0, 4))
        self._placeholder(ent, "Search columns (e.g. gyro, motor, nav)")
        lb_frame = ttk.Frame(self.custom_frame, style="Side.TFrame")
        lb_frame.pack(fill=tk.BOTH, expand=True)
        self.col_list = tk.Listbox(lb_frame, selectmode=tk.MULTIPLE, activestyle="none", exportselection=False,
                                   borderwidth=0, highlightthickness=1, font=(UI_FONT, 9))
        self._style_listbox(self.col_list)
        lsb = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL, command=self.col_list.yview)
        self.col_list.configure(yscrollcommand=lsb.set)
        self.col_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.col_list.bind("<<ListboxSelect>>", self._on_column_pick)
        self.custom_count = ttk.Label(self.custom_frame, text="", style="Muted.TLabel")
        self.custom_count.pack(anchor=tk.W, pady=(4, 0))
        self.visible_columns: list = []

        self.plot_btn = ttk.Button(side, text="Redraw  (F5)", style="Accent.TButton", command=self.replot)
        self.plot_btn.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        self._update_custom_visibility()

    def _placeholder(self, entry, text):
        entry._ph = text
        entry._ph_on = False

        def show(_=None):
            if not self.search_var.get():
                entry._ph_on = True
                entry.configure(foreground=self.pal["faint"])
                entry.insert(0, text)

        def hide(_=None):
            if entry._ph_on:
                entry._ph_on = False
                entry.delete(0, tk.END)
                entry.configure(foreground=self.pal["fg"])

        entry.bind("<FocusIn>", hide)
        entry.bind("<FocusOut>", show)
        self._search_entry = entry
        show()

    def _search_term(self):
        e = getattr(self, "_search_entry", None)
        if e is not None and e._ph_on:
            return ""
        return self.search_var.get().strip().lower()

    def _style_listbox(self, lb):
        pal = self.pal
        lb.configure(background=pal["field"], foreground=pal["fg"], selectbackground=pal["select"],
                     selectforeground=pal["fg"], highlightbackground=pal["border"],
                     highlightcolor=pal["accent"])

    def _build_tabs(self, main):
        self.nb = ttk.Notebook(main)
        self.nb.pack(fill=tk.BOTH, expand=True)

        # --- plot tab
        plot_tab = ttk.Frame(self.nb)
        self.nb.add(plot_tab, text="  Plot  ")
        self.readout = ttk.Label(plot_tab, text=" ", style="Readout.TLabel", anchor=tk.W)
        self.readout.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=(2, 4))
        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_tab)
        self.toolbar = Toolbar(self.canvas, plot_tab, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._keep_fitted(self.canvas)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("axes_leave_event", lambda e: self._hide_cursor())
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self._style_toolbar()
        self._draw_placeholder()

        # --- spectrum tab
        spec_tab = ttk.Frame(self.nb)
        self.nb.add(spec_tab, text="  Spectrum  ")
        ctl = ttk.Frame(spec_tab, style="Card.TFrame", padding=(10, 8))
        ctl.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(ctl, text="SIGNALS", style="Section.TLabel").pack(anchor=tk.W)
        self.spec_list = tk.Listbox(ctl, selectmode=tk.MULTIPLE, exportselection=False, width=26, height=18,
                                    borderwidth=0, highlightthickness=1, font=(UI_FONT, 9), activestyle="none")
        self._style_listbox(self.spec_list)
        self.spec_list.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        row = ttk.Frame(ctl, style="Card.TFrame")
        row.pack(fill=tk.X)
        ttk.Label(row, text="Segment", style="Side.TLabel").pack(side=tk.LEFT)
        self.seg_var = tk.StringVar(value="1024")
        ttk.Combobox(row, textvariable=self.seg_var, values=["256", "512", "1024", "2048", "4096"],
                     width=7, state="readonly").pack(side=tk.RIGHT)
        self.spec_visible_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text="Only the zoomed time range", variable=self.spec_visible_var).pack(
            anchor=tk.W, pady=(8, 0))
        ttk.Button(ctl, text="Compute spectrum", style="Accent.TButton",
                   command=self.compute_spectrum).pack(fill=tk.X, pady=(10, 0))
        self.spec_info = ttk.Label(ctl, text="Pick gyro or other signals to see\nvibration peaks for notch tuning.",
                                   style="Muted.TLabel", justify=tk.LEFT, wraplength=200)
        self.spec_info.pack(anchor=tk.W, pady=(10, 0))
        spec_plot = ttk.Frame(spec_tab)
        spec_plot.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.spec_fig = Figure(figsize=(8, 5), dpi=100)
        self.spec_canvas = FigureCanvasTkAgg(self.spec_fig, master=spec_plot)
        self.spec_toolbar = Toolbar(self.spec_canvas, spec_plot, pack_toolbar=False)
        self.spec_toolbar.update()
        self.spec_toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.spec_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._keep_fitted(self.spec_canvas)

        # --- statistics tab
        stats_tab = ttk.Frame(self.nb, padding=(4, 8))
        self.nb.add(stats_tab, text="  Statistics  ")
        top = ttk.Frame(stats_tab)
        top.pack(fill=tk.X, pady=(0, 6))
        self.stats_range_lbl = ttk.Label(top, text="Plot something to see statistics for the visible range.")
        self.stats_range_lbl.pack(side=tk.LEFT)
        ttk.Button(top, text="Export visible range CSV...", command=self.export_visible).pack(side=tk.RIGHT)
        ttk.Button(top, text="Copy table", command=self.copy_stats).pack(side=tk.RIGHT, padx=(0, 6))
        cols = ("panel", "min", "max", "mean", "std", "rms", "p2p", "n")
        self.stats_tree = ttk.Treeview(stats_tab, columns=cols, show="tree headings")
        self.stats_tree.heading("#0", text="SERIES")
        self.stats_tree.column("#0", width=200)
        for c, w in zip(cols, (200, 90, 90, 90, 90, 90, 90, 80)):
            self.stats_tree.heading(c, text=c.upper())
            self.stats_tree.column(c, width=w, anchor=tk.W if c == "panel" else tk.E)
        self.stats_tree.pack(fill=tk.BOTH, expand=True)

        # --- info tab
        info_tab = ttk.Frame(self.nb, padding=(4, 8))
        self.nb.add(info_tab, text="  Session info  ")
        self.info_text = tk.Text(info_tab, height=20, wrap=tk.WORD, borderwidth=0, highlightthickness=0,
                                 font=(MONO_FONT, 9), padx=10, pady=8)
        self.info_text.pack(fill=tk.X)
        srow = ttk.Frame(info_tab)
        srow.pack(fill=tk.X, pady=(8, 4))
        ttk.Label(srow, text="All headers").pack(side=tk.LEFT)
        self.hdr_search = tk.StringVar()
        self.hdr_search.trace_add("write", lambda *a: self._fill_headers())
        ttk.Entry(srow, textvariable=self.hdr_search, width=30).pack(side=tk.RIGHT)
        ttk.Label(srow, text="Filter ").pack(side=tk.RIGHT)
        self.hdr_tree = ttk.Treeview(info_tab, columns=("value",), show="tree headings")
        self.hdr_tree.heading("#0", text="KEY")
        self.hdr_tree.heading("value", text="VALUE")
        self.hdr_tree.column("#0", width=260)
        self.hdr_tree.column("value", width=700)
        self.hdr_tree.pack(fill=tk.BOTH, expand=True)
        self._style_text()
        self._style_toolbar()

    def _keep_fitted(self, canvas):
        """Matplotlib's Tk backend can size the figure for a stale DPI on scaled displays
        (Windows 125/150 %), leaving the right edge clipped. Re-fit after layout settles."""
        widget = canvas.get_tk_widget()
        state = {"job": None}

        def fit():
            state["job"] = None
            w, h = widget.winfo_width(), widget.winfo_height()
            if w < 10 or h < 10:
                return
            fw, fh = canvas.figure.get_size_inches() * canvas.figure.dpi
            if abs(fw - w) > 2 or abs(fh - h) > 2:
                canvas.resize(SimpleNamespace(width=w, height=h))

        def on_configure(_e):
            if state["job"]:
                widget.after_cancel(state["job"])
            state["job"] = widget.after(120, fit)

        widget.bind("<Configure>", on_configure, add="+")
        widget.after(400, fit)

    def _style_text(self):
        pal = self.pal
        self.info_text.configure(background=pal["panel"], foreground=pal["fg"], insertbackground=pal["fg"])

    def _style_toolbar(self):
        pal = self.pal
        for tb in (self.toolbar, getattr(self, "spec_toolbar", None)):
            if tb is None:
                continue
            tb.configure(background=pal["bg"])
            for child in tb.winfo_children():
                try:
                    child.configure(background=pal["bg"])
                    if isinstance(child, (tk.Button, tk.Checkbutton)):
                        child.configure(activebackground=pal["border"], highlightbackground=pal["bg"],
                                        relief=tk.FLAT, borderwidth=0, foreground=pal["fg"],
                                        activeforeground=pal["fg"])
                        if isinstance(child, tk.Checkbutton):
                            child.configure(selectcolor=pal["select"])
                        if getattr(child, "_image_file", None):
                            # re-render icon so matplotlib picks the light variant on dark bg
                            NavigationToolbar2Tk._set_image_for_button(tb, child)
                    if isinstance(child, tk.Label):
                        child.configure(foreground=pal["muted"])
                except tk.TclError:
                    pass

    def _bind_keys(self):
        r = self.root
        r.bind_all("<Control-o>", lambda e: self.browse())
        r.bind_all("<Control-s>", lambda e: self.save_plot())
        r.bind_all("<Control-e>", lambda e: self.export_visible())
        r.bind_all("<F5>", lambda e: self.replot())
        r.bind_all("<Home>", lambda e: self.reset_zoom() if not isinstance(e.widget, (tk.Entry, ttk.Entry)) else None)

    # ------------------------------------------------------------------ async plumbing

    def run_async(self, label, fn, on_done, *args):
        self.busy += 1
        self.set_status(label)
        self.progress.pack(side=tk.RIGHT)
        self.progress.start(12)

        def work():
            try:
                res = fn(*args)
                self.q.put(("done", on_done, res))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", label, exc, traceback.format_exc()))

        threading.Thread(target=work, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "status":
                    self.set_status(item[1])
                    continue
                self.busy = max(0, self.busy - 1)
                if self.busy == 0:
                    self.progress.stop()
                    self.progress.pack_forget()
                if item[0] == "done":
                    try:
                        item[1](item[2])
                    except Exception as exc:  # noqa: BLE001
                        traceback.print_exc()
                        messagebox.showerror(APP_NAME, f"{exc}")
                else:
                    _, label, exc, tb = item
                    sys.stderr.write(tb)
                    self.set_status(f"Failed: {exc}")
                    messagebox.showerror(APP_NAME, f"{label}\n\n{exc}")
        except queue.Empty:
            pass
        self.root.after(50, self._poll_queue)

    def set_status(self, text):
        self.status_lbl.configure(text=text)

    # ------------------------------------------------------------------ opening files

    def browse(self):
        path = filedialog.askopenfilename(title="Open blackbox log", filetypes=FILETYPES,
                                          initialdir=self.settings.get("last_dir") or None)
        if path:
            self.open_path(path)

    def _refresh_recent_menu(self):
        self.recent_menu.delete(0, tk.END)
        rec = [p for p in self.settings.get("recent", []) if os.path.exists(p)]
        if not rec:
            self.recent_menu.add_command(label="(none)", state=tk.DISABLED)
        for p in rec:
            self.recent_menu.add_command(label=p, command=lambda p=p: self.open_path(p))

    def open_path(self, path):
        if not os.path.isfile(path):
            messagebox.showerror(APP_NAME, f"File not found:\n{path}")
            return
        self.settings.add_recent(path)
        self._refresh_recent_menu()
        self.file_lbl.configure(text=os.path.basename(path))
        ext = os.path.splitext(path)[1].lower()
        if ext in decoder.RAW_EXTENSIONS:
            self.raw_path = path

            def job(p):
                res = decoder.decode_log(p, progress=lambda s: self.q.put(("status", s)))
                headers = logdata.read_log_headers(p)
                return res, headers

            self.run_async(f"Decoding {os.path.basename(path)}...", job, self._on_decoded, path)
        else:
            def job(p):
                sibs = decoder.sibling_csvs(p)
                raw = logdata.find_raw_for_csv(p)
                headers = logdata.read_log_headers(raw) if raw else []
                out = []
                for i, c in enumerate(sibs):
                    ev = c[:-4] + ".event"
                    out.append({"csv": c, "index": self._index_of(c, i + 1),
                                "duration": logdata.quick_duration(c), "start": "", "failed": 0,
                                "event": ev if os.path.isfile(ev) else None, "stats": ""})
                return p, raw, headers, out

            self.run_async(f"Reading {os.path.basename(path)}...", job, self._on_csv_listed, path)

    @staticmethod
    def _index_of(csv, default):
        import re
        m = re.search(r"\.(\d+)\.csv$", csv, re.IGNORECASE)
        return int(m.group(1)) if m else default

    def _on_decoded(self, res):
        result, headers = res
        entries = []
        for log in result.logs:
            entries.append({"csv": log.csv_path, "index": log.index, "duration": log.duration_s,
                            "start": log.start_str, "failed": log.failed_frames, "event": log.event_path,
                            "stats": log.stats_text})
        for e in entries:
            e["headers"] = headers[e["index"] - 1] if 0 < e["index"] <= len(headers) else {}
        self.entries = entries
        cache_note = " (from cache)" if result.from_cache else ""
        self.set_status(f"Decoded {len(entries)} session(s){cache_note}.")
        self._fill_tree(select_csv=None)

    def _on_csv_listed(self, res):
        path, raw, headers, entries = res
        self.raw_path = raw
        for e in entries:
            e["headers"] = headers[e["index"] - 1] if 0 < e["index"] <= len(headers) else {}
        self.entries = entries
        self._fill_tree(select_csv=path)

    def _fill_tree(self, select_csv=None):
        self.tree.delete(*self.tree.get_children())
        thr = float(self.settings["short_threshold_s"])
        hide = self.hide_short_var.get()
        long_ones = [e for e in self.entries if e["duration"] is None or e["duration"] >= thr]
        show = long_ones if (hide and long_ones) else self.entries
        first_long = None
        for e in show:
            short = e["duration"] is not None and e["duration"] < thr
            dur = f"{e['duration']:.1f} s" if e["duration"] is not None else "?"
            note = []
            if e.get("failed"):
                note.append(f"{e['failed']} bad frames")
            if short:
                note.append("short")
            iid = self.tree.insert("", tk.END, text=f"  {e['index']:02d}",
                                   values=(dur, e.get("start", "")[:8], ", ".join(note)),
                                   tags=("short",) if short else ())
            e["iid"] = iid
            if first_long is None and not short:
                first_long = iid
        hidden = len(self.entries) - len(show)
        self.session_lbl.configure(
            text=f"{len(self.entries)} session(s) in log" + (f", {hidden} short hidden" if hidden else ""))
        target = None
        if select_csv:
            target = next((e.get("iid") for e in show
                           if os.path.normcase(e["csv"]) == os.path.normcase(select_csv)), None)
        if target is None:
            # Pick the longest session: that is usually the real flight.
            cands = [e for e in show if e["duration"] is not None]
            target = max(cands, key=lambda e: e["duration"])["iid"] if cands else first_long
        if target:
            self.tree.selection_set(target)
            self.tree.see(target)

    def _on_hide_short(self):
        self.settings["hide_short"] = self.hide_short_var.get()
        self.settings.save()
        cur = self.session.path if self.session else None
        self._fill_tree(select_csv=cur)

    def _on_session_select(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        entry = next((e for e in self.entries if e.get("iid") == sel[0]), None)
        if entry is None:
            return
        if self.session is not None and os.path.normcase(self.session.path) == os.path.normcase(entry["csv"]):
            return
        self.run_async(f"Loading session {entry['index']:02d}...", logdata.build_session, self._on_session_loaded,
                       entry["csv"], entry.get("headers") or {}, entry.get("event"), entry.get("stats", ""))

    def _on_session_loaded(self, s: logdata.Session):
        self.session = s
        if not s.clock_start and self.raw_path is None and s.kind == "inav":
            s.clock_start = logdata.datetime_from_filename(s.path)
        avail = available_presets(s.df.columns)
        self.preset_combo.configure(values=[p.name for p in avail])
        cur = PRESET_BY_KEY.get(self._preset_key())
        if s.kind == "parallax" and cur.key not in ("parallax", "custom"):
            self._set_preset("parallax" if any(p.key == "parallax" for p in avail) else "custom")
        elif cur not in avail:
            self._set_preset(avail[0].key)
        self._refresh_column_list()
        self._fill_spec_list()
        self._fill_info()
        self.replot()
        armed = s.armed_time()
        clock = s.clock_start.strftime("%Y-%m-%d %H:%M:%S") if s.clock_start else "FC clock not set"
        self.set_status(f"{os.path.basename(s.path)}: {len(s.df):,} rows, {s.duration:.1f} s, "
                        f"{s.sample_rate:.0f} Hz" + (f", armed {armed:.1f} s" if armed else "") + f", {clock}")

    # ------------------------------------------------------------------ presets and options

    def _preset_key(self):
        name = self.preset_var.get()
        return next((p.key for p in PRESETS if p.name == name), "overview")

    def _set_preset(self, key):
        p = PRESET_BY_KEY.get(key, PRESETS[0])
        self.preset_var.set(p.name)
        self.preset_desc.configure(text=p.description)
        if hasattr(self, "custom_frame"):
            self._update_custom_visibility()

    def _on_preset_change(self, _evt=None):
        key = self._preset_key()
        self._set_preset(key)
        self.settings["preset"] = key
        self.settings.save()
        self.replot()

    def _update_custom_visibility(self):
        if self._preset_key() == "custom":
            self.custom_frame.pack(fill=tk.BOTH, expand=True, before=self.plot_btn)
        else:
            self.custom_frame.pack_forget()

    def _on_option(self):
        self.settings.update(x_mode=self.x_mode_var.get(), show_modes=self.modes_var.get(),
                             show_events=self.events_var.get(), layout=self.layout_var.get())
        self.settings.save()
        self.replot()

    def _refresh_column_list(self):
        if self.session is None:
            return
        term = self._search_term()
        cols = [c for c in self.session.numeric_columns if not term or term in c.lower()]
        self.visible_columns = cols
        self.col_list.delete(0, tk.END)
        for i, c in enumerate(cols):
            self.col_list.insert(tk.END, c)
            if c in self.custom_selected:
                self.col_list.selection_set(i)
        self._update_custom_count()

    def _on_column_pick(self, _evt=None):
        chosen = {self.visible_columns[i] for i in self.col_list.curselection()}
        for c in self.visible_columns:
            if c in chosen:
                self.custom_selected.add(c)
            else:
                self.custom_selected.discard(c)
        self._update_custom_count()
        self.settings["custom_columns"] = sorted(self.custom_selected)
        if self._replot_job:
            self.root.after_cancel(self._replot_job)
        self._replot_job = self.root.after(250, self.replot)

    def _update_custom_count(self):
        n = len(self.custom_selected)
        self.custom_count.configure(text=f"{n} column(s) selected" if n else "Click columns to plot them")

    def _clear_custom(self):
        self.custom_selected.clear()
        self.col_list.selection_clear(0, tk.END)
        self._update_custom_count()
        self.replot()

    def _custom_panels(self):
        cols = [c for c in self.session.numeric_columns if c in self.custom_selected]
        if not cols:
            return []
        if self.layout_var.get() == "overlay":
            return [Panel("Selected columns", [Series(c, c) for c in cols])]
        return [Panel(c, [Series(c, c)]) for c in cols]

    # ------------------------------------------------------------------ plotting

    def _mpl_colors(self):
        pal = self.pal
        return dict(fig=pal["fig_bg"], ax=pal["plot_bg"], grid=pal["grid"], text=pal["axis"], fg=pal["fg"])

    def _draw_placeholder(self, msg=None):
        self.fig.clear()
        c = self._mpl_colors()
        self.fig.patch.set_facecolor(c["fig"])
        self.fig.text(0.5, 0.55, msg or "Open a blackbox log to start", ha="center", va="center",
                      color=self.pal["muted"], fontsize=15, fontweight="bold")
        if not msg:
            self.fig.text(0.5, 0.47, "Raw .TXT / .BBL logs are decoded automatically.  "
                                     "Decoded INAV CSVs and Parallax telemetry CSVs open directly.",
                          ha="center", va="center", color=self.pal["faint"], fontsize=10)
        self.lines, self.data_axes, self.cursor_lines = [], [], []
        self.canvas.draw_idle()

    def replot(self):
        self._replot_job = None
        s = self.session
        if s is None:
            self._draw_placeholder()
            return
        key = self._preset_key()
        self._update_custom_visibility()
        panels = self._custom_panels() if key == "custom" else resolve_panels(PRESET_BY_KEY[key], s.df.columns)
        if not panels:
            self._draw_placeholder("Pick one or more columns on the left" if key == "custom"
                                   else "This log has none of the columns this view needs")
            self._fill_stats()
            return

        c = self._mpl_colors()
        pal = self.pal
        fig = self.fig
        fig.clear()
        fig.patch.set_facecolor(c["fig"])

        self.x_is_clock = self.x_mode_var.get() == "clock" and s.clock_start is not None
        self.x_base = mdates.date2num(s.clock_start) if self.x_is_clock else 0.0
        xs = self.x_base + s.t / 86400.0 if self.x_is_clock else s.t

        mode_names = []
        if self.modes_var.get() and s.modes:
            order = [m for m in logdata.MODE_ORDER if m in s.modes]
            mode_names = order + [m for m in s.modes if m not in order]
            mode_names = mode_names[:9]
        n = len(panels)
        ratios = ([0.12 + 0.07 * len(mode_names)] if mode_names else []) + [1.0] * n
        axes = fig.subplots(len(ratios), 1, sharex=True, gridspec_kw={"height_ratios": ratios, "hspace": 0.12})
        axes = list(np.atleast_1d(axes))
        strip = axes.pop(0) if mode_names else None

        def style_ax(ax):
            ax.set_facecolor(c["ax"])
            ax.grid(True, color=c["grid"], linewidth=0.6)
            ax.tick_params(colors=c["text"], labelsize=8, length=3)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color(c["grid"])

        self.lines = []
        series_colors = pal["series"]
        for pi, (ax, panel) in enumerate(zip(axes, panels)):
            style_ax(ax)
            for k, ser in enumerate(panel.series):
                y = s.df[ser.column].to_numpy(dtype=np.float64) * ser.scale
                if ser.positive_only:
                    y = np.where(y > 0, y, np.nan)
                ci = pi if len(panel.series) == 1 and key == "custom" else k
                color = series_colors[ci % len(series_colors)]
                dx, dy = analysis.minmax_decimate(xs, y, DISPLAY_POINTS)
                (ln,) = ax.plot(dx, dy, ser.style, color=color, linewidth=1.1, label=ser.label)
                self.lines.append(dict(line=ln, x=xs, y=y, ax=ax, label=ser.label, column=ser.column,
                                       panel=panel.title, color=color))
            ax.set_title(panel.title, loc="left", fontsize=9, color=c["fg"], fontweight="bold", pad=4)
            if panel.ylabel:
                ax.set_ylabel(panel.ylabel, color=c["text"], fontsize=8)
            if panel.ylim:
                ax.set_ylim(*panel.ylim)
            if len(panel.series) > 1:
                leg = ax.legend(loc="upper right", fontsize=7.5, frameon=True, ncol=min(4, len(panel.series)),
                                facecolor=c["fig"], edgecolor=c["grid"], labelcolor=c["fg"], framealpha=0.85)
                leg.set_draggable(True)

        if strip is not None:
            style_ax(strip)
            strip.grid(False)
            for i, m in enumerate(mode_names):
                spans = s.modes[m]
                col = pal["modes"].get(m, pal["series"][i % len(pal["series"])])
                bars = []
                for a, b in spans:
                    if self.x_is_clock:
                        a, b = self.x_base + a / 86400.0, self.x_base + b / 86400.0
                    bars.append((a, max(b - a, 1e-9)))
                strip.broken_barh(bars, (i - 0.38, 0.76), facecolors=col, alpha=0.85)
            strip.set_yticks(range(len(mode_names)))
            strip.set_yticklabels([logdata.MODE_LABELS.get(m, m) for m in mode_names], fontsize=7,
                                  color=c["text"])
            strip.set_ylim(len(mode_names) - 0.5, -0.5)
            strip.tick_params(axis="y", length=0)
            strip.set_title("Flight modes", loc="left", fontsize=9, color=c["fg"], fontweight="bold", pad=4)

        all_axes = ([strip] if strip is not None else []) + axes
        if self.events_var.get() and s.events:
            for t_ev, name in s.events[:60]:
                xe = self.x_base + t_ev / 86400.0 if self.x_is_clock else t_ev
                if t_ev < -1 or t_ev > s.duration + 1:
                    continue
                for ax in all_axes:
                    ax.axvline(xe, color=pal["event"], linewidth=0.8, linestyle=":", alpha=0.9)
                top = all_axes[0]
                top.annotate(name, xy=(xe, 1.0), xycoords=("data", "axes fraction"), xytext=(2, 2),
                             textcoords="offset points", fontsize=7, color=pal["event"], rotation=0,
                             annotation_clip=True)

        last = axes[-1]
        if self.x_is_clock:
            last.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            last.set_xlabel("Clock time", color=c["text"], fontsize=8)
        else:
            last.set_xlabel("Elapsed time (s)", color=c["text"], fontsize=8)
        last.set_xlim(xs[0], xs[-1])

        self.data_axes = axes
        self.cursor_lines = [ax.axvline(xs[0], color=pal["muted"], linewidth=0.8, visible=False)
                             for ax in all_axes]
        for ax in all_axes:
            ax.callbacks.connect("xlim_changed", self._on_xlim)
        fig.subplots_adjust(left=0.065, right=0.985, top=0.965, bottom=0.07)
        self.canvas.draw_idle()
        self._on_xlim(None)
        self.readout.configure(text="  Hover the plot for values.  Scroll to zoom time, drag with the pan tool, "
                                    "Home resets.")

    def reset_zoom(self):
        if self.lines:
            x = self.lines[0]["x"]
            self.data_axes[-1].set_xlim(x[0], x[-1])
            for ax in self.data_axes:
                ax.relim()
                ax.autoscale_view(scalex=False)
            self.canvas.draw_idle()

    def _on_scroll(self, event):
        if event.inaxes is None or not self.data_axes or event.xdata is None:
            return
        ax = self.data_axes[-1]
        lo, hi = ax.get_xlim()
        factor = 0.8 if event.button == "up" else 1.25
        x = event.xdata
        ax.set_xlim(x - (x - lo) * factor, x + (hi - x) * factor)
        self.canvas.draw_idle()

    def _on_xlim(self, _ax):
        if self._xlim_job:
            self.root.after_cancel(self._xlim_job)
        self._xlim_job = self.root.after(80, self._refresh_visible)

    def _x_to_t(self, x):
        return (x - self.x_base) * 86400.0 if self.x_is_clock else x

    def _refresh_visible(self):
        self._xlim_job = None
        if not self.lines:
            return
        lo, hi = self.data_axes[-1].get_xlim()
        for d in self.lines:
            sl = analysis.visible_slice(d["x"], lo, hi)
            dx, dy = analysis.minmax_decimate(d["x"][sl], d["y"][sl], DISPLAY_POINTS)
            d["line"].set_data(dx, dy)
        self.visible_range = (self._x_to_t(lo), self._x_to_t(hi))
        self.canvas.draw_idle()
        self._fill_stats()

    def _hide_cursor(self):
        for ln in self.cursor_lines:
            ln.set_visible(False)
        self.canvas.draw_idle()

    def _on_motion(self, event):
        self._last_motion = event
        if self._motion_job is None:
            self._motion_job = self.root.after(30, self._update_cursor)

    def _update_cursor(self):
        self._motion_job = None
        ev = self._last_motion
        if ev is None or ev.inaxes is None or ev.xdata is None or not self.lines:
            return
        x = ev.xdata
        for ln in self.cursor_lines:
            ln.set_xdata([x, x])
            ln.set_visible(True)
        t = self._x_to_t(x)
        parts = []
        if self.x_is_clock:
            stamp = self.session.clock_start + _dt.timedelta(seconds=float(t))
            parts.append(stamp.strftime("%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}")
        parts.append(f"t={t:8.3f}s")
        target_ax = ev.inaxes if ev.inaxes in self.data_axes else None
        for d in self.lines:
            if target_ax is not None and d["ax"] is not target_ax:
                continue
            i = int(np.clip(np.searchsorted(d["x"], x), 0, len(d["x"]) - 1))
            v = d["y"][i]
            parts.append(f"{d['label']}={v:.4g}" if np.isfinite(v) else f"{d['label']}=n/a")
            if len(parts) > 10:
                parts.append("...")
                break
        self.readout.configure(text="  " + "   ".join(parts))
        self.canvas.draw_idle()

    # ------------------------------------------------------------------ statistics / export

    def _fill_stats(self):
        self.stats_tree.delete(*self.stats_tree.get_children())
        if not self.lines or self.session is None:
            return
        lo, hi = self.data_axes[-1].get_xlim()
        t0, t1 = self.visible_range
        self.stats_range_lbl.configure(text=f"Visible range {t0:.2f} s to {t1:.2f} s  ({t1 - t0:.2f} s)")
        fmt = lambda v: "" if not np.isfinite(v) else f"{v:.4g}"  # noqa: E731

        def add(text, panel, st, tags=()):
            self.stats_tree.insert("", tk.END, text=text, tags=tags,
                                   values=(panel, fmt(st["min"]), fmt(st["max"]), fmt(st["mean"]),
                                           fmt(st["std"]), fmt(st["rms"]), fmt(st["p2p"]), st["n"]))

        by_panel: dict = {}
        for d in self.lines:
            by_panel.setdefault(d["panel"], []).append(d)
            sl = analysis.visible_slice(d["x"], lo, hi)
            add(d["label"] if d["label"] == d["column"] else f"{d['label']}  ({d['column']})",
                d["panel"], analysis.describe(d["y"][sl]))
        # Tracking error rows: how far the measured value is from what was commanded.
        pairs = ({"Setpoint", "Gyro"}, {"Estimated", "Target"})
        self.stats_tree.tag_configure("err", foreground=self.pal["warn"])
        for panel, ds in by_panel.items():
            labels = {d["label"]: d for d in ds}
            for pair in pairs:
                if pair <= set(labels):
                    want, got = (labels["Setpoint"], labels["Gyro"]) if "Gyro" in pair else \
                        (labels["Target"], labels["Estimated"])
                    sl = analysis.visible_slice(got["x"], lo, hi)
                    add(f"Tracking error ({got['label']} minus {want['label']})", panel,
                        analysis.describe(got["y"][sl] - want["y"][sl]), ("err",))

    def copy_stats(self):
        rows = ["series\tpanel\tmin\tmax\tmean\tstd\trms\tp2p\tn"]
        for iid in self.stats_tree.get_children():
            item = self.stats_tree.item(iid)
            rows.append("\t".join([item["text"]] + [str(v) for v in item["values"]]))
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(rows))
        self.set_status("Statistics copied to clipboard (tab separated).")

    def export_visible(self):
        if self.session is None or not self.lines:
            messagebox.showinfo(APP_NAME, "Plot something first.")
            return
        s = self.session
        lo, hi = self.data_axes[-1].get_xlim()
        sl = analysis.visible_slice(self.lines[0]["x"], lo, hi)
        cols = []
        for d in self.lines:
            if d["column"] not in cols:
                cols.append(d["column"])
        base = os.path.splitext(os.path.basename(s.path))[0]
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=f"{base}_selection.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        out = s.df.iloc[sl][cols].copy()
        out.insert(0, "t_s", s.t[sl])
        time_cols = [c for c in ("time (us)",) if c in s.df.columns]
        for tc in time_cols:
            out.insert(1, tc, s.df[tc].iloc[sl].to_numpy())
        out.to_csv(path, index=False)
        self.set_status(f"Exported {len(out):,} rows x {len(cols)} columns to {os.path.basename(path)}")

    def save_plot(self):
        if not self.lines:
            messagebox.showinfo(APP_NAME, "There is no plot to save yet.")
            return
        base = os.path.splitext(os.path.basename(self.session.path))[0]
        path = filedialog.asksaveasfilename(defaultextension=".png", initialfile=f"{base}_{self._preset_key()}.png",
                                            filetypes=[("PNG image", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")])
        if path:
            self.fig.savefig(path, dpi=200, facecolor=self.fig.get_facecolor())
            self.set_status(f"Saved {os.path.basename(path)}")

    # ------------------------------------------------------------------ spectrum

    def _fill_spec_list(self):
        s = self.session
        self.spec_list.delete(0, tk.END)
        if s is None:
            return
        prefer = [c for c in s.numeric_columns if c.startswith(("gyro", "axisRate", "accSmooth", "motor", "axisD"))]
        rest = [c for c in s.numeric_columns if c not in prefer]
        self.spec_cols = prefer + rest
        defaults = {"gyroADC[0]", "gyroADC[1]", "gyroADC[2]"}
        for i, c in enumerate(self.spec_cols):
            self.spec_list.insert(tk.END, c)
            if c in defaults:
                self.spec_list.selection_set(i)

    def compute_spectrum(self):
        s = self.session
        if s is None:
            return
        cols = [self.spec_cols[i] for i in self.spec_list.curselection()]
        if not cols:
            messagebox.showinfo(APP_NAME, "Select at least one signal.")
            return
        if self.spec_visible_var.get() and self.lines:
            t0, t1 = self.visible_range
        else:
            t0, t1 = s.t[0], s.t[-1]
        sl = analysis.visible_slice(s.t, t0, t1)
        seg = int(self.seg_var.get())
        fs = s.sample_rate
        c = self._mpl_colors()
        fig = self.spec_fig
        fig.clear()
        fig.patch.set_facecolor(c["fig"])
        ax = fig.add_subplot(111)
        ax.set_facecolor(c["ax"])
        ax.grid(True, color=c["grid"], linewidth=0.6)
        ax.tick_params(colors=c["text"], labelsize=8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(c["grid"])
        notes = []
        for k, col in enumerate(cols):
            y = s.df[col].to_numpy(dtype=np.float64)[sl]
            f, p = analysis.welch_psd(y, fs, seg)
            if len(f) == 0:
                continue
            peaks = analysis.dominant_peaks(f, p, 3, min_hz=40.0)
            label = col + ("  peaks " + ", ".join(f"{q[0]:.0f}" for q in peaks) + " Hz" if peaks else "")
            ax.plot(f, p, color=self.pal["series"][k % len(self.pal["series"])], linewidth=1.1, label=label)
            notes.append(f"{col}: " + (", ".join(f"{q[0]:.0f} Hz" for q in peaks) or "no clear peak"))
        ax.set_xlabel("Frequency (Hz)", color=c["text"], fontsize=8)
        ax.set_ylabel("Power spectral density (dB)", color=c["text"], fontsize=8)
        ax.set_xlim(0, fs / 2 if fs else None)
        ax.set_title(f"Spectrum, {t1 - t0:.1f} s window, fs = {fs:.0f} Hz, segment {seg}",
                     loc="left", fontsize=9, color=c["fg"], fontweight="bold")
        ax.legend(loc="upper right", fontsize=8, facecolor=c["fig"], edgecolor=c["grid"], labelcolor=c["fg"])
        fig.subplots_adjust(left=0.08, right=0.98, top=0.93, bottom=0.1)
        self.spec_canvas.draw_idle()
        self.spec_info.configure(text="Strongest peaks above 40 Hz\n" + "\n".join(notes) +
                                 f"\n\nResolution {fs / seg:.1f} Hz per bin. Below 40 Hz is mostly "
                                 "pilot / controller motion.")

    # ------------------------------------------------------------------ session info

    def _fill_info(self):
        s = self.session
        t = self.info_text
        t.configure(state=tk.NORMAL)
        t.delete("1.0", tk.END)
        if s is None:
            return
        lines = [
            ("File", s.path),
            ("Format", {"inav": "INAV blackbox (decoded)", "parallax": "Parallax telemetry CSV",
                        "generic": "Generic CSV"}[s.kind]),
            ("Rows / columns", f"{len(s.df):,} / {len(s.df.columns)}"),
            ("Duration", f"{s.duration:.2f} s at {s.sample_rate:.0f} Hz"),
            ("Armed time", f"{s.armed_time():.1f} s" if s.modes.get("ARM") else "not armed / unknown"),
            ("Log start", s.clock_start.strftime("%Y-%m-%d %H:%M:%S") if s.clock_start
             else (s.headers.get("Log start datetime", "") + "  (clock not set on FC)").strip()),
            ("Events", ", ".join(sorted({n for _, n in s.events})) or "none"),
        ] + logdata.summarize_headers(s.headers)
        width = max(len(k) for k, _ in lines) + 2
        for k, v in lines:
            t.insert(tk.END, f"{k:<{width}}{v}\n")
        if s.decoder_stats:
            t.insert(tk.END, "\nDecoder report\n" + s.decoder_stats + "\n")
        t.configure(state=tk.DISABLED)
        self._fill_headers()

    def _fill_headers(self):
        self.hdr_tree.delete(*self.hdr_tree.get_children())
        if self.session is None:
            return
        term = self.hdr_search.get().strip().lower()
        for k, v in self.session.headers.items():
            if term and term not in k.lower() and term not in v.lower():
                continue
            self.hdr_tree.insert("", tk.END, text=k, values=(v,))

    # ------------------------------------------------------------------ misc actions

    def _theme_btn_text(self):
        return "Light mode" if self.settings["theme"] == "dark" else "Dark mode"

    def _flip_theme(self):
        self.theme_var.set("light" if self.settings["theme"] == "dark" else "dark")
        self.toggle_theme()

    def toggle_theme(self):
        name = self.theme_var.get()
        self.settings["theme"] = name
        self.settings.save()
        self.pal = apply_style(self.root, name)
        for lb in (self.col_list, self.spec_list):
            self._style_listbox(lb)
        self.tree.tag_configure("short", foreground=self.pal["faint"])
        self._style_text()
        self._style_toolbar()
        self.theme_btn.configure(text=self._theme_btn_text())
        set_windows_titlebar(self.root, name == "dark")
        if self.session is not None:
            self.replot()
        else:
            self._draw_placeholder()

    def show_decoded_folder(self):
        folder = os.path.dirname(self.session.path) if self.session else decoder.cache_root()
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:  # noqa: BLE001
            messagebox.showinfo(APP_NAME, f"Decoded files are in:\n{folder}\n\n({exc})")

    def clear_cache(self):
        mb = decoder.cache_size_bytes() / 1e6
        if messagebox.askyesno(APP_NAME, f"Delete all decoded CSVs from the cache ({mb:.0f} MB)?\n"
                                         "Logs will be decoded again next time you open them."):
            self.session = None
            decoder.clear_cache()
            self.entries = []
            self.tree.delete(*self.tree.get_children())
            self._draw_placeholder()
            self.set_status("Cache cleared.")

    def show_shortcuts(self):
        messagebox.showinfo(APP_NAME, "Ctrl+O   Open log\nCtrl+S   Save plot image\nCtrl+E   Export visible "
                                      "range to CSV\nF5       Redraw\nHome     Reset zoom\nMouse wheel over plot   "
                                      "Zoom time axis\nToolbar  Pan / box zoom")

    def show_about(self):
        dec = decoder.find_decoder()
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME} {__version__}\n\nBuilt by Shay Colaco for ASCEND / Team Parallax.\n\n"
            f"Decoding uses INAV blackbox_decode (blackbox-tools by Nicholas Sherlock and the INAV team, GPLv3).\n\n"
            f"Decoder: {dec or 'not found'}\nCache: {decoder.cache_root()}")

    def _on_close(self):
        self.settings["custom_columns"] = sorted(self.custom_selected)
        self.settings.save()
        self.root.destroy()


def _enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _enable_dpi_awareness()
    root = tk.Tk()
    try:
        icon = os.path.join(decoder.app_base_dir(), "assets", "icon.png")
        if os.path.isfile(icon):
            root.iconphoto(True, tk.PhotoImage(file=icon))
    except Exception:
        pass
    App(root, argv[0] if argv else None)
    root.mainloop()


if __name__ == "__main__":
    main()
