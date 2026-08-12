"""Local-map terrain tiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional

from ..engine import colors
from ..engine.colors import Color


@dataclass(frozen=True)
class TileDef:
    """One kind of terrain square."""

    id: str
    name: str
    glyph: str
    color: Color
    bg: Optional[Color]
    walk: bool
    sight: bool
    swim: bool
    climb: bool
    flags: FrozenSet[str]
    material: str = ""
    description: str = ""

    def has(self, flag: str) -> bool:
        """True if this tile carries *flag*."""
        return flag in self.flags


def _t(
    tid: str, name: str, glyph: str, color: Color, walk: bool, sight: bool,
    *flags: str, bg: Optional[Color] = None, swim: bool = False,
    climb: bool = False, material: str = "", desc: str = "",
) -> TileDef:
    return TileDef(
        id=tid, name=name, glyph=glyph, color=color, bg=bg, walk=walk,
        sight=sight, swim=swim, climb=climb, flags=frozenset(flags),
        material=material, description=desc,
    )


_GROUND = colors.Color(96, 84, 66)

TILES: Dict[str, TileDef] = {
    t.id: t
    for t in (
        _t("air", "open space", " ", colors.NIGHT, False, True, "OPEN"),
        _t("floor", "floor", ".", _GROUND, True, True, "FLOOR"),
        _t("dirt", "dirt", ".", colors.SOIL, True, True, "FLOOR", "DIGGABLE",
           material="dirt"),
        _t("grass", "grass", ".", colors.GRASS_GREEN, True, True, "FLOOR",
           "GRASS", "DIGGABLE"),
        _t("grass_dead", "dead grass", ".", colors.Color(146, 134, 88), True,
           True, "FLOOR", "GRASS", "DIGGABLE"),
        _t("sand", "sand", ".", colors.SAND, True, True, "FLOOR", "SAND",
           "DIGGABLE", material="sand"),
        _t("mud", "mud", ",", colors.Color(96, 76, 56), True, True, "FLOOR",
           "DIGGABLE", material="mud"),
        _t("snow", "snow", ".", colors.SNOW, True, True, "FLOOR", "DIGGABLE"),
        _t("stone_floor", "stone floor", ".", colors.STONE, True, True, "FLOOR"),
        _t("rock_wall", "rock wall", "#", colors.Color(122, 118, 112), False,
           False, "WALL", "DIGGABLE", climb=True, material="granite",
           desc="Solid stone. A pick would go through it."),
        _t("soil_wall", "soil wall", "#", colors.Color(104, 80, 56), False,
           False, "WALL", "DIGGABLE", climb=True, material="dirt"),
        _t("ore_vein", "ore vein", "*", colors.Color(178, 150, 96), False,
           False, "WALL", "DIGGABLE", "ORE", climb=True),
        _t("gem_vein", "gem cluster", "*", colors.Color(150, 200, 220), False,
           False, "WALL", "DIGGABLE", "GEM", climb=True),
        _t("tree", "tree", "T", colors.FOREST, False, False, "TREE",
           "FLAMMABLE", climb=True,
           desc="An elf would be upset if you cut this down."),
        _t("sapling", "sapling", "i", colors.Color(110, 168, 96), True, True,
           "TREE", "FLAMMABLE"),
        _t("shrub", "shrub", '"', colors.Color(86, 140, 72), True, True,
           "FLAMMABLE"),
        _t("boulder", "boulder", "*", colors.Color(140, 136, 130), False, True,
           "WALL"),
        _t("rubble", "rubble", "%", colors.Color(130, 122, 112), True, True,
           "FLOOR"),
        _t("shallow_water", "shallow water", "~", colors.Color(96, 150, 200),
           True, True, "WATER", bg=colors.Color(26, 44, 70), swim=False,
           material="water"),
        _t("water", "water", "~", colors.WATER_BLUE, False, True, "WATER",
           bg=colors.Color(20, 36, 62), swim=True, material="water"),
        _t("deep_water", "deep water", "~", colors.DEEP_WATER, False, True,
           "WATER", "DEEP", bg=colors.Color(12, 22, 44), swim=True,
           material="water", desc="Dark and cold. Things live down there."),
        _t("ice", "ice", "+", colors.ICE, True, True, "FLOOR", "ICE",
           material="ice"),
        _t("lava", "lava", "~", colors.LAVA, False, True, "LAVA",
           bg=colors.Color(90, 26, 10), material="obsidian",
           desc="Molten rock. Do not swim."),
        _t("chasm", "chasm", ">", colors.NIGHT, False, True, "OPEN", "CHASM",
           desc="It goes down further than you can see."),
        _t("stair_up", "up staircase", "<", colors.Color(198, 190, 176), True,
           True, "FLOOR", "STAIR_UP"),
        _t("stair_down", "down staircase", ">", colors.Color(198, 190, 176),
           True, True, "FLOOR", "STAIR_DOWN"),
        _t("stair_updown", "staircase", "x", colors.Color(198, 190, 176), True,
           True, "FLOOR", "STAIR_UP", "STAIR_DOWN"),
        _t("ramp_up", "upward ramp", "/", colors.Color(178, 170, 156), True,
           True, "FLOOR", "RAMP", "STAIR_UP"),
        _t("ramp_down", "downward ramp", "\\", colors.Color(178, 170, 156),
           True, True, "FLOOR", "RAMP", "STAIR_DOWN"),
        _t("door_closed", "door", "+", colors.Color(160, 118, 66), True, False,
           "DOOR", "CONSTRUCTED"),
        _t("door_open", "open door", "'", colors.Color(160, 118, 66), True,
           True, "DOOR", "OPEN", "CONSTRUCTED"),
        _t("wall_constructed", "wall", "#", colors.Color(168, 160, 146), False,
           False, "WALL", "CONSTRUCTED", climb=True),
        _t("floor_constructed", "smooth floor", ".", colors.Color(150, 144, 132),
           True, True, "FLOOR", "CONSTRUCTED"),
        _t("bridge", "bridge", "=", colors.Color(150, 112, 66), True, True,
           "FLOOR", "CONSTRUCTED"),
        _t("road", "road", ".", colors.Color(142, 128, 106), True, True,
           "FLOOR", "CONSTRUCTED"),
        _t("track", "worn track", ".", colors.Color(126, 112, 92), True, True,
           "FLOOR"),
        _t("fortification", "fortification", "#", colors.Color(178, 172, 158),
           False, True, "WALL", "CONSTRUCTED"),
        _t("bed", "bed", "=", colors.Color(178, 142, 96), True, True, "FLOOR",
           "FURNITURE"),
        _t("table", "table", "=", colors.Color(160, 124, 78), True, True,
           "FLOOR", "FURNITURE"),
        _t("chair", "chair", "=", colors.Color(150, 116, 72), True, True,
           "FLOOR", "FURNITURE"),
        _t("cabinet", "cabinet", "=", colors.Color(140, 108, 68), False, True,
           "FURNITURE"),
        _t("coffer", "coffer", "=", colors.Color(180, 150, 90), False, True,
           "FURNITURE", "CONTAINER"),
        _t("altar", "altar", "_", colors.Color(214, 206, 186), True, True,
           "FLOOR", "FURNITURE"),
        _t("statue", "statue", "&", colors.Color(196, 190, 178), False, True,
           "FURNITURE"),
        _t("well", "well", "o", colors.Color(150, 160, 176), True, True,
           "FLOOR", "FURNITURE", "WATER_SOURCE"),
        _t("fire", "fire", "^", colors.FIRE, False, True, "FIRE", "LIGHT",
           bg=colors.Color(70, 26, 8)),
        _t("campfire", "campfire", "^", colors.EMBER, True, True, "FLOOR",
           "FIRE", "LIGHT"),
        _t("grave", "grave", "+", colors.Color(120, 116, 108), True, True,
           "FLOOR", "FURNITURE"),
        _t("web", "web", "*", colors.Color(210, 212, 218), True, True, "WEB"),
    )
}


def get(tid: str) -> TileDef:
    """Look up a tile definition, defaulting to floor."""
    return TILES.get(tid) or TILES["floor"]


def exists(tid: str) -> bool:
    """True if *tid* names a known tile."""
    return tid in TILES


def walkable(tid: str) -> bool:
    """True if creatures can walk on this tile."""
    return get(tid).walk


def blocks_sight(tid: str) -> bool:
    """True if this tile stops line of sight."""
    return not get(tid).sight


def is_wall(tid: str) -> bool:
    """True for solid walls."""
    return get(tid).has("WALL")


def is_open(tid: str) -> bool:
    """True for empty air a creature would fall through."""
    return get(tid).has("OPEN")


def is_water(tid: str) -> bool:
    """True for any water tile."""
    return get(tid).has("WATER")


def is_stair_up(tid: str) -> bool:
    """True if you can climb up here."""
    return get(tid).has("STAIR_UP")


def is_stair_down(tid: str) -> bool:
    """True if you can climb down here."""
    return get(tid).has("STAIR_DOWN")


def is_diggable(tid: str) -> bool:
    """True if a pick can remove this tile."""
    return get(tid).has("DIGGABLE")


def by_flag(flag: str) -> List[TileDef]:
    """Every tile carrying *flag*."""
    return [t for t in TILES.values() if t.has(flag)]
