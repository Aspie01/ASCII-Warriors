"""What a room has in it besides the people.

`traps.populate` and `artifacts.populate` already put things into a site when
the player walks into it, for the reason a floor plan is made there rather
than at worldgen. This is the third of them: the things a place keeps because
of what it is for.

A tavern keeps instruments. The performance system has scored a bonus for the
right instrument in the performer's hands and a smaller one for the wrong
instrument lying in the room since it was written -- `instrument_for`'s own
docstring says a fortress that crafted every instrument in the game would
otherwise perform identically without them -- and in adventure mode no tavern
in any world had ever contained one. Six instrument definitions, a bonus
nothing could earn, and every song in every tavern played on nothing.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ..data import items as item_data
from ..engine.rng import RNG

#: The tile a tavern is made of.
TAVERN = "tavern"

#: How many instruments a house keeps. Enough that a form usually finds the
#: one it wants, few enough that a tavern is not a music shop.
HOUSE_INSTRUMENTS = (1, 3)


def instruments() -> List[str]:
    """Every item the table calls an instrument."""
    return sorted(i.id for i in item_data.ITEMS.values() if i.has("INSTRUMENT"))


def _wanted_here(world, site) -> List[str]:
    """The instruments the music of this place actually calls for.

    Drawn from the civilization's own forms, so the drum in the corner is the
    drum its songs were written for and the bonus is one somebody can earn.
    """
    civ_id = getattr(site, "civ_id", None)
    mine = [f.instrument for f in world.forms
            if f.kind == "music" and f.instrument
            and (civ_id is None or f.civ_id == civ_id)]
    known = set(instruments())
    return [i for i in mine if i in known]


def populate(game, site, rng: RNG) -> int:
    """Furnish a site's rooms. Returns how many things went in."""
    if site is None or game.local is None:
        return 0
    cells = _tavern_cells(game.local)
    if not cells:
        return 0
    wanted = _wanted_here(game.world, site) or instruments()
    if not wanted:
        return 0
    from .item import make_item

    placed = 0
    for _ in range(rng.randint(*HOUSE_INSTRUMENTS)):
        cell = rng.choice(cells)
        game.drop_item(make_item(rng, rng.choice(wanted)), *cell)
        placed += 1
    return placed


def _tavern_cells(lm) -> List[Tuple[int, int, int]]:
    """Every floor tile of every tavern on this map."""
    out: List[Tuple[int, int, int]] = []
    for z, level in lm.levels.items():
        for i, tid in enumerate(level):
            if tid == TAVERN:
                out.append((i % lm.width, i // lm.width, z))
    return out
