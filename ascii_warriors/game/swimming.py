"""Swimming: water you can be in, rather than water you cannot cross.

`TileDef.swim` has been on the water tiles since the tile table was written --
`water` and `deep_water` carry it, `shallow_water` does not -- and no code has
ever read it. What decided whether you could enter water was `TileDef.walk`,
and both of the deep tiles are `walk=False`, so a river was a wall. `Game.
is_passable` even has a branch letting a `SWIMMER` or an `AQUATIC` creature
into deep water; it sits below the `walk` test and has never once been reached.
The `swimming` skill is in the table with a blank description, is awarded
experience in three places, and outside the fortress's drowning loop is read by
nothing.

The two modes had also drifted apart, which is the usual reason a thing like
this survives. The fortress models water as a fluid layer with a depth of 0 to
7 on top of the terrain, and drowns whatever stands in too much of it.
Adventure mode has no fluid layer at all -- its water is terrain -- so it had
no depth to consult and no drowning to do. `TILE_DEPTH` is what lets one rule
serve both: it says what depth each water tile stands for, so the question
"is this creature's head under" has a single answer everywhere.
"""

from __future__ import annotations

from ..engine.rng import RNG
from ..world import fluids

# -- what the terrain is worth ---------------------------------------------- #

#: Terrain water, on the fluid layer's 0..7 scale. A river tile is not a
#: flooded room: `deep_water` is 6 rather than 7 on purpose, because 7 is water
#: to the ceiling and nothing swims in that. A lake you can swim across and a
#: sealed room filling to the roof are different things and the numbers have to
#: say so.
TILE_DEPTH = {
    "shallow_water": 2,
    "water": 5,
    "deep_water": 6,
}

# -- keeping your head up --------------------------------------------------- #

#: Chance an unskilled creature keeps its head above water for one more step.
#: Not zero, which is what the fortress used: a skill nobody can survive long
#: enough to train is a skill nobody trains. Flailing buys you a few steps to
#: get back to the bank, and getting back to the bank is what teaches you.
BASE_STROKE = 0.34
#: What each level of `swimming` adds. Set so the ceiling arrives at level 20
#: rather than at 11 -- the same mistake v3.28 found in `armor_use`, and it is
#: apparently an easy one to make twice.
PER_LEVEL = 0.030
#: Nobody is so good that deep water is never dangerous.
MAX_STROKE = 0.94

#: Load carried, as a share of capacity, that costs nothing. Carry capacity in
#: this game is generous -- a full kit is under a twentieth of it -- so the
#: free share has to be small or the oldest true thing about swimming, that
#: armour drowns you, never happens to anybody.
FREE_LOAD = 0.05
#: What each further share of capacity costs.
LOAD_PENALTY = 1.40
#: The load at which no skill is any use and you simply go down. A full steel
#: harness is above this and stays above it however good the wearer is at
#: carrying one, which is the point: some things you take off or go round. A
#: gradual penalty alone could not say that -- at legendary the curve still
#: came out at even odds, and "you cannot swim in plate" is worth more as a
#: rule than as a steep slope.
SINK_LOAD = 0.35

#: Three water tiles, three cases, named rather than interpolated because
#: three is all the data there is. `water` is the base case; `deep_water` is
#: worse; water to the ceiling is a flooded room and not a lake at all.
DEEP_WATER = 0.62
OVERHEAD = 0.12

#: Ticks of breath a creature has. An actor gains its speed in energy every
#: tick and acts at `ACTION_COST`, so at the baseline speed one standard action
#: is one tick and this is two dozen of them -- long enough to turn round and
#: swim back, short enough to be frightening. Getting the unit wrong here is
#: easy and quiet: the first draft read 800, which is most of a minute of
#: continuous drowning and would have meant nothing ever drowned at all.
DROWN_TICKS = 24

#: Exertion one swum step costs, against 2 for a walked one.
SWIM_EXERTION = 7

#: What swimming does to how fast you get anywhere.
SWIM_SPEED = 0.45


