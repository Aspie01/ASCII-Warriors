"""Webs: the thing a giant cave spider is actually for.

`WEBBER` has been on the giant cave spider and the giant desert scorpion since
the creature data was written, and there has been a `web` tile with a `WEB`
flag in the tile table for just as long. Neither has ever been read. A spider
was a large animal that bit you.

A web is a tile, not a status. It sits on the floor, it is visible, it can be
walked around, and it catches whatever walks into it -- including the spider's
other prey, and including the spider, which is why spinners ignore their own.
Getting out is a strength roll against the strands, so the answer to a web is
either not walking into it or being strong enough that it does not matter.

Being stuck is the point. A creature that cannot move while something that can
walks towards it is the oldest trap in the genre, and the game has had every
piece of it in the data files since v1 without one line joining them up.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

Cell = Tuple[int, int, int]

#: The tile a web is made of. Already in the tile table, already walkable,
#: already drawn as a pale `*`.
WEB_TILE = "web"

#: How strong a fresh strand is. A struggle removes some of it.
STRENGTH = 100

#: How far a spinner will throw one.
RANGE = 6

#: Odds per turn that a webber in sight of prey spins.
SPIN_ODDS = 0.14

#: Ticks between one web and the next from the same creature, so a spider
#: cannot carpet a room in a dozen turns.
COOLDOWN = 120

#: How much a point of strength is worth against a strand.
PER_STRENGTH = 34.0

#: What one failed struggle still tears away, so nobody is stuck for ever.
MIN_TEAR = 12


def is_web(game, cell: Cell) -> bool:
    """Whether a cell is webbed."""
    lm = getattr(game, "local", None)
    if lm is None or not lm.in_bounds(*cell):
        return False
    return lm.tile(*cell) == WEB_TILE


def spins(creature) -> bool:
    """Whether this creature makes webs."""
    defn = getattr(creature, "defn", None)
    return bool(defn is not None and defn.has("WEBBER"))


def immune(creature) -> bool:
    """Whether a web holds this creature at all.

    Spinners walk their own webs, which is both true of spiders and the only
    thing that stops a spider webbing itself into a corner and starving.
    """
    return spins(creature)


def spin(game, spinner, cell: Cell) -> bool:
    """Lay a web on a cell. False if it could not be laid there."""
    lm = getattr(game, "local", None)
    if lm is None or not lm.in_bounds(*cell):
        return False
    if not lm.walkable(*cell) or lm.tile(*cell) == WEB_TILE:
        return False
    lm.set_tile(cell[0], cell[1], cell[2], WEB_TILE)
    strands(game)[cell] = STRENGTH
    return True


def strands(game) -> Dict[Cell, int]:
    """How much web is left on each webbed cell."""
    got = getattr(game, "webs", None)
    if got is None:
        got = game.webs = {}
    return got


def strength_at(game, cell: Cell) -> int:
    """How much web is on a cell. A webbed tile with no record is a full one."""
    if not is_web(game, cell):
        return 0
    return strands(game).get(cell, STRENGTH)


def caught(game, creature) -> bool:
    """Whether this creature is currently held."""
    if immune(creature):
        return False
    return strength_at(game, (creature.x, creature.y, creature.z)) > 0


def struggle(game, creature, rng) -> Tuple[bool, str]:
    """Try to tear free of a web. Returns whether it worked and what to say.

    Always tears something away even on a failure, so no creature is ever
    permanently stuck by bad luck -- the worst case is several turns of being
    somewhere a spider knows about, which is bad enough.
    """
    cell = (creature.x, creature.y, creature.z)
    left = strength_at(game, cell)
    if left <= 0:
        return (True, "")
    power = creature.attributes.factor("strength") * PER_STRENGTH
    torn = max(MIN_TEAR, int(power * rng.uniform(0.5, 1.3)))
    left -= torn
    creature.needs.exert(12)
    if left <= 0:
        clear(game, cell)
        return (True, "You tear free of the web." if creature.is_player
                else "%s tears free." % creature.short_name().capitalize())
    strands(game)[cell] = left
    return (False, "You are stuck in the web." if creature.is_player
            else "%s is stuck." % creature.short_name().capitalize())


def clear(game, cell: Cell) -> None:
    """Take the web off a cell and put the floor back."""
    lm = getattr(game, "local", None)
    strands(game).pop(cell, None)
    if lm is None or lm.tile(*cell) != WEB_TILE:
        return
    lm.set_tile(cell[0], cell[1], cell[2], lm.soil or "dirt")


def maybe_spin(game, spinner, target, rng) -> Optional[Cell]:
    """A webber decides whether to throw one, and where.

    In front of the prey rather than on it: a web laid where somebody already
    stands is a web they walk out of next turn, and one laid in their path is
    a trap. The spider is aiming at where you are going.
    """
    if not spins(spinner) or target is None:
        return None
    if game.scheduler.ticks < getattr(spinner, "_web_next", 0):
        return None
    if spinner.distance_to(target) > RANGE:
        return None
    if not rng.chance(SPIN_ODDS):
        return None

    dx = _sign(spinner.x - target.x)
    dy = _sign(spinner.y - target.y)
    for cell in ((target.x + dx, target.y + dy, target.z),
                 (target.x, target.y, target.z)):
        if spin(game, spinner, cell):
            spinner._web_next = game.scheduler.ticks + COOLDOWN
            return cell
    return None


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def to_list(game) -> List[Any]:
    """Serialise the strand map."""
    return [[c[0], c[1], c[2], v] for c, v in strands(game).items()]


def from_list(game, raw: Sequence[Any]) -> None:
    """Rebuild it from :func:`to_list`."""
    out: Dict[Cell, int] = {}
    for row in raw or ():
        try:
            x, y, z, v = row
        except (TypeError, ValueError):      # pragma: no cover - defensive
            continue
        out[(int(x), int(y), int(z))] = int(v)
    game.webs = out
