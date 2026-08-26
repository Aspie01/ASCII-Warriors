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
from ascii_warriors.game import companions as companion_mod
from ascii_warriors.game import trade
from ascii_warriors.game.state import Game
from ascii_warriors.world.worldgen import generate_world
from tools import scratch_saves

#: Turns an adventurer has to have lived before "it never went anywhere" and
#: "nobody had any work for it" are fair questions.
#:
#: Measured over twelve seeds: the ones that died inside 70 turns saw one or
#: two world squares and the ones that lived 189 turns or more saw between 5
#: and 34. A hundred sits in the gap, and the shortest life that clears it
#: had already reached four.
TRAVEL_ENOUGH = 100

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


def _can_outrun(game, foes) -> bool:
    """Whether backing away from these gains ground, or donates it.

    A retreat is only a retreat from something slower than you. Fifty of the
    eighty-one creature kinds are quicker than a man -- `Game._pace_of` says
    so on the look screen, "It is much faster than you", and a wolf is 160 to
    a starting warrior's 102, which is 1.57 actions to your one. Every step
    away from one is a free attack handed over, and the driver had been taking
    that trade since it was written.

    Measured over forty seeds run both ways. The retreats drop from 482 to
    88 -- the 88 being the surrounded cases below and the genuinely slower
    quarry -- and survival barely moves: paired by seed, 20 longer, 9 shorter,
    11 unchanged, a mean of 328.7 turns against 311.9. So this is not a fix
    for the dying. It removes 394 steps that could not gain ground, which is
    reason enough on its own.

    Relative, and asked fresh every turn, because both numbers move: pain and
    a broken leg multiply into `effective_speed`, so the wolf you outpaced
    this morning is the wolf that runs you down this afternoon.

    Only consulted when one thing is on you. With two or more in contact a
    step is worth taking whatever their speed, because it is fewer of them
    that can reach you next turn -- see `_run_away`.
    """
    mine = max(1, game.player.effective_speed())
    return all(c.effective_speed() <= mine for c in foes)


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
    # Surrounded is the exception, and it is a measured one: §"knowing when
    # to run" established that stepping diagonally out of a cross of four
    # puts two of them behind you. That gain does not depend on outpacing
    # anybody -- it is fewer things able to reach you this turn -- so the
    # speed gate only governs the case it was measured on, which is being
    # chased by something you cannot shake.
    touching = [c for c in foes
                if max(abs(c.x - p.x), abs(c.y - p.y)) <= 1]
    if len(touching) < 2 and not _can_outrun(game, foes):
        return None

    return _step_away(game, foes, why)


def _step_away(game, foes, why, label: str = "ran") -> Optional[int]:
    """The step that puts the most ground between you and *foes*.

    Ground gained on the nearest of them, then on all of them. The second
    half matters when the first cannot move: hemmed in on four sides every
    step still leaves you next to somebody, so the nearest distance stays at
    one whichever way you go. Stepping diagonally out of a cross puts two of
    them behind you even so, and the total distance is what says that.
    """
    p = game.player

    def room(x, y):
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
    why[label] += 1
    return cost


