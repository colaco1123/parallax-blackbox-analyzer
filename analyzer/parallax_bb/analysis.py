"""Numerical helpers: display decimation, statistics and spectra."""

from __future__ import annotations

import numpy as np


def minmax_decimate(x: np.ndarray, y: np.ndarray, max_points: int = 4000):
    """Reduce a series for display while keeping every spike visible.

    Splits the data into buckets and keeps the min and max sample of each one,
    in time order, so peaks survive at any zoom level.
    """
    n = len(x)
    if n <= max_points:
        return x, y
    buckets = max(1, max_points // 2)
    size = n // buckets
    if size < 2:
        return x, y
    usable = buckets * size
    yb = y[:usable].reshape(buckets, size)
    with np.errstate(invalid="ignore"):
        if np.isnan(yb).any():
            filled_lo = np.where(np.isnan(yb), np.inf, yb)
            filled_hi = np.where(np.isnan(yb), -np.inf, yb)
            imin = filled_lo.argmin(axis=1)
            imax = filled_hi.argmax(axis=1)
        else:
            imin = yb.argmin(axis=1)
            imax = yb.argmax(axis=1)
    offs = np.arange(buckets) * size
    first = np.minimum(imin, imax) + offs
    second = np.maximum(imin, imax) + offs
    idx = np.empty(buckets * 2, dtype=np.int64)
    idx[0::2] = first
    idx[1::2] = second
    if usable < n:
        idx = np.concatenate((idx, [n - 1]))
    return x[idx], y[idx]


def visible_slice(t: np.ndarray, lo: float, hi: float) -> slice:
    a = int(np.searchsorted(t, lo, side="left"))
    b = int(np.searchsorted(t, hi, side="right"))
    a = max(0, a - 1)
    b = min(len(t), b + 1)
    return slice(a, b)


def describe(y: np.ndarray) -> dict:
    y = np.asarray(y, dtype=np.float64)
    y = y[np.isfinite(y)]
    if len(y) == 0:
        return {"n": 0, "min": np.nan, "max": np.nan, "mean": np.nan,
                "std": np.nan, "rms": np.nan, "p2p": np.nan}
    return {
        "n": int(len(y)),
        "min": float(y.min()),
        "max": float(y.max()),
        "mean": float(y.mean()),
        "std": float(y.std()),
        "rms": float(np.sqrt(np.mean(y * y))),
        "p2p": float(y.max() - y.min()),
    }


def welch_psd(y: np.ndarray, fs: float, seg_len: int = 1024):
    """Welch power spectral density with a Hann window (numpy only).

    Returns (freqs, psd_db). Segment length shrinks for short inputs.
    """
    y = np.asarray(y, dtype=np.float64)
    y = y[np.isfinite(y)]
    if len(y) < 16 or fs <= 0:
        return np.array([]), np.array([])
    seg = int(min(seg_len, 2 ** int(np.floor(np.log2(len(y))))))
    step = seg // 2
    win = np.hanning(seg)
    scale = 1.0 / (fs * (win ** 2).sum())
    acc = None
    count = 0
    for start in range(0, len(y) - seg + 1, step):
        chunk = y[start:start + seg]
        chunk = (chunk - chunk.mean()) * win
        p = np.abs(np.fft.rfft(chunk)) ** 2 * scale
        acc = p if acc is None else acc + p
        count += 1
    psd = acc / count
    psd[1:-1] *= 2
    freqs = np.fft.rfftfreq(seg, 1.0 / fs)
    return freqs, 10 * np.log10(psd + 1e-12)


def dominant_peaks(freqs: np.ndarray, psd_db: np.ndarray, count: int = 3, min_hz: float = 10.0):
    """Highest local maxima above min_hz, as (freq, dB) pairs."""
    if len(freqs) < 3:
        return []
    mask = freqs >= min_hz
    f, p = freqs[mask], psd_db[mask]
    if len(p) < 3:
        return []
    local = np.flatnonzero((p[1:-1] > p[:-2]) & (p[1:-1] >= p[2:])) + 1
    if len(local) == 0:
        return []
    order = local[np.argsort(p[local])[::-1]]
    picked = []
    for i in order:
        if all(abs(f[i] - q[0]) > 8.0 for q in picked):
            picked.append((float(f[i]), float(p[i])))
        if len(picked) >= count:
            break
    return picked
