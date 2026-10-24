"""Loading decoded CSVs and the metadata that goes with them."""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# Flight modes worth drawing in the mode strip, in display order.
MODE_ORDER = [
    "ARM", "ANGLE", "HORIZON", "NAVALTHOLD", "SURFACE", "NAVPOSHOLD", "HEADINGHOLD",
    "NAVRTH", "NAVWP", "NAVCRUISE", "NAVCOURSEHOLD", "NAVLAUNCH", "MANUAL",
    "TURTLE", "FAILSAFE",
]

MODE_LABELS = {
    "NAVALTHOLD": "ALT HOLD", "NAVPOSHOLD": "POS HOLD", "HEADINGHOLD": "HDG HOLD",
    "NAVRTH": "RTH", "NAVWP": "WAYPOINT", "NAVCRUISE": "CRUISE", "NAVCOURSEHOLD": "COURSE",
    "NAVLAUNCH": "LAUNCH",
}

TIME_COLUMNS =("time (us)", "time (s)", "iso_time", "t_ms", "dateTime", "loopIteration")


# --------------------------------------------------------------------------- headers

def read_log_headers(raw_path: str) -> list:
    """Return one dict of 'H key:value' headers per log contained in a raw file."""
    try:
        with open(raw_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return []
    out = []
    marker = b"H Product:"
    starts = [m.start() for m in re.finditer(re.escape(marker), data)]
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(data)
        chunk = data[s:min(end, s + 64000)]
        headers = {}
        for raw_line in chunk.split(b"\n"):
            if not raw_line.startswith(b"H "):
                if headers and raw_line[:1] not in (b"H",):
                    # headers are contiguous; stop at first binary frame
                    break
                continue
            line = raw_line[2:].decode("latin-1", errors="replace").rstrip("\r")
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        out.append(headers)
    return out


def find_raw_for_csv(csv_path: str) -> Optional[str]:
    """Locate the raw log a decoded CSV came from (same folder or parent)."""
    m = re.match(r"(.*)\.\d{2,}\.csv$", os.path.basename(csv_path), re.IGNORECASE)
    if not m:
        return None
    root = m.group(1)
    folder = os.path.dirname(csv_path)
    for d in (folder, os.path.dirname(folder)):
        for ext in (".TXT", ".txt", ".BBL", ".bbl", ".BFL", ".bfl"):
            cand = os.path.join(d, root + ext)
            if os.path.isfile(cand):
                return cand
    return None


def parse_log_datetime(headers: dict) -> Optional[_dt.datetime]:
    """Log start time from headers, or None when the FC clock was clearly unset."""
    val = headers.get("Log start datetime", "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", val)
    if not m:
        return None
    try:
        dt = _dt.datetime(*[int(g) for g in m.groups()])
    except ValueError:
        return None
    # FCs without RTC/GPS time report 0000-01-01 or a garbage future date.
    if dt.year < 2015 or dt > _dt.datetime.now() + _dt.timedelta(days=2):
        return None
    return dt


def datetime_from_filename(path: str) -> Optional[_dt.datetime]:
    m = re.search(r"(\d{4}-\d{2}-\d{2})[_T](\d{2})[-:]?(\d{2})[-:]?(\d{2})", os.path.basename(path))
    if not m:
        return None
    try:
        return _dt.datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}",
                                     "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def summarize_headers(h: dict) -> list:
    """Short human-readable list of (label, value) from INAV headers."""
    rows = []

    def add(label, key, fmt=None):
        if key in h and h[key] != "":
            rows.append((label, fmt(h[key]) if fmt else h[key]))

    add("Firmware", "Firmware revision")
    add("Craft", "Craft name")
    add("Looptime", "looptime", lambda v: f"{v} us")
    add("Log rate", "P interval")
    for axis in ("roll", "pitch", "yaw"):
        key = f"{axis}PID"
        if key in h:
            vals = h[key].split(",")
            names = ["P", "I", "D", "FF"]
            rows.append((f"{axis.capitalize()} PID",
                         "  ".join(f"{n}={v}" for n, v in zip(names, vals))))
    for key, label in (("levelPID", "Level PID"), ("altPID", "Alt PID"),
                       ("velPID", "Vel PID"), ("posPID", "Pos PID"), ("posrPID", "PosR PID")):
        add(label, key, lambda v: v.replace(",", " / "))
    add("Gyro LPF", "gyro_lpf_hz", lambda v: f"{v} Hz")
    add("D-term LPF", "dterm_lpf_hz", lambda v: f"{v} Hz")
    add("Dyn notch min", "dynamicGyroNotchMinHz", lambda v: f"{v} Hz")
    add("Motor protocol", "motor_pwm_protocol")
    add("Motor output", "motorOutput", lambda v: v.replace(",", " to "))
    add("Debug mode", "debug_mode")
    return rows


# --------------------------------------------------------------------------- events

def read_events(event_path: Optional[str]) -> list:
    """Parse the decoder's JSON-lines .event file into (time_us, name, raw) tuples."""
    if not event_path or not os.path.isfile(event_path):
        return []
    events = []
    with open(event_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            t = obj.get("time")
            if t is None:
                continue
            name = obj.get("name", "event")
            extra = {k: v for k, v in obj.items() if k not in ("time", "name")}
            if extra:
                name += " " + ", ".join(f"{k}={v}" for k, v in extra.items())
            events.append((float(t), name, obj))
    # Decoders sometimes duplicate the same event; keep unique ones.
    seen, uniq = set(), []
    for e in events:
        key = (e[0], e[1])
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return uniq


# --------------------------------------------------------------------------- data

def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, skipinitialspace=True, low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c and not c.startswith("Unnamed")]]
    for c in df.columns:
        if df[c].dtype == np.float64:
            df[c] = df[c].astype(np.float32)
    return df


