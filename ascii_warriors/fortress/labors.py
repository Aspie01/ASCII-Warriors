"""Labors: which jobs a dwarf is willing to do.

Every dwarf has a set of enabled labors. A job is only ever offered to a dwarf
whose labors include it, which is how you stop your legendary weaponsmith from
spending the winter hauling rocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple


@dataclass(frozen=True)
class Labor:
    """One kind of work a dwarf can be assigned."""

    id: str
    name: str
    category: str
    skill: str
    description: str = ""


LABORS: Dict[str, Labor] = {
    lab.id: lab
    for lab in (
        Labor("mining", "Mining", "Excavation", "mining",
              "Dig out walls, channels, stairs and ramps."),
        Labor("woodcutting", "Woodcutting", "Excavation", "woodcutting",
              "Fell trees for logs."),
        Labor("herbalism", "Plant gathering", "Farming", "herbalism", ""),
        Labor("farming", "Farming", "Farming", "herbalism",
              "Plant and harvest farm plots."),
        Labor("brewing", "Brewing", "Farming", "brewing", ""),
        Labor("cooking", "Cooking", "Farming", "cooking", ""),
        Labor("butchery", "Butchery", "Farming", "butchery", ""),
        Labor("fishing", "Fishing", "Farming", "fishing", ""),
        Labor("carpentry", "Carpentry", "Crafts", "carpentry", ""),
        Labor("masonry", "Masonry", "Crafts", "masonry", ""),
        Labor("crafting", "Stonecrafting", "Crafts", "crafting", ""),
        Labor("smithing", "Metalsmithing", "Crafts", "smithing", ""),
        Labor("weaponsmithing", "Weaponsmithing", "Crafts", "weaponsmithing", ""),
        Labor("armorsmithing", "Armorsmithing", "Crafts", "armorsmithing", ""),
        Labor("leatherwork", "Leatherworking", "Crafts", "leatherwork", ""),
        Labor("mechanics", "Mechanics", "Crafts", "mechanics", ""),
        Labor("building", "Construction", "Hauling", "masonry",
              "Put up walls, floors, workshops and furniture."),
        Labor("hauling", "Hauling", "Hauling", "",
              "Carry goods to stockpiles. Everyone should do this."),
        Labor("medicine", "Medicine", "Health", "wound_dressing", ""),
        Labor("military", "Soldier", "Military", "fighter",
              "Stand and fight when the fortress is attacked."),
    )
}

CATEGORIES: Tuple[str, ...] = (
    "Excavation", "Farming", "Crafts", "Hauling", "Health", "Military",
)

#: Labors every new dwarf starts with.
DEFAULT_LABORS: FrozenSet[str] = frozenset({
    "hauling", "building", "farming", "herbalism", "cooking", "brewing",
    "butchery",
})

#: What a starting dwarf's profession implies, on top of the defaults.
PROFESSION_LABORS: Dict[str, Tuple[str, ...]] = {
    "miner": ("mining",),
    "woodcutter": ("woodcutting", "carpentry"),
    "mason": ("masonry", "crafting"),
    "carpenter": ("carpentry", "woodcutting"),
    "farmer": ("farming", "herbalism", "brewing", "cooking"),
    "smith": ("smithing", "weaponsmithing", "armorsmithing"),
    "craftsdwarf": ("crafting", "leatherwork", "mechanics"),
    "doctor": ("medicine",),
    "soldier": ("military",),
    "hunter": ("butchery", "fishing", "herbalism"),
}

#: Which skill each starting profession is good at, and how good.
PROFESSION_SKILLS: Dict[str, Dict[str, int]] = {
    "miner": {"mining": 5, "fighter": 1},
    "woodcutter": {"woodcutting": 5, "carpentry": 2, "axe": 2},
    "mason": {"masonry": 5, "crafting": 2},
    "carpenter": {"carpentry": 5, "woodcutting": 2},
    "farmer": {"herbalism": 4, "brewing": 4, "cooking": 3},
    "smith": {"smithing": 4, "weaponsmithing": 3, "armorsmithing": 3},
    "craftsdwarf": {"crafting": 5, "leatherwork": 3, "mechanics": 2},
    "doctor": {"diagnose": 4, "wound_dressing": 4, "suturing": 3,
               "bone_setting": 3},
    "soldier": {"fighter": 4, "axe": 4, "shield_use": 3, "armor_use": 3,
                "dodging": 2},
    "hunter": {"bow": 4, "butchery": 4, "tracker": 3, "ambusher": 2},
}

#: The seven who set out. Chosen so the fortress can actually function.
STARTING_SEVEN: Tuple[str, ...] = (
    "miner", "miner", "woodcutter", "mason", "farmer", "craftsdwarf", "soldier",
)


class LaborSet:
    """The labors one dwarf will accept."""

    __slots__ = ("enabled",)

    def __init__(self, enabled=None) -> None:
        self.enabled = set(enabled) if enabled else set(DEFAULT_LABORS)

    def has(self, labor: str) -> bool:
        """True if the dwarf will take this kind of work."""
        return not labor or labor in self.enabled

    def enable(self, labor: str) -> None:
        """Turn a labor on."""
        if labor in LABORS:
            self.enabled.add(labor)

    def disable(self, labor: str) -> None:
        """Turn a labor off."""
        self.enabled.discard(labor)

    def toggle(self, labor: str) -> bool:
        """Flip a labor; returns its new state."""
        if labor in self.enabled:
            self.enabled.discard(labor)
            return False
        self.enable(labor)
        return True

    def by_category(self) -> Dict[str, List[Tuple[Labor, bool]]]:
        """Every labor grouped for the labor screen."""
        out: Dict[str, List[Tuple[Labor, bool]]] = {c: [] for c in CATEGORIES}
        for lab in LABORS.values():
            out.setdefault(lab.category, []).append((lab, lab.id in self.enabled))
        return out

    def to_list(self) -> List[str]:
        """Serialise as a sorted list."""
        return sorted(self.enabled)

    @classmethod
    def from_list(cls, data) -> "LaborSet":
        """Rebuild from :meth:`to_list`."""
        return cls(data or DEFAULT_LABORS)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "LaborSet(%d enabled)" % len(self.enabled)


def labors_for_profession(profession: str) -> LaborSet:
    """The labors a starting dwarf of this profession has enabled."""
    labs = LaborSet()
    for extra in PROFESSION_LABORS.get(profession, ()):
        labs.enable(extra)
    return labs


def profession_title(dwarf) -> str:
    """The title a dwarf earns from its best relevant skill."""
    from ..game.skills import SKILLS, level_name

    best_skill = ""
    best_level = 0
    for labor in dwarf.labors.enabled:
        skill = LABORS[labor].skill
        if not skill:
            continue
        level = dwarf.skills.level(skill)
        if level > best_level:
            best_skill, best_level = skill, level
    if not best_skill or best_level <= 0:
        return "Peasant"
    name = SKILLS[best_skill].name
    if best_level >= 15:
        return "Legendary %s" % name
    if best_level >= 5:
        return "%s %s" % (level_name(best_level), name)
    return name
