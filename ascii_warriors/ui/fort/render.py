"""Drawing the fortress map.

Fortress mode has no fog of war: you are looking at your own fortress, and you
are allowed to know what is in it. Levels below the current one show through
open space, dimmer with depth, the way a cutaway drawing works.
"""

from __future__ import annotations

from typing import Optional, Tuple

from ...data import materials as mat_data
from ...engine import colors
from ...engine.colors import Color
from ...engine.screen import Screen
from ...fortress import designations as designation_mod
from ...world import tiles as tile_data

Cell = Tuple[int, int, int]

#: How much dimmer each level below the current one renders.
DEPTH_FADE = 0.5
#: Floor of the depth fade, so the bottom of a shaft is not pure black.
DEPTH_FLOOR = 0.16


def cell_appearance(fort, x: int, y: int, z: int) -> Tuple[str, Color, Color]:
    """Glyph, foreground and background for one map cell."""
    lm = fort.local
    tid = lm.tile(x, y, z)
    t = tile_data.get(tid)
    bg = t.bg if t.bg is not None else colors.UI["bg"]

    if t.has("OPEN"):
        depth = 0
        zz = z - 1
        while zz >= lm.zmin and depth < 6:
            below = tile_data.get(lm.tile(x, y, zz))
            if not below.has("OPEN"):
                fade = max(DEPTH_FLOOR, DEPTH_FADE ** (depth + 1))
                bbg = below.bg if below.bg is not None else colors.UI["bg"]
                return (below.glyph, colors.darken(below.color, fade),
                        colors.darken(bbg, fade * 0.8))
            depth += 1
            zz -= 1
        return (" ", colors.UI["bg"], colors.UI["bg"])
    if t.has("ORE") or t.has("GEM"):
        # Veins are drawn in the colour of what is in them, so a wall of gold
        # and a wall of tin are not the same wall.
        material = lm.veins.get((x, y, z))
        if material:
            return (t.glyph, mat_data.get(material).color, bg)
    return (t.glyph, t.color, bg)


def draw_map(
    scr: Screen, fort, ox: int, oy: int, w: int, h: int,
    cam_x: int, cam_y: int, *, cursor: Optional[Cell] = None,
    region: Optional[Tuple[int, int, int, int]] = None,
    ghost: Optional[Tuple[str, int, int, int, int]] = None,
) -> None:
    """Render the fortress.

    *region* is a highlighted rectangle in world coordinates and *ghost* is a
    ``(glyph, x, y, w, h)`` outline for a building being placed.
    """
    lm = fort.local
    z = fort.z

    for sy in range(h):
        wy = cam_y + sy
        if wy < 0 or wy >= lm.height:
            continue
        for sx in range(w):
            wx = cam_x + sx
            if wx < 0 or wx >= lm.width:
                continue
            glyph, fg, bg = cell_appearance(fort, wx, wy, z)
            scr.put(ox + sx, oy + sy, glyph, fg, bg)

    _draw_water(scr, fort, ox, oy, w, h, cam_x, cam_y)
    _draw_magma(scr, fort, ox, oy, w, h, cam_x, cam_y)
    _draw_fire(scr, fort, ox, oy, w, h, cam_x, cam_y)
    _draw_zones(scr, fort, ox, oy, w, h, cam_x, cam_y)
    _draw_designations(scr, fort, ox, oy, w, h, cam_x, cam_y)
    _draw_buildings(scr, fort, ox, oy, w, h, cam_x, cam_y)
    _draw_items(scr, fort, ox, oy, w, h, cam_x, cam_y)
    _draw_creatures(scr, fort, ox, oy, w, h, cam_x, cam_y)

    if region is not None:
        _draw_region(scr, ox, oy, w, h, cam_x, cam_y, region)
    if ghost is not None:
        _draw_ghost(scr, ox, oy, w, h, cam_x, cam_y, ghost)
    if cursor is not None and cursor[2] == z:
        sx, sy = cursor[0] - cam_x, cursor[1] - cam_y
        if 0 <= sx < w and 0 <= sy < h:
            ch, fg, _bg = scr.get(ox + sx, oy + sy)
            scr.put(ox + sx, oy + sy, ch, colors.UI["bg"], colors.UI["accent"])


