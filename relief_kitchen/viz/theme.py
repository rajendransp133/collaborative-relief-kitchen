"""Colours, fonts and small drawing helpers for the visualiser.

Light "report" style: warm off-white paper, ink text, hairline dividers, one accent colour
(ink-blue) for the time cursor and selection, and brick red reserved for problems.
Data colours are desaturated so that no single order shouts.
"""

from __future__ import annotations

import math

import pygame
import pygame.gfxdraw as gfx


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


PAPER = hex_rgb("#F7F6F2")
SURFACE = hex_rgb("#FFFFFF")
BAND = hex_rgb("#FAF9F6")  # alternate table / chart rows
HAIRLINE = hex_rgb("#E2DED6")
GRID = hex_rgb("#EFECE6")
INK = hex_rgb("#1F2328")
MUTED = hex_rgb("#6B6F76")
FAINT = hex_rgb("#A3A7AD")
ACCENT = hex_rgb("#2F5D9F")
ERROR = hex_rgb("#B5523B")
OK = hex_rgb("#4F7A45")
HIGHLIGHT = hex_rgb("#EFEBE2")
WALL = hex_rgb("#ECE8E0")
ROAD = hex_rgb("#D3CFC6")

ORDER_COLORS = [hex_rgb(c) for c in ("#B5523B", "#4A6FA5", "#C08A2E", "#6A8F5B", "#7D5C8C", "#3C8C88",
                                      "#8C6A4F", "#5E7C8A")]

# station type -> (fill, outline)
STATION_STYLE = {
    "storage": (hex_rgb("#EFE6D8"), hex_rgb("#C9B9A0")),
    "prep": (hex_rgb("#E3EAF3"), hex_rgb("#AFC0D5")),
    "stove": (hex_rgb("#F4E1DC"), hex_rgb("#D6A99D")),
    "steamer": (hex_rgb("#EFE2EC"), hex_rgb("#C9ABC2")),
    "packaging": (hex_rgb("#E2EEE6"), hex_rgb("#A5C4AF")),
    "dispatch": (hex_rgb("#F3EBD3"), hex_rgb("#D2BD86")),
}
FAILED_STYLE = (hex_rgb("#ECEAE6"), hex_rgb("#C9C5BE"))

_FONTS: dict = {}
_FAMILY = "inter,segoeui,helveticaneue,helvetica,dejavusans,arial"


def font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (size, bold)
    if key not in _FONTS:
        path = pygame.font.match_font(_FAMILY, bold=bold)
        _FONTS[key] = pygame.font.Font(path, size) if path else pygame.font.Font(None, int(size * 1.35))
    return _FONTS[key]


def text(surf, s, pos, size=13, color=INK, bold=False, anchor="topleft") -> pygame.Rect:
    img = font(size, bold).render(str(s), True, color)
    rect = img.get_rect(**{anchor: pos})
    surf.blit(img, rect)
    return rect


def text_width(s: str, size: int, bold: bool = False) -> int:
    return font(size, bold).size(s)[0]


def fit(s: str, size: int, width: int, bold: bool = False) -> str:
    """Truncate with an ellipsis so the text fits in `width` pixels."""
    if text_width(s, size, bold) <= width:
        return s
    while s and text_width(s + "…", size, bold) > width:
        s = s[:-1]
    return s + "…"


def wrap(s: str, size: int, width: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if text_width(trial, size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def section(surf, x, y, title, caption=""):
    """Small uppercase section label with an optional muted caption after it."""
    r = text(surf, title.upper(), (x, y), 11, INK, True)
    if caption:
        text(surf, caption, (r.right + 10, y), 11, FAINT)


def hline(surf, x0, x1, y, color=HAIRLINE):
    pygame.draw.line(surf, color, (x0, y), (x1, y), 1)


def dashed(surf, color, a, b, width=2, dash=7, gap=5):
    ax, ay = a
    bx, by = b
    length = math.hypot(bx - ax, by - ay)
    if length == 0:
        return
    ux, uy = (bx - ax) / length, (by - ay) / length
    d = 0.0
    while d < length:
        e = min(d + dash, length)
        pygame.draw.line(surf, color, (ax + ux * d, ay + uy * d), (ax + ux * e, ay + uy * e), width)
        d = e + gap


def aaline(surf, color, a, b, width=1):
    if width <= 1:
        pygame.draw.aaline(surf, color, a, b)
    else:
        pygame.draw.line(surf, color, a, b, width)


def disc(surf, color, center, r):
    """Anti-aliased filled circle."""
    x, y, r = int(round(center[0])), int(round(center[1])), int(round(r))
    gfx.aacircle(surf, x, y, r, color)
    gfx.filled_circle(surf, x, y, r, color)


def ring(surf, color, center, r, fill=SURFACE):
    """Anti-aliased circle outline (2 px) around a filled centre."""
    x, y, r = int(round(center[0])), int(round(center[1])), int(round(r))
    gfx.filled_circle(surf, x, y, r, color)
    gfx.aacircle(surf, x, y, r, color)
    gfx.filled_circle(surf, x, y, r - 2, fill)
    gfx.aacircle(surf, x, y, r - 2, fill)
