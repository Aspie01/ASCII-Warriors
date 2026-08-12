"""Hired companions.

Mercenaries and tavern patrons will travel with you for coin. They follow you
between world tiles, fight what you fight, and complain when you do not feed
them.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from ..engine import colors
from ..engine.screen import Frag

#: How many companions one adventurer can lead at once, before Leader skill.
BASE_PARTY_SIZE = 2
#: Roughly what a fighter of a given calibre asks for up front.
BASE_HIRE_PRICE = 60


def party_limit(player) -> int:
    """How many companions the player can lead."""
    leadership = player.skills.level("leadership")
    social = player.attributes.factor("social_awareness")
    return max(1, int(round(
        BASE_PARTY_SIZE + leadership / 4.0 + (social - 1.0) * 1.5)))


def can_recruit(npc) -> bool:
    """True if this NPC is the sort who hires out."""
    if npc.body.dead or not npc.defn.has("CAN_SPEAK"):
        return False
    if npc.faction == "hostile":
        return False
    if npc.speech.get("companion"):
        return False
    role = npc.ai.role if npc.ai else ""
    return role in ("patron", "citizen", "guard") or npc.profession in (
        "bandit", "guard", "hunter", "soldier", "warrior", "peasant", "archer",
    )


def hire_price(npc, player) -> int:
    """What this NPC asks to join you."""
    prowess = npc.skills.level("fighter") + npc.skills.total_levels() // 4
    greed = npc.personality.greed_factor()
    price = BASE_HIRE_PRICE * (1.0 + prowess * 0.35) * greed
    # A persuasive leader talks the price down.
    price *= max(0.5, 1.0 - player.skills.level("persuasion") * 0.02)
    return max(10, int(round(price)))


def companions_of(game) -> List[Any]:
    """Every living companion currently following the player."""
    return [
        game.creatures[cid] for cid in game.companion_ids
        if cid in game.creatures and not game.creatures[cid].body.dead
    ]


def recruit(game, npc) -> Tuple[bool, str]:
    """Try to hire an NPC. Returns ``(ok, message)``."""
    from .ai import AIState

    player = game.player
    if npc.speech.get("companion"):
        return (False, "%s already travels with you." % npc.display_name())
    if len(companions_of(game)) >= party_limit(player):
        return (False, "You cannot lead any more followers.")
    if not can_recruit(npc):
        return (False, "%s has no interest in wandering." % npc.display_name())

    price = hire_price(npc, player)
    if player.inventory.coins() < price:
        return (False, "%s wants %d coins to come with you." % (
            npc.display_name(), price))

    bravery = npc.personality.facet("bravery")
    if bravery < 20 and game.rng.chance(0.5):
        return (False, '"Out there? Not for any money."')

    player.inventory.spend_coins(price)
    from .item import Item

    npc.inventory.add(Item("coin", "silver", count=price))

    npc.faction = "player"
    npc.speech["companion"] = True
    if npc.ai is None:
        npc.ai = AIState("follow")
    npc.ai.role = "companion"
    npc.ai.mode = "follow"
    npc.ai.leader_id = player.id
    npc.inventory.auto_equip()
    game.companion_ids.append(npc.id)
    player.add_exp("leadership", 60)
    player.add_exp("persuasion", 30)
    return (True, "%s joins you for %d coins." % (npc.display_name(), price))


def dismiss(game, npc) -> Tuple[bool, str]:
    """Send a companion on their way."""
    if npc.id not in game.companion_ids:
        return (False, "%s is not following you." % npc.display_name())
    game.companion_ids.remove(npc.id)
    npc.speech.pop("companion", None)
    npc.faction = "town"
    if npc.ai is not None:
        npc.ai.role = ""
        npc.ai.leader_id = None
        npc.ai.mode = "wander"
    return (True, "%s parts ways with you." % npc.display_name())


def bring_along(game, positions_from) -> None:
    """Place the player's companions around them on a newly entered map.

    Called after the player has been positioned. Companions are kept out of the
    per-tile creature cache so they never get left behind or duplicated.
    """
    player = game.player
    placed = 0
    for npc in list(game.travelling_companions):
        spot = _free_spot_near(game, player, placed)
        npc.x, npc.y, npc.z = spot
        npc.wx, npc.wy = player.wx, player.wy
        if npc.ai is not None:
            npc.ai.leader_id = player.id
            npc.ai.home = spot
        game.add_creature(npc)
        placed += 1
    game.travelling_companions = []


def _free_spot_near(game, player, offset: int) -> Tuple[int, int, int]:
    """A walkable cell next to the player, or the player's own cell."""
    from ..engine.geometry import DIRS8

    order = list(DIRS8[offset % len(DIRS8):]) + list(DIRS8[: offset % len(DIRS8)])
    for dx, dy in order:
        x, y, z = player.x + dx, player.y + dy, player.z
        if game.is_passable(x, y, z) and game.creature_at(x, y, z) is None:
            return (x, y, z)
    for radius in range(2, 6):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                x, y, z = player.x + dx, player.y + dy, player.z
                if game.is_passable(x, y, z) and game.creature_at(x, y, z) is None:
                    return (x, y, z)
    return (player.x, player.y, player.z)


def status_lines(game) -> List[Frag]:
    """Sidebar lines describing the party."""
    out: List[Frag] = []
    for npc in companions_of(game):
        health = npc.body.health_fraction()
        colour = (colors.UI["good"] if health > 0.6 else
                  colors.UI["warn"] if health > 0.3 else colors.UI["danger"])
        out.append(Frag("%s  %d%%" % (
            npc.display_name()[:18], int(health * 100)), colour))
    return out


def on_death(game, npc) -> None:
    """Drop a companion from the party when they are killed."""
    if npc.id in game.companion_ids:
        game.companion_ids.remove(npc.id)
        game.log.bad("%s has fallen." % npc.display_name())
        game.player.needs.add_thought("lost a companion", 25)
