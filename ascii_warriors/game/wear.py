"""Wear: the reason a fortress needs a clothier for ever.

`Item.wear_tick` has been on the item class since there were items: a per-call
chance, a lower one for metal, an exemption for artifacts, and a ``True``
return meaning the thing has finally come apart. It was called from exactly
one place -- a weapon that lands a blow -- and **the return value was thrown
away**, which is the whole of the problem.

Nothing was ever destroyed by use, so `wear` had no ceiling. It is clamped to
0..3 in the constructor and incremented without one, so a weapon that has
landed enough blows walks past the end of the scale: `wear_factor` is
``1 - 0.15 * wear``, which reaches zero at 6 and goes **negative** at 7, and
`compute_momentum` multiplies by it. A well-used sword quietly becomes worse
than a bare fist, and the examine screen cannot say so because the condition
names run out at "XX". Armour and clothing were never asked at all -- armour
that has turned a hundred blows was as good as the day it was forged, and
v3.18 dressed every dwarf in clothes that would outlast the mountain.

**Wear is what use costs.** A weapon wears when it lands a blow, armour wears
when it stops one, and clothing wears by being worn. The odds live on the item
and are deliberately small; what this module decides is how often to ask, and
the answer is calibrated so a sword outlasts a war and a shirt does not
outlast a year. The `sharpen_weapon` recipe -- which took a whetstone and
handed back a whetstone, because there was never anything blunt to put an edge
on -- finally has something to do.

**One funnel.** Everything that removes a worn-out item goes through
`destroy`, because an item that is gone from a creature's hands but still in
its pack -- or still equipped, or still counted by the stockpile -- is the
shape of bug this project keeps finding, and four call sites were how it kept
happening.
"""

from __future__ import annotations

from typing import Any, List, Optional

from ..data.calendar import TICKS_PER_DAY

#: How often clothing is asked whether it has worn out: once a day. `wear_tick`
#: gives cloth about one chance in eighty and `MAX_WEAR` is three, so four
#: hits finish a garment and it lasts something over a year of wearing -- long
#: enough that replacing it is an industry rather than a chore, short enough
#: that a fortress cannot ignore it for ever. From the calendar, so the "year"
#: in that sentence stays checkable: see `HAUNT_AFTER`.
CLOTH_TICKS = TICKS_PER_DAY

#: What a whetstone gives back, and how sure it is. Sharpening is a repair,
#: not a restoration: it takes the edge back a step, and a badly enough abused
#: blade never comes all the way home.
SHARPEN_ODDS = 0.75

#: What losing the clothes off your back is worth as a thought. v3.15 scales
#: it by who it happened to.
RAGS_THOUGHT = 6


def is_clothing(item) -> bool:
    """Whether an item is worn rather than fought in."""
    return getattr(item.defn, "category", "") == "clothing"


def destroy(owner, item, *, log=None, world=None) -> None:
    """Take a worn-out item out of the world.

    The one place anything worn out is removed. An item unequipped but still
    in the pack, or gone from the pack but still on the body, is a bug that
    only shows up much later and looks like something else entirely.
    """
    inv = getattr(owner, "inventory", None)
    if inv is not None:
        inv.unequip_item(item)
        if item in inv.items:
            inv.items.remove(item)
    if world is not None:
        pile = getattr(world, "items_on_ground", None)
        if isinstance(pile, dict):
            for cell, items in list(pile.items()):
                if item in items:
                    items.remove(item)
                    if not items:
                        pile.pop(cell, None)
    if log is not None:
        who = "Your" if getattr(owner, "is_player", False) else (
            "%s's" % owner.name)
        log.warn("%s %s has fallen apart." % (who, item.defn.name))
    needs = getattr(owner, "needs", None)
    if needs is not None and is_clothing(item):
        needs.add_thought("was left in rags", RAGS_THOUGHT)


def _use(owner, item, rng, *, log=None, world=None) -> bool:
    """Ask one item whether this use finished it. True if it is gone."""
    if item is None or not item.wear_tick(rng):
        return False
    destroy(owner, item, log=log, world=world)
    return True


def strike(attacker, weapon, rng, *, log=None) -> bool:
    """A weapon has landed a blow."""
    return _use(attacker, weapon, rng, log=log)


def absorb(defender, piece, rng, *, log=None) -> bool:
    """A piece of armour has stopped one."""
    return _use(defender, piece, rng, log=log)


def wearing(creature, rng, *, log=None) -> List[str]:
    """One clothing-wear check on everything a creature has on.

    Called on a cadence rather than every tick: see `CLOTH_TICKS`. Armour is
    not included -- it wears from being hit, which is a different clock and
    already has one.
    """
    inv = getattr(creature, "inventory", None)
    if inv is None:
        return []
    gone: List[str] = []
    for item in [i for i in inv.equipped.values() if i is not None]:
        if not is_clothing(item):
            continue
        name = item.defn.name
        if _use(creature, item, rng, log=log):
            gone.append(name)
    return gone


def due(creature, now: int) -> bool:
    """Whether this creature's clothes are due a look."""
    return now >= getattr(creature, "next_wear_check", 0)


def mark(creature, now: int) -> None:
    """Record that they have just had one."""
    creature.next_wear_check = now + CLOTH_TICKS


def dressed(creature) -> bool:
    """Whether a creature has anything on at all."""
    inv = getattr(creature, "inventory", None)
    if inv is None:
        return True
    return any(is_clothing(i) for i in inv.equipped.values() if i is not None)


# --------------------------------------------------------------------------- #
# Putting an edge back on
# --------------------------------------------------------------------------- #


def whetstone_of(creature):
    """A whetstone in this creature's pack, if it has one."""
    inv = getattr(creature, "inventory", None)
    if inv is None:
        return None
    for item in inv.items:
        if item.def_id == "whetstone":
            return item
    return None


def can_sharpen(item) -> bool:
    """Whether a whetstone is any use on this.

    An edge is something you can put back. A maul is not blunt, it is a maul,
    and no amount of stone will improve it.
    """
    if item is None or item.defn.weapon is None or item.wear <= 0:
        return False
    return any(a.is_edged for a in item.defn.weapon.attacks)


def sharpen(creature, weapon, rng, *, log=None) -> str:
    """Work a whetstone over a blade. Returns what to tell the player."""
    if whetstone_of(creature) is None:
        return "You have no whetstone."
    if weapon is None:
        return "You are not holding anything to sharpen."
    if weapon.defn.weapon is None or not any(
            a.is_edged for a in weapon.defn.weapon.attacks):
        return "There is no edge on that to put back."
    if weapon.wear <= 0:
        return "It is already as sharp as it will get."
    creature.add_exp("weaponsmithing", 8)
    if not rng.chance(SHARPEN_ODDS):
        return "You work at it, and it is no better than it was."
    weapon.wear -= 1
    return "You put an edge back on %s." % weapon.name(article=True)