def detect_kind(columns) -> str:
    cols = set(columns)
    if "time (us)" in cols or "time (s)" in cols:
        return "inav"
    if "iso_time" in cols or "t_ms" in cols:
        return "parallax"
    return "generic"


def flag_spans(t: np.ndarray, flags: pd.Series) -> dict:
    """Map mode name -> list of (t_start, t_end) where that flag is set."""
    if flags is None or len(flags) == 0:
        return {}
    s = flags.astype(str).fillna("")
    tokens = sorted({tok for v in s.unique() for tok in re.split(r"[|\s]+", v)
                     if tok and tok != "0" and not tok.isdigit()})
    spans = {}
    for tok in tokens:
        active = s.str.contains(rf"(?:^|\|){re.escape(tok)}(?:\||$)", regex=True).to_numpy()
        if not active.any():
            continue
        edges = np.diff(np.concatenate(([0], active.astype(np.int8), [0])))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1) - 1
        spans[tok] = [(float(t[a]), float(t[b])) for a, b in zip(starts, ends)]
    return spans


@dataclass
class Session:
    path: str
    df: pd.DataFrame
    kind: str
    t: np.ndarray                     # seconds since session start
    t0_raw: float = 0.0               # raw first timestamp (us for INAV)
    clock_start: Optional[_dt.datetime] = None
    headers: dict = field(default_factory=dict)
    events: list = field(default_factory=list)   # (t_seconds, name)
    modes: dict = field(default_factory=dict)
    numeric_columns: list = field(default_factory=list)
    sample_rate: float = 0.0
    decoder_stats: str = ""

    @property
    def duration(self) -> float:
        return float(self.t[-1] - self.t[0]) if len(self.t) > 1 else 0.0

    def clock_times(self) -> Optional[np.ndarray]:
        if self.clock_start is None:
            return None
        base = np.datetime64(self.clock_start, "us")
        return base + (self.t * 1e6).astype("timedelta64[us]")

    def armed_time(self) -> float:
        return sum(b - a for a, b in self.modes.get("ARM", []))


def build_session(path: str, headers: Optional[dict] = None, event_path: Optional[str] = None,
                  decoder_stats: str = "") -> Session:
    df = load_csv(path)
    kind = detect_kind(df.columns)
    headers = headers or {}
    clock = None
    t0_raw = 0.0

    if kind == "inav":
        if "time (us)" in df.columns:
            raw = df["time (us)"].to_numpy(dtype=np.float64)
            t = (raw - raw[0]) / 1e6
        else:
            raw = df["time (s)"].to_numpy(dtype=np.float64) * 1e6
            t = (raw - raw[0]) / 1e6
        t0_raw = float(raw[0]) if len(raw) else 0.0
        start = parse_log_datetime(headers)
        if start is not None:
            # 'Log start datetime' corresponds to the log's first frame time.
            clock = start
    elif kind == "parallax":
        t = None
        if "t_ms" in df.columns:
            raw = df["t_ms"].to_numpy(dtype=np.float64)
            t = (raw - raw[0]) / 1000.0
        if "iso_time" in df.columns:
            ts = pd.to_datetime(df["iso_time"], errors="coerce")
            ok = ts.notna().to_numpy()
            if ok.sum() > 1:
                first = ts[ok].iloc[0]
                clock = first.to_pydatetime().replace(tzinfo=None)
                if t is None:
                    secs = (ts - first).dt.total_seconds().to_numpy(dtype=np.float64)
                    idx = np.arange(len(secs))
                    t = np.interp(idx, idx[ok], secs[ok])
        if t is None:
            t = np.arange(len(df), dtype=np.float64)
    else:
        t = np.arange(len(df), dtype=np.float64)
        clock = None

    numeric = [c for c in df.columns
               if c not in TIME_COLUMNS and pd.api.types.is_numeric_dtype(df[c])]

    modes = {}
    if "flightModeFlags (flags)" in df.columns:
        modes = flag_spans(t, df["flightModeFlags (flags)"])
    if "failsafePhase (flags)" in df.columns:
        fs = df["failsafePhase (flags)"].astype(str)
        active = (~fs.isin(["IDLE", "0", "nan"])).to_numpy()
        if active.any():
            edges = np.diff(np.concatenate(([0], active.astype(np.int8), [0])))
            st = np.flatnonzero(edges == 1)
            en = np.flatnonzero(edges == -1) - 1
            modes["FAILSAFE"] = [(float(t[a]), float(t[b])) for a, b in zip(st, en)]

    events = []
    if kind == "inav":
        for t_us, name, _ in read_events(event_path):
            events.append(((t_us - t0_raw) / 1e6, name))

    dt = np.diff(t)
    dt = dt[dt > 0]
    rate = float(1.0 / np.median(dt)) if len(dt) else 0.0

    return Session(path=path, df=df, kind=kind, t=t, t0_raw=t0_raw, clock_start=clock,
                   headers=headers, events=events, modes=modes, numeric_columns=numeric,
                   sample_rate=rate, decoder_stats=decoder_stats)


def quick_duration(csv_path: str) -> Optional[float]:
    """Cheap duration estimate for a CSV without parsing every column."""
    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as fh:
            header = [h.strip() for h in fh.readline().split(",")]
            first = fh.readline().split(",")
        if "time (us)" not in header:
            return None
        idx = header.index("time (us)")
        t_first = float(first[idx])
        with open(csv_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 8192))
            tail = fh.read().decode("utf-8", errors="replace").strip().splitlines()
        for line in reversed(tail):
            parts = line.split(",")
            if len(parts) > idx:
                try:
                    return (float(parts[idx]) - t_first) / 1e6
                except ValueError:
                    continue
    except Exception:
        return None
    return None