def _shoot(game, why) -> Optional[int]:
    """Put an arrow in whatever is coming, while it is still coming.

    The band is the AI's own -- two to twelve, near enough to hit and far
    enough that closing costs the other side a turn -- so the driver
    shoots on the same terms the world shoots at it. Nothing here reaches
    for a bow it does not have: an adventurer that starts with a sword
    stays a swordsman until it loots or buys one.
    """
    p = game.player
    weapon = p.inventory.weapon()
    if weapon is None or not weapon.is_ranged:
        return None
    # `inventory.ammo()` answers for the *quiver* -- what is equipped --
    # and `fire` falls back to any matching ammunition in the pack. The
    # first draft of this gate asked only the quiver, so a driver with
    # forty arrows in its bag reported "out of arrows" a hundred times a
    # life and never loosed one: the gate was stricter than the verb it
    # guards, which is the same shape as v4.15's `move_z` refusing steps
    # the graph allowed.
    from ascii_warriors.data import items as item_data

    ammo = p.inventory.ammo()
    if ammo is None:
        ammo_id = item_data.ammo_for(weapon.defn)
        if not ammo_id or not p.inventory.by_def(ammo_id):
            why["out of arrows"] += 1
            return None
    if game.local is None:
        return None
    best = None
    for c in game.creatures.values():
        if c.is_player or c.body.dead or not c.is_hostile_to(p) or c.z != p.z:
            continue
        d = max(abs(c.x - p.x), abs(c.y - p.y))
        if d < 2 or d > 12:
            continue
        # The same question `fire` asks, asked the same way: a shot walks
        # the line and hits the first body on it, so a clear line means
        # this foe is that body. Firing blind spends the arrow on "your
        # shot flies wide and is lost" -- a real turn, a real arrow, and
        # the driver would keep paying it.
        path = actions.line_of_fire(
            p.x, p.y, c.x, c.y,
            lambda x, y: game.local.blocks_sight(x, y, p.z))
        first = next((game.creature_at(x, y, p.z) for x, y in path
                      if game.creature_at(x, y, p.z) is not None
                      and game.creature_at(x, y, p.z) is not p), None)
        if first is not c:
            continue
        if best is None or d < best[0]:
            best = (d, c)
    if best is None:
        return None
    why["loosed an arrow"] += 1
    return actions.fire(game, best[1].x, best[1].y)


def _decline_the_melee(game, why) -> Optional[int]:
    """Step out of a fight the odds refuse, while the blood is still in you.

    `_run_away` asks its question at 62% blood, which is an answer about a
    fight already lost. This one is asked at full health: 22 of 24 census
    adventurers died of accumulated wounds, none of them to a foe they
    could not beat alone -- the strike-by-strike duel wins every 1-on-1 in
    the game at real cadence except the skeleton -- and every one of them
    died in a melee of two or more. Seed `play` was a four-wolf pack. So the
    driver refuses the outnumbered melee outright: more of them in reach
    than there are of you and yours, and the next step is the one that
    leaves.
    """
    p = game.player
    foes = [c for c in game.creatures.values()
            if not c.body.dead and not c.is_player and c.is_hostile_to(p)
            and max(abs(c.x - p.x), abs(c.y - p.y)) <= 2 and c.z == p.z]
    party = 1 + len(companion_mod.companions_of(game))
    if len(foes) <= party:
        return None
    return _step_away(game, foes, why, label="declined the melee")


