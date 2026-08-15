"""Fluids that move: water, and the other one.

A fluid is stored as a depth from 1 to 7 on the cells that have any, separate
from the terrain. It falls into whatever is below it, spreads sideways into
anything shallower, and — if it is the kind that does — evaporates when there
is almost none left.

Only cells that have fluid, and their neighbours, are ever looked at. A river
of five hundred tiles costs five hundred cells of work per step, not eighty
thousand.

Magma is the same simulation with three constants changed: it is thicker, so
it moves on one step in three; it never dries up; and it kills whatever it
touches. Everything else about it — reservoirs, sealed banks, pressure from a
source — is water's machinery, which had already been debugged the hard way.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import tiles as tile_data

Cell = Tuple[int, int, int]

#: Maximum water in one cell. 7 is a full tile, as in Dwarf Fortress.
MAX_DEPTH = 7

#: A creature standing in this much water is swimming, not wading.
SWIM_DEPTH = 4

#: Below this, a puddle dries up.
EVAPORATE_AT = 1

#: How many cells the simulation will touch in one step before giving up and
#: finishing the rest next time. A flooding fortress must not stall the game.
MAX_ACTIVE = 2500

#: How far a saturated source will look for somewhere to put the next unit.
PUSH_RANGE = 400


def can_hold(lm, cell: Cell) -> bool:
    """True if water can occupy this cell at all.

    Walls stop it; so do closed doors, floodgates and raised bridges, which
    is the whole point of building them.
    """
    if not lm.in_bounds(*cell):
        return False
    t = tile_data.get(lm.tile(*cell))
    if t.has("DOOR") and not t.has("OPEN"):
        # A shut door holds water, which is why you put one there.
        return False
    return t.walk or t.has("OPEN")


class Water:
    """The water on one local map."""

    #: What this is, for messages and saves.
    NAME = "water"
    #: Puddles of this dry up outdoors. Magma does not.
    EVAPORATES = True
    #: Steps between moves. Water moves every step; magma is thicker.
    VISCOSITY = 1

    def __init__(self) -> None:
        #: cell -> depth, 1..7. Cells with no water are absent.
        self.depth: Dict[Cell, int] = {}
        #: Cells that produce water every step: aquifers and springs.
        self.sources: Dict[Cell, int] = {}
        #: Cells belonging to a river or lake, and the depth they return to.
        #: A natural body of water is effectively infinite: channel into one
        #: and it pours in for ever without the river itself draining away.
        self.infinite: Dict[Cell, int] = {}
        #: Open cells beside a natural body that are its bed or its bank.
        self.sealed: Set[Cell] = set()
        #: Natural cells that border anything else, refreshed when that
        #: changes, with a set beside it so patching stays cheap.
        self._shore: List[Cell] = []
        self._shore_set: Set[Cell] = set()
        #: Cells worth looking at next step.
        self._active: Set[Cell] = set()
        #: Rising water is worth telling the player about, once.
        self.flooded = False
        #: Steps taken, so a thick fluid can sit still on most of them.
        self.ticks = 0
        #: Set when something was dug: the shore is worked out again on the
        #: next step, when there is a map to hand.
        self._shore_dirty = True

    # -- queries ------------------------------------------------------------ #

    def at(self, x: int, y: int, z: int) -> int:
        """Depth of water on a cell, 0 if dry."""
        return self.depth.get((x, y, z), 0)

    def deep(self, x: int, y: int, z: int) -> bool:
        """True if a creature would be swimming here."""
        return self.at(x, y, z) >= SWIM_DEPTH

    def wet(self, x: int, y: int, z: int) -> bool:
        """True if there is any water at all."""
        return (x, y, z) in self.depth

    def set(self, cell: Cell, depth: int) -> None:
        """Put a given depth of water on a cell."""
        depth = max(0, min(MAX_DEPTH, depth))
        if depth <= 0:
            self.depth.pop(cell, None)
        else:
            self.depth[cell] = depth
        self._wake(cell)

    def add(self, cell: Cell, amount: int) -> None:
        """Pour water onto a cell."""
        self.set(cell, self.at(*cell) + amount)

    def add_source(self, cell: Cell, rate: int = 1) -> None:
        """Mark a cell as producing water for ever."""
        self.sources[cell] = max(1, rate)
        self._wake(cell)

    def cells(self) -> Iterable[Cell]:
        """Every wet cell."""
        return self.depth.keys()

    def total(self) -> int:
        """How much water is on the map, for tests and debugging."""
        return sum(self.depth.values())

    # -- simulation --------------------------------------------------------- #

    def _wake(self, cell: Cell) -> None:
        """Mark a cell and its neighbours as worth simulating."""
        x, y, z = cell
        self._active.add(cell)
        self._active.add((x, y, z - 1))
        self._active.add((x, y, z + 1))
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            self._active.add((x + dx, y + dy, z))

    def _passable(self, lm, cell: Cell) -> bool:
        """True if water can occupy this cell at all."""
        return can_hold(lm, cell)

    def step(self, lm) -> None:
        """Move the fluid one step."""
        self.ticks += 1
        if self.VISCOSITY > 1 and self.ticks % self.VISCOSITY:
            # Thick fluid: it is still going, just not this step.
            return
        if self._shore_dirty:
            self.rebuild_shore(lm)
        for cell, rate in self.sources.items():
            if self._passable(lm, cell) and self.at(*cell) < MAX_DEPTH:
                self.depth[cell] = min(MAX_DEPTH, self.at(*cell) + rate)
                self._wake(cell)
        self._push(lm)
        self._feed_from_natural(lm)

        # Rivers and lakes are reservoirs, not weather. They feed whatever you
        # dig next to them, but they do not creep across the countryside.
        active = [c for c in self._active
                  if c in self.depth and c not in self.infinite]
        if len(active) > MAX_ACTIVE:
            active = active[:MAX_ACTIVE]
        self._active = set()

        # Deepest first, so a column drains from the top down in one pass.
        active.sort(key=lambda c: (c[2], -self.depth.get(c, 0)))
        for cell in active:
            depth = self.depth.get(cell, 0)
            if depth <= 0:
                continue
            depth = self._fall(lm, cell, depth)
            if depth <= 0:
                continue
            self._spread(lm, cell, depth)

        for cell in [c for c, d in self.depth.items() if d <= 0]:
            del self.depth[cell]

    def _push(self, lm) -> None:
        """Let a source that has filled its own cell push on into the pool.

        Water levels out to within one unit and then stops: every cell is
        within one of its neighbours, nothing is worth moving, and the pool
        sits there in a shallow staircase. That is fine for a pond and wrong
        for an aquifer, which has a whole rock layer behind it. A saturated
        source shoves one unit through to the nearest shallow water instead,
        so the leak keeps working its way outward.
        """
        full = [c for c in self.sources
                if self.depth.get(c, 0) >= MAX_DEPTH]
        if not full:
            return
        seen = set(full)
        frontier = list(full)
        targets: List[Cell] = []
        scanned = 0
        while frontier and scanned < PUSH_RANGE and len(targets) < len(full):
            nxt: List[Cell] = []
            for cell in frontier:
                scanned += 1
                x, y, z = cell
                # Down and outward only. Water without a pump does not climb.
                for side in ((x, y, z - 1), (x - 1, y, z), (x + 1, y, z),
                             (x, y - 1, z), (x, y + 1, z)):
                    if side in seen or not self._passable(lm, side):
                        continue
                    seen.add(side)
                    if self.depth.get(side, 0) <= MAX_DEPTH - 2:
                        targets.append(side)
                        if len(targets) >= len(full):
                            break
                    nxt.append(side)
                if len(targets) >= len(full):
                    break
            frontier = nxt
        for source, target in zip(full, targets):
            self.depth[source] = self.depth[source] - 1
            self.depth[target] = self.depth.get(target, 0) + 1
            self._wake(source)
            self._wake(target)

    def _feed_from_natural(self, lm) -> None:
        """Let rivers and lakes pour into anything opened up beside them.

        A riverbed holds its water until somebody breaks it. Every cell that
        was already open next to the water when the map was made is sealed —
        it is the bank, or the rock the river runs over. Dig one out and it
        floods, which is the entire appeal.
        """
        for cell in self._shore:
            level = self.infinite.get(cell, 0)
            if self.depth.get(cell, 0) < level:
                self.depth[cell] = level
            x, y, z = cell
            for side in ((x, y, z - 1), (x - 1, y, z), (x + 1, y, z),
                         (x, y - 1, z), (x, y + 1, z)):
                if side in self.infinite or side in self.sealed:
                    continue
                other = self.depth.get(side, 0)
                if other >= level:
                    continue
                if not self._passable(lm, side):
                    continue
                self.depth[side] = min(MAX_DEPTH, other + max(1, level // 2))
                self._wake(side)

    def seal_banks(self, lm) -> None:
        """Record which open cells beside the water are the bank."""
        self.sealed = set()
        for cell in self.infinite:
            x, y, z = cell
            for side in ((x, y, z - 1), (x - 1, y, z), (x + 1, y, z),
                         (x, y - 1, z), (x, y + 1, z)):
                if side in self.infinite or side in self.depth:
                    continue
                if self._passable(lm, side):
                    self.sealed.add(side)
        self.rebuild_shore(lm)

    def unseal(self, cell: Cell) -> None:
        """Somebody dug here. Whatever it held back, it no longer does.

        Two things can have been holding the fluid: a sealed bank, or plain
        rock. Opening either one puts the reservoir cell next door on the
        shore, and the shore is what gets simulated. Rebuilding the whole
        shore here would cost ten milliseconds a pick swing on a map with a
        magma sea in it, so it is patched in place instead.
        """
        x, y, z = cell
        for probe in ((x, y, z), (x, y, z + 1), (x, y, z - 1),
                      (x - 1, y, z), (x + 1, y, z),
                      (x, y - 1, z), (x, y + 1, z)):
            was_sealed = probe in self.sealed
            self.sealed.discard(probe)
            self._add_shore(probe)
            if was_sealed:
                # That cell was the bank. Whatever it was holding back is now
                # looking at open ground.
                px, py, pz = probe
                for side in ((px, py, pz + 1), (px, py, pz - 1),
                             (px - 1, py, pz), (px + 1, py, pz),
                             (px, py - 1, pz), (px, py + 1, pz)):
                    self._add_shore(side)
        self._wake(cell)

    def _add_shore(self, cell: Cell) -> None:
        """Put a reservoir cell on the list of ones worth simulating."""
        if cell in self.infinite and cell not in self._shore_set:
            self._shore.append(cell)
            self._shore_set.add(cell)

    def rebuild_shore(self, lm=None) -> None:
        """Work out which natural cells actually border something they can
        pour into.

        A river cell in the middle of the river has nowhere to send anything,
        and neither has a magma sea walled in by a mile of rock: only the
        edges that touch somewhere a fluid could go are worth looking at every
        step. Without the rock check the whole surface of the sea counts as
        shore, and the fortress spends ten milliseconds a step on it.
        """
        shore = []
        for cell in self.infinite:
            x, y, z = cell
            for side in ((x, y, z - 1), (x - 1, y, z), (x + 1, y, z),
                         (x, y - 1, z), (x, y + 1, z)):
                if side in self.infinite or side in self.sealed:
                    continue
                if lm is not None and not can_hold(lm, side):
                    continue
                shore.append(cell)
                break
        self._shore = shore
        self._shore_set = set(shore)
        self._shore_dirty = False

    def _fall(self, lm, cell: Cell, depth: int) -> int:
        """Drop water into the cell below. Returns what is left."""
        below = (cell[0], cell[1], cell[2] - 1)
        if not self._passable(lm, below):
            return depth
        room = MAX_DEPTH - self.at(*below)
        if room <= 0:
            return depth
        moved = min(depth, room)
        self.depth[below] = self.at(*below) + moved
        depth -= moved
        if depth <= 0:
            self.depth.pop(cell, None)
        else:
            self.depth[cell] = depth
        self._wake(below)
        self._wake(cell)
        return depth

    def _spread(self, lm, cell: Cell, depth: int) -> None:
        """Even the water out with its neighbours on the same level."""
        if depth <= EVAPORATE_AT:
            # A puddle under the open sky dries up rather than wandering the
            # map for ever. Water underground stays where you put it, or a
            # flooded room quietly empties itself and the flood means nothing.
            if self.EVAPORATES and lm.is_outside(*cell) \
                    and not self._standing(lm, cell):
                self.depth.pop(cell, None)
            return
        x, y, z = cell
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            side = (x + dx, y + dy, z)
            if not self._passable(lm, side):
                continue
            other = self.at(*side)
            # Two deep is the smallest difference worth moving: half of it is
            # one unit, which levels the pair exactly. Chasing a difference of
            # one moves nothing and keeps every cell in the pool awake.
            if other >= depth - 1:
                continue
            move = (depth - other) // 2
            if move <= 0:
                continue
            self.depth[side] = other + move
            depth -= move
            self.depth[cell] = depth
            self._wake(side)
            self._wake(cell)
            if depth <= 1:
                break

    def _standing(self, lm, cell: Cell) -> bool:
        """True if this cell is a basin the last drop can sit in."""
        x, y, z = cell
        below = (x, y, z - 1)
        if self._passable(lm, below) and self.at(*below) < MAX_DEPTH:
            return False
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            side = (x + dx, y + dy, z)
            if self._passable(lm, side) and self.at(*side) == 0:
                return False
        return True

    def moving(self) -> Set[Cell]:
        """Cells that changed this step, and their neighbours.

        Anything interested in where the fluid has just been — obsidian
        casting, burning goods — looks here rather than at the whole body.
        """
        return set(self._active)

    def wake_all(self) -> None:
        """Mark everything wet as worth simulating, after a load or a dig."""
        self._active = set()
        for cell in list(self.depth) + list(self.sources):
            self._wake(cell)

    # -- serialisation ------------------------------------------------------ #

    def to_dict(self) -> Dict[str, object]:
        """Serialise the water."""
        return {
            "depth": {"%d,%d,%d" % c: d for c, d in self.depth.items()},
            "sources": {"%d,%d,%d" % c: r for c, r in self.sources.items()},
            "infinite": {"%d,%d,%d" % c: d for c, d in self.infinite.items()},
            "sealed": ["%d,%d,%d" % c for c in self.sealed],
            "flooded": self.flooded,
            # Magma moves every `VISCOSITY` ticks and this is the phase of
            # that clock. Dropping it on load restarted the cadence, which is
            # small and is still not the game you saved.
            "ticks": self.ticks,
        }

    @classmethod
    def from_dict(cls, d) -> "Water":
        """Rebuild from :meth:`to_dict`."""
        w = cls()
        w.depth = {
            tuple(int(v) for v in k.split(",")): int(n)
            for k, n in (d.get("depth") or {}).items()
        }
        w.sources = {
            tuple(int(v) for v in k.split(",")): int(n)
            for k, n in (d.get("sources") or {}).items()
        }
        w.infinite = {
            tuple(int(v) for v in k.split(",")): int(n)
            for k, n in (d.get("infinite") or {}).items()
        }
        w.sealed = {
            tuple(int(v) for v in k.split(",")) for k in d.get("sealed", [])
        }
        w.flooded = bool(d.get("flooded", False))
        # The shore needs the map, which a save does not carry: the first step
        # after loading works it out.
        w._shore_dirty = True
        w.wake_all()
        w.ticks = int(d.get("ticks", 0))
        return w

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Water(%d wet cells, %d sources, %d natural)" % (
            len(self.depth), len(self.sources), len(self.infinite))


class Magma(Water):
    """Molten rock. The same physics with worse manners.

    Thicker than water, so it creeps; it never dries up, because nothing
    underground is going to cool it; and standing in it is not a wetting.
    """

    NAME = "magma"
    EVAPORATES = False
    VISCOSITY = 3


#: Depth of magma that will kill whatever is standing in it. Ankle-deep magma
#: is still magma.
BURN_DEPTH = 1


def quench(magma: Magma, water: Water, lm) -> List[Cell]:
    """Turn magma that has met water into obsidian. Returns the cells cast.

    The oldest trick in the fortress: run water onto magma and the two of them
    make you a wall for nothing. It costs a unit of each, and the tile it
    leaves is solid rock that has to be dug out again like any other.

    Only cells that moved this step are considered. Sweeping the whole magma
    sea instead costs ten milliseconds a step to discover that a mile of rock
    is still a mile of rock.
    """
    cast: List[Cell] = []
    candidates = [c for c in (magma.moving() | water.moving())
                  if c in magma.depth]
    for cell in candidates:
        x, y, z = cell
        touching = [
            side for side in ((x, y, z + 1), (x, y, z - 1), (x - 1, y, z),
                              (x + 1, y, z), (x, y - 1, z), (x, y + 1, z),
                              cell)
            if water.depth.get(side, 0) > 0
        ]
        if not touching:
            continue
        side = touching[0]
        water.add(side, -1)
        magma.depth.pop(cell, None)
        lm.set_tile(x, y, z, "obsidian_wall")
        magma._wake(cell)
        water._wake(side)
        cast.append(cell)
    return cast


def seed_magma(lm, floor: int, extra: Optional[Iterable[Cell]] = None) -> Magma:
    """Fill the bottom of the map with a magma sea, and the pipe above it.

    Everything at or below *floor* is molten, as is every cell of *extra* —
    the magma tube that stands up out of the sea. It is a reservoir like a
    river: it sits there for ever until somebody digs into it, and then it
    does not stop coming.
    """
    magma = Magma()
    cells = [(x, y, z)
             for z in range(lm.zmin, floor + 1)
             for y in range(lm.height)
             for x in range(lm.width)]
    cells.extend(extra or ())
    for cell in cells:
        if not can_hold(lm, cell):
            continue
        magma.depth[cell] = MAX_DEPTH
        magma.infinite[cell] = MAX_DEPTH
    magma.seal_banks(lm)
    magma.wake_all()
    return magma


def seed_from_terrain(lm) -> Water:
    """Fill a Water layer from the rivers and lakes the map generator drew."""
    water = Water()
    for z, level in lm.levels.items():
        for i, tid in enumerate(level):
            t = tile_data.get(tid)
            if not t.has("WATER"):
                continue
            x, y = i % lm.width, i // lm.width
            if t.has("DEEP"):
                depth = MAX_DEPTH
            elif tid == "water":
                depth = 5
            else:
                depth = 2
            water.depth[(x, y, z)] = depth
            water.infinite[(x, y, z)] = depth
    water.seal_banks(lm)
    water.wake_all()
    return water
