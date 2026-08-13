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
                 "workshop", "blocked", "sleeping", "lonely")

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
        #: Ticks since this dwarf last spoke to anybody.
        self.lonely = 0

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
            "lonely": self.lonely,
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
        s.lonely = int(d.get("lonely", 0))
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


def make_dwarf(rng: RNG, profession: str = "", *, race: str = "dwarf",
               age: Optional[int] = None) -> Creature:
    """Create a fortress dwarf of a given profession.

    *age* is for the ones that are born here rather than walking in: a
    newborn has no profession and no skills, and picks both up on the
    birthday it stops being a child.
    """
    from ..game.entity import make_creature

    c = make_creature(rng, race, faction="fortress", equip=False)
    if age is not None:
        c.age = age
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


#: Work a dwarf can do to the tile above or below the one it stands on. You
#: dig the rock under your feet; you do not drink from a barrel through a
#: solid floor, and a fortress that thinks you can will crowd every thirsty
#: dwarf onto the one tile underneath the ale and let them die there.
VERTICAL_JOBS = frozenset({"dig", "channel", "stairs", "ramp", "smooth"})


def vertical_reach(job) -> bool:
    """True if this job can be done to the tile above or below."""
    return getattr(job, "kind", "") in VERTICAL_JOBS


def work_positions(lm, goal: Cell, *, vertical: bool = True) -> List[Cell]:
    """Every cell a dwarf could stand in and still reach *goal*.

    This has to agree exactly with :func:`at_or_beside`, *vertical* included.
    When it does not, a dwarf paths to a spot it does not believe it has
    arrived at, and walks on the same tile until it dies of thirst.
    """
    gx, gy, gz = goal
    out: List[Cell] = []
    for dx, dy in geometry.DIRS8:
        cell = (gx + dx, gy + dy, gz)
        if lm.walkable(*cell):
            out.append(cell)
    if vertical:
        for dz in (-1, 1):
            cell = (gx, gy, gz + dz)
            if lm.walkable(*cell):
                out.append(cell)
    return out


