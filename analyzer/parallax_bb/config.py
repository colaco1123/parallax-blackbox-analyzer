"""Small JSON settings file kept in the user's app-data folder."""

from __future__ import annotations

import json
import os

from parallax_bb.decoder import user_data_dir

DEFAULTS = {
    "theme": "dark",
    "x_mode": "elapsed",          # elapsed | clock
    "show_modes": True,
    "show_events": True,
    "hide_short": True,
    "short_threshold_s": 2.0,
    "layout": "stacked",          # stacked | overlay (custom preset)
    "preset": "overview",
    "last_dir": "",
    "recent": [],
    "custom_columns": [],
}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = os.path.join(user_data_dir(), "settings.json")
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self.update({k: v for k, v in data.items() if k in DEFAULTS})
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(dict(self), fh, indent=2)
        except Exception:
            pass

    def add_recent(self, path: str):
        rec = [p for p in self.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
        rec.insert(0, path)
        self["recent"] = rec[:8]
        self["last_dir"] = os.path.dirname(path)
        self.save()
