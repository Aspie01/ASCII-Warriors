"""Crime, and what the sheriff does about it.

The fortress already had dwarves who smash the furniture when they have had
enough, mayors who demand statues nobody builds, and no consequences for any
of it. This is the consequences: a record of who did what, a sheriff who
convicts them, and a punishment that satisfies the law and upsets the guilty,
which is the trade every fortress makes.

Nothing here is automatic justice. A fortress with no sheriff accumulates
unsolved crimes and everybody living in it notices, which is its own kind of
pressure, and a crime nobody was caught at cannot be tried at all however big
the fortress gets.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..data.calendar import TICKS_PER_DAY

#: What can be committed, and how badly the fortress takes it.
CRIMES: Dict[str, Tuple[str, int]] = {
    "vandalism": ("destroyed something in a tantrum", 1),
    "assault": ("attacked another dwarf", 2),
    "theft": ("made off with fortress property", 2),
    "murder": ("killed another dwarf", 4),
    "neglect": ("failed to satisfy a mandate", 1),
}

#: How long a conviction takes to serve, per unit of severity.
JAIL_TICKS = TICKS_PER_DAY * 4

#: A crime older than this is forgotten, sheriff or no sheriff.
COLD_CASE = TICKS_PER_DAY * 90

#: How much an unpunished crime raises everybody's stress each season.
UNSOLVED_STRESS = 3

#: How often the sheriff opens the book. A season is far too long: a bad week
#: fills the book with a dozen cases, and a law that answers them in three
#: months is a law nobody in the fortress can see working.
COURT_INTERVAL = TICKS_PER_DAY * 3


class Crime:
    """One thing somebody did."""

    _next_id = 1

    def __init__(self, kind: str, culprit: Optional[int], tick: int,
                 detail: str = "") -> None:
        self.id = Crime._next_id
        Crime._next_id += 1
        self.kind = kind
        self.culprit = culprit
        self.tick = tick
        self.detail = detail
        self.convicted = False
        #: Tick the sentence ends. Zero until one is passed, -1 once it is over.
        self.until = 0
        #: Set when the sentence was ended early rather than served. The book
        #: remembers the difference even though the prisoner is out either way.
        self.pardoned = False

    @property
    def severity(self) -> int:
        """How seriously the fortress takes this."""
        return CRIMES.get(self.kind, ("", 1))[1]

    @property
    def description(self) -> str:
        """What the sheriff's book says."""
        return CRIMES.get(self.kind, ("did something", 1))[0]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the crime."""
        return {"id": self.id, "kind": self.kind, "culprit": self.culprit,
                "tick": self.tick, "detail": self.detail,
                "convicted": self.convicted, "until": self.until,
                "pardoned": self.pardoned}

    @classmethod
    def from_dict(cls, d) -> "Crime":
        """Rebuild from :meth:`to_dict`."""
        c = cls(str(d["kind"]), d.get("culprit"), int(d.get("tick", 0)),
                str(d.get("detail", "")))
        c.id = int(d.get("id", c.id))
        Crime._next_id = max(Crime._next_id, c.id + 1)
        c.convicted = bool(d.get("convicted", False))
        c.until = int(d.get("until", 0))
        c.pardoned = bool(d.get("pardoned", False))
        return c


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def report(fort, kind: str, culprit, detail: str = "") -> Optional[Crime]:
    """Write a crime into the fortress's book.

    The culprit may be nobody: a thief that got away leaves a crime with no
    name on it, which is exactly how a fortress experiences one.
    """
    if kind not in CRIMES:
        return None
    crime = Crime(kind, getattr(culprit, "id", None), fort.ticks, detail)
    fort.crimes.append(crime)
    who = culprit.name if culprit is not None else "Somebody"
    fort.log.warn("%s %s." % (who, crime.description))
    return crime


def open_cases(fort) -> List[Crime]:
    """Crimes nobody has answered for yet."""
    return [c for c in fort.crimes
            if not c.convicted and fort.ticks - c.tick < COLD_CASE]


def cold_cases(fort) -> List[Crime]:
    """Crimes nobody is going to answer for now."""
    return [c for c in fort.crimes
            if not c.convicted and fort.ticks - c.tick >= COLD_CASE]


def serving(fort) -> List[Crime]:
    """Convictions still being served."""
    return [c for c in fort.crimes if c.convicted and c.until > fort.ticks]


def is_jailed(fort, dwarf) -> bool:
    """True while a dwarf is serving a sentence."""
    return any(c.culprit == dwarf.id and c.until > fort.ticks
               for c in fort.crimes if c.convicted)


def culprit_of(fort, crime: Crime):
    """The dwarf a crime is pinned on, if it is pinned on anybody here."""
    if crime.culprit is None:
        return None
    return fort.creatures.get(crime.culprit)


def describe(fort, crime: Crime) -> str:
    """One line of the sheriff's book."""
    culprit = culprit_of(fort, crime)
    who = culprit.name if culprit is not None else "Somebody"
    detail = " (%s)" % crime.detail if crime.detail else ""
    return "%s %s%s" % (who, crime.description, detail)


