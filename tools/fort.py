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
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ascii_warriors.data.calendar import (
    DAYS_PER_MONTH, GameTime, TICKS_PER_DAY)
from ascii_warriors.engine.rng import RNG
from ascii_warriors.fortress import buildings, perform as perform_mod, sim
from ascii_warriors.fortress.buildings import Building
from ascii_warriors.fortress.fortress import Fortress
from ascii_warriors.game.weather import starting_weather
from ascii_warriors.ui.fort.embark import suggest_site
from ascii_warriors.world import tiles as tile_data
from ascii_warriors.world.worldgen import generate_world
from tools import scratch_saves

#: When the staged raid lands, and how many come. Day three of seven: the
#: militia has had two days to equip and train, and four days remain for the
#: fight and the burying. Three raiders against seven dwarves and a two-dwarf
#: militia is the fight `spawn_attack`'s own tests call survivable.
RAID_DAY = 3
RAID_STRENGTH = 3

#: One simulation step is `sim.STEP_TICKS`; a day is this many steps.
STEPS_PER_DAY = TICKS_PER_DAY // sim.STEP_TICKS

#: The month and day the driver's fortress starts on, so that a seven-day run
#: turns a season.
#:
#: `Fortress.embark` starts every fortress on the 1st of Granite, the first
#: day of Spring, so the first season boundary is the 1st of Hematite -- day
#: 85, twelve weeks out. The ritual runs seven days. `_calendar` had
#: therefore never turned in any driver run ever made, and nothing hanging
#: off it had run end to end: seasonal thoughts, appointments, `_world_turns`
#: and the megabeast it can bring, `justice.season`, marriages, births,
#: migrants, the autumn caravan, werebeasts and necromancers. Measured
#: across the four ritual seeds: seasons turned, 0 of 4.
#:
#: This is `RAID_DAY`'s argument one level up, and it is settled the same
#: way -- the driver arranges for the thing to happen, through the game's own
#: machinery, early enough that the ordinary run sees it.
#:
#: Autumn, and late. Two choices, both measured over the four seeds at seven
#: days, against 22 alive and 399 designated cells worked as shipped:
#:
#:   as shipped     turned 0/4   alive 22   worked 399
#:   -> Summer d6   turned 4/4   alive 14   worked 399
#:   -> Autumn d6   turned 4/4   alive 35   worked 399
#:
#: The work is identical either way -- the same 399 cells, because the turn
#: is the last thing the run does. What differs is who is standing at the
#: end. Summer runs `_maybe_attack`, and a siege on top of the day-three
#: raid costs eight dwarves; Autumn brings the migrant wave and the caravan
#: and hands back thirteen. `_maybe_attack`'s ground is already covered --
#: that is what `RAID_DAY` is for -- and migrants and the caravan are
#: covered by nothing else at all.
#:
#: An earlier draft put the boundary on day three. That makes the run a
#: survival test of a three-day-old fortress rather than a test of the game:
#: `_maybe_beast` fires against seven dwarves who have had no time to dig in,
#: a named megabeast lands, and half the seeds are wiped. The boundary
#: belongs after the work, not before it.
SEASON_START_MONTH = 6           # Galena, the last month of Summer
SEASON_START_DAY = 23

#: Which day of the run the season turns on, from the start date above. The
#: run has to be at least this long before a driver that did not turn one is
#: a defect rather than a short run.
SEASON_TURNS_ON = DAYS_PER_MONTH - SEASON_START_DAY + 1

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
#:
#: No coffin on this list, deliberately: see `_bury_the_dead`.
PLAN = ["farm", "farm", "still", "carpenter", "barracks", "tavern"] + ["bed"] * 7

#: How many coffins the driver puts up when somebody dies. One coffin holds
#: one dwarf and a raid does not stop at one.
COFFINS = 2


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


