"""Creature attributes.

Nineteen attributes on a 0..5000 scale where 1000 is average. Wounds, fatigue
and hunger apply temporary penalties on top of the base value.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from ..data.descriptors import attribute_desc, attribute_rank
from ..engine.rng import RNG

PHYSICAL: Tuple[str, ...] = (
    "strength", "agility", "toughness", "endurance", "recuperation",
    "disease_resistance",
)
MENTAL: Tuple[str, ...] = (
    "analytical_ability", "focus", "willpower", "creativity", "intuition",
    "patience", "memory", "linguistic_ability", "spatial_sense", "musicality",
    "kinesthetic_sense", "empathy", "social_awareness",
)
ALL_ATTRS: Tuple[str, ...] = PHYSICAL + MENTAL

ATTR_NAMES: Dict[str, str] = {
    "strength": "Strength",
    "agility": "Agility",
    "toughness": "Toughness",
    "endurance": "Endurance",
    "recuperation": "Recuperation",
    "disease_resistance": "Disease Resistance",
    "analytical_ability": "Analytical Ability",
    "focus": "Focus",
    "willpower": "Willpower",
    "creativity": "Creativity",
    "intuition": "Intuition",
    "patience": "Patience",
    "memory": "Memory",
    "linguistic_ability": "Linguistic Ability",
    "spatial_sense": "Spatial Sense",
    "musicality": "Musicality",
    "kinesthetic_sense": "Kinesthetic Sense",
    "empathy": "Empathy",
    "social_awareness": "Social Awareness",
}

#: The average value; :meth:`Attributes.factor` returns 1.0 here.
AVERAGE = 1000
MIN_VALUE = 0
MAX_VALUE = 5000


class Attributes:
    """A creature's nineteen attributes, with temporary modifiers."""

    __slots__ = ("_base", "_mods")

    def __init__(self, values: Optional[Mapping[str, int]] = None) -> None:
        self._base: Dict[str, int] = {a: AVERAGE for a in ALL_ATTRS}
        if values:
            for k, v in values.items():
                if k in self._base:
                    self._base[k] = int(v)
        self._mods: Dict[str, int] = {}

    # -- access ------------------------------------------------------------ #

    def base(self, attr: str) -> int:
        """The unmodified value."""
        return self._base.get(attr, AVERAGE)

    def get(self, attr: str) -> int:
        """The current value after temporary modifiers, clamped to the scale."""
        v = self._base.get(attr, AVERAGE) + self._mods.get(attr, 0)
        return max(MIN_VALUE, min(MAX_VALUE, v))

    def set(self, attr: str, value: int) -> None:
        """Set the base value."""
        if attr in self._base:
            self._base[attr] = max(MIN_VALUE, min(MAX_VALUE, int(value)))

    def modify(self, attr: str, delta: int) -> None:
        """Permanently adjust the base value (training, injury, age)."""
        if attr in self._base:
            self.set(attr, self._base[attr] + int(delta))

    def set_modifier(self, attr: str, delta: int) -> None:
        """Set a temporary modifier, replacing any previous one."""
        if delta:
            self._mods[attr] = int(delta)
        else:
            self._mods.pop(attr, None)

    def clear_modifiers(self) -> None:
        """Remove every temporary modifier."""
        self._mods.clear()

    def factor(self, attr: str) -> float:
        """The multiplier combat and skills use, roughly 0.4 to 2.2."""
        v = self.get(attr)
        if v >= AVERAGE:
            return 1.0 + (v - AVERAGE) / 3200.0
        return max(0.35, 0.35 + 0.65 * (v / float(AVERAGE)))

    def describe(self, attr: str) -> str:
        """Descriptive phrase for an attribute, ``""`` when average."""
        return attribute_desc(attr, self.get(attr))

    def rank(self, attr: str) -> int:
        """Coarse 0..7 rank (0 highest)."""
        return attribute_rank(self.get(attr))

    def physical_average(self) -> int:
        """Mean of the six physical attributes."""
        return sum(self.get(a) for a in PHYSICAL) // len(PHYSICAL)

    def mental_average(self) -> int:
        """Mean of the thirteen mental attributes."""
        return sum(self.get(a) for a in MENTAL) // len(MENTAL)

    def notable(self) -> Dict[str, str]:
        """Every attribute with a non-empty description, in display order."""
        out: Dict[str, str] = {}
        for a in ALL_ATTRS:
            d = self.describe(a)
            if d:
                out[a] = d
        return out

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise base values and modifiers."""
        return {"base": dict(self._base), "mods": dict(self._mods)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Attributes":
        """Rebuild from :meth:`to_dict`."""
        a = cls(d.get("base") or {})
        a._mods = {k: int(v) for k, v in (d.get("mods") or {}).items()}
        return a

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Attributes(str=%d, agi=%d, tou=%d)" % (
            self.get("strength"), self.get("agility"), self.get("toughness")
        )


def roll_attributes(rng: RNG, base: Mapping[str, int]) -> Attributes:
    """Roll a creature's attributes around the species means.

    Dwarf Fortress rolls each attribute from a bell curve; a handful of values
    land far from the mean, which is what makes individuals memorable.
    """
    values: Dict[str, int] = {}
    for attr in ALL_ATTRS:
        mean = int(base.get(attr, AVERAGE))
        spread = max(120, mean * 0.28)
        v = rng.gauss(mean, spread)
        # Occasionally a creature is genuinely exceptional at something.
        if rng.one_in(24):
            v += rng.gauss(0, spread * 2.2)
        values[attr] = max(MIN_VALUE, min(MAX_VALUE, int(v)))
    return Attributes(values)


def point_buy_defaults() -> Dict[str, int]:
    """Starting attribute values for a freshly created player character."""
    return {a: AVERAGE for a in ALL_ATTRS}