#: Background shades for water one to seven deep.
WATER_SHADES = (
    colors.Color(24, 40, 62), colors.Color(26, 48, 76),
    colors.Color(28, 56, 92), colors.Color(28, 64, 108),
    colors.Color(26, 70, 124), colors.Color(22, 74, 140),
    colors.Color(18, 76, 156),
)


def _draw_water(scr, fort, ox, oy, w, h, cam_x, cam_y) -> None:
    """Water, shaded by how deep it is.

    Depth is what matters: a dwarf can wade through two and drowns in seven,
    and the player has to be able to tell those apart at a glance.
    """
    water = getattr(fort, "water", None)
    if water is None:
        return
    from ...world.fluids import SWIM_DEPTH

    for (wx, wy, wz), depth in water.depth.items():
        if wz != fort.z or depth <= 0:
            continue
        sx, sy = wx - cam_x, wy - cam_y
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        ch, fg, _bg = scr.get(ox + sx, oy + sy)
        bg = WATER_SHADES[min(depth, 7) - 1]
        if depth >= SWIM_DEPTH:
            scr.put(ox + sx, oy + sy, "~", colors.Color(120, 175, 225), bg)
        else:
            scr.put(ox + sx, oy + sy, ch, fg, bg)


#: Background shades for magma one to seven deep. There is no safe depth.
MAGMA_SHADES = (
    colors.Color(78, 22, 10), colors.Color(96, 28, 10),
    colors.Color(118, 36, 10), colors.Color(142, 46, 10),
    colors.Color(168, 58, 10), colors.Color(194, 72, 12),
    colors.Color(220, 88, 14),
)


def _draw_magma(scr, fort, ox, oy, w, h, cam_x, cam_y) -> None:
    """Magma, over the top of everything else on the level."""
    magma = getattr(fort, "magma", None)
    if magma is None:
        return
    for (wx, wy, wz), depth in magma.depth.items():
        if wz != fort.z or depth <= 0:
            continue
        sx, sy = wx - cam_x, wy - cam_y
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        scr.put(ox + sx, oy + sy, "~", colors.Color(255, 210, 120),
                MAGMA_SHADES[min(depth, 7) - 1])


#: Flame colours, hottest first. A fire that has nearly burnt out is embers.
FIRE_SHADES = (
    colors.Color(255, 232, 150), colors.Color(255, 176, 48),
    colors.Color(214, 96, 24), colors.Color(150, 54, 20),
)


def _draw_fire(scr, fort, ox, oy, w, h, cam_x, cam_y) -> None:
    """Whatever is alight, over everything else on the level."""
    from ...world import fire as fire_mod

    blaze = getattr(fort, "fire", None)
    if blaze is None or not blaze.anything_burning:
        return
    for (wx, wy, wz), left in blaze.fuel.items():
        if wz != fort.z or left <= 0:
            continue
        sx, sy = wx - cam_x, wy - cam_y
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        band = min(len(FIRE_SHADES) - 1,
                   max(0, (fire_mod.TILE_FUEL["tree"] - left) // 24))
        scr.put(ox + sx, oy + sy, "^", FIRE_SHADES[band],
                colors.Color(60, 20, 8))


def _draw_zones(scr, fort, ox, oy, w, h, cam_x, cam_y) -> None:
    """Stockpile and burrow rectangles, tinted behind whatever is on them."""
    for pile in fort.stockpiles:
        if pile.z != fort.z:
            continue
        tint = pile.color
        for cx, cy, _cz in pile.cells():
            sx, sy = cx - cam_x, cy - cam_y
            if not (0 <= sx < w and 0 <= sy < h):
                continue
            ch, fg, _bg = scr.get(ox + sx, oy + sy)
            scr.put(ox + sx, oy + sy, ch, fg, colors.darken(tint, 0.22))

    burrow = getattr(fort, "military", None)
    if burrow is None or burrow.burrow is None:
        return
    tint = (colors.Color(90, 40, 40) if burrow.alarm
            else colors.Color(40, 50, 70))
    for cx, cy, cz in burrow.burrow_cells():
        if cz != fort.z:
            continue
        sx, sy = cx - cam_x, cy - cam_y
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        ch, fg, _bg = scr.get(ox + sx, oy + sy)
        scr.put(ox + sx, oy + sy, ch, fg, tint)


def _draw_designations(scr, fort, ox, oy, w, h, cam_x, cam_y) -> None:
    """The marks the player has painted."""
    for cell, kind in fort.designations.on_level(fort.z):
        sx, sy = cell[0] - cam_x, cell[1] - cam_y
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        glyph, colour = designation_mod.render(kind)
        claimed = cell in fort.designations.claimed
        scr.put(ox + sx, oy + sy, glyph,
                colour if not claimed else colors.darken(colour, 0.6),
                colors.Color(40, 36, 28))


def _draw_buildings(scr, fort, ox, oy, w, h, cam_x, cam_y) -> None:
    """Workshops and furniture, with unbuilt plans shown faintly."""
    for b in fort.buildings:
        if b.z != fort.z:
            continue
        defn = b.defn
        for cx, cy, _cz in b.cells():
            sx, sy = cx - cam_x, cy - cam_y
            if not (0 <= sx < w and 0 <= sy < h):
                continue
            if b.built:
                scr.put(ox + sx, oy + sy, defn.glyph, defn.color)
            else:
                scr.put(ox + sx, oy + sy, defn.glyph,
                        colors.darken(defn.color, 0.4),
                        colors.Color(30, 30, 38))


def _draw_items(scr, fort, ox, oy, w, h, cam_x, cam_y) -> None:
    """Loose goods on the floor."""
    for (ix, iy, iz), pile in fort.items_on_ground.items():
        if iz != fort.z or not pile:
            continue
        sx, sy = ix - cam_x, iy - cam_y
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        item = pile[-1]
        _ch, _fg, bg = scr.get(ox + sx, oy + sy)
        scr.put(ox + sx, oy + sy, item.glyph, item.color, bg)


def _draw_creatures(scr, fort, ox, oy, w, h, cam_x, cam_y) -> None:
    """Dwarves and whatever has come to visit them."""
    for c in fort.creatures.values():
        if c.z != fort.z or c.body.dead:
            continue
        sx, sy = c.x - cam_x, c.y - cam_y
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        glyph, colour = c.glyph_and_color()
        _ch, _fg, bg = scr.get(ox + sx, oy + sy)
        if c.faction == "hostile":
            bg = colors.Color(60, 16, 16)
        scr.put(ox + sx, oy + sy, glyph, colour, bg)


def _draw_region(scr, ox, oy, w, h, cam_x, cam_y, region) -> None:
    """Tint the rectangle a drag is covering."""
    x0, y0, x1, y1 = region
    lo_x, hi_x = sorted((x0, x1))
    lo_y, hi_y = sorted((y0, y1))
    for wy in range(lo_y, hi_y + 1):
        for wx in range(lo_x, hi_x + 1):
            sx, sy = wx - cam_x, wy - cam_y
            if not (0 <= sx < w and 0 <= sy < h):
                continue
            ch, fg, _bg = scr.get(ox + sx, oy + sy)
            scr.put(ox + sx, oy + sy, ch, fg, colors.Color(58, 58, 26))


def _draw_ghost(scr, ox, oy, w, h, cam_x, cam_y, ghost) -> None:
    """Outline of a building about to be placed."""
    glyph, gx, gy, gw, gh = ghost
    for dy in range(gh):
        for dx in range(gw):
            sx, sy = gx + dx - cam_x, gy + dy - cam_y
            if not (0 <= sx < w and 0 <= sy < h):
                continue
            scr.put(ox + sx, oy + sy, glyph, colors.UI["accent"],
                    colors.Color(30, 44, 30))


def clamp_camera(fort, cam_x: int, cam_y: int, w: int, h: int) -> Tuple[int, int]:
    """Keep the viewport inside the map."""
    lm = fort.local
    cam_x = max(0, min(max(0, lm.width - w), cam_x))
    cam_y = max(0, min(max(0, lm.height - h), cam_y))
    return (cam_x, cam_y)
