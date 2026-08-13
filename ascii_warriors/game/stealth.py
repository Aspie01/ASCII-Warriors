"""Moving unseen, and what happens the moment you are not.

The game has had a rogue class since the beginning -- dagger 4, sneak 5,
dodging 4, observer 3 -- and sneaking did nothing at all. `sneak` and
`ambusher` were handed out to kobolds, bandits, wolves and the thief that
robs your fortress, and no line of code ever read either of them. A roguelike
without stealth is missing a whole way of playing, and the numbers to build it
with were already sitting in the save file.

The model is one roll, made per watcher rather than globally, because being
hidden is not a property of a creature -- it is a fact about a *pair*. The
guard by the fire has not seen you; the one on the wall has. `noticed_by`
answers that question and everything else is built on it: hostiles do not
chase what they have not noticed, and an attack on somebody who has not
noticed you is an ambush.

Three things move the roll, and each of them is a decision the player already
makes for other reasons:

- **Light.** The torch that lets you see the corridor is the thing that gives
  you away. Underground with no light you are nearly invisible and nearly
  blind, which is the trade the torch system has always implied and never
  charged for.
- **Distance.** Far away is most of hiding.
- **What you just did.** Standing still is quiet, walking is not, and
  attacking is not stealth at all.
"""

from __future__ import annotations

from typing import Any, Optional

from ..engine import geometry
from ..engine.fov import has_los

#: How much of the roll each side brings before anything modifies it.
SKILL_WEIGHT = 6.0

#: Where an unskilled creature starts. Sneaking has to be a *skill*: without
#: this the curve is centred on zero, which hands somebody who has never
#: sneaked in their life even odds of standing next to a bandit unnoticed.
UNTRAINED = -40.0

#: How sharply the odds swing around that. Smaller is steeper.
CURVE = 12.0

#: Odds floor and ceiling. Nothing is ever certain in either direction: a
#: legendary sneak can be unlucky and a blind guard can turn round.
MIN_CHANCE = 0.03
MAX_CHANCE = 0.97

#: Carrying a burning torch. It is not that you are easy to see; it is that
#: you are the only thing anybody is looking at.
TORCH_PENALTY = 14.0

#: What you were doing when they looked.
NOISE = {"still": -3.0, "move": 2.0, "run": 8.0, "fight": 24.0, "open": 6.0}

#: Distance is most of hiding: this much help per tile between you.
DISTANCE_HELP = 0.9

#: Being asleep, unconscious or stunned is not watching.
ASLEEP_HELP = 40.0

#: Behind something. Cover is worth about as much as a rank of sneaking.
COVER_HELP = 5.0

#: What an unnoticed attacker gets. Multiplied into the strike, so a dagger
#: in the dark is a different weapon from a dagger in a fair fight.
AMBUSH_MOMENTUM = 2.4

#: And it lands where it is aimed.
AMBUSH_PARTS = ("neck", "throat", "head", "upper_body")


def is_sneaking(creature) -> bool:
    """Whether this creature is currently trying not to be seen."""
    return bool(getattr(creature, "sneaking", False))


def set_sneaking(creature, on: bool) -> bool:
    """Start or stop sneaking. Returns the new state."""
    creature.sneaking = bool(on)
    if on:
        creature.noise = "still"
    return creature.sneaking


def natural_sneak(creature) -> bool:
    """Creatures that move quietly whether or not anybody told them to.

    A kobold thief does not need the player to press a key, and neither does
    an ambusher lying in the scrub. This is what makes the skills the data
    files have always handed out mean something.

    Never the player. A skilled character that hides without being asked is a
    character the status bar is lying about, and it takes the decision -- the
    one thing stealth is actually made of -- away from the person playing.
    """
    if creature.is_player:
        return False
    return creature.skills.level("ambusher") >= 3 \
        or creature.skills.level("sneak") >= 5


def hidden(creature) -> bool:
    """Whether this creature is playing the hiding game at all."""
    return is_sneaking(creature) or natural_sneak(creature)


def note_action(creature, kind: str) -> None:
    """Record what a creature just did, for the next watcher who looks."""
    creature.noise = kind if kind in NOISE else "move"
    if kind == "fight":
        # You cannot stab somebody quietly enough to stay hidden from them.
        creature.sneaking = False


