"""What animals eat and drink, and the food chain that decides which.

Every creature without `NO_EAT` has accrued hunger and thirst since needs
existed, and `Needs.tick` kills at `THIRST_DEATH`, which is three days. **No
wild animal has ever eaten or drunk anything.** Measured on a fresh map: 46
animals, all alive on day three, and 43 of them dead of thirst on day four --
the three survivors being the undead and the megabeasts, who are exempt. Stay
anywhere for a week and the wilderness is a field of corpses with no marks on
them.

The other half of the same hole: `CreatureDef.diet` classifies all eighty
species as carnivore, herbivore or omnivore, and **nothing had ever read it**.
Everything wild shares the faction `"wild"`, and `is_hostile_to` returns
`False` for the same faction, so a wolf and a deer were on the same side. The
wilderness was one peaceable kingdom in which nothing ate anything and
everything quietly died of thirst.

**An animal that can reach what it needs takes it.** Water from a river or a
puddle, grass from the ground it is standing on, meat from whatever it has
just killed or found already dead. When the need gets bad enough it goes
looking, which is the `forage` mode; the rest of the time it is opportunistic,
because an animal standing in a stream does not need a plan.

**Size decides what is prey, and it is not a straight comparison.** A wolf is
40 litres and a deer is 100, and wolves eat deer -- so a hunter takes anything
up to `PREY_RATIO` of its own size, and a pack hunter counts the pack.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ..data.calendar import TICKS_PER_DAY
from ..world import tiles as tile_data

Cell = Tuple[int, int, int]

#: How far an animal will look for a drink or a mouthful before giving up and
#: carrying on with its day.
FORAGE_RANGE = 14

#: How thirsty or hungry before it stops doing anything else. Both clocks kill
#: well after this, so an animal has plenty of time to find something.
THIRSTY_AT = 9000
HUNGRY_AT = 20000

#: How fast a wild animal's needs run against a person's.
#:
#: `Needs` was written for somebody with a waterskin and a pack: three days to
#: die of thirst, five of hunger. Wild animals were put on the same clock and
#: given no way to answer it, which killed 43 of 46 on a map by day four.
#: Foraging is the answer to most of it, but not all -- a local map draws no
#: water unless the world tile is a river or a lake, and a bat roosting above
#: a meadow is not standing on the grass.
#:
#: So an animal's clock runs slower, and the reason is not a fudge: it is
#: foraging continuously in ways the map has no cells for. What the clock is
#: still *for* is the interesting part -- when to hunt, when to graze, and
#: when to do either with something watching.
WILD_NEED_SCALE = 0.25


def need_ticks(creature, ticks: int) -> int:
    """How much of a person's need clock this creature actually feels."""
    defn = getattr(creature, "defn", None)
    if defn is None or defn.intelligent or getattr(creature, "is_player", False):
        return ticks
    if getattr(creature, "tame", False):
        # Somebody else is feeding it. That is what a pasture is for.
        return ticks
    return max(1, int(ticks * WILD_NEED_SCALE))


#: And where it stops caring what else is out there.
#:
#: Fear used to outrank everything: `pick_mode` asks `wild.frightener` before
#: anything else, and once prey started fleeing predators -- which is the
#: point of reading `diet` -- a rabbit within sight of a fox fled until it
#: died of thirst standing on grass. Past this, it eats anyway. That is what
#: a real animal does, and it is the only thing that lets prey and predator
#: share a map.
DESPERATE_THIRST = 26000
DESPERATE_HUNGER = 45000

#: What one drink and one mouthful are worth. A full belly is the point --
#: an animal that has to eat every few steps is a chore for the scheduler
#: rather than a creature.
DRINK_VALUE = TICKS_PER_DAY * 2
GRAZE_VALUE = TICKS_PER_DAY // 2
MEAT_VALUE = TICKS_PER_DAY * 3

