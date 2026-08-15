"""Flight: the ten creatures in the bestiary that have never left the ground.

`FLIER` has been on ten creature definitions since the bestiary was written --
the duck, the raven, the eagle, the buzzard, the bat, the giant bat, the giant
cave swallow, the roc, the dragon and the demon -- and no line of code in the
project has ever read it. Nine of the ten also carry a pair of wings in their
body plan, modelled down to the tissue, which nothing has ever asked about
either. A raven walked. A dragon walked. Everything that could fly was
pathfinding around lakes and falling down holes with the cows.

Flight is mostly a set of exemptions from rules written for things with feet,
so this module is the one place that says who is exempt:

* v3.26 made everything fall. A flier does not.
* v3.29 made deep water swimmable and drownable. A flier crosses it dry.
* The `chasm` tile and any open air are walls to a walker and a road to a
  flier.

**Wings are the reason it is worth modelling rather than flagging.** A wing is
a body part with tissues, and the combat model has been able to break and sever
those since long before this. Take one off a roc and it comes down -- through
`gravity`, on to whatever is underneath, at whatever speed the drop is worth.
That is a fight you can win by aiming.
"""

from __future__ import annotations

from typing import List, Optional

#: Share of carrying capacity above which wings are not enough. A roc can
#: carry off a goat; it cannot carry off a granite block.
FLIGHT_LOAD = 0.60

#: How much of a wing has to be left to be worth beating. A part that is
#: `functional` is intact enough to work; a broken or half-severed wing is
#: not, and the body model already knows the difference.
def wings(creature) -> List:
    """Every wing on this creature, whatever condition it is in."""
    body = getattr(creature, "body", None)
    if body is None:
        return []
    return [p for p in body.parts.values() if p.defn.category == "wing"]


def has_wings(creature) -> bool:
    """Whether this creature's body plan has wings at all.

    The demon does not, and flies anyway. Whatever is carrying it is not a
    pair of wings and cannot be cut off.
    """
    return bool(wings(creature))


def wings_work(creature) -> bool:
    """Whether enough wing is left to fly on."""
    have = wings(creature)
    if not have:
        return True
    return all(w.functional() for w in have if not w.gone) and any(
        not w.gone for w in have)


def is_flier(creature) -> bool:
    """Whether this kind of creature flies at all, condition aside."""
    defn = getattr(creature, "defn", None)
    return bool(defn is not None and defn.has("FLIER"))


def can_fly(creature) -> bool:
    """Whether this creature is flying right now.

    Everything that stops a walker walking stops a flier flying, and one thing
    more: what it is carrying. The condition checks are why this is worth a
    function rather than a flag test at every call site.
    """
    if creature is None or not is_flier(creature):
        return False
    body = getattr(creature, "body", None)
    if body is None:
        return True
    if body.dead or body.unconscious > 0 or body.stunned > 0:
        return False
    if body.is_incapacitated():
        return False
    if not wings_work(creature):
        return False
    try:
        if creature.encumbrance() > FLIGHT_LOAD:
            return False
    except (AttributeError, TypeError):
        pass
    return True


def grounded_reason(creature) -> Optional[str]:
    """Why a flier is not flying, for the message log. ``None`` if it is."""
    if not is_flier(creature):
        return None
    if can_fly(creature):
        return None
    body = getattr(creature, "body", None)
    if body is None:
        return None
    if body.dead:
        return "dead"
    if not wings_work(creature):
        broken = [w for w in wings(creature) if w.gone or not w.functional()]
        if broken:
            return "%s is ruined" % broken[0].name
        return "its wings are ruined"
    if body.unconscious > 0 or body.stunned > 0:
        return "senseless"
    if body.is_incapacitated():
        return "too badly hurt"
    return "too heavily laden"
