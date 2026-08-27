"""The dwarves you did not bury.

A dwarf that dies is a corpse on the floor and a bad afternoon for everybody
who saw it. Leave it there and it becomes something else. After a season the
dwarf comes back, and what comes back is not a monster with a body -- it walks
through the walls, it cannot be hit and it hits nothing, and it makes the
fortress a worse place to live for as long as it is there.

There is exactly one way to stop it, and it is the way a fortress would think
of first: put the body in a coffin. That is the whole rule. A haunting is not
a fight, it is an unfinished job with a name.

Kept apart from `Creature` deliberately. A ghost has no body, no needs, no
inventory, nothing to path around and nothing to path with; giving it one so
that the combat system would accept it would be handing the fortress a
monster it can neither kill nor flee, which is a different and much worse
game.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..data.calendar import TICKS_PER_HOUR, TICKS_PER_SEASON
from ..engine import colors

Cell = Tuple[int, int, int]

#: How long a dwarf lies unburied before it stops waiting. A season: long
#: enough that the first death is not immediately a crisis, short enough that
#: a fortress which never builds a coffin finds out why it should have.
#:
#: Taken from the calendar rather than written out, because the number that
#: used to be here was 100800 -- eighty-four days at twelve hundred ticks a
#: day, which is what a day is worth nowhere in this game. A day is
#: `TICKS_PER_DAY`, fourteen thousand four hundred, so the season above was
#: being served as a week. Nothing could see it: this was the one module in
#: the fortress with a duration constant and no calendar import, and both
#: tests that guard the window were written in terms of the constant, so
#: `test_nothing_rises_before_the_season_is_out` would have passed at
#: `HAUNT_AFTER = 1`. Measured over a played year, the first two dwarves to
#: die rose seven days later, and the fortress -- which had no coffin, and
#: had been given no reason yet to think it needed one -- carried them for
#: the remaining nine months.
HAUNT_AFTER = TICKS_PER_SEASON

#: How close a ghost has to be to be felt, and how much it costs to feel it.
HAUNT_RANGE = 6
HAUNT_STRESS = 3

#: Between one chill and the next, per ghost. Being haunted should be a slow
#: ruin rather than a fortress-wide panic every step.
CHILL_TICKS = TICKS_PER_HOUR * 2

#: How the dead are drawn.
GLYPH = "¤"
COLOR = colors.Color(180, 200, 220)


class Ghost:
    """One dwarf that is still here, and should not be."""

    __slots__ = ("who", "name", "x", "y", "z", "since", "last_chill")

    def __init__(self, who: int, name: str, cell: Cell, since: int) -> None:
        self.who = who
        self.name = name
        self.x, self.y, self.z = cell
        self.since = since
        self.last_chill = since

    @property
    def cell(self) -> Cell:
        """Where it is."""
        return (self.x, self.y, self.z)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise it."""
        return {"who": self.who, "name": self.name, "x": self.x, "y": self.y,
                "z": self.z, "since": self.since, "chill": self.last_chill}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Ghost":
        """Rebuild from :meth:`to_dict`."""
        g = cls(int(d.get("who", 0)), str(d.get("name", "")),
                (int(d.get("x", 0)), int(d.get("y", 0)), int(d.get("z", 0))),
                int(d.get("since", 0)))
        g.last_chill = int(d.get("chill", g.since))
        return g

    def __repr__(self) -> str:      # pragma: no cover - debugging aid
        return "Ghost(%s at %d,%d,%d)" % (self.name, self.x, self.y, self.z)


def buried(fort, who: int) -> bool:
    """True if this dwarf is in a coffin."""
    return any(b.buried == who for b in fort.buildings)


def body_of(fort, who: int):
    """The corpse of a particular dwarf, wherever it is lying."""
    for pile in fort.items_on_ground.values():
        for item in pile:
            if item.is_corpse and item.flags.get("who") == who:
                return item
    return None


def restless(fort) -> List[int]:
    """Every dwarf that has been dead too long and is not in a coffin.

    Only while there is still a body to put in one. A dwarf whose corpse was
    burned, eaten or carried off the map by a thief is gone with it -- there
    is no memorial slab in this game, and a haunting nobody can end is a
    fortress nobody can save.
    """
    out = []
    for who, died in fort.unburied.items():
        if fort.ticks - died < HAUNT_AFTER:
            continue
        if who in fort.ghosts or buried(fort, who):
            continue
        if body_of(fort, who) is None:
            continue
        out.append(who)
    return out


def rise(fort, who: int) -> Optional[Ghost]:
    """One dwarf gives up on being buried."""
    dead = fort.creatures.get(who)
    body = body_of(fort, who)
    if body is None:
        return None
    cell = fort.item_cell(body)
    if cell is None:
        return None
    name = dead.name if dead is not None else "somebody"
    ghost = Ghost(who, name, cell, fort.ticks)
    fort.ghosts[who] = ghost
    fort.log.bad("The ghost of %s has risen. It was never buried." % name)
    return ghost


def lay(fort, who: int) -> bool:
    """The body is in the ground; the dwarf can stop. True if one was laid."""
    ghost = fort.ghosts.pop(who, None)
    if ghost is None:
        return False
    fort.log.good("The ghost of %s has been laid to rest." % ghost.name)
    for d in fort.dwarves():
        d.needs.add_thought("a ghost was laid to rest", -6)
    return True


def _drift(fort, ghost: Ghost) -> None:
    """One step towards the nearest living dwarf, through whatever is between.

    No pathing: it has no feet. Walls are not an obstacle to it and that is
    most of what makes it frightening -- there is nowhere in the fortress a
    door will keep it out of.
    """
    from ..engine import geometry

    living = fort.dwarves()
    if not living:
        return
    prey = min(living, key=lambda d: (geometry.chebyshev(ghost.x, ghost.y,
                                                         d.x, d.y)
                                      + abs(ghost.z - d.z) * 4))
    dx, dy = geometry.normalize_dir(prey.x - ghost.x, prey.y - ghost.y)
    ghost.x = max(0, min(fort.local.width - 1, ghost.x + dx))
    ghost.y = max(0, min(fort.local.height - 1, ghost.y + dy))
    if ghost.z != prey.z:
        ghost.z += 1 if prey.z > ghost.z else -1


def haunt(fort, ticks: int) -> None:
    """Raise the restless, move the risen, and chill whoever is near one."""
    from ..engine import geometry

    for who in restless(fort):
        rise(fort, who)
    if not fort.ghosts:
        return
    for ghost in list(fort.ghosts.values()):
        _drift(fort, ghost)
        if fort.ticks - ghost.last_chill < CHILL_TICKS:
            continue
        felt = [d for d in fort.dwarves()
                if d.z == ghost.z
                and geometry.chebyshev(d.x, d.y, ghost.x, ghost.y)
                <= HAUNT_RANGE]
        if not felt:
            continue
        ghost.last_chill = fort.ticks
        for d in felt:
            d.needs.add_thought("was haunted", HAUNT_STRESS)
        fort.warn_once("haunted",
                       "Something cold walks the fortress. Bury your dead.")


def to_list(fort) -> List[Any]:
    """Serialise every ghost."""
    return [g.to_dict() for g in fort.ghosts.values()]


def from_list(fort, raw) -> None:
    """Rebuild them from :func:`to_list`."""
    out: Dict[int, Ghost] = {}
    for row in raw or ():
        g = Ghost.from_dict(row)
        out[g.who] = g
    fort.ghosts = out
