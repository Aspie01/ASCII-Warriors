"""War: who is attacking you, why, and what it costs them.

A siege used to be a number of goblins that appeared at the edge of the map.
This makes it an act by a civilization that exists in the world's history: a
named commander, soldiers off that civilization's own population, armed to
whatever its metalworking runs to, sent because it is at war with the people
who sent you.

What happens to them matters as much. Kill an army and the civilization that
raised it is smaller for it, permanently, and the legends screen says who died
at your gates. Lose, and the same screen says your fortress fell to them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..data import creatures as creature_data
from ..data import names as name_data
from ..engine.rng import RNG
from ..game.entity import make_creature
from ..world import history as history_mod

#: Races that raid a dwarven fortress without needing a reason.
RAIDERS: Tuple[str, ...] = ("goblin", "kobold")

#: Wealth a fortress has to be worth before anybody makes the trip.
NOTICE_WEALTH = 500

#: How many attackers a civilization can raise, before wealth is counted.
BASE_STRENGTH = 3

#: A siege breaks when this much of it is on the floor.
ROUT_LOSSES = 0.55

#: What the survivors do about it: leave, by the shortest route out.
RETREAT_SPEED = 2

#: How hard a routed invader looks for a way off the map before giving up.
#: Generous, because it only runs when the cached route has been broken and
#: a besieger that stands in the corridor for ever is the worse outcome.
RETREAT_SEARCH = 8000

#: A routed army that cannot find its way out is gone anyway after this long.
#: Something wedged in a corridor must not leave the alarm ringing for ever.
FLEE_TICKS = 3000


class Siege:
    """One army, on its way in or on its way out."""

    def __init__(self, civ_id: Optional[int], commander_hf: Optional[int],
                 strength: int, year: int) -> None:
        self.civ_id = civ_id
        self.commander_hf = commander_hf
        self.strength = strength
        self.year = year
        self.killed = 0
        self.routed = False
        self.recorded = False
        #: Tick the rout began, so a stuck survivor cannot besiege you for ever.
        self.fleeing_since = 0

    @property
    def losses(self) -> float:
        """How much of the army is down, as a fraction."""
        return self.killed / float(max(1, self.strength))

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the siege."""
        return {"civ": self.civ_id, "commander": self.commander_hf,
                "strength": self.strength, "year": self.year,
                "killed": self.killed, "routed": self.routed,
                "recorded": self.recorded, "fleeing": self.fleeing_since}

    @classmethod
    def from_dict(cls, d) -> "Siege":
        """Rebuild from :meth:`to_dict`."""
        s = cls(d.get("civ"), d.get("commander"), int(d.get("strength", 1)),
                int(d.get("year", 0)))
        s.killed = int(d.get("killed", 0))
        s.routed = bool(d.get("routed", False))
        s.recorded = bool(d.get("recorded", False))
        s.fleeing_since = int(d.get("fleeing", 0))
        return s


# --------------------------------------------------------------------------- #
# Who wants you dead
# --------------------------------------------------------------------------- #


def home_civ(fort) -> Optional[Any]:
    """The civilization that sent the expedition, if there is one left."""
    if fort.civ_id is not None:
        civ = fort.world.civ(fort.civ_id)
        if civ is not None and civ.destroyed is None:
            return civ
    dwarves = [c for c in fort.world.civs
               if c.race == "dwarf" and c.destroyed is None]
    if not dwarves:
        return None
    civ = dwarves[0]
    fort.civ_id = civ.id
    return civ


def enemies(fort) -> List[Any]:
    """Every civilization that would send an army here.

    Anyone at war with the mountainhomes, plus the ones who never needed a
    declaration.
    """
    home = home_civ(fort)
    out = []
    for civ in fort.world.civs:
        if civ.destroyed is not None or civ is home:
            continue
        if civ.race in RAIDERS:
            out.append(civ)
        elif home is not None and civ.id in home.at_war_with:
            out.append(civ)
    return out


