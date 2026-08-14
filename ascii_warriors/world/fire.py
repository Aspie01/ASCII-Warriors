"""Fire: the thing this game has had every ingredient for and never lit.

`FLAMMABLE` is on the tree, the sapling and the shrub in the tile table, and on
oak, willow, pine, cedar, birch, coal and charcoal in the material table, and on
the torch and the log in the item table. Magma has been flowing in fortresses
since v2.5 and adventurers have been carrying burning torches since v1. Nothing
in the game has ever caught alight.

**A fire is fuel and a clock, on one cell.** The model is v2.5's fluid layer
with the water taken out: a dict of burning cells, an active set so a map that
is not on fire costs nothing to step, and a hard cap on how much can burn at
once. Each cell has fuel that runs down, and while it burns it may light the
flammable cells around it.

**What burns is what the data says burns.** The tile decides most of it -- a
tree is a long fire and a shrub is a brief one -- and flammable items lying on
the cell add to it, which is why a woodpile is a bad thing to keep next to the
forge. When the fuel is gone the tile becomes ash and whatever was lying on it
does not come back.

Fire is also light, which means v3.6's stealth reads it for free: standing in
front of a burning tree is the least hidden you will ever be.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

Cell = Tuple[int, int, int]

#: How much fuel each kind of ground is worth. A tree burns for a long time; a
#: shrub is a flare and gone.
TILE_FUEL: Dict[str, int] = {
    "tree": 90, "sapling": 30, "shrub": 18,
}

#: What a flammable item adds to the cell it is lying on.
ITEM_FUEL = 12

#: Fuel spent per step of fire.
BURN_RATE = 3

#: The most cells that may be alight at once. A forest fire that eats a whole
#: map is a frame-rate problem rather than a drama, and the cap is what keeps
#: the step bounded the way v2.5's `MAX_ACTIVE` does for water.
MAX_BURNING = 600

#: Odds per step that a burning cell lights one particular neighbour. Low,
#: because it is rolled for eight neighbours every step: at 0.08 a tree next to
#: a tree catches within a handful of turns and a lone shrub usually does not
#: take the forest with it.
SPREAD_ODDS = 0.08

#: How hot a cell has to be burning before it will spread at all -- a fire
#: that has nearly burnt out does not jump.
SPREAD_FLOOR = 6

#: What standing in a fire does per step, as momentum into the body model.
BURN_MOMENTUM = 5200

#: How much light a burning cell throws, and how far.
FIRE_LIGHT = 1.0
LIGHT_RADIUS = 4

#: What a fire leaves.
ASH_TILE = "ash"


class Fire:
    """Everything alight on one map."""

    __slots__ = ("fuel", "_active")

    def __init__(self) -> None:
        #: Cell -> fuel remaining. A cell in here is on fire.
        self.fuel: Dict[Cell, int] = {}
        self._active: Set[Cell] = set()

    # -- asking -------------------------------------------------------------- #

    def burning(self, x: int, y: int, z: int) -> int:
        """Fuel left on a cell, or 0 if it is not alight."""
        return self.fuel.get((x, y, z), 0)

    @property
    def anything_burning(self) -> bool:
        """Whether there is a fire anywhere."""
        return bool(self.fuel)

    def light_at(self, x: int, y: int, z: int) -> float:
        """How much light the fires throw on a cell, 0..1.

        Read by both modes' `light_at`, so v3.6's stealth charges you for
        standing near a burning tree without knowing what a fire is.
        """
        if not self.fuel:
            return 0.0
        best = 0.0
        for (fx, fy, fz), left in self.fuel.items():
            if fz != z:
                continue
            d = max(abs(fx - x), abs(fy - y))
            if d > LIGHT_RADIUS:
                continue
            best = max(best, FIRE_LIGHT * (1.0 - d / float(LIGHT_RADIUS + 1)))
        return min(1.0, best)

    # -- lighting ------------------------------------------------------------ #

    def ignite(self, lm, cell: Cell, *, extra: int = 0) -> bool:
        """Set a cell alight. False if there is nothing there to burn."""
        if cell in self.fuel or len(self.fuel) >= MAX_BURNING:
            return False
        fuel = fuel_at(lm, cell) + extra
        if fuel <= 0:
            return False
        self.fuel[cell] = fuel
        self._wake(cell)
        return True

    def _wake(self, cell: Cell) -> None:
        """Mark a cell and its neighbours as worth looking at next step."""
        x, y, z = cell
        self._active.add(cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                self._active.add((x + dx, y + dy, z))

    def extinguish(self, cell: Cell) -> None:
        """Put one cell out without burning it away."""
        self.fuel.pop(cell, None)

    # -- burning ------------------------------------------------------------- #

    def step(self, lm, rng, *, items_at=None, on_burn_out=None) -> List[Cell]:
        """Advance every fire. Returns the cells that finished burning.

        *items_at* is a callable returning the items on a cell, so the same
        step works for a Fortress and a Game without this module knowing what
        either of them is.
        """
        if not self.fuel:
            self._active.clear()
            return []

        spread: List[Cell] = []
        done: List[Cell] = []
        for cell, left in list(self.fuel.items()):
            left -= BURN_RATE
            if left <= 0:
                del self.fuel[cell]
                done.append(cell)
                continue
            self.fuel[cell] = left
            if left < SPREAD_FLOOR:
                continue
            x, y, z = cell
            for dx, dy in _NEIGHBOURS:
                nxt = (x + dx, y + dy, z)
                if nxt in self.fuel or not rng.chance(SPREAD_ODDS):
                    continue
                if fuel_at(lm, nxt) <= 0:
                    continue
                spread.append(nxt)

        for cell in spread:
            self.ignite(lm, cell)

        for cell in done:
            self._burn_away(lm, cell, items_at, on_burn_out)
        if not self.fuel:
            self._active.clear()
        return done

    def _burn_away(self, lm, cell: Cell, items_at, on_burn_out) -> None:
        """Turn a spent cell to ash and take what was on it."""
        if lm.in_bounds(*cell) and lm.tile(*cell) in TILE_FUEL:
            lm.set_tile(cell[0], cell[1], cell[2], ASH_TILE)
        if items_at is not None:
            for item in list(items_at(*cell)):
                if is_flammable_item(item) and on_burn_out is not None:
                    on_burn_out(item, cell)
        self.fuel.pop(cell, None)

    # -- serialising --------------------------------------------------------- #

    def to_list(self) -> List[Any]:
        """The whole layer, for a save."""
        return [[c[0], c[1], c[2], v] for c, v in self.fuel.items()]

    @classmethod
    def from_list(cls, raw: Sequence[Any]) -> "Fire":
        """Rebuild from :meth:`to_list`."""
        f = cls()
        for row in raw or ():
            try:
                x, y, z, v = row
            except (TypeError, ValueError):    # pragma: no cover - defensive
                continue
            cell = (int(x), int(y), int(z))
            f.fuel[cell] = int(v)
            f._wake(cell)
        return f

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Fire(%d burning)" % len(self.fuel)


_NEIGHBOURS: Tuple[Tuple[int, int], ...] = (
    (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1),
)


# --------------------------------------------------------------------------- #
# What burns
# --------------------------------------------------------------------------- #


def fuel_at(lm, cell: Cell) -> int:
    """How much a cell's own ground is worth as fuel."""
    if lm is None or not lm.in_bounds(*cell):
        return 0
    return TILE_FUEL.get(lm.tile(*cell), 0)


