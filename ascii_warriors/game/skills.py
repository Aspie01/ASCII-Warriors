"""Use-based skills.

Skills rise by doing, from Dabbling to Legendary+5. Experience needed per level
grows steadily, so a Legendary swordsman represents thousands of swings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..data.descriptors import skill_level_name

MAX_LEVEL = 20
LEVEL_NAMES: Tuple[str, ...] = tuple(skill_level_name(i) for i in range(MAX_LEVEL + 1))


@dataclass(frozen=True)
class SkillDef:
    """One trainable skill."""

    id: str
    name: str
    category: str
    attrs: Tuple[str, ...]
    description: str = ""


SKILLS: Dict[str, SkillDef] = {}


def _s(
    sid: str, name: str, category: str, attrs: Tuple[str, ...], desc: str = ""
) -> SkillDef:
    sd = SkillDef(sid, name, category, attrs, desc)
    SKILLS[sid] = sd
    return sd


_MELEE_ATTRS = ("strength", "agility", "kinesthetic_sense")
_RANGED_ATTRS = ("agility", "focus", "spatial_sense")
_SOCIAL_ATTRS = ("social_awareness", "empathy", "linguistic_ability")
_CRAFT_ATTRS = ("agility", "creativity", "focus")

# -- weapon skills ---------------------------------------------------------- #
_s("sword", "Swordsman", "weapon", _MELEE_ATTRS, "Blades that cut and thrust.")
_s("axe", "Axeman", "weapon", _MELEE_ATTRS, "Heavy edges that hack limbs off.")
_s("mace", "Macedwarf", "weapon", _MELEE_ATTRS, "Blunt weight that breaks bone.")
_s("hammer", "Hammerman", "weapon", _MELEE_ATTRS, "Concentrated crushing force.")
_s("spear", "Spearman", "weapon", _MELEE_ATTRS, "Reach and penetration.")
_s("dagger", "Knife User", "weapon", _MELEE_ATTRS, "Quick, close and quiet.")
_s("pick", "Pikeman", "weapon", _MELEE_ATTRS, "Mining tools turned to war.")
_s("whip", "Lasher", "weapon", ("agility", "kinesthetic_sense"), "")
_s("crossbow", "Crossbowman", "weapon", _RANGED_ATTRS, "")
_s("bow", "Bowman", "weapon", _RANGED_ATTRS, "")
_s("sling", "Slinger", "weapon", _RANGED_ATTRS, "")
_s("misc_weapon", "Misc. Object User", "weapon", _MELEE_ATTRS, "")

# -- combat skills ---------------------------------------------------------- #
_s("fighter", "Fighter", "combat", _MELEE_ATTRS, "General skill at arms.")
_s("wrestling", "Wrestler", "combat", ("strength", "agility"), "")
_s("striker", "Striker", "combat", ("strength", "kinesthetic_sense"), "")
_s("biter", "Biter", "combat", ("strength", "agility"), "")
_s("kicker", "Kicker", "combat", ("strength", "kinesthetic_sense"), "")
_s("dodging", "Dodger", "combat", ("agility", "kinesthetic_sense"),
   "Getting out of the way.")
_s("shield_use", "Shield User", "combat", ("strength", "agility"), "")
_s("armor_use", "Armor User", "combat", ("strength", "endurance"),
   "Wearing armour well: less of its weight, and less of a hammer through it.")
_s("throwing", "Thrower", "combat", _RANGED_ATTRS, "")

# -- outdoor skills --------------------------------------------------------- #
_s("observer", "Observer", "outdoor", ("intuition", "focus"),
   "Noticing what others miss.")
_s("swimming", "Swimmer", "outdoor", ("strength", "endurance"),
   "Keeping your head above water. What you are carrying decides the rest.")
_s("climbing", "Climber", "outdoor", ("strength", "agility"), "")
_s("ambusher", "Ambusher", "outdoor", ("agility", "spatial_sense"), "")
_s("sneak", "Sneak", "outdoor", ("agility", "spatial_sense"), "")
_s("tracker", "Tracker", "outdoor", ("intuition", "spatial_sense"), "")
_s("rider", "Rider", "outdoor", ("agility", "kinesthetic_sense"), "")
_s("herbalism", "Herbalist", "outdoor", ("intuition", "memory"), "")
_s("fishing", "Fisherdwarf", "outdoor", ("patience", "agility"), "")
_s("navigation", "Navigator", "outdoor", ("spatial_sense", "memory"), "")

# -- social skills ---------------------------------------------------------- #
_s("appraisal", "Appraiser", "social", ("analytical_ability", "memory"), "")
_s("negotiation", "Negotiator", "social", _SOCIAL_ATTRS, "")
_s("persuasion", "Persuader", "social", _SOCIAL_ATTRS, "")
_s("intimidation", "Intimidator", "social", ("willpower", "social_awareness"), "")
_s("conversation", "Conversationalist", "social", _SOCIAL_ATTRS, "")
_s("lying", "Liar", "social", ("creativity", "social_awareness"), "")
_s("leadership", "Leader", "social", ("willpower", "social_awareness"), "")
_s("poetry", "Poet", "social", ("creativity", "linguistic_ability"), "")
_s("music", "Musician", "social", ("musicality", "kinesthetic_sense"), "")
_s("dancing", "Dancer", "social", ("kinesthetic_sense", "agility"), "")

# -- medical skills --------------------------------------------------------- #
_s("diagnose", "Diagnostician", "medical", ("analytical_ability", "intuition"), "")
_s("surgery", "Surgeon", "medical", ("agility", "focus"), "")
_s("suturing", "Suturer", "medical", ("agility", "focus"), "")
_s("bone_setting", "Bone Doctor", "medical", ("strength", "focus"), "")
_s("wound_dressing", "Wound Dresser", "medical", ("agility", "empathy"), "")

# -- crafting skills -------------------------------------------------------- #
_s("butchery", "Butcher", "craft", ("strength", "agility"), "")
_s("cooking", "Cook", "craft", ("creativity", "kinesthetic_sense"), "")
_s("brewing", "Brewer", "craft", ("creativity", "patience"), "")
_s("smelting", "Furnace Operator", "craft", _CRAFT_ATTRS,
   "Turning ore and fuel into metal.")
_s("glassmaking", "Glassmaker", "craft", _CRAFT_ATTRS,
   "Melting sand into green glass, and green glass into whatever is wanted.")
_s("smithing", "Metalcrafter", "craft", _CRAFT_ATTRS, "")
_s("weaponsmithing", "Weaponsmith", "craft", _CRAFT_ATTRS, "")
_s("armorsmithing", "Armorsmith", "craft", _CRAFT_ATTRS, "")
_s("mining", "Miner", "craft", ("strength", "endurance"), "")
_s("woodcutting", "Woodcutter", "craft", ("strength", "endurance"), "")
_s("carpentry", "Carpenter", "craft", _CRAFT_ATTRS, "")
_s("masonry", "Mason", "craft", ("strength", "creativity"), "")
_s("mechanics", "Mechanic", "craft", ("analytical_ability", "agility"), "")
_s("crafting", "Craftsdwarf", "craft", _CRAFT_ATTRS, "")
_s("engraving", "Engraver", "craft", ("creativity", "agility"), "")
_s("leatherwork", "Leatherworker", "craft", _CRAFT_ATTRS, "")
_s("bowyer", "Bowyer", "craft", _CRAFT_ATTRS, "")

# -- mental skills ---------------------------------------------------------- #
_s("reading", "Reader", "misc", ("linguistic_ability", "focus"), "")
_s("writing", "Writer", "misc", ("linguistic_ability", "creativity"), "")
_s("knowledge", "Scholar", "misc", ("analytical_ability", "memory"), "")
_s("concentration", "Concentration", "misc", ("focus", "willpower"), "")
_s("discipline", "Discipline", "misc", ("willpower", "focus"),
   "Keeping your head when things go badly.")

SKILL_CATEGORIES: Tuple[str, ...] = (
    "combat", "weapon", "outdoor", "social", "medical", "craft", "misc",
)


def get(sid: str) -> SkillDef:
    """Look up a skill definition, defaulting to Fighter."""
    return SKILLS.get(sid) or SKILLS["fighter"]


def exists(sid: str) -> bool:
    """True if *sid* names a known skill."""
    return sid in SKILLS


def by_category(cat: str) -> List[SkillDef]:
    """Every skill in a category."""
    return [s for s in SKILLS.values() if s.category == cat]


def exp_for_level(level: int) -> int:
    """Cumulative experience needed to reach *level*."""
    if level <= 0:
        return 0
    total = 0
    for i in range(1, min(level, MAX_LEVEL) + 1):
        total += 500 + (i - 1) * 100
    return total


_LEVEL_TABLE: Tuple[int, ...] = tuple(exp_for_level(i) for i in range(MAX_LEVEL + 1))


# --------------------------------------------------------------------------- #
# Aptitude: what a creature was born with, as against what it has learned
# --------------------------------------------------------------------------- #
#
# Every skill in the table has declared the two or three attributes that govern
# it since the table was written, and `SkillDef.attrs` had never been read by
# anything. The consequence was quiet and large: ten of the nineteen attributes
# -- analytical ability, creativity, memory, patience, willpower, empathy,
# linguistic ability, spatial sense, musicality and disease resistance -- were
# rolled for every creature in the world, shown on the character sheet, and
# read by no line of code anywhere. A dwarf with legendary creativity crafted
# exactly like a dull one.
#
# What the other nine attributes had instead was a hand-tuned model in combat,
# written call site by call site: `attack_power` reaches for agility and
# kinesthetic sense itself. That model is deliberately left alone here. It has
# been calibrated against measurements in every milestone from v3.19 to v3.28,
# and running aptitude over the top of it would count agility twice and
# invalidate all of it. Aptitude is for the places that had nothing.

#: How far aptitude can move a skill. An average creature is 1.0, and the range
#: is deliberately much narrower than the attribute spread that feeds it: what
#: it is set to decides how many levels of training talent is worth, and that
#: is the whole balance of the thing. At 0.82 and 1.18 the ratio is 1.44, so
#: talent is worth a little under half your current level -- three levels to a
#: journeyman, never four -- and a dull veteran always out-works a gifted
#: apprentice. A wider band was tried first and a prodigy beat a man four
#: levels above him, which is not what practice is for.
MIN_APTITUDE = 0.82
MAX_APTITUDE = 1.18
#: The most training aptitude can stand in for, as a share of level. Derived
#: from the band above and asserted against it, so the two cannot drift.
TALENT_WORTH = MAX_APTITUDE / MIN_APTITUDE - 1.0


def aptitude(creature, sid: str) -> float:
    """How much a creature's attributes help it at one skill.

    The average of the governing attributes' factors, pulled towards 1.0 so
    that being clever is worth something and not everything.
    """
    sd = SKILLS.get(sid)
    attrs = getattr(creature, "attributes", None)
    if sd is None or attrs is None or not sd.attrs:
        return 1.0
    total = 0.0
    for attr in sd.attrs:
        total += attrs.factor(attr)
    mean = total / float(len(sd.attrs))
    # Half the deviation from average: the attributes decide the edges, the
    # skill decides the middle.
    return max(MIN_APTITUDE, min(MAX_APTITUDE, 1.0 + (mean - 1.0) * 0.5))


def ability(creature, sid: str) -> float:
    """A creature's effective level at a skill: what it learned, times knack.

    Use this for **rolls and magnitudes** -- how good the work came out, how
    much was gathered, how far a price moved, how long the breath lasted.

    Do *not* use it for **knowledge thresholds**: the bands in
    `tracks.read` and `medical.diagnose` decide what a reader can tell you,
    and a dull tracker still knows what a deer print looks like once he has
    been taught. Running aptitude over those quietly takes away the thing the
    player trained to exactly the advertised level to get, which is a lie the
    character sheet cannot see.

    Keep `SkillSet.level` for what is displayed, trained and written to a
    save. Aptitude is not experience and must never be stored as any.
    """
    attrs = getattr(creature, "skills", None)
    if attrs is None:
        return 0.0
    return attrs.level(sid) * aptitude(creature, sid)


def governed_by(attr: str) -> List[str]:
    """Every skill this attribute helps, in table order.

    The link has existed as data since the skill table was written. Now that
    something reads it, it is worth showing: nineteen numbers on a character
    sheet mean nothing until you can see what each of them is for.
    """
    return [sd.id for sd in SKILLS.values() if attr in sd.attrs]


def aptitude_word(value: float) -> str:
    """A word for how much aptitude is helping, "" when it is not much."""
    for edge, word in APTITUDE_WORDS:
        if value <= edge:
            return word
    return APTITUDE_WORDS[-1][1]


#: What to call an aptitude. Five bands, and nothing said in the middle one,
#: because most creatures sit there and a label on it would be noise.
APTITUDE_WORDS: Tuple[Tuple[float, str], ...] = (
    (0.90, "a struggle"),
    (0.96, "uphill"),
    (1.04, ""),
    (1.12, "comes easily"),
    (99.0, "a natural gift"),
)


def level_from_exp(exp: int) -> int:
    """The highest level fully paid for by *exp*."""
    level = 0
    for i in range(MAX_LEVEL, -1, -1):
        if exp >= _LEVEL_TABLE[i]:
            level = i
            break
    return level


class SkillSet:
    """A creature's skills and the experience behind them."""

    __slots__ = ("_exp",)

    def __init__(self, levels: Optional[Mapping[str, int]] = None) -> None:
        self._exp: Dict[str, int] = {}
        if levels:
            for sid, lv in levels.items():
                if sid in SKILLS:
                    self._exp[sid] = exp_for_level(int(lv))

    # -- access ------------------------------------------------------------ #

    def level(self, sid: str) -> int:
        """Current level of a skill, 0 for untrained."""
        return level_from_exp(self._exp.get(sid, 0))

    def exp(self, sid: str) -> int:
        """Raw experience in a skill."""
        return self._exp.get(sid, 0)

    def progress(self, sid: str) -> float:
        """Fraction of the way to the next level, 0..1."""
        lv = self.level(sid)
        if lv >= MAX_LEVEL:
            return 1.0
        here = _LEVEL_TABLE[lv]
        nxt = _LEVEL_TABLE[lv + 1]
        if nxt <= here:
            return 1.0
        return max(0.0, min(1.0, (self._exp.get(sid, 0) - here) / float(nxt - here)))

    def set_level(self, sid: str, level: int) -> None:
        """Set a skill directly to *level*."""
        if sid in SKILLS:
            self._exp[sid] = exp_for_level(level)

    def add_exp(self, sid: str, amount: int) -> Optional[int]:
        """Add experience; returns the new level if the skill went up."""
        if sid not in SKILLS or amount <= 0:
            return None
        before = self.level(sid)
        self._exp[sid] = self._exp.get(sid, 0) + int(amount)
        after = self.level(sid)
        return after if after > before else None

    def rust(self, sid: str, amount: int = 1) -> None:
        """Lose a little experience through disuse."""
        if sid in self._exp:
            self._exp[sid] = max(0, self._exp[sid] - max(0, amount))

    def known(self) -> List[Tuple[str, int]]:
        """Every trained skill as ``(id, level)``, best first."""
        out = [(sid, self.level(sid)) for sid, e in self._exp.items() if e > 0]
        out.sort(key=lambda kv: (-kv[1], SKILLS[kv[0]].name))
        return out

    def best(self, sids: Tuple[str, ...]) -> str:
        """Whichever of *sids* is trained highest."""
        if not sids:
            return "fighter"
        return max(sids, key=self.level)

    def total_levels(self) -> int:
        """Sum of every skill level, a rough measure of experience."""
        return sum(self.level(s) for s in self._exp)

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise raw experience per skill."""
        return {"exp": dict(self._exp)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "SkillSet":
        """Rebuild from :meth:`to_dict`."""
        s = cls()
        s._exp = {k: int(v) for k, v in (d.get("exp") or {}).items() if k in SKILLS}
        return s

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "SkillSet(%d skills)" % len(self._exp)


def skill_bonus(level: int) -> float:
    """The multiplier a skill level contributes to rolls.

    Level 0 gives 1.0; Legendary+5 roughly triples effectiveness.
    """
    return 1.0 + level * 0.10


def level_name(level: int) -> str:
    """Title for a skill level."""
    return skill_level_name(level)
