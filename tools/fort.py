"""Play a fortress for a year and report what happened to it.

`smoke --mode fortress` proves the screens fit together and `fuzz` presses
keys at random. Neither of them *plays*: nothing digs a stairway, plants a
crop, or brews the harvest, so a defect that only shows up in a fortress that
is being run properly has never had anything looking for it. `tools.play` did
this for the other half of the game in v3.51 and found three defects in an
afternoon; this is the fortress's own.

It does what a competent player does in the first year -- a stairway down,
rooms cut out of the rock, a still and a farm and a carpenter, beds for
everybody, orders standing at the workshops -- and then watches the season
tick over. The invariants at the end are the interesting part: a fortress
that starves beside a full field, or whose dwarves die of thirst with a
barrel they could have walked to, exits non-zero and says so.
"""

from __future__ import annotations

import argparse
import collections
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ascii_warriors.data.calendar import TICKS_PER_DAY
from ascii_warriors.engine.rng import RNG
from ascii_warriors.fortress import buildings, perform as perform_mod, sim
from ascii_warriors.fortress.buildings import Building
from ascii_warriors.fortress.fortress import Fortress
from ascii_warriors.ui.fort.embark import suggest_site
from ascii_warriors.world import tiles as tile_data
from ascii_warriors.world.worldgen import generate_world
from tools import scratch_saves

#: One simulation step is `sim.STEP_TICKS`; a day is this many steps.
STEPS_PER_DAY = TICKS_PER_DAY // sim.STEP_TICKS

#: How much of the map to hollow out. A first year is a stairway and a
#: handful of rooms, not a megaproject.
ROOM_W = 9
ROOM_H = 7

#: How much of the wood and the undergrowth to mark. A player marks a stand
#: near the fortress, not every tree on the map.
WOOD_WANTED = 60
PLANTS_WANTED = 20

#: How far from open water the stairway starts, and how deep the rock under
#: it has to go.
DRY_MARGIN = 4
DEEP_ENOUGH = 4

#: How far from the wagon the fortress may be sunk. Everything the seven
#: brought with them is lying beside the wagon, so the stairway goes near it.
SITE_RANGE = 30


def _dry_ground(fort, x, y):
    """Somewhere near the wagon to sink a stairway that will not fill up.

    The wagon stops on the flattest open ground near the middle of the map,
    and beside a lake that is the shore. Sinking the stairway there puts a
    hole below the waterline one tile from the water: the shaft fills to the
    brim, the only cell anybody could stand in to cut the next step is under
    seven units of water, and every room below is filed away as unreachable
    for ever. Measured on this driver's own embark -- sixty-two cells painted
    for digging, none dug, seven dwarves idle for a year, and a FORT OK on the
    way out because the wood kept coming in from the surface.

    A player picks somewhere dry. So does this: level ground away from open
    water, with rock under it worth digging into.
    """
    lm = fort.local
    for r in range(0, SITE_RANGE):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                sx, sy = x + dx, y + dy
                sz = lm.surface_z(sx, sy)
                if not lm.in_bounds(sx, sy, sz):
                    continue
                if not lm.walkable(sx, sy, sz) or not lm.is_outside(sx, sy, sz):
                    continue
                if _water_near(fort, sx, sy, sz):
                    continue
                if _rock_below(fort, sx, sy, sz) < DEEP_ENOUGH:
                    continue
                return (sx, sy, sz)
    return None


def _water_near(fort, x, y, z) -> bool:
    """Open water within `DRY_MARGIN`, at this level or above it.

    Above it, because water runs downhill into the hole and not up out of it.
    """
    lm = fort.local
    for dy in range(-DRY_MARGIN, DRY_MARGIN + 1):
        for dx in range(-DRY_MARGIN, DRY_MARGIN + 1):
            cell = (x + dx, y + dy)
            if not lm.in_bounds(cell[0], cell[1], z):
                continue
            wz = lm.surface_z(*cell)
            if wz >= z and tile_data.get(lm.tile(cell[0], cell[1],
                                                 wz)).has("WATER"):
                return True
    return False


def _rock_below(fort, x, y, z) -> int:
    """How many levels of diggable rock lie straight under a cell."""
    lm = fort.local
    deep = 0
    for zz in range(z - 1, lm.zmin - 1, -1):
        t = tile_data.get(lm.tile(x, y, zz))
        if not (t.has("DIGGABLE") and t.has("WALL")):
            break
        deep += 1
    return deep


