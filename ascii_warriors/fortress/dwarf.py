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

#: When a dwarf starts wanting somewhere quiet. Ranked below the bodily needs
#: on purpose -- nobody prays instead of drinking -- so this only ever wins a
#: turn when nothing else is pressing.
PRAYER_URGENT = 100800

#: Ticks of standing in a temple that count as having prayed.
PRAYER_TICKS = 300

#: How far a dwarf will walk for a job before giving up on it.
MAX_PATH_NODES = 6000

#: Failures a dwarf has to have already had this turn, and candidates that
#: have to be left on the board, before one flood fill is worth drawing to
#: answer the rest. A fill costs the size of the component and so does the
#: failure that asks for it, so it only pays where failures come in runs --
#: which is exactly the difference between the embark that spends twelve
#: million node expansions on a day and the one that spends seventeen
#: thousand. On an ordinary fortress, where a search fails twenty times a day
#: and never twice in a row, no fill is ever drawn.
FILL_PAYS_OFF = 2


class DwarfState:
    """Everything a dwarf has that only matters inside a fortress."""

    __slots__ = ("labors", "job", "path", "path_goal", "nickname", "bed",
                 "mood", "mood_ticks", "idle_ticks", "praying", "squad",
                 "carrying",
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
        #: Ticks spent standing in a temple so far. A dwarf who is interrupted
        #: halfway keeps what it has, or it would never finish in a busy fort.
        self.praying = 0
        self.squad = False
        #: Written whenever a dwarf picks something up for a job, and read by
        #: nothing. The item lives in the dwarf's inventory and `put_down`
        #: finds it from the job, so this was never load-bearing; it is a
        #: debugging aid and is now marked as one rather than left looking
        #: like state that a save ought to be keeping.
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
            # Read by the vampire's victim search and by the sleep loop: a
            # save used to wake the whole fortress, which quietly meant a
            # vampire could not feed until somebody went back to bed.
            "sleeping": self.sleeping,
            "idle_ticks": self.idle_ticks,
            "praying": self.praying,
            "blocked": self.blocked,
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
        s.sleeping = bool(d.get("sleeping", False))
        s.idle_ticks = int(d.get("idle_ticks", 0))
        s.praying = int(d.get("praying", 0))
        s.blocked = int(d.get("blocked", 0))
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


#: What everybody walks off the wagon wearing. Clothing has been in the item
#: table since it was written -- traded, stockpiled, sorted into a category of
#: its own and tailored at a workshop -- and no dwarf has ever put any on. It
#: did not matter until v3.18 made the air cold, at which point a fortress in
#: the mountains froze to death in its own dining hall.
EVERYDAY_CLOTHES: Tuple[Tuple[str, str], ...] = (
    ("tunic", "wool_cloth"), ("trousers", "wool_cloth"), ("shoes", "leather"),
)

#: And what the ones whose work is above ground add to it.
OUTDOOR_CLOTHES: Tuple[Tuple[str, str], ...] = (
    ("cloak", "wool_cloth"), ("hood", "wool_cloth"),
)

#: Whose work is above ground.
OUTDOOR_WORK = frozenset({"woodcutter", "farmer", "hunter", "soldier"})


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
    for item_id, material in EVERYDAY_CLOTHES:
        c.inventory.add(Item(item_id, material))
    if profession in OUTDOOR_WORK:
        for item_id, material in OUTDOOR_CLOTHES:
            c.inventory.add(Item(item_id, material))
    c.inventory.auto_equip()
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


def _urgency(dwarf) -> float:
    """How badly this dwarf needs to be somewhere other than here."""
    needs = getattr(dwarf, "needs", None)
    if needs is None:
        return 0.0
    return max(needs.thirst / float(THIRST_URGENT),
               needs.hunger / float(HUNGER_URGENT),
               needs.drowsy / float(SLEEP_URGENT))


def _may_stand(fort, creature, cell: Cell) -> bool:
    """Whether a creature shoved into a cell can be in it at all.

    The tile a dwarf is standing on is walkable by construction, so this is
    only ever about what a *particular* creature needs of it. A carp does not
    leave the water anywhere else in the game, and it does not leave it
    because a dwarf wanted past either.
    """
    if not creature.defn.has("AQUATIC"):
        return True
    from ..world import tiles as tile_data

    if tile_data.get(fort.local.tile(*cell)).has("WATER"):
        return True
    return fort.water.at(*cell) > 0


def _outranks(dwarf, other) -> bool:
    """Whether this dwarf gets to shoulder past that one.

    Somebody has to yield, and it has to be the same somebody every time.
    Letting either of a pair shove the other is what a symmetric rule buys
    you: two dwarves heading the same way down a one-tile corridor trade
    places for ever, each of them reporting a successful step, so nothing
    escalates, nobody re-plans and neither ever arrives.

    Measured on a year of fortress: at day ninety every dwarf was dead of
    thirst in the corridor outside a stockpile holding two thousand units of
    ale, each one calling `_go_drink` every step and each one being told it
    had moved. In isolation two dwarves six tiles from a goal settle into a
    three-turn cycle and stay in it.

    The order is need first -- the one dying of thirst gets past the one who
    is merely walking somewhere -- and id as the tiebreak, so it is total and
    a pair can never disagree about which of them is yielding.
    """
    if getattr(other, "fort", None) is None:
        return True
    mine, theirs = _urgency(dwarf), _urgency(other)
    if mine != theirs:
        return mine > theirs
    return dwarf.id < other.id


def _step_around(fort, dwarf, other, nxt: Cell) -> bool:
    """Somebody is in the way.

    Waiting politely is what deadlocks a fortress: seven dwarves queue for the
    same barrel of ale and none of them ever reaches it. So a dwarf waits one
    beat, then shoulders past whoever is in front of it, then gives up on the
    route entirely.

    *Whoever*, not *whichever dwarf*. This only ever pushed past other dwarves,
    and livestock does not queue, does not path and does not get out of the
    way: measured on a year of fortress, three cows standing in the corridor
    between the dwarves and the drink were a wall, and every dwarf died of
    thirst behind them with two thousand units of ale on the other side --
    each one asking for a drink every single step and being told it had moved.
    A hostile is not shouldered aside. That is what the axe is for.
    """
    state = dwarf.fort
    state.blocked += 1
    if state.blocked < 2:
        return True

    here = (dwarf.x, dwarf.y, dwarf.z)
    if (getattr(other, "faction", "") != "hostile"
            and _may_stand(fort, other, here)
            and _outranks(dwarf, other)):
        other.x, other.y, other.z = here
        theirs = getattr(other, "fort", None)
        if theirs is not None:
            theirs.path = []
            theirs.path_goal = None
            theirs.blocked = 0
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
    # Before the needs, not after: a dwarf that leaves the cell whenever it is
    # hungry is not being held, and it is back in the dormitory every night,
    # which is exactly where a vampire wants to be. `_serving_time` answers
    # the needs itself instead -- somebody brings them their dinner.
    if _serving_time(fort, dwarf, ticks):
        return
    if _handle_needs(fort, dwarf, ticks):
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


def _serving_time(fort, dwarf, ticks: int) -> bool:
    """A held dwarf does no work. True if that is what is happening.

    It still eats, drinks and sleeps -- `_keep` sees to that where it stands --
    but it takes no job and it does not wander, which is what being held
    amounts to. A sentence costs the fortress its legendary mason for a few
    days, and that cost is the whole point of having a law.

    Not working is not enough on its own. A vampire that stops hauling rocks
    but goes on sleeping in the dormitory is a vampire that goes on feeding,
    so a fortress that has marked a cell puts the dwarf *in* it: that is what
    turns holding somebody from a note in a book into something that happens
    to them. With no cell marked, this is only the old rule -- no work, no
    wandering -- and the fortress is told so once.
    """
    from . import justice

    if not fort.crimes and not fort.held:
        return False
    if not justice.is_jailed(fort, dwarf):
        return False
    release_job(fort, dwarf)
    dwarf.fort.idle_ticks = 0
    if fort.cell is None:
        fort.warn_once("cell", "You are holding somebody and have nowhere to "
                               "put them. Mark a cell.")
        return _handle_needs(fort, dwarf, ticks) or True
    cells = [c for c in justice.cell_cells(fort) if fort.local.walkable(*c)]
    if not cells:
        fort.warn_once("cell", "The cell has no floor anybody can stand on.")
        return _handle_needs(fort, dwarf, ticks) or True
    if not justice.in_cell(fort, dwarf.x, dwarf.y, dwarf.z):
        goal = min(cells, key=lambda c: (abs(c[0] - dwarf.x)
                                         + abs(c[1] - dwarf.y)
                                         + abs(c[2] - dwarf.z) * 4))
        if path_to(fort, dwarf, goal, adjacent=False):
            step_along(fort, dwarf)
            return True
        # Nowhere to walk to. Being unable to reach the cell is not a licence
        # to go back to the dormitory, so it stays where it is.
        fort.warn_once("cell", "Nobody can reach the cell from where they are.")
    _keep(fort, dwarf, ticks)
    return True


def _keep(fort, dwarf, ticks: int) -> None:
    """Feed, water and bed a dwarf that is not allowed to fetch its own.

    A cell that starves its occupant is not a punishment, it is an execution
    with extra steps, and the fortress has a word for that already. Somebody
    brings them what they need, out of the same stores everybody else eats
    from -- so holding a dwarf costs the fortress food as well as a pair of
    hands.
    """
    needs = dwarf.needs
    state = dwarf.fort
    if needs.thirst >= THIRST_URGENT:
        item = fort.find_consumable(dwarf, drink=True)
        if item is not None:
            fort.consume(dwarf, item, drink=True)
    if needs.hunger >= HUNGER_URGENT:
        item = fort.find_consumable(dwarf, drink=False)
        if item is not None:
            fort.consume(dwarf, item, drink=False)
    if needs.drowsy >= SLEEP_URGENT:
        state.sleeping = True
        needs.sleep(ticks * 4)
        dwarf.body.rest_heal(ticks * 2, dwarf.attributes.factor("recuperation"))
        if needs.drowsy <= 0:
            state.sleeping = False
            needs.add_thought("slept on the floor", 3)


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
        combat.timed_strike(dwarf, foe, rng=fort.rng, log=fort.log, ground=fort)
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
            # Stay in it. Returning False here meant "I did not use my turn",
            # so a civilian that had just run to safety immediately claimed a
            # job and walked back out of the burrow -- which is the one thing
            # a burrow exists to stop. Needs are handled before this, so
            # holding position cannot starve anybody.
            release_job(fort, dwarf)
            return True
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
        (needs.prayer / float(PRAYER_URGENT), _go_pray),
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


def _go_pray(fort, dwarf, ticks: int) -> bool:
    """Walk to a temple and be quiet in it for a while.

    Fails silently when the fortress has no temple, and the dwarf goes on
    wanting one -- which is the whole mechanism. There is no warning for it
    because a fortress with no altar is a choice, not an emergency, and it
    tells you in the only way that matters: everybody is a little unhappier.
    """
    from . import rooms as room_mod
    from ..world import religion as religion_mod

    found = room_mod.temples(fort)
    if not found:
        return False
    temple = found[0]
    here = (dwarf.x, dwarf.y, dwarf.z)
    if here in temple.cells:
        state = dwarf.fort
        state.praying = state.praying + ticks
        if state.praying < PRAYER_TICKS:
            return True
        state.praying = 0
        dwarf.needs.prayer = 0
        god = religion_mod.deity_of(fort.world, dwarf)
        dwarf.needs.add_thought(
            "prayed to %s" % god.name if god is not None
            else "sat a while in the temple",
            -(4 + temple.quality // 8))
        return True
    release_job(fort, dwarf)
    for cell in sorted(temple.cells,
                       key=lambda c: _heuristic(here, c))[:4]:
        if path_to(fort, dwarf, cell, adjacent=False):
            step_along(fort, dwarf)
            return True
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
    """Take the best available job, if the dwarf can reach it.

    A job whose cell nobody could reach is remembered as unreachable for a
    while rather than searched for again on the next step. `job.failed`
    already counts give-ups and `_prune` already drops a job at three, but the
    count lives on the job and the scanners post a fresh one the moment the
    old one goes: a cow in a sealed cavern is four `tend` jobs that come back
    for ever. Measured on the embark that showed it, every dwarf spent every
    step inside a full-budget A* that could not succeed -- forty-two searches
    out of forty-four failing, forty thousand cells expanded apiece, and a
    fortress step of twelve hundred milliseconds against the ordinary one and
    a half.

    The memory is `fort.unreachable`, which the designation scanner has
    consulted since it was written; this is the same rule applied to the jobs
    nobody designated. It is per cell rather than per dwarf, so a job one
    dwarf cannot reach is set aside for all of them -- the cheap assumption,
    and the retry is what makes it safe. Digging clears it outright, because
    digging is how a fortress reaches somewhere it could not.
    """
    from . import sim as sim_mod

    state = dwarf.fort
    # Skipped before the window is taken, not inside it. A player designates
    # the room before the stairway down to it is finished -- that is how a
    # fortress is dug -- and the board fills with work that cannot be reached
    # yet. Slicing first meant a dwarf looked at twelve jobs it already knew
    # were unreachable, found nothing, and stood still: measured on a played
    # embark, forty-two of forty-three board entries, all seven dwarves idle
    # every step, and the fortress starved to death in a fortnight with a
    # thousand trees marked for felling and a fortnight of ale in the barrel.
    board = [job for job in fort.jobs.for_dwarf(dwarf)
             if fort.ticks >= fort.unreachable.get(job.cell, 0)]
    # `within` is drawn the first time a search comes back with nothing, and
    # answers every candidate after it for nothing. Until then this costs
    # exactly what it always did: a fortress whose work is all reachable never
    # builds one. See `Fortress.reach_from`.
    here = (dwarf.x, dwarf.y, dwarf.z)
    within = None
    shortlist = board[:12]
    misses = 0
    for index, job in enumerate(shortlist):
        if not fort.prepare_job(dwarf, job):
            continue
        spots = work_positions(fort.local, job.cell,
                               vertical=vertical_reach(job))
        if fort.local.walkable(*job.cell):
            spots.append(job.cell)
        if not spots:
            # Nowhere to stand and work it. `path_to` answers this without
            # searching at all, so there is nothing here worth drawing a map
            # over -- and drawing one anyway is how a fortress that never
            # fails a search ends up paying for thirty-five thousand cells.
            _set_aside(fort, dwarf, job)
            continue
        if within is not None and not any(spot in within for spot in spots):
            _set_aside(fort, dwarf, job)
            continue
        if not path_to(fort, dwarf, job.cell, vertical=vertical_reach(job)):
            # That one cost the size of the component -- and so does a fill,
            # so drawing one only pays if there are questions left for it to
            # answer. With nothing behind it on the board it is pure cost, and
            # measured on an ordinary embark that was nineteen fills a day
            # preventing nothing at all.
            misses += 1
            if (within is None and misses >= FILL_PAYS_OFF
                    and len(shortlist) - index > FILL_PAYS_OFF):
                within = fort.reach_from(here)
            _set_aside(fort, dwarf, job)
            continue
        fort.jobs.assign(job, dwarf)
        state.job = job
        state.idle_ticks = 0
        return job
    return None


def _set_aside(fort, dwarf, job) -> None:
    """Remember a job as unreachable and take it off the board.

    Off the board, not just released: a job left posted is one
    `_scan_designations` will not replace and every dwarf will keep stepping
    over. The designation stays painted, `dig_out` clears the memory, and the
    work comes back the moment somebody opens the way to it.
    """
    from . import sim as sim_mod

    fort.unreachable[job.cell] = fort.ticks + sim_mod.RETRY_DELAY
    if job.kind in sim_mod.DESIGNATION_KINDS:
        fort.jobs.remove(job)
    else:
        fort.jobs.release(job)
    fort.cancel_preparation(dwarf, job)


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

#: Ticks to stop trying after the tavern turns out to be unreachable.
#:
#: TAVERN_REPATH alone bounds how often a dwarf *plans*; it does nothing about
#: how much one plan costs. A search that succeeds stops at the goal, but a
#: search for somewhere it cannot get to expands the entire reachable map
#: before giving up -- about 2,300 cells here -- and every idle dwarf pays it
#: every sixteen ticks for as long as the tavern is cut off. Measured on a
#: fortress whose tavern sat one z-level above the floor: 76 ms a step against
#: 1.5 ms for the same fortress with no tavern at all, with 36 of every 37
#: seconds inside a failing A*. A walled-off, flooded or caved-in tavern is an
#: ordinary thing to happen to a fortress and must not cost fifty times the
#: frame.
TAVERN_UNREACHABLE_BACKOFF = 1800


def tavern_spot(fort, tavern=None) -> Optional[Cell]:
    """Where in the tavern a dwarf can actually stand, or None if nowhere.

    Almost always the middle of the room, because a tavern is built on ground
    somebody checked was walkable. The rest of this exists for what happens
    afterwards: a cave-in fills the room, water floods it, somebody walls it
    off. The centre stops being walkable and the two halves of this function
    used to disagree about what that meant -- `path_to` would happily route to
    a cell *adjacent* to the blocked centre, including one a z-level away,
    while the arrival test insisted on standing at the centre's own z. So the
    dwarf arrived somewhere it did not believe it had arrived, threw the path
    away and searched again, for ever.

    That is the exact failure `work_positions` warns about, and it cost 76 ms
    a step against 1.5 for the same fortress with no tavern -- 36 of every 37
    seconds inside A*. Returning one cell that both halves use is the fix.
    """
    tavern = tavern or fort.tavern()
    if tavern is None:
        return None
    cx, cy, cz = tavern.center
    if fort.local.walkable(cx, cy, cz):
        return (cx, cy, cz)
    best = None
    for dy in range(-TAVERN_RADIUS, TAVERN_RADIUS + 1):
        for dx in range(-TAVERN_RADIUS, TAVERN_RADIUS + 1):
            cell = (cx + dx, cy + dy, cz)
            if not fort.local.walkable(*cell):
                continue
            d = max(abs(dx), abs(dy))
            if best is None or d < best[0]:
                best = (d, cell)
    return best[1] if best else None


def _to_the_tavern(fort, dwarf) -> bool:
    """Walk towards the tavern. True if that is what this turn was spent on.

    A dwarf that has arrived stays in the room and lets the others come to
    it, which is what makes the tavern a place where everybody meets rather
    than a place everybody walks through.
    """
    tavern = fort.tavern()
    if tavern is None:
        return False
    if fort.ticks < getattr(fort, "_tavern_blocked_until", 0):
        return False
    spot = tavern_spot(fort, tavern)
    if spot is None:
        fort._tavern_blocked_until = fort.ticks + TAVERN_UNREACHABLE_BACKOFF
        return False
    state = dwarf.fort
    cx, cy, cz = spot
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
        # Nobody else try either. One dwarf finding out the tavern is cut off
        # is enough information for the whole fortress, and it is the only
        # thing that keeps the cost of a walled-off tavern bounded.
        fort._tavern_blocked_until = fort.ticks + TAVERN_UNREACHABLE_BACKOFF
        return False
    step_along(fort, dwarf)
    return True
