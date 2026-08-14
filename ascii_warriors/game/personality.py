"""Personality facets and cultural values.

Facets run 0..100 (50 average) and drive whether a creature stands and fights,
runs, bargains or picks a quarrel. Values run -50..50 and shape what a creature
thinks of what it sees.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..data.descriptors import personality_desc
from ..engine.rng import RNG

FACETS: Tuple[str, ...] = (
    "bravery", "cheer", "anxiety", "anger", "greed", "curiosity", "friendliness",
    "pride", "envy", "stubbornness", "discipline", "vengefulness", "confidence",
    "gregariousness", "ambition", "trust", "humour", "altruism",
    "hate_propensity", "love_propensity", "cruelty", "perseverance",
    "excitement_seeking", "imagination", "swayed_by_emotions", "activity_level",
    "orderliness", "politeness", "assertiveness", "tolerance",
)

VALUES: Tuple[str, ...] = (
    "law", "loyalty", "family", "friendship", "power", "cunning", "eloquence",
    "fairness", "knowledge", "nature", "craftsmanship", "martial_prowess",
    "tradition", "artwork", "commerce", "romance", "peace", "harmony",
    "independence", "sacrifice",
)

VALUE_NAMES: Dict[str, str] = {
    "law": "Law", "loyalty": "Loyalty", "family": "Family",
    "friendship": "Friendship", "power": "Power", "cunning": "Cunning",
    "eloquence": "Eloquence", "fairness": "Fairness", "knowledge": "Knowledge",
    "nature": "Nature", "craftsmanship": "Craftsmanship",
    "martial_prowess": "Martial Prowess", "tradition": "Tradition",
    "artwork": "Artwork", "commerce": "Commerce", "romance": "Romance",
    "peace": "Peace", "harmony": "Harmony", "independence": "Independence",
    "sacrifice": "Sacrifice",
}

FACET_NAMES: Dict[str, str] = {f: f.replace("_", " ").title() for f in FACETS}

#: Racial leanings applied on top of the neutral 50.
RACE_BIAS: Dict[str, Dict[str, int]] = {
    "dwarf": {
        "stubbornness": 22, "bravery": 12, "greed": 10, "perseverance": 15,
        "tolerance": -8, "orderliness": 8,
    },
    "human": {"ambition": 8, "curiosity": 6},
    "elf": {
        "patience": 15, "pride": 15, "tolerance": -10, "cruelty": -12,
        "curiosity": 8, "gregariousness": -8,
    },
    "goblin": {
        "cruelty": 30, "bravery": 18, "altruism": -22, "anger": 15,
        "trust": -15, "vengefulness": 20, "politeness": -18,
    },
    "kobold": {
        "bravery": -22, "greed": 25, "trust": -20, "cunning": 15,
        "anxiety": 18, "assertiveness": -15,
    },
}

RACE_VALUES: Dict[str, Dict[str, int]] = {
    "dwarf": {"craftsmanship": 30, "tradition": 25, "family": 20,
              "martial_prowess": 15, "nature": -15, "commerce": 10},
    "human": {"commerce": 20, "law": 15, "knowledge": 10, "power": 10},
    "elf": {"nature": 40, "harmony": 25, "artwork": 20, "commerce": -25,
            "craftsmanship": -15, "tradition": 20},
    "goblin": {"power": 35, "cunning": 30, "martial_prowess": 25, "peace": -35,
               "fairness": -30, "harmony": -20},
    "kobold": {"cunning": 35, "independence": 25, "commerce": -10, "law": -25},
}


class Personality:
    """One creature's temperament and beliefs."""

    __slots__ = ("facets", "values")

    def __init__(
        self,
        facets: Optional[Mapping[str, int]] = None,
        values: Optional[Mapping[str, int]] = None,
    ) -> None:
        self.facets: Dict[str, int] = {f: 50 for f in FACETS}
        self.values: Dict[str, int] = {v: 0 for v in VALUES}
        if facets:
            for k, v in facets.items():
                if k in self.facets:
                    self.facets[k] = max(0, min(100, int(v)))
        if values:
            for k, v in values.items():
                if k in self.values:
                    self.values[k] = max(-50, min(50, int(v)))

    # -- access ------------------------------------------------------------ #

    def facet(self, name: str) -> int:
        """A facet value, 0..100."""
        return self.facets.get(name, 50)

    def value(self, name: str) -> int:
        """A cultural value, -50..50."""
        return self.values.get(name, 0)

    def set_facet(self, name: str, v: int) -> None:
        """Set a facet, clamped to 0..100."""
        if name in self.facets:
            self.facets[name] = max(0, min(100, int(v)))

    def bravery_factor(self) -> float:
        """How willing this creature is to keep fighting when hurt, 0.2..1.8."""
        brave = self.facet("bravery")
        anxious = self.facet("anxiety")
        raw = 0.2 + 1.6 * (brave / 100.0)
        raw -= 0.35 * (anxious / 100.0)
        return max(0.15, min(1.9, raw))

    def aggression(self) -> float:
        """How readily this creature starts a fight, 0..1."""
        return max(
            0.0,
            min(
                1.0,
                (self.facet("anger") + self.facet("cruelty")
                 + self.facet("assertiveness")) / 300.0,
            ),
        )

    def greed_factor(self) -> float:
        """How hard this creature bargains, 0.5..1.5."""
        return 0.5 + self.facet("greed") / 100.0

    def sociability(self) -> float:
        """How willing this creature is to talk, 0..1."""
        return (self.facet("gregariousness") + self.facet("friendliness")) / 200.0

    def describe(self) -> List[str]:
        """A handful of sentences about this creature's character."""
        traits: List[Tuple[int, str]] = []
        for f in FACETS:
            v = self.facet(f)
            phrase = personality_desc(f, v)
            if phrase:
                traits.append((abs(v - 50), phrase))
        traits.sort(key=lambda t: -t[0])
        out: List[str] = []
        for _, phrase in traits[:6]:
            out.append("They %s." % phrase[3:] if phrase.startswith("is ") else
                       "They %s." % phrase)
        strong_values = sorted(
            ((abs(v), k, v) for k, v in self.values.items() if abs(v) >= 25),
            reverse=True,
        )[:3]
        for _mag, key, v in strong_values:
            name = VALUE_NAMES.get(key, key)
            if v > 0:
                out.append("They hold %s in high regard." % name.lower())
            else:
                out.append("They have no use for %s." % name.lower())
        return out or ["They are unremarkable in temperament."]

    def strongest_values(self, n: int = 3) -> List[Tuple[str, int]]:
        """The *n* most strongly held values."""
        ranked = sorted(self.values.items(), key=lambda kv: -abs(kv[1]))
        return ranked[:n]

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise facets and values."""
        return {"facets": dict(self.facets), "values": dict(self.values)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Personality":
        """Rebuild from :meth:`to_dict`."""
        return cls(d.get("facets") or {}, d.get("values") or {})

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Personality(bravery=%d, anger=%d)" % (
            self.facet("bravery"), self.facet("anger")
        )


def roll_personality(rng: RNG, race: str) -> Personality:
    """Roll a personality around a race's cultural leanings."""
    bias = RACE_BIAS.get(race, {})
    value_bias = RACE_VALUES.get(race, {})
    facets = {
        f: max(0, min(100, int(rng.gauss(50 + bias.get(f, 0), 17))))
        for f in FACETS
    }
    values = {
        v: max(-50, min(50, int(rng.gauss(value_bias.get(v, 0), 16))))
        for v in VALUES
    }
    return Personality(facets, values)