def _home(fort):
    """Where this fortress is.

    The stairway head, or the wagon if there is nowhere better. Asked in one
    place, so the workshops go up where the stairway went down.
    """
    wagon = fort.wagon if getattr(fort, "wagon", None) else fort._wagon_site()
    return _dry_ground(fort, wagon[0], wagon[1]) or wagon


def _dig_out_the_fortress(fort) -> Dict[str, int]:
    """Designate a stairway down and a floor of rooms under the fortress.

    Painted as designations rather than carved with `dig_out`, because the
    point is to watch dwarves do it: a job that nobody claims is exactly the
    kind of thing this driver exists to catch.
    """
    lm = fort.local
    x, y, z = _home(fort)
    counts = collections.Counter()
    for dz in range(0, 4):
        if lm.in_bounds(x, y, z - dz) and fort.designations.set(
            lm, x, y, z - dz, "stairs"
        ):
            counts["stairs"] += 1
    floor = z - 3
    for yy in range(y - ROOM_H // 2, y + ROOM_H // 2 + 1):
        for xx in range(x - ROOM_W // 2, x + ROOM_W // 2 + 1):
            if (xx, yy) == (x, y):
                continue
            if fort.designations.set(lm, xx, yy, floor, "dig"):
                counts["dig"] += 1
    # And what is lying about outside: wood for the carpenter, plants for the
    # larder. Both are labors every dwarf starts with. A stand of trees near
    # the wagon rather than every tree on the map, because a player marks what
    # is walking distance from the fortress and a thousand designations is a
    # benchmark rather than a game.
    #
    # Walking distance, and only what can be walked to. Twenty tiles as the
    # crow flies is not twenty tiles on foot, and a player marking a stand of
    # trees can see the river between him and half of it. Measured over a
    # full year of `year1` before this check existed: sixty trees painted,
    # twenty-three cut, and **thirty-seven left standing all year with every
    # dwarf idle** -- none of the thirty-seven reachable, all of them
    # correctly set aside by the job board, and the driver reporting
    # `left {'chop': 37}` as though the fortress had shirked.
    somebody = fort.dwarves()[0] if fort.dwarves() else None
    for r in range(1, 20):
        if counts["chop"] >= WOOD_WANTED and counts["gather"] >= PLANTS_WANTED:
            break
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                xx, yy = x + dx, y + dy
                if not lm.in_bounds(xx, yy, z):
                    continue
                tid = lm.tile(xx, yy, z)
                want = None
                if tid == "shrub" and counts["gather"] < PLANTS_WANTED:
                    want = "gather"
                elif (tile_data.get(tid).has("TREE")
                      and counts["chop"] < WOOD_WANTED):
                    want = "chop"
                if want is None:
                    continue
                if somebody is not None \
                        and not fort.can_reach(somebody, (xx, yy, z)):
                    counts["out of reach"] += 1
                    continue
                if fort.designations.set(lm, xx, yy, z, want):
                    counts[want] += 1
    return dict(counts)


def _clear_spot(fort, x, y, w, h, taken, *, soil=False):
    """The nearest site big enough to take a building, searching outward.

    On the *ground*, not on the wagon's z. An embark is hilly, so a patch of
    level ground at exactly the wagon's height often does not exist; the
    search ran on one z-plane, found nothing, and `_put_up_the_workshops`
    skipped the building without a word. Measured on the driver's own embark:
    two farm plots quietly not built, nothing grown all year, and seven
    dwarves starved on day sixteen with the run reporting FORT OK because it
    stopped on day seven.

    A tree standing on the site does not disqualify it. Nine tenths of the
    level ground on a wooded embark has a trunk somewhere in it -- measured,
    2010 of 2182 three-by-three patches on one map -- and clearing them is
    what a player does before building. The caller fells what it finds.

    Returns ``(x, y, z)``, because which floor it found matters.
    """
    lm = fort.local
    # The whole map, nearest first. A workshop is not much use forty tiles
    # from the stairway, but "there is nowhere on this map to put a farm" is
    # worth knowing and "there is nowhere within thirty tiles" is not: the
    # report carries how far it had to go.
    for r in range(1, max(lm.width, lm.height)):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                sx, sy = x + dx, y + dy
                # Level with the ground under the corner, whatever height
                # that is.
                sz = lm.surface_z(sx, sy)
                if not lm.in_bounds(sx, sy, sz):
                    continue
                cells = [(sx + a, sy + b, sz)
                         for a in range(w) for b in range(h)]
                if any(c in taken for c in cells):
                    continue
                if not all(lm.in_bounds(*c) and lm.is_outside(*c)
                           and lm.surface_z(c[0], c[1]) == sz for c in cells):
                    continue
                tiles = [tile_data.get(lm.tile(*c)) for c in cells]
                if any(t.has("WATER") for t in tiles):
                    continue
                # A felled trunk leaves grass, so a tree is both walkable
                # ground and soil once it is down.
                if not all(t.walk or t.has("TREE") for t in tiles):
                    continue
                if soil and not all(t.has("SOIL") or t.has("TREE")
                                    for t in tiles):
                    continue
                return (sx, sy, sz)
    return None


#: What the driver builds on the morning of day one. Two farms and a still
#: feed the fortress, the carpenter turns the felled trees into the beds, and
#: the barracks is where the militia trains -- a squad with nowhere to train
#: never picks up a weapon.
#: The tavern is the one building on this list that does nothing for
#: survival. It is here because the ritual is the only place the game gets
#: played end to end, and a driver that never builds one leaves gathering,
#: performances, audience stress and the instrument pool running in no test
#: at all -- a whole subsystem exercised only by unit fixtures. Measured over
#: a settled fortnight before this: 0 performances in every ritual run ever.
PLAN = ["farm", "farm", "still", "carpenter", "barracks", "tavern"] + ["bed"] * 7


def _put_up_the_workshops(fort) -> Tuple[List[str], List[str], int, int]:
    """Everything in `PLAN`, out by the stairway.

    Built rather than queued as construction jobs: this driver is about what
    the fortress does with its workshops over a year, and a first season spent
    watching nobody haul a boulder is a different test. The trees on each site
    come down the same way -- instantly, and for free. That is the same cheat
    as the building, and it buys the driver the same thing: a fortress that is
    already playing on the morning of day one.

    The last word on whether a building fits belongs to `can_place`, the rule
    the player builds by. A site this function likes and the game refuses is
    reported as a miss rather than built anyway; the driver is not allowed its
    own idea of buildable ground.
    """
    x, y, _z = _home(fort)
    taken = set()
    for b in fort.buildings:
        taken.update(b.cells())
    put: List[str] = []
    missed: List[str] = []
    felled = 0
    furthest = 0
    plan = list(PLAN)
    for kind in plan:
        k = buildings.KINDS[kind]
        spot = _clear_spot(fort, x, y, k.width, k.height, taken,
                           soil=kind in buildings.SOIL_KINDS)
        if spot is None:
            # Recorded rather than shrugged off. A driver that cannot put up
            # the one building that feeds everybody has not tested the
            # fortress, it has tested starvation.
            missed.append("%s: nowhere on the map" % kind)
            continue
        sx, sy, sz = spot
        furthest = max(furthest, max(abs(sx - x), abs(sy - y)))
        for cell in [(sx + a, sy + b, sz)
                     for a in range(k.width) for b in range(k.height)]:
            if tile_data.get(fort.local.tile(*cell)).has("TREE"):
                fort.fell_tree(cell)
                felled += 1
        ok, why = buildings.can_place(fort.local, kind, sx, sy, sz,
                                      fort.buildings)
        if not ok:
            missed.append("%s: %s" % (kind, why))
            continue
        b = Building(kind, sx, sy, sz)
        b.built = True
        fort.buildings.append(b)
        taken.update(b.cells())
        put.append(kind)
    return put, missed, felled, furthest


def _more_beds(fort) -> int:
    """Put up beds for anybody who has not got one. Returns how many.

    `PLAN` builds seven on the morning of day one and the carpenter is told
    `count 4, repeat False` -- four beds, once, for ever. A fortress that
    grows does not grow any beds: measured over a full year of `year1`, seven
    beds and fifteen dwarves at the end of it, with eight of them sleeping on
    the floor for a "slept on the floor" thought worth three unhappiness
    apiece, every night.

    Beds are *built*, not designated, so unlike the seasonal digging §151
    measured and threw away this costs the pathfinder nothing at all: no job
    goes on the board, and nobody walks anywhere they could not already.
    """
    want = len(fort.dwarves())
    have = sum(1 for b in fort.buildings if b.kind == "bed" and b.built)
    if have >= want:
        return 0
    x, y, _z = _home(fort)
    taken = set()
    for b in fort.buildings:
        taken.update(b.cells())
    k = buildings.KINDS["bed"]
    put = 0
    for _ in range(want - have):
        spot = _clear_spot(fort, x, y, k.width, k.height, taken)
        if spot is None:
            break
        sx, sy, sz = spot
        ok, _why = buildings.can_place(fort.local, "bed", sx, sy, sz,
                                       fort.buildings)
        if not ok:
            break
        b = Building("bed", sx, sy, sz)
        b.built = True
        fort.buildings.append(b)
        taken.update(b.cells())
        put += 1
    return put


def _stock_the_tavern(fort) -> int:
    """A small goods pile in the tavern, so the lute gets hauled to the music.

    The carpenter finishes the lute at the workshop, and nothing moves an
    item anywhere on its own: `_scan_stockpiles` posts hauling for goods a
    stockpile wants, and a `goods` pile accepts category `tool`, which is
    what every instrument is. The pile goes on the tavern's own walkable
    cells -- within `TAVERN_RADIUS` of the spot `instruments()` measures
    from -- so the haul that stocks the bar is the haul that stocks the band.

    Returns how many cells of pile were laid.
    """
    from ascii_warriors.fortress.buildings import Stockpile

    tavern = next((b for b in fort.buildings
                   if b.kind == "tavern" and b.built), None)
    if tavern is None:
        return 0
    cells = [c for c in tavern.cells() if fort.local.walkable(*c)]
    if not cells:
        return 0
    x, y, z = cells[0]
    pile = Stockpile("goods", x, y, z, 2, 2)
    fort.stockpiles.append(pile)
    return pile.w * pile.h


def _queue_the_orders(fort) -> List[str]:
    """Standing orders at whatever got built."""
    queued = []
    for b in fort.buildings:
        if not b.built:
            continue
        if b.kind == "still":
            b.orders.append({"recipe": "brew_ale", "count": 1, "repeat": True})
            queued.append("brew_ale")
        elif b.kind == "carpenter":
            b.orders.append({"recipe": "wood_bed", "count": 4, "repeat": False})
            queued.append("wood_bed")
            # One lute, once. `instruments()` pools whatever lies within the
            # tavern's radius, and a form played on the right instrument is
            # worth `INSTRUMENT_BONUS` instead of `NO_INSTRUMENT` -- a
            # twenty-two point swing nothing in the ritual had ever exercised.
            b.orders.append({"recipe": "wood_lute", "count": 1,
                             "repeat": False})
            queued.append("wood_lute")
    return queued


def _raise_the_militia(fort) -> Dict[str, Any]:
    """Put two dwarves under arms and set them to train.

    The manual's DEFENCE section is unambiguous about when to do this:
    "Goblins come once you have something worth taking. Raise a squad with m,
    pick a uniform, and enlist somebody; they will find their own weapons and
    armour out of your stockpiles and then train at a barracks until they are
    dangerous." A siege lands twenty-three tiles out and is on the dwarves
    forty steps later -- 2.8% of a day -- so raising one when it arrives is not
    a plan, and this driver had no militia at all.

    Two of seven, because that is what a fortress of seven can spare: a squad
    ordered to train is a squad off the labour force, and the run still has to
    dig, farm and brew.
    """
    dwarves = fort.dwarves()
    if len(dwarves) < 4:
        return {"squad": 0, "enlisted": 0, "barracks": False}
    squad = fort.military.add_squad("The Militia", "axe")
    barracks = next((b for b in fort.buildings
                     if b.kind == "barracks" and b.built), None)
    if barracks is not None:
        squad.barracks = barracks.id
    squad.order = "train"
    # The last two on the list: the first few are whoever the embark made its
    # miners, and a fortress that puts its only miner in the militia never
    # finishes its stairway.
    enlisted = 0
    for dwarf in dwarves[-2:]:
        if fort.military.enlist(squad, dwarf.id):
            enlisted += 1
    return {"squad": squad.id, "enlisted": enlisted,
            "barracks": barracks is not None}


class _Searches:
    """Counts what the pathfinder was asked and what it cost to answer.

    Wall-clock across embarks is not a number this box can measure honestly --
    it moves by a factor of three depending on what else is running -- but the
    node counts do not move at all. A search that finds a route and one that
    cannot are different in kind, not in degree, and this is how you see it.
    """

    def __init__(self) -> None:
        self.found = 0
        self.failed = 0
        self.found_nodes = 0
        self.failed_nodes = 0

    def __enter__(self):
        from ascii_warriors.engine import pathfind
        from ascii_warriors.fortress import dwarf as dwarf_mod

        self._real = pathfind.astar

        def counted(start, goal, neighbours, heuristic, max_nodes=50000):
            seen = [0]

            def wrapped(node):
                seen[0] += 1
                return neighbours(node)

            route = self._real(start, goal, wrapped, heuristic,
                               max_nodes=max_nodes)
            if route:
                self.found += 1
                self.found_nodes += seen[0]
            else:
                self.failed += 1
                self.failed_nodes += seen[0]
            return route

        pathfind.astar = counted
        dwarf_mod.astar = counted
        self._modules = (pathfind, dwarf_mod)
        return self

    def __exit__(self, *exc):
        pathfind, dwarf_mod = self._modules
        pathfind.astar = self._real
        dwarf_mod.astar = self._real
        return False

    def report(self) -> Dict[str, Any]:
        """The two numbers that matter, and the ratio between them."""
        return {
            "found": self.found,
            "failed": self.failed,
            "nodes_per_success": self.found_nodes // max(1, self.found),
            "nodes_per_failure": self.failed_nodes // max(1, self.failed),
            "nodes_total": self.found_nodes + self.failed_nodes,
        }


def _watch_the_tavern():
    """Count performances as they happen, by quality band.

    `perform.tick` returns a `Result` when somebody actually got up. The
    result does not say what instrument the band played -- `score()` consults
    the pool and discards the item -- so whether the lute mattered is read
    off the *bands*: the right instrument is a twenty-two point swing, about
    a band and a half, and `instruments()` says what was in the room. Wrapped
    the same way the workshops are watched: events, not leftovers.
    """
    from ascii_warriors.game import performance as performance_mod

    shows = collections.Counter()
    real = perform_mod.tick

    def counting(fort_, ticks):
        result = real(fort_, ticks)
        if result is not None:
            shows[performance_mod.QUALITY_NAMES[result.band]] += 1
        return result

    perform_mod.tick = counting
    return shows


def _watch_the_workshops(fort):
    """Count what the workshops finish, by the kind of shop that finished it.

    The still's invariant used to read the ale *stock* at the end of the run,
    which answers a different question. The embark arrives with 150 units, so
    "the still made nothing" could not fire until the fortress had drunk its
    way through every one of them -- measured over three seeds the stock went
    150 to 413, 150 to 617 and 150 to 427, and the check has never once fired.
    It was wrong the other way too: a still that worked all year for dwarves
    who drank the lot would have been reported as a still that made nothing.

    A finished `craft` job carries the building it was done at, so this counts
    the work rather than the leftovers.
    """
    made = collections.Counter()
    real = fort.complete_job

    def counting(dwarf, job):
        if job.kind == "craft":
            shop = next((b for b in fort.buildings if b.id == job.target), None)
            made[shop.kind if shop is not None else "?"] += 1
        return real(dwarf, job)

    fort.complete_job = counting
    return made


def _could_have_drunk(fort, dwarf) -> bool:
    """Whether a drink was within this dwarf's reach where it fell.

    The invariant this feeds used to ask a different question -- whether the
    *map* held any water at all -- and a map holds water in the sea, in sealed
    caverns and in the aquifer inside the rock. Seed alpha breaches a magma
    pipe on day one and burns half the fortress; the dwarves who then died of
    thirst were reported as a defect in the game because 360 cells of water
    existed somewhere on the map. That is a fortress being destroyed, which is
    the game working.

    Asked of the dwarf, and asked where and when it died: both barrels on the
    floor and open water it could have walked to, by the same `can_reach` the
    game itself uses.
    """
    here = (dwarf.x, dwarf.y, dwarf.z)
    within = fort.reach_from(here)
    for cell, pile in fort.items_on_ground.items():
        if cell in within and any(item.is_drink for item in pile):
            return True
    return fort.nearest_water(dwarf) is not None


def play(seed: str, days: int, *, size: str = "small", history: int = 60,
         report=None) -> Dict[str, Any]:
    """Run one fortress for *days* and return what the year did to it."""
    world = generate_world(RNG(seed).sub("w"), size=size,
                           history_years=history)
    wx, wy = suggest_site(world)
    fort = Fortress.embark(world, wx, wy, RNG(seed).sub("f"))
    lm = fort.local

    dug = _dig_out_the_fortress(fort)
    painted = dict(collections.Counter(fort.designations.cells.values()))
    built, unbuilt, felled, furthest = _put_up_the_workshops(fort)
    orders = _queue_the_orders(fort)
    _stock_the_tavern(fort)
    militia = _raise_the_militia(fort)
    water = sum(1 for z in range(lm.zmin, lm.zmax + 1)
                for y in range(lm.height) for x in range(lm.width)
                if tile_data.get(lm.tile(x, y, z)).has("WATER"))
    start = len(fort.dwarves())

    out: Dict[str, Any] = {
        "seed": seed, "at": (wx, wy), "designated": dug, "painted": painted,
        "built": built, "unbuilt": unbuilt, "felled": felled,
        "furthest_build": furthest,
        "orders": orders, "water_cells": water, "aquifer": len(fort.aquifer),
        "militia": militia,
        "started_with": start, "days": 0, "low_food": None, "low_drink": None,
    }
    low_food, low_drink = 1 << 30, 1 << 30
    # Checked as they die rather than at the end, because the map does not
    # hold still: magma spreads, water flows, and a corpse's surroundings an
    # hour later are not the ones it died in.
    counted, stranded = set(), []
    made = _watch_the_workshops(fort)
    shows = _watch_the_tavern()
    searches = _Searches()
    searches.__enter__()
    #: Days between the driver looking round for anybody without a bed.
    season = 28
    made_beds = 0
    for day in range(days):
        sim.run(fort, STEPS_PER_DAY)
        out["days"] = day + 1
        if (day + 1) % season == 0:
            made_beds += _more_beds(fort)
        for c in list(fort.creatures.values()):
            if c.id in counted or not c.body.dead:
                continue
            counted.add(c.id)
            if (getattr(c.body, "death_cause", "") or "") != "died of thirst":
                continue
            if _could_have_drunk(fort, c):
                stranded.append("%s on day %d" % (c.name, day + 1))
        low_food = min(low_food, fort.food_stock())
        low_drink = min(low_drink, fort.stock_count("dwarven_ale"))
        if report is not None and (day + 1) % 28 == 0:
            report("day %3d: %d alive, %d food, %d drink, %d jobs, %d left to dig"
                   % (day + 1, len(fort.dwarves()), fort.food_stock(),
                      fort.stock_count("dwarven_ale"), len(fort.jobs.jobs),
                      sum(1 for k in fort.designations.cells.values()
                          if k == "dig")))
        if not fort.dwarves():
            break

    searches.__exit__()
    causes = collections.Counter()
    for c in fort.creatures.values():
        if c.body.dead and getattr(c.body, "death_cause", ""):
            causes[c.body.death_cause] += 1
    left = collections.Counter(fort.designations.cells.values())
    spent = searches.report()
    spent["fills"] = fort.reach_fills
    spent["fill_cells"] = fort.reach_cells
    spent["nodes_and_fills"] = spent["nodes_total"] + fort.reach_cells
    out.update({
        "searches": spent,
        "left": dict(left),
        "done": {k: painted[k] - left.get(k, 0) for k in painted},
        "idle": sum(1 for d in fort.dwarves() if d.fort.job is None),
        "performances": dict(shows),
        "instruments": [i.def_id for i in perform_mod.instruments(fort)],
        "alive": len(fort.dwarves()),
        "deaths": dict(causes),
        "low_food": low_food, "low_drink": low_drink,
        "food": fort.food_stock(), "drink": fort.stock_count("dwarven_ale"),
        "left_undug": sum(1 for k in fort.designations.cells.values()
                          if k == "dig"),
        "thirst_in_reach": stranded,
        "made": dict(made),
        "wealth": fort.wealth,
        "beds": sum(1 for b in fort.buildings if b.kind == "bed" and b.built),
        "beds_added": made_beds,
        "lost": fort.lost,
    })
    return out


#: What a run prints, in the order it prints it.
#:
#: Named rather than inline because the reporting tests replay a canned
#: result through `main`, and that canned copy is a hand-written version of a
#: shape this module owns. It drifted twice -- v3.80 added `militia`, v3.91
#: added `beds_added` -- and each time five reporting tests died on a
#: `KeyError` and six more followed, discovered by the twenty-five-minute full
#: suite rather than by anything quick. `TestTheStubThatDriftedTwice` compares
#: the two in milliseconds now.
REPORT_KEYS = (
    "at", "painted", "done", "left", "built", "unbuilt",
    "felled", "furthest_build", "orders", "militia",
    "water_cells", "aquifer", "thirst_in_reach", "made",
    "started_with", "alive", "idle", "deaths", "food", "drink",
    "low_food", "low_drink", "left_undug", "lost",
    "wealth", "beds", "beds_added", "days", "searches", "performances",
    "instruments",
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", default="fort")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--size", default="small")
    ap.add_argument("--history", type=int, default=60)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    scratch_saves()
    report = None if args.quiet else (lambda line: print(line, flush=True))
    out = play(args.seed, args.days, size=args.size, history=args.history,
               report=report)
    if not args.quiet:
        for key in REPORT_KEYS:
            print("  %-13s %s" % (key, out[key]))

    # What this driver can honestly assert is about the *job board*: a
    # fortress that plays badly should not be reported as a defect in the
    # game. Whether these seven survive the winter depends on how well the
    # script above plays; whether painted work that can be reached ever gets
    # done does not.
    problems = []
    done = out["done"]
    if out["unbuilt"]:
        # A building the driver could not put up is a building the player
        # could not put up either: the site search asks the game's own
        # `can_place`. Silence here is how two farm plots went missing and
        # nobody noticed until the fortress starved.
        problems.append("could not put up: %s" % "; ".join(out["unbuilt"]))
    if done.get("dig", 0) == 0 and out["painted"].get("dig", 0) > 10:
        # Everything underground hangs off this. A fortress that cannot cut
        # its stairway files every room below as unreachable and then stands
        # about for a year, and the only thing that showed on the surface was
        # that the wood kept coming in.
        problems.append("%d cells painted for digging, none dug, %d of %d "
                        "idle" % (out["painted"]["dig"], out["idle"],
                                  out["alive"]))
    if sum(done.values()) == 0:
        problems.append("not one designated cell was worked in %d days"
                        % out["days"])
    if done.get("chop", 0) == 0 and out["painted"].get("chop", 0) > 20:
        problems.append("%d trees marked for felling and none felled"
                        % out["painted"]["chop"])
    if done.get("gather", 0) == 0 and out["painted"].get("gather", 0) > 4:
        problems.append("%d shrubs marked and none gathered"
                        % out["painted"]["gather"])
    if out["thirst_in_reach"]:
        problems.append("died of thirst with a drink in reach: %s"
                        % "; ".join(out["thirst_in_reach"]))
    if "brew_ale" in out["orders"] and not out["made"].get("still"):
        problems.append("the still had a standing order and brewed nothing")
    for problem in problems:
        print("FORT PROBLEM: %s" % problem)
    if problems:
        return 1
    if out["started_with"] and not out["alive"]:
        # Not a defect in the game. A fortress of seven with no military and
        # twenty thousand in wealth is exactly what a siege comes for, and two
        # separate seeds run to a hundred days were wiped between day
        # fifty-six and day eighty-four, every dwarf bled to death. It is a
        # defect in *this*, which printed OK over a graveyard: the run stops
        # at the last death, so every number above -- the food, the wealth,
        # the beds, the work left on the board -- was measured on a corpse.
        print("FORT LOST: %s, everybody died by day %d: %s"
              % (args.seed, out["days"], out["deaths"]))
        return 1
    print("FORT OK: %s, %d days, %d alive of %d, %d designated cells worked"
          % (args.seed, out["days"], out["alive"], out["started_with"],
             sum(done.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
