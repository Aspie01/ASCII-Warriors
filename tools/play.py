"""Play an adventurer, sensibly, for a long time, and report what happened.

`smoke` proves the screens fit together and `fuzz` presses keys at random.
Neither of them plays: the fortress has been measured by simulating a year and
looking at the wreckage since v3.46 -- five defects came out of it, including a
fortress that died of thirst with two thousand units of ale in the stockpile --
and adventure mode had no equivalent.

This is that equivalent. It drives the real action layer through
`Game.player_acts`, the way the play screen does, and looks after the
character the way a player would: drink when thirsty, eat when hungry, sleep
when tired, hit what is next to it, otherwise wander. Then it prints what
became of them.

    python -m tools.play --seed adv1 --turns 16000

The point is the invariants at the bottom. A run that ends with an adventurer
dead of thirst beside a river, or with needs that never moved, is a bug report.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys
import tempfile
import time
from typing import Optional, Sequence

from ascii_warriors.engine.rng import RNG
from ascii_warriors.game import actions
from ascii_warriors.game.state import Game
from ascii_warriors.world.worldgen import generate_world

#: Needs at which the driver stops what it is doing and sees to itself. Below
#: the fatal thresholds by a wide margin, because a player who waits for
#: `THIRST_DEATH` is not testing the game, they are testing the clock.
THIRSTY = 12000
HUNGRY = 16000
SLEEPY = 18000


def _look_after(game, why) -> Optional[int]:
    """Deal with whatever the body is complaining about. Returns a cost."""
    p = game.player
    if p.needs.thirst > THIRSTY:
        cost = actions.drink(game)
        why["drank" if cost > 0 else "nothing to drink"] += 1
        return cost
    if p.needs.hunger > HUNGRY:
        food = next((i for i in p.inventory.items if i.defn.nutrition), None)
        cost = actions.eat(game, food) if food is not None else 0
        why["ate" if cost > 0 else "nothing to eat"] += 1
        return cost
    if p.needs.drowsy > SLEEPY:
        why["slept"] += 1
        return actions.sleep(game, 8)
    return None


def _adjacent_foe(game):
    """A hostile standing next to the player, if there is one."""
    p = game.player
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == dy == 0:
                continue
            c = game.creature_at(p.x + dx, p.y + dy, p.z)
            if c is not None and not c.body.dead and c.faction == "hostile":
                return dx, dy
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

    why: collections.Counter = collections.Counter()
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
            foe = _adjacent_foe(game)
            if foe is not None:
                cost = actions.attack_dir(game, *foe)
                why["fought"] += 1
            else:
                dx, dy = game.rng.choice(
                    [(1, 0), (-1, 0), (0, 1), (0, -1),
                     (1, 1), (-1, -1), (1, -1), (-1, 1)])
                cost = actions.move_or_attack(game, dx, dy)
                if cost <= 0:
                    why["blocked"] += 1
                    cost = actions.wait(game)
        game.player_acts(max(1, cost))
        far = max(far, abs(p.x - start[0]) + abs(p.y - start[1]))
        for need in peak:
            peak[need] = max(peak[need], getattr(p.needs, need))

    out = {
        "seed": seed,
        "turns": turn + 1,
        "seconds": time.perf_counter() - t0,
        "dead": p.body.dead,
        "cause": p.body.death_cause or "",
        "peak": peak,
        "furthest": far,
        "actions": dict(why),
        "water_nearby": actions.water_source_near(game),
    }
    report("survived %(turns)d turns in %(seconds).0fs; dead=%(dead)s %(cause)s"
           % out)
    report("peak needs %(peak)s, furthest %(furthest)d tiles" % out)
    report("actions %(actions)s" % out)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", default="play")
    ap.add_argument("--turns", type=int, default=16000)
    ap.add_argument("--size", default="small")
    ap.add_argument("--history", type=int, default=120)
    args = ap.parse_args(argv)

    os.environ.setdefault("ASCII_WARRIORS_SAVE_DIR", tempfile.mkdtemp())
    out = play(args.seed, args.turns, size=args.size, history=args.history)

    # The invariants. A driver that only prints is a driver nobody reads.
    problems = []
    if out["peak"]["thirst"] < 100:
        problems.append("needs never moved: the clock is not running")
    if out["cause"] == "died of thirst" and out["water_nearby"]:
        problems.append("died of thirst standing next to water")
    if out["turns"] < args.turns and not out["dead"]:
        problems.append("stopped early without dying")
    for problem in problems:
        print("PLAY PROBLEM: %s" % problem)
    if problems:
        return 1
    print("PLAY OK: %s, %d turns" % (args.seed, out["turns"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
