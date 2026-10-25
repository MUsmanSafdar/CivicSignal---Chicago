"""Colour-vision-safe palette and WCAG contrast helpers (Phase 1.7). No Streamlit imports.

The risk scale runs blue (low) to orange (high). Blue/orange stays distinguishable for the common forms of
colour-vision deficiency, and every colour use in the app is paired with a text label (level name, badge or
printed value) so colour is never the only signal.
"""
from __future__ import annotations

LOW = "#1f5fa8"
LIGHT_LOW = "#9ec5ea"
LIGHT_HIGH = "#f7b267"
HIGH = "#b5470b"
NEUTRAL = "#f4f1ea"
INK = "#1d1d1f"
WHITE = "#ffffff"

RISK_COLORS: dict[str, str] = {"Low": LOW, "Medium": LIGHT_LOW, "High": LIGHT_HIGH, "Very High": HIGH}
RISK_SCALE: list[list[object]] = [[0.0, LOW], [0.5, NEUTRAL], [1.0, HIGH]]

# One-hue (orange) ramp for "need during a heat wave": light = lower need, dark = higher need.
NEED_RAMP = ["#fff1e6", "#fdbe85", "#fd8d3c", "#d94801", "#7f2704"]
NEED_SCALE: list[list[object]] = [[i / (len(NEED_RAMP) - 1), c] for i, c in enumerate(NEED_RAMP)]

# Foreground/background pairs used for the status pills in the CivicSignal page (text is always shown too).
PILL_PAIRS: dict[str, tuple[str, str]] = {
    "pass": ("#15692e", "#e3f6e8"),
    "review": ("#7a4f00", "#fff1d6"),
    "fail": ("#a1201f", "#fde6e6"),
    "none": ("#515154", "#efeff2"),
    "yes": ("#0b5cad", "#e1effd"),
    "dec": ("#ffffff", "#1d1d1f"),
}

# Machado et al. (2009), severity 1.0, applied to linear RGB.
_CVD = {
    "protanopia": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deuteranopia": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
    "tritanopia": ((1.255528, -0.076749, -0.178779), (-0.078411, 0.930809, 0.147602), (0.004733, 0.691367, 0.303900)),
}


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Parse ``#rrggbb`` into 0-255 integers."""
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _lin(v: float) -> float:
    v /= 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG relative luminance of a hex colour."""
    r, g, b = (_lin(v) for v in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two hex colours (1.0 to 21.0)."""
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def text_on(bg: str) -> str:
    """Black or white text, whichever has the higher contrast on ``bg``."""
    return INK if contrast_ratio(INK, bg) >= contrast_ratio(WHITE, bg) else WHITE


def simulate_cvd(color: str, kind: str) -> tuple[float, float, float]:
    """Approximate how ``color`` appears under ``kind`` (protanopia, deuteranopia or tritanopia), as 0-255 sRGB."""
    m = _CVD[kind]
    lin = [_lin(v) for v in hex_to_rgb(color)]
    out = []
    for row in m:
        v = max(0.0, min(1.0, sum(w * c for w, c in zip(row, lin))))
        s = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        out.append(255.0 * s)
    return out[0], out[1], out[2]


def cvd_distance(a: str, b: str, kind: str) -> float:
    """Euclidean sRGB distance between two colours as seen under ``kind``."""
    x, y = simulate_cvd(a, kind), simulate_cvd(b, kind)
    return sum((p - q) ** 2 for p, q in zip(x, y)) ** 0.5


def level_text_color(level: str) -> str:
    """Readable label colour for a risk level swatch."""
    return text_on(RISK_COLORS.get(level, NEUTRAL))


def ramp_color(fraction: float) -> str:
    """Colour on the one-hue need ramp for ``fraction`` in 0..1 (clamped), linearly interpolated."""
    f = max(0.0, min(1.0, float(fraction))) * (len(NEED_RAMP) - 1)
    i = min(int(f), len(NEED_RAMP) - 2)
    a, b = hex_to_rgb(NEED_RAMP[i]), hex_to_rgb(NEED_RAMP[i + 1])
    t = f - i
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))