#: What is worth stopping to pick up off a body.
WORTH_TAKING = ("bandage", "splint", "waterskin", "water_drink", "meat",
                "bread", "cheese", "berries", "plump_helmet", "dwarven_ale",
                "wine", "beer", "mead", "rum", "torch",
                # A bow off a dead hunter, and something to put through it.
                # Ranged combat is a whole system -- `line_of_fire`, the
                # ammo that breaks and is recovered, the AI's own 2-to-12
                # band -- and v4.17's verb census found `fire` had never
                # been called by any run the project has made. It could not
                # be: until this milestone nobody in human lands carried a
                # bow to drop.
                "bow", "crossbow", "arrow", "bolt")


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
    """Every shallow water or well tile on the map, with its id.

    Worked out once per map rather than once per turn. The scan walks every
    tile of every level -- 33792 of them on a small world's local map, 64 by
    48 over eleven levels -- and where the water is is a fact about the
    terrain, which does not move while the adventurer stands on it.

    Measured before this cache: 5.41 ms a call, 1318 calls over forty seeds,
    7.66 seconds, and 1261 of those calls were on maps with no water at all --
    walking the whole map to say "none" again. Seed `s28` did it 1059 times in
    a life of 1107 turns. §144.3 and §145.4 both wrote it down and left it.

    This is the lesson `dwarf.py` already learned in `TAVERN_UNREACHABLE_
    BACKOFF`: "one dwarf finding out the tavern is cut off is enough
    information for the whole fortress".

    Keyed on the map object itself as well as the world square, so a square
    revisited with a freshly generated map is scanned again rather than
    answered from the last visit.
    """
    from ascii_warriors.world import tiles as tile_data

    lm = game.local
    p = game.player
    where = (p.wx, p.wy)
    hit = getattr(game, "_play_water_cells", None)
    if hit is not None and hit[0] is lm and hit[1] == where:
        return hit[2]

    found = []
    for z, level in lm.levels.items():
        for i, tid in enumerate(level):
            t = tile_data.get(tid)
            if t.has("WATER_SOURCE") or (t.has("WATER") and not t.has("DEEP")):
                found.append(((i % lm.width, i // lm.width, z), tid))
    game._play_water_cells = (lm, where, found)
    return found


#: Who in a town will give you work, from `conversation.topics_for`.
EMPLOYERS = ("lord", "tavern_keeper", "guard", "priest", "merchant")

#: How far the driver will walk inside one map before giving up on a target
#: and doing something else. A local map is 80 by 60.
#:
#: Declared with that docstring and read by nothing until v3.97, which is how
#: seed `long` came to run three thousand turns, take one job, finish none of
#: it, and be reported `PLAY OK`. The job was a bounty; the prey was a
#: `goblin_snatcher` standing one z-level above the player and diagonally
#: adjacent, with no path to it at a hundred thousand nodes. The driver aimed
#: at it eight hundred and eighty-five times.
#:
#: Two hundred is generous on an eighty-by-sixty map: a corner-to-corner walk
#: is about a hundred and forty steps, so anything that has not arrived in two
#: hundred is not walking towards it.
LOCAL_PATIENCE = 200

#: How many world tiles it will cross for one errand before writing it off.
#:
#: The same story as `LOCAL_PATIENCE`: declared, documented, and read by
#: nothing. Forty is a long way on a world the driver has never crossed more
#: than a handful of squares of, so this is a backstop rather than a
#: day-to-day bound -- but an unspent backstop is not a backstop.
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
        if nxt[2] != p.z and (nxt[0], nxt[1]) == (p.x, p.y):
            return actions.move_z(game, 1 if nxt[2] > p.z else -1) or None
        # A ramp edge changes level *and* square in one step, and the verb
        # for it is walking, not climbing: `_step_on_the_graph` follows the
        # ramp for anybody who steps into it. Sending those through
        # `move_z` asked to rise straight up through rock.
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
            # And nothing the *step* would turn into a swim. A route node
            # is a cell; taking it is a call to `move_or_attack`, which
            # tries the same-level square first and only asks the graph
            # when that square is impassable -- and swim-depth water is
            # perfectly passable, so a level-changing edge whose same-level
            # square is deep water puts the driver in the river instead of
            # on the slope. `_get_out_of_the_water` then walks it straight
            # back out, and the two of them trade turns until the breath
            # runs out. A graph the walker cannot actually walk is not the
            # walker's graph: filtering the destination is not enough,
            # because the destination is not where the step lands.
            if nxt[2] != cell[2]:
                flat = (nxt[0], nxt[1], cell[2])
                if game.local.in_bounds(*flat) \
                        and tile_data.get(game.local.tile(*flat)).swim:
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


def _patience(game) -> dict:
    """Per-run memory of what the driver has been walking at, and for how long.

    Kept on the game rather than threaded through every branch, the way
    `_play_water_cells` is. It never has to survive a save: it is the
    driver's own book-keeping, not the game's.
    """
    book = getattr(game, "_play_patience", None)
    if book is None:
        book = game._play_patience = {
            "tries": {}, "gave_up": set(),
            # v4.10: who the driver is currently fighting, so a melee is one
            # fight finished and not a spray; what that target's body looked
            # like when the fight started, and how long it has looked the
            # same, so a fight the weapon cannot win is walked away from.
            "fight_target": None, "stall": {}, "stalled": set(),
            # Where each written-off target was standing when the patience
            # ran out, so a target that has since moved earns it back.
            "written_off_at": {},
            # Turns spent standing at a quest's own square with nothing the
            # quest wants doable, per quest. Past the bound the job itself is
            # written off, or it becomes the sink `hero` measured: 2772 turns
            # wandering a site whose last target stands where no path goes.
            "site_dry": {},
        }
    return book


def _worth_chasing(game, target) -> bool:
    """False once the driver has spent `LOCAL_PATIENCE` failing to reach this.

    Something one z-level away with no stair between is indistinguishable,
    step by step, from something that is nearly in reach: the walk always
    finds a next square, and the distance never closes. This is what notices.
    """
    if target.id not in _patience(game)["gave_up"]:
        return True
    return hasattr(target, "x") and _forgiven(game, target)


def _gave_up_on(game, target, why) -> None:
    """Count another failed approach, and write the target off past the bound."""
    book = _patience(game)
    book["tries"][target.id] = book["tries"].get(target.id, 0) + 1
    if book["tries"][target.id] > LOCAL_PATIENCE:
        book["gave_up"].add(target.id)
        if hasattr(target, "x"):
            book["written_off_at"][target.id] = (target.x, target.y, target.z)
        why["gave up on something it could not reach"] += 1


def _forgiven(game, target) -> bool:
    """A written-off creature that has moved gets its patience back.

    The write-off was built for the target standing somewhere no path goes
    -- a z-level up, the far side of rock -- and that is a fact about a
    *position*, not a creature. Seed `hero`'s last bounty vampire spent the
    day indoors where two hundred approaches failed, was written off, then
    walked out at nightfall; the driver wandered the site for 2772 turns
    with the quest's own target hunting it, because the book said that
    vampire did not exist. If it has moved, the fact the book recorded is
    gone, and the chase is worth what a fresh chase is worth.
    """
    book = _patience(game)
    was = book["written_off_at"].get(target.id)
    here = (target.x, target.y, target.z)
    if was is None or max(abs(here[0] - was[0]), abs(here[1] - was[1])) <= 2 \
            and here[2] == was[2]:
        return False
    book["gave_up"].discard(target.id)
    book["written_off_at"].pop(target.id, None)
    book["tries"].pop(target.id, None)
    return True


def _job_ran_dry(game, quest, why) -> None:
    """Spend a turn of quest-level patience at the quest's own square.

    Per-creature patience already writes off the target no path reaches --
    but the quest kept pointing at the square, `_do_here` kept answering
    "nothing to hunt", and the driver wandered seed `hero`'s site for 2772
    turns between its third kill and a fourth that arrived by luck. The job
    gets the same `LOCAL_PATIENCE` a single chase gets; past that it goes in
    the same `gave_up` book `_worth_travelling` already reads, and the
    ask-for-work gate looks past it.
    """
    book = _patience(game)
    dry = book["site_dry"].get(quest.id, 0) + 1
    book["site_dry"][quest.id] = dry
    if dry > LOCAL_PATIENCE and quest.id not in book["gave_up"]:
        book["gave_up"].add(quest.id)
        why["wrote the job off: what it wants is past reaching"] += 1


def _worth_travelling(game, quest, why) -> bool:
    """False once the driver has crossed `TRAVEL_PATIENCE` squares for this job.

    Counted per job rather than per run, and only for the steps taken towards
    it: a job that keeps the driver walking further than the width of the
    world it is on is not a job it is going to reach.
    """
    book = _patience(game)
    if quest.id in book["gave_up"]:
        return False
    book["tries"][quest.id] = book["tries"].get(quest.id, 0) + 1
    if book["tries"][quest.id] > TRAVEL_PATIENCE:
        book["gave_up"].add(quest.id)
        why["gave up on somewhere it could not get to"] += 1
        return False
    return True


def _quarry(game, quest) -> list:
    """Whatever this quest wants killed, here and now.

    Anything the driver has already spent its patience on is not here as far
    as this is concerned: the bounty branch takes the nearest, and the nearest
    was exactly the one it could not get to.
    """
    return [
        c for c in game.creatures.values()
        if not c.body.dead and not c.is_player and _worth_chasing(game, c)
        and ((quest.target_hf is not None and c.hf_id == quest.target_hf)
             or (quest.target_def and c.def_id == quest.target_def))
    ]


def _adjacent_foes(game) -> list:
    """Every hostile standing next to the player."""
    p = game.player
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == dy == 0:
                continue
            c = game.creature_at(p.x + dx, p.y + dy, p.z)
            if c is not None and not c.body.dead and c.is_hostile_to(p):
                out.append(c)
    return out


def _health_of(c) -> float:
    """One number for "how close to beaten", whatever the body runs on."""
    return (c.body.structure_fraction() if c.body.bloodless
            else c.body.blood_fraction())


def _adjacent_foe(game):
    """The direction of the one adjacent hostile worth hitting.

    `is_hostile_to` rather than `faction == "hostile"`, which is what this
    asked since v3.51 and is not the same question: a wolf's faction is
    `"wild"`. The driver could not hit an animal, so a wolf could chew
    through an adventurer who never once swung back -- and the counter said
    `fought: 0` while the log filled with bites.

    And since v4.10, *one* hostile, held onto: this used to return the first
    foe in scan order, re-rolled every turn as the melee shuffled. Traced on
    seed `play` -- a four-wolf pack, 30 landed sword hits, the most wounded
    wolf abandoned at 84% blood for a pristine one, nothing killed, dead on
    turn 45. Every strike-by-strike duel says the same sword kills a wolf in
    about ten landed hits when they all land on the same wolf. So the driver
    keeps its target while the target stands, and picks fights it has
    already half-won -- the most wounded foe -- when it picks at all. Foes
    the fight has proven unhurtable (`stalled`, below) come last.
    """
    p = game.player
    foes = _adjacent_foes(game)
    if not foes:
        return None
    book = _patience(game)
    target = next((c for c in foes if c.id == book["fight_target"]), None)
    if target is None or target.id in book["stalled"]:
        fresh = [c for c in foes if c.id not in book["stalled"]]
        if not fresh:
            book["fight_target"] = None
            return None
        target = min(fresh, key=_health_of)
        book["fight_target"] = target.id
    return _sign(target.x - p.x), _sign(target.y - p.y)


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


#: Bandages the driver keeps stocked when a town can sell them. Four is the
#: starting kit's worth, and the census line it comes from is sharp: of 24
#: lives, the nine that ran dry spent 217 turns "bleeding, and nothing to
#: bind it with" and died holding 17 to 175 coins -- a purse that buys the
#: remedy several times over -- while no life that died still holding
#: bandages ever logged a famine turn. Topped up to this whenever a town
#: that sells them is underfoot.
KEEP_BANDAGES = 4


#: Fight turns against the same foe with nothing on its body changing before
#: the driver stops swinging at it. A skeleton against a sword is the case in
#: the data -- "swords and hammers still glance off it" is a designed fact
#: with a test to its name, and seeds `t` and `adv2` spent 97 and 64 strikes
#: proving it the hard way. Judged by the fight, not by a bestiary: anything
#: this weapon cannot mark in a dozen tries, it will not mark in a hundred.
STALL_PATIENCE = 12


def _fight_adjacent(game, why) -> Optional[int]:
    """Swing at the chosen adjacent foe, and notice when nothing lands.

    The stall book samples the target's health -- blood, or structure for
    the bloodless -- before each swing. `STALL_PATIENCE` consecutive swings
    that move neither marks the foe unhurtable for the rest of the run, and
    `_adjacent_foe` stops offering it.
    """
    direction = _adjacent_foe(game)
    if direction is None:
        return None
    p = game.player
    book = _patience(game)
    target = game.creature_at(p.x + direction[0], p.y + direction[1], p.z)
    if target is not None:
        health = _health_of(target)
        last, same = book["stall"].get(target.id, (None, 0))
        same = same + 1 if last is not None and health >= last - 1e-9 else 0
        book["stall"][target.id] = (health, same)
        if same >= STALL_PATIENCE:
            book["stalled"].add(target.id)
            book["fight_target"] = None
            why["stopped hitting what it cannot hurt"] += 1
            return None
    cost = actions.attack_dir(game, *direction)
    why["fought"] += 1
    return cost


def _swing_at(game, target, why, label: str):
    """Hit something adjacent, or walk to it. None once it is not worth it.

    Every chase in this driver goes through here, so this is where the
    patience is spent. Getting beside the target clears its count: a long
    approach that works is not a failure.
    """
    p = game.player
    if _beside(game, target):
        why[label] += 1
        _patience(game)["tries"].pop(target.id, None)
        return actions.attack_dir(game, _sign(target.x - p.x),
                                  _sign(target.y - p.y))
    if not _worth_chasing(game, target):
        return None
    _gave_up_on(game, target, why)
    if not _worth_chasing(game, target):
        return None
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
            _job_ran_dry(game, quest, why)
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
            _job_ran_dry(game, quest, why)
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

    # The one cause of death in the whole census is bleeding, the world
    # sells bandages in every town, and 1784 coins died unspent across 24
    # lives before anybody thought to shop. Topped up *in town*, any time
    # under the bound: the first draft waited for the roll to run low, and
    # low happens at the site, mid-fight, where no merchant stands and no
    # turn is free. And the stall is stocked the way the shop screen does it
    # -- `stock_merchant` fills a trader the first time anybody talks trade,
    # so a driver that only ever browsed saw empty counters everywhere.
    have = sum(i.count for i in p.inventory.items if i.def_id == "bandage")
    coins = sum(i.count for i in p.inventory.items if i.def_id == "coin")
    if have < KEEP_BANDAGES and coins >= 10:
        book = _patience(game)
        bare = book.setdefault("bare_stalls", set())
        stalls = [
            c for c in game.creatures.values()
            if not c.is_player and not c.body.dead and c.id not in bare
            and trade.is_trader(c) and not c.is_hostile_to(p)
            and "bandage" in trade.STOCK_TABLES.get(
                trade.trader_kind(c) or "merchant", ())
        ]
        if stalls:
            merchant = min(stalls, key=lambda c: max(abs(c.x - p.x),
                                                     abs(c.y - p.y)))
            if _beside(game, merchant):
                trade.stock_merchant(merchant, game.rng)
                # The cheapest roll on the counter, not the first: everybody
                # in the world carries a personal bandage (v3.63), a
                # merchant's own is on the counter too, and its cloth prices
                # at ~45 a strip against ~7 for shop stock. The first draft
                # grabbed it, found it unaffordable, and called the whole
                # stall bare.
                rolls = [i for i in trade.for_sale(merchant)
                         if i.def_id == "bandage"]
                roll = min(rolls, key=lambda i: trade.price_to_buy(
                    i, merchant, p, game)) if rolls else None
                unit = (trade.price_to_buy(roll, merchant, p, game)
                        if roll is not None else 0)
                if roll is None or unit > coins:
                    bare.add(merchant.id)
                    why["the stall had no bandages"] += 1
                    return actions.wait(game)
                count = max(1, min(roll.count, KEEP_BANDAGES - have,
                                   coins // max(1, unit)))
                ok, _message = trade.buy(game, merchant, roll, count)
                why["bought bandages" if ok else "the shop refused"] += 1
                if not ok:
                    bare.add(merchant.id)
                return actions.wait(game)
            if _worth_chasing(game, merchant):
                return _walk_toward(game, merchant.x, merchant.y, merchant.z)

    # Work that means fighting several of them means not going alone. A
    # clear_site is three to eight foes and a slay_beast is a megabeast; the
    # census put a lone level-nought warrior against those numbers 22 times
    # and buried 22. The game has had companions for hire all along -- 49
    # starting coins, hire prices from a few dozen, quest rewards from 80 --
    # and no driver ever spent a coin on one.
    fight_q = next((q for q in log.active
                    if q.kind in ("clear_site", "slay_beast")
                    and q.progress < q.goal), None)
    if fight_q is not None and (p.wx, p.wy) != (fight_q.wx, fight_q.wy) \
            and not companion_mod.companions_of(game):
        coins = sum(i.count for i in p.inventory.items
                    if i.def_id == "coin")
        hands = [c for c in game.creatures.values()
                 if not c.is_player and not c.body.dead
                 and companion_mod.can_recruit(c)
                 and companion_mod.hire_price(c, p) <= coins]
        if hands:
            hand = min(hands,
                       key=lambda c: max(abs(c.x - p.x), abs(c.y - p.y)))
            if _beside(game, hand):
                conv.say(p, hand, "recruit", game)
                got = bool(companion_mod.companions_of(game))
                why["hired a sword" if got else "asked; nobody would come"] += 1
                return actions.talk(game, hand)
            if _worth_chasing(game, hand):
                return _walk_toward(game, hand.x, hand.y, hand.z)

    # Somewhere to be.
    for q in list(log.active):
        if q.progress >= q.goal:
            continue
        if (p.wx, p.wy) != (q.wx, q.wy):
            if not _worth_travelling(game, q, why):
                continue
            why["on the road to the job"] += 1
            step = _travel_toward(game, q.wx, q.wy, why)
            if step is not None:
                return step

    # Nothing in hand: find somebody who wants something done. A job the
    # patience wrote off no longer counts as something in hand.
    book = _patience(game)
    if not [q for q in log.active if q.id not in book["gave_up"]]:
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


def _press(game, why) -> int:
    """One turn of the whole policy: what the driver presses, and its cost.

    The priority order is the driver's charter -- look after the body, leave
    fights already lost, refuse fights not worth starting, rest, fight the
    one fight, do the errand, wander. Factored out of the loop so a test can
    drive the actual policy against a built scenario instead of a replica of
    it; the replica is how `player_acts` was once skipped and two hundred
    turns moved the clock two ticks.
    """
    cost = _look_after(game, why)
    if cost is None:
        cost = _shoot(game, why)
    if cost is None:
        cost = _run_away(game, why)
    if cost is None:
        cost = _decline_the_melee(game, why)
    if cost is None:
        cost = _rest_up(game, why)
    if cost is None:
        cost = _fight_adjacent(game, why)
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
    return cost


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
        game.player_acts(max(1, _press(game, why)))
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
        # Targets and jobs the driver spent its patience on and wrote off.
        "gave_up": len(_patience(game)["gave_up"]),
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
    report("work: %(quests_taken)d taken %(kinds_taken)s, "
           "%(quests_done)d finished, "
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
    # Dormant by design, not by accident: this one only means anything about
    # a run that ended with the adventurer alive, and none of them do. Left
    # exactly as it is, because it guards the driver against truncating a run
    # silently and it cannot fire wrongly.
    if out["turns"] < args.turns and not out["dead"]:
        problems.append("stopped early without dying")
    # A player that lived a long life, wrote off everything it could not
    # reach, and finished nothing. That is not a hard run -- it is a run in
    # which the game offered work that could not be done from where it put
    # the player. Seed `long` is the case this was built from: a bounty on a
    # `goblin_snatcher` standing one z-level up with no path to it at a
    # hundred thousand nodes, on a map the driver spent three thousand turns
    # on. `dead` is excluded because a player who was killed has an obvious
    # reason for finishing nothing.
    if out["gave_up"] and not out["quests_done"] and not out["dead"] \
            and out["turns"] >= LOCAL_PATIENCE * 2:
        problems.append("survived %d turns, gave up on %d thing(s) it could "
                        "not reach and finished none of the %d job(s) it took"
                        % (out["turns"], out["gave_up"], out["quests_taken"]))
    if out["nowhere"]:
        problems.append("work with no destination: %s"
                        % ", ".join(out["nowhere"]))
    # Gated on having lived long enough to go somewhere, not on having
    # survived. Twelve seeds measured, twelve dead -- every adventurer in the
    # ritual bleeds to death, most of them inside 300 turns of a 16000-turn
    # budget -- so `not dead` was a gate that never opened and these two
    # checks had never run at all. An adventurer killed on turn 36 has not
    # failed to travel; one that lived 300 turns on one world square has.
    if out["turns"] > TRAVEL_ENOUGH and out["world_tiles"] < 2:
        problems.append("%d turns and it never left the world square it "
                        "started on" % out["turns"])
    missed = out["actions"].get("ARRIVED AND IT WAS NOT THERE", 0)
    if missed:
        problems.append("%d times it walked to where the job was and the job "
                        "was not there" % missed)
    if out["ready_but_unpaid"]:
        problems.append("%d jobs met and reported and never paid"
                        % out["ready_but_unpaid"])
    if out["turns"] > TRAVEL_ENOUGH and not out["quests_taken"]:
        problems.append("%d turns and nobody in the world had any work"
                        % out["turns"])
    for problem in problems:
        print("PLAY PROBLEM: %s" % problem)
    if problems:
        return 1
    print("PLAY OK: %s, %d turns, %d/%d jobs done"
          % (args.seed, out["turns"], out["quests_done"], out["quests_taken"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