def strength_for(fort, civ) -> int:
    """How many soldiers this civilization sends to a fortress this rich.

    A civilization can only send what it has: raid a goblin nation until it is
    two villages and a camp and the sieges get smaller, which is the point of
    winning one.
    """
    population = sum(s.population for s in fort.world.sites
                     if s.civ_id == civ.id and not s.is_ruin)
    wealth = max(0, fort.wealth - NOTICE_WEALTH)
    want = BASE_STRENGTH + wealth // 2500 + fort.siege_count
    return max(0, min(want, 16, 2 + population // 40))


def commander(fort, civ):
    """A named leader for the army, from the civilization's own people."""
    living = [f for f in fort.world.figures.values()
              if f.civ_id == civ.id and f.alive(fort.time.year)
              and ("hero" in f.flags or "leader" in f.flags)]
    if living:
        return fort.rng.choice(living)
    fig = history_mod.new_figure(fort.world, fort.rng, civ.race, civ.id,
                                 civ.capital, year=fort.time.year,
                                 profession="warrior",
                                 age=fort.rng.randint(20, 60))
    fig.flags.add("hero")
    fig.titles.append(name_data.title_for(fort.rng, "hero"))
    fig.stats["prowess"] = fort.rng.randint(6, 14)
    return fig


# --------------------------------------------------------------------------- #
# Sending them
# --------------------------------------------------------------------------- #


def plan(fort) -> Optional[Siege]:
    """Decide whether anybody attacks, and with what."""
    if fort.wealth < NOTICE_WEALTH or not fort.dwarves():
        return None
    hostile = enemies(fort)
    if not hostile:
        return None
    civ = fort.rng.choice(hostile)
    strength = strength_for(fort, civ)
    if strength <= 0:
        return None
    leader = commander(fort, civ)
    return Siege(civ.id, leader.id if leader else None, strength,
                 fort.time.year)


def launch(fort, siege: Siege) -> List:
    """Put the army on the edge of the map and tell the fortress about it."""
    civ = fort.world.civ(siege.civ_id) if siege.civ_id is not None else None
    race = civ.race if civ is not None else "goblin"
    tier = _tier(fort, civ)
    entry = fort.edge_arrival()

    out = []
    for i in range(siege.strength):
        kind = race
        if race == "goblin" and i and fort.rng.chance(0.15):
            kind = "troll"
        foe = make_creature(fort.rng, kind, faction="hostile",
                            level=min(5, 1 + fort.siege_count // 2),
                            tier=tier)
        foe.x, foe.y, foe.z = fort._free_spot(entry, i)
        foe.wx, foe.wy = fort.wx, fort.wy
        fort.add_creature(foe)
        out.append(foe)

    leader = fort.world.figures.get(siege.commander_hf) \
        if siege.commander_hf is not None else None
    if out and leader is not None:
        head = out[0]
        head.name = leader.name
        if leader.titles:
            head.title = leader.titles[-1]
        head.hf_id = leader.id
        head.skills.set_level("fighter", 8)

    fort.siege = siege
    fort.siege_count += 1
    fort.military.alert = "danger"
    _announce(fort, siege, civ, leader, len(out))
    return out


def _tier(fort, civ) -> int:
    """How well armed they are, from how much civilization is behind them."""
    if civ is None:
        return 2
    sites = sum(1 for s in fort.world.sites
                if s.civ_id == civ.id and not s.is_ruin)
    return max(0, min(5, 1 + sites // 3))


def _announce(fort, siege: Siege, civ, leader, count: int) -> None:
    """Say who has come, and from where."""
    who = civ.name if civ is not None else "an enemy"
    if leader is not None:
        fort.log.bad("%s has come from %s. They number %d."
                     % (leader.display_name, who, count))
    else:
        fort.log.bad("An army of %s has arrived. They number %d."
                     % (who, count))
    fort.log.warn("Get everyone inside and pull up the bridge.")


# --------------------------------------------------------------------------- #
# What it costs them
# --------------------------------------------------------------------------- #


def on_kill(fort, foe) -> None:
    """Count an invader's death against the army that brought it."""
    siege = fort.siege
    if siege is None or foe.faction != "hostile":
        return
    siege.killed += 1
    if not siege.routed and siege.losses >= ROUT_LOSSES:
        rout(fort)


def rout(fort) -> None:
    """The army breaks. Whoever is left runs for the edge of the map.

    Invaders that fight to the last man are a grind, and worse, they take the
    dwarves with them. An army that breaks is a battle you can win and a story
    you can tell.
    """
    siege = fort.siege
    if siege is None or siege.routed:
        return
    siege.routed = True
    siege.fleeing_since = fort.ticks
    fort.log.good("The attackers break and run!")
    record(fort, won=True)


def _edge_distance(lm, x: int, y: int) -> int:
    """How far a cell is from the nearest edge of the map."""
    return min(x, y, lm.width - 1 - x, lm.height - 1 - y)


def retreat_step(fort, foe) -> bool:
    """Move one routed invader towards the nearest map edge. True if it left.

    Along the walking graph, not along a compass. The first version stepped
    in x or y on the invader's own level, which meant an army that had walked
    down a hillside to reach the fortress could never walk back up it: a
    goblin routed at the bottom of a slope stood on the spot for the rest of
    the fortress's life, and because a siege only ends when the map is clear
    of it, the alarm never stopped either. Ramps and stairs are part of the
    way out, so the route is searched for rather than guessed at -- breadth
    first, because "any edge of the map" is a goal you can describe and
    cannot point at, which is what A* would want.

    The route is kept in the same scratch state the approach uses and only
    re-searched when the invader is no longer standing on it. An invader
    walled in with no way out at all stops moving, which is what a besieger
    in a sealed corridor should do; `FLEE_TICKS` clears it eventually.
    """
    from ..engine.pathfind import path_to

    lm = fort.local
    state = fort.hostile_state.setdefault(foe.id, {"path": [], "goal": None})
    for _ in range(RETREAT_SPEED):
        pos = (foe.x, foe.y, foe.z)
        if _edge_distance(lm, *pos[:2]) <= 0:
            fort.creatures.pop(foe.id, None)
            return True
        route = state.get("out") or []
        if pos not in route:
            route = path_to(
                pos, fort.path_neighbours,
                lambda c: _edge_distance(lm, c[0], c[1]) <= 0,
                max_nodes=RETREAT_SEARCH,
            ) or []
            state["out"] = route
        idx = route.index(pos) if pos in route else -1
        if idx < 0 or idx + 1 >= len(route):
            break
        nxt = route[idx + 1]
        if not lm.walkable(*nxt) or fort.creature_at(*nxt) is not None:
            state["out"] = []
            break
        foe.x, foe.y, foe.z = nxt
    return False


def record(fort, *, won: bool) -> None:
    """Write the siege into the world, and take the losses off the enemy.

    A civilization that loses an army is smaller for it: fewer people at home,
    and a smaller army next time. Winning a siege is the only thing a fortress
    does that makes the world easier.
    """
    siege = fort.siege
    if siege is None or siege.recorded:
        return
    siege.recorded = True
    civ = fort.world.civ(siege.civ_id) if siege.civ_id is not None else None
    year = fort.time.year
    if civ is not None and siege.killed:
        _bleed(fort, civ, siege.killed)
    who = civ.name if civ is not None else "raiders"
    if won:
        text = "%s broke against %s. %d of them died." % (
            who, fort.name, siege.killed)
    else:
        text = "%s was overrun by %s." % (fort.name, who)
    history_mod.record(
        fort.world, year, "battle", text,
        [siege.commander_hf] if siege.commander_hf else [],
        [fort.site_id] if fort.site_id else [],
        [civ.id] if civ is not None else [],
    )


def _bleed(fort, civ, dead: int) -> None:
    """Take an army's dead out of the population that raised it."""
    sites = [s for s in fort.world.sites
             if s.civ_id == civ.id and not s.is_ruin and s.population > 0]
    if not sites:
        return
    share = max(1, dead // len(sites))
    for site in sites:
        site.population = max(1, site.population - share)


def summary(fort) -> str:
    """One line for the status bar while an army is on the map."""
    siege = fort.siege
    if siege is None:
        return ""
    civ = fort.world.civ(siege.civ_id) if siege.civ_id is not None else None
    who = civ.name if civ is not None else "raiders"
    if siege.routed:
        return "%s are fleeing" % who
    return "%s: %d dead of %d" % (who, siege.killed, siege.strength)
