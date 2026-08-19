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
that starves beside a full field, or dies of thirst on a map with a river
across it, exits non-zero and says so.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence

from ascii_warriors.data.calendar import TICKS_PER_DAY
from ascii_warriors.engine.rng import RNG
from ascii_warriors.fortress import sim
from ascii_warriors.fortress.buildings import Building
from ascii_warriors.fortress.fortress import Fortress
from ascii_warriors.ui.fort.embark import suggest_site
from ascii_warriors.world import tiles as tile_data
from ascii_warriors.world.worldgen import generate_world

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


def _dig_out_the_fortress(fort) -> Dict[str, int]:
    """Designate a stairway down and a floor of rooms under the wagon.

    Painted as designations rather than carved with `dig_out`, because the
    point is to watch dwarves do it: a job that nobody claims is exactly the
    kind of thing this driver exists to catch.
    """
    lm = fort.local
    x, y, z = fort.wagon if getattr(fort, "wagon", None) else fort._wagon_site()
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
                if tid == "shrub" and counts["gather"] < PLANTS_WANTED:
                    if fort.designations.set(lm, xx, yy, z, "gather"):
                        counts["gather"] += 1
                elif (tile_data.get(tid).has("TREE")
                      and counts["chop"] < WOOD_WANTED):
                    if fort.designations.set(lm, xx, yy, z, "chop"):
                        counts["chop"] += 1
    return dict(counts)


def _clear_spot(fort, x, y, z, w, h, taken, *, soil=False):
    """The nearest patch of open ground big enough, searching outward."""
    lm = fort.local
    for r in range(1, 22):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                sx, sy = x + dx, y + dy
                cells = [(sx + a, sy + b, z)
                         for a in range(w) for b in range(h)]
                if any(c in taken for c in cells):
                    continue
                if not all(lm.walkable(*c) and lm.is_outside(*c)
                           for c in cells):
                    continue
                if soil and not all(
                        tile_data.get(lm.tile(*c)).has("SOIL") for c in cells):
                    continue
                return (sx, sy)
    return None


def _put_up_the_workshops(fort) -> List[str]:
    """A still, a farm, a carpenter and beds, on the surface beside the wagon.

    Built rather than queued as construction jobs: this driver is about what
    the fortress does with its workshops over a year, and a first season spent
    watching nobody haul a boulder is a different test.
    """
    x, y, z = fort._wagon_site()
    taken = set()
    for b in fort.buildings:
        taken.update(b.cells())
    put: List[str] = []
    plan = [("farm", 3, 3), ("farm", 3, 3), ("still", 3, 3),
            ("carpenter", 3, 3)] + [("bed", 1, 1)] * 7
    for kind, w, h in plan:
        spot = _clear_spot(fort, x, y, z, w, h, taken,
                           soil=kind in ("farm",))
        if spot is None:
            continue
        b = Building(kind, spot[0], spot[1], z)
        b.built = True
        fort.buildings.append(b)
        taken.update(b.cells())
        put.append(kind)
    return put


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
    return queued


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
    built = _put_up_the_workshops(fort)
    orders = _queue_the_orders(fort)
    water = sum(1 for z in range(lm.zmin, lm.zmax + 1)
                for y in range(lm.height) for x in range(lm.width)
                if tile_data.get(lm.tile(x, y, z)).has("WATER"))
    start = len(fort.dwarves())

    out: Dict[str, Any] = {
        "seed": seed, "at": (wx, wy), "designated": dug, "painted": painted,
        "built": built,
        "orders": orders, "water_cells": water, "aquifer": len(fort.aquifer),
        "started_with": start, "days": 0, "low_food": None, "low_drink": None,
    }
    low_food, low_drink = 1 << 30, 1 << 30
    searches = _Searches()
    searches.__enter__()
    for day in range(days):
        sim.run(fort, STEPS_PER_DAY)
        out["days"] = day + 1
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
        "alive": len(fort.dwarves()),
        "deaths": dict(causes),
        "low_food": low_food, "low_drink": low_drink,
        "food": fort.food_stock(), "drink": fort.stock_count("dwarven_ale"),
        "left_undug": sum(1 for k in fort.designations.cells.values()
                          if k == "dig"),
        "wealth": fort.wealth,
        "beds": sum(1 for b in fort.buildings if b.kind == "bed" and b.built),
        "lost": fort.lost,
    })
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", default="fort")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--size", default="small")
    ap.add_argument("--history", type=int, default=60)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    os.environ.setdefault("ASCII_WARRIORS_SAVE_DIR", tempfile.mkdtemp())
    report = None if args.quiet else (lambda line: print(line, flush=True))
    out = play(args.seed, args.days, size=args.size, history=args.history,
               report=report)
    if not args.quiet:
        for key in ("at", "painted", "done", "left", "built", "orders",
                    "water_cells", "aquifer", "started_with", "alive", "idle",
                    "deaths", "food", "drink", "wealth", "beds", "days",
                    "searches"):
            print("  %-13s %s" % (key, out[key]))

    # What this driver can honestly assert is about the *job board*: a
    # fortress that plays badly should not be reported as a defect in the
    # game. Whether these seven survive the winter depends on how well the
    # script above plays; whether painted work that can be reached ever gets
    # done does not.
    problems = []
    done = out["done"]
    if sum(done.values()) == 0:
        problems.append("not one designated cell was worked in %d days"
                        % out["days"])
    if done.get("chop", 0) == 0 and out["painted"].get("chop", 0) > 20:
        problems.append("%d trees marked for felling and none felled"
                        % out["painted"]["chop"])
    if done.get("gather", 0) == 0 and out["painted"].get("gather", 0) > 4:
        problems.append("%d shrubs marked and none gathered"
                        % out["painted"]["gather"])
    if out["water_cells"] and "died of thirst" in out["deaths"]:
        problems.append("died of thirst on a map with %d cells of water"
                        % out["water_cells"])
    if out["drink"] <= 0 and "brew_ale" in out["orders"]:
        problems.append("the still had a standing order and made nothing")
    for problem in problems:
        print("FORT PROBLEM: %s" % problem)
    if problems:
        return 1
    print("FORT OK: %s, %d days, %d alive of %d, %d designated cells worked"
          % (args.seed, out["days"], out["alive"], out["started_with"],
             sum(done.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