#: What eating is worth against thirst.
#:
#: A local map has no water on it unless the world tile is a river or a lake:
#: a temperate forest generates 1,647 cells of grass and **zero** cells of
#: water. An animal that could only drink from terrain could not drink at all
#: in most of the world, and the three-day thirst clock -- a human clock,
#: written for somebody carrying a waterskin -- killed everything on the map.
#:
#: Grass and meat are mostly water, which is how a great many real animals get
#: most of theirs, and it is the honest model at a resolution that does not
#: draw puddles. Standing water is still better and still worth walking to.
WATER_FROM_FOOD = TICKS_PER_DAY

#: The most an animal may take of something larger than itself, as a multiple
#: of its own size. A wolf is smaller than the deer it eats.
PREY_RATIO = 3.0

#: What each packmate adds to what a hunter will take on.
#:
#: Sized against the bestiary rather than guessed: a wolf is 40 litres and
#: reaches three times that alone, which covers a goat, a sheep and a deer and
#: stops short of an elk at 300. At 0.9 a packmate the number was decoration
#: -- nothing in the table sits between a lone wolf's reach and a pack of
#: four's. Three wolves bring down an elk, which is the thing a pack is for.
PACK_REACH = 1.6

#: And the floor: nothing hunts something its own size or bigger for sport.
#: Vermin are beneath notice rather than prey.
PREY_FLOOR = 0.02


def eats_meat(creature) -> bool:
    """Whether this creature hunts. `diet`, read at last."""
    defn = getattr(creature, "defn", None)
    return bool(defn is not None and defn.diet in ("carnivore", "omnivore"))


def eats_plants(creature) -> bool:
    """Whether grass is food to it."""
    defn = getattr(creature, "defn", None)
    return bool(defn is not None and defn.diet in ("herbivore", "omnivore"))


def needs_nothing(creature) -> bool:
    """Whether feeding is somebody else's problem."""
    defn = getattr(creature, "defn", None)
    if defn is None:
        return True
    return bool(defn.has("NO_EAT") and defn.has("NO_DRINK"))


def is_prey(hunter, target, *, pack: int = 0) -> bool:
    """Whether *hunter* would treat *target* as a meal.

    Not a straight size comparison: a wolf is 40 litres and a deer is 100.
    Numbers extend the reach, which is what a pack is for.
    """
    if hunter is target or target.body.dead:
        return False
    if not eats_meat(hunter) or target.is_player:
        return False
    if target.defn.intelligent or target.defn.has("UNDEAD"):
        # Eating people is a different decision, and one `is_hostile_to`
        # already makes on faction.
        return False
    if eats_meat(target) and target.defn.size >= hunter.defn.size:
        # Predators leave each other alone unless one is plainly bigger.
        return False
    reach = PREY_RATIO
    if hunter.defn.has("PACK"):
        reach += PACK_REACH * pack
    ratio = target.defn.size / float(max(1, hunter.defn.size))
    return PREY_FLOOR <= ratio <= reach


def hunting(creature) -> bool:
    """Whether this creature is hungry enough to go after something."""
    return (eats_meat(creature)
            and creature.needs.hunger >= HUNGRY_AT
            and not creature.defn.has("NO_EAT"))


def prey_for(creature, game) -> Optional[Any]:
    """The nearest thing this creature would eat, if it wants one."""
    if not hunting(creature):
        return None
    from . import morale

    pack = len(morale.company(creature, game)) if creature.defn.has("PACK") else 0
    best, best_d = None, 999
    for other in game.creatures.values():
        if other.body.dead or other.z != creature.z:
            continue
        if not is_prey(creature, other, pack=pack):
            continue
        d = creature.distance_to(other)
        if d < best_d and d <= FORAGE_RANGE:
            best, best_d = other, d
    return best


def hunted_by(animal, other) -> bool:
    """Whether *other* is something *animal* should be running from.

    v3.13 asked whether the other thing was an ambusher or `SAVAGE`, which
    left a wolf looking like scenery to a deer.
    """
    return is_prey(other, animal)


# --------------------------------------------------------------------------- #
# Finding it
# --------------------------------------------------------------------------- #


def _drinkable(game, cell: Cell) -> bool:
    """Whether there is water here to drink."""
    lm = game.local
    if lm is None or not lm.in_bounds(*cell):
        return False
    t = tile_data.get(lm.tile(*cell))
    return t.has("WATER") or t.has("WATER_SOURCE")


