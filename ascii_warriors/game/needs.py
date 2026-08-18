"""Hunger, thirst, sleep, fatigue and stress."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from ..data.calendar import TICKS_PER_DAY
from ..data.descriptors import stress_desc
from .item import Item

#: Values are "ticks since satisfied"; the thresholds below turn them into words.
HUNGER_HUNGRY = int(TICKS_PER_DAY * 0.75)
HUNGER_STARVING = int(TICKS_PER_DAY * 2.0)
HUNGER_DEATH = int(TICKS_PER_DAY * 5.0)

THIRST_THIRSTY = int(TICKS_PER_DAY * 0.5)
THIRST_DEHYDRATED = int(TICKS_PER_DAY * 1.25)
THIRST_DEATH = int(TICKS_PER_DAY * 3.0)

SLEEP_DROWSY = int(TICKS_PER_DAY * 0.9)
SLEEP_EXHAUSTED = int(TICKS_PER_DAY * 1.4)
SLEEP_COLLAPSE = int(TICKS_PER_DAY * 2.0)

FATIGUE_TIRED = 600
FATIGUE_EXHAUSTED = 1200
FATIGUE_MAX = 2000

#: Ticks of hunger one point of nutrition holds off. A plump helmet (450) is
#: about three quarters of a day; a fine meal is nearly three days.
NUTRITION_SCALE = 24
#: The same for thirst. A mug of ale (800) is very nearly a full day.
HYDRATION_SCALE = 16

#: Ticks for one point of stress to fade back towards indifference.
STRESS_DECAY = 900

#: Ticks of sleep that take one point of stress off.
SLEEP_SETTLES = 400

#: The want of a quiet place. Slower than any of the bodily needs -- a week
#: without it is a grumble, not a crisis -- and unlike them it kills nobody:
#: a dwarf who never prays is unhappy, not dead.
PRAYER_WANTED = int(TICKS_PER_DAY * 7.0)
PRAYER_NEGLECTED = int(TICKS_PER_DAY * 16.0)


class Needs:
    """A creature's bodily and mental needs."""

    __slots__ = ("hunger", "thirst", "drowsy", "fatigue", "stress", "thoughts",
                 "prayer", "owner", "drift", "rested")

    def __init__(self) -> None:
        #: Whose needs these are, set by `Creature.__init__`. Kept so that
        #: `add_thought` can ask the personality how hard to land -- there are
        #: fifty-six places in the game that make somebody feel something and
        #: exactly one of them is worth teaching about personalities.
        self.owner = None
        self.hunger = 0
        self.thirst = 0
        self.drowsy = 0
        self.fatigue = 0
        self.stress = 0
        #: Ticks since this creature last had a quiet moment somewhere it
        #: counted. A temple is what a temple is for.
        self.prayer = 0
        #: Recent thoughts as ``(text, stress delta)``.
        self.thoughts: List[Tuple[str, int]] = []
        #: Ticks of fading banked but not yet worth a whole point of
        #: stress. Without somewhere to keep them a fortress step is far
        #: too short to fade any stress at all, and rounding up instead --
        #: which is what this used to do -- fades a whole point every step,
        #: ninety times faster than `STRESS_DECAY` asks for.
        self.drift = 0.0
        #: The same, for the stress a good sleep takes off. A
        #: fortress sleeps in forty-tick instalments and this
        #: used to be `ticks // 400`, so sleeping has never once
        #: settled anybody: forty over four hundred is zero.
        self.rested = 0

    # -- upkeep ------------------------------------------------------------ #

    def tick(self, ticks: int, creature, game) -> List[str]:
        """Advance the needs clock and return any warnings to log."""
        msgs: List[str] = []
        if ticks <= 0:
            return msgs
        defn = creature.defn

        if not defn.has("NO_EAT"):
            before = self.hunger
            self.hunger += ticks
            msgs.extend(
                _threshold_messages(
                    before, self.hunger,
                    ((HUNGER_HUNGRY, "You are hungry."),
                     (HUNGER_STARVING, "You are starving!")),
                )
            )
        if not defn.has("NO_DRINK"):
            before = self.thirst
            self.thirst += ticks
            msgs.extend(
                _threshold_messages(
                    before, self.thirst,
                    ((THIRST_THIRSTY, "You are thirsty."),
                     (THIRST_DEHYDRATED, "You are dying of thirst!")),
                )
            )
        if not defn.has("NO_SLEEP"):
            if creature.body.unconscious > 0:
                # Being out cold is still rest. Without this a creature that
                # collapses from exhaustion never sleeps it off, wakes up
                # exhausted, collapses again, and dies in its coma.
                self.drowsy = max(0, self.drowsy - ticks * 3)
            else:
                before = self.drowsy
                self.drowsy += ticks
                msgs.extend(
                    _threshold_messages(
                        before, self.drowsy,
                        ((SLEEP_DROWSY, "You are drowsy."),
                         (SLEEP_EXHAUSTED,
                          "You are exhausted and can barely stand.")),
                    )
                )

        self.fatigue = max(0, self.fatigue - max(1, ticks // 4))

        # A want rather than a need: nothing below ever kills for it. What it
        # does is make a fortress with nowhere quiet in it a worse place to
        # live, which is what an altar was always supposed to be for.
        self.prayer += ticks
        msgs.extend(
            _threshold_messages(
                self.prayer - ticks, self.prayer,
                ((PRAYER_WANTED, "You could do with a quiet moment."),),
            )
        )

        # Feelings fade. Without this a creature that had one good week stays
        # ecstatic for ever and nothing you do to it afterwards matters.
        if self.stress:
            # Banked as ticks, not as fractions of a point: ninety lots of
            # one ninetieth add up to 0.9999999999999999, and nine hundred
            # ticks of fading has to shed exactly one point.
            self.drift += ticks * self.recovery()
            faded, self.drift = divmod(self.drift, STRESS_DECAY)
            if faded:
                if abs(self.stress) <= faded:
                    self.stress = 0
                else:
                    self.stress -= int(math.copysign(faded, self.stress))
        else:
            self.drift = 0.0

        # Starvation and dehydration eventually kill.
        if self.hunger > HUNGER_DEATH:
            creature.body.dead = True
            creature.body.death_cause = "starved to death"
        elif self.thirst > THIRST_DEATH:
            creature.body.dead = True
            creature.body.death_cause = "died of thirst"
        elif self.drowsy > SLEEP_COLLAPSE and creature.body.unconscious <= 0:
            creature.body.unconscious = 3000
            msgs.append("You collapse from exhaustion.")

        self._apply_penalties(creature)
        return msgs

    def _apply_penalties(self, creature) -> None:
        """Translate need levels into temporary attribute modifiers."""
        attrs = creature.attributes
        penalty = 0
        if self.hunger > HUNGER_STARVING:
            penalty += 300
        elif self.hunger > HUNGER_HUNGRY:
            penalty += 80
        if self.thirst > THIRST_DEHYDRATED:
            penalty += 350
        elif self.thirst > THIRST_THIRSTY:
            penalty += 80
        if self.drowsy > SLEEP_EXHAUSTED:
            penalty += 250
        elif self.drowsy > SLEEP_DROWSY:
            penalty += 60
        if self.fatigue > FATIGUE_EXHAUSTED:
            penalty += 200
        elif self.fatigue > FATIGUE_TIRED:
            penalty += 60
        for attr in ("strength", "agility", "endurance", "focus"):
            attrs.set_modifier(attr, -penalty)

    # -- satisfying needs -------------------------------------------------- #

    def eat(self, item: Item) -> str:
        """Consume food; returns the message to show.

        The multipliers are set so one unit of a staple — a plump helmet, a
        mug of ale — is most of a day. Anything tighter and a creature spends
        its whole life queueing at the food pile.
        """
        nutrition = item.defn.nutrition or 400
        self.hunger = max(0, self.hunger - nutrition * NUTRITION_SCALE)
        if item.defn.hydration:
            self.thirst = max(
                0, self.thirst - item.defn.hydration * HYDRATION_SCALE // 2)
        if item.quality >= 3:
            self.add_thought("ate a fine meal", -6)
        return "You eat %s." % item.name(article=True)

    def drink(self, item: Item) -> str:
        """Consume a drink; returns the message to show."""
        hydration = item.defn.hydration or 600
        self.thirst = max(0, self.thirst - hydration * HYDRATION_SCALE)
        if item.defn.nutrition:
            self.hunger = max(
                0, self.hunger - item.defn.nutrition * NUTRITION_SCALE * 2 // 3)
        if item.material == "alcohol":
            self.add_thought("had a drink", -4)
            self.stress = max(-100, self.stress - 2)
        return "You drink %s." % item.name(article=True)

    def sleep(self, ticks: int) -> None:
        """Rest for a while.

        Carried in fractions like the fade is, and for the same reason: a
        fortress sleeps forty ticks at a time and integer division by
        `SLEEP_SETTLES` threw every one of them away. Banked as whole
        ticks rather than as a fraction of a point, because ten lots of
        nought-point-one add up to 0.9999999999999999 and a dwarf that sleeps
        exactly four hundred ticks should settle by exactly one.
        """
        self.drowsy = max(0, self.drowsy - ticks * 3)
        self.fatigue = 0
        self.rested += ticks
        settled, self.rested = divmod(self.rested, SLEEP_SETTLES)
        if settled:
            self.stress = max(-100, self.stress - int(settled))

    def exert(self, amount: int = 10) -> None:
        """Spend energy on a strenuous action."""
        self.fatigue = min(FATIGUE_MAX, self.fatigue + amount)

    def add_thought(self, text: str, value: int, *,
                    scaled: bool = True) -> None:
        """Record a thought and shift stress by *value* (negative is good).

        Scaled by whose thought it is. Thirty personality facets have been
        rolled for every creature since personalities existed and three of
        them were ever read; an anxious dwarf and a stoic one took the same
        funeral exactly as hard, which made the whole system decoration.

        `scaled=False` is for callers that have already applied the
        personality themselves and clamped the result -- scaling a number that
        has been clamped moves it back outside the clamp, which is exactly
        what happened the first time.
        """
        if scaled:
            value = int(round(value * self.feeling()))
        self.thoughts.append((text, value))
        if len(self.thoughts) > 40:
            del self.thoughts[:-40]
        self.stress = max(-150, min(200, self.stress + value))

    def feeling(self) -> float:
        """How hard things land on the owner of these needs."""
        owner = self.owner
        pers = getattr(owner, "personality", None) if owner is not None else None
        if pers is None:
            return 1.0
        from . import personality as personality_mod

        return personality_mod.sensitivity(pers)

    def recovery(self) -> float:
        """How fast the owner's feelings fade."""
        owner = self.owner
        pers = getattr(owner, "personality", None) if owner is not None else None
        if pers is None:
            return 1.0
        from . import personality as personality_mod

        return personality_mod.resilience(pers)

    # -- presentation ------------------------------------------------------ #

    def status(self) -> List[Tuple[str, float, str]]:
        """``(label, fill 0..1, severity)`` rows for the sidebar gauges."""
        return [
            ("Food", 1.0 - min(1.0, self.hunger / float(HUNGER_STARVING)),
             _severity(self.hunger, HUNGER_HUNGRY, HUNGER_STARVING)),
            ("Water", 1.0 - min(1.0, self.thirst / float(THIRST_DEHYDRATED)),
             _severity(self.thirst, THIRST_THIRSTY, THIRST_DEHYDRATED)),
            ("Rest", 1.0 - min(1.0, self.drowsy / float(SLEEP_EXHAUSTED)),
             _severity(self.drowsy, SLEEP_DROWSY, SLEEP_EXHAUSTED)),
            ("Energy", 1.0 - min(1.0, self.fatigue / float(FATIGUE_MAX)),
             _severity(self.fatigue, FATIGUE_TIRED, FATIGUE_EXHAUSTED)),
        ]

    def hunger_word(self) -> str:
        """A word for the current hunger level."""
        if self.hunger > HUNGER_STARVING:
            return "starving"
        if self.hunger > HUNGER_HUNGRY:
            return "hungry"
        if self.hunger < HUNGER_HUNGRY // 3:
            return "well fed"
        return "peckish"

    def thirst_word(self) -> str:
        """A word for the current thirst level."""
        if self.thirst > THIRST_DEHYDRATED:
            return "dehydrated"
        if self.thirst > THIRST_THIRSTY:
            return "thirsty"
        return "quenched"

    def sleep_word(self) -> str:
        """A word for the current tiredness level."""
        if self.drowsy > SLEEP_EXHAUSTED:
            return "exhausted"
        if self.drowsy > SLEEP_DROWSY:
            return "drowsy"
        return "rested"

    def mood(self) -> str:
        """Wording for the current stress level."""
        return stress_desc(self.stress)

    def recent_thoughts(self, n: int = 6) -> List[str]:
        """The last few thoughts, newest first."""
        return [t for t, _v in reversed(self.thoughts[-n:])]

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the needs."""
        return {
            "hunger": self.hunger, "thirst": self.thirst, "drowsy": self.drowsy,
            "fatigue": self.fatigue, "stress": self.stress,
            "drift": self.drift, "rested": self.rested,
            "prayer": self.prayer,
            "thoughts": [list(t) for t in self.thoughts[-20:]],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Needs":
        """Rebuild from :meth:`to_dict`."""
        n = cls()
        n.hunger = int(d.get("hunger", 0))
        n.thirst = int(d.get("thirst", 0))
        n.drowsy = int(d.get("drowsy", 0))
        n.prayer = int(d.get("prayer", 0))
        n.fatigue = int(d.get("fatigue", 0))
        n.stress = int(d.get("stress", 0))
        n.drift = float(d.get("drift", 0.0))
        n.rested = int(d.get("rested", 0))
        n.thoughts = [(str(t[0]), int(t[1])) for t in d.get("thoughts", [])]
        return n

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Needs(%s, %s, %s)" % (
            self.hunger_word(), self.thirst_word(), self.sleep_word()
        )


def _severity(value: int, warn: int, danger: int) -> str:
    """Classify a need value as ok/warn/danger."""
    if value >= danger:
        return "danger"
    if value >= warn:
        return "warn"
    return "ok"


def _threshold_messages(
    before: int, after: int, thresholds: Sequence[Tuple[int, str]]
) -> List[str]:
    """Emit a message each time a threshold is newly crossed."""
    return [msg for limit, msg in thresholds if before < limit <= after]
