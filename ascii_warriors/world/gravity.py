"""Gravity: the thing a nineteen-level map had no use for.

`LocalMap.has_floor` has answered "is there anything holding this creature up"
since there were z-levels, and it is asked in **one place** -- the player's own
step, which quietly slides you down to the first solid thing and does nothing
else about it. You could walk off a ten-level cliff and land unhurt, and
nothing else in the game fell at all: not creatures, not items, and not a dwarf
standing on a floor another dwarf had just channelled away.

The `chasm` tile has been in the table since the table was written, flagged
`OPEN` and `CHASM`, unwalkable, coloured for the dark at the bottom -- and no
map generator has ever placed one, because there was nothing a hole in the
floor could do.

**A fall is a trap that the ground sets.** It goes through
`combat.trap_strike`, the same table v3.14, v3.17 and v3.18 put their hazards
in, so there is one list of damage nobody gets to parry rather than a second
set of numbers for the same event. It has its own row rather than borrowing
the `pit` trap's: a fall is the whole body arriving at once, which is an
enormous contact area and almost no penetration, and a trap's numbers let a
breastplate eat a six-storey drop entirely. Distance is what scales it: one
level is a step down, four is a broken leg, ten is the end.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from . import tiles as tile_data

Cell = Tuple[int, int, int]

#: How far something can drop before it starts to hurt. One level is a step
#: down, which the player has been taking for free since v1 and should keep.
SAFE_DROP = 1

#: What each level past that is worth, as a number of impacts. Measured
#: against an unarmoured human: two levels bruises, five breaks something six
#: times in ten, and ten levels breaks something every time and kills three
#: in ten. Iron plate roughly halves all of it.
PER_LEVEL = 0.45

#: The most a fall can be worth, however deep the hole. Past a point the
#: difference between very dead and very very dead is not worth modelling.
MAX_FALL = 4.0

#: How much of a fall a landing in water takes off. Deep water is the reason
#: to build a reservoir under the drop.
WATER_RELIEF = 0.65


def supported(lm, cell: Cell) -> bool:
    """Whether anything is holding a creature up here."""
    return lm is not None and lm.has_floor(*cell)


def landing(lm, cell: Cell) -> Cell:
    """Where something at *cell* comes to rest."""
    if lm is None:
        return cell
    x, y, z = cell
    while z > lm.zmin and not lm.has_floor(x, y, z):
        z -= 1
    return (x, y, z)


def drop_distance(lm, cell: Cell) -> int:
    """How far something at *cell* would fall."""
    return cell[2] - landing(lm, cell)[2]


def fall_force(distance: int) -> float:
    """What a fall of *distance* levels is worth, against the `pit` trap."""
    if distance <= SAFE_DROP:
        return 0.0
    return min(MAX_FALL, PER_LEVEL * (distance - SAFE_DROP))


def hurt(creature, distance: int, rng, *, log=None, water=0) -> float:
    """Land on somebody. Returns the force, 0 if the drop was nothing.

    Through `combat.trap_strike` and the `pit` entry v3.14 already wrote,
    which is what a fall is: something hits you very hard and you do not get
    to parry it.
    """
    force = fall_force(distance)
    if water:
        force *= 1.0 - WATER_RELIEF
    if force <= 0.0:
        return 0.0
    from ..game import combat

    # The table is one strike; a long fall is that strike several times over.
    # Rolling it as repeats rather than one huge number keeps the body model
    # doing what it does -- several broken things rather than one crater.
    for _ in range(max(1, int(force + 0.5))):
        if creature.body.dead:
            break
        combat.trap_strike(creature, "fall", "", rng=rng, log=log)
    return force


def settle(world, creature, rng, *, log=None) -> int:
    """Let a creature fall to wherever it is going. Returns levels fallen.

    Called from the one funnel each mode has for movement, and from anywhere
    the floor is taken away, so there is no second way to be standing in
    mid-air.
    """
    lm = getattr(world, "local", None)
    if lm is None:
        return 0
    from ..game import flight

    if flight.can_fly(creature):
        # Ten creatures in the bestiary carry `FLIER` and every one of them
        # used to fall down holes with the cows.
        return 0
    here = (creature.x, creature.y, creature.z)
    rest = landing(lm, here)
    distance = here[2] - rest[2]
    if distance <= 0:
        return 0
    creature.x, creature.y, creature.z = rest
    depth = 0
    water = getattr(world, "water", None)
    if water is not None:
        depth = water.at(*rest)
    if fall_force(distance) > 0.0 and log is not None:
        who = ("You fall" if getattr(creature, "is_player", False)
               else "%s falls" % creature.display_name())
        log.warn("%s %d level%s." % (who, distance,
                                     "" if distance == 1 else "s"))
    hurt(creature, distance, rng, log=log, water=depth)
    return distance


def settle_items(world, cell: Cell) -> int:
    """Let anything lying in mid-air fall. Returns how many pieces moved."""
    lm = getattr(world, "local", None)
    if lm is None or supported(lm, cell):
        return 0
    rest = landing(lm, cell)
    if rest == cell:
        return 0
    moved = 0
    for item in list(world.items_at(*cell)):
        # A Game removes an item from a named cell and a Fortress goes and
        # finds it; the two have had different signatures since both existed
        # and this is the only caller that has to know.
        try:
            world.take_item(item, *cell)
        except TypeError:
            world.take_item(item)
        world.drop_item(item, *rest)
        moved += 1
    return moved


def unsupported_creatures(world) -> List[Any]:
    """Everyone currently standing on nothing."""
    lm = getattr(world, "local", None)
    if lm is None:
        return []
    from ..game import flight

    out = []
    for c in getattr(world, "creatures", {}).values():
        if c.body.dead or getattr(c, "mount", None) is not None:
            continue
        if flight.can_fly(c):
            continue
        if not supported(lm, (c.x, c.y, c.z)):
            out.append(c)
    return out


def is_chasm(lm, cell: Cell) -> bool:
    """Whether this cell is an open hole rather than a floor."""
    if lm is None or not lm.in_bounds(*cell):
        return False
    return tile_data.get(lm.tile(*cell)).has("CHASM")
