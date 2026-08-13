"""Livestock, pets and the wild things outside.

An animal is a creature with an ``.animal`` state where a dwarf has a ``.fort``
state. The fortress owns it, it grazes, it breeds, it gives milk or wool, and
eventually somebody butchers it. Nothing here gives an animal a job: they are
livestock, not labour.

Everything an animal does costs one dictionary lookup and a couple of tile
reads. There can be forty of them wandering about while the fortress works, so
none of it may be expensive.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..data.calendar import TICKS_PER_DAY
from ..engine import geometry
from ..game.entity import make_creature
from ..game.item import Item

Cell = Tuple[int, int, int]

#: What the fortress sets out with.
EMBARK_ANIMALS: Tuple[Tuple[str, bool], ...] = (
    ("dog", False), ("dog", True), ("cat", True),
    ("cow", True), ("cow", False), ("sheep", True), ("sheep", False),
)

#: A grazer that has gone this long without eating is dead. Long enough that
#: a player has a season to notice, because the classic dwarven embark is a
#: mountain with not one blade of grass on it.
GRAZE_TICKS = TICKS_PER_DAY * 20

#: Past this much hunger, an animal with no grass starts on the stores.
FODDER_AT = TICKS_PER_DAY * 8

#: Plants the fortress keeps back for itself before the animals get any.
FODDER_RESERVE = 20

#: How long a grazed tile takes to come back.
REGROW_TICKS = TICKS_PER_DAY * 10

#: How often a fed cow or sheep is worth milking or shearing.
PRODUCE_TICKS = TICKS_PER_DAY * 12

#: Gestation, and the herd size a species stops growing at. A fortress that
#: fills up with sheep has a different problem from the one it started with.
BREED_TICKS = TICKS_PER_DAY * 30
HERD_CAP = 10

#: Young animals are not milked, sheared, bred or butchered for much.
ADULT_DAYS = 60

#: How far a pet will wander from whoever it has decided to follow.
PET_RANGE = 3

#: What a species gives when it is milked or sheared, and what it is worth
#: dead. Everything else is just an animal.
PRODUCE: Dict[str, Tuple[str, str]] = {
    "cow": ("milk", "milk"),
    "goat": ("milk", "milk"),
    "sheep": ("wool", "wool_cloth"),
}

#: Meat, hide and bone from one carcass, by size in cubic centimetres.
BUTCHER_YIELD: Tuple[Tuple[int, int, int, int], ...] = (
    (500000, 12, 3, 4),
    (100000, 6, 2, 3),
    (30000, 3, 1, 2),
    (0, 1, 0, 1),
)


class Animal:
    """What the fortress knows about one of its animals."""

    __slots__ = ("pasture", "owner", "hunger", "produce_at", "breed_at",
                 "slaughter", "wild")

    def __init__(self) -> None:
        #: Pasture id a grazer belongs to, if the player has painted one.
        self.pasture: Optional[int] = None
        #: The dwarf a pet follows about.
        self.owner: Optional[int] = None
        #: Ticks since it last found something to eat.
        self.hunger = 0
        #: Tick it is next worth milking or shearing at.
        self.produce_at = 0
        #: Tick it may next give birth.
        self.breed_at = 0
        #: Set by the player. A butcher will come for it.
        self.slaughter = False
        #: Wild things are on the map but not owned.
        self.wild = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the animal state."""
        return {
            "pasture": self.pasture, "owner": self.owner,
            "hunger": self.hunger, "produce_at": self.produce_at,
            "breed_at": self.breed_at, "slaughter": self.slaughter,
            "wild": self.wild,
        }

    @classmethod
    def from_dict(cls, d) -> "Animal":
        """Rebuild from :meth:`to_dict`."""
        a = cls()
        a.pasture = d.get("pasture")
        a.owner = d.get("owner")
        a.hunger = int(d.get("hunger", 0))
        a.produce_at = int(d.get("produce_at", 0))
        a.breed_at = int(d.get("breed_at", 0))
        a.slaughter = bool(d.get("slaughter", False))
        a.wild = bool(d.get("wild", False))
        return a


class Pasture:
    """A rectangle of ground the fortress keeps animals on."""

    _next_id = 1

    def __init__(self, x: int, y: int, z: int, w: int, h: int) -> None:
        self.id = Pasture._next_id
        Pasture._next_id += 1
        self.x = x
        self.y = y
        self.z = z
        self.w = max(1, w)
        self.h = max(1, h)

    def contains(self, x: int, y: int, z: int) -> bool:
        """True if a cell lies in this pasture."""
        return (z == self.z and self.x <= x < self.x + self.w
                and self.y <= y < self.y + self.h)

    def cells(self) -> List[Cell]:
        """Every cell of the pasture."""
        return [(self.x + dx, self.y + dy, self.z)
                for dy in range(self.h) for dx in range(self.w)]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the pasture."""
        return {"id": self.id, "x": self.x, "y": self.y, "z": self.z,
                "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, d) -> "Pasture":
        """Rebuild from :meth:`to_dict`."""
        p = cls(int(d["x"]), int(d["y"]), int(d["z"]), int(d["w"]),
                int(d["h"]))
        p.id = int(d.get("id", p.id))
        Pasture._next_id = max(Pasture._next_id, p.id + 1)
        return p


# --------------------------------------------------------------------------- #
# Making them
# --------------------------------------------------------------------------- #


def attach(creature, *, wild: bool = False):
    """Give a creature the state that makes it an animal of the fortress."""
    creature.animal = Animal()
    creature.animal.wild = wild
    return creature


def make_animal(rng, species: str, *, female: bool = True, wild: bool = False,
                age: Optional[int] = None):
    """One animal, tame or wild."""
    c = make_creature(rng, species, faction="wild" if wild else "fortress",
                      equip=False)
    c.female = female
    if age is not None:
        c.age = age
    return attach(c, wild=wild)


def spawn_wildlife(fort, rng, count: Optional[int] = None) -> List:
    """Put a few wild animals on the surface, whatever lives around here.

    A map with nothing moving on it but your own dwarves reads as a diorama.
    These are hunted, they eat your crops, and the savage ones are a reason
    to keep the militia trained.
    """
    from ..data import creatures as creature_data

    kinds = creature_data.spawnable(
        fort.local.biome, max_tier=2,
        # Wildlife, not enemies: a siege arrives as a siege, and the walking
        # dead are not something you hunt for the hides.
        flags_none=("MEGABEAST", "SEMIMEGABEAST", "INTELLIGENT", "EVIL",
                    "OPPOSED_TO_LIFE", "NO_EAT"))
    if not kinds:
        return []
    out = []
    for _ in range(count if count is not None else rng.randint(4, 9)):
        defn = rng.choice(kinds)
        spot = fort.local.random_open(rng)
        if not fort.local.is_outside(*spot):
            continue
        beast = make_animal(rng, defn.id, female=rng.chance(0.5), wild=True)
        beast.x, beast.y, beast.z = spot
        beast.wx, beast.wy = fort.wx, fort.wy
        fort.add_creature(beast)
        out.append(beast)
    return out


def is_animal(c) -> bool:
    """True for anything with animal state on it."""
    return getattr(c, "animal", None) is not None


def livestock(fort) -> List:
    """Every living animal the fortress owns."""
    return [c for c in fort.creatures.values()
            if is_animal(c) and not c.animal.wild and not c.body.dead]


def wildlife(fort) -> List:
    """Every living wild animal on the map."""
    return [c for c in fort.creatures.values()
            if is_animal(c) and c.animal.wild and not c.body.dead]


def is_adult(fort, c) -> bool:
    """True once an animal is worth breeding, milking or butchering."""
    return c.age >= 1 or fort.ticks >= ADULT_DAYS * TICKS_PER_DAY


def grazes(c) -> bool:
    """True for animals that need grass."""
    return c.defn.has("GRAZER")


# --------------------------------------------------------------------------- #
# Living
# --------------------------------------------------------------------------- #


def step(fort, ticks: int) -> None:
    """One simulation step for every animal on the map."""
    _regrow(fort)
    for c in list(fort.creatures.values()):
        if not is_animal(c) or c.body.dead:
            continue
        state = c.animal
        if state.wild:
            _wander(fort, c, indoors=False)
            continue
        _assign_pasture(fort, c)
        if grazes(c):
            _graze(fort, c, ticks)
        elif state.owner is not None:
            _follow(fort, c)
        else:
            _wander(fort, c, indoors=True)
    _breed(fort)


def _regrow(fort) -> None:
    """Grass comes back where animals ate it."""
    if not fort.grazed:
        return
    for cell, when in list(fort.grazed.items()):
        if fort.ticks < when + REGROW_TICKS:
            continue
        del fort.grazed[cell]
        if fort.local.tile(*cell) == "dirt":
            fort.local.set_tile(cell[0], cell[1], cell[2], "grass")


def _assign_pasture(fort, c) -> None:
    """Put a grazer in the emptiest pasture there is."""
    state = c.animal
    if not grazes(c) or not fort.pastures:
        return
    if state.pasture is not None and fort.pasture(state.pasture) is not None:
        return
    counts = {p.id: 0 for p in fort.pastures}
    for other in livestock(fort):
        if other.animal.pasture in counts:
            counts[other.animal.pasture] += 1
    state.pasture = min(counts, key=lambda pid: counts[pid])


def _graze(fort, c, ticks: int) -> None:
    """Eat the grass under your feet, or go and find some.

    An animal with a pasture stays in it, which is the entire point of
    painting one. An animal without a pasture wanders the map eating whatever
    it walks over, which is the entire point of not painting one.
    """
    state = c.animal
    state.hunger += ticks
    here = (c.x, c.y, c.z)
    tile = fort.local.tile(*here)
    if tile in ("grass", "shrub", "sapling"):
        fort.local.set_tile(c.x, c.y, c.z, "dirt")
        fort.grazed[here] = fort.ticks
        state.hunger = 0
        return

    pasture = fort.pasture(state.pasture) if state.pasture else None
    if pasture is not None and not pasture.contains(*here):
        _step_towards(fort, c, (pasture.x + pasture.w // 2,
                                pasture.y + pasture.h // 2, pasture.z))
        return
    _wander(fort, c, indoors=True, inside=pasture)

    if state.hunger > FODDER_AT and _eat_fodder(fort):
        # No grass on this embark, or none left in the pasture. A mountain
        # fortress feeds its animals out of the same cellar it eats from,
        # which is expensive and much better than watching them die.
        state.hunger = 0
        fort.warn_once("fodder",
                       "Your animals are eating the stores. They need grass: "
                       "paint a pasture with n.")
        return

    if state.hunger > GRAZE_TICKS:
        c.body.dead = True
        c.body.death_cause = "starved to death"
        fort.kill_creature(c)
        fort.warn_once("grazing", "Your animals are starving.")


def _eat_fodder(fort) -> bool:
    """Take one plant out of the stores for an animal. False if there is none."""
    for item in fort.all_items():
        if item.def_id not in ("plump_helmet", "cave_wheat", "berries"):
            continue
        if fort.stock_count(item.def_id) <= FODDER_RESERVE:
            continue
        item.count -= 1
        if item.count <= 0:
            fort.take_item(item)
        return True
    return False


def _follow(fort, c) -> None:
    """A pet keeps its dwarf in sight and otherwise pleases itself."""
    owner = fort.creatures.get(c.animal.owner)
    if owner is None or owner.body.dead:
        c.animal.owner = None
        return
    if geometry.chebyshev(c.x, c.y, owner.x, owner.y) > PET_RANGE \
            or c.z != owner.z:
        _step_towards(fort, c, (owner.x, owner.y, owner.z))
    else:
        _wander(fort, c, indoors=True)


def _wander(fort, c, *, indoors: bool, inside: Optional[Pasture] = None) -> None:
    """A step in no particular direction, if there is anywhere to put a foot."""
    if not fort.rng.chance(0.35):
        return
    dx, dy = fort.rng.choice(list(geometry.DIRS8))
    cell = (c.x + dx, c.y + dy, c.z)
    if inside is not None and not inside.contains(*cell):
        return
    if not fort.local.walkable(*cell) or fort.creature_at(*cell) is not None:
        return
    if fort.water.deep(*cell) or fort.magma.at(*cell) > 0:
        return
    if not indoors and not fort.local.is_outside(*cell):
        return
    c.x, c.y, c.z = cell


def _step_towards(fort, c, goal: Cell) -> None:
    """One step in roughly the right direction. Animals do not use A*."""
    dx, dy = geometry.normalize_dir(goal[0] - c.x, goal[1] - c.y)
    for cand in ((c.x + dx, c.y + dy, c.z), (c.x + dx, c.y, c.z),
                 (c.x, c.y + dy, c.z)):
        if not fort.local.walkable(*cand) or fort.creature_at(*cand):
            continue
        if fort.water.deep(*cand) or fort.magma.at(*cand) > 0:
            continue
        c.x, c.y, c.z = cand
        return


def _breed(fort) -> None:
    """Two of a kind in one pasture, given time, make a third."""
    herds: Dict[str, List] = {}
    for c in livestock(fort):
        if grazes(c) and is_adult(fort, c):
            herds.setdefault(c.defn.id, []).append(c)
    for species, herd in herds.items():
        if len(herd) >= HERD_CAP or len(herd) < 2:
            continue
        mothers = [c for c in herd if c.female]
        if not mothers or not any(not c.female for c in herd):
            continue
        mother = mothers[0]
        if fort.ticks < mother.animal.breed_at:
            continue
        if mother.animal.breed_at == 0:
            mother.animal.breed_at = fort.ticks + BREED_TICKS
            continue
        mother.animal.breed_at = fort.ticks + BREED_TICKS
        calf = make_animal(fort.rng, species,
                           female=fort.rng.chance(0.5), age=0)
        calf.x, calf.y, calf.z = mother.x, mother.y, mother.z
        calf.wx, calf.wy = fort.wx, fort.wy
        calf.animal.pasture = mother.animal.pasture
        fort.add_creature(calf)
        fort.log.good("A %s has been born." % calf.short_name())


# --------------------------------------------------------------------------- #
# What they are worth
# --------------------------------------------------------------------------- #


def ready_to_produce(fort, c) -> bool:
    """True if this animal has milk or wool waiting."""
    if c.defn.id not in PRODUCE or not is_adult(fort, c):
        return False
    return fort.ticks >= c.animal.produce_at


def produce(fort, c) -> Optional[Item]:
    """Milk or shear one animal."""
    made = PRODUCE.get(c.defn.id)
    if made is None:
        return None
    def_id, material = made
    c.animal.produce_at = fort.ticks + PRODUCE_TICKS
    return Item(def_id, material, count=2)


def butcher_yield(fort, c) -> List[Item]:
    """Meat, hide and bone off one carcass."""
    size = c.defn.size
    meat, hide, bone = 1, 0, 1
    for threshold, m, h, b in BUTCHER_YIELD:
        if size >= threshold:
            meat, hide, bone = m, h, b
            break
    if not is_adult(fort, c):
        meat = max(1, meat // 2)
    out = [Item("meat", "meat", count=meat),
           Item("bone_item", "bone", count=bone)]
    if hide:
        out.append(Item("hide", "leather", count=hide))
    return out


def summary(fort) -> str:
    """One line for the sidebar."""
    herd = livestock(fort)
    if not herd:
        return ""
    grazers = sum(1 for c in herd if grazes(c))
    return "%d animals (%d grazing)" % (len(herd), grazers)
