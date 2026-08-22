"""Play an adventurer, sensibly, for a long time, and report what happened.

`smoke` proves the screens fit together and `fuzz` presses keys at random.
Neither of them plays: the fortress has been measured by simulating a year and
looking at the wreckage since v3.46 -- five defects came out of it, including a
fortress that died of thirst with two thousand units of ale in the stockpile --
and adventure mode had no equivalent.

This is that equivalent. It drives the real action layer through
`Game.player_acts`, the way the play screen does.

v3.51 gave it a body to look after: drink when thirsty, eat when hungry, sleep
when tired, hit what is next to it, otherwise wander. That found three defects
and then measured nothing else for a dozen versions, because looking after a
body is not playing this game. The other nine tenths of adventure mode was
never driven by anything: travel, a town, somebody to talk to, work to take, a
place the work points at, the thing waiting there, and the walk back to be
paid. The README spends most of its words on that loop and nothing had ever
walked it.

So it plays the errand now. In priority order it looks after itself, fights
what is next to it, does the job it is standing on, reports work that is
finished, asks for work when it has none, and otherwise travels toward
whatever it is supposed to be doing.

    python -m tools.play --seed adv1 --turns 16000

The point is the invariants at the bottom. A run that ends with an adventurer
dead of thirst beside a river, with needs that never moved, or holding four
jobs it was never told where to do, is a bug report.
"""

from __future__ import annotations

import argparse
import collections
import sys
import time
from typing import Optional, Sequence

from ascii_warriors.engine import geometry
from ascii_warriors.engine.pathfind import astar
from ascii_warriors.engine.rng import RNG
from ascii_warriors.game import actions
from ascii_warriors.game import conversation as conv
from ascii_warriors.game.state import Game
from ascii_warriors.world.worldgen import generate_world
from tools import scratch_saves

#: Ticks of game time below which "nobody got thirsty" says nothing, and the
#: thirst a working clock has to have produced by then.
#:
#: Thirst climbs about a point a tick before anybody drinks, so six hundred
#: ticks clears a floor of a hundred six times over -- wide enough that no
#: honest run trips it, and short enough to still catch a clock that has
#: stopped. The shortest life measured (36 ticks) is never asked the question.
CLOCK_ENOUGH = 600
CLOCK_FLOOR = 100

#: Blood left, as a fraction, at which the driver stops fighting and sees to
#: itself. A starting warrior who trades blows until the end dies on turn 51
#: and measures nothing past it.
PATCH_UP_AT = 0.85
RUN_AWAY_AT = 0.62
#: And the point at which you bind it whatever is standing over you.
BIND_IT_NOW = 0.75

#: Blood left at which a quiet moment is worth spending on resting rather
#: than on walking somewhere. Above `PATCH_UP_AT`, because binding closes
#: wounds and only time puts the blood back.
REST_UP_AT = 0.92

#: How long one sit-down is. An hour, which is what `R` does on the keyboard.
REST_TICKS = 600

#: Needs at which the driver stops what it is doing and sees to itself. Below
#: the fatal thresholds by a wide margin, because a player who waits for
#: `THIRST_DEATH` is not testing the game, they are testing the clock.
THIRSTY = 12000
HUNGRY = 16000
SLEEPY = 18000


