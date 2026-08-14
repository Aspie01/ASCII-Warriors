"""How animals behave when they are not fighting you.

Three flags in the creature data have never been read. `BENIGN` is on the
deer, the rabbit, the cow and everything else that has no interest in a fight;
`AMBUSHER` is on the wolf, the lion and the giant cave spider; `VERMIN` is on
the rat and its relatives. Until now the wilderness was a set of creatures
that either attacked you or stood still, and a deer that stands there while
you walk up to it and cut its throat makes nonsense of two systems that were
built specifically to get you close to one.

**`BENIGN` means it runs.** Not when it is hurt -- `opportunity_to_flee`
already covers that, and it is a different question -- but when a person gets
near it at all. That is what makes hunting an activity rather than a walk:
v3.9 put tracks in the ground to be followed, v3.6 put stealth in so you could
close the distance, and neither of them had a point while dinner waited
politely for you to arrive.

How near is "near" depends on whether the animal has noticed you, which is
v3.6's `noticed_by` again. Sneak well and you are inside its flight distance
before it knows; walk up in daylight and you watch it go.

**`AMBUSHER` means it does not run at you.** A wolf that charges from thirty
tiles away is a wolf you shoot twice before it arrives. An ambusher holds
still while you are far off, then breaks cover inside its strike range, with
v3.6's ambush bonus already waiting for whatever it reaches. Carrying the flag now also
means `natural_sneak` hides you: a fox has AMBUSHER and no `ambusher` skill
whatsoever, so reading only the skill left every animal the data calls an
ambusher standing in the open where anything could see it.

**`VERMIN` means it wants your food and not your blood.** It flees anything
bigger than it, and if it finds itself next to food on the ground it takes
some and keeps running.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

#: How close a person gets before a skittish animal leaves, when it has seen
#: them. Deliberately longer than a bow's comfortable range: shooting one at
#: this distance is a real shot, not a formality.
FLIGHT_SEEN = 9

#: And when it has not. Something that has not noticed you still startles when
#: you are close enough to touch.
FLIGHT_UNSEEN = 2

#: How long an animal keeps running once it has started, in turns. Without
#: this it flees one step, stops, and gets shot anyway.
FLIGHT_TURNS = 14

#: Inside this an ambusher stops waiting and goes. Chosen so the charge is one
#: or two turns long: far enough to be a decision, near enough that a bow is
#: not the automatic answer.
STRIKE_RANGE = 4

#: An ambusher that has been seen has lost the ambush, and stops pretending.
#: It hunts like anything else after that.
GIVE_UP_HIDDEN = 16

#: How close vermin let anything get before scattering.
VERMIN_FLIGHT = 4

#: Odds a vermin next to food on the ground takes some and runs.
STEAL_ODDS = 0.5


def is_skittish(creature) -> bool:
    """Whether this animal would rather be somewhere else."""
    defn = getattr(creature, "defn", None)
    if defn is None or defn.intelligent:
        return False
    return defn.has("BENIGN") or defn.has("VERMIN")


def is_ambusher(creature) -> bool:
    """Whether this creature waits rather than charges."""
    defn = getattr(creature, "defn", None)
    return bool(defn is not None and defn.has("AMBUSHER"))


def is_vermin(creature) -> bool:
    """Whether this creature is after food rather than a fight."""
    defn = getattr(creature, "defn", None)
    return bool(defn is not None and defn.has("VERMIN"))


# --------------------------------------------------------------------------- #
# Running away
# --------------------------------------------------------------------------- #


def flight_distance(game, animal, person) -> int:
    """How close *person* may get before *animal* leaves.

    Through `noticed_by`, so the whole of v3.6 is what decides whether you get
    within bowshot of a deer. A tame animal has no flight distance at all: it
    has decided about you already.
    """
    from . import stealth

    if getattr(animal, "tame", False):
        return 0
    if is_vermin(animal):
        return VERMIN_FLIGHT
    if not stealth.noticed_by(game, person, animal):
        return FLIGHT_UNSEEN
    return FLIGHT_SEEN


def frightener(game, animal) -> Optional[Any]:
    """The nearest person close enough to put this animal to flight."""
    if not is_skittish(animal) or getattr(animal, "tame", False):
        return None
    best, best_d = None, 999
    for other in game.creatures.values():
        if other is animal or not other.alive:
            continue
        if not _alarming(animal, other):
            continue
        d = animal.distance_to(other)
        if d < best_d and d <= flight_distance(game, animal, other):
            best, best_d = other, d
    return best


def _alarming(animal, other) -> bool:
    """Whether *other* is the sort of thing *animal* runs from.

    People and predators. A deer does not bolt from another deer, and vermin
    run from anything at all that is bigger than they are.
    """
    if other.is_player or other.defn.intelligent:
        return True
    if is_vermin(animal):
        return other.defn.size > animal.defn.size
    return is_ambusher(other) or other.defn.has("SAVAGE")


def start_flight(animal, from_who) -> None:
    """Set an animal running from something."""
    ai = getattr(animal, "ai", None)
    if ai is None:
        return
    ai.mode = "flee"
    ai.target_id = from_who.id
    ai.last_seen = (from_who.x, from_who.y, from_who.z)
    animal.fleeing = FLIGHT_TURNS


def still_fleeing(animal) -> bool:
    """Whether an animal is still running from something."""
    left = getattr(animal, "fleeing", 0)
    if left <= 0:
        return False
    animal.fleeing = left - 1
    return True


# --------------------------------------------------------------------------- #
# Lying in wait
# --------------------------------------------------------------------------- #


def waiting(game, hunter, prey) -> bool:
    """Whether an ambusher should hold still rather than close.

    It waits while it is still hidden and the prey is out of reach. Once it
    has been noticed there is nothing left to ambush and it hunts like
    anything else, which is what stops a wolf standing in a field for ever
    because the player is looking at it.
    """
    from . import stealth

    if not is_ambusher(hunter) or prey is None:
        return False
    if hunter.distance_to(prey) <= STRIKE_RANGE:
        return False
    if getattr(hunter, "ambush_wait", 0) >= GIVE_UP_HIDDEN:
        return False
    hunter.ambush_wait = getattr(hunter, "ambush_wait", 0) + 1
    if stealth.noticed_by(game, hunter, prey):
        # Spotted this turn, so there is nothing to spring: come on anyway.
        # Not permanent -- `noticed_by` is rolled fresh every time by design,
        # and an early unlucky roll used to set the counter straight to its
        # ceiling and kill lurking outright for the rest of the animal's life.
        return False
    return True


# --------------------------------------------------------------------------- #
# Vermin
# --------------------------------------------------------------------------- #


def steal(game, pest, rng) -> Optional[Any]:
    """A vermin next to food on the ground takes some. Returns what it took."""
    if not is_vermin(pest):
        return None
    if not rng.chance(STEAL_ODDS):
        return None
    for cell in _around(pest):
        for item in game.items_at(*cell):
            if not item.is_edible:
                continue
            game.take_item(item, *cell)
            pest.inventory.add(item)
            return item
    return None


def _around(creature) -> List[Tuple[int, int, int]]:
    """This creature's cell and the eight around it."""
    from ..engine.geometry import DIRS8

    out = [(creature.x, creature.y, creature.z)]
    out.extend((creature.x + dx, creature.y + dy, creature.z)
               for dx, dy in DIRS8)
    return out
