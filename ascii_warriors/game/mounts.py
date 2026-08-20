"""Riding: the last dead skill in the table, and the flags that go with it.

`rider` has been in the skill list since the skill list was written and no
line of code has ever read it -- the last of the four the audit started with,
after stealth, books and the artistic skills. `MOUNT` has been on the horse,
the donkey, the mule and the camel since the creature data was written, and
`TRAINABLE` on ten creatures besides. Horses were a thing you could kill.

**A ridden mount comes off the map.** While you are on it, it is held on the
player rather than standing in `game.creatures`, exactly the way
`travelling_companions` holds a follower between world tiles. The alternative
-- two creatures on two cells that have to move as one -- is a whole class of
bugs about which of them is where, who gets attacked, what happens when the
path is one tile wide, and what the scheduler thinks it is doing. Coming off
the map costs one thing, which is that the mount cannot be attacked out from
under you; being unseated by a solid hit is the cost that replaces it, and it
is a better mechanic than the one it stands in for.

**Riding is a skill and falling off is how you learn it.** Every hit you take
while mounted is a `rider` roll. Fail it and you are on the ground, winded,
next to something that is still swinging. A legendary rider effectively never
falls; somebody who has never been on a horse falls off most of the time, and
the difference between them is the entire reason the skill exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Which skill keeps you on, and which one gets an animal to accept you.
SKILL = "rider"

#: How much of the mount's speed you actually get. A rider is not cargo; they
#: are steering, and steering is slower than the animal running loose.
SPEED_SHARE = 0.85

#: How far a mount lets you see over a crowd or a hedge.
SIGHT_BONUS = 2

#: What the mount will carry for you, as a multiplier on your own capacity.
#: A pack animal is the difference between a trip and an expedition.
CARRY_SHARE = 1.6

#: Overland travel with a mount under you, as a multiplier on the time a
#: world tile costs. This is the number a horse is actually for.
TRAVEL_FACTOR = 0.62

#: Staying on. The roll is `rider` against the size of the hit, and these are
#: the two ends of it: untrained and badly hit, and legendary and barely.
SEAT_BASE = 0.30
SEAT_PER_LEVEL = 0.055
SEAT_MAX = 0.97

#: Momentum above which a hit threatens your seat at all. A scratch does not
#: put anybody on the ground.
UNSEAT_THRESHOLD = 8000

#: Falling off hurts, in fatigue and in a moment of not acting.
FALL_FATIGUE = 120

#: Taming. Odds are the rider skill against how much the animal minds.
TAME_BASE = 0.12
TAME_PER_LEVEL = 0.07
TAME_MAX = 0.9

#: How much a wild animal minds, against one that grew up around people.
WILD_PENALTY = 0.35


def is_mount(creature) -> bool:
    """Whether this creature can be ridden."""
    defn = getattr(creature, "defn", None)
    return bool(defn is not None and defn.has("MOUNT"))


def is_trainable(creature) -> bool:
    """Whether this creature can be brought round to a person at all."""
    defn = getattr(creature, "defn", None)
    if defn is None or not defn.has("TRAINABLE"):
        return False
    return not defn.intelligent          # people are not tamed


def riding(game) -> Optional[Any]:
    """The mount the player is on, or None."""
    return getattr(game.player, "mount", None)


def mounted(game) -> bool:
    """Whether the player is on something."""
    return riding(game) is not None


# --------------------------------------------------------------------------- #
# Getting on and off
# --------------------------------------------------------------------------- #


def can_ride(game, animal) -> Tuple[bool, str]:
    """Whether the player could get on this animal right now."""
    if animal is None:
        return (False, "There is nothing here to ride.")
    if not is_mount(animal):
        return (False, "%s is not something you ride."
                % animal.short_name().capitalize())
    if not animal.alive:
        return (False, "It is dead.")
    if animal.is_hostile_to(game.player):
        return (False, "It will not let you near it.")
    if not getattr(animal, "tame", False):
        return (False, "It is not yours to ride. Tame it first.")
    if mounted(game):
        return (False, "You are already mounted.")
    return (True, "")


def ride(game, animal) -> Tuple[bool, str]:
    """Get on. The mount leaves the map and rides on the player."""
    ok, why = can_ride(game, animal)
    if not ok:
        return (False, why)
    game.remove_creature(animal)
    game.player.mount = animal
    game.player.add_exp(SKILL, 20)
    return (True, "You mount %s." % animal.object_name())


def dismount(game, *, thrown: bool = False) -> Tuple[bool, str]:
    """Get off, or come off. The mount goes back on the map beside you."""
    animal = riding(game)
    if animal is None:
        return (False, "You are not riding anything.")
    p = game.player
    game.player.mount = None
    spot = _free_spot(game, p)
    animal.x, animal.y, animal.z = spot
    animal.wx, animal.wy = p.wx, p.wy
    game.add_creature(animal)
    if thrown:
        p.needs.exert(FALL_FATIGUE)
        return (True, "You are thrown from %s!" % animal.object_name())
    return (True, "You dismount.")


def _free_spot(game, player) -> Tuple[int, int, int]:
    """Somewhere beside the player to put a mount down."""
    from ..engine.geometry import DIRS8

    for dx, dy in DIRS8:
        cell = (player.x + dx, player.y + dy, player.z)
        if game.is_passable(*cell) and game.creature_at(*cell) is None:
            return cell
    return (player.x, player.y, player.z)


# --------------------------------------------------------------------------- #
# Staying on
# --------------------------------------------------------------------------- #


def seat_chance(rider) -> float:
    """How likely this rider is to stay on through a solid hit."""
    level = max(0, rider.skills.level(SKILL))
    return min(SEAT_MAX, SEAT_BASE + level * SEAT_PER_LEVEL)


def on_hit(game, momentum: int, rng) -> Optional[str]:
    """A blow has landed on a mounted player. Returns a line if they came off.

    Called from the same place in `melee_attack` that already knows how hard
    the hit was, because "hard enough to unseat" is a question about momentum
    and nothing else knows it.
    """
    if not mounted(game) or momentum < UNSEAT_THRESHOLD:
        return None
    p = game.player
    if rng.chance(seat_chance(p)):
        p.add_exp(SKILL, 25)
        return None
    _ok, said = dismount(game, thrown=True)
    return said


def speed_of(game) -> Optional[int]:
    """The speed the player moves at while mounted, or None on foot."""
    animal = riding(game)
    if animal is None:
        return None
    return max(10, int(animal.defn.speed * SPEED_SHARE))


def travel_factor(game) -> float:
    """What a mount does to the time an overland tile costs."""
    return TRAVEL_FACTOR if mounted(game) else 1.0


def carry_bonus(game) -> float:
    """Extra carrying capacity from whatever is under you."""
    return CARRY_SHARE if mounted(game) else 1.0


# --------------------------------------------------------------------------- #
# Taming
# --------------------------------------------------------------------------- #


def tame_chance(tamer, animal) -> float:
    """How likely this person is to bring this animal round."""
    if not is_trainable(animal):
        return 0.0
    level = max(0, tamer.skills.level(SKILL))
    odds = TAME_BASE + level * TAME_PER_LEVEL
    if animal.faction in ("wild", "wild_hostile"):
        odds -= WILD_PENALTY
    return max(0.0, min(TAME_MAX, odds))


def tame(game, animal, rng) -> Tuple[bool, str]:
    """Try to win an animal over. It takes as long as it takes.

    A failure is not a refusal for ever -- it is one attempt that did not
    work, and the animal is more wary for it, which is what stops this being
    a button you hold down until the horse is yours.
    """
    if animal is None or not is_trainable(animal):
        return (False, "That is not an animal you can tame.")
    if getattr(animal, "tame", False):
        return (False, "%s is already yours." % animal.subject_name())
    if not animal.alive:
        return (False, "It is dead.")

    p = game.player
    p.add_exp(SKILL, 30)
    odds = tame_chance(p, animal) - 0.06 * getattr(animal, "tame_tries", 0)
    animal.tame_tries = getattr(animal, "tame_tries", 0) + 1
    if not rng.chance(max(0.02, odds)):
        return (False, "%s shies away from you." % animal.subject_name())

    animal.tame = True
    animal.faction = "player"
    if animal.ai is not None:
        animal.ai.leader_id = p.id
        animal.ai.role = "pet"
    p.add_exp(SKILL, 60)
    return (True, "%s will follow you now." % animal.subject_name())


def tamed_of(game) -> List[Any]:
    """Every animal the player has tamed and that is still on this map."""
    return [c for c in game.creatures.values()
            if getattr(c, "tame", False) and c.alive]


def status(game) -> str:
    """One line for the status bar."""
    animal = riding(game)
    if animal is None:
        return ""
    return "riding %s" % animal.short_name()