# --------------------------------------------------------------------------- #
# The roll
# --------------------------------------------------------------------------- #


def hide_chance(world, sneaker, watcher) -> float:
    """The odds that *watcher* fails to notice *sneaker* right now.

    Zero when the sneaker is not hiding at all, so a creature standing in the
    open is always seen and never pays for a roll.
    """
    if not hidden(sneaker) or sneaker is watcher:
        return 0.0
    if watcher.body.dead:
        return 1.0

    score = UNTRAINED
    score += SKILL_WEIGHT * (sneaker.skills.level("sneak")
                             + sneaker.skills.level("ambusher") * 0.5)
    score -= SKILL_WEIGHT * watcher.skills.level("observer")
    score += sneaker.attributes.factor("agility") * 8.0 - 8.0
    score -= watcher.attributes.factor("intuition") * 8.0 - 8.0

    dist = geometry.chebyshev(sneaker.x, sneaker.y, watcher.x, watcher.y)
    score += dist * DISTANCE_HELP
    score += NOISE.get(getattr(sneaker, "noise", "move"), 2.0) * -1.0

    if not watcher.body.can_see() or watcher.body.unconscious > 0 \
            or watcher.body.stunned > 0:
        score += ASLEEP_HELP
    elif getattr(watcher, "ai", None) is not None \
            and watcher.ai.mode == "sleep":
        score += ASLEEP_HELP

    light = world.light_at(sneaker.x, sneaker.y, sneaker.z)
    # Full dark is worth about three ranks of sneaking; full daylight costs it.
    score += (0.5 - light) * 36.0
    if _carrying_light(sneaker):
        score -= TORCH_PENALTY
    if _has_cover(world, sneaker, watcher):
        score += COVER_HELP

    # A logistic curve rather than a clamp, so every point of skill is worth
    # something and no amount of it is ever a guarantee.
    return max(MIN_CHANCE,
               min(MAX_CHANCE, 1.0 / (1.0 + pow(2.71828, -score / CURVE))))


def _carrying_light(creature) -> bool:
    """Whether this creature is holding something burning."""
    for it in creature.inventory.items:
        if it.is_light and it.flags.get("lit") and it.charges > 0:
            return True
    return False


def _has_cover(world, sneaker, watcher) -> bool:
    """Whether anything stands between the two of them.

    Not a wall -- a wall is handled by line of sight and means the watcher
    cannot see at all. This is the diagonal glance past a pillar.
    """
    local = getattr(world, "local", None)
    if local is None:
        return False
    z = sneaker.z
    return not has_los(
        watcher.x, watcher.y, sneaker.x, sneaker.y,
        lambda x, y: local.blocks_sight(x, y, z),
    )


def noticed_by(world, sneaker, watcher) -> bool:
    """Whether this watcher has spotted this sneaker.

    Rolled fresh each time rather than stored, because it is a fact about a
    pair and a moment: step into the light and the same guard that missed you
    a second ago sees you.
    """
    chance = hide_chance(world, sneaker, watcher)
    if chance <= 0.0:
        return True
    return not world.rng.chance(chance)


def unnoticed(world, attacker, defender) -> bool:
    """Whether an attack on *defender* would come out of nowhere."""
    return hidden(attacker) and not noticed_by(world, attacker, defender)


# --------------------------------------------------------------------------- #
# Ambush
# --------------------------------------------------------------------------- #


def ambush_part(defender, rng) -> Optional[str]:
    """Where an unnoticed attacker puts it, if that part is there to hit."""
    for name in AMBUSH_PARTS:
        part = defender.body.part(name)
        if part is not None and not part.gone:
            return part.id
    return None


def on_ambush(world, attacker, defender) -> None:
    """Bookkeeping after a strike from hiding.

    The attack itself gives you away, which is the whole balance of it: one
    devastating blow, and then an ordinary fight against somebody who now
    knows exactly where you are.
    """
    note_action(attacker, "fight")
    attacker.add_exp("ambusher", 40)
    attacker.add_exp("sneak", 10)
