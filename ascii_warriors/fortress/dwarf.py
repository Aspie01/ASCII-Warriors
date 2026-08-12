"""Dwarves at work.

A dwarf looks after itself first — drink, food, sleep — then takes the nearest
job its labors allow and works it until it is finished or something stops it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..engine import geometry
from ..engine.pathfind import astar
from ..engine.rng import RNG
from ..game.entity import Creature
from ..game.item import Item
from .jobs import WORK_SCALE, Job, work_rate
from .labors import LaborSet, PROFESSION_SKILLS, labors_for_profession

Cell = Tuple[int, int, int]

#: Needs at which a dwarf drops what it is doing.
THIRST_URGENT = 9000
HUNGER_URGENT = 14000
SLEEP_URGENT = 15000

#: How far a dwarf will walk for a job before giving up on it.
MAX_PATH_NODES = 6000


class DwarfState:
    """Everything a dwarf has that only matters inside a fortress."""

    __slots__ = ("labors", "job", "path", "path_goal", "nickname", "bed",
                 "mood", "mood_ticks", "idle_ticks", "squad", "carrying",
                 "workshop", "blocked", "sleeping")

    def __init__(self, labors: Optional[LaborSet] = None) -> None:
        self.labors = labors or LaborSet()
        self.job: Optional[Job] = None
        self.path: List[Cell] = []
        self.path_goal: Optional[Cell] = None
        self.blocked = 0
        self.sleeping = False
        self.nickname = ""
        self.bed: Optional[int] = None
        self.mood = ""
        self.mood_ticks = 0
        self.idle_ticks = 0
        self.squad = False
        self.carrying: Optional[int] = None
        self.workshop: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the fortress-only state."""
        return {
            "labors": self.labors.to_list(),
            "job": self.job.id if self.job else None,
            "nickname": self.nickname,
            "bed": self.bed,
            "mood": self.mood,
            "mood_ticks": self.mood_ticks,
            "squad": self.squad,
            "workshop": self.workshop,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "DwarfState":
        """Rebuild from :meth:`to_dict`."""
        s = cls(LaborSet.from_list(d.get("labors")))
        s.nickname = str(d.get("nickname", ""))
        s.bed = d.get("bed")
        s.mood = str(d.get("mood", ""))
        s.mood_ticks = int(d.get("mood_ticks", 0))
        s.squad = bool(d.get("squad", False))
        s.workshop = d.get("workshop")
        return s


def attach(dwarf: Creature, profession: str = "") -> Creature:
    """Give an ordinary creature the state it needs to work in a fortress."""
    state = DwarfState(labors_for_profession(profession))
    dwarf.fort = state
    dwarf.labors = state.labors
    dwarf.job = None
    if profession:
        dwarf.profession = profession
        for skill, level in PROFESSION_SKILLS.get(profession, {}).items():
            dwarf.skills.set_level(skill, max(dwarf.skills.level(skill), level))
    return dwarf


def make_dwarf(rng: RNG, profession: str = "", *, race: str = "dwarf") -> Creature:
    """Create a fortress dwarf of a given profession."""
    from ..game.entity import make_creature

    c = make_creature(rng, race, faction="fortress", equip=False)
    attach(c, profession)
    if profession in ("miner", "woodcutter"):
        c.inventory.add(Item("pick" if profession == "miner" else "axe", "iron"))
        c.inventory.auto_equip()
    elif profession == "soldier":
        c.inventory.add(Item("axe", "iron"))
        c.inventory.add(Item("shield", "oak"))
        c.inventory.add(Item("mail_shirt", "iron"))
        c.inventory.auto_equip()
    return c


def display_title(dwarf) -> str:
    """Name plus profession, the way the units list shows it."""
    from .labors import profession_title

    name = dwarf.fort.nickname or dwarf.name
    return "%s, %s" % (name, profession_title(dwarf))


# --------------------------------------------------------------------------- #
# Movement
# --------------------------------------------------------------------------- #


def _heuristic(a: Cell, b: Cell) -> float:
    return geometry.chebyshev(a[0], a[1], b[0], b[1]) + abs(a[2] - b[2]) * 2.0


def work_positions(lm, goal: Cell) -> List[Cell]:
    """Every cell a dwarf could stand in and still reach *goal*.

    This has to agree exactly with :func:`at_or_beside`. When it does not, a
    dwarf paths to a spot it does not believe it has arrived at, and walks on
    the same tile until it dies of thirst.
    """
    gx, gy, gz = goal
    out: List[Cell] = []
    for dx, dy in geometry.DIRS8:
        cell = (gx + dx, gy + dy, gz)
        if lm.walkable(*cell):
            out.append(cell)
    for dz in (-1, 1):
        cell = (gx, gy, gz + dz)
        if lm.walkable(*cell):
            out.append(cell)
    return out


def path_to(fort, dwarf, goal: Cell, *, adjacent: bool = True) -> bool:
    """Plan a route to a goal. Returns False if there is no way there."""
    state = dwarf.fort
    start = (dwarf.x, dwarf.y, dwarf.z)
    if state.path and state.path_goal == goal and start in state.path:
        return True

    lm = fort.local
    targets: List[Cell] = work_positions(lm, goal) if adjacent else []
    if lm.walkable(*goal):
        targets.append(goal)
    if not targets:
        return False
    targets.sort(key=lambda c: _heuristic(start, c))

    for target in targets[:6]:
        if target == start:
            state.path = [start]
            state.path_goal = goal
            return True
        route = astar(start, target, lm.path_neighbours, _heuristic,
                      max_nodes=MAX_PATH_NODES)
        if route:
            state.path = route
            state.path_goal = goal
            return True
    return False


def step_along(fort, dwarf) -> bool:
    """Take one step along the planned route. False if blocked."""
    state = dwarf.fort
    start = (dwarf.x, dwarf.y, dwarf.z)
    if not state.path:
        return False
    if start not in state.path:
        state.path = []
        return False
    idx = state.path.index(start)
    if idx + 1 >= len(state.path):
        return True
    nxt = state.path[idx + 1]
    if not fort.local.walkable(*nxt):
        state.path = []
        return False
    other = fort.creature_at(*nxt)
    if other is not None and other is not dwarf:
        return _step_around(fort, dwarf, other, nxt)
    dwarf.x, dwarf.y, dwarf.z = nxt
    state.blocked = 0
    return True


def _step_around(fort, dwarf, other, nxt: Cell) -> bool:
    """Somebody is in the way.

    Waiting politely is what deadlocks a fortress: seven dwarves queue for the
    same barrel of ale and none of them ever reaches it. So a dwarf waits one
    beat, then shoulders past its colleague, then gives up on the route
    entirely.
    """
    state = dwarf.fort
    state.blocked += 1
    if state.blocked < 2:
        return True

    if getattr(other, "fort", None) is not None:
        here = (dwarf.x, dwarf.y, dwarf.z)
        other.x, other.y, other.z = here
        other.fort.path = []
        other.fort.path_goal = None
        other.fort.blocked = 0
        dwarf.x, dwarf.y, dwarf.z = nxt
        state.blocked = 0
        return True

    if state.blocked >= 4:
        state.path = []
        state.path_goal = None
        state.blocked = 0
        for dx, dy in fort.rng.shuffled(list(geometry.DIRS8)):
            cell = (dwarf.x + dx, dwarf.y + dy, dwarf.z)
            if fort.local.walkable(*cell) and fort.creature_at(*cell) is None:
                dwarf.x, dwarf.y, dwarf.z = cell
                break
    return True


def at_or_beside(dwarf, cell: Cell) -> bool:
    """True if the dwarf is close enough to work on a cell.

    Adjacent on the same level, or directly above or below it — a miner
    standing on the floor can dig the rock beneath its feet.
    """
    dx = dwarf.x - cell[0]
    dy = dwarf.y - cell[1]
    dz = dwarf.z - cell[2]
    if dz == 0:
        return abs(dx) <= 1 and abs(dy) <= 1
    return abs(dz) == 1 and dx == 0 and dy == 0


# --------------------------------------------------------------------------- #
# The work loop
# --------------------------------------------------------------------------- #


def take_turn(fort, dwarf, ticks: int) -> None:
    """Run one dwarf for *ticks* of fortress time."""
    state = getattr(dwarf, "fort", None)
    if state is None:
        return
    if dwarf.body.dead:
        return
    if dwarf.body.unconscious > 0 or dwarf.body.stunned > 0:
        return

    if _handle_danger(fort, dwarf):
        return
    if _handle_needs(fort, dwarf, ticks):
        return

    job = state.job
    if job is None or job.id not in fort.jobs.jobs:
        state.job = None
        job = _claim_job(fort, dwarf)
        if job is None:
            _idle(fort, dwarf)
            return

    _work_job(fort, dwarf, job, ticks)


def _handle_danger(fort, dwarf) -> bool:
    """Fight or run from a hostile in sight. True if it took the turn."""
    from ..game import combat
    from ..game.ai import can_see

    enemies = [
        c for c in fort.creatures.values()
        if not c.body.dead and c.faction == "hostile" and c.z == dwarf.z
        and geometry.chebyshev(dwarf.x, dwarf.y, c.x, c.y) <= 10
    ]
    if not enemies:
        return False
    enemies.sort(key=lambda c: geometry.chebyshev(dwarf.x, dwarf.y, c.x, c.y))
    foe = enemies[0]
    dist = geometry.chebyshev(dwarf.x, dwarf.y, foe.x, foe.y)
    state = dwarf.fort

    if state.squad:
        if dist <= 1:
            combat.melee_attack(dwarf, foe, rng=fort.rng, log=fort.log)
            if foe.body.dead:
                fort.kill_creature(foe)
            return True
        if path_to(fort, dwarf, (foe.x, foe.y, foe.z)):
            step_along(fort, dwarf)
            return True
        return False

    # Civilians fight only when cornered.
    if dist <= 1:
        combat.melee_attack(dwarf, foe, rng=fort.rng, log=fort.log)
        if foe.body.dead:
            fort.kill_creature(foe)
        return True
    if dist <= 6:
        _release_job(fort, dwarf)
        dx, dy = geometry.normalize_dir(dwarf.x - foe.x, dwarf.y - foe.y)
        for cand in ((dwarf.x + dx, dwarf.y + dy, dwarf.z),
                     (dwarf.x + dx, dwarf.y, dwarf.z),
                     (dwarf.x, dwarf.y + dy, dwarf.z)):
            if fort.local.walkable(*cand) and fort.creature_at(*cand) is None:
                dwarf.x, dwarf.y, dwarf.z = cand
                return True
        return True
    return False


def _handle_needs(fort, dwarf, ticks: int) -> bool:
    """Drink, eat or sleep if it has become urgent. True if it took the turn.

    The most pressing need wins. A fixed order looks reasonable until a dwarf
    spends every turn of a long walk to the ale barrel getting more tired, and
    drops dead of exhaustion two tiles short of it.
    """
    needs = dwarf.needs
    state = dwarf.fort
    if state.sleeping and needs.drowsy > 0 \
            and needs.thirst < THIRST_URGENT * 1.5 \
            and needs.hunger < HUNGER_URGENT * 1.5:
        return _go_sleep(fort, dwarf, ticks)
    state.sleeping = False
    wants = [
        (needs.thirst / float(THIRST_URGENT), _go_drink),
        (needs.hunger / float(HUNGER_URGENT), _go_eat),
        (needs.drowsy / float(SLEEP_URGENT), _go_sleep),
    ]
    wants.sort(key=lambda w: -w[0])
    for urgency, action in wants:
        if urgency < 1.0:
            break
        if action(fort, dwarf, ticks):
            return True
    return False


def _go_drink(fort, dwarf, ticks: int) -> bool:
    """Find something to drink and get to it."""
    item = fort.find_consumable(dwarf, drink=True)
    if item is not None:
        cell = fort.item_cell(item)
        if cell is None or at_or_beside(dwarf, cell):
            fort.consume(dwarf, item, drink=True)
            return True
        _release_job(fort, dwarf)
        if path_to(fort, dwarf, cell):
            step_along(fort, dwarf)
            return True
    if _drink_water(fort, dwarf):
        return True
    if dwarf.needs.thirst > THIRST_URGENT * 1.6:
        fort.warn_once("thirst", "Your dwarves have nothing to drink!")
    return False


def _go_eat(fort, dwarf, ticks: int) -> bool:
    """Find something to eat and get to it."""
    item = fort.find_consumable(dwarf, drink=False)
    if item is not None:
        cell = fort.item_cell(item)
        if cell is None or at_or_beside(dwarf, cell):
            fort.consume(dwarf, item, drink=False)
            return True
        _release_job(fort, dwarf)
        if path_to(fort, dwarf, cell):
            step_along(fort, dwarf)
            return True
    elif dwarf.needs.hunger > HUNGER_URGENT * 1.5:
        fort.warn_once("hunger", "Your dwarves are starving!")
    return False


def _go_sleep(fort, dwarf, ticks: int) -> bool:
    """Go to bed, or lie down where you stand.

    A dwarf that starts sleeping keeps sleeping until it is rested. Waking at
    the threshold and dozing off again a few seconds later leaves it
    permanently half-asleep and permanently useless.
    """
    needs = dwarf.needs
    state = dwarf.fort
    bed = fort.bed_for(dwarf)
    here = (dwarf.x, dwarf.y, dwarf.z)
    target = bed.center if bed is not None else here
    exhausted = needs.drowsy > SLEEP_URGENT * 1.6
    if here == target or bed is None or exhausted:
        if not state.sleeping:
            state.sleeping = True
        needs.sleep(ticks * 4)
        dwarf.body.rest_heal(ticks * 2, dwarf.attributes.factor("recuperation"))
        if needs.drowsy <= 0:
            state.sleeping = False
            if bed is not None and here == target:
                needs.add_thought("slept in a good bed", -6)
            else:
                needs.add_thought("slept on the floor", 3)
        return True
    _release_job(fort, dwarf)
    if path_to(fort, dwarf, target, adjacent=False):
        step_along(fort, dwarf)
        return True
    return False


def _drink_water(fort, dwarf) -> bool:
    """Go and drink from a river or a well. Dwarves resent this."""
    cell = fort.nearest_water(dwarf)
    if cell is None:
        return False
    if at_or_beside(dwarf, cell):
        dwarf.needs.thirst = 0
        dwarf.needs.add_thought("had to drink water", 4)
        fort.clear_warning("thirst")
        return True
    _release_job(fort, dwarf)
    if path_to(fort, dwarf, cell):
        step_along(fort, dwarf)
        return True
    return False


def _claim_job(fort, dwarf) -> Optional[Job]:
    """Take the best available job, if the dwarf can reach it."""
    state = dwarf.fort
    for job in fort.jobs.for_dwarf(dwarf)[:12]:
        if not fort.prepare_job(dwarf, job):
            continue
        if not path_to(fort, dwarf, job.cell):
            fort.jobs.release(job)
            fort.cancel_preparation(dwarf, job)
            continue
        fort.jobs.assign(job, dwarf)
        state.job = job
        state.idle_ticks = 0
        return job
    return None


def _release_job(fort, dwarf) -> None:
    """Drop whatever the dwarf was doing."""
    state = dwarf.fort
    if state.job is not None:
        fort.abandon_job(dwarf, state.job)
        state.job = None
    state.path = []
    state.path_goal = None


def _work_job(fort, dwarf, job: Job, ticks: int) -> None:
    """Fetch what a job needs, walk to it, and put work into it."""
    state = dwarf.fort

    fetch = fort.fetch_target(dwarf, job)
    if fetch is not None:
        if at_or_beside(dwarf, fetch):
            if not fort.pick_up_for(dwarf, job):
                fort.abandon_job(dwarf, job)
                state.job = None
            return
        if not path_to(fort, dwarf, fetch) or not step_along(fort, dwarf):
            fort.abandon_job(dwarf, job)
            state.job = None
        return

    if not at_or_beside(dwarf, job.cell):
        if not path_to(fort, dwarf, job.cell):
            fort.abandon_job(dwarf, job)
            state.job = None
            return
        if not step_along(fort, dwarf):
            fort.abandon_job(dwarf, job)
            state.job = None
        return

    job.progress += max(
        1, work_rate(dwarf, job) * max(1, ticks) // WORK_SCALE)
    if job.skill:
        dwarf.add_exp(job.skill, max(1, ticks // 8))
    dwarf.needs.exert(max(1, ticks // 2))
    if job.done:
        fort.complete_job(dwarf, job)
        state.job = None
        state.path = []
        state.path_goal = None


def _idle(fort, dwarf) -> None:
    """Wander a little when there is nothing to do."""
    state = dwarf.fort
    state.idle_ticks += 1
    if state.idle_ticks % 4 != 0:
        return
    if fort.rng.chance(0.5):
        dx, dy = fort.rng.dir8()
        cell = (dwarf.x + dx, dwarf.y + dy, dwarf.z)
        if fort.local.walkable(*cell) and fort.creature_at(*cell) is None:
            dwarf.x, dwarf.y, dwarf.z = cell
    if state.idle_ticks > 600:
        dwarf.needs.add_thought("had nothing to do", 2)
        state.idle_ticks = 0
