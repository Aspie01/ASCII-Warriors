"""Material properties.

Yield and fracture figures are in kilopascals, roughly following Dwarf
Fortress's own material science: a weapon's edge only bites when the force it
delivers exceeds the target tissue's shear yield, and armour stops a blow by
spreading that force across its own material strength.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

from ..engine import colors
from ..engine.colors import Color


@dataclass(frozen=True)
class Material:
    """The physical properties of one substance."""

    id: str
    name: str
    adjective: str
    category: str
    density: int
    color: Color
    impact_yield: int
    impact_fracture: int
    impact_strain: int
    shear_yield: int
    shear_fracture: int
    shear_strain: int
    max_edge: int
    value: int
    melting_point: int
    flags: FrozenSet[str]

    def weight_of(self, volume_cm3: float) -> float:
        """Mass in kilograms of *volume_cm3* of this material."""
        return self.density * volume_cm3 / 1_000_000.0

    def has(self, flag: str) -> bool:
        """True if this material carries *flag*."""
        return flag in self.flags

    @property
    def is_metal(self) -> bool:
        """True for metals."""
        return "METAL" in self.flags

    @property
    def can_hold_edge(self) -> bool:
        """True if weapons of this material can cut rather than only bruise."""
        return self.max_edge >= 5000


def _m(
    mid: str,
    name: str,
    adjective: str,
    category: str,
    density: int,
    color: Color,
    iy: int,
    ifr: int,
    sy: int,
    sfr: int,
    max_edge: int,
    value: int,
    flags: Tuple[str, ...],
    melting: int = 12000,
    istrain: int = 940,
    sstrain: int = 940,
) -> Material:
    """Terse constructor keeping the table below readable."""
    return Material(
        id=mid, name=name, adjective=adjective, category=category,
        density=density, color=color,
        impact_yield=iy, impact_fracture=ifr, impact_strain=istrain,
        shear_yield=sy, shear_fracture=sfr, shear_strain=sstrain,
        max_edge=max_edge, value=value, melting_point=melting,
        flags=frozenset(flags),
    )


_METAL = ("METAL", "WEAPON_OK", "ARMOR_OK")
_STONE = ("STONE",)
# `ARMOR_OK` because a shield is armour and a wooden shield is a real thing.
# There is no recipe asking wood for a mail shirt, and the flag is a rule
# about what a workshop may accept, not a claim that it would be any good.
_WOOD = ("WOOD", "FLAMMABLE", "WEAPON_OK", "ARMOR_OK")
_ORGANIC = ("ORGANIC",)

MATERIALS: Dict[str, Material] = {}


def _add(mat: Material) -> Material:
    MATERIALS[mat.id] = mat
    return mat


# -- metals ----------------------------------------------------------------- #
_add(_m("copper", "copper", "copper", "metal", 8930, colors.COPPER,
        245000, 770000, 70000, 220000, 8000, 6, _METAL, 13123))
_add(_m("bronze", "bronze", "bronze", "metal", 8250, colors.BRONZE,
        400000, 700000, 130000, 260000, 9000, 10, _METAL, 13260))
_add(_m("bismuth_bronze", "bismuth bronze", "bismuth bronze", "metal", 8250,
        colors.Color(150, 148, 96),
        400000, 700000, 130000, 260000, 9000, 12, _METAL, 13260))
_add(_m("iron", "iron", "iron", "metal", 7850, colors.IRON,
        542500, 1080000, 155000, 310000, 10000, 10, _METAL, 13573))
_add(_m("steel", "steel", "steel", "metal", 7850, colors.STEEL,
        1505000, 2520000, 430000, 720000, 10000, 30, _METAL, 13683))
_add(_m("silver", "silver", "silver", "metal", 10490, colors.SILVER,
        175000, 245000, 50000, 70000, 5000, 30,
        ("METAL", "ARMOR_OK", "WEAPON_OK"), 12234))
_add(_m("gold", "gold", "gold", "metal", 19320, colors.GOLD,
        170000, 210000, 50000, 60000, 3000, 60, ("METAL", "ARMOR_OK"), 12142))
_add(_m("platinum", "platinum", "platinum", "metal", 21400,
        colors.Color(214, 216, 220),
        350000, 490000, 100000, 140000, 4000, 80, ("METAL", "ARMOR_OK"), 13045))
_add(_m("adamantine", "adamantine", "adamantine", "metal", 200,
        colors.Color(140, 226, 232),
        5000000, 5000000, 5000000, 5000000, 10000, 300,
        ("METAL", "WEAPON_OK", "ARMOR_OK", "MAGICAL"), 25000))
_add(_m("lead", "lead", "lead", "metal", 11340, colors.Color(120, 124, 136),
        60000, 90000, 15000, 25000, 1000, 4, ("METAL", "ARMOR_OK"), 10725))
_add(_m("nickel", "nickel", "nickel", "metal", 8900, colors.Color(190, 190, 176),
        380000, 655000, 110000, 190000, 8000, 12, _METAL, 13494))
_add(_m("tin", "tin", "tin", "metal", 7300, colors.Color(196, 200, 206),
        60000, 100000, 20000, 30000, 2000, 5, ("METAL", "ARMOR_OK"), 10505))

#: Weapon metals ordered from worst to best.
WEAPON_METALS: List[str] = [
    "copper", "bismuth_bronze", "bronze", "iron", "steel", "adamantine",
]

#: Stone the smelter burns off to make steel. Any of these will do.
FLUX_STONES: List[str] = ["limestone", "marble", "chalk"]

# -- stone ------------------------------------------------------------------ #
_add(_m("granite", "granite", "granite", "stone", 2700, colors.Color(146, 138, 132),
        1000, 1000, 800, 800, 0, 3, _STONE + ("WEAPON_OK",), 25000))
_add(_m("gabbro", "gabbro", "gabbro", "stone", 3000, colors.Color(96, 96, 100),
        1000, 1000, 800, 800, 0, 3, _STONE + ("WEAPON_OK",), 25000))
_add(_m("basalt", "basalt", "basalt", "stone", 3000, colors.Color(72, 72, 78),
        1000, 1000, 800, 800, 0, 3, _STONE, 25000))
_add(_m("obsidian", "obsidian", "obsidian", "stone", 2500, colors.Color(38, 34, 44),
        1000, 1000, 800, 800, 8000, 4, _STONE + ("WEAPON_OK",), 25000))
_add(_m("marble", "marble", "marble", "stone", 2700, colors.Color(226, 224, 216),
        1000, 1000, 800, 800, 0, 10, _STONE, 25000))
_add(_m("limestone", "limestone", "limestone", "stone", 2600,
        colors.Color(196, 190, 168), 1000, 1000, 800, 800, 0, 3, _STONE, 25000))
_add(_m("sandstone", "sandstone", "sandstone", "stone", 2320,
        colors.Color(206, 178, 128), 1000, 1000, 800, 800, 0, 3, _STONE, 25000))
_add(_m("slate", "slate", "slate", "stone", 2700, colors.SLATE,
        1000, 1000, 800, 800, 0, 3, _STONE, 25000))
_add(_m("microcline", "microcline", "microcline", "stone", 2560,
        colors.Color(96, 172, 168), 1000, 1000, 800, 800, 0, 6, _STONE, 25000))
_add(_m("orthoclase", "orthoclase", "orthoclase", "stone", 2560,
        colors.Color(206, 182, 116), 1000, 1000, 800, 800, 0, 6, _STONE, 25000))
_add(_m("chalk", "chalk", "chalk", "stone", 2499, colors.Color(238, 236, 228),
        1000, 1000, 800, 800, 0, 2, _STONE, 25000))
_add(_m("schist", "schist", "schist", "stone", 2670, colors.Color(122, 126, 118),
        1000, 1000, 800, 800, 0, 3, _STONE, 25000))
_add(_m("shale", "shale", "shale", "stone", 2670, colors.Color(96, 100, 104),
        1000, 1000, 800, 800, 0, 3, _STONE, 25000))

_add(_m("milk", "milk", "milk", "liquid", 1030, colors.Color(242, 240, 232),
        1000, 1000, 800, 800, 0, 3, ("ORGANIC",), 10250))

# -- fuel ------------------------------------------------------------------- #
# Neither is a building material: nobody makes a wall out of the coal they
# were going to smelt with. No STONE or WOOD flag, so nothing will try.
_add(_m("coal", "coal", "coal", "fuel", 1350, colors.Color(48, 46, 52),
        1000, 1000, 800, 800, 0, 3, ("FUEL", "FLAMMABLE"), 25000))
_add(_m("charcoal", "charcoal", "charcoal", "fuel", 400,
        colors.Color(72, 66, 62),
        1000, 1000, 800, 800, 0, 3, ("FUEL", "FLAMMABLE"), 25000))

STONE_LAYERS: Dict[str, List[str]] = {
    "sedimentary": ["limestone", "sandstone", "shale", "chalk", "slate"],
    "igneous": ["granite", "gabbro", "basalt", "obsidian"],
    "metamorphic": ["marble", "schist", "slate", "microcline", "orthoclase"],
}

# -- wood ------------------------------------------------------------------- #
for _wid, _wname, _wcol, _wval in (
    ("oak", "oak", colors.Color(146, 110, 62), 4),
    ("willow", "willow", colors.Color(160, 142, 96), 3),
    ("pine", "pine", colors.Color(178, 150, 92), 2),
    ("mahogany", "mahogany", colors.Color(126, 66, 48), 6),
    ("feather_wood", "feather wood", colors.Color(214, 206, 178), 8),
    ("highwood", "highwood", colors.Color(190, 176, 128), 12),
    ("cedar", "cedar", colors.Color(168, 112, 70), 3),
    ("birch", "birch", colors.Color(216, 206, 180), 3),
):
    _add(_m(_wid, _wname, _wname, "wood", 700, _wcol,
            22000, 43000, 22000, 43000, 0, _wval, _WOOD, 10508))

# -- organics --------------------------------------------------------------- #
_add(_m("leather", "leather", "leather", "leather", 800, colors.LEATHER,
        11000, 11000, 11000, 11000, 0, 2,
        ("LEATHER", "ORGANIC", "ARMOR_OK", "WEAPON_OK",
         "FLAMMABLE"), 10250))
_add(_m("bone", "bone", "bone", "bone", 500, colors.BONE,
        200000, 200000, 115000, 130000, 6000, 2,
        ("BONE", "ORGANIC", "WEAPON_OK", "ARMOR_OK"), 12000))
_add(_m("shell", "shell", "shell", "bone", 800, colors.Color(226, 206, 182),
        200000, 200000, 115000, 130000, 5000, 2,
        ("BONE", "ORGANIC", "ARMOR_OK"), 12000))
_add(_m("chitin", "chitin", "chitin", "bone", 600, colors.Color(148, 116, 62),
        150000, 150000, 90000, 100000, 4000, 2,
        ("BONE", "ORGANIC", "ARMOR_OK"), 12000))
_add(_m("ivory", "ivory", "ivory", "bone", 1800, colors.Color(238, 230, 208),
        200000, 200000, 115000, 130000, 5000, 20,
        ("BONE", "ORGANIC", "WEAPON_OK"), 12000))
_add(_m("horn", "horn", "horn", "bone", 1300, colors.Color(198, 176, 128),
        150000, 150000, 90000, 110000, 4000, 3,
        ("BONE", "ORGANIC", "WEAPON_OK"), 12000))
_add(_m("tooth", "tooth", "tooth", "bone", 1800, colors.Color(244, 240, 226),
        200000, 200000, 115000, 130000, 6000, 3,
        ("BONE", "ORGANIC"), 12000))

# -- cloth ------------------------------------------------------------------ #
_add(_m("pig_tail_cloth", "pig tail cloth", "pig tail", "cloth", 700,
        colors.Color(196, 180, 140), 10000, 10000, 10000, 10000, 0, 1,
        ("CLOTH", "ORGANIC", "ARMOR_OK", "FLAMMABLE"), 10000))
_add(_m("silk_cloth", "silk", "silk", "cloth", 700, colors.Color(232, 226, 240),
        10000, 10000, 10000, 10000, 0, 6,
        ("CLOTH", "ORGANIC", "ARMOR_OK", "FLAMMABLE"), 10000))
_add(_m("wool_cloth", "wool", "wool", "cloth", 700, colors.Color(212, 200, 176),
        10000, 10000, 10000, 10000, 0, 2,
        ("CLOTH", "ORGANIC", "ARMOR_OK", "FLAMMABLE"), 10000))
_add(_m("cave_spider_silk", "cave spider silk", "cave spider silk", "cloth", 700,
        colors.Color(206, 210, 216), 12000, 12000, 12000, 12000, 0, 4,
        ("CLOTH", "ORGANIC", "ARMOR_OK", "FLAMMABLE"), 10000))

# -- gems ------------------------------------------------------------------- #
for _gid, _gname, _gcol, _gval in (
    ("diamond", "diamond", colors.Color(230, 244, 250), 60),
    ("ruby", "ruby", colors.Color(206, 40, 60), 40),
    ("sapphire", "sapphire", colors.Color(58, 96, 200), 40),
    ("emerald", "emerald", colors.Color(48, 182, 108), 40),
    ("amethyst", "amethyst", colors.Color(158, 96, 208), 25),
    ("topaz", "topaz", colors.Color(226, 176, 68), 25),
    ("garnet", "garnet", colors.Color(160, 40, 44), 20),
    ("opal", "opal", colors.Color(220, 228, 226), 30),
):
    _add(_m(_gid, _gname, _gname, "gem", 3000, _gcol,
            1000, 1000, 800, 800, 0, _gval, ("GEM",), 25000))

# -- the ground ------------------------------------------------------------- #
# The tiles have named these three since the tile table was written and there
# was nothing behind the names: `mat_data.get("dirt")` fell through to iron,
# and a bag of sand would have been a bag of iron, because `Item` quietly
# swaps an unknown material for iron rather than complain.
_add(_m("dirt", "dirt", "earthen", "soil", 1300, colors.SOIL,
        1000, 1000, 200, 200, 0, 1, ("SOIL",), 12000))
# SAND as well as SOIL: a bag of sand is sand, and "SOIL" is a flag on dirt
# and mud too, so the bag's material was a roll of three and one seed in three
# produced a muddy bag of sand.
_add(_m("sand", "sand", "sand", "soil", 1600, colors.SAND,
        1000, 1000, 200, 200, 0, 1, ("SOIL", "SAND"), 13000))
_add(_m("mud", "mud", "muddy", "soil", 1700, colors.Color(96, 76, 56),
        1000, 1000, 200, 200, 0, 1, ("SOIL",), 12000))

# -- miscellaneous ---------------------------------------------------------- #
_add(_m("glass", "glass", "glass", "glass", 2600, colors.Color(178, 214, 218),
        1000, 1000, 800, 800, 8000, 5, ("GLASS", "WEAPON_OK"), 12000))
_add(_m("ice", "ice", "ice", "stone", 920, colors.ICE,
        1000, 1000, 800, 800, 0, 1, ("STONE",), 10000))
_add(_m("water", "water", "water", "liquid", 1000, colors.WATER_BLUE,
        1000, 1000, 500, 500, 0, 1, ("LIQUID",), 10000))
_add(_m("charcoal", "charcoal", "charcoal", "misc", 800, colors.Color(52, 50, 50),
        1000, 1000, 800, 800, 0, 1, ("FLAMMABLE",), 11000))
_add(_m("ash", "ash", "ash", "misc", 800, colors.ASH,
        1000, 1000, 800, 800, 0, 1, (), 11000))
_add(_m("soap", "soap", "soap", "misc", 900, colors.Color(232, 226, 200),
        1000, 1000, 800, 800, 0, 2, ("ORGANIC",), 10000))

# -- tissues (used by bodies) ----------------------------------------------- #
_add(_m("skin", "skin", "skin", "tissue", 1040, colors.FLESH,
        10000, 10000, 20000, 20000, 0, 1, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("fat", "fat", "fat", "tissue", 900, colors.Color(232, 220, 172),
        10000, 10000, 15000, 15000, 0, 1, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("muscle", "muscle", "muscle", "tissue", 1060, colors.Color(178, 62, 62),
        20000, 20000, 30000, 30000, 0, 1, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("nerve", "nerve", "nervous tissue", "tissue", 1030,
        colors.Color(226, 222, 190), 10000, 10000, 10000, 10000, 0, 1,
        ("ORGANIC",), 10000))
_add(_m("cartilage", "cartilage", "cartilage", "tissue", 1100,
        colors.Color(216, 212, 198), 60000, 60000, 60000, 60000, 0, 1,
        ("ORGANIC", "EDIBLE"), 10000))
_add(_m("blood", "blood", "blood", "tissue", 1060, colors.BLOOD,
        10000, 10000, 10000, 10000, 0, 1, ("ORGANIC", "LIQUID"), 10000))
_add(_m("brain", "brain", "brain", "tissue", 1030, colors.Color(212, 172, 176),
        10000, 10000, 10000, 10000, 0, 1, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("heart", "heart", "heart", "tissue", 1060, colors.Color(168, 44, 48),
        20000, 20000, 25000, 25000, 0, 1, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("lung", "lung", "lung", "tissue", 1050, colors.Color(196, 116, 120),
        15000, 15000, 20000, 20000, 0, 1, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("gut", "guts", "gut", "tissue", 1045, colors.Color(180, 128, 96),
        15000, 15000, 20000, 20000, 0, 1, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("liver", "liver", "liver", "tissue", 1050, colors.Color(140, 62, 56),
        18000, 18000, 22000, 22000, 0, 1, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("eye", "eye", "eye", "tissue", 1030, colors.Color(230, 232, 236),
        10000, 10000, 10000, 10000, 0, 1, ("ORGANIC",), 10000))
_add(_m("nail", "nail", "nail", "tissue", 1300, colors.Color(226, 214, 190),
        100000, 100000, 60000, 70000, 3000, 1, ("ORGANIC",), 12000))
_add(_m("hair", "hair", "hair", "tissue", 1300, colors.Color(90, 70, 50),
        10000, 10000, 10000, 10000, 0, 1, ("ORGANIC", "FLAMMABLE"), 11000))
_add(_m("scale", "scale", "scale", "tissue", 1200, colors.Color(110, 148, 96),
        180000, 180000, 100000, 120000, 3000, 2,
        ("ORGANIC", "ARMOR_OK"), 12000))
_add(_m("feather", "feather", "feather", "tissue", 300,
        colors.Color(206, 202, 194), 10000, 10000, 10000, 10000, 0, 1,
        ("ORGANIC", "FLAMMABLE"), 11000))

# Edible foodstuffs referenced by item definitions.
_add(_m("meat", "meat", "meat", "food", 1040, colors.Color(186, 82, 76),
        10000, 10000, 15000, 15000, 0, 2, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("plant", "plant", "plant", "food", 700, colors.Color(120, 160, 78),
        10000, 10000, 10000, 10000, 0, 1, ("ORGANIC", "EDIBLE", "FLAMMABLE"), 10000))
_add(_m("cheese", "cheese", "cheese", "food", 1000, colors.Color(226, 202, 116),
        10000, 10000, 10000, 10000, 0, 3, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("bread", "bread", "bread", "food", 500, colors.Color(198, 160, 104),
        10000, 10000, 10000, 10000, 0, 2, ("ORGANIC", "EDIBLE"), 10000))
_add(_m("alcohol", "alcohol", "alcohol", "drink", 900, colors.Color(178, 122, 64),
        10000, 10000, 10000, 10000, 0, 2, ("ORGANIC", "LIQUID", "FLAMMABLE"), 10000))


def get(mid: str) -> Material:
    """Look up a material by id, falling back to iron."""
    return MATERIALS.get(mid) or MATERIALS["iron"]


def exists(mid: str) -> bool:
    """True if *mid* names a known material."""
    return mid in MATERIALS


def by_flag(flag: str) -> List[Material]:
    """Every material carrying *flag*."""
    return [m for m in MATERIALS.values() if flag in m.flags]


def by_category(cat: str) -> List[Material]:
    """Every material in *cat*."""
    return [m for m in MATERIALS.values() if m.category == cat]


def weapon_metal_for_tier(tier: int) -> str:
    """A sensible weapon metal for a difficulty/wealth tier 0..5."""
    ladder = ["copper", "bronze", "bronze", "iron", "steel", "steel"]
    return ladder[max(0, min(len(ladder) - 1, tier))]


def material_value(mid: str) -> int:
    """The base value multiplier of a material."""
    return get(mid).value
