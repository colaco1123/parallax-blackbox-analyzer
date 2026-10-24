"""Built-in plot layouts. Each preset is a list of panels drawn on a shared time axis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

AXES = ("Roll", "Pitch", "Yaw")


@dataclass
class Series:
    column: str
    label: Optional[str] = None
    scale: float = 1.0
    positive_only: bool = False   # drop samples <= 0 (rangefinder reports -1 when invalid)
    style: str = "-"


@dataclass
class Panel:
    title: str
    series: list
    ylabel: str = ""
    ylim: Optional[tuple] = None


@dataclass
class Preset:
    key: str
    name: str
    panels: list = field(default_factory=list)
    description: str = ""


def _s(col, label=None, **kw):
    return Series(col, label or col, **kw)


def build_presets() -> list:
    p = []
    p.append(Preset("overview", "Overview: LiDAR, throttle, motors", [
        Panel("Rangefinder (LiDAR) raw distance", [_s("surfaceRaw", "surfaceRaw", positive_only=True)], "cm"),
        Panel("Throttle", [_s("rcData[3]", "rcData[3] stick"), _s("rcCommand[3]", "rcCommand[3]", style="--")],
              "us", (950, 2050)),
        Panel("Motor outputs", [_s(f"motor[{i}]", f"Motor {i + 1}") for i in range(8)], "us"),
    ], "Your original ASCEND debug view, now with rcCommand overlay."))

    p.append(Preset("altitude", "Altitude hold: baro vs LiDAR vs nav", [
        Panel("Altitude sources", [
            _s("BaroAlt (cm)", "Baro"),
            _s("surfaceRaw", "LiDAR raw", positive_only=True),
            _s("navSurf", "navSurf"),
            _s("navPos[2]", "Estimated Z"),
            _s("navTgtPos[2]", "Target Z", style="--"),
        ], "cm"),
        Panel("Vertical velocity", [_s("navVel[2]", "Estimated"), _s("navTgtVel[2]", "Target", style="--")], "cm/s"),
        Panel("Surface controller", [_s("mcSurfaceP", "P"), _s("mcSurfaceI", "I"), _s("mcSurfaceD", "D"),
                                     _s("mcSurfaceOut", "Out", style="--")], ""),
        Panel("Throttle", [_s("rcCommand[3]", "rcCommand[3]")], "us"),
    ], "Compare every altitude estimate against the nav target."))

    p.append(Preset("motors", "Motors", [
        Panel("Motor outputs", [_s(f"motor[{i}]", f"Motor {i + 1}") for i in range(8)], "us"),
    ]))

    p.append(Preset("rc", "RC sticks vs commands", [
        Panel(f"{name}", [_s(f"rcData[{i}]", "rcData (stick)"), _s(f"rcCommand[{i}]", "rcCommand", style="--")], "")
        for i, name in enumerate(("Roll", "Pitch", "Yaw", "Throttle"))
    ]))

    p.append(Preset("tracking", "Gyro vs setpoint (PID tracking)", [
        Panel(f"{AXES[i]} rate", [_s(f"axisRate[{i}]", "Setpoint"), _s(f"gyroADC[{i}]", "Gyro")], "deg/s")
        for i in range(3)
    ], "Setpoint should lead gyro closely; gaps show tuning issues."))

    p.append(Preset("pid", "PID terms per axis", [
        Panel(f"{AXES[i]} PID", [_s(f"axisP[{i}]", "P"), _s(f"axisI[{i}]", "I"),
                                 _s(f"axisD[{i}]", "D"), _s(f"axisF[{i}]", "FF")], "")
        for i in range(3)
    ]))

    p.append(Preset("attitude", "Attitude", [
        Panel("Attitude", [_s("attitude[0]", "Roll", scale=0.1), _s("attitude[1]", "Pitch", scale=0.1)], "deg"),
        Panel("Heading", [_s("attitude[2]", "Yaw", scale=0.1), _s("navTgtHdg", "Target heading", scale=0.01,
                                                                    style="--")], "deg"),
    ]))

    p.append(Preset("navpos", "Position hold: position and velocity", [
        Panel("X position", [_s("navPos[0]", "Estimated"), _s("navTgtPos[0]", "Target", style="--")], "cm"),
        Panel("Y position", [_s("navPos[1]", "Estimated"), _s("navTgtPos[1]", "Target", style="--")], "cm"),
        Panel("X velocity", [_s("navVel[0]", "Estimated"), _s("navTgtVel[0]", "Target", style="--")], "cm/s"),
        Panel("Y velocity", [_s("navVel[1]", "Estimated"), _s("navTgtVel[1]", "Target", style="--")], "cm/s"),
        Panel("Nav accuracy", [_s("navEPH", "EPH"), _s("navEPV", "EPV")], "cm"),
    ], "Drift in GPS-denied flight shows as estimate vs target divergence."))

    p.append(Preset("battery", "Battery and power", [
        Panel("Voltage", [_s("vbat (V)", "vbat"), _s("sagCompensatedVBat", "Sag compensated", scale=0.01,
                                                     style="--")], "V"),
        Panel("Current", [_s("amperage (A)", "Current")], "A"),
        Panel("Energy used", [_s("energyCumulative (mAh)", "Consumed")], "mAh"),
    ]))

    p.append(Preset("vibration", "Vibration and accelerometer", [
        Panel("Vibration level", [_s("accVib", "accVib")], ""),
        Panel("Accelerometer", [_s("accSmooth[0]", "X"), _s("accSmooth[1]", "Y"), _s("accSmooth[2]", "Z")], "raw"),
        Panel("Gyro raw", [_s(f"gyroRaw[{i}]", AXES[i]) for i in range(3)], "deg/s"),
    ]))

    p.append(Preset("parallax", "Parallax telemetry (att / battery)", [
        Panel("Attitude", [_s("att.r", "Roll"), _s("att.p", "Pitch"), _s("att.y", "Yaw")], "deg"),
        Panel("Battery", [_s("bat.v", "Voltage"), _s("ba", "ba")], ""),
        Panel("Sequence", [_s("seq.pct", "Progress")], "%"),
    ], "For CSV logs written by the Parallax ground station."))

    p.append(Preset("custom", "Custom: pick columns", [], "Choose any columns from the list."))
    return p


PRESETS = build_presets()
PRESET_BY_KEY = {p.key: p for p in PRESETS}


def resolve_panels(preset: Preset, columns) -> list:
    """Drop series whose columns are missing, and panels left empty."""
    cols = set(columns)
    out = []
    for panel in preset.panels:
        series = [s for s in panel.series if s.column in cols]
        if series:
            out.append(Panel(panel.title, series, panel.ylabel, panel.ylim))
    return out


def available_presets(columns) -> list:
    return [p for p in PRESETS if p.key == "custom" or resolve_panels(p, columns)]