def _bury_the_dead(fort) -> int:
    """Put up coffins once the fortress has somebody to put in one.

    Dwarves have always died in the ritual -- the staged raid on day three
    sees to that -- and not one of them was ever buried. `_scan_burials`
    answered every death the same way, "There is nowhere to bury the dead.
    Build a coffin.", on three of the four ritual seeds, because `PLAN` had
    no coffin on it and never had. Measured over ten driver seeds at seven
    days: **0 burials, in every seed, ever** -- so `_finish_bury`, the corpse
    reserved against a second hauler, the tomb a coffin makes of its room,
    and the one answer this game has to §180's ghosts all ran in unit
    fixtures and nowhere else.

    Built on the death rather than on the morning of day one, which is both
    the honest thing and the cheap one. Honest, because that is the loop the
    game asks a player for: the fortress prints the warning, and the answer
    to it is a coffin. Cheap, because until somebody dies the map is byte
    for byte the map the ritual has always run, so the day-three raid meets
    exactly the fortress it has always met.

    That last part is not a nicety. Putting two coffins on `PLAN` instead
    moves whatever `_clear_spot` would have given the next building, and one
    dwarf standing one tile over is a different week: seed `alpha` survives
    the raid with three by a margin of about that much, and with the coffins
    on the list it was wiped on day three. Nothing was wrong with the
    coffins -- over ten seeds the arms differ by 85 alive against 79, and
    individual seeds move ±10 in *both* directions -- but a ritual that goes
    red on a seed's coin flip has stopped being a signal.

    Returns how many were put up.
    """
    if not fort.unburied:
        return 0
    if any(b.kind == "coffin" for b in fort.buildings):
        return 0
    x, y, _z = _home(fort)
    taken = set()
    for b in fort.buildings:
        taken.update(b.cells())
    k = buildings.KINDS["coffin"]
    put = 0
    for _ in range(COFFINS):
        spot = _clear_spot(fort, x, y, k.width, k.height, taken)
        if spot is None:
            break
        sx, sy, sz = spot
        ok, _why = buildings.can_place(fort.local, "coffin", sx, sy, sz,
                                       fort.buildings)
        if not ok:
            break
        b = Building("coffin", sx, sy, sz)
        b.built = True
        fort.buildings.append(b)
        taken.update(b.cells())
        put += 1
    return put


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
    # Move the clock before anything is dug, so the whole run happens on the
    # date the driver means. The season is used for exactly one thing outside
    # `_calendar` -- the weather -- so the map is untouched and the only
    # thing that has to be redone is the sky, re-rolled here for the season
    # the clock now says rather than the Spring `embark` assumed.
    fort.time = GameTime.at(fort.time.year, SEASON_START_MONTH,
                            SEASON_START_DAY, 8, 0)
    tile0 = world.tile(wx, wy)
    fort.weather = starting_weather(fort.rng, tile0.biome, tile0.temperature,
                                    fort.time.season)
    lm = fort.local

    began = time.time()
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
    #: The raid. Real sieges and thieves arrive on a clock measured in
    #: seasons, and this driver runs seven days -- so across every ritual run
    #: ever made, no fortress once saw a hostile: the militia, the alarm
    #: watch, the burrow, the traps and everything in `war.py` ran in no
    #: end-to-end test at all. Day three, through `sim.spawn_attack`, which
    #: is the game's own raid entry: late enough that the militia has kitted
    #: up, small enough that a seven-dwarf fortress is meant to survive it.
    raid = {"foes": 0, "day": RAID_DAY, "alarm_rose": False,
            "cleared_by": None, "dwarves_lost": 0}
    raiders: List[Any] = []
    # Event-true, not sampled. The first cut of this polled
    # `fort.military.alarm` at the end of each day, and the raid was met,
    # fought and cleared inside day three -- the watch had already called
    # all-clear by the sample, so the driver's very first run reported "the
    # alarm never rose" over a fortress that had raised it, fought under it
    # and stood down correctly. The same mistake as measuring reachability
    # from a treetop: the instrument's grid, not the game.
    real_alarm = fort.military.sound_alarm

    def noting_alarm(log=None):
        raid["alarm_rose"] = True
        return real_alarm(log)

    fort.military.sound_alarm = noting_alarm

    #: What the calendar did. Event-true for the same reason the alarm is:
    #: `_calendar` is the only thing that moves `season_index`, and it does
    #: it once, at the boundary, before it runs anything -- so counting the
    #: moves counts the turns, and a turn cannot be missed by looking at the
    #: wrong moment. What arrived because of it is in the log like anything
    #: else.
    #: `migrant_waves` is the fortress's own counter, incremented by
    #: `_maybe_migrants` when a wave actually lands, so nothing here has to
    #: be monkeypatched and nothing leaks into the next run in the process.
    turn = {"turned": 0, "entered": [], "on_day": None, "waves": 0}
    waves_at_start = fort.migrant_waves

    #: Who went in the ground. Counted off the coffins rather than off the
    #: log, because `MessageLog` caps and collapses repeats and a fortress
    #: that buries four in one afternoon prints one line. A coffin with a
    #: name in it is the record the game itself keeps.
    def buried_now():
        return sum(1 for b in fort.buildings
                   if b.kind == "coffin" and b.buried is not None)

    coffins_put = 0
    seen_index = fort.season_index
    dwarves_at_raid = 0
    for day in range(days):
        if day + 1 == RAID_DAY and days >= RAID_DAY:
            dwarves_at_raid = len(fort.dwarves())
            raiders = sim.spawn_attack(fort, RAID_STRENGTH)
            raid["foes"] = len(raiders)
        sim.run(fort, STEPS_PER_DAY)
        # After the day, so the first death and the answer to it are a day
        # apart -- the fortress notices, then acts.
        coffins_put += _bury_the_dead(fort)
        if fort.season_index != seen_index:
            # `season_index` starts at zero and `_calendar`'s first call only
            # records where the fortress began; the turn that counts is the
            # one after that.
            if seen_index:
                turn["turned"] += 1
                turn["entered"].append(fort.time.season)
                if turn["on_day"] is None:
                    turn["on_day"] = day + 1
            seen_index = fort.season_index
            turn["waves"] = fort.migrant_waves - waves_at_start
        if raiders and raid["cleared_by"] is None and not fort.hostiles():
            raid["cleared_by"] = day + 1
            raid["dwarves_lost"] = dwarves_at_raid - len(fort.dwarves())
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
        "raid": raid,
        "season": turn,
        "dead": {
            "coffins": sum(1 for b in fort.buildings
                           if b.kind == "coffin" and b.built),
            "coffins_put": coffins_put,
            "buried": buried_now(),
            "waiting": len(fort.unburied),
            # Only the dead the fortress has had a full day to answer.
            # `unburied` keeps the death tick, so the driver does not have
            # to guess: seed `beta` draws a vampire in its Autumn migrant
            # wave, the victim is found drained on the last night, and a
            # corpse four hours old beside a fresh coffin is a burial in
            # progress, not a burial chain that has stopped.
            "waiting_long": sum(
                1 for died in fort.unburied.values()
                if fort.ticks - died >= TICKS_PER_DAY),
            "ghosts": len(fort.ghosts),
        },
        # Wall time. Seed `alpha` spent versions costing twenty-one minutes
        # per ritual -- 3747 failed searches at the full 6000-node budget and
        # 2035 flood fills, constant from at least v4.01 -- and nothing
        # noticed, because the ritual reports OK or FAIL and never how long a
        # seed took. A number nobody prints is a number nobody sees move.
        "seconds": round(time.time() - began, 1),
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
    "instruments", "raid", "season", "dead", "seconds",
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
    # §153's guarantee, held on every run: something hostile arrives and the
    # watch raises the alarm. The driver does not assert the fight is *won* --
    # whether seven dwarves beat three goblins is the fortress playing well or
    # badly -- but an alarm that never rose over a raid is the defect v3.93
    # fixed, arrived back.
    raid_out = out["raid"]
    if raid_out["foes"] and not raid_out["alarm_rose"]:
        problems.append("a raid of %d landed on day %d and the alarm never "
                        "rose" % (raid_out["foes"], raid_out["day"]))
    # The same guarantee for the calendar. A driver that stops turning a
    # season goes quietly back to the state §«the season the ritual never
    # saw» found it in -- seasonal thoughts, appointments, the world's own
    # turn, justice, marriages, births, migrants and the caravan all running
    # in unit fixtures and nowhere else. A run too short to reach the
    # boundary is not scolded for it, the way a run too short to reach the
    # raid is not.
    season_out = out["season"]
    if out["days"] >= SEASON_TURNS_ON and not season_out["turned"]:
        problems.append("%d days run and the season never turned; nothing "
                        "on the seasonal clock was exercised" % out["days"])
    # A fortress that still has hands, and standing empty coffins, and its
    # own dead on the floor, has a burial chain that is not running. Not "did
    # anybody die" -- plenty of runs lose nobody -- and not "was everybody
    # buried", because a fortress that ends with nobody alive had nobody left
    # to carry them.
    dead_out = out["dead"]
    if (out["alive"] and dead_out["waiting_long"]
            and dead_out["coffins"] > dead_out["buried"]):
        problems.append("%d of the fortress's own dead have lain out for "
                        "over a day with %d empty coffin(s) and %d dwarves "
                        "alive"
                        % (dead_out["waiting_long"],
                           dead_out["coffins"] - dead_out["buried"],
                           out["alive"]))
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