def _grazeable(game, cell: Cell) -> bool:
    """Whether there is anything growing here."""
    lm = game.local
    if lm is None or not lm.in_bounds(*cell):
        return False
    return tile_data.get(lm.tile(*cell)).has("GRASS")


def _carrion(game, cell: Cell):
    """A corpse lying here."""
    for item in game.items_at(*cell):
        if item.defn.category == "corpse":
            return item
    return None


def _nearby(game, creature, test, radius: int) -> Optional[Cell]:
    """The nearest cell within *radius* that passes *test*."""
    x, y, z = creature.x, creature.y, creature.z
    for d in range(radius + 1):
        for dy in range(-d, d + 1):
            for dx in range(-d, d + 1):
                if max(abs(dx), abs(dy)) != d:
                    continue
                cell = (x + dx, y + dy, z)
                if test(game, cell):
                    return cell
    return None


def wants(creature) -> str:
    """What this creature is short of: ``"drink"``, ``"food"`` or ``""``."""
    if needs_nothing(creature):
        return ""
    if (creature.needs.thirst >= THIRSTY_AT
            and not creature.defn.has("NO_DRINK")):
        return "drink"
    if creature.needs.hunger >= HUNGRY_AT and not creature.defn.has("NO_EAT"):
        return "food"
    return ""


def desperate(creature) -> bool:
    """Whether this creature will eat with something watching."""
    if needs_nothing(creature):
        return False
    return (creature.needs.thirst >= DESPERATE_THIRST
            or creature.needs.hunger >= DESPERATE_HUNGER)


def target_cell(creature, game) -> Optional[Cell]:
    """Where this creature would go to deal with what it is short of."""
    want = wants(creature)
    if want == "drink":
        cell = _nearby(game, creature, _drinkable, FORAGE_RANGE)
        if cell is not None:
            return cell
        # Nothing to drink within reach, and on most maps nothing anywhere.
        # Eat instead: that is where the water is.
        want = "food"
    if want == "food":
        if eats_meat(creature):
            cell = _nearby(game, creature, lambda g, c: _carrion(g, c) is not None,
                           FORAGE_RANGE)
            if cell is not None:
                return cell
        if eats_plants(creature):
            return _nearby(game, creature, _grazeable, FORAGE_RANGE)
    return None


def feed_here(creature, game) -> str:
    """Take whatever is on this cell. Returns what happened, or ``""``.

    Opportunistic and free: an animal standing in a stream does not need a
    plan to drink from it.
    """
    if needs_nothing(creature):
        return ""
    cell = (creature.x, creature.y, creature.z)
    if (creature.needs.thirst >= THIRSTY_AT
            and not creature.defn.has("NO_DRINK") and _drinkable(game, cell)):
        creature.needs.thirst = max(0, creature.needs.thirst - DRINK_VALUE)
        return "drink"
    if creature.needs.hunger < HUNGRY_AT or creature.defn.has("NO_EAT"):
        return ""
    if eats_meat(creature):
        corpse = _carrion(game, cell)
        if corpse is not None:
            _feed(creature, MEAT_VALUE)
            game.take_item(corpse, *cell)
            return "meat"
    if eats_plants(creature) and _grazeable(game, cell):
        _feed(creature, GRAZE_VALUE)
        return "graze"
    return ""


def _feed(creature, value: int) -> None:
    """A mouthful, and what it is worth against both clocks."""
    creature.needs.hunger = max(0, creature.needs.hunger - value)
    creature.needs.thirst = max(0, creature.needs.thirst - WATER_FROM_FOOD)


def ate(hunter, victim) -> None:
    """A kill is a meal. The hunter stops being hungry for a while."""
    if not eats_meat(hunter) or hunter.defn.has("NO_EAT"):
        return
    share = MEAT_VALUE
    if victim.defn.size < hunter.defn.size // 4:
        share //= 2      # a mouse is not a dinner
    _feed(hunter, share)
