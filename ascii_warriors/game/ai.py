"""Creature AI.

Needs-driven, not scripted: a creature looks around, decides what it wants
(safety, food, a fight, a bed) and takes one step toward it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..engine import geometry
from ..engine.fov import has_los
from ..engine.pathfind import astar
from ..engine.scheduler import ACTION_COST
from . import combat

MODES = (
    "idle", "wander", "hunt", "flee", "follow", "sleep", "guard", "graze",
    "travel", "talk",
)


class AIState:
    """One creature's current intentions."""

    __slots__ = (
        "mode", "target_id", "home", "path", "alertness", "last_seen",
        "leader_id", "role", "patience", "site_id",
    )

    def __init__(self, mode: str = "idle", role: str = "") -> None:
        self.mode = mode
        self.target_id: Optional[int] = None
        self.home: Optional[Tuple[int, int, int]] = None
        self.path: List[Tuple[int, int, int]] = []
        self.alertness = 0
        self.last_seen: Optional[Tuple[int, int, int]] = None
        self.leader_id: Optional[int] = None
        self.role = role
        self.patience = 0
        self.site_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the AI state."""
        return {
            "mode": self.mode, "target": self.target_id,
            "home": list(self.home) if self.home else None,
            "alert": self.alertness,
            "seen": list(self.last_seen) if self.last_seen else None,
            "leader": self.leader_id, "role": self.role,
            "patience": self.patience, "site": self.site_id,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "AIState":
        """Rebuild from :meth:`to_dict`."""
        a = cls(str(d.get("mode", "idle")), str(d.get("role", "")))
        a.target_id = d.get("target")
        home = d.get("home")
        a.home = tuple(home) if home else None
        a.alertness = int(d.get("alert", 0))
        seen = d.get("seen")
        a.last_seen = tuple(seen) if seen else None
        a.leader_id = d.get("leader")
        a.patience = int(d.get("patience", 0))
        a.site_id = d.get("site")
        return a

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "AIState(%s, target=%s)" % (self.mode, self.target_id)


# --------------------------------------------------------------------------- #
# Perception
# --------------------------------------------------------------------------- #


def can_see(creature, other, game) -> bool:
    """True if *creature* can currently see *other*."""
    if creature.z != other.z:
        return False
    dist = creature.distance_to(other)
    light = game.light_at(other.x, other.y, other.z)
    if dist > creature.sight_radius(light):
        return False
    if not creature.body.can_see():
        return dist <= 1
    z = creature.z
    return has_los(
        creature.x, creature.y, other.x, other.y,
        lambda x, y: game.local.blocks_sight(x, y, z),
    )


def hostile_targets(creature, game) -> List[Any]:
    """Every visible creature this one would attack, nearest first."""
    out = []
    for other in game.creatures.values():
        if other is creature or other.body.dead:
            continue
        if not creature.is_hostile_to(other):
            continue
        if not can_see(creature, other, game):
            continue
        out.append(other)
    out.sort(key=creature.distance_to)
    return out


def allies_near(creature, game, radius: int = 8) -> List[Any]:
    """Same-faction creatures within *radius*."""
    return [
        c for c in game.creatures.values()
        if c is not creature and not c.body.dead and c.faction == creature.faction
        and c.z == creature.z and creature.distance_to(c) <= radius
    ]


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #


def pick_mode(creature, game) -> str:
    """Decide what this creature wants to do right now."""
    ai = creature.ai
    defn = creature.defn

    if creature.body.unconscious > 0:
        return "sleep"

    targets = hostile_targets(creature, game)
    if targets:
        ai.target_id = targets[0].id
        ai.last_seen = (targets[0].x, targets[0].y, targets[0].z)
        ai.alertness = 12
        if combat.opportunity_to_flee(creature):
            return "flee"
        return "hunt"

    if ai.alertness > 0:
        ai.alertness -= 1
        if ai.last_seen is not None:
            return "hunt"

    if not defn.has("NO_SLEEP") and creature.needs.drowsy > 12000:
        if game.time.is_night() or creature.needs.drowsy > 18000:
            return "sleep"

    if ai.role == "guard" and ai.home is not None:
        return "guard"
    if defn.has("GRAZER") and game.rng.chance(0.3):
        return "graze"
    if ai.leader_id is not None and ai.leader_id in game.creatures:
        return "follow"
    if game.rng.chance(0.55):
        return "wander"
    return "idle"


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


def _step_toward(creature, game, tx: int, ty: int, tz: int) -> bool:
    """Take one step along a path to a target; True if the creature moved."""
    ai = creature.ai
    start = (creature.x, creature.y, creature.z)
    goal = (tx, ty, tz)

    if ai.path and ai.path[-1] == goal and start in ai.path:
        idx = ai.path.index(start)
        if idx + 1 < len(ai.path):
            nxt = ai.path[idx + 1]
            if game.is_passable(nxt[0], nxt[1], nxt[2], creature):
                return _move_to(creature, game, nxt)
    path = astar(
        start, goal, game.local.path_neighbours,
        lambda a, b: geometry.chebyshev(a[0], a[1], b[0], b[1]) + abs(a[2] - b[2]),
        max_nodes=3000,
    )
    if not path or len(path) < 2:
        # No route; shuffle in roughly the right direction instead.
        dx, dy = geometry.normalize_dir(tx - creature.x, ty - creature.y)
        return _move_to(creature, game, (creature.x + dx, creature.y + dy, creature.z))
    ai.path = path
    return _move_to(creature, game, path[1])


def _step_away(creature, game, tx: int, ty: int) -> bool:
    """Take one step directly away from a threat."""
    dx, dy = geometry.normalize_dir(creature.x - tx, creature.y - ty)
    options = [
        (creature.x + dx, creature.y + dy, creature.z),
        (creature.x + dx, creature.y, creature.z),
        (creature.x, creature.y + dy, creature.z),
    ]
    for opt in options:
        if game.is_passable(opt[0], opt[1], opt[2], creature):
            return _move_to(creature, game, opt)
    return _wander_step(creature, game)


def _wander_step(creature, game) -> bool:
    """Take a random step."""
    for _ in range(6):
        dx, dy = game.rng.dir8()
        nxt = (creature.x + dx, creature.y + dy, creature.z)
        if game.is_passable(nxt[0], nxt[1], nxt[2], creature):
            return _move_to(creature, game, nxt)
    return False


def _move_to(creature, game, cell: Tuple[int, int, int]) -> bool:
    """Move a creature into a cell, or attack whatever is standing there."""
    x, y, z = cell
    occupant = game.creature_at(x, y, z)
    if occupant is not None and occupant is not creature:
        if creature.is_hostile_to(occupant):
            combat.melee_attack(creature, occupant, rng=game.rng,
                                log=game.log if game.can_see_creature(creature)
                                or occupant.is_player else None)
            return True
        return False
    if not game.is_passable(x, y, z, creature):
        return False
    game.move_creature(creature, x, y, z)
    return True


def take_turn(creature, game) -> int:
    """Run one AI turn; returns the energy cost of what it did."""
    if creature.ai is None:
        creature.ai = AIState()
    ai = creature.ai

    if not creature.can_act():
        return ACTION_COST

    mode = pick_mode(creature, game)
    ai.mode = mode

    if mode == "sleep":
        creature.needs.sleep(ACTION_COST)
        creature.body.rest_heal(ACTION_COST, creature.attributes.factor("recuperation"))
        return ACTION_COST

    if mode == "hunt":
        target = game.creatures.get(ai.target_id) if ai.target_id else None
        if target is None or target.body.dead:
            ai.target_id = None
            ai.last_seen = None
            _wander_step(creature, game)
            return ACTION_COST
        dist = creature.distance_to(target)
        if dist <= 1 and creature.z == target.z:
            visible = game.can_see_creature(creature) or target.is_player
            combat.melee_attack(creature, target, rng=game.rng,
                                log=game.log if visible else None)
            return ACTION_COST
        # Shoot if we can.
        weapon = creature.inventory.weapon()
        ammo = creature.inventory.ammo()
        if (
            weapon is not None and weapon.is_ranged and ammo is not None
            and 2 <= dist <= 12 and can_see(creature, target, game)
        ):
            visible = game.can_see_creature(creature) or target.is_player
            combat.ranged_attack(creature, target, weapon, ammo, rng=game.rng,
                                 log=game.log if visible else None)
            return ACTION_COST
        _step_toward(creature, game, target.x, target.y, target.z)
        return ACTION_COST

    if mode == "flee":
        target = game.creatures.get(ai.target_id) if ai.target_id else None
        if target is not None:
            _step_away(creature, game, target.x, target.y)
        else:
            _wander_step(creature, game)
        return ACTION_COST

    if mode == "guard":
        if ai.home is not None:
            hx, hy, hz = ai.home
            if geometry.chebyshev(creature.x, creature.y, hx, hy) > 6 \
                    or creature.z != hz:
                _step_toward(creature, game, hx, hy, hz)
            elif game.rng.chance(0.4):
                _wander_step(creature, game)
        return ACTION_COST

    if mode == "follow":
        leader = game.creatures.get(ai.leader_id) if ai.leader_id else None
        if leader is not None and creature.distance_to(leader) > 3:
            _step_toward(creature, game, leader.x, leader.y, leader.z)
        elif game.rng.chance(0.3):
            _wander_step(creature, game)
        return ACTION_COST

    if mode in ("wander", "graze"):
        if game.rng.chance(0.75):
            _wander_step(creature, game)
        return ACTION_COST

    return ACTION_COST
