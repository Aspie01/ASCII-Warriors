"""Putting the world's named artifacts into the world.

A world's histories forge artifacts, name them, remember who made each one and
where it ended up, and `_quest_retrieve` sends the player after one by name:
*"It lies at Blood Grave, a tomb."* Nothing ever put it there. `sitegen` has
never mentioned artifacts, `Item.artifact_id` was read, copied and saved and
**written nowhere**, and `quests.on_pickup` matches on exactly that field — so
a retrieve-the-artifact quest could be accepted, could be walked to, and could
not be finished by anybody.

Placed on arrival rather than at worldgen, for the reason the traps are: a
floor to lie on is part of a floor plan, and floor plans are made when the
player walks in.
"""

from __future__ import annotations

from typing import Any, List, Optional

from ..engine.rng import RNG
from .item import make_item

#: What an artifact is worth as a piece of work. The histories already say it
#: is the best thing anybody ever made; the item table's top grade says the
#: same in the language the rest of the game speaks.
ARTIFACT_QUALITY = 5


def at_site(world, site_id: Optional[int]) -> List[Any]:
    """Every artifact the histories place at a site."""
    if site_id is None:
        return []
    return [a for a in world.artifacts
            if a.site_id == site_id and not a.lost]


def make(art, rng: RNG):
    """The item an artifact record describes."""
    it = make_item(rng, art.item_def, material=art.material or None,
                   quality=ARTIFACT_QUALITY)
    it.artifact_id = art.id
    it.name_override = art.name
    return it


def populate(game, site, rng: RNG) -> int:
    """Put this site's artifacts where the histories say they are.

    In the hands of whoever holds it if that figure is standing here -- taking
    a crown off a king is a different evening from picking one off the floor --
    and otherwise on the ground, deep in the site rather than by the door.
    Returns how many went in.
    """
    if site is None or game.local is None:
        return 0
    made = 0
    carried = {getattr(i, "artifact_id", None)
               for i in game.player.inventory.items}
    for art in at_site(game.world, getattr(site, "id", None)):
        if art.id in carried:
            # Already taken. The local map cache holds twenty-four tiles and
            # then evicts, so a site revisited after a long journey is built
            # again from scratch -- and without this the crown you are wearing
            # is lying on the floor of the tomb you took it from, as often as
            # you care to walk back.
            continue
        it = make(art, rng)
        holder = None
        if art.holder_hf is not None:
            holder = next((c for c in game.creatures.values()
                           if c.hf_id == art.holder_hf and not c.body.dead),
                          None)
        if holder is not None:
            holder.inventory.add(it)
        else:
            cell = game.local.random_open(rng)
            if cell is None:
                continue
            game.drop_item(it, *cell)
        made += 1
    return made