def is_flammable_item(item) -> bool:
    """Whether an item will burn.

    The item's own flag or its material's -- a wooden bed is not flagged
    FLAMMABLE and is unambiguously firewood.
    """
    from ..data import materials as mat_data

    defn = getattr(item, "defn", None)
    if defn is not None and defn.has("FLAMMABLE"):
        return True
    mat = mat_data.MATERIALS.get(getattr(item, "material", ""))
    return bool(mat is not None and "FLAMMABLE" in mat.flags)


def item_fuel(items: Iterable[Any]) -> int:
    """What a pile of items adds to a fire."""
    return sum(ITEM_FUEL for i in items if is_flammable_item(i))


def carrying_flame(creature) -> bool:
    """Whether this creature is holding something already burning.

    The same question v3.6's stealth asks to decide whether your own torch is
    giving you away, asked here to decide whether you can start a fire.
    """
    inv = getattr(creature, "inventory", None)
    if inv is None:
        return False
    for item in inv.items:
        if item.is_light and item.flags.get("lit") and item.charges > 0:
            return True
    return False


def burn(creature, rng, log=None) -> None:
    """Standing in a fire, for one step.

    Through `combat.trap_strike`, which is the path the game already uses for
    damage that nobody gets to parry -- a third way to hurt somebody is a third
    set of numbers to keep in agreement with the other two.
    """
    from ..game import combat

    combat.trap_strike(creature, "fire", "", rng=rng, log=log)
