"""Nobles, their demands, and what happens when a dwarf has had enough.

A fortress that grows appoints people to positions. Most of them are useful.
The mayor is not, and will make demands, and will be unhappy if you ignore
them. That is the trade for the migrants that come with a famous fortress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..data.calendar import TICKS_PER_DAY

#: Stress at which a dwarf starts behaving badly, and then very badly.
STRESS_UNHAPPY = 60
STRESS_TANTRUM = 110
STRESS_BERSERK = 175

#: Odds per step that a miserable dwarf does something about it.
TANTRUM_ODDS = 3000


@dataclass(frozen=True)
class Position:
    """One appointment the fortress can fill."""

    id: str
    title: str
    #: Population at which the position appears.
    at_population: int
    #: Labor the holder is expected to have, if any.
    labor: str
    description: str = ""


POSITIONS: Dict[str, Position] = {
    p.id: p
    for p in (
        Position("expedition_leader", "expedition leader", 0, "",
                 "Whoever was in charge of the wagon."),
        Position("manager", "manager", 12, "",
                 "Keeps the work orders straight."),
        Position("broker", "broker", 14, "",
                 "Haggles with the caravan, and does better at it."),
        Position("chief_medical", "chief medical dwarf", 16, "medicine",
                 "Runs the hospital."),
        Position("sheriff", "sheriff", 18, "military",
                 "Deals with dwarves who deal with each other."),
        Position("mayor", "mayor", 22, "",
                 "Elected, and full of ideas about what you should build."),
    )
}

#: What a mayor might demand, and the item or building that satisfies it.
MANDATES: Tuple[Tuple[str, str, str], ...] = (
    ("statue", "building", "A statue, and soon."),
    ("table", "building", "Tables. Nobody should eat standing up."),
    ("chair", "building", "Chairs to go with the tables."),
    ("door", "building", "Doors. Privacy is a dwarven right."),
    ("gem", "item", "Something bright to look at."),
    ("prepared_meal", "item", "A proper meal, cooked properly."),
    ("dwarven_ale", "item", "More ale. Always more ale."),
)

#: How long a mandate stands before the noble takes offence. Twenty days,
#: from the calendar rather than from a hand-written 14400: see `HAUNT_AFTER`
#: for what happens when a duration is spelled out instead of derived.
MANDATE_TICKS = TICKS_PER_DAY * 20


class Noble:
    """One dwarf holding one position."""

    def __init__(self, position: str, dwarf_id: int, since: int = 0) -> None:
        self.position = position
        self.dwarf_id = dwarf_id
        self.since = since
        #: ``(target, kind, text, deadline, satisfied)``.
        self.mandate: Optional[Dict[str, Any]] = None

    @property
    def defn(self) -> Position:
        """The position's definition."""
        return POSITIONS.get(self.position) or POSITIONS["expedition_leader"]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the appointment."""
        return {"position": self.position, "dwarf": self.dwarf_id,
                "since": self.since, "mandate": self.mandate}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Noble":
        """Rebuild from :meth:`to_dict`."""
        n = cls(str(d["position"]), int(d["dwarf"]), int(d.get("since", 0)))
        n.mandate = d.get("mandate")
        return n

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Noble(%s, dwarf %d)" % (self.position, self.dwarf_id)


class Court:
    """Every appointment the fortress has made."""

    def __init__(self) -> None:
        self.nobles: List[Noble] = []

    def holder(self, position: str) -> Optional[int]:
        """The dwarf holding a position."""
        for n in self.nobles:
            if n.position == position:
                return n.dwarf_id
        return None

    def noble(self, position: str) -> Optional[Noble]:
        """The appointment for a position."""
        for n in self.nobles:
            if n.position == position:
                return n
        return None

    def position_of(self, dwarf_id: int) -> Optional[Noble]:
        """The position a dwarf holds, if any."""
        for n in self.nobles:
            if n.dwarf_id == dwarf_id:
                return n
        return None

    def title_of(self, dwarf_id: int) -> str:
        """A dwarf's title, or an empty string."""
        n = self.position_of(dwarf_id)
        return n.defn.title if n is not None else ""

    def appoint(self, position: str, dwarf_id: int, when: int = 0) -> Noble:
        """Give a dwarf a job with a title on it."""
        existing = self.noble(position)
        if existing is not None:
            existing.dwarf_id = dwarf_id
            existing.since = when
            return existing
        noble = Noble(position, dwarf_id, when)
        self.nobles.append(noble)
        return noble

    def vacate(self, dwarf_id: int) -> List[str]:
        """Strip every position a dwarf held; returns the positions freed."""
        freed = [n.position for n in self.nobles if n.dwarf_id == dwarf_id]
        self.nobles = [n for n in self.nobles if n.dwarf_id != dwarf_id]
        return freed

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the court."""
        return {"nobles": [n.to_dict() for n in self.nobles]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Court":
        """Rebuild from :meth:`to_dict`."""
        c = cls()
        c.nobles = [Noble.from_dict(n) for n in d.get("nobles", [])]
        return c

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Court(%d appointments)" % len(self.nobles)


def mandate_met(fort, mandate: Mapping[str, Any]) -> bool:
    """True if the fortress has done what was asked."""
    target = mandate.get("target", "")
    if mandate.get("kind") == "building":
        return any(b.kind == target and b.built for b in fort.buildings)
    return fort.stock_count(target) > 0
