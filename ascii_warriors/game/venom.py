"""Venom: what a sting does after it has stopped hurting.

`POISON_BITE` has been on the giant cave spider, the giant desert scorpion and
the alligator since the creature data was written, and `WEBBER` has been on
the two of them that spin. Nothing has ever read either flag. A giant cave
spider was a large animal that bit you, which is not what a giant cave spider
is for.

The combat model here is already about tissue: an attack drives momentum
through skin, fat, muscle and bone and leaves a wound that bleeds and hurts.
Venom is the thing that model has no vocabulary for, because it does no damage
at all at the moment it lands. It arrives with the bite, waits, and then
spends the next several hundred ticks doing something the wound did not.

**A syndrome is a clock, not a number.** Each one has an onset, a duration and
a per-tick effect, and stacking a second dose extends the clock rather than
doubling the effect -- otherwise a swarm of anything venomous is an instant
death rather than a fight you should have run from. Toughness and the
`discipline` to keep moving through it both shorten it, which is the first
thing in the game that has ever read `discipline`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: The kinds of venom in the world, and what each does per tick while it runs.
#:
#: `pain` and `bleed` feed the existing body model; `slow` costs speed;
#: `nausea` costs nothing directly and makes you vomit, which costs food. They
#: are deliberately small numbers: venom is a long emergency, not a big hit.
KINDS: Dict[str, Dict[str, Any]] = {
    "spider": {
        "name": "spider venom",
        "onset": 60, "duration": 3600,
        "pain": 3, "slow": 18, "nausea": 0.0, "bleed": 0,
        "arrives": "Your limbs are growing heavy.",
        "ends": "The heaviness passes.",
    },
    "scorpion": {
        "name": "scorpion venom",
        "onset": 30, "duration": 2400,
        "pain": 6, "slow": 6, "nausea": 0.4, "bleed": 0,
        "arrives": "The sting is burning far worse than it should.",
        "ends": "The burning fades.",
    },
    "rot": {
        "name": "septic bite",
        "onset": 400, "duration": 7200,
        "pain": 2, "slow": 2, "nausea": 0.2, "bleed": 1,
        "arrives": "The bite has gone bad.",
        "ends": "The wound is clean again.",
    },
}

#: Which venom each kind of creature carries. Anything with POISON_BITE and no
#: entry here carries the septic bite, which is what a dirty mouth amounts to.
BY_CREATURE: Dict[str, str] = {
    "giant_cave_spider": "spider",
    "giant_desert_scorpion": "scorpion",
    "alligator": "rot",
}

#: How much of the duration a point of toughness or discipline takes off.
RESIST_PER_POINT = 0.03

#: The most resistance is ever worth. Somebody very tough still has a bad day.
MAX_RESIST = 0.55

#: A second dose extends rather than stacks, and only up to this multiple of
#: the base duration. A nest of spiders should be terrifying and finite.
MAX_EXTEND = 2.5

#: How much a treated dose is cut by, and the skill that does it.
TREAT_CUT = 0.45
TREAT_SKILL = "diagnose"


class Dose:
    """One working of venom in one creature."""

    __slots__ = ("kind", "left", "onset", "total", "treated")

    def __init__(self, kind: str = "rot", left: int = 0,
                 onset: int = 0) -> None:
        self.kind = kind
        #: Ticks of effect still to run.
        self.left = left
        #: Ticks before it starts.
        self.onset = onset
        #: What it started at, so a second dose knows the ceiling.
        self.total = left
        self.treated = False

    @property
    def defn(self) -> Dict[str, Any]:
        """The venom's own entry."""
        return KINDS.get(self.kind, KINDS["rot"])

    @property
    def name(self) -> str:
        """What it is called."""
        return str(self.defn["name"])

    @property
    def active(self) -> bool:
        """Whether it is currently doing anything."""
        return self.onset <= 0 and self.left > 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the dose."""
        return {"k": self.kind, "l": self.left, "o": self.onset,
                "t": self.total, "x": self.treated}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Dose":
        """Rebuild from :meth:`to_dict`."""
        dose = cls(str(d.get("k", "rot")), int(d.get("l", 0)),
                   int(d.get("o", 0)))
        dose.total = int(d.get("t", dose.left))
        dose.treated = bool(d.get("x", False))
        return dose

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Dose(%s, %d left)" % (self.kind, self.left)


# --------------------------------------------------------------------------- #
# Getting it
# --------------------------------------------------------------------------- #


def doses(creature) -> List[Dose]:
    """Every venom working in a creature, creating the list."""
    got = getattr(creature, "venom", None)
    if got is None:
        got = creature.venom = []
    return got


def carries(creature) -> Optional[str]:
    """Which venom this creature's bite carries, if any."""
    defn = getattr(creature, "defn", None)
    if defn is None or not defn.has("POISON_BITE"):
        return None
    return BY_CREATURE.get(getattr(creature, "def_id", ""), "rot")


def resistance(victim) -> float:
    """How much of a dose this creature shrugs off.

    Toughness is the obvious half. `discipline` is the other, and it is the
    first line of code in the game to read that skill: what a syndrome mostly
    does is make you stop, and the ones who do not stop take less of it.
    """
    tough = 0.0
    attrs = getattr(victim, "attributes", None)
    if attrs is not None:
        tough = max(0.0, (attrs.factor("toughness") - 1.0)) * 10.0
    grit = max(0, victim.skills.level("discipline"))
    return min(MAX_RESIST, (tough + grit) * RESIST_PER_POINT)


