"""Colours, fonts and small drawing helpers for the visualiser.

"Web console" style: a cool grey ground, white cards with a 1px border, ink text, IBM Plex Sans
for words and IBM Plex Mono for ids, clocks and times. Colour goes on data (orders, station
zones) and on problems (brick red); the accent blue marks selection.
"""

from __future__ import annotations

import math
from pathlib import Path

import pygame
import pygame.gfxdraw as gfx


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


PAPER = hex_rgb("#F1F2F4")  # the ground behind cards
SURFACE = hex_rgb("#FFFFFF")  # cards
BAND = hex_rgb("#F7F8F9")  # alternate table / chart rows
HAIRLINE = hex_rgb("#DCDFE5")  # card borders and section rules
DIVIDER = hex_rgb("#E6E8EC")  # rules between rows inside a card
GRID = hex_rgb("#E6E8EC")
BORDER = hex_rgb("#C9CDD5")  # outlines of pills and secondary buttons
INK = hex_rgb("#14161B")
SUBTLE = hex_rgb("#3D4350")  # secondary text that still reads as content
MUTED = hex_rgb("#596070")  # labels and captions
FAINT = hex_rgb("#7A808C")  # ticks and the quietest notes
ACCENT = hex_rgb("#2F5FB3")
ERROR = hex_rgb("#B4360F")
OK = hex_rgb("#3B7F4C")
HIGHLIGHT = hex_rgb("#E6E8EC")
MAP_BG = hex_rgb("#E4E6EA")  # the inset the kitchen floor sits in
WALL = hex_rgb("#D3D6DC")
ROAD = hex_rgb("#CDD1D8")
PATH_DOT = hex_rgb("#9AA1AE")
HATCH_A, HATCH_B, HATCH_EDGE = hex_rgb("#F6DAD5"), hex_rgb("#E8BDB5"), hex_rgb("#8E2F25")  # out of service

ORDER_COLORS = [hex_rgb(c) for c in ("#C2412F", "#2F5FB3", "#9A6A0B", "#3B7F4C", "#7D5C8C", "#2E8784",
                                      "#8C6A4F", "#5E7C8A")]

# Station colours follow HACCP colour coding used in commercial kitchens: brown for stores / root
# vegetables, green for vegetable prep, yellow for cooked ready-to-eat food (packing), purple for
# allergen-free. The stove zone uses warm red as on kitchen floor plans.
# station type -> (fill, outline / strong colour)
STATION_STYLE = {
    "storage": (hex_rgb("#EBD7C1"), hex_rgb("#9C6B3F")),
    "prep": (hex_rgb("#D3E9D8"), hex_rgb("#3B7F4C")),
    "stove": (hex_rgb("#F4D3CD"), hex_rgb("#B8443A")),
    "packaging": (hex_rgb("#F3E7AE"), hex_rgb("#9A7B12")),
    "dispatch": (hex_rgb("#D4E0ED"), hex_rgb("#40608A")),
}
STATION_BUSY = {"storage": hex_rgb("#E2C4A3"), "prep": hex_rgb("#B3DABD"), "stove": hex_rgb("#ECB3A9"),
                "packaging": hex_rgb("#EAD678"), "dispatch": hex_rgb("#B7CBE2")}
ZONE_TINT = {"storage": hex_rgb("#F4EADF"), "prep": hex_rgb("#E7F2E9"), "stove": hex_rgb("#F9E7E4"),
             "packaging": hex_rgb("#FAF5DD"), "dispatch": hex_rgb("#E6ECF4")}
STATION_NAME = {"storage": "Storage shelf", "prep": "Prep counter", "stove": "Stove",
                "packaging": "Packing table", "dispatch": "Dispatch door"}
ZONE_NAME = {"storage": "Storage zone", "prep": "Preparation zone", "stove": "Cooking zone",
             "packaging": "Packing zone", "dispatch": "Dispatch"}