def _look_after(game, why) -> Optional[int]:
    """Deal with whatever the body is complaining about. Returns a cost.

    Returns None when it could not: an action that did not happen must not
    claim the turn, or the driver spends the run pressing a key that does
    nothing. It did exactly that -- 3971 of 4000 turns on "nothing to
    drink" -- and the invariants at the bottom never noticed, because needs
    that are pinned at the ceiling have certainly moved.
    """
    p = game.player
    # Before anything else: your head is under water. A player gets out; the
    # driver stood in the river trading blows with a goblin and drowned
    # holding a sword, and the run reported it as "dead=True drowned" with
    # nothing in the log about water.
    cost = _get_out_of_the_water(game, why)
    if cost is not None:
        return cost
    cost = _staunch(game, why)
    if cost is not None:
        return cost
    cost = _loot(game, why)
    if cost is not None:
        return cost
    # Top up whenever you are standing at water, not only when parched. A
    # waterskin holds four and the driver crossed three rivers with an empty
    # one and died of thirst in the next desert.
    if (actions.water_source_near(game)
            and p.inventory.by_def("waterskin")
            and p.inventory.count_of("water_drink")
            < 4 * len(p.inventory.by_def("waterskin"))):
        why["filled the skin"] += 1
        return actions.drink(game)
    if p.needs.thirst > THIRSTY:
        cost = actions.drink(game)
        if cost > 0:
            why["drank"] += 1
            return cost
        why["nothing to drink"] += 1
        return _find_water(game, why)
    if p.needs.hunger > HUNGRY:
        food = next((i for i in p.inventory.items if i.defn.nutrition), None)
        cost = actions.eat(game, food) if food is not None else 0
        if cost > 0:
            why["ate"] += 1
            return cost
        why["nothing to eat"] += 1
        return None
    if p.needs.drowsy > SLEEPY:
        cost = actions.sleep(game, 8)
        if cost > 0:
            why["slept"] += 1
            return cost
        # Something is watching. You cannot sleep, so do anything else.
        why["could not sleep for the company"] += 1
        return None
    return None


def _staunch(game, why) -> Optional[int]:
    """Bandage what is bleeding, when there is a moment to do it in.

    Or when there is not: past `BIND_IT_NOW` the bleeding is what is going to
    kill you and the thing in front of you is not, so you spend the turn.
    """
    from ascii_warriors.game import medical

    p = game.player
    blood = p.body.blood_fraction()
    if blood > PATCH_UP_AT:
        return None
    if _adjacent_foe(game) is not None and blood > BIND_IT_NOW:
        return None
    # And not at all, with something still on you, once the wounds are
    # arriving faster than the bandages close them. Traced on a doomed run:
    # seventeen consecutive turns of binding in a four-way melee, fourteen
    # points closed each time and twelve more arriving, the total climbing
    # from forty to a hundred and twenty-four against a ceiling of
    # thirty-seven, and it bled out with a bandage in its hand. Binding was
    # not the wrong verb, it was the wrong turn -- and because `_staunch` is
    # asked before `_run_away`, taking the turn every time is how the driver
    # came to run away twenty-nine times in five thousand eight hundred.
    if _outrun_by_the_bleeding(game) and _adjacent_foe(game) is not None:
        return None
    if not medical.treatable(p):
        return None
    said = medical.auto_treat(p, rng=game.rng)
    text = " ".join(getattr(f, "text", "") for f in said)
    if "nothing you can do" in text:
        # Out of bandages, still bleeding, and wearing four of them. Tearing
        # up a shirt is what a person does, and until now the driver bled to
        # death with the answer in its own pack: seven runs in eight ended
        # with the third bandage spent and "nothing to bind it with" counted
        # sixteen, nineteen, fifty-two times before it fell over.
        if _tear_a_bandage(game, why):
            return actions.NORMAL
        why["bleeding, and nothing to bind it with"] += 1
        return None
    why["patched itself up"] += 1
    return actions.NORMAL


def _tear_a_bandage(game, why) -> bool:
    """Rip up a garment for dressings. True if there was one to rip."""
    from ascii_warriors.game import crafting

    recipe = crafting.RECIPES.get("make_bandage")
    if recipe is None:
        return False
    made, _msg = crafting.craft(game.player, recipe, game)
    if made:
        why["tore up a shirt"] += 1
    return bool(made)


def _outrun_by_the_bleeding(game) -> bool:
    """True when no amount of binding will bring the rate down this turn.

    `Body.bleeding_rate` is capped at `BLEED_CAP` of the body's own volume,
    so past that ceiling the number on the screen stops moving however many
    wounds you close. That is the moment to stop closing them and leave.
    """
    from ascii_warriors.game.body import BLEED_CAP

    body = game.player.body
    return body.bleeding_rate() >= body.max_blood * BLEED_CAP - 1e-9


