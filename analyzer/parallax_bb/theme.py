"""Colour palettes and ttk styling for dark and light modes."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

PALETTES = {
    "dark": {
        "bg": "#0e1116", "panel": "#151a21", "card": "#1b222b", "field": "#0f141a",
        "fg": "#e6e9ee", "muted": "#8a94a3", "faint": "#5a6472", "border": "#2a333f",
        "accent": "#4f8cff", "accent_hover": "#3b78ee", "accent_fg": "#ffffff",
        "select": "#24406e", "warn": "#f6c560",
        "plot_bg": "#11161c", "fig_bg": "#151a21", "grid": "#2a333f", "axis": "#8a94a3",
        "series": ["#7aa2ff", "#ff7a90", "#5fd3a4", "#f6c560", "#c792ea", "#4fd1e8",
                   "#ff9e64", "#a3be8c"],
        "modes": {"ARM": "#5fd3a4", "ANGLE": "#7aa2ff", "HORIZON": "#7aa2ff",
                  "NAVALTHOLD": "#f6c560", "SURFACE": "#ff9e64", "NAVPOSHOLD": "#c792ea",
                  "HEADINGHOLD": "#4fd1e8", "NAVRTH": "#ff7a90", "NAVWP": "#ff7a90",
                  "FAILSAFE": "#ff4d5e"},
        "event": "#ff9e64",
    },
    "light": {
        "bg": "#f4f6f9", "panel": "#ffffff", "card": "#ffffff", "field": "#ffffff",
        "fg": "#1b2330", "muted": "#5d6878", "faint": "#9aa4b2", "border": "#d8dee6",
        "accent": "#2f6fe4", "accent_hover": "#245dc7", "accent_fg": "#ffffff",
        "select": "#d6e4ff", "warn": "#b7791f",
        "plot_bg": "#ffffff", "fig_bg": "#ffffff", "grid": "#e3e7ed", "axis": "#5d6878",
        "series": ["#2f5fd0", "#d6335a", "#1f9d6b", "#c48a0a", "#8a4fd0", "#0b8fb0",
                   "#d9601a", "#5f7f3f"],
        "modes": {"ARM": "#1f9d6b", "ANGLE": "#2f5fd0", "HORIZON": "#2f5fd0",
                  "NAVALTHOLD": "#c48a0a", "SURFACE": "#d9601a", "NAVPOSHOLD": "#8a4fd0",
                  "HEADINGHOLD": "#0b8fb0", "NAVRTH": "#d6335a", "NAVWP": "#d6335a",
                  "FAILSAFE": "#e5132b"},
        "event": "#d9601a",
    },
}

if sys.platform == "win32":
    UI_FONT = "Segoe UI"
    MONO_FONT = "Consolas"
elif sys.platform == "darwin":
    UI_FONT = "Helvetica Neue"
    MONO_FONT = "Menlo"
else:
    UI_FONT = "DejaVu Sans"
    MONO_FONT = "DejaVu Sans Mono"


def apply_style(root: tk.Tk, name: str) -> dict:
    pal = PALETTES[name]
    st = ttk.Style(root)
    st.theme_use("clam")
    f = (UI_FONT, 10)
    root.configure(background=pal["bg"])

    st.configure(".", background=pal["bg"], foreground=pal["fg"], fieldbackground=pal["field"],
                 bordercolor=pal["border"], lightcolor=pal["border"], darkcolor=pal["border"],
                 troughcolor=pal["panel"], focuscolor=pal["accent"], selectbackground=pal["select"],
                 selectforeground=pal["fg"], insertcolor=pal["fg"], font=f)
    st.configure("TFrame", background=pal["bg"])
    st.configure("Side.TFrame", background=pal["panel"])
    st.configure("Card.TFrame", background=pal["panel"])
    st.configure("Header.TFrame", background=pal["panel"])
    st.configure("TLabel", background=pal["bg"], foreground=pal["fg"])
    st.configure("Side.TLabel", background=pal["panel"], foreground=pal["fg"])
    st.configure("Muted.TLabel", background=pal["panel"], foreground=pal["muted"], font=(UI_FONT, 9))
    st.configure("Section.TLabel", background=pal["panel"], foreground=pal["muted"],
                 font=(UI_FONT, 8, "bold"))
    st.configure("Title.TLabel", background=pal["panel"], foreground=pal["fg"], font=(UI_FONT, 12, "bold"))
    st.configure("Accent.TLabel", background=pal["panel"], foreground=pal["accent"], font=(UI_FONT, 12, "bold"))
    st.configure("File.TLabel", background=pal["panel"], foreground=pal["muted"], font=(UI_FONT, 9))
    st.configure("Status.TLabel", background=pal["panel"], foreground=pal["muted"], font=(UI_FONT, 9))
    st.configure("Readout.TLabel", background=pal["bg"], foreground=pal["fg"], font=(MONO_FONT, 9))
    st.configure("Placeholder.TLabel", background=pal["bg"], foreground=pal["faint"], font=(UI_FONT, 12))

    st.configure("TButton", background=pal["card"], foreground=pal["fg"], bordercolor=pal["border"],
                 padding=(10, 5), relief="flat", font=(UI_FONT, 9))
    st.map("TButton", background=[("pressed", pal["border"]), ("active", pal["border"])],
           foreground=[("disabled", pal["faint"])])
    st.configure("Accent.TButton", background=pal["accent"], foreground=pal["accent_fg"],
                 bordercolor=pal["accent"], padding=(12, 7), font=(UI_FONT, 10, "bold"))
    st.map("Accent.TButton", background=[("pressed", pal["accent_hover"]), ("active", pal["accent_hover"])])

    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, background=pal["panel"], foreground=pal["fg"], font=(UI_FONT, 9),
                     indicatorbackground=pal["field"], indicatorforeground=pal["accent"])
        st.map(w, background=[("active", pal["panel"])],
               indicatorbackground=[("selected", pal["accent"]), ("active", pal["card"])],
               indicatorforeground=[("selected", pal["accent_fg"])])

    st.configure("TEntry", fieldbackground=pal["field"], foreground=pal["fg"], padding=4)
    st.configure("TCombobox", fieldbackground=pal["field"], background=pal["card"], foreground=pal["fg"],
                 arrowcolor=pal["muted"], padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", pal["field"])],
           foreground=[("readonly", pal["fg"])], selectbackground=[("readonly", pal["field"])],
           selectforeground=[("readonly", pal["fg"])])
    root.option_add("*TCombobox*Listbox.background", pal["card"])
    root.option_add("*TCombobox*Listbox.foreground", pal["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", pal["select"])
    root.option_add("*TCombobox*Listbox.selectForeground", pal["fg"])

    st.configure("Treeview", background=pal["field"], fieldbackground=pal["field"], foreground=pal["fg"],
                 bordercolor=pal["border"], rowheight=24, font=(UI_FONT, 9))
    st.map("Treeview", background=[("selected", pal["select"])], foreground=[("selected", pal["fg"])])
    st.configure("Treeview.Heading", background=pal["card"], foreground=pal["muted"], relief="flat",
                 font=(UI_FONT, 8, "bold"), padding=(6, 4))
    st.map("Treeview.Heading", background=[("active", pal["border"])])

    st.configure("TNotebook", background=pal["bg"], borderwidth=0, tabmargins=(8, 6, 8, 0))
    st.configure("TNotebook.Tab", background=pal["bg"], foreground=pal["muted"], padding=(14, 6),
                 borderwidth=0, font=(UI_FONT, 9, "bold"))
    st.map("TNotebook.Tab", background=[("selected", pal["panel"])],
           foreground=[("selected", pal["fg"])])

    st.configure("TScrollbar", background=pal["card"], troughcolor=pal["panel"], bordercolor=pal["panel"],
                 arrowcolor=pal["muted"], relief="flat")
    st.configure("TProgressbar", background=pal["accent"], troughcolor=pal["card"], bordercolor=pal["card"],
                 lightcolor=pal["accent"], darkcolor=pal["accent"])
    st.configure("TPanedwindow", background=pal["border"])
    st.configure("Sash", sashthickness=4)
    st.configure("TSeparator", background=pal["border"])
    return pal


def set_windows_titlebar(root: tk.Tk, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val),
                                                         ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass
