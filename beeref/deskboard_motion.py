# This file is part of Birdboard (GPL-3.0-or-later).

"""Deskboard damped harmonic spring physics, 2-segment Spread flight Bezier,
and fast K-Means dominant palette extractor.
"""

from dataclasses import dataclass
import math

from PyQt6 import QtCore, QtGui


@dataclass(frozen=True)
class Spring:
    """Closed-form damped harmonic oscillator (mass=1, v0=0, 0 -> 1)."""
    stiffness: float
    damping: float

    @property
    def w0(self) -> float:
        return math.sqrt(self.stiffness)

    @property
    def zeta(self) -> float:
        return self.damping / (2.0 * math.sqrt(self.stiffness))

    def value(self, t: float) -> float:
        if t <= 0.0:
            return 0.0
        w0 = self.w0
        z = self.zeta
        if z < 1.0 - 1e-6:
            wd = w0 * math.sqrt(1.0 - z * z)
            env = math.exp(-z * w0 * t)
            x = env * (math.cos(wd * t) + (z * w0 / wd) * math.sin(wd * t))
        elif abs(z - 1.0) <= 1e-6:
            x = math.exp(-w0 * t) * (1.0 + w0 * t)
        else:
            s = math.sqrt(z * z - 1.0)
            r1 = -w0 * (z - s)
            r2 = -w0 * (z + s)
            x = (r2 * math.exp(r1 * t) - r1 * math.exp(r2 * t)) / (r2 - r1)
        return 1.0 - x

    @property
    def settle_duration(self) -> float:
        """Settling time (seconds) where |1 - x(t)| <= 0.001, sampled at 240 Hz."""
        last_unsettled = 0.0
        for step in range(1, 360):
            t = step / 240.0
            if abs(1.0 - self.value(t)) > 0.001:
                last_unsettled = t
        return max(0.15, last_unsettled + (1.0 / 240.0))


# Deskboard canonical spring presets
SPRING_PRESENT = Spring(260.0, 24.0)   # ~0.49s: toolbar present / slide up
SPRING_LIFT = Spring(420.0, 30.0)      # ~0.48s: hover / selection lift
SPRING_SOFT = Spring(170.0, 25.0)      # ~0.60s: toolbar width morph
SPRING_PLACE = Spring(300.0, 30.0)     # ~0.50s: stack collapse, grid, pull-out reflow
SPRING_TOAST = Spring(300.0, 24.0)     # ~0.60s: toast entrance
SPRING_OPEN = Spring(230.0, 28.0)      # ~0.55s: Detail Stage open zoom
SPRING_CLOSE = Spring(320.0, 34.0)     # ~0.40s: Detail Stage close zoom
SPRING_POP = Spring(420.0, 14.0)       # ~0.65s: bouncy pop (zeta = 0.34)


def _bezier_1d(p1: float, p2: float, t: float) -> float:
    u = 1.0 - t
    return 3.0 * u * u * t * p1 + 3.0 * u * t * t * p2 + t * t * t


def cubic_bezier(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    """Evaluate CSS cubic-bezier(x1, y1, x2, y2) at normalized time x in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    t = x
    for _ in range(18):
        val = _bezier_1d(x1, x2, t)
        if abs(val - x) < 1e-5:
            break
        if val < x:
            lo = t
        else:
            hi = t
        t = 0.5 * (lo + hi)
    return _bezier_1d(y1, y2, t)


def spread_flight_factor(raw_t: float) -> float:
    """2-segment Spread flight [0 -> 0.76 -> 1.0] with subtle recoil peak (1.015).

    Segment 1 (0 -> 0.76): cubic-bezier(0.16, 0.65, 0.28, 1.0) to 1.015.
    Segment 2 (0.76 -> 1.0): ease-in-out cubic-bezier(0.42, 0, 0.58, 1.0) back to 1.0.
    """
    t = max(0.0, min(1.0, raw_t))
    if t <= 0.76:
        u = cubic_bezier(0.16, 0.65, 0.28, 1.0, t / 0.76)
        return u * 1.015
    u = cubic_bezier(0.42, 0.0, 0.58, 1.0, (t - 0.76) / 0.24)
    return 1.015 + (1.0 - 1.015) * u


def collapse_flight_factor(raw_t: float) -> float:
    """Smooth 0.24s fold-back curve."""
    return cubic_bezier(0.42, 0.0, 0.58, 1.0, max(0.0, min(1.0, raw_t)))


def _luminance(r: float, g: float, b: float) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def extract_dominant_palette(img_or_pixmap, count: int = 5) -> list[str]:
    """Extract `count` distinct dominant HEX colors sorted brightest -> darkest.

    Downscales input to 40x40 (~1600 pixels) and runs deterministic K-Means
    clustering in < 1ms.
    """
    if isinstance(img_or_pixmap, QtGui.QPixmap):
        if img_or_pixmap.isNull():
            return ['#E5E0D8', '#C4BEB4', '#9E978E', '#6E685F', '#3D3A36'][:count]
        qimg = img_or_pixmap.toImage()
    else:
        qimg = img_or_pixmap

    if qimg is None or qimg.isNull():
        return ['#E5E0D8', '#C4BEB4', '#9E978E', '#6E685F', '#3D3A36'][:count]

    small = qimg.scaled(
        40, 40,
        QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QtGui.QImage.Format.Format_ARGB32)

    pixels: list[tuple[float, float, float]] = []
    w, h = small.width(), small.height()
    for y in range(h):
        for x in range(w):
            c = small.pixelColor(x, y)
            if c.alpha() >= 45:
                pixels.append((float(c.red()), float(c.green()), float(c.blue())))

    if not pixels:
        return ['#E5E0D8', '#C4BEB4', '#9E978E', '#6E685F', '#3D3A36'][:count]

    # Sort pixels by luminance to pick well-spaced quantile initial centroids
    pixels_by_lum = sorted(pixels, key=lambda p: _luminance(p[0], p[1], p[2]))
    n = len(pixels_by_lum)
    centroids: list[tuple[float, float, float]] = [
        pixels_by_lum[min(n - 1, int((i + 0.5) * n / count))]
        for i in range(count)
    ]

    # 6 fast K-Means iterations
    for _ in range(6):
        sums = [[0.0, 0.0, 0.0, 0] for _ in range(count)]
        for r, g, b in pixels:
            best_k = 0
            best_d = 1e18
            for k, (cr, cg, cb) in enumerate(centroids):
                d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
                if d < best_d:
                    best_d = d
                    best_k = k
            acc = sums[best_k]
            acc[0] += r
            acc[1] += g
            acc[2] += b
            acc[3] += 1

        new_centroids = []
        for k in range(count):
            cnt = sums[k][3]
            if cnt > 0:
                new_centroids.append((
                    sums[k][0] / cnt,
                    sums[k][1] / cnt,
                    sums[k][2] / cnt,
                ))
            else:
                new_centroids.append(centroids[k])
        centroids = new_centroids

    # Sort brightest (highest luminance) at top -> darkest at bottom
    centroids.sort(key=lambda c: _luminance(c[0], c[1], c[2]), reverse=True)

    hex_list = []
    for r, g, b in centroids:
        ri = max(0, min(255, round(r)))
        gi = max(0, min(255, round(g)))
        bi = max(0, min(255, round(b)))
        hex_list.append(f'#{ri:02X}{gi:02X}{bi:02X}')
    return hex_list