def _rest_up(game, why) -> Optional[int]:
    """Sit down and bleed less, once there is nobody watching.

    The other half of running. Breaking contact is only worth the turns if
    something is done with the quiet afterwards, and an hour of rest is worth
    about a third of a litre -- which is most of what a bad fight costs.
    """
    p = game.player
    if p.body.blood_fraction() > REST_UP_AT or game.hostiles_in_sight():
        return None
    if p.needs.thirst > THIRSTY or p.needs.hunger > HUNGRY:
        return None
    cost = actions.rest(game, REST_TICKS)
    if cost <= 0:
        return None
    why["rested"] += 1
    return cost


def _run_away(game, why) -> Optional[int]:
    """Back off from whatever is hitting you, when you are losing.

    The step that puts the most ground between you and the nearest of them,
    not the sum of the directions they are in. Summing was the old rule and
    it has one arrangement it cannot handle: four foes evenly around you add
    up to nothing at all, `ax == ay == 0`, and the driver stood in the middle
    of them and fought. That is the arrangement it most needed to leave.
    """
    p = game.player
    if p.body.blood_fraction() > RUN_AWAY_AT \
            and not _outrun_by_the_bleeding(game):
        return None
    foes = [c for c in game.creatures.values()
            if not c.body.dead and not c.is_player and c.is_hostile_to(p)
            and max(abs(c.x - p.x), abs(c.y - p.y)) <= 2 and c.z == p.z]
    if not foes or game.local is None:
        return None

    def room(x, y):
        """Ground gained on the nearest of them, then on all of them.

        The second half matters when the first cannot move: hemmed in on
        four sides every step still leaves you next to somebody, so the
        nearest distance stays at one whichever way you go. Stepping
        diagonally out of a cross puts two of them behind you even so, and
        the total distance is what says that.
        """
        dists = [max(abs(c.x - x), abs(c.y - y)) for c in foes]
        return (min(dists), sum(dists))

    best, best_room = None, room(p.x, p.y)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == dy == 0:
                continue
            cell = (p.x + dx, p.y + dy, p.z)
            if not game.local.in_bounds(*cell) \
                    or not game.local.walkable(*cell) \
                    or game.creature_at(*cell) is not None:
                continue
            gain = room(cell[0], cell[1])
            if gain > best_room:
                best, best_room = (dx, dy), gain
    if best is None:
        return None
    cost = actions.move_or_attack(game, *best)
    if cost <= 0:
        return None
    why["ran"] += 1
    return cost


#: What is worth stopping to pick up off a body.
WORTH_TAKING = ("bandage", "splint", "waterskin", "water_drink", "meat",
                "bread", "cheese", "berries", "plump_helmet", "dwarven_ale",
                "wine", "beer", "mead", "rum", "torch")


def _loot(game, why) -> Optional[int]:
    """Take what you need off what you killed.

    Everybody in the world carries a bandage since v3.63 and it falls to the
    floor when they do. The driver walked over all of it: three bandages out
    of the starting kit, and then 95 turns in one run reporting "bleeding,
    and nothing to bind it with" while standing on a pile of them.
    """
    p = game.player
    if _adjacent_foe(game) is not None:
        return None
    pile = game.items_at(p.x, p.y, p.z)
    if not pile:
        return None
    for it in pile:
        if it.def_id not in WORTH_TAKING:
            continue
        if it.def_id == "bandage" and len(p.inventory.by_def("bandage")) >= 6:
            continue
        why["took what it needed"] += 1
        return actions.pick_up(game, it)
    return None


def _get_out_of_the_water(game, why) -> Optional[int]:
    """One step toward dry land, if the water is over your head."""
    from ascii_warriors.game import swimming

    p = game.player
    if game.local is None:
        return None
    if not swimming.is_swimming(swimming.depth_of(
            game.local.tile(p.x, p.y, p.z))):
        return None
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                   (1, 1), (-1, -1), (1, -1), (-1, 1)):
        cell = (p.x + dx, p.y + dy, p.z)
        if not game.local.in_bounds(*cell):
            continue
        if swimming.is_swimming(swimming.depth_of(game.local.tile(*cell))):
            continue
        if not game.is_passable(*cell, p):
            continue
        why["struck out for the bank"] += 1
        return actions.move_or_attack(game, dx, dy)
    why["out of my depth with nowhere to go"] += 1
    return None


def _find_water(game, why) -> Optional[int]:
    """Walk to a bank you can drink from, if there is one on this map.

    The bank, not the water: `water_source_near` is satisfied from beside it,
    and walking into the river instead drowned the adventurer on the first
    run that tried.
    """
    p, lm = game.player, game.local
    if lm is None:
        return None
    best = None
    for (x, y, z), _tid in _water_cells(game):
        for bank in _banks(game, x, y, z):
            d = max(abs(bank[0] - p.x), abs(bank[1] - p.y)) + abs(bank[2] - p.z) * 8
            if best is None or d < best[0]:
                best = (d, bank)
    if best is None:
        why["no water on this map"] += 1
        return None
    why["went for a drink"] += 1
    return _walk_toward(game, *best[1])


def _banks(game, x: int, y: int, z: int):
    """Dry, walkable cells beside a water cell."""
    from ascii_warriors.world import tiles as tile_data

    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == dy == 0:
                continue
            cell = (x + dx, y + dy, z)
            if not game.local.in_bounds(*cell):
                continue
            t = tile_data.get(game.local.tile(*cell))
            if t.has("WATER") or not game.is_passable(*cell):
                continue
            yield cell


def _water_cells(game):
    """Every shallow water or well tile on the map, with its id."""
    from ascii_warriors.world import tiles as tile_data

    lm = game.local
    for z, level in lm.levels.items():
        for i, tid in enumerate(level):
            t = tile_data.get(tid)
            if t.has("WATER_SOURCE") or (t.has("WATER") and not t.has("DEEP")):
                yield ((i % lm.width, i // lm.width, z), tid)


#: Who in a town will give you work, from `conversation.topics_for`.
EMPLOYERS = ("lord", "tavern_keeper", "guard", "priest", "merchant")

#: How far the driver will walk inside one map before giving up on a target
#: and doing something else. A local map is 80 by 60.
LOCAL_PATIENCE = 200

#: How many world tiles it will cross for one errand before writing it off.
TRAVEL_PATIENCE = 40


def _walk_toward(game, tx: int, ty: int, tz: int) -> Optional[int]:
    """One step along a route to somewhere on this map. Returns a cost.

    None when the step did not happen -- a wall, a closed door, somebody in
    the way. A blocked move costs nothing, and returning that zero as though
    it were a turn spent left the driver walking into the same rock for
    2958 turns while it "worked" on a bounty.

    The same shape as `ai._step_toward`, which is the point: the driver walks
    the way anything else on the map walks, over `local.path_neighbours`,
    rather than being teleported to whatever it is measuring.
    """
    p = game.player
    if (p.x, p.y, p.z) == (tx, ty, tz):
        return 0
    path = astar(
        (p.x, p.y, p.z), (tx, ty, tz), _on_foot(game),
        lambda a, b: geometry.chebyshev(a[0], a[1], b[0], b[1]) + abs(a[2] - b[2]),
        max_nodes=3000,
    )
    if path and len(path) > 1:
        nxt = path[1]
        if nxt[2] != p.z:
            return actions.move_z(game, 1 if nxt[2] > p.z else -1) or None
        return actions.move_or_attack(
            game, nxt[0] - p.x, nxt[1] - p.y) or None
    dx, dy = geometry.normalize_dir(tx - p.x, ty - p.y)
    return actions.move_or_attack(game, dx, dy) or None


def _on_foot(game):
    """`path_neighbours`, minus anything you would have to swim.

    The map's own neighbours are what a creature can *get through*, and that
    includes the river. A player walks round; the driver swam, and drowned on
    its first errand with a full pack on.
    """
    from ascii_warriors.world import tiles as tile_data

    inner = game.local.path_neighbours

    def walkable(cell):
        for nxt, cost in inner(cell):
            if tile_data.get(game.local.tile(*nxt)).swim:
                continue
            yield nxt, cost

    return walkable


def _beside(game, other) -> bool:
    """True when the player is close enough to speak or swing."""
    p = game.player
    return (p.z == other.z
            and max(abs(p.x - other.x), abs(p.y - other.y)) <= 1)


def _travel_toward(game, wx: int, wy: int, why) -> Optional[int]:
    """One step along a route across the world map.

    The route rather than the bearing. Walking greedily at the goal and
    trying four neighbours when that failed left the driver hemmed in by a
    coastline for 3999 turns out of 4000, three runs in ten. `route_overland`
    is what the travel screen has always drawn for the player.
    """
    p = game.player
    if (p.wx, p.wy) == (wx, wy):
        return None
    if not game.can_travel():
        why["could not set out"] += 1
        return None
    route = game.route_overland(wx, wy)
    if len(route) < 2:
        why["no way there overland"] += 1
        return None
    step = route[1]
    if not game.travel_step(step[0] - p.wx, step[1] - p.wy):
        why["the road was shut"] += 1
        return None
    why["travelled"] += 1
    _check_arrival(game, why)
    return 0


def _check_arrival(game, why) -> None:
    """On stepping onto a job's square, is the job there?

    The interesting measurement of the whole errand, and the one a player
    makes without thinking: you were sent to the Wandering Dunes for four
    giant rats, and you are standing in the Wandering Dunes. `artifacts` and
    the lair beast already hold this line; the bounty did not, and the
    quarry was there seven arrivals in forty-two.
    """
    p = game.player
    for q in game.quests.active:
        if (q.wx, q.wy) != (p.wx, p.wy) or q.progress >= q.goal:
            continue
        if q.kind in ("slay_beast", "bounty"):
            why["arrived and it was there" if _quarry(game, q)
                else "ARRIVED AND IT WAS NOT THERE"] += 1
        elif q.kind == "retrieve_artifact":
            found = any(
                getattr(it, "artifact_id", None) == q.artifact_id
                for pile in game.items_on_ground.values() for it in pile
            ) or any(
                getattr(it, "artifact_id", None) == q.artifact_id
                for c in game.creatures.values() for it in c.inventory.items
            )
            why["arrived and it was there" if found
                else "ARRIVED AND IT WAS NOT THERE"] += 1


def _employers(game) -> list:
    """People on this map who hand out work."""
    return [
        c for c in game.creatures.values()
        if not c.is_player and not c.body.dead and c.ai
        and c.ai.role in EMPLOYERS and c.defn.has("CAN_SPEAK")
        and not c.is_hostile_to(game.player)
    ]


def _giver_of(game, quest):
    """The person who set this job, if they are standing on this map."""
    if quest.giver_hf is None:
        return None
    return next((c for c in game.creatures.values()
                 if c.hf_id == quest.giver_hf and not c.body.dead), None)


def _quarry(game, quest) -> list:
    """Whatever this quest wants killed, here and now."""
    return [
        c for c in game.creatures.values()
        if not c.body.dead and not c.is_player
        and ((quest.target_hf is not None and c.hf_id == quest.target_hf)
             or (quest.target_def and c.def_id == quest.target_def))
    ]


def _adjacent_foe(game):
    """A hostile standing next to the player, if there is one.

    `is_hostile_to` rather than `faction == "hostile"`, which is what this
    asked since v3.51 and is not the same question: a wolf's faction is
    `"wild"`. The driver could not hit an animal, so a wolf could chew
    through an adventurer who never once swung back -- and the counter said
    `fought: 0` while the log filled with bites.
    """
    p = game.player
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == dy == 0:
                continue
            c = game.creature_at(p.x + dx, p.y + dy, p.z)
            if c is not None and not c.body.dead and c.is_hostile_to(p):
                return dx, dy
    return None


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _swing_at(game, target, why, label: str) -> int:
    """Hit something adjacent, or walk to it."""
    p = game.player
    if _beside(game, target):
        why[label] += 1
        return actions.attack_dir(game, _sign(target.x - p.x),
                                  _sign(target.y - p.y))
    return _walk_toward(game, target.x, target.y, target.z)


def _dry_land_beside(game) -> bool:
    """True if a step out of the water was available where the player ended."""
    from ascii_warriors.game import swimming

    p = game.player
    if game.local is None:
        return False
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            cell = (p.x + dx, p.y + dy, p.z)
            if not game.local.in_bounds(*cell):
                continue
            if not swimming.is_swimming(
                    swimming.depth_of(game.local.tile(*cell))):
                return True
    return False


def _nearest_town(game):
    """The closest settlement, for somebody looking for work."""
    p = game.player
    towns = [s for s in game.world.sites if s.is_settlement]
    if not towns:
        return None
    return min(towns, key=lambda s: max(abs(s.wx - p.wx), abs(s.wy - p.wy)))


def _do_here(game, quest, why) -> Optional[int]:
    """The job, on the square it is on. None if it cannot be done here."""
    p = game.player
    if quest.kind in ("slay_beast", "bounty"):
        prey = _quarry(game, quest)
        if not prey:
            why["nothing to hunt where it said"] += 1
            return None
        target = min(prey, key=lambda c: max(abs(c.x - p.x), abs(c.y - p.y)))
        return _swing_at(game, target, why, "hunted")
    if quest.kind == "retrieve_artifact":
        for cell, pile in list(game.items_on_ground.items()):
            for it in pile:
                if getattr(it, "artifact_id", None) != quest.artifact_id:
                    continue
                if (p.x, p.y, p.z) == cell:
                    why["picked it up"] += 1
                    return actions.pick_up(game, it)
                return _walk_toward(game, *cell)
        holder = next(
            (c for c in game.creatures.values()
             if not c.body.dead and not c.is_player
             and any(getattr(i, "artifact_id", None) == quest.artifact_id
                     for i in c.inventory.items)), None)
        if holder is not None:
            return _swing_at(game, holder, why, "fought for it")
        why["artifact was not where it said"] += 1
        return None
    if quest.kind == "clear_site":
        foes = [c for c in game.creatures.values()
                if not c.body.dead and not c.is_player
                and c.is_hostile_to(p)]
        if not foes:
            why["nothing left to clear"] += 1
            return None
        target = min(foes, key=lambda c: max(abs(c.x - p.x), abs(c.y - p.y)))
        return _swing_at(game, target, why, "cleared")
    return None


def _errand(game, why) -> Optional[int]:
    """What somebody with a job to do would press next.

    None when nothing errand-shaped applies, and the caller wanders instead.
    """
    p = game.player
    log = game.quests

    # Something finished, and somebody to tell.
    for q in list(log.active):
        if q.progress < q.goal or q.giver_hf is None:
            continue
        if q.giver_wx >= 0 and (p.wx, p.wy) != (q.giver_wx, q.giver_wy):
            step = _travel_toward(game, q.giver_wx, q.giver_wy, why)
            if step is not None:
                return step
            continue
        giver = _giver_of(game, q)
        if giver is None:
            why["came back and the one who sent you was gone"] += 1
            continue
        if _beside(game, giver):
            conv.say(p, giver, "report_quest", game)
            why["reported"] += 1
            return actions.talk(game, giver)
        return _walk_toward(game, giver.x, giver.y, giver.z)

    # A job on the square you are standing on.
    for q in list(log.active):
        if q.progress >= q.goal:
            continue
        if (p.wx, p.wy) != (q.wx, q.wy):
            continue
        cost = _do_here(game, q, why)
        if cost is not None:
            why["working"] += 1
            return cost

    # Somewhere to be.
    for q in list(log.active):
        if q.progress >= q.goal:
            continue
        if (p.wx, p.wy) != (q.wx, q.wy):
            why["on the road to the job"] += 1
            step = _travel_toward(game, q.wx, q.wy, why)
            if step is not None:
                return step

    # Nothing in hand: find somebody who wants something done.
    if not log.active:
        bosses = _employers(game)
        if bosses:
            boss = min(bosses,
                       key=lambda c: max(abs(c.x - p.x), abs(c.y - p.y)))
            if _beside(game, boss):
                before = len(log.active)
                conv.say(p, boss, "request_quest", game)
                why["took work" if len(log.active) > before
                    else "asked, nothing doing"] += 1
                return actions.talk(game, boss)
            return _walk_toward(game, boss.x, boss.y, boss.z)
        town = _nearest_town(game)
        if town is not None and (town.wx, town.wy) != (p.wx, p.wy):
            step = _travel_toward(game, town.wx, town.wy, why)
            if step is not None:
                return step
    return None


def play(seed: str, turns: int, *, size: str = "small",
         history: int = 120, report=print) -> dict:
    """Play one adventurer and return what happened to them."""
    rng = RNG(seed)
    world = generate_world(rng.sub("w"), size=size, history_years=history)
    game = Game.new_game(
        world, {"race": "human", "profession": "warrior"}, rng)
    p = game.player
    report("%s the %s, in %s" % (p.name, p.profession,
                                 world.tile(p.wx, p.wy).biome))

    started_at = game.time.ticks
    why: collections.Counter = collections.Counter()
    taken: dict = {}
    seen_tiles = {(p.wx, p.wy)}
    start = (p.x, p.y)
    far = 0
    peak = {"thirst": 0, "hunger": 0, "drowsy": 0}
    t0 = time.perf_counter()
    turn = 0
    for turn in range(turns):
        if p.body.dead or game.game_over:
            break
        cost = _look_after(game, why)
        if cost is None:
            cost = _run_away(game, why)
        if cost is None:
            cost = _rest_up(game, why)
        if cost is None:
            foe = _adjacent_foe(game)
            if foe is not None:
                cost = actions.attack_dir(game, *foe)
                why["fought"] += 1
        if cost is None:
            cost = _errand(game, why)
        if cost is None:
            dx, dy = game.rng.choice(
                [(1, 0), (-1, 0), (0, 1), (0, -1),
                 (1, 1), (-1, -1), (1, -1), (-1, 1)])
            cost = actions.move_or_attack(game, dx, dy)
            if cost <= 0:
                why["blocked"] += 1
                cost = actions.wait(game)
        game.player_acts(max(1, cost))
        seen_tiles.add((p.wx, p.wy))
        for q in game.quests.active + game.quests.completed:
            taken.setdefault(q.id, q)
        far = max(far, abs(p.x - start[0]) + abs(p.y - start[1]))
        for need in peak:
            peak[need] = max(peak[need], getattr(p.needs, need))

    out = {
        "seed": seed,
        "turns": turn + 1,
        "ticks": game.time.ticks - started_at,
        "seconds": time.perf_counter() - t0,
        "dead": p.body.dead,
        "cause": p.body.death_cause or "",
        "peak": peak,
        "furthest": far,
        "actions": dict(why),
        "water_nearby": actions.water_source_near(game),
        "dry_land_beside": _dry_land_beside(game),
        "world_tiles": len(seen_tiles),
        "quests_taken": len(taken),
        "quests_done": len([q for q in taken.values() if q.state == "done"]),
        "quests_failed": len([q for q in taken.values() if q.state == "failed"]),
        "kinds_done": sorted({q.kind for q in taken.values()
                              if q.state == "done"}),
        "kinds_taken": sorted({q.kind for q in taken.values()}),
        "nowhere": sorted({q.kind for q in taken.values() if not q.site_name}),
        # Met, carried back, told to the person who set it, and still owing.
        "ready_but_unpaid": len([
            q for q in taken.values()
            if q.progress >= q.goal and q.state != "done"
            and q.giver_hf is not None
            and why.get("reported", 0) > 0
        ]),
        "coins": sum(i.count for i in p.inventory.items if i.def_id == "coin"),
    }
    report("survived %(turns)d turns in %(seconds).0fs; dead=%(dead)s %(cause)s"
           % out)
    report("peak needs %(peak)s, furthest %(furthest)d tiles, "
           "%(world_tiles)d world squares" % out)
    report("work: %(quests_taken)d taken, %(quests_done)d finished, "
           "%(quests_failed)d lost; finished %(kinds_done)s" % out)
    report("actions %(actions)s" % out)
    if out["dead"]:
        # A driver that says "dead=True drowned" and stops has told you the
        # least useful half of what it knows.
        report("last words:")
        for line in game.log.recent(6):
            frags = line if isinstance(line, list) else [line]
            report("    " + " ".join(getattr(x, "text", str(x)) for x in frags))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", default="play")
    ap.add_argument("--turns", type=int, default=16000)
    ap.add_argument("--size", default="small")
    ap.add_argument("--history", type=int, default=120)
    args = ap.parse_args(argv)

    scratch_saves()
    out = play(args.seed, args.turns, size=args.size, history=args.history)

    # The invariants. A driver that only prints is a driver nobody reads.
    problems = []
    # A floor, but only once enough game time has passed to clear it.
    #
    # How many ticks a turn buys depends entirely on what the turn was:
    # walking the world map moves the clock in strides of a hundred, trading
    # blows with a wolf moves it by one. Seed `play` is jumped on the road and
    # dies in 36 local turns, so 36 ticks pass and thirst reaches 36 -- and
    # the bare floor of 100 called that a stopped clock in every run of the
    # ritual. It is a short violent life, which is a thing that happens to
    # adventurers, and the clock kept perfect time throughout.
    #
    # Measured against elapsed ticks rather than turns, and as a floor rather
    # than a proportion, because thirst is not proportional to time: it climbs
    # about a point a tick until the character drinks and then flattens out.
    # Six seeds -- 36/36, 3586/4097, 11600/11600, then 109921/22126,
    # 115506/16904, 118368/28797. The first three have not drunk yet and the
    # last three have.
    elapsed = out["ticks"]
    if elapsed > CLOCK_ENOUGH and out["peak"]["thirst"] < CLOCK_FLOOR:
        problems.append("%d ticks passed and thirst only reached %d: the "
                        "clock is running and needs are not"
                        % (elapsed, out["peak"]["thirst"]))
    if elapsed <= 0 and out["turns"] > 1:
        problems.append("%d turns and the clock never moved at all"
                        % out["turns"])
    if out["cause"] == "died of thirst" and out["water_nearby"]:
        problems.append("died of thirst standing next to water")
    if out["cause"] == "drowned" and out["dry_land_beside"]:
        problems.append("drowned with dry land one step away")
    if out["turns"] < args.turns and not out["dead"]:
        problems.append("stopped early without dying")
    if out["nowhere"]:
        problems.append("work with no destination: %s"
                        % ", ".join(out["nowhere"]))
    if out["world_tiles"] < 2 and not out["dead"]:
        problems.append("never left the world square it started on")
    missed = out["actions"].get("ARRIVED AND IT WAS NOT THERE", 0)
    if missed:
        problems.append("%d times it walked to where the job was and the job "
                        "was not there" % missed)
    if out["ready_but_unpaid"]:
        problems.append("%d jobs met and reported and never paid"
                        % out["ready_but_unpaid"])
    if not out["quests_taken"] and not out["dead"]:
        problems.append("nobody in the world had any work")
    for problem in problems:
        print("PLAY PROBLEM: %s" % problem)
    if problems:
        return 1
    print("PLAY OK: %s, %d turns, %d/%d jobs done"
          % (args.seed, out["turns"], out["quests_done"], out["quests_taken"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
