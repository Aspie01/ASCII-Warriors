"""What the world's record says about a named thing, and who keeps it true.

The histories know where every artifact is: which site it lies in, and whose
hands it is in there. `_quest_retrieve` reads exactly that -- *"It lies at
Blood Grave, a tomb"* -- and v3.53 finally put the thing on the floor for you
to pick up.

Nothing ever told the histories you had picked it up. `art.site_id` and
`art.holder_hf` still said it was in the tomb in a dead king's hands, which
makes the quest generator offer it again: a quest to fetch something already
in your pack, that no pickup can ever complete because the pickup already
happened. Measured: take *The Bridge of the Tower* off its holder, ask around,
and the eighteenth offer is a quest to go and get it. State active, progress
zero of one, and nothing at the site to change that.

So the record follows the object. One funnel per direction -- `took` when
something reaches the player's hands and `gave_up` when it leaves them,
whether that is dropping it, selling it, or dying with it -- because the
number of ways to acquire something only ever goes up.

The other half is seats. A tower's `owner_hf` and a town's `ruler_hf` are
historical facts and stay true after their holder dies -- Ustgath the Foul did
hold that tower -- so the fix is not to erase them but to stop the readers
saying "is" about a person the same screen records the death of.
"""

from __future__ import annotations

from typing import Any, Optional

from ..world.history import record


def artifact_of(world, item) -> Optional[Any]:
    """The world's record for this item, if it is a named artifact."""
    aid = getattr(item, "artifact_id", None)
    if aid is None:
        return None
    return next((a for a in world.artifacts if a.id == aid), None)


def took(game, item) -> bool:
    """The player has it now. True if the record had to change.

    An artifact on a wandering adventurer is at no site, which is what takes
    it out of `_quest_retrieve`'s pool: that generator asks for artifacts with
    a site to send somebody to, and there is no longer anywhere to send them.
    """
    from . import renown as renown_mod

    art = artifact_of(game.world, item)
    if art is None:
        return False
    fig = renown_mod.figure(game)
    if art.holder_hf == fig.id and art.site_id is None:
        return False
    site = game.world.site(art.site_id) if art.site_id else None
    art.holder_hf = fig.id
    art.site_id = None
    art.lost = False
    record(
        game.world, game.time.year, "artifact_stolen",
        "%s took %s%s." % (fig.display_name, art.name,
                           " from %s" % site.name if site is not None else ""),
        [fig.id], [site.id] if site is not None else [],
    )
    return True


def gave_up(game, item, *, by=None, to=None) -> bool:
    """It is out of those hands: dropped, sold, or fallen with the body.

    *by* is who had it and *to* is who has it now, either of which may be
    nobody -- an artifact dropped on a floor is held by no one. The record
    moves to wherever this is happening, so a crown sold in a town is a crown
    the histories place in that town, and one somebody can be sent after
    again. That is the point of keeping it: an artifact with a site is a
    quest, and an artifact with nothing is a rumour.
    """
    art = artifact_of(game.world, item)
    if art is None:
        return False
    site = game.current_site()
    art.holder_hf = getattr(to, "hf_id", None) if to is not None else None
    art.site_id = site.id if site is not None else None
    # Nowhere anybody could be sent, so the histories say so rather than
    # pretend to know. Picking it up again clears it.
    art.lost = art.site_id is None and art.holder_hf is None
    if by is not None and getattr(by, "is_player", False):
        holder = game.world.figures.get(art.holder_hf) if art.holder_hf else None
        record(
            game.world, game.time.year, "artifact_stolen",
            "%s let %s go%s%s." % (
                by.display_name(), art.name,
                " to %s" % holder.display_name if holder is not None else "",
                " at %s" % site.name if site is not None else ""),
            [game.player.hf_id] if game.player.hf_id else [],
            [art.site_id] if art.site_id else [],
        )
    return True


def on_death(game, creature) -> int:
    """Whatever this one was carrying is on the floor now.

    Called from `Game.kill_creature`, where the corpse's inventory is already
    being emptied onto the ground -- so the record has to follow it there or
    the histories go on naming a dead man as the holder of a crown lying at
    his feet.
    """
    moved = 0
    for item in list(creature.inventory.items):
        if gave_up(game, item, by=creature):
            moved += 1
    return moved
