"""Nerve: whether a creature still wants to be in this fight.

`combat.opportunity_to_flee` has decided that since there was combat, out of
health, `bravery` and `NO_FEAR` -- and it asks about one creature, alone in
the world. Meanwhile `ai.allies_near` has been sitting in the AI module the
whole time, complete and correct and **called by nothing**, and `PACK` is read
once at spawn to decide how many wolves to put on the map and never looked at
again. So seven wolves arrive together and then fight as seven separate
animals, not one of which notices when the other six are dead.

**Nerve is what the company around you is worth.** Numbers steady a creature,
being the last one standing does not, and something that expects a pack takes
being alone much harder than something that never had one. Watching an ally go
down is a shock that wears off, so a hard fight grinds a side down rather than
flipping it: the third death is what breaks a line, not the first.

The two modes had opposite halves of this. Adventure mode had individual fear
and no idea of a group; the fortress had `war.py`, which routs a whole army on
its losses and gives the individuals in it no say at all. Both ask `broke`
now, and an invader in a routed army knows the army has routed.
"""

from __future__ import annotations

from typing import Any, List, Optional

#: How far a creature looks for company. Shorter than sight: somebody across
#: the field is not standing with you.
COMPANY_RANGE = 7

#: What each ally in reach is worth, and how many are worth counting. Past a
#: handful, more bodies stop being reassurance and start being a crowd.
ALLY_NERVE = 0.13
MAX_COMPANY = 5

#: What being alone costs something built to hunt in a pack. A lone wolf is
#: not a wolf that is winning.
PACK_ALONE = 0.45

#: What seeing somebody on your side go down does, and how long the shock
#: takes to wear off.
DEATH_SHOCK = 0.30
STEADY_EXP = 1

SHOCK_DECAY_TICKS = 1200

#: The most shock a creature can be carrying. Without a cap a massacre makes
#: a number that never comes back.
MAX_SHOCK = 1.2

#: Where nerve gives out.
BREAK_AT = 0.35

#: What is left of a creature's nerve when its body is entirely gone.
#:
#: This was 0.35 and written into the expression, which made it the same
#: number as `BREAK_AT` -- so nerve bottomed out at `bravery * 0.35`, and
#: anything with a bravery factor of 1.0 or better could not break however
#: badly it was hurt. The median goblin rolls 1.14. Measured over eight
#: adventurer lifetimes: 1908 creature-turns of facing the player and the only
#: thing that ever broke off was the goblin snatcher, which is a thief and was
#: always going to run. A wolf got to 0.39 and a bandit to 0.42.
HURT_FLOOR = 0.05

#: What emptying a creature out is worth, as nerve subtracted at no blood
#: left.
#:
#: §135 left this: blood loss does nothing in this game but kill you. It does
#: not slow you (§133), it does not weaken you, and until now it did not
#: frighten you either -- a creature at a third of its blood fought exactly as
#: hard as one at full. `health_fraction` is structure, which is a different
#: question: a body opened up in twenty places and still standing is intact
#: and nearly empty at the same time.
BLED_NERVE = 0.5


def fearless(creature) -> bool:
    """Whether fear is somebody else's problem."""
    defn = getattr(creature, "defn", None)
    if defn is None:
        return True
    return bool(defn.has("NO_FEAR") or defn.has("UNDEAD")
                or defn.has("MEGABEAST") or defn.has("OPPOSED_TO_LIFE"))


def company(creature, game) -> List[Any]:
    """Whoever is standing with this creature.

    `ai.allies_near` written out at last -- the radius is this module's
    business rather than the AI's, so it passes its own.
    """
    from . import ai as ai_mod

    return ai_mod.allies_near(creature, game, radius=COMPANY_RANGE)


def nerve(creature, game) -> float:
    """How much fight is left in a creature. 1.0 is fresh, `BREAK_AT` is gone.

    Health and temperament are what it always was; the company and the losses
    came with v3.49; the blood and a floor low enough to reach came with §136.

    A fresh creature sits at its bravery factor, so nothing here changes what
    walks up to you -- only what walks away.
    """
    if fearless(creature):
        return 1.0
    body = creature.body
    left = creature.personality.bravery_factor()
    left *= HURT_FLOOR + (1.0 - HURT_FLOOR) * body.health_fraction()
    friends = min(MAX_COMPANY, len(company(creature, game)))
    left += ALLY_NERVE * friends
    if not friends and creature.defn.has("PACK"):
        left -= PACK_ALONE
    if body.max_blood > 0:
        left -= BLED_NERVE * (1.0 - body.blood_fraction())
    return left - getattr(creature, "shaken", 0.0)


def broke(creature, game) -> bool:
    """Whether this creature has had enough."""
    if fearless(creature):
        return False
    return nerve(creature, game) < BREAK_AT


def saw_death(game, victim) -> None:
    """Shake everyone on the dead creature's side who was near enough to see.

    Called from the one place a creature dies in each mode, so there is no
    second way for a death to go unnoticed.
    """
    if victim is None or game is None:
        return
    for other in list(getattr(game, "creatures", {}).values()):
        if other is victim or other.body.dead or fearless(other):
            continue
        if other.faction != victim.faction or other.z != victim.z:
            continue
        if other.distance_to(victim) > COMPANY_RANGE:
            continue
        shock = DEATH_SHOCK
        if other.defn.has("PACK"):
            # It came here with them.
            shock *= 1.5
        shake(other, shock)


def shake(creature, amount: float) -> None:
    """Put a fright into somebody."""
    creature.shaken = min(MAX_SHOCK,
                          getattr(creature, "shaken", 0.0) + amount)


def steady(creature, ticks: int) -> None:
    """Let the shock wear off.

    And teach `discipline` for having stood there while it did. The skill is
    described as keeping your head when things go badly, which is precisely
    this: somebody who has seen a friend go down and has not run is learning
    something that nothing else in the game teaches.
    """
    have = getattr(creature, "shaken", 0.0)
    if not have:
        return
    creature.add_exp("discipline", STEADY_EXP)
    creature.shaken = max(0.0, have - ticks / float(SHOCK_DECAY_TICKS))


def describe(creature, game) -> str:
    """A word for how somebody is holding up, or ``""``."""
    if fearless(creature):
        return ""
    left = nerve(creature, game)
    if left < BREAK_AT:
        return "breaking"
    if left < BREAK_AT + 0.25:
        return "wavering"
    return ""
