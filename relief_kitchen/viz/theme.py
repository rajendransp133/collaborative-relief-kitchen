"""Ant Design-inspired colour tokens and drawing utilities.

Primary palette follows antd v5 design tokens:
  colorPrimary      #1677FF   colorError    #FF4D4F
  colorSuccess      #52C41A   colorWarning  #FAAD14
  colorText         #262626   colorTextSecondary #8C8C8C
  colorBgContainer  #FFFFFF   colorBgLayout #F5F5F5
  colorBorder       #D9D9D9   colorBorderSecondary #F0F0F0
"""

from __future__ import annotations

import math

import pygame
import pygame.gfxdraw as gfx


def hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ── colour tokens ────────────────────────────────────────────────────────────
PAPER     = hex_rgb("#F5F5F5")   # colorBgLayout
SURFACE   = hex_rgb("#FFFFFF")   # colorBgContainer
BAND      = hex_rgb("#FAFAFA")   # table alternate row / card section bg
HAIRLINE  = hex_rgb("#F0F0F0")   # colorBorderSecondary
GRID      = hex_rgb("#F5F5F5")
INK       = hex_rgb("#262626")   # colorText
MUTED     = hex_rgb("#8C8C8C")   # colorTextSecondary
FAINT     = hex_rgb("#BFBFBF")   # colorTextDisabled
ACCENT    = hex_rgb("#1677FF")   # colorPrimary
ERROR     = hex_rgb("#FF4D4F")   # colorError
OK        = hex_rgb("#52C41A")   # colorSuccess
HIGHLIGHT = hex_rgb("#E6F4FF")   # colorPrimaryBg (hover / selected bg)
WALL      = hex_rgb("#FAFAFA")
ROAD      = hex_rgb("#D9D9D9")   # colorBorder

# Ant Design preset colour palette (one per order)
ORDER_COLORS = [hex_rgb(c) for c in (
    "#1677FF",  # blue
    "#52C41A",  # green
    "#FAAD14",  # gold
    "#FF4D4F",  # red
    "#722ED1",  # purple
    "#13C2C2",  # cyan
    "#FA8C16",  # orange
    "#EB2F96",  # magenta
)]

# Station colours → (background, accent) from antd preset colour bg/text pairs
STATION_STYLE = {
    "storage":   (hex_rgb("#FFF7E6"), hex_rgb("#FA8C16")),  # orange-1 / -6
    "prep":      (hex_rgb("#F6FFED"), hex_rgb("#52C41A")),  # green-1  / -6
    "stove":     (hex_rgb("#FFF1F0"), hex_rgb("#FF4D4F")),  # red-1    / -5
    "steamer":   (hex_rgb("#FFFBE6"), hex_rgb("#FAAD14")),  # yellow-1 / -6
    "packaging": (hex_rgb("#F0F5FF"), hex_rgb("#2F54EB")),  # geekblue-1 / -6
    "dispatch":  (hex_rgb("#E6FFFB"), hex_rgb("#13C2C2")),  # cyan-1   / -6
}
STATION_NAME = {
    "storage": "Storage shelf", "prep": "Prep counter", "stove": "Stove",
    "steamer": "Steamer", "packaging": "Packing table", "dispatch": "Dispatch door",
}
ZONE_NAME = {
    "storage": "Storage zone", "prep": "Preparation zone",
    "stove": "Cooking zone", "steamer": "Cooking zone",
    "packaging": "Packing zone", "dispatch": "Dispatch",
}
ALLERGEN_FREE = hex_rgb("#722ED1")   # purple (HACCP allergen-free)
FAILED_STYLE  = (hex_rgb("#FAFAFA"), hex_rgb("#D9D9D9"))


# ── colour helpers ───────────────────────────────────────────────────────────
def mix(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ── fonts ─────────────────────────────────────────────────────────────────────
_FONTS: dict = {}
_FAMILY = "segoeui,inter,helveticaneue,helvetica,dejavusans,arial"


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
    if text_width(s, size, bold) <= width:
        return s
    while s and text_width(s + "…", size, bold) > width:
        s = s[:-1]
    return s + "…"


def wrap(s: str, size: int, width: int) -> list:
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


# ── section heading ───────────────────────────────────────────────────────────
def section(surf, x, y, title, caption=""):
    """Ant Design card section heading — bold title with faint caption."""
    r = text(surf, title, (x, y), 14, INK, True)
    if caption:
        text(surf, caption, (r.right + 10, y + 1), 11, FAINT)


# ── line helpers ──────────────────────────────────────────────────────────────
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


# ── shape helpers ─────────────────────────────────────────────────────────────
def disc(surf, color, center, r):
    x, y, r = int(round(center[0])), int(round(center[1])), int(round(r))
    gfx.aacircle(surf, x, y, r, color)
    gfx.filled_circle(surf, x, y, r, color)


def ring(surf, color, center, r, fill=SURFACE):
    x, y, r = int(round(center[0])), int(round(center[1])), int(round(r))
    gfx.filled_circle(surf, x, y, r, color)
    gfx.aacircle(surf, x, y, r, color)
    gfx.filled_circle(surf, x, y, r - 2, fill)
    gfx.aacircle(surf, x, y, r - 2, fill)


def card(surf, rect: pygame.Rect, radius: int = 8) -> None:
    """Ant Design card: white bg, light border, two-layer drop shadow."""
    for dy, alpha, pad in ((4, 10, 6), (2, 16, 2)):
        sh = pygame.Surface((rect.width + pad * 2, rect.height + pad * 2), pygame.SRCALPHA)
        pygame.draw.rect(
            sh, (*INK, alpha),
            pygame.Rect(pad // 2, pad // 2 + dy, rect.width + pad, rect.height + pad),
            border_radius=radius + pad // 2,
        )
        surf.blit(sh, (rect.x - pad, rect.y - pad))
    pygame.draw.rect(surf, SURFACE, rect, border_radius=radius)
    pygame.draw.rect(surf, HAIRLINE, rect, 1, border_radius=radius)


def tag(surf, label: str, center, size=11, color=ACCENT, bg=HIGHLIGHT, radius=4) -> pygame.Rect:
    """Ant Design Tag component."""
    tw = text_width(label, size) + 14
    r = pygame.Rect(0, 0, tw, 20)
    r.center = center
    pygame.draw.rect(surf, bg, r, border_radius=radius)
    pygame.draw.rect(surf, color, r, 1, border_radius=radius)
    text(surf, label, r.center, size, color, anchor="center")
    return r
