"""What a fortress leaves standing.

The README has promised, since it was written, that an adventurer can travel to
a fortress they lost and walk into it: "the corridors you dug, the workshops
you raised, the goods still on the floor, and your dwarves lying where they
fell." Three of those four were true. `legacy.preserve` froze the buildings
along with everything else and `legacy.restore` handed back the map, the
creatures and the items and quietly dropped them, so every workshop in the
place became bare floor.

They come back as *ruins* rather than as buildings. An adventurer cannot queue
an order at a forge, and pretending otherwise would mean carrying the whole
job board into the other mode for one screen nobody would open. What a ruin
does is stand there, take up its footprint, draw itself, and answer the look
cursor -- which is the whole of what the promise was about.

Only the workshops come across; see `marks_the_ground` for why the other
two dozen kinds of building do not need to.

The payload is `Building.to_dict`'s, kept as plain data on purpose: this module
reads a shape that the fortress writes, and neither mode has to import the
other's classes to do it.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

from ..engine import colors


def _defn(ruin: Mapping[str, Any]):
    """The building kind this ruin was, or None if it is not one we know."""
    from ..fortress.buildings import KINDS

    return KINDS.get(str(ruin.get("kind", "")))


def marks_the_ground(defn) -> bool:
    """Whether this kind of building leaves anything the frozen map does not.

    A building stamps a tile when it goes up, and the map is frozen along with
    everything else, so a statue already *is* a statue tile and a lever a lever
    tile. Carrying those across would draw the same glyph on top of itself and
    make the look cursor name the thing twice. What a tile cannot record is a
    workshop: eleven of the twelve stand on plain smooth floor and the hospital
    on a bed, so the floor of a dead fortress kept no sign of them at all --
    which is exactly the clause of the promise that was broken.

    Comparing the two glyphs lets the set work itself out, so a workshop added
    later is carried without anybody remembering to come back here.
    """
    from ..world import tiles as tile_data

    return tile_data.get(defn.tile).glyph != defn.glyph


def left_standing(buildings) -> List[dict]:
    """The buildings from a preserved fortress worth carrying into ruins."""
    out: List[dict] = []
    for b in buildings or ():
        defn = _defn(b)
        if defn is not None and marks_the_ground(defn):
            out.append(dict(b))
    return out


def cells(ruin: Mapping[str, Any]) -> List[Tuple[int, int, int]]:
    """Every cell this ruin covers.

    Worked out from the footprint rather than stored, because that is how the
    fortress works it out and two copies of a rectangle is one too many.
    """
    defn = _defn(ruin)
    if defn is None:
        return []
    x, y, z = int(ruin.get("x", 0)), int(ruin.get("y", 0)), int(ruin.get("z", 0))
    return [(x + dx, y + dy, z)
            for dy in range(defn.height)
            for dx in range(defn.width)]


def appearance(ruin: Mapping[str, Any]):
    """``(glyph, colour, cells)`` for drawing, or ``(None, None, [])``."""
    defn = _defn(ruin)
    if defn is None:
        return (None, None, [])
    # Faded: it has been standing empty since whatever ended the fortress.
    return (defn.glyph, colors.darken(defn.color, 0.75), cells(ruin))


def at(game, x: int, y: int, z: int) -> Optional[Mapping[str, Any]]:
    """The ruin covering a cell, if any."""
    for ruin in getattr(game, "ruins", ()) or ():
        if (x, y, z) in cells(ruin):
            return ruin
    return None


def describe(ruin: Mapping[str, Any]) -> str:
    """What the look cursor says about it."""
    defn = _defn(ruin)
    if defn is None:
        return ""
    # Named the way the fortress named it: material first, and the kind's own
    # name lowered so "Metalsmith's forge" reads as "steel metalsmith's forge".
    material = str(ruin.get("material_name") or "").strip()
    name = "%s %s" % (material, defn.name.lower()) if material else defn.name
    return "%s, long abandoned." % name
