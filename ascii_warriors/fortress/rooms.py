"""Rooms, and what living in them does to a dwarf.

A bed in a corridor is a bed. A bed in a smoothed room with a door, a cabinet
and a statue is a bedroom, and the dwarf sleeping in it is measurably happier
about its life. This module works out which is which.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..world import tiles as tile_data

Cell = Tuple[int, int, int]

#: How far a room extends from its central piece of furniture.
ROOM_RADIUS = 4

#: Furniture that defines a room, and what the room is called.
ROOM_KINDS: Dict[str, str] = {
    "bed": "bedroom",
    "hospital": "hospital",
    "table": "dining room",
    "chair": "office",
    "statue": "sculpture garden",
    "well": "well room",
    "barracks": "barracks",
}

#: What each piece of furniture inside a room adds to its quality.
FURNITURE_VALUE: Dict[str, int] = {
    "bed": 2, "table": 2, "chair": 2, "cabinet": 3, "coffer": 3,
    "statue": 6, "door": 2, "well": 4, "altar": 5, "barracks": 2,
    "hospital": 2,
}

#: Quality thresholds and the names Dwarf Fortress would give them.
QUALITY_NAMES: Tuple[Tuple[int, str], ...] = (
    (60, "royal"),
    (40, "splendid"),
    (26, "great"),
    (16, "fine"),
    (8, "decent"),
    (3, "modest"),
    (0, "meagre"),
)


@dataclass
class Room:
    """One furnished space and what it is worth to whoever uses it."""

    kind: str
    building_id: int
    owner: Optional[int]
    cells: Tuple[Cell, ...]
    quality: int
    furniture: int
    smoothed: int

    @property
    def name(self) -> str:
        """``"a fine bedroom"``."""
        return "%s %s" % (quality_name(self.quality), self.kind)

    @property
    def thought(self) -> int:
        """Stress change from living with this room. Negative is good."""
        return -min(12, self.quality // 3)


def quality_name(quality: int) -> str:
    """The word for a room of this quality."""
    for threshold, name in QUALITY_NAMES:
        if quality >= threshold:
            return name
    return "meagre"


def room_cells(lm, centre: Cell) -> List[Cell]:
    """The enclosed floor around a piece of furniture.

    Flood fill outward, stopping at walls and doors, so a bed in an open
    cavern does not claim half the map as its bedroom.
    """
    cx, cy, cz = centre
    seen = {(cx, cy, cz)}
    frontier = [(cx, cy, cz)]
    out: List[Cell] = [(cx, cy, cz)]
    while frontier:
        x, y, z = frontier.pop()
        if max(abs(x - cx), abs(y - cy)) >= ROOM_RADIUS:
            continue
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            cell = (x + dx, y + dy, z)
            if cell in seen:
                continue
            seen.add(cell)
            tile = tile_data.get(lm.tile(*cell))
            if tile.has("WALL") or not tile.walk:
                continue
            out.append(cell)
            if tile.has("DOOR"):
                # A door bounds a room; you do not count the corridor beyond.
                continue
            frontier.append(cell)
    return out


def measure(fort, building) -> Room:
    """Work out what room a piece of furniture defines."""
    kind = ROOM_KINDS.get(building.kind, "room")
    cells = tuple(room_cells(fort.local, building.center))
    cellset = set(cells)

    furniture = 0
    for other in fort.buildings:
        if not other.built:
            continue
        if not any(c in cellset for c in other.cells()):
            continue
        value = FURNITURE_VALUE.get(other.kind, 0)
        if other is building:
            value = max(value, 1)
        furniture += value

    smoothed = 0
    for cell in cells:
        tile = tile_data.get(fort.local.tile(*cell))
        if tile.has("CONSTRUCTED"):
            smoothed += 1

    # Size counts, but only up to a point: a bedroom is not improved by being
    # a hall, and a hall is not a bedroom.
    size = min(len(cells), 24)
    quality = furniture * 2 + smoothed // 2 + size // 3
    return Room(kind, building.id, building.owner, cells, quality,
                furniture, smoothed)


def rooms(fort) -> List[Room]:
    """Every room in the fortress."""
    out: List[Room] = []
    for b in fort.buildings:
        if b.built and b.kind in ROOM_KINDS:
            out.append(measure(fort, b))
    return out


def room_of(fort, dwarf) -> Optional[Room]:
    """The bedroom assigned to a dwarf, if it has one."""
    bed_id = dwarf.fort.bed
    if bed_id is None:
        return None
    building = fort.building(bed_id)
    if building is None or not building.built:
        return None
    return measure(fort, building)


def dining_quality(fort) -> int:
    """The best dining room the fortress has, or zero."""
    best = 0
    for room in rooms(fort):
        if room.kind == "dining room":
            best = max(best, room.quality)
    return best


def value(fort) -> int:
    """Total room quality, which is part of what draws migrants."""
    return sum(r.quality for r in rooms(fort))
