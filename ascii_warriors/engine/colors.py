"""RGB colour type, palette and terminal colour quantisation.

Everything in the game speaks 24-bit RGB internally; :mod:`ascii_warriors.engine.terminal`
quantises down to 256- or 16-colour terminals at render time.
"""

from __future__ import annotations

from typing import Dict, NamedTuple, Tuple


def _clamp(v: int) -> int:
    """Clamp an int into the 0..255 channel range."""
    if v < 0:
        return 0
    if v > 255:
        return 255
    return int(v)


class Color(NamedTuple):
    """An 8-bit-per-channel RGB colour."""

    r: int
    g: int
    b: int

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return "#%02x%02x%02x" % (self.r, self.g, self.b)


def rgb(r: int, g: int, b: int) -> Color:
    """Build a :class:`Color`, clamping each channel."""
    return Color(_clamp(r), _clamp(g), _clamp(b))


def hexc(s: str) -> Color:
    """Parse ``"#rrggbb"``, ``"rrggbb"``, ``"#rgb"`` or ``"rgb"`` into a colour."""
    s = s.strip().lstrip("#")
    if len(s) == 3:
        return Color(int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16))
    if len(s) != 6:
        raise ValueError("bad hex colour: %r" % s)
    return Color(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def blend(a: Color, b: Color, t: float) -> Color:
    """Linear interpolation: ``t=0`` yields *a*, ``t=1`` yields *b*."""
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    return Color(
        _clamp(int(a.r + (b.r - a.r) * t)),
        _clamp(int(a.g + (b.g - a.g) * t)),
        _clamp(int(a.b + (b.b - a.b) * t)),
    )


def darken(c: Color, f: float) -> Color:
    """Scale a colour toward black. ``f=0`` is black, ``f=1`` is unchanged."""
    if f <= 0.0:
        return BLACK
    if f >= 1.0:
        return c
    return Color(_clamp(int(c.r * f)), _clamp(int(c.g * f)), _clamp(int(c.b * f)))


def lighten(c: Color, f: float) -> Color:
    """Scale a colour toward white. ``f=0`` is unchanged, ``f=1`` is white."""
    return blend(c, WHITE, max(0.0, min(1.0, f)))


def desaturate(c: Color, f: float) -> Color:
    """Move a colour toward its luminance. ``f=1`` yields pure grey."""
    lum = luminance(c)
    grey = Color(lum, lum, lum)
    return blend(c, grey, max(0.0, min(1.0, f)))


def luminance(c: Color) -> int:
    """Perceptual luminance of *c* as a 0..255 int."""
    return _clamp(int(0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b))


# --------------------------------------------------------------------------- #
# Named colours
# --------------------------------------------------------------------------- #

BLACK = Color(0, 0, 0)
WHITE = Color(255, 255, 255)
GRAY = Color(128, 128, 128)
GREY = GRAY
LGRAY = Color(190, 190, 190)
DGRAY = Color(72, 72, 76)

RED = Color(200, 48, 48)
DRED = Color(120, 24, 24)
LRED = Color(255, 106, 96)
GREEN = Color(64, 176, 64)
DGREEN = Color(32, 104, 40)
LGREEN = Color(128, 232, 120)
BLUE = Color(72, 104, 220)
DBLUE = Color(36, 56, 140)
LBLUE = Color(128, 176, 255)
CYAN = Color(72, 190, 190)
DCYAN = Color(28, 110, 116)
MAGENTA = Color(190, 72, 190)
DMAGENTA = Color(112, 36, 112)
YELLOW = Color(232, 208, 88)
DYELLOW = Color(168, 144, 40)
BROWN = Color(150, 104, 56)
DBROWN = Color(96, 64, 32)
ORANGE = Color(224, 132, 48)
PURPLE = Color(146, 92, 200)
PINK = Color(232, 148, 176)
TAN = Color(206, 178, 128)
OLIVE = Color(126, 132, 62)
SLATE = Color(96, 106, 122)
STEEL = Color(176, 184, 198)
GOLD = Color(224, 186, 72)
SILVER = Color(198, 206, 214)
COPPER = Color(186, 116, 66)
BLOOD = Color(148, 28, 28)
BONE = Color(226, 218, 194)

MOSS = Color(96, 132, 72)
RUST = Color(148, 84, 44)
ASH = Color(112, 108, 104)
EMBER = Color(238, 116, 40)
FLESH = Color(214, 160, 132)
IRON = Color(138, 142, 150)
BRONZE = Color(170, 128, 62)
LEATHER = Color(142, 98, 58)
WATER_BLUE = Color(58, 106, 168)
DEEP_WATER = Color(28, 58, 116)
LAVA = Color(226, 88, 26)
ICE = Color(196, 226, 240)
SAND = Color(214, 194, 142)
SOIL = Color(110, 84, 58)
STONE = Color(124, 122, 118)
GRASS_GREEN = Color(86, 148, 66)
FOREST = Color(46, 106, 54)
SNOW = Color(238, 244, 250)
NIGHT = Color(18, 20, 32)
MAGIC = Color(180, 120, 255)
POISON = Color(126, 196, 72)
FIRE = Color(246, 158, 52)

#: The classic 16-colour DF/CGA palette, by name.
PALETTE16: Dict[str, Color] = {
    "black": Color(0, 0, 0),
    "blue": Color(0, 0, 170),
    "green": Color(0, 170, 0),
    "cyan": Color(0, 170, 170),
    "red": Color(170, 0, 0),
    "magenta": Color(170, 0, 170),
    "brown": Color(170, 85, 0),
    "lgray": Color(170, 170, 170),
    "dgray": Color(85, 85, 85),
    "lblue": Color(85, 85, 255),
    "lgreen": Color(85, 255, 85),
    "lcyan": Color(85, 255, 255),
    "lred": Color(255, 85, 85),
    "lmagenta": Color(255, 85, 255),
    "yellow": Color(255, 255, 85),
    "white": Color(255, 255, 255),
}

#: Semantic UI palette used by every screen.
UI: Dict[str, Color] = {
    "bg": Color(14, 15, 20),
    "fg": Color(198, 196, 186),
    "dim": Color(112, 110, 104),
    "accent": Color(206, 168, 88),
    "accent2": Color(108, 158, 176),
    "warn": Color(224, 164, 56),
    "danger": Color(206, 62, 54),
    "good": Color(112, 186, 96),
    "frame": Color(84, 80, 72),
    "frame_hi": Color(160, 142, 100),
    "title": Color(228, 202, 132),
    "select_bg": Color(58, 54, 44),
    "select_fg": Color(248, 236, 202),
    "shadow": Color(8, 8, 10),
}

_NAMED: Dict[str, Color] = dict(PALETTE16)
_NAMED.update(
    {
        "gray": GRAY,
        "grey": GRAY,
        "orange": ORANGE,
        "purple": PURPLE,
        "pink": PINK,
        "tan": TAN,
        "gold": GOLD,
        "silver": SILVER,
        "copper": COPPER,
        "blood": BLOOD,
        "bone": BONE,
        "steel": STEEL,
        "olive": OLIVE,
        "slate": SLATE,
        "moss": MOSS,
        "rust": RUST,
        "ash": ASH,
        "ember": EMBER,
        "flesh": FLESH,
        "iron": IRON,
        "bronze": BRONZE,
        "leather": LEATHER,
        "lava": LAVA,
        "ice": ICE,
        "sand": SAND,
        "soil": SOIL,
        "stone": STONE,
        "snow": SNOW,
        "magic": MAGIC,
        "poison": POISON,
        "fire": FIRE,
    }
)


def ansi_name_to_color(name: str) -> Color:
    """Resolve a colour name (16-colour names plus extras) to a :class:`Color`."""
    key = name.strip().lower()
    if key in _NAMED:
        return _NAMED[key]
    if key in UI:
        return UI[key]
    if key.startswith("#"):
        return hexc(key)
    return UI["fg"]


def color_names() -> Tuple[str, ...]:
    """All names accepted by :func:`ansi_name_to_color`."""
    return tuple(sorted(set(list(_NAMED) + list(UI))))


# --------------------------------------------------------------------------- #
# Quantisation
# --------------------------------------------------------------------------- #

_CUBE_STEPS = (0, 95, 135, 175, 215, 255)


def _cube_index(v: int) -> int:
    """Nearest index into the xterm 6-level colour cube."""
    best, best_d = 0, 1 << 30
    for i, s in enumerate(_CUBE_STEPS):
        d = abs(s - v)
        if d < best_d:
            best, best_d = i, d
    return best


def _dist(a: Color, r: int, g: int, b: int) -> int:
    dr, dg, db = a.r - r, a.g - g, a.b - b
    return dr * dr + dg * dg + db * db


#: The 16 system colours as xterm renders them, in ANSI index order.
_SYSTEM16: Tuple[Color, ...] = (
    Color(0, 0, 0),
    Color(205, 0, 0),
    Color(0, 205, 0),
    Color(205, 205, 0),
    Color(0, 0, 238),
    Color(205, 0, 205),
    Color(0, 205, 205),
    Color(229, 229, 229),
    Color(127, 127, 127),
    Color(255, 0, 0),
    Color(0, 255, 0),
    Color(255, 255, 0),
    Color(92, 92, 255),
    Color(255, 0, 255),
    Color(0, 255, 255),
    Color(255, 255, 255),
)

_to256_cache: Dict[Color, int] = {}
_to16_cache: Dict[Color, int] = {}


def to_256(c: Color) -> int:
    """Nearest xterm-256 palette index for *c*."""
    cached = _to256_cache.get(c)
    if cached is not None:
        return cached

    # Candidate 1: the 6x6x6 colour cube.
    ri, gi, bi = _cube_index(c.r), _cube_index(c.g), _cube_index(c.b)
    cube_idx = 16 + 36 * ri + 6 * gi + bi
    cube_d = _dist(c, _CUBE_STEPS[ri], _CUBE_STEPS[gi], _CUBE_STEPS[bi])

    # Candidate 2: the 24-step grey ramp.
    avg = (c.r + c.g + c.b) // 3
    step = int(round((avg - 8) / 10.0))
    if step < 0:
        step = 0
    elif step > 23:
        step = 23
    grey_v = 8 + step * 10
    grey_idx = 232 + step
    grey_d = _dist(c, grey_v, grey_v, grey_v)

    # Candidate 3: the 16 system colours (they cover pure black/white best).
    sys_idx, sys_d = 0, 1 << 30
    for i, sc in enumerate(_SYSTEM16):
        d = _dist(c, sc.r, sc.g, sc.b)
        if d < sys_d:
            sys_idx, sys_d = i, d

    best_idx, best_d = cube_idx, cube_d
    if grey_d < best_d:
        best_idx, best_d = grey_idx, grey_d
    if sys_d < best_d:
        best_idx = sys_idx

    if len(_to256_cache) < 8192:
        _to256_cache[c] = best_idx
    return best_idx


def to_16(c: Color) -> int:
    """Nearest ANSI 16-colour index (0..15) for *c*."""
    cached = _to16_cache.get(c)
    if cached is not None:
        return cached
    best, best_d = 7, 1 << 30
    for i, sc in enumerate(_SYSTEM16):
        d = _dist(c, sc.r, sc.g, sc.b)
        if d < best_d:
            best, best_d = i, d
    if len(_to16_cache) < 8192:
        _to16_cache[c] = best
    return best
