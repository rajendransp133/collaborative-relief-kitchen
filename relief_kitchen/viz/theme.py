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

# Station colours follow HACCP colour coding used in commercial kitchens: brown for stores / root
# vegetables, green for vegetable prep, yellow for cooked ready-to-eat food (packing), purple for
# allergen-free. Heat zones (stove, steamer) use warm red / amber as on kitchen floor plans.
# station type -> (fill, outline / strong colour)
STATION_STYLE = {
    "storage": (hex_rgb("#EAD9C6"), hex_rgb("#B98B5E")),
    "prep": (hex_rgb("#DCEBD8"), hex_rgb("#5E9E5A")),
    "stove": (hex_rgb("#F6D9CF"), hex_rgb("#D0593A")),
    "steamer": (hex_rgb("#F7E3C4"), hex_rgb("#D98E2B")),
    "packaging": (hex_rgb("#F6EDC2"), hex_rgb("#C9A51E")),
    "dispatch": (hex_rgb("#DDE5EA"), hex_rgb("#5F7A8C")),
}
STATION_NAME = {"storage": "Storage shelf", "prep": "Prep counter", "stove": "Stove", "steamer": "Steamer",
                "packaging": "Packing table", "dispatch": "Dispatch door"}
ZONE_NAME = {"storage": "Storage zone", "prep": "Preparation zone", "stove": "Cooking zone",
             "steamer": "Cooking zone", "packaging": "Packing zone", "dispatch": "Dispatch"}
ALLERGEN_FREE = hex_rgb("#7B5EA7")  # HACCP purple


def mix(a, b, t: float):
    """Blend colour a towards b by t (0..1)."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


FAILED_STYLE = (hex_rgb("#ECEAE6"), hex_rgb("#C9C5BE"))

# ---------------------------------------------------------------------------------------------
# render scale: pages lay out in logical units (a 1440 x 860 canvas); the helpers below draw at
# the window's real resolution, so text and lines stay sharp at any window size
# ---------------------------------------------------------------------------------------------
LOGICAL_W, LOGICAL_H = 1440, 860
S, OX, OY = 1.0, 0.0, 0.0  # physical pixels per logical unit, and the letterbox offset


def set_scale(width: int, height: int):
    """Fit the logical canvas into a window of `width` x `height` physical pixels (centred)."""
    global S, OX, OY
    S = min(width / LOGICAL_W, height / LOGICAL_H)
    OX, OY = (width - LOGICAL_W * S) / 2, (height - LOGICAL_H * S) / 2


def pt(p):
    """Logical point -> physical point."""
    return OX + p[0] * S, OY + p[1] * S


def prect(r) -> pygame.Rect:
    """Logical rect -> physical rect; edges are rounded separately so neighbouring cells tile exactly."""
    x, y, w, h = r
    x0, y0 = round(OX + x * S), round(OY + y * S)
    return pygame.Rect(x0, y0, round(OX + (x + w) * S) - x0, round(OY + (y + h) * S) - y0)


def to_logical(pos):
    return (pos[0] - OX) / S, (pos[1] - OY) / S


def _px(v: float) -> int:
    """Logical line width or radius -> whole physical pixels (at least 1)."""
    return max(1, round(v * S))


_FONTS: dict = {}
_FAMILY = "inter,segoeui,helveticaneue,helvetica,dejavusans,arial"


def font(size: int, bold: bool = False) -> pygame.font.Font:
    """Font at the physical pixel size for a logical `size`."""
    px = max(6, round(size * S))
    key = (px, bold)
    if key not in _FONTS:
        path = pygame.font.match_font(_FAMILY, bold=bold)
        _FONTS[key] = pygame.font.Font(path, px) if path else pygame.font.Font(None, int(px * 1.35))
    return _FONTS[key]


def text(surf, s, pos, size=13, color=INK, bold=False, anchor="topleft") -> pygame.Rect:
    """Draw text at a logical position; returns its logical rect (for layout and hover)."""
    img = font(size, bold).render(str(s), True, color)
    surf.blit(img, img.get_rect(**{anchor: pt(pos)}))
    rect = pygame.Rect(0, 0, round(img.get_width() / S), round(img.get_height() / S))
    setattr(rect, anchor, (round(pos[0]), round(pos[1])))
    return rect


def text_width(s: str, size: int, bold: bool = False) -> float:
    return font(size, bold).size(s)[0] / S


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


# ---------------------------------------------------------------------------------------------
# shapes, all in logical coordinates
# ---------------------------------------------------------------------------------------------
def draw_rect(surf, color, r, width=0, border_radius=0, **corners):
    """pygame.draw.rect in logical units (corner radii such as border_top_left_radius are scaled too)."""
    corners = {k: round(v * S) for k, v in corners.items()}
    pygame.draw.rect(surf, color, prect(r), _px(width) if width else 0, round(border_radius * S), **corners)


def draw_line(surf, color, a, b, width=1):
    """Straight line: crisp when horizontal or vertical, anti-aliased otherwise."""
    (ax, ay), (bx, by) = pt(a), pt(b)
    w = width * S
    if round(ax) == round(bx) or round(ay) == round(by):
        pygame.draw.line(surf, color, (round(ax), round(ay)), (round(bx), round(by)), _px(width))
    elif w < 1.6:
        pygame.draw.aaline(surf, color, (ax, ay), (bx, by))
    else:
        n = math.hypot(bx - ax, by - ay)
        nx, ny = -(by - ay) / n * w / 2, (bx - ax) / n * w / 2
        quad = [(ax + nx, ay + ny), (bx + nx, by + ny), (bx - nx, by - ny), (ax - nx, ay - ny)]
        pygame.draw.polygon(surf, color, quad)
        pygame.draw.aalines(surf, color, True, quad)
        for x, y in ((ax, ay), (bx, by)):  # round caps so joined segments meet cleanly
            _disc_px(surf, color, x, y, w / 2)


def hline(surf, x0, x1, y, color=HAIRLINE):
    draw_line(surf, color, (x0, y), (x1, y), 1)


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
        draw_line(surf, color, (ax + ux * d, ay + uy * d), (ax + ux * e, ay + uy * e), width)
        d = e + gap


def _disc_px(surf, color, x, y, r):
    x, y, r = int(round(x)), int(round(y)), max(1, int(round(r)))
    gfx.aacircle(surf, x, y, r, color)
    gfx.filled_circle(surf, x, y, r, color)


def disc(surf, color, center, r):
    """Anti-aliased filled circle."""
    x, y = pt(center)
    _disc_px(surf, color, x, y, r * S)


def ring(surf, color, center, r, fill=SURFACE):
    """Anti-aliased circle outline (2 logical px) around a filled centre."""
    x, y = pt(center)
    _disc_px(surf, color, x, y, r * S)
    _disc_px(surf, fill, x, y, (r - 2) * S)


def shadow(surf, r, radius=8, alpha=22):
    """Soft drop shadow under a logical rect."""
    pr = prect(r)
    layer = pygame.Surface(pr.size, pygame.SRCALPHA)
    pygame.draw.rect(layer, (0, 0, 0, alpha), layer.get_rect(), border_radius=round(radius * S))
    surf.blit(layer, pr.topleft)


def veil(surf, color, alpha):
    """Translucent wash over the whole window."""
    layer = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    layer.fill((*color, alpha))
    surf.blit(layer, (0, 0))
