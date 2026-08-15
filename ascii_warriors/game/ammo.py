"""Where a spent arrow goes.

Throwing a dagger and firing an arrow are the same act with different tackle,
and the game treated them as different kinds of event. `actions.throw` walks
the flight path, works out where the thing came down, and drops it there --
so a thrown dagger is lying in the grass afterwards and can be picked up and
thrown again. `combat.ranged_attack` did `ammo.count -= 1` and that was the
end of the arrow. Every shot fired in the history of this project has
annihilated its ammunition.

It matters most where ammunition is hardest to come by. An archer forty tiles
from anywhere runs dry and has nothing to do about it, and a fortress that
forges twenty bolts from a bar of iron watches a siege drain the stock with
nothing to sweep up afterwards.

**Some of it has to break, or an archer never runs out at all.** A shot that
hits something breaks more often than one that goes into the turf, and a
stone shatters where a steel bolt bends. `survives` is the whole of that
judgement.
"""

from __future__ import annotations

from typing import Optional, Tuple

from ..engine.rng import RNG

# -- tunable constants ------------------------------------------------------ #

#: Chance a shot that hit nothing is worth picking up again. Missing is the
#: cheap case: the arrow is in the grass, not in a rib.
MISS_SURVIVES = 0.80

#: Chance a shot that struck a body or a shield survives it.
HIT_SURVIVES = 0.45

#: What the material does to both. Shear yield stands in for how well the
#: shaft takes the shock: obsidian and stone shatter, iron bends, steel does
#: not much mind. Bounded so no material makes ammunition permanent.
MIN_TOUGHNESS = 0.55
MAX_TOUGHNESS = 1.30
#: The yield the scale is centred on -- iron, which is what most ammunition in
#: a fortress is made of.
TOUGH_REFERENCE = 155000.0


def toughness(item) -> float:
    """How well this ammunition takes being fired, around 1.0 for iron."""
    mat = getattr(item, "mat", None)
    if mat is None:
        return 1.0
    yield_str = float(getattr(mat, "shear_yield", TOUGH_REFERENCE))
    if yield_str <= 0.0:
        return MIN_TOUGHNESS
    return max(MIN_TOUGHNESS,
               min(MAX_TOUGHNESS, (yield_str / TOUGH_REFERENCE) ** 0.25))


def survives(item, rng: RNG, *, hit: bool) -> bool:
    """Whether a fired round is worth picking up afterwards."""
    base = HIT_SURVIVES if hit else MISS_SURVIVES
    return rng.chance(min(0.95, base * toughness(item)))


def land(world, item, cell: Tuple[int, int, int], rng: RNG, *,
         hit: bool) -> bool:
    """Put one spent round on the ground, if it is still worth anything.

    Takes the same shape as v3.25's severed-limb drop: a *world* that may or
    may not have a `drop_item`, because combat is called from two modes and a
    handful of tests that have neither.
    """
    if world is None or item is None:
        return False
    drop = getattr(world, "drop_item", None)
    if drop is None:
        return False
    if not survives(item, rng, hit=hit):
        return False
    drop(item, cell[0], cell[1], cell[2])
    return True


def spend(attacker, ammo) -> Optional[object]:
    """Take one round out of a stack and return it as its own item.

    The stack is what the quiver holds and a single round is what lands, so
    they cannot be the same object. `Item.split` already knew how to do this
    for throwing; firing simply never asked.
    """
    if ammo is None or ammo.count <= 0:
        return None
    if ammo.count > 1:
        one = ammo.split(1)
    else:
        one = ammo
        attacker.inventory.remove(ammo, 1)
        if one in attacker.inventory.items:
            attacker.inventory.items.remove(one)
    return one