def mix(a, b, t: float):
    """Blend colour a towards b by t (0..1)."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


FAILED_STYLE = (HATCH_A, HATCH_EDGE)

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
FONT_DIR = Path(__file__).parent / "fonts"  # IBM Plex, SIL Open Font License (see fonts/OFL.txt)
_FONT_FILES = {("sans", "regular"): "IBMPlexSans-Regular.ttf", ("sans", "medium"): "IBMPlexSans-Medium.ttf",
               ("sans", "semibold"): "IBMPlexSans-SemiBold.ttf", ("mono", "regular"): "IBMPlexMono-Regular.ttf",
               ("mono", "medium"): "IBMPlexMono-SemiBold.ttf", ("mono", "semibold"): "IBMPlexMono-SemiBold.ttf"}
_FALLBACK = {"sans": "segoeui,helveticaneue,helvetica,dejavusans,arial",
             "mono": "consolas,dejavusansmono,menlo,couriernew"}


def bundled_fonts() -> bool:
    """Are the bundled IBM Plex files present (otherwise system fonts are used)?"""
    return all((FONT_DIR / f).exists() for f in _FONT_FILES.values())


def font(size: int, bold: bool = False, mono: bool = False, weight: str | None = None) -> pygame.font.Font:
    """Font at the physical pixel size for a logical `size`; weight is regular, medium or semibold."""
    px = max(6, round(size * S))
    family, weight = ("mono" if mono else "sans"), (weight or ("semibold" if bold else "regular"))
    key = (px, family, weight)
    if key not in _FONTS:
        path = FONT_DIR / _FONT_FILES[(family, weight)]
        if path.exists():
            _FONTS[key] = pygame.font.Font(str(path), px)
        else:
            sys_path = pygame.font.match_font(_FALLBACK[family], bold=weight != "regular")
            _FONTS[key] = pygame.font.Font(sys_path, px) if sys_path else pygame.font.Font(None, int(px * 1.35))
    return _FONTS[key]


def text(surf, s, pos, size=13, color=INK, bold=False, anchor="topleft", mono=False, weight=None) -> pygame.Rect:
    """Draw text at a logical position; returns its logical rect (for layout and hover)."""
    img = font(size, bold, mono, weight).render(str(s), True, color)
    surf.blit(img, img.get_rect(**{anchor: pt(pos)}))
    rect = pygame.Rect(0, 0, round(img.get_width() / S), round(img.get_height() / S))
    setattr(rect, anchor, (round(pos[0]), round(pos[1])))
    return rect


def text_width(s: str, size: int, bold: bool = False, mono: bool = False, weight: str | None = None) -> float:
    return font(size, bold, mono, weight).size(s)[0] / S


def fit(s: str, size: int, width: int, bold: bool = False, mono: bool = False, weight: str | None = None) -> str:
    """Truncate with an ellipsis so the text fits in `width` pixels."""
    if text_width(s, size, bold, mono, weight) <= width:
        return s
    while s and text_width(s + "…", size, bold, mono, weight) > width:
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


def caps(surf, s, pos, size=11, color=MUTED, anchor="topleft", weight="semibold") -> pygame.Rect:
    """Small uppercase label with 0.08em letter spacing (the console's section labels)."""
    s = str(s).upper()
    gap = size * 0.08
    width = sum(text_width(ch, size, weight=weight) for ch in s) + gap * max(0, len(s) - 1)
    box = pygame.Rect(0, 0, round(width), round(font(size, weight=weight).get_height() / S))
    setattr(box, anchor, (round(pos[0]), round(pos[1])))
    x = box.x
    for ch in s:
        text(surf, ch, (x, box.y), size, color, weight=weight)
        x += text_width(ch, size, weight=weight) + gap
    return box


def card(surf, r, fill=SURFACE, border=HAIRLINE, radius=12):
    """White card with a 1px border (no shadow)."""
    draw_rect(surf, fill, r, border_radius=radius)
    draw_rect(surf, border, r, 1, border_radius=radius)


def hatch(surf, r, radius=7, a=HATCH_A, b=HATCH_B, step=6):
    """Diagonal stripes (out of service), clipped to the rect."""
    r = pygame.Rect(r)
    draw_rect(surf, a, r, border_radius=radius)
    old = surf.get_clip()
    surf.set_clip(prect(r.inflate(-2, -2)))
    for k in range(0, r.width + r.height, step):
        draw_line(surf, b, (r.x + k, r.y), (r.x + k - r.height, r.bottom), 2.5)
    surf.set_clip(old)


def pill_width(label: str, num: str = "") -> float:
    return 24 + text_width(label, 13) + (text_width(num, 13, mono=True, weight="semibold") + 6 if num else 0)


def pill(surf, x, y, label, num="", active=False) -> pygame.Rect:
    """Rounded plan-step pill: mono number, then the label. Active is filled ink."""
    r = pygame.Rect(round(x), round(y), round(pill_width(label, num)), 24)
    draw_rect(surf, INK if active else SURFACE, r, border_radius=12)
    if not active:
        draw_rect(surf, BORDER, r, 1, border_radius=12)
    colour = SURFACE if active else SUBTLE
    tx = r.x + 12
    if num:
        tx = text(surf, num, (tx, r.centery), 13, colour, anchor="midleft", mono=True, weight="semibold").right + 6
    text(surf, label, (tx, r.centery), 13, colour, anchor="midleft")
    return r


def chip(surf, s, pos, anchor="topleft") -> pygame.Rect:
    """Grey rounded mono chip (header stats)."""
    w = text_width(s, 12, mono=True) + 20
    r = pygame.Rect(0, 0, round(w), 24)
    setattr(r, anchor, (round(pos[0]), round(pos[1])))
    draw_rect(surf, PAPER, r, border_radius=6)
    text(surf, s, (r.x + 10, r.centery), 12, SUBTLE, anchor="midleft", mono=True)
    return r


def heading(surf, x, y, title, caption=""):
    """Sentence-case panel heading with an optional caption after it (the larger, easier-to-read style)."""
    r = text(surf, title, (x, y), 16, INK, True)
    if caption:
        text(surf, caption, (r.right + 12, y + 3), 13, MUTED)
    return r


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