def inject(victim, kind: str, rng=None) -> Optional[Dose]:
    """Put a dose of venom into somebody. Returns it, or None if it did not take.

    A second dose of the same venom extends the clock instead of adding a
    second clock, bounded by `MAX_EXTEND`: a nest of spiders should be
    terrifying and survivable rather than arithmetic.
    """
    defn = KINDS.get(kind)
    if defn is None:
        return None
    body = getattr(victim, "body", None)
    if body is not None and getattr(body, "bloodless", False):
        return None                     # nothing to carry it
    if getattr(victim, "defn", None) is not None \
            and victim.defn.has("POISON_BITE"):
        return None                     # it makes its own

    duration = int(defn["duration"] * (1.0 - resistance(victim)))
    if duration <= 0:
        return None
    have = [d for d in doses(victim) if d.kind == kind]
    if have:
        dose = have[0]
        ceiling = int(dose.total * MAX_EXTEND)
        dose.left = min(ceiling, dose.left + duration // 2)
        return dose
    dose = Dose(kind, duration, int(defn["onset"]))
    doses(victim).append(dose)
    return dose


def on_bite(attacker, defender, rng=None) -> Optional[Dose]:
    """A bite has landed. Inject whatever the biter carries.

    Called from the same place in `melee_attack` that v3.5's curse uses, and
    for the same reason: what matters is the attack that broke the skin, not
    what else the creature owns.
    """
    kind = carries(attacker)
    if kind is None:
        return None
    return inject(defender, kind, rng)


# --------------------------------------------------------------------------- #
# Living with it
# --------------------------------------------------------------------------- #


def tick(creature, ticks: int, rng=None) -> List[str]:
    """Advance every dose and apply it. Returns lines to tell the victim."""
    active = doses(creature)
    if not active or ticks <= 0:
        return []
    msgs: List[str] = []
    for dose in list(active):
        defn = dose.defn
        if dose.onset > 0:
            dose.onset -= ticks
            if dose.onset <= 0:
                msgs.append(str(defn["arrives"]))
            continue
        dose.left -= ticks
        if dose.left <= 0:
            active.remove(dose)
            msgs.append(str(defn["ends"]))
            continue
        _apply(creature, dose, defn, ticks, rng, msgs)
    return msgs


def _apply(creature, dose: Dose, defn, ticks: int, rng, msgs: List[str]) -> None:
    """What one dose does over one stretch of time."""
    scale = 0.5 if dose.treated else 1.0
    body = getattr(creature, "body", None)
    if body is not None:
        pain = int(defn["pain"] * scale * max(1, ticks // 50))
        if pain:
            body.pain = min(1000, getattr(body, "pain", 0) + pain)
    needs = getattr(creature, "needs", None)
    if needs is not None and defn["nausea"] and rng is not None:
        if rng.chance(defn["nausea"] * ticks / 600.0):
            needs.hunger += 400
            msgs.append("You retch." if creature.is_player else "")
    if defn["bleed"] and body is not None:
        wounds = [w for w in getattr(body, "wounds", ()) if w.bleeding]
        if wounds and rng is not None and rng.chance(ticks / 600.0):
            wounds[0].bleeding += int(defn["bleed"] * scale)


def slow_factor(creature) -> float:
    """What the venom in somebody is doing to their speed.

    Read by `effective_speed`, so a poisoned adventurer is slower in the only
    way the scheduler understands: everything else gets more turns than they
    do.
    """
    worst = 0
    for dose in (getattr(creature, "venom", None) or ()):
        if not dose.active:
            continue
        cut = int(dose.defn["slow"] * (0.5 if dose.treated else 1.0))
        worst = max(worst, cut)
    return max(0.35, 1.0 - worst / 100.0)


def afflicted(creature) -> List[str]:
    """Names of whatever is currently working in somebody, for the panels."""
    return [d.name for d in (getattr(creature, "venom", None) or ())
            if d.active]


def treat(healer, patient) -> Tuple[bool, str]:
    """Draw and bind a venomous bite. Halves what is left of every dose.

    It is `diagnose` rather than a new skill because knowing what bit somebody
    is the whole of the treatment; there is no antidote in this world, only
    somebody who has seen it before and knows to cut and bind.
    """
    active = [d for d in doses(patient) if not d.treated]
    if not active:
        return (False, "There is no venom to draw.")
    level = max(0, healer.skills.level(TREAT_SKILL))
    if level < 2:
        return (False, "You would not know where to start.")
    for dose in active:
        dose.treated = True
        dose.left = int(dose.left * (1.0 - TREAT_CUT))
    healer.add_exp(TREAT_SKILL, 40)
    healer.add_exp("wound_dressing", 25)
    return (True, "You draw what you can of the %s." % active[0].name)


def to_list(creature) -> List[Any]:
    """Serialise a creature's doses."""
    return [d.to_dict() for d in (getattr(creature, "venom", None) or ())]


def from_list(creature, raw: Sequence[Any]) -> None:
    """Rebuild them from :func:`to_list`."""
    creature.venom = [Dose.from_dict(d) for d in (raw or ())]
