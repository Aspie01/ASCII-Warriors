"""Designations: the marks you paint on the map telling dwarves what to do.

A designation is a standing instruction attached to a tile. The job board turns
each reachable one into a job, and clears it when the work is done.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

from ..engine import colors
from ..engine.colors import Color
from ..world import tiles as tile_data

Cell = Tuple[int, int, int]


@dataclass(frozen=True)
class DesignationKind:
    """One kind of standing order."""

    id: str
    name: str
    glyph: str
    color: Color
    labor: str
    skill: str
    work: int
    description: str = ""


KINDS: Dict[str, DesignationKind] = {
    k.id: k
    for k in (
        DesignationKind("dig", "Mine", "x", colors.Color(200, 190, 140),
                        "mining", "mining", 90,
                        "Dig out a wall, leaving a floor behind."),
        DesignationKind("channel", "Channel", "v", colors.Color(190, 160, 110),
                        "mining", "mining", 120,
                        "Cut the floor away, dropping to the level below."),
        DesignationKind("stairs", "Stairway", "I", colors.Color(200, 200, 170),
                        "mining", "mining", 110,
                        "Carve a staircase up and down."),
        DesignationKind("ramp", "Ramp", "/", colors.Color(190, 180, 150),
                        "mining", "mining", 110,
                        "Carve a ramp to the level above."),
        DesignationKind("smooth", "Smooth", "=", colors.Color(180, 190, 200),
                        "masonry", "masonry", 70,
                        "Smooth a rough wall or floor."),
        DesignationKind("chop", "Fell trees", "T", colors.Color(150, 200, 130),
                        "woodcutting", "woodcutting", 80,
                        "Cut a tree down for logs."),
        DesignationKind("gather", "Gather plants", '"',
                        colors.Color(150, 210, 150), "herbalism", "herbalism", 50,
                        "Pick shrubs for food and seeds."),
        DesignationKind("remove", "Remove construction", "X",
                        colors.Color(200, 140, 130), "building", "masonry", 60,
                        "Tear down a wall or floor you built."),
    )
}

#: Designations that need a wall or tree present to make sense.
_NEEDS_SOLID = ("dig", "smooth", "remove")


class Designations:
    """Every standing order on the map, keyed by cell."""

    def __init__(self) -> None:
        self.cells: Dict[Cell, str] = {}
        #: Cells a dwarf has claimed, so two miners do not dig the same wall.
        self.claimed: Dict[Cell, int] = {}

    # -- editing ----------------------------------------------------------- #

    def valid(self, lm, x: int, y: int, z: int, kind: str) -> bool:
        """True if a designation makes sense on this tile."""
        if not lm.in_bounds(x, y, z):
            return False
        tid = lm.tile(x, y, z)
        t = tile_data.get(tid)
        if kind == "dig":
            return t.has("WALL") and t.has("DIGGABLE")
        if kind in ("channel", "stairs", "ramp"):
            if kind == "channel":
                return t.walk or t.has("WALL")
            return t.has("WALL") or t.walk
        if kind == "smooth":
            return t.has("WALL") and not t.has("CONSTRUCTED")
        if kind == "chop":
            return t.has("TREE")
        if kind == "gather":
            return tid == "shrub"
        if kind == "remove":
            return t.has("CONSTRUCTED")
        return False

    def set(self, lm, x: int, y: int, z: int, kind: str) -> bool:
        """Paint one designation. Returns True if it was applied."""
        if kind and not self.valid(lm, x, y, z, kind):
            return False
        cell = (x, y, z)
        if not kind:
            return self.clear(cell)
        self.cells[cell] = kind
        return True

    def clear(self, cell: Cell) -> bool:
        """Remove a designation."""
        self.claimed.pop(cell, None)
        return self.cells.pop(cell, None) is not None

    def paint_rect(
        self, lm, x0: int, y0: int, x1: int, y1: int, z: int, kind: str
    ) -> int:
        """Paint a rectangle; returns how many tiles took the designation."""
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))
        count = 0
        for y in range(lo_y, hi_y + 1):
            for x in range(lo_x, hi_x + 1):
                if self.set(lm, x, y, z, kind):
                    count += 1
        return count

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int, z: int) -> int:
        """Erase every designation in a rectangle."""
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))
        count = 0
        for y in range(lo_y, hi_y + 1):
            for x in range(lo_x, hi_x + 1):
                if self.clear((x, y, z)):
                    count += 1
        return count

    # -- queries ----------------------------------------------------------- #

    def get(self, x: int, y: int, z: int) -> str:
        """The designation on a cell, or ``""``."""
        return self.cells.get((x, y, z), "")

    def kind_of(self, cell: Cell) -> Optional[DesignationKind]:
        """The definition of a cell's designation."""
        kind = self.cells.get(cell)
        return KINDS.get(kind) if kind else None

    def on_level(self, z: int) -> Iterator[Tuple[Cell, str]]:
        """Every designation on one z-level."""
        for cell, kind in self.cells.items():
            if cell[2] == z:
                yield (cell, kind)

    def unclaimed(self) -> Iterator[Tuple[Cell, str]]:
        """Designations nobody is working on."""
        for cell, kind in self.cells.items():
            if cell not in self.claimed:
                yield (cell, kind)

    def claim(self, cell: Cell, dwarf_id: int) -> bool:
        """Reserve a designation for one dwarf."""
        if cell in self.claimed or cell not in self.cells:
            return False
        self.claimed[cell] = dwarf_id
        return True

    def release(self, cell: Cell) -> None:
        """Give a claimed designation back to the pool."""
        self.claimed.pop(cell, None)

    def release_all(self, dwarf_id: int) -> None:
        """Free everything a dwarf had claimed, when it dies or is reassigned."""
        for cell, owner in list(self.claimed.items()):
            if owner == dwarf_id:
                del self.claimed[cell]

    def __len__(self) -> int:
        return len(self.cells)

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise every designation."""
        return {
            "cells": {"%d,%d,%d" % c: k for c, k in self.cells.items()},
            "claimed": {"%d,%d,%d" % c: v for c, v in self.claimed.items()},
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Designations":
        """Rebuild from :meth:`to_dict`."""
        out = cls()
        out.cells = {
            tuple(int(v) for v in k.split(",")): kind
            for k, kind in (d.get("cells") or {}).items()
        }
        out.claimed = {
            tuple(int(v) for v in k.split(",")): int(v2)
            for k, v2 in (d.get("claimed") or {}).items()
        }
        return out


def render(kind: str) -> Tuple[str, Color]:
    """Glyph and colour for a designation overlay."""
    k = KINDS.get(kind)
    if k is None:
        return ("?", colors.UI["warn"])
    return (k.glyph, k.color)
