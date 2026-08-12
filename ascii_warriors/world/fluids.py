"""Water that moves.

Water is stored as a depth from 1 to 7 on the cells that have any, separate
from the terrain. It falls into whatever is below it, spreads sideways into
anything shallower, and evaporates when there is almost none left.

Only cells that have water, and their neighbours, are ever looked at. A river
of five hundred tiles costs five hundred cells of work per step, not eighty
thousand.
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
        #: Natural cells that border anything else, refreshed when that changes.
        self._shore: List[Cell] = []
        #: Cells worth looking at next step.
        self._active: Set[Cell] = set()
        #: Rising water is worth telling the player about, once.
        self.flooded = False

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
        """Move the water one step."""
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
        self.rebuild_shore()

    def unseal(self, cell: Cell) -> None:
        """Somebody dug here. Whatever it held back, it no longer does."""
        x, y, z = cell
        touched = False
        for probe in ((x, y, z), (x, y, z + 1), (x - 1, y, z), (x + 1, y, z),
                      (x, y - 1, z), (x, y + 1, z)):
            if probe in self.sealed:
                self.sealed.discard(probe)
                touched = True
        if touched:
            self.rebuild_shore()
        self._wake(cell)

    def rebuild_shore(self) -> None:
        """Work out which natural cells actually border something else.

        A river cell in the middle of the river has nowhere to send anything;
        only the edges are worth looking at every step.
        """
        shore = []
        for cell in self.infinite:
            x, y, z = cell
            for side in ((x, y, z - 1), (x - 1, y, z), (x + 1, y, z),
                         (x, y - 1, z), (x, y + 1, z)):
                if side not in self.infinite and side not in self.sealed:
                    shore.append(cell)
                    break
        self._shore = shore

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
            if lm.is_outside(*cell) and not self._standing(lm, cell):
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
        w.rebuild_shore()
        w.wake_all()
        return w

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Water(%d wet cells, %d sources, %d natural)" % (
            len(self.depth), len(self.sources), len(self.infinite))


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
