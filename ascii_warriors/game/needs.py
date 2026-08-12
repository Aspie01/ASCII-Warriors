"""Hunger, thirst, sleep, fatigue and stress."""

from __future__ import annotations

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


class Needs:
    """A creature's bodily and mental needs."""

    __slots__ = ("hunger", "thirst", "drowsy", "fatigue", "stress", "thoughts")

    def __init__(self) -> None:
        self.hunger = 0
        self.thirst = 0
        self.drowsy = 0
        self.fatigue = 0
        self.stress = 0
        #: Recent thoughts as ``(text, stress delta)``.
        self.thoughts: List[Tuple[str, int]] = []

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
            before = self.drowsy
            self.drowsy += ticks
            msgs.extend(
                _threshold_messages(
                    before, self.drowsy,
                    ((SLEEP_DROWSY, "You are drowsy."),
                     (SLEEP_EXHAUSTED, "You are exhausted and can barely stand.")),
                )
            )

        self.fatigue = max(0, self.fatigue - max(1, ticks // 4))

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
        """Consume food; returns the message to show."""
        nutrition = item.defn.nutrition or 400
        self.hunger = max(0, self.hunger - nutrition * 6)
        if item.defn.hydration:
            self.thirst = max(0, self.thirst - item.defn.hydration * 6)
        if item.quality >= 3:
            self.add_thought("ate a fine meal", -6)
        return "You eat %s." % item.name(article=True)

    def drink(self, item: Item) -> str:
        """Consume a drink; returns the message to show."""
        hydration = item.defn.hydration or 600
        self.thirst = max(0, self.thirst - hydration * 8)
        if item.defn.nutrition:
            self.hunger = max(0, self.hunger - item.defn.nutrition * 4)
        if item.material == "alcohol":
            self.add_thought("had a drink", -4)
            self.stress = max(-100, self.stress - 2)
        return "You drink %s." % item.name(article=True)

    def sleep(self, ticks: int) -> None:
        """Rest for a while."""
        self.drowsy = max(0, self.drowsy - ticks * 3)
        self.fatigue = 0
        self.stress = max(-100, self.stress - ticks // 400)

    def exert(self, amount: int = 10) -> None:
        """Spend energy on a strenuous action."""
        self.fatigue = min(FATIGUE_MAX, self.fatigue + amount)

    def add_thought(self, text: str, value: int) -> None:
        """Record a thought and shift stress by *value* (negative is good)."""
        self.thoughts.append((text, value))
        if len(self.thoughts) > 40:
            del self.thoughts[:-40]
        self.stress = max(-150, min(200, self.stress + value))

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
            "thoughts": [list(t) for t in self.thoughts[-20:]],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Needs":
        """Rebuild from :meth:`to_dict`."""
        n = cls()
        n.hunger = int(d.get("hunger", 0))
        n.thirst = int(d.get("thirst", 0))
        n.drowsy = int(d.get("drowsy", 0))
        n.fatigue = int(d.get("fatigue", 0))
        n.stress = int(d.get("stress", 0))
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