def path_to(fort, dwarf, goal: Cell, *, adjacent: bool = True,
            vertical: bool = True) -> bool:
    """Plan a route to a goal. Returns False if there is no way there."""
    state = dwarf.fort
    start = (dwarf.x, dwarf.y, dwarf.z)
    if state.path and state.path_goal == goal and start in state.path:
        return True

    lm = fort.local
    targets: List[Cell] = (work_positions(lm, goal, vertical=vertical)
                           if adjacent else [])
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
        route = astar(start, target, fort.path_neighbours, _heuristic,
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


def at_or_beside(dwarf, cell: Cell, *, vertical: bool = True) -> bool:
    """True if the dwarf is close enough to work on a cell.

    Adjacent on the same level, and — for the work that allows it — directly
    above or below: a miner standing on the floor can dig the rock beneath
    its feet. Reaching a thing rather than a tile does not allow it, or a
    dwarf picks a barrel up through the ceiling.
    """
    dx = dwarf.x - cell[0]
    dy = dwarf.y - cell[1]
    dz = dwarf.z - cell[2]
    if dz == 0:
        return abs(dx) <= 1 and abs(dy) <= 1
    return vertical and abs(dz) == 1 and dx == 0 and dy == 0


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

    if _flee_water(fort, dwarf):
        return
    if _handle_danger(fort, dwarf):
        return
    if _handle_wounds(fort, dwarf, ticks):
        return
    if _handle_needs(fort, dwarf, ticks):
        return
    if _serving_time(fort, dwarf):
        return
    if _too_young(fort, dwarf):
        return

    job = state.job
    if job is None or job.id not in fort.jobs.jobs:
        state.job = None
        job = _claim_job(fort, dwarf)
        if job is None:
            _idle(fort, dwarf)
            return

    _work_job(fort, dwarf, job, ticks)


def _too_young(fort, dwarf) -> bool:
    """Children play. True if that is what this turn was.

    They idle rather than working, which means they end up in the tavern with
    everybody else, which is how a child comes to have friends of its own by
    the time it is old enough to hold a pick.
    """
    from . import social

    if not social.is_child(dwarf):
        return False
    release_job(fort, dwarf)
    _idle(fort, dwarf)
    return True


def _serving_time(fort, dwarf) -> bool:
    """A convicted dwarf does no work. True if that is what is happening.

    It still eats, drinks and sleeps -- the needs run before this -- but it
    takes no job and it does not wander, which is what being held amounts to.
    A sentence costs the fortress its legendary mason for a few days, and that
    cost is the whole point of having a law.
    """
    from . import justice

    if not fort.crimes or not justice.is_jailed(fort, dwarf):
        return False
    release_job(fort, dwarf)
    dwarf.fort.idle_ticks = 0
    return True


#: How far a soldier will chase, and how far a civilian panics.
SOLDIER_SIGHT = 24
CIVILIAN_SIGHT = 10


def _handle_danger(fort, dwarf) -> bool:
    """Fight, chase or run. True if it took the turn."""
    from ..game import combat

    state = dwarf.fort
    squad = fort.military.squad_of(dwarf.id)
    reach = SOLDIER_SIGHT if squad is not None else CIVILIAN_SIGHT

    from ..game import stealth

    enemies = [
        c for c in fort.creatures.values()
        if not c.body.dead and c.faction == "hostile"
        and abs(c.z - dwarf.z) <= 2
        and geometry.chebyshev(dwarf.x, dwarf.y, c.x, c.y) <= reach
        # A kobold with sneak 8 is not standing in plain sight. It has had
        # that skill since v3.3 and nothing has ever read it.
        and stealth.noticed_by(fort, c, dwarf)
    ]
    if not enemies:
        return _hold_position(fort, dwarf, squad)

    enemies.sort(key=lambda c: geometry.chebyshev(dwarf.x, dwarf.y, c.x, c.y))
    foe = enemies[0]
    if squad is not None and squad.order == "kill" and squad.target is not None:
        wanted = fort.creatures.get(squad.target)
        if wanted is not None and not wanted.body.dead:
            foe = wanted
    dist = geometry.chebyshev(dwarf.x, dwarf.y, foe.x, foe.y)

    if dist <= 1 and foe.z == dwarf.z:
        release_job(fort, dwarf)
        combat.melee_attack(dwarf, foe, rng=fort.rng, log=fort.log)
        if foe.body.dead:
            fort.kill_creature(foe)
        return True

    # Nobody fights on past the point of collapse, siege or no siege.
    if dist > 2 and _desperate(dwarf):
        return False

    if squad is not None:
        release_job(fort, dwarf)
        if path_to(fort, dwarf, (foe.x, foe.y, foe.z)):
            step_along(fort, dwarf)
            return True
        return False

    # Civilians run for the burrow if there is one, and away if there is not.
    if dist <= CIVILIAN_SIGHT:
        release_job(fort, dwarf)
        if _retreat_to_burrow(fort, dwarf):
            return True
        dx, dy = geometry.normalize_dir(dwarf.x - foe.x, dwarf.y - foe.y)
        for cand in ((dwarf.x + dx, dwarf.y + dy, dwarf.z),
                     (dwarf.x + dx, dwarf.y, dwarf.z),
                     (dwarf.x, dwarf.y + dy, dwarf.z)):
            if fort.local.walkable(*cand) and fort.creature_at(*cand) is None:
                dwarf.x, dwarf.y, dwarf.z = cand
                return True
        return True
    return False


def _magma_near(fort, cell: Cell) -> bool:
    """True if there is *loose* magma in this cell or the next one over.

    Magma kills on contact rather than over a minute, so the useful moment to
    run is while it is still next door. The sea and the pipe do not count: a
    corridor mined past a sealed pipe has magma one tile away for its whole
    length, and a dwarf that runs from that runs for ever, back and forth,
    until it dies of thirst beside a barrel of ale.
    """
    x, y, z = cell
    magma = fort.magma
    if magma.at(x, y, z) > 0:
        return True
    for dx, dy in geometry.DIRS8:
        side = (x + dx, y + dy, z)
        if magma.depth.get(side, 0) > 0 and side not in magma.infinite:
            return True
    return False


def _flee_water(fort, dwarf) -> bool:
    """Get out of rising water, or away from magma. True if it took the turn.

    Pathing already refuses to route through either, but that does not help a
    dwarf standing in a room that is filling up around it.
    """
    from ..world.fluids import SWIM_DEPTH

    here = (dwarf.x, dwarf.y, dwarf.z)
    burning = _magma_near(fort, here)
    if fort.water.at(*here) < SWIM_DEPTH - 1 and not burning:
        return False
    release_job(fort, dwarf)

    # Straight to the driest neighbour if there is one; that is usually enough.
    lm = fort.local
    best, best_depth = None, fort.water.at(*here) + (9 if burning else 0)
    for dx, dy in geometry.DIRS8:
        cell = (dwarf.x + dx, dwarf.y + dy, dwarf.z)
        if not lm.walkable(*cell) or fort.creature_at(*cell) is not None:
            continue
        if fort.magma.at(*cell) > 0:
            continue
        depth = fort.water.at(*cell) + (9 if _magma_near(fort, cell) else 0)
        if depth < best_depth:
            best, best_depth = cell, depth
    if best is not None:
        dwarf.x, dwarf.y, dwarf.z = best
        return True

    # Otherwise look further for dry land, and if there is none, swim for it.
    for radius in (4, 10):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                cell = (dwarf.x + dx, dwarf.y + dy, dwarf.z)
                if fort.water.at(*cell) > 0 or not lm.walkable(*cell):
                    continue
                if path_to(fort, dwarf, cell, adjacent=False):
                    step_along(fort, dwarf)
                    return True
    dwarf.add_exp("swimming", 6)
    return True


def _handle_wounds(fort, dwarf, ticks: int) -> bool:
    """A hurt dwarf goes to bed and stays there. True if it took the turn.

    A doctor with a patient waiting is the exception: somebody has to be well
    enough to do the binding, and a scratched surgeon is better than a dead
    fortress.
    """
    from . import hospital

    if not hospital.is_hurt(dwarf):
        hospital.release_bed(fort, dwarf)
        return False
    state = dwarf.fort
    if state.job is not None and state.job.kind == "treat":
        return False
    if not hospital.is_critical(dwarf) and dwarf.fort.labors.has("medicine") \
            and any(hospital.is_critical(p) for p in hospital.patients(fort)):
        return False

    release_job(fort, dwarf)
    bed = hospital.free_bed(fort, dwarf)
    here = (dwarf.x, dwarf.y, dwarf.z)
    if bed is None or here == bed.center:
        dwarf.body.rest_heal(ticks * 3, dwarf.attributes.factor("recuperation"))
        if bed is not None:
            dwarf.needs.add_thought("rested in a hospital bed", -2)
        return True
    if path_to(fort, dwarf, bed.center, adjacent=False):
        step_along(fort, dwarf)
        return True
    dwarf.body.rest_heal(ticks * 3, dwarf.attributes.factor("recuperation"))
    return True


def _desperate(dwarf) -> bool:
    """True when a need has passed the point where anything else matters."""
    needs = dwarf.needs
    return (needs.thirst > THIRST_URGENT * 1.5
            or needs.hunger > HUNGER_URGENT * 1.5
            or needs.drowsy > SLEEP_URGENT * 1.8)


def _hold_position(fort, dwarf, squad) -> bool:
    """No enemy in sight: stand where you were told, or shelter."""
    if _desperate(dwarf):
        return False
    if squad is not None:
        if squad.order == "station" and squad.station is not None:
            here = (dwarf.x, dwarf.y, dwarf.z)
            if geometry.chebyshev(here[0], here[1], squad.station[0],
                                  squad.station[1]) <= 2 \
                    and here[2] == squad.station[2]:
                return True
            release_job(fort, dwarf)
            if path_to(fort, dwarf, squad.station):
                step_along(fort, dwarf)
                return True
        return False
    if fort.military.alarm and fort.military.burrow is not None:
        if fort.military.in_burrow(dwarf.x, dwarf.y, dwarf.z):
            return False
        release_job(fort, dwarf)
        return _retreat_to_burrow(fort, dwarf)
    return False


def _retreat_to_burrow(fort, dwarf) -> bool:
    """Head for the safe zone. False if there is nowhere to go."""
    military = fort.military
    if military.burrow is None:
        return False
    if military.in_burrow(dwarf.x, dwarf.y, dwarf.z):
        return True
    cells = [c for c in military.burrow_cells() if fort.local.walkable(*c)]
    if not cells:
        return False
    cells.sort(key=lambda c: _heuristic((dwarf.x, dwarf.y, dwarf.z), c))
    for cell in cells[:4]:
        if path_to(fort, dwarf, cell, adjacent=False):
            step_along(fort, dwarf)
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
        if cell is None or at_or_beside(dwarf, cell, vertical=False):
            fort.consume(dwarf, item, drink=True)
            return True
        release_job(fort, dwarf)
        if path_to(fort, dwarf, cell, vertical=False):
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
        if cell is None or at_or_beside(dwarf, cell, vertical=False):
            fort.consume(dwarf, item, drink=False)
            return True
        release_job(fort, dwarf)
        if path_to(fort, dwarf, cell, vertical=False):
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
    release_job(fort, dwarf)
    if path_to(fort, dwarf, target, adjacent=False):
        step_along(fort, dwarf)
        return True
    return False


def _drink_water(fort, dwarf) -> bool:
    """Go and drink from a river or a well. Dwarves resent this."""
    cell = fort.nearest_water(dwarf)
    if cell is None:
        return False
    if at_or_beside(dwarf, cell, vertical=False):
        dwarf.needs.thirst = 0
        dwarf.needs.add_thought("had to drink water", 4)
        fort.clear_warning("thirst")
        return True
    release_job(fort, dwarf)
    if path_to(fort, dwarf, cell, vertical=False):
        step_along(fort, dwarf)
        return True
    return False


#: Jobs whose target walks about: the work is wherever it has got to.
CHASING_JOBS = frozenset({"treat", "tend", "slaughter"})


def _follow_target(fort, dwarf, job: Job) -> None:
    """Keep a job aimed at a creature pointed at where the creature is."""
    if job.kind not in CHASING_JOBS or job.target is None:
        return
    quarry = fort.creatures.get(job.target)
    if quarry is None or quarry.body.dead:
        return
    cell = (quarry.x, quarry.y, quarry.z)
    if cell != job.cell:
        fort.jobs.retarget(job, cell)
        state = dwarf.fort
        state.path = []
        state.path_goal = None


def _claim_job(fort, dwarf) -> Optional[Job]:
    """Take the best available job, if the dwarf can reach it."""
    state = dwarf.fort
    for job in fort.jobs.for_dwarf(dwarf)[:12]:
        if not fort.prepare_job(dwarf, job):
            continue
        if not path_to(fort, dwarf, job.cell, vertical=vertical_reach(job)):
            fort.jobs.release(job)
            fort.cancel_preparation(dwarf, job)
            continue
        fort.jobs.assign(job, dwarf)
        state.job = job
        state.idle_ticks = 0
        return job
    return None


def release_job(fort, dwarf) -> None:
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
    _follow_target(fort, dwarf, job)

    fetch = fort.fetch_target(dwarf, job)
    if fetch is not None:
        # Items are picked up, not reached through the floor.
        if at_or_beside(dwarf, fetch, vertical=False):
            if not fort.pick_up_for(dwarf, job):
                fort.abandon_job(dwarf, job)
                state.job = None
            return
        if not path_to(fort, dwarf, fetch, vertical=False) \
                or not step_along(fort, dwarf):
            fort.abandon_job(dwarf, job)
            state.job = None
        return

    reach = vertical_reach(job)
    if not at_or_beside(dwarf, job.cell, vertical=reach):
        if not path_to(fort, dwarf, job.cell, vertical=reach):
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
    """Go to the tavern when there is nothing to do, or wander if there is none."""
    state = dwarf.fort
    state.idle_ticks += 1
    if state.idle_ticks % 4 != 0:
        return
    if _to_the_tavern(fort, dwarf):
        return
    if fort.rng.chance(0.5):
        dx, dy = fort.rng.dir8()
        cell = (dwarf.x + dx, dwarf.y + dy, dwarf.z)
        if fort.local.walkable(*cell) and fort.creature_at(*cell) is None:
            dwarf.x, dwarf.y, dwarf.z = cell
    if state.idle_ticks > 600:
        dwarf.needs.add_thought("had nothing to do", 2)
        state.idle_ticks = 0


#: How far from the tavern's middle still counts as being in the tavern.
#: The whole room, not the three tiles the furniture stands on: twenty idle
#: dwarves converging on one 3x3 building shove each other off it for ever,
#: and every shove throws away a path and buys another A* search.
TAVERN_RADIUS = 4

#: Idle ticks between attempts to plan a route there. Walking is cheap and
#: happens every idle tick; planning is not, and a dwarf that cannot get
#: there must not pay for a search every time it thinks about a drink.
TAVERN_REPATH = 16


def _to_the_tavern(fort, dwarf) -> bool:
    """Walk towards the tavern. True if that is what this turn was spent on.

    A dwarf that has arrived stays in the room and lets the others come to
    it, which is what makes the tavern a place where everybody meets rather
    than a place everybody walks through.
    """
    tavern = fort.tavern()
    if tavern is None:
        return False
    state = dwarf.fort
    cx, cy, cz = tavern.center
    if dwarf.z == cz and max(abs(dwarf.x - cx), abs(dwarf.y - cy)) \
            <= TAVERN_RADIUS:
        state.path = []
        # Standing about in a tavern is the point of a tavern. Drift a little
        # so the room mixes and everybody does not talk to the same neighbour.
        if fort.rng.chance(0.3):
            dx, dy = fort.rng.dir8()
            cell = (dwarf.x + dx, dwarf.y + dy, dwarf.z)
            if max(abs(cell[0] - cx), abs(cell[1] - cy)) <= TAVERN_RADIUS \
                    and fort.local.walkable(*cell) \
                    and fort.creature_at(*cell) is None:
                dwarf.x, dwarf.y, dwarf.z = cell
        return True
    if state.path and state.path_goal == (cx, cy, cz):
        if step_along(fort, dwarf):
            return True
        state.path = []
        return True
    if state.idle_ticks % TAVERN_REPATH != 0:
        return False
    if not path_to(fort, dwarf, (cx, cy, cz)):
        return False
    step_along(fort, dwarf)
    return True
