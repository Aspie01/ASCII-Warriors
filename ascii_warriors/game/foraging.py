"""Living off the land: what an adventurer can take from it.

Two gaps, both of them whole chains missing one link.

**Fishing.** The `fishing` skill is in the skill table. The `fishing` labor is
in the fortress labor list and the hunter profession carries it. `fishing_rod`
is in the item table. `fish_food` is in the item table, in the fortress
larder, in the stockpile categories and on the sidebar's food list. `cook_fish`
is in the crafting table. Carp and pike swim in the bestiary, on a `fish` body
plan written for them. **Nobody, in either mode, has ever caught a fish.**

**Gathering.** The fortress has herbalism wired end to end -- a dwarf gathers
plants, plants seeds and harvests them, and gets better at it. An adventurer
standing on the same shrub could do nothing at all. v3.23 gave the wilderness
animals that eat; this is the half where you can too.

Both are slow, and that is the point: an afternoon spent fishing is an
afternoon not spent walking, which is the trade a survival mechanic is for.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ..data.calendar import TICKS_PER_HOUR
from ..engine.geometry import DIRS8
from ..world import tiles as tile_data

Cell = Tuple[int, int, int]

#: What a shrub gives up, and the skill that decides how much.
GATHER_BASE = 2
GATHER_PER_LEVEL = 0.4
GATHER_MAX = 9

#: What is growing where. A shrub is worth picking; grass is worth searching
#: and mostly is not.
SHRUB_YIELD = ("berries", "plump_helmet", "cave_wheat")
GRASS_ODDS = 0.25

#: How long each takes. Long enough to be a decision.
GATHER_TURNS = TICKS_PER_HOUR // 2
FISH_TURNS = TICKS_PER_HOUR * 2

#: What a cast is worth, before skill.
FISH_BASE = 0.22
FISH_PER_LEVEL = 0.05
FISH_MAX = 0.85

#: How many fish one good cast is.
FISH_YIELD = (1, 3)


# --------------------------------------------------------------------------- #
# Gathering
# --------------------------------------------------------------------------- #


def gatherable(game, cell: Cell) -> str:
    """What could be picked here: ``"shrub"``, ``"grass"`` or ``""``."""
    lm = getattr(game, "local", None)
    if lm is None or not lm.in_bounds(*cell):
        return ""
    tile = lm.tile(*cell)
    if tile in ("shrub", "sapling"):
        return "shrub"
    if tile_data.get(tile).has("GRASS"):
        return "grass"
    return ""


def gather_spot(game, creature) -> Optional[Cell]:
    """The best thing within reach to pick, underfoot first."""
    here = (creature.x, creature.y, creature.z)
    best = None
    for dx, dy in ((0, 0),) + tuple(DIRS8):
        cell = (here[0] + dx, here[1] + dy, here[2])
        kind = gatherable(game, cell)
        if kind == "shrub":
            return cell
        if kind == "grass" and best is None:
            best = cell
    return best


def gather(game, creature, rng) -> Tuple[List[Tuple[str, int]], str]:
    """Pick what is growing here.

    Returns ``([(item id, count)], message)`` rather than the items
    themselves, because they are in the pack by then and may have been merged
    into a stack that was already there.
    """
    from .item import Item

    cell = gather_spot(game, creature)
    if cell is None:
        return ([], "There is nothing growing here to pick.")
    kind = gatherable(game, cell)
    skill = creature.skills.level("herbalism")
    creature.add_exp("herbalism", 12 if kind == "shrub" else 6)

    if kind == "grass":
        # Mostly there is nothing in it. That is what makes a shrub worth
        # walking to.
        if not rng.chance(GRASS_ODDS + skill * 0.02):
            return ([], "You search the grass and find nothing worth taking.")
        count = 1
    else:
        count = min(GATHER_MAX,
                    GATHER_BASE + int(skill * GATHER_PER_LEVEL) + rng.randint(0, 2))
        game.local.set_tile(cell[0], cell[1], cell[2], "grass")

    what = rng.choice(SHRUB_YIELD) if kind == "shrub" else "berries"
    item = Item(what, "plant", count=count)
    # Named before it goes in the pack: `Inventory.add` merges the stack into
    # one already carried and leaves this one holding nothing, so reading the
    # count afterwards reports a handful of berries as none at all.
    said = "You gather %s." % item.name(article=True)
    creature.inventory.add(item)
    return ([(what, count)], said)


# --------------------------------------------------------------------------- #
# Fishing
# --------------------------------------------------------------------------- #


def has_rod(creature) -> bool:
    """Whether this creature is carrying the thing the item table has always
    had and nothing has ever asked for."""
    inv = getattr(creature, "inventory", None)
    return bool(inv is not None and inv.by_def("fishing_rod"))


def water_beside(game, creature) -> Optional[Cell]:
    """Open water next to this creature, if there is any."""
    lm = getattr(game, "local", None)
    if lm is None:
        return None
    here = (creature.x, creature.y, creature.z)
    for dx, dy in ((0, 0),) + tuple(DIRS8):
        cell = (here[0] + dx, here[1] + dy, here[2])
        if not lm.in_bounds(*cell):
            continue
        if tile_data.get(lm.tile(*cell)).has("WATER"):
            return cell
    return None


def fish_chance(creature) -> float:
    """How likely a cast is to come back with something."""
    skill = creature.skills.level("fishing")
    return min(FISH_MAX, FISH_BASE + FISH_PER_LEVEL * skill)


def fish(game, creature, rng) -> Tuple[List[Tuple[str, int]], str]:
    """Spend a while at the water's edge. Returns ``([(id, count)], message)``."""
    from .item import Item

    if not has_rod(creature):
        return ([], "You have no fishing rod.")
    if water_beside(game, creature) is None:
        return ([], "There is no water here to fish in.")
    creature.add_exp("fishing", 25)
    if not rng.chance(fish_chance(creature)):
        return ([], "You fish for a while and catch nothing.")
    count = rng.randint(*FISH_YIELD)
    item = Item("fish_food", "meat", count=count)
    said = "You land %s." % item.name(article=True)
    creature.inventory.add(item)
    return ([("fish_food", count)], said)