# --------------------------------------------------------------------------- #
# What a personality actually does
# --------------------------------------------------------------------------- #
#
# Thirty facets and twenty values have been rolled for every creature in the
# game since personalities existed, written into every save, and printed on the
# character sheet. Three of them were ever read by anything: `bravery`, `anger`
# and `love_propensity`. The module docstring above has claimed since it was
# written that facets "drive whether a creature stands and fights, runs,
# bargains or picks a quarrel" and that values "shape what a creature thinks of
# what it sees". Neither was true. These are the functions that make it true.

#: How far a personality is allowed to move any of the numbers it touches.
#: A dwarf is not four times as productive as another dwarf because it is
#: keen; it is a fifth better, and that is enough to notice over a season.
SWING = 0.35

#: And how far it may move stress, which is the one that matters most and so
#: gets the widest range: the difference between a stoic and a worrier taking
#: the same news is the whole of what a personality is for.
FEELING_SWING = 0.6


def _unit(value: int) -> float:
    """A 0..100 facet as -1..1 around the average."""
    return max(-1.0, min(1.0, (value - 50) / 50.0))


def _blend(pers, positives, negatives=()) -> float:
    """Average several facets into one -1..1 number."""
    parts = [_unit(pers.facet(f)) for f in positives]
    parts += [-_unit(pers.facet(f)) for f in negatives]
    return sum(parts) / float(len(parts)) if parts else 0.0


def sensitivity(pers) -> float:
    """How hard things land on this creature, as a multiplier on a thought.

    An anxious dwarf swayed by its emotions takes the same funeral harder than
    a confident, tolerant one takes it. This is the single most valuable thing
    a personality can do, because every system in the game that makes anybody
    feel anything goes through one function -- and now through this.
    """
    tilt = _blend(pers, ("anxiety", "swayed_by_emotions"),
                  ("confidence", "tolerance"))
    return max(0.2, 1.0 + tilt * FEELING_SWING)


def resilience(pers) -> float:
    """How fast feelings fade, as a multiplier on the stress drift.

    The other half of sensitivity: somebody may take a thing badly and get
    over it quickly, or shrug it off and never quite let it go.
    """
    tilt = _blend(pers, ("confidence", "cheer"), ("anxiety", "vengefulness"))
    return max(0.35, 1.0 + tilt * SWING)


def diligence(pers) -> float:
    """How hard this creature works, as a multiplier on its work rate."""
    tilt = _blend(pers, ("perseverance", "activity_level", "discipline"))
    return max(0.5, 1.0 + tilt * SWING)


def grudge(pers) -> float:
    """How badly this creature takes being wronged, 0..2."""
    tilt = _blend(pers, ("vengefulness", "hate_propensity"),
                  ("tolerance", "altruism"))
    return max(0.0, 1.0 + tilt)


def values_held(pers, topic: str) -> float:
    """How strongly this creature holds one value, as -1..1.

    Values run -50..50 and have never been read by anything but the character
    sheet. A dwarf who prizes craftsmanship should be lifted by a masterwork
    and a dwarf who does not should walk past it.
    """
    return max(-1.0, min(1.0, pers.value(topic) / 50.0))


def feels_about(pers, topic: str, base: int) -> int:
    """What an event on *topic* is worth to somebody holding that value.

    Returns a stress delta already signed the way `add_thought` wants it, and
    zero when the creature simply does not care -- which is the point. Half
    the fortress should be indifferent to the new statue.
    """
    held = values_held(pers, topic)
    if abs(held) < 0.15:
        return 0
    return int(round(base * held))
