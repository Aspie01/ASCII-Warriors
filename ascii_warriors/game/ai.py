"""Creature AI.

Needs-driven, not scripted: a creature looks around, decides what it wants
(safety, food, a fight, a bed) and takes one step toward it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..engine import geometry
from ..engine.fov import has_los
from ..engine.pathfind import astar
from ..engine.scheduler import ACTION_COST
from . import combat

#: Every mode a creature can be in, and the whole of it.
#:
#: Nothing read this tuple, so nothing kept it true. It listed "travel" and
#: "talk", which no code path can produce, and omitted "spin" and "stuck",
#: which `take_turn` assigns to a spider throwing a web and to anything caught
#: in one. Both lists were thirteen long, which is how it went unnoticed.
#:
#: `TestTheModesNobodyEnters` now derives this set from the source -- every
#: string `pick_mode` returns and every literal assigned to `ai.mode` -- and
#: fails when the two disagree, so the list cannot drift again while nothing
#: reads it.
MODES = (
    "idle", "wander", "hunt", "flee", "follow", "sleep", "guard", "graze",
    "forage", "lurk", "raise",
    # Set by `take_turn` rather than chosen by `pick_mode`.
    "spin", "stuck",
)


class AIState:
    """One creature's current intentions."""

    __slots__ = (
        "mode", "target_id", "home", "path", "alertness", "last_seen",
        "leader_id", "role", "patience", "site_id", "last_cost",
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
        #: What the last action actually cost. The stepping helpers return
        #: whether they did something, not how long it took, and only
        #: `_move_to` knows it ended in a swing rather than a step -- so it
        #: leaves the figure here for `take_turn` to charge. Not saved: it is
        #: spent the moment it is read.
        self.last_cost = 0

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
    """Every creature this one would attack and has actually noticed.

    Line of sight is not the same as having seen something. Somebody moving
    quietly in the dark is in plain view and still unnoticed, which is the
    entire point of moving quietly in the dark.
    """
    from . import stealth

    out = []
    for other in game.creatures.values():
        if other is creature or other.body.dead:
            continue
        if not creature.is_hostile_to(other):
            continue
        if not can_see(creature, other, game):
            continue
        if not stealth.noticed_by(game, other, creature):
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

    from . import feeding, wild

    # Hunger and thirst outrank fear, once they are bad enough. Fear is asked
    # first here and always was; the moment prey started running from
    # predators, a rabbit in sight of a fox fled until it died of thirst
    # standing on grass.
    if feeding.desperate(creature) and feeding.target_cell(creature, game):
        return "forage"

    # Still running from something it saw a moment ago. Fleeing has to last
    # more than one step or the animal simply gets shot where it stands.
    if wild.still_fleeing(creature):
        return "flee"

    # A deer does not wait to be attacked before it decides to leave, and
    # `opportunity_to_flee` below is about being hurt, which is a different
    # question with a different answer.
    scared_of = wild.frightener(game, creature)
    if scared_of is not None:
        wild.start_flight(creature, scared_of)
        return "flee"

    # Whatever it is short of comes before whatever it was doing. Both need
    # clocks kill, and until v3.23 nothing wild had ever eaten or drunk.
    if feeding.wants(creature) and feeding.target_cell(creature, game):
        return "forage"

    quarry = feeding.prey_for(creature, game)
    if quarry is not None:
        if ai is not None:
            # `pick_mode` may be asked about a creature whose AI state has
            # not been built yet -- `take_turn` builds it, and this is the
            # first branch here that ever wrote to it.
            ai.target_id = quarry.id
            ai.last_seen = (quarry.x, quarry.y, quarry.z)
        return "hunt"

    targets = hostile_targets(creature, game)
    if targets:
        ai.target_id = targets[0].id
        ai.last_seen = (targets[0].x, targets[0].y, targets[0].z)
        ai.alertness = 12
        if combat.opportunity_to_flee(creature, game):
            return "flee"
        # An ambusher does not cross a field at you. It waits.
        if wild.waiting(game, creature, targets[0]):
            return "lurk"
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
            result = combat.melee_attack(
                creature, occupant, rng=game.rng,
                log=game.log if game.can_see_creature(creature)
                or occupant.is_player else None,
                ground=game)
            creature.ai.last_cost = result.cost
            if result.killed:
                from . import feeding

                feeding.ate(creature, occupant)
            return True
        return False
    if not game.is_passable(x, y, z, creature):
        return False
    if game.local is not None:
        from . import swimming

        mode = getattr(creature.ai, "mode", "") if creature.ai else ""
        if swimming.avoids(
            creature,
            swimming.depth_of(game.local.tile(creature.x, creature.y, creature.z)),
            swimming.depth_of(game.local.tile(x, y, z)),
            desperate=(mode == "flee"),
        ):
            return False
    game.move_creature(creature, x, y, z)
    return True


def _spent(creature) -> int:
    """What the action just taken cost, defaulting to a standard action."""
    cost = creature.ai.last_cost or ACTION_COST
    creature.ai.last_cost = 0
    return cost


def take_turn(creature, game) -> int:
    """Run one AI turn; returns the energy cost of what it did."""
    if creature.ai is None:
        creature.ai = AIState()
    ai = creature.ai

    if not creature.can_act():
        return _spent(creature)

    # Before anything else: a necromancer with a corpse in front of it does
    # not chase you, it makes the corpse chase you.
    from . import night

    if night.necromancy_turn(game, creature):
        ai.mode = "raise"
        return _spent(creature)

    # Nor does a creature in a web go anywhere until it is out of it.
    from . import webs

    if webs.caught(game, creature):
        _free, said = webs.struggle(game, creature, game.rng)
        if said and game.can_see_creature(creature):
            game.log.info(said)
        ai.mode = "stuck"
        return _spent(creature)

    # A spinner throws one at what it is hunting, ahead of where that is now.
    if webs.spins(creature):
        prey = _web_prey(creature, game)
        if webs.maybe_spin(game, creature, prey, game.rng) is not None:
            ai.mode = "spin"
            if prey is not None and prey.is_player:
                game.log.warn("%s throws a web!" % creature.subject_name())
            return _spent(creature)

    mode = pick_mode(creature, game)
    ai.mode = mode

    if mode == "sleep":
        creature.needs.sleep(ACTION_COST)
        creature.body.rest_heal(ACTION_COST, creature.attributes.factor("recuperation"))
        return _spent(creature)

    if mode == "hunt":
        target = game.creatures.get(ai.target_id) if ai.target_id else None
        if target is None or target.body.dead:
            ai.target_id = None
            ai.last_seen = None
            _wander_step(creature, game)
            return _spent(creature)
        dist = creature.distance_to(target)
        if dist <= 1 and creature.z == target.z:
            visible = game.can_see_creature(creature) or target.is_player
            result = combat.melee_attack(creature, target, rng=game.rng,
                                         log=game.log if visible else None,
                                         ground=game)
            return result.cost
        # Shoot if we can.
        weapon = creature.inventory.weapon()
        ammo = creature.inventory.ammo()
        if (
            weapon is not None and weapon.is_ranged and ammo is not None
            and 2 <= dist <= 12 and can_see(creature, target, game)
        ):
            visible = game.can_see_creature(creature) or target.is_player
            combat.ranged_attack(creature, target, weapon, ammo,
                                 ground=game, rng=game.rng,
                                 log=game.log if visible else None)
            return _spent(creature)
        _step_toward(creature, game, target.x, target.y, target.z)
        return _spent(creature)

    if mode == "lurk":
        # Hold absolutely still. Moving is what gives a hidden thing away --
        # v3.6 charges ten points of stealth for a step -- so an ambusher
        # waiting in cover is an ambusher that stays in cover.
        return _spent(creature)

    if mode == "forage":
        from . import feeding

        # Standing in it is the common case, and costs nothing to check.
        if feeding.feed_here(creature, game):
            return _spent(creature)
        cell = feeding.target_cell(creature, game)
        if cell is not None:
            _step_toward(creature, game, *cell)
            feeding.feed_here(creature, game)
        else:
            _wander_step(creature, game)
        return _spent(creature)

    if mode == "flee":
        from . import wild

        target = game.creatures.get(ai.target_id) if ai.target_id else None
        took = wild.steal(game, creature, game.rng)
        if took is not None and game.can_see_creature(creature):
            game.log.warn("%s snatches %s and bolts."
                          % (creature.subject_name(),
                             took.name(article=True)))
        if target is not None:
            _step_away(creature, game, target.x, target.y)
        else:
            _wander_step(creature, game)
        return _spent(creature)

    if mode == "guard":
        if ai.home is not None:
            hx, hy, hz = ai.home
            if geometry.chebyshev(creature.x, creature.y, hx, hy) > 6 \
                    or creature.z != hz:
                _step_toward(creature, game, hx, hy, hz)
            elif game.rng.chance(0.4):
                _wander_step(creature, game)
        return _spent(creature)

    if mode == "follow":
        leader = game.creatures.get(ai.leader_id) if ai.leader_id else None
        if leader is not None and creature.distance_to(leader) > 3:
            _step_toward(creature, game, leader.x, leader.y, leader.z)
        elif game.rng.chance(0.3):
            _wander_step(creature, game)
        return _spent(creature)

    if mode in ("wander", "graze"):
        if game.rng.chance(0.75):
            _wander_step(creature, game)
        return _spent(creature)

    return _spent(creature)


def _web_prey(creature, game):
    """The nearest thing this spinner would like to hold still."""
    best, best_d = None, 999
    for other in game.creatures.values():
        if other is creature or not other.alive:
            continue
        if not creature.is_hostile_to(other):
            continue
        d = creature.distance_to(other)
        if d < best_d:
            best, best_d = other, d
    return best