# --------------------------------------------------------------------------- #
# The sheriff
# --------------------------------------------------------------------------- #


def sheriff(fort):
    """The dwarf who deals with dwarves who deal with each other."""
    noble = fort.court.noble("sheriff")
    if noble is None:
        return None
    return fort.creatures.get(noble.dwarf_id)


def can_try(fort, crime: Crime) -> bool:
    """Whether this case can go anywhere.

    A crime nobody was caught at -- a thief in the night, a body at the
    bottom of a stairwell -- has nobody to try, and stays open until it goes
    cold. That gap is what the unsolved-crime stress is for.
    """
    if crime.convicted:
        return False
    culprit = culprit_of(fort, crime)
    return (culprit is not None and not culprit.body.dead
            and getattr(culprit, "fort", None) is not None)


def hold_court(fort) -> List[Crime]:
    """Try every open case the sheriff can actually solve."""
    law = sheriff(fort)
    if law is None or law.body.dead:
        return []
    done = []
    for crime in open_cases(fort):
        if not can_try(fort, crime):
            continue
        convict(fort, crime, culprit_of(fort, crime), law)
        done.append(crime)
    return done


def convict(fort, crime: Crime, culprit, law=None) -> None:
    """Pass a sentence and make everybody feel about it."""
    crime.convicted = True
    crime.until = fort.ticks + JAIL_TICKS * crime.severity
    days = JAIL_TICKS * crime.severity // TICKS_PER_DAY
    fort.log.system("%s is convicted: %s. %d days." % (
        culprit.name, crime.description, days))
    culprit.needs.add_thought("was convicted of a crime", 12)
    for other in fort.dwarves():
        if other is not culprit:
            # A fortress that punishes its criminals is a calmer fortress.
            other.needs.add_thought("saw justice done", -3)


def pardon(fort, crime: Crime) -> bool:
    """Let somebody out early, and wear what the rest of them think of it.

    The overseer's prerogative. Your legendary mason is back on the roster
    this afternoon, and every other dwarf spends a season remembering that
    the law is what you say it is.
    """
    if not crime.convicted or crime.until <= fort.ticks:
        return False
    crime.until = -1
    crime.pardoned = True
    culprit = culprit_of(fort, crime)
    name = culprit.name if culprit is not None else "The prisoner"
    fort.log.warn("%s is pardoned." % name)
    if culprit is not None and not culprit.body.dead:
        culprit.needs.add_thought("was pardoned", -10)
    for other in fort.dwarves():
        if other is not culprit:
            other.needs.add_thought("saw a criminal walk free", 6)
    return True


def tick(fort) -> None:
    """Hold court when it is due, and release anybody who has served.

    Runs every step, so it leaves immediately in the ordinary case where the
    fortress is law-abiding or at least uncaught.
    """
    if not fort.crimes:
        return
    if fort.ticks >= fort._next_court:
        fort._next_court = fort.ticks + COURT_INTERVAL
        hold_court(fort)
    for crime in fort.crimes:
        if not crime.convicted or not crime.until:
            continue
        if crime.until > fort.ticks or crime.until < 0:
            continue
        crime.until = -1
        culprit = (fort.creatures.get(crime.culprit)
                   if crime.culprit is not None else None)
        if culprit is not None and not culprit.body.dead:
            fort.log.system("%s has served their sentence." % culprit.name)
            culprit.needs.add_thought("served a sentence", 4)


def season(fort) -> None:
    """What the fortress thinks of the state of the law."""
    unsolved = open_cases(fort)
    if not unsolved:
        return
    if sheriff(fort) is None:
        fort.warn_once(
            "sheriff",
            "There are crimes nobody has answered for, and nobody to try "
            "them. A fortress of eighteen appoints a sheriff.")
    for d in fort.dwarves():
        d.needs.add_thought("lives among unpunished crime",
                            min(9, UNSOLVED_STRESS * len(unsolved)))


def days_left(fort, crime: Crime) -> int:
    """Days still to serve on a sentence."""
    if not crime.convicted or crime.until <= fort.ticks:
        return 0
    return max(1, (crime.until - fort.ticks) // TICKS_PER_DAY)


def summary(fort) -> str:
    """One line for the status bar.

    Both numbers when there are both. A fortress with four fifths of its
    labour in a cell needs to be told so, and the unsolved count alone hides
    exactly the half the overseer can do something about.
    """
    unsolved = len(open_cases(fort))
    jailed = len(serving(fort))
    if unsolved and jailed:
        return "%d unsolved, %d serving" % (unsolved, jailed)
    if jailed:
        return "%d serving" % jailed
    if unsolved:
        return "%d unsolved" % unsolved
    return ""
