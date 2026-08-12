"""Biomes: the climate classes world generation assigns and local maps read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

from ..engine import colors
from ..engine.colors import Color


@dataclass(frozen=True)
class Biome:
    """A climate zone with its terrain, colours and travel properties."""

    id: str
    name: str
    glyph: str
    color: Color
    map_color: Color
    tree_density: float
    shrub_density: float
    grass: bool
    soil: str
    stone: str
    savagery_bias: int
    temperature_bias: int
    flags: FrozenSet[str]
    travel_cost: float = 1.0
    description: str = ""

    def has(self, flag: str) -> bool:
        """True if this biome carries *flag*."""
        return flag in self.flags

    @property
    def is_water(self) -> bool:
        """True for oceans, lakes and rivers."""
        return "WATER" in self.flags


def _b(
    bid: str, name: str, glyph: str, color: Color, map_color: Color,
    trees: float, shrubs: float, grass: bool, soil: str, stone: str,
    savagery: int, temp: int, flags: Tuple[str, ...], cost: float = 1.0,
    desc: str = "",
) -> Biome:
    return Biome(
        id=bid, name=name, glyph=glyph, color=color, map_color=map_color,
        tree_density=trees, shrub_density=shrubs, grass=grass,
        soil=soil, stone=stone, savagery_bias=savagery, temperature_bias=temp,
        flags=frozenset(flags), travel_cost=cost, description=desc,
    )


BIOMES: Dict[str, Biome] = {
    b.id: b
    for b in (
        _b("deep_ocean", "Deep Ocean", "~", colors.DEEP_WATER, colors.DEEP_WATER,
           0.0, 0.0, False, "sand", "basalt", 0, 0, ("WATER", "DEEP"), 6.0,
           "Black water with no bottom in sight."),
        _b("ocean", "Ocean", "~", colors.WATER_BLUE, colors.WATER_BLUE,
           0.0, 0.0, False, "sand", "basalt", 0, 0, ("WATER",), 4.0,
           "Salt water stretching to the horizon."),
        _b("lake", "Lake", "~", colors.Color(72, 132, 196), colors.Color(72, 132, 196),
           0.0, 0.0, False, "mud", "limestone", 0, 0, ("WATER",), 3.0),
        _b("river", "River", "~", colors.Color(84, 144, 206),
           colors.Color(84, 144, 206), 0.02, 0.1, True, "mud", "limestone",
           0, 0, ("WATER",), 2.0),
        _b("glacier", "Glacier", "*", colors.ICE, colors.Color(214, 236, 246),
           0.0, 0.0, False, "ice", "granite", 10, -40, ("FROZEN",), 2.2,
           "A groaning river of ice."),
        _b("tundra", "Tundra", "\"", colors.Color(174, 186, 176),
           colors.Color(174, 186, 176), 0.01, 0.05, True, "dirt", "granite",
           10, -25, ("FROZEN", "GRASS"), 1.3),
        _b("taiga", "Taiga", "&", colors.Color(66, 116, 84),
           colors.Color(66, 116, 84), 0.55, 0.2, True, "dirt", "granite",
           15, -15, ("FOREST", "GRASS"), 1.6,
           "Dark conifers standing shoulder to shoulder."),
        _b("temperate_forest", "Temperate Forest", "&", colors.FOREST,
           colors.FOREST, 0.6, 0.25, True, "dirt", "limestone", 10, 0,
           ("FOREST", "GRASS"), 1.5),
        _b("temperate_broadleaf", "Broadleaf Forest", "&",
           colors.Color(64, 132, 60), colors.Color(64, 132, 60), 0.65, 0.3,
           True, "dirt", "limestone", 10, 5, ("FOREST", "GRASS"), 1.5),
        _b("tropical_forest", "Tropical Forest", "&", colors.Color(38, 128, 62),
           colors.Color(38, 128, 62), 0.7, 0.35, True, "dirt", "limestone",
           25, 25, ("FOREST", "GRASS"), 1.7),
        _b("jungle", "Jungle", "&", colors.Color(26, 110, 48),
           colors.Color(26, 110, 48), 0.85, 0.5, True, "mud", "limestone",
           40, 30, ("FOREST", "GRASS"), 2.2,
           "Green so thick it swallows the light."),
        _b("savanna", "Savanna", "\"", colors.Color(174, 162, 76),
           colors.Color(174, 162, 76), 0.08, 0.2, True, "dirt", "sandstone",
           25, 25, ("GRASS",), 1.1),
        _b("shrubland", "Shrubland", "\"", colors.Color(140, 148, 84),
           colors.Color(140, 148, 84), 0.08, 0.4, True, "dirt", "sandstone",
           15, 10, ("GRASS",), 1.2),
        _b("grassland", "Grassland", "\"", colors.GRASS_GREEN,
           colors.GRASS_GREEN, 0.03, 0.15, True, "dirt", "limestone",
           5, 5, ("GRASS",), 1.0,
           "Open country where you can see trouble coming."),
        _b("desert", "Desert", ".", colors.SAND, colors.SAND,
           0.005, 0.03, False, "sand", "sandstone", 20, 35, ("DESERT",), 1.4,
           "Sand and stone and a sun that does not forgive."),
        _b("badlands", "Badlands", ".", colors.Color(168, 116, 74),
           colors.Color(168, 116, 74), 0.01, 0.05, False, "sand", "sandstone",
           30, 25, ("DESERT",), 1.5),
        _b("mountain", "Mountain", "^", colors.Color(142, 138, 134),
           colors.Color(142, 138, 134), 0.05, 0.05, False, "dirt", "granite",
           20, -20, ("MOUNTAIN",), 2.5,
           "Bare rock and thin air. Dwarves call it home."),
        _b("hills", "Hills", "n", colors.Color(112, 140, 82),
           colors.Color(112, 140, 82), 0.25, 0.2, True, "dirt", "limestone",
           10, 0, ("GRASS",), 1.4),
        _b("marsh", "Marsh", "\"", colors.Color(96, 128, 96),
           colors.Color(96, 128, 96), 0.1, 0.4, True, "mud", "limestone",
           20, 5, ("WETLAND", "GRASS"), 2.0),
        _b("swamp", "Swamp", "&", colors.Color(72, 106, 72),
           colors.Color(72, 106, 72), 0.45, 0.4, True, "mud", "limestone",
           30, 15, ("WETLAND", "FOREST"), 2.3,
           "Standing water, biting flies and things that wait."),
        _b("beach", "Beach", ".", colors.Color(226, 208, 156),
           colors.Color(226, 208, 156), 0.02, 0.05, False, "sand", "sandstone",
           5, 5, ("DESERT",), 1.1),
        _b("volcano", "Volcano", "^", colors.LAVA, colors.Color(150, 60, 40),
           0.0, 0.0, False, "sand", "obsidian", 50, 60, ("MOUNTAIN", "EVIL"), 3.0,
           "The mountain is awake."),
    )
}


def get(bid: str) -> Biome:
    """Look up a biome, defaulting to grassland."""
    return BIOMES.get(bid) or BIOMES["grassland"]


def exists(bid: str) -> bool:
    """True if *bid* names a known biome."""
    return bid in BIOMES


def land_biomes() -> List[Biome]:
    """Every biome that is not water."""
    return [b for b in BIOMES.values() if not b.is_water]


def classify(
    elevation: float,
    rainfall: float,
    temperature: float,
    drainage: float,
    *,
    is_water: bool = False,
) -> str:
    """Pick a biome id from normalised climate values.

    *elevation*, *rainfall* and *drainage* run 0..1; *temperature* is in degrees
    Urist where 0 is freezing-cold tundra and 100 is scorching desert.
    """
    if is_water:
        if elevation < 0.18:
            return "deep_ocean"
        return "ocean"
    if elevation > 0.86:
        return "mountain"
    if temperature <= 5:
        return "glacier" if elevation > 0.55 else "tundra"
    if temperature <= 20:
        if rainfall > 0.45:
            return "taiga"
        return "tundra"
    if drainage < 0.22 and rainfall > 0.4:
        return "swamp" if rainfall > 0.62 else "marsh"
    if rainfall < 0.16:
        return "badlands" if drainage > 0.72 else "desert"
    if rainfall < 0.30:
        if temperature > 65:
            return "savanna"
        return "shrubland"
    if elevation > 0.68:
        return "hills"
    if rainfall > 0.70:
        if temperature > 70:
            return "jungle"
        if temperature > 50:
            return "tropical_forest"
        return "temperate_broadleaf"
    if rainfall > 0.46:
        if temperature > 62:
            return "tropical_forest"
        return "temperate_forest"
    if temperature > 68:
        return "savanna"
    return "grassland"


def savagery_name(value: int) -> str:
    """Wording for a 0..100 savagery value."""
    if value >= 66:
        return "Savage"
    if value >= 33:
        return "Wilderness"
    return "Serene"


def alignment_name(evil: int) -> str:
    """Wording for a 0..100 good/evil value (50 is neutral)."""
    if evil >= 70:
        return "Evil"
    if evil <= 30:
        return "Good"
    return "Neutral"


def region_adjective(biome_id: str, savagery: int, evil: int) -> str:
    """A DF-style region label such as ``"Sinister Forest"``."""
    biome = get(biome_id)
    align = alignment_name(evil)
    if align == "Evil":
        prefix = "Sinister" if savagery < 66 else "Haunted"
    elif align == "Good":
        prefix = "Serene" if savagery < 66 else "Joyous"
    else:
        prefix = savagery_name(savagery)
    return "%s %s" % (prefix, biome.name)