def depth_of(tile_id: str) -> int:
    """What depth of water a terrain tile stands for, 0 if it is not water."""
    return TILE_DEPTH.get(tile_id, 0)


def is_swimming(depth: int) -> bool:
    """True if this much water has a creature off its feet."""
    return depth >= fluids.SWIM_DEPTH


def can_enter(creature, depth: int) -> bool:
    """Whether a creature will go into this much water at all.

    Everything that breathes air can try. What separates them is whether they
    come out again, which is the next question and not this one.
    """
    if depth <= 0:
        return True
    if creature is None:
        return not is_swimming(depth)
    if creature.defn.has("AQUATIC") or creature.defn.has("SWIMMER"):
        return True
    if not is_swimming(depth):
        return True
    return creature.body.can_stand() and not creature.body.is_incapacitated()


def stroke_chance(creature, depth: int) -> float:
    """Odds this creature keeps its head above *depth* for one more step."""
    if creature.defn.has("AQUATIC") or creature.defn.has("SWIMMER"):
        return 1.0
    if not is_swimming(depth):
        return 1.0
    load = creature.encumbrance()
    if load >= SINK_LOAD:
        return 0.0
    chance = BASE_STROKE + creature.skills.level("swimming") * PER_LEVEL
    if load > FREE_LOAD:
        chance -= (load - FREE_LOAD) * LOAD_PENALTY
    if creature.body.is_incapacitated() or creature.body.unconscious > 0:
        return 0.0
    if not creature.body.can_stand():
        # You swim with your legs. A broken one is felt here more than
        # anywhere else, because there is no ground to lean the rest on.
        chance *= 0.4
    if depth >= fluids.MAX_DEPTH:
        chance *= OVERHEAD
    elif depth > fluids.SWIM_DEPTH + 1:
        chance *= DEEP_WATER
    return max(0.0, min(MAX_STROKE, chance))


def stays_up(creature, depth: int, rng: RNG) -> bool:
    """Roll whether a creature keeps its head above water this step.

    The one rule both modes ask. A creature that stays up learns something for
    having done it; a creature that goes under starts holding its breath.
    """
    if not is_swimming(depth):
        return True
    chance = stroke_chance(creature, depth)
    if chance >= 1.0:
        return True
    if rng.chance(chance):
        creature.add_exp("swimming", 4)
        return True
    return False


def breath_lost(creature, depth: int, ticks: int) -> float:
    """Ticks of breath *ticks* of this water costs.

    The two modes run on different clocks and there is no honest way round it:
    the fortress steps ten ticks at a time and rolls once per step, while
    adventure mode advances by however long the last creature's action took.
    Rolling per call would make drowning depend on how many goblins happened
    to be awake. So the shared thing is the odds -- :func:`stroke_chance` --
    and this integrates them instead of rolling them.

    Returns a float on purpose. Rounding here and treating a zero as "head
    above water" throws the whole held breath away every time the world
    advances by a tick or two, which on a busy map is most of the time.
    """
    if ticks <= 0 or not is_swimming(depth):
        return 0.0
    return ticks * (1.0 - stroke_chance(creature, depth))


def avoids(creature, here_depth: int, there_depth: int, *,
           desperate: bool = False) -> bool:
    """Whether a creature refuses to step from one depth into another.

    A deer does not swim a lake for the sake of it. Once water could be
    entered at all, every wandering animal on the map could walk into one and
    hold its breath until it stopped, which is not wildlife behaviour, it is a
    bug with legs. Something already swimming never refuses -- it has to be
    able to reach the bank -- and something running for its life will take to
    the water, which is what water is for.
    """
    if not is_swimming(there_depth):
        return False
    if creature.defn.has("AQUATIC") or creature.defn.has("SWIMMER"):
        return False
    if is_swimming(here_depth) or desperate:
        return False
    return True


def drop_weight(creature) -> float:
    """How far over the free load this creature is carrying, 0 if under it."""
    return max(0.0, creature.encumbrance() - FREE_LOAD)
