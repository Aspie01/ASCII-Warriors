"""Running the fortress.

A fortress runs itself. This module is the loop that makes it do so: it turns
standing orders into jobs, gives every dwarf a turn, moves whatever is trying to
kill them, and handles the things that arrive with the seasons.

Nothing here asks the player for anything. The player paints designations and
queues orders; the fortress works out the rest, badly, and dies of it eventually.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from ..data import names as name_data
from ..data.calendar import TICKS_PER_DAY, TICKS_PER_HOUR
from ..engine import geometry
from ..game import combat
from ..game.entity import make_creature
from ..game.item import Item
from . import dwarf as dwarf_mod
from . import production
from .buildings import Building
from .designations import KINDS as DESIGNATION_KINDS
from .labors import LABORS

Cell = Tuple[int, int, int]

#: How much fortress time passes per simulation step.
STEP_TICKS = 10

#: Ticks between sweeps of the map looking for work.
SCAN_INTERVAL = 60

#: Caps, so a fortress buried in loose rock does not spend its life scanning.
#: You may designate ten thousand tiles; only so many are ever live jobs.
MAX_HAUL_JOBS = 24
MAX_DIG_JOBS = 60
MAX_NEW_JOBS = 40

#: How long an unreachable designation is left alone before we try it again.
RETRY_DELAY = TICKS_PER_HOUR * 4

#: How many separate items a single stockpile tile will hold.
STOCKPILE_CAPACITY = 6

#: Work put into a haul job once the goods are in hand.
HAUL_WORK = 20

#: Ticks a farm plot takes to grow a crop.
GROW_TICKS = TICKS_PER_DAY * 5

#: Steps under water before a creature drowns. About a minute of game time.
DROWN_STEPS = 6

#: How much new water counts as a flood worth shouting about. Digging a
#: tunnel that clips a riverbank lets a little in; that is not a flood.
FLOOD_WARN = 1200

#: Training outranks ordinary work. A squad ordered to train is a squad taken
#: off the labour force; set it to defend instead if you need the hands.
TRAIN_PRIORITY = 8

#: Which labor covers each production skill.
SKILL_LABOR: Dict[str, str] = {
    lab.skill: lab.id for lab in LABORS.values() if lab.skill
}

#: Fallback labor per workshop, for skills with no labor of their own.
WORKSHOP_LABOR: Dict[str, str] = {
    "carpenter": "carpentry", "mason": "masonry", "craftsdwarf": "crafting",
    "smith": "smithing", "still": "brewing", "kitchen": "cooking",
    "butcher": "butchery",
}

#: Odds per step of a dwarf being seized. About one mood every three months —
#: an artifact should be an event, not a Tuesday.
MOOD_ODDS = 120000

#: What a strange mood produces, by the workshop the moody dwarf seizes.
MOOD_OUTPUT: Dict[str, Tuple[str, ...]] = {
    "craftsdwarf": ("gem", "amulet", "ring", "crown"),
    "mason": ("statue", "coffer", "altar"),
    "carpenter": ("shield", "bow", "cabinet"),
    "smith": ("axe", "short_sword", "warhammer", "helm", "mail_shirt"),
}


# --------------------------------------------------------------------------- #
# The step
# --------------------------------------------------------------------------- #


def step(fort) -> None:
    """Advance the fortress by one simulation step."""
    if fort.lost:
        return
    ticks = STEP_TICKS
    fort.time.advance(ticks)
    fort.ticks += ticks
    fort.log.turn = fort.ticks // TICKS_PER_HOUR

    _weather(fort, ticks)
    if fort.ticks >= fort._next_scan:
        fort._next_scan = fort.ticks + SCAN_INTERVAL
        scan_jobs(fort)
        fort.wealth = appraise(fort)
    _flow(fort, ticks)
    _bodies(fort, ticks)
    _triage(fort)
    for dwarf in list(fort.dwarves()):
        dwarf_mod.take_turn(fort, dwarf, ticks)
    _hostiles(fort, ticks)
    _traps(fort)
    _watch(fort)
    _crops(fort, ticks)
    _moods(fort, ticks)
    _tantrums(fort)
    _calendar(fort)
    _check_loss(fort)


def run(fort, steps: int) -> None:
    """Run many steps at once, for fast-forwarding and for tests."""
    for _ in range(max(0, steps)):
        if fort.lost:
            return
        step(fort)


# --------------------------------------------------------------------------- #
# Upkeep
# --------------------------------------------------------------------------- #


def _weather(fort, ticks: int) -> None:
    """Move the sky along."""
    tile = fort.world.tile(fort.wx, fort.wy)
    change = fort.weather.tick(
        ticks, fort.rng, tile.biome, tile.temperature, fort.time.season)
    if change:
        fort.log.info(change)


def _flow(fort, ticks: int) -> None:
    """Move the water, and drown whatever is standing in it."""
    from ..world import fluids

    water = fort.water
    water.step(fort.local)

    for c in list(fort.creatures.values()):
        if c.body.dead:
            continue
        depth = water.at(c.x, c.y, c.z)
        if depth < fluids.SWIM_DEPTH:
            # Out of the deep, or never in it: whatever breath it was holding
            # it gets back.
            fort.drowning.pop(c.id, None)
            continue
        if c.defn.has("AQUATIC"):
            continue
        # A dwarf can swim, badly, for a while. Full water over its head is
        # another matter.
        skill = c.skills.level("swimming")
        if depth < fluids.MAX_DEPTH and skill > 0 and fort.rng.chance(
                min(0.9, 0.25 + skill * 0.06)):
            c.add_exp("swimming", 4)
            fort.drowning.pop(c.id, None)
            continue
        held = fort.drowning.get(c.id, 0) + 1
        fort.drowning[c.id] = held
        if held == 1:
            fort.warn_once("drowning", "%s is in the water!" % c.name)
        if held >= DROWN_STEPS:
            c.body.dead = True
            c.body.death_cause = "drowned"
            fort.drowning.pop(c.id, None)
            fort.kill_creature(c)

    # Measured against the water the map started with, not against last step:
    # a mark that follows the total can never notice a slow flood.
    if water.total() > fort._water_mark + FLOOD_WARN and not water.flooded:
        water.flooded = True
        fort.log.bad("The fortress is flooding!")


def _bodies(fort, ticks: int) -> None:
    """Needs, bleeding and healing, for everything on the map."""
    from ..game import needs as needs_mod

    for c in list(fort.creatures.values()):
        if c.body.dead:
            continue
        c.needs.tick(ticks, c, fort)
        c.body.tick(fort.rng, ticks, c.attributes.factor("toughness"),
                    c.attributes.factor("recuperation"))
        if getattr(c, "fort", None) is not None:
            if c.needs.thirst > needs_mod.THIRST_DEHYDRATED:
                fort.warn_once("thirst", "Your dwarves are dying of thirst!")
            if c.needs.hunger > needs_mod.HUNGER_STARVING:
                fort.warn_once("hunger", "Your dwarves are starving!")
        if c.body.dead:
            fort.kill_creature(c)


def _triage(fort) -> None:
    """Post treatment for anybody bleeding out, without waiting for the scan.

    The ordinary job scan runs once a minute of fortress time. A dwarf with a
    severed artery does not have a minute.
    """
    from . import hospital

    for patient in fort.dwarves():
        if not hospital.is_critical(patient):
            continue
        cell = (patient.x, patient.y, patient.z)
        if fort.jobs.has_job_at("treat", cell):
            continue
        if any(j.kind == "treat" and j.target == patient.id
               for j in fort.jobs.jobs.values()):
            continue
        _scan_hospital(fort, 4)
        return


def _hostiles(fort, ticks: int) -> None:
    """Enemies hunt the nearest dwarf and hit it."""
    targets = fort.dwarves()
    if not targets:
        return
    for foe in fort.hostiles():
        if foe.body.unconscious > 0 or foe.body.stunned > 0:
            continue
        prey = min(targets, key=lambda d: (
            geometry.chebyshev(foe.x, foe.y, d.x, d.y) + abs(foe.z - d.z) * 4))
        dist = geometry.chebyshev(foe.x, foe.y, prey.x, prey.y)
        if dist <= 1 and foe.z == prey.z:
            combat.melee_attack(foe, prey, rng=fort.rng, log=fort.log)
            if prey.body.dead:
                fort.kill_creature(prey)
            continue
        _hostile_step(fort, foe, (prey.x, prey.y, prey.z))


def _hostile_step(fort, foe, goal: Cell) -> None:
    """One step of an enemy's approach."""
    state = fort.hostile_state.setdefault(foe.id, {"path": [], "goal": None})
    pos = (foe.x, foe.y, foe.z)
    path = state["path"]
    if state["goal"] != goal or pos not in path:
        from ..engine.pathfind import astar

        route = astar(pos, goal, fort.path_neighbours,
                      dwarf_mod._heuristic, max_nodes=2500)
        if not route:
            dx, dy = geometry.normalize_dir(goal[0] - foe.x, goal[1] - foe.y)
            cell = (foe.x + dx, foe.y + dy, foe.z)
            if fort.local.walkable(*cell) and fort.creature_at(*cell) is None:
                foe.x, foe.y, foe.z = cell
            return
        state["path"], state["goal"] = route, goal
        path = route
    idx = path.index(pos)
    if idx + 1 >= len(path):
        return
    nxt = path[idx + 1]
    if not fort.local.walkable(*nxt) or fort.creature_at(*nxt) is not None:
        state["path"] = []
        return
    foe.x, foe.y, foe.z = nxt


def _traps(fort) -> None:
    """Anything hostile standing on a trap gets what a trap gives."""
    from ..game import combat
    from .buildings import TRAP_KINDS

    traps = [b for b in fort.buildings
             if b.built and b.kind in TRAP_KINDS]
    if not traps:
        return
    for foe in fort.hostiles():
        here = (foe.x, foe.y, foe.z)
        for trap in traps:
            if here not in trap.cells():
                continue
            combat.trap_strike(foe, trap.kind, trap.material_name,
                               rng=fort.rng, log=fort.log)
            if foe.body.dead:
                fort.kill_creature(foe)
            break


def _watch(fort) -> None:
    """Sound and lift the alarm on the player's behalf."""
    military = fort.military
    hostiles = fort.hostiles()
    if hostiles and not military.alarm:
        military.sound_alarm()
        fort.log.warn("The alarm is raised. Civilians, get inside.")
    elif not hostiles and military.alarm:
        military.all_clear()
        fort.log.good("All clear.")


def _crops(fort, ticks: int) -> None:
    """Farm plots grow."""
    for b in fort.buildings:
        if b.kind != "farm" or not b.built or not b.planted:
            continue
        b.growth += ticks
        if b.growth >= GROW_TICKS and fort.local.tile(*b.center) != "farm_planted":
            for cx, cy, cz in b.cells():
                fort.local.set_tile(cx, cy, cz, "farm_planted")


# --------------------------------------------------------------------------- #
# Finding work
# --------------------------------------------------------------------------- #


def scan_jobs(fort) -> int:
    """Sweep the fortress for work and post it. Returns how many jobs appeared."""
    _prune(fort)
    budget = MAX_NEW_JOBS
    for scanner in (_scan_hospital, _scan_levers, _scan_military,
                    _scan_designations,
                    _scan_buildings, _scan_farms, _scan_workshops,
                    _scan_stockpiles):
        if budget <= 0:
            break
        budget -= scanner(fort, budget)
    return MAX_NEW_JOBS - budget


def _prune(fort) -> None:
    """Drop jobs that no longer make sense."""
    for job in list(fort.jobs.jobs.values()):
        if job.failed >= 3:
            if job.kind in DESIGNATION_KINDS:
                fort.unreachable[job.cell] = fort.ticks + RETRY_DELAY
                fort.designations.release(job.cell)
                fort.warn_once(
                    "unreachable",
                    "Some designated tiles cannot be reached.")
            fort.release_job_items(job)
            fort.jobs.remove(job)
            continue
        if job.kind in DESIGNATION_KINDS:
            if fort.designations.get(*job.cell) != job.kind:
                fort.jobs.remove(job)
    for cell, when in list(fort.unreachable.items()):
        if fort.ticks >= when:
            del fort.unreachable[cell]
            fort.clear_warning("unreachable")


def _scan_hospital(fort, budget: int) -> int:
    """Post treatment jobs for anybody bleeding.

    This runs before everything else: a dwarf with an open artery has minutes,
    and a fortress that finishes hauling the rocks first is a fortress with a
    corpse in it.
    """
    from . import hospital

    hurt = hospital.patients(fort)
    if not hurt:
        return 0
    available = hospital.doctors(fort)
    if not available:
        fort.warn_once("doctor",
                       "Somebody is hurt and nobody can treat them. "
                       "Enable the medicine labor.")
        return 0
    fort.clear_warning("doctor")

    busy = {j.assigned for j in fort.jobs.jobs.values()
            if j.kind == "treat" and j.assigned is not None}
    posted = 0
    for patient in hurt:
        if posted >= budget:
            break
        care = hospital.needs_care(patient)
        if not care:
            continue
        part_id, treatment = care[0]
        cell = (patient.x, patient.y, patient.z)
        if any(j.kind == "treat" and j.target == patient.id
               for j in fort.jobs.jobs.values()):
            continue
        if not hospital.can_supply(fort, treatment):
            fort.warn_once("bandages", "The hospital has run out of bandages.")
            continue
        fort.clear_warning("bandages")
        # Send the closest doctor, rather than leaving it on the board for
        # whoever happens to look next. Bleeding is measured in minutes.
        doctor = _nearest_doctor(available, busy, patient)
        if doctor is None:
            continue
        item = hospital.supplies(fort, treatment)
        job = fort.jobs.make(
            "treat", cell[0], cell[1], cell[2], labor="medicine",
            skill=medical_skill(treatment), work=hospital.TREAT_WORK,
            target=patient.id, priority=10)
        job.carrying = item.id if item is not None else None
        if item is not None:
            fort.jobs.reserve_item(item.id, job)
        if doctor.fort.job is not None:
            fort.abandon_job(doctor, doctor.fort.job)
            doctor.fort.job = None
        fort.jobs.assign(job, doctor)
        busy.add(doctor.id)
        posted += 1
    return posted


def _nearest_doctor(available, busy, patient):
    """The closest free doctor who is not the patient."""
    best = None
    best_d = 1 << 30
    for doctor in available:
        if doctor.id in busy or doctor.id == patient.id:
            continue
        d = (geometry.chebyshev(doctor.x, doctor.y, patient.x, patient.y)
             + abs(doctor.z - patient.z) * 4)
        if d < best_d:
            best, best_d = doctor, d
    return best


def medical_skill(treatment: str) -> str:
    """The skill a treatment trains."""
    from ..game import medical

    return medical.TREATMENT_SKILL.get(treatment, "wound_dressing")


def _scan_military(fort, budget: int) -> int:
    """Kit soldiers out and send them to train.

    Equipment comes first and at the highest priority in the game: a squad
    standing around in civilian clothes when the goblins arrive is worse than
    no squad at all, because you were counting on it.
    """
    from . import military as military_mod

    military = fort.military
    if not military.squads:
        return 0
    enlisted = set(military.soldiers())
    for d in fort.dwarves():
        d.fort.squad = d.id in enlisted

    posted = 0
    for squad in military.squads:
        for dwarf_id in list(squad.members):
            if posted >= budget:
                return posted
            dwarf = fort.creatures.get(dwarf_id)
            if dwarf is None or dwarf.body.dead:
                military.discharge(dwarf_id)
                continue
            dwarf.fort.labors.enable("military")
            posted += _equip_one(fort, squad, dwarf)
        if squad.order == "train" and not military.alarm:
            posted += _train_squad(fort, squad, budget - posted)
    return posted


def _equip_one(fort, squad, dwarf) -> int:
    """Post one equipment job for a soldier that is short of its uniform."""
    from . import military as military_mod

    if fort.jobs.has_job_at("equip", (dwarf.x, dwarf.y, dwarf.z)):
        return 0
    if any(j.kind == "equip" and j.assigned == dwarf.id
           for j in fort.jobs.jobs.values()):
        return 0
    wanted = military_mod.wanted_items(squad, dwarf)
    if not wanted:
        return 0
    item = _find_kit(fort, wanted)
    if item is None:
        fort.warn_once("kit-" + squad.defn.id,
                       "%s has nothing to arm itself with." % squad.name)
        return 0
    fort.clear_warning("kit-" + squad.defn.id)
    # Whatever it was doing, arming itself comes first — but put down the
    # rocks properly rather than walking off with them.
    if dwarf.fort.job is not None:
        fort.abandon_job(dwarf, dwarf.fort.job)
        dwarf.fort.job = None
    cell = fort.item_cell(item)
    job = fort.jobs.make("equip", cell[0], cell[1], cell[2], labor="military",
                         work=20, target=item.id, priority=9)
    fort.jobs.assign(job, dwarf)
    fort.jobs.reserve_item(item.id, job)
    return 1


def _find_kit(fort, wanted: Sequence[str]):
    """The best unclaimed piece of kit from a wanted list."""
    for def_id in wanted:
        best = None
        best_value = -1
        for pile in fort.items_on_ground.values():
            for item in pile:
                if item.def_id != def_id or fort.jobs.is_reserved(item.id):
                    continue
                if item.value > best_value:
                    best, best_value = item, item.value
        if best is not None:
            return best
    return None


def _train_squad(fort, squad, budget: int) -> int:
    """Send a squad to the barracks to spar.

    One job per member, not one per squad: with a single job the same dwarf
    takes it every time and the rest of the militia never picks up a shield.
    """
    if budget <= 0 or not squad.members:
        return 0
    barracks = _barracks_for(fort, squad)
    if barracks is None:
        fort.warn_once("barracks",
                       "Your militia has no barracks to train in.")
        return 0
    fort.clear_warning("barracks")
    outstanding = sum(1 for j in fort.jobs.jobs.values()
                      if j.kind == "train" and j.target == barracks.id)
    want = min(budget, len(squad.members) - outstanding)
    cx, cy, cz = barracks.center
    posted = 0
    for _ in range(max(0, want)):
        fort.jobs.make("train", cx, cy, cz, labor="military", skill="fighter",
                       work=400, target=barracks.id, priority=TRAIN_PRIORITY)
        posted += 1
    return posted


def _barracks_for(fort, squad):
    """The barracks a squad trains at, claiming one if it has none."""
    if squad.barracks is not None:
        b = fort.building(squad.barracks)
        if b is not None and b.built:
            return b
        squad.barracks = None
    for b in fort.buildings:
        if b.kind == "barracks" and b.built:
            squad.barracks = b.id
            return b
    return None


def _scan_levers(fort, budget: int) -> int:
    """Send somebody to throw the levers the player has asked for."""
    posted = 0
    for lever in fort.levers():
        if posted >= budget:
            break
        if not lever.pending:
            continue
        if fort.jobs.has_job_at("pull", lever.center):
            continue
        cx, cy, cz = lever.center
        fort.jobs.make("pull", cx, cy, cz, labor="", skill="mechanics",
                       work=20, target=lever.id, priority=10)
        posted += 1
    return posted


def _scan_designations(fort, budget: int) -> int:
    """Turn painted designations into digging and chopping jobs."""
    live = sum(1 for j in fort.jobs.jobs.values()
               if j.kind in DESIGNATION_KINDS)
    budget = min(budget, MAX_DIG_JOBS - live)
    posted = 0
    stale: List[Cell] = []
    for cell, kind in list(fort.designations.cells.items()):
        if posted >= budget:
            break
        if cell in fort.designations.claimed or cell in fort.unreachable:
            continue
        if fort.jobs.has_job_at(kind, cell):
            continue
        if not fort.designations.valid(fort.local, cell[0], cell[1], cell[2],
                                       kind):
            stale.append(cell)
            continue
        defn = DESIGNATION_KINDS[kind]
        fort.jobs.make(kind, cell[0], cell[1], cell[2], labor=defn.labor,
                       skill=defn.skill, work=defn.work, priority=6)
        posted += 1
    for cell in stale:
        fort.designations.clear(cell)
    return posted


def _scan_buildings(fort, budget: int) -> int:
    """Post construction jobs, reserving the materials they will eat."""
    posted = 0
    for b in fort.buildings:
        if posted >= budget:
            break
        if b.built or fort.jobs.has_job_at("build", b.center):
            continue
        defn = b.defn
        if len(b.materials) < defn.material_count:
            found = _reserve_materials(fort, b)
            if not found:
                fort.warn_once(
                    "material-" + b.kind,
                    "A %s is waiting on building material."
                    % defn.name.lower())
                continue
            fort.clear_warning("material-" + b.kind)
        cx, cy, cz = b.center
        job = fort.jobs.make("build", cx, cy, cz, labor=defn.labor,
                             skill=defn.skill, work=defn.work, target=b.id,
                             priority=7)
        for item_id in b.materials:
            fort.jobs.reserved_items[item_id] = job.id
        posted += 1
    return posted


def _reserve_materials(fort, b: Building) -> bool:
    """Find enough unclaimed material for a building. False if short."""
    from .buildings import material_matches

    defn = b.defn
    need = defn.material_count - len(b.materials)
    if need <= 0:
        return True
    chosen: List[int] = []
    for cell, pile in fort.items_on_ground.items():
        for item in pile:
            if len(chosen) >= need:
                break
            if fort.jobs.is_reserved(item.id) or item.id in b.materials:
                continue
            if not material_matches(item, b.kind):
                continue
            chosen.append(item.id)
        if len(chosen) >= need:
            break
    if len(chosen) < need:
        return False
    b.materials.extend(chosen)
    return True


def _scan_farms(fort, budget: int) -> int:
    """Plant and harvest farm plots."""
    posted = 0
    for b in fort.buildings:
        if posted >= budget:
            break
        if b.kind != "farm" or not b.built:
            continue
        cx, cy, cz = b.center
        if b.planted:
            if b.growth < GROW_TICKS or fort.jobs.has_job_at("harvest", b.center):
                continue
            fort.jobs.make("harvest", cx, cy, cz, labor="farming",
                           skill="herbalism", work=80, target=b.id, priority=6)
        else:
            if fort.jobs.has_job_at("plant", b.center):
                continue
            if fort.stock_count("plump_helmet") <= 0:
                fort.warn_once("seeds", "There are no seeds left to plant.")
                continue
            fort.clear_warning("seeds")
            fort.jobs.make("plant", cx, cy, cz, labor="farming",
                           skill="herbalism", work=70, target=b.id, priority=4)
        posted += 1
    return posted


def _scan_workshops(fort, budget: int) -> int:
    """Post one job per workshop with something queued."""
    posted = 0
    for b in fort.buildings:
        if posted >= budget:
            break
        if not b.built or not b.is_workshop or not b.orders:
            continue
        if fort.jobs.has_job_at("craft", b.center):
            continue
        order = b.orders[0]
        if fort.ticks < int(order.get("blocked_until", 0)):
            continue
        recipe = production.RECIPES.get(order.get("recipe", ""))
        if recipe is None:
            b.orders.pop(0)
            continue
        labor = SKILL_LABOR.get(recipe.skill) or WORKSHOP_LABOR.get(b.kind, "")
        cx, cy, cz = b.center
        fort.jobs.make("craft", cx, cy, cz, labor=labor, skill=recipe.skill,
                       work=recipe.work, target=b.id, priority=5)
        posted += 1
    return posted


def _scan_stockpiles(fort, budget: int) -> int:
    """Post hauling jobs for loose goods a stockpile wants."""
    if not fort.stockpiles:
        return 0
    outstanding = fort.jobs.count("haul")
    if outstanding >= MAX_HAUL_JOBS:
        return 0
    room = _stockpile_room(fort)
    posted = 0
    for cell, pile in list(fort.items_on_ground.items()):
        if posted >= budget or outstanding + posted >= MAX_HAUL_JOBS:
            break
        here = fort.stockpile_at(*cell)
        for item in list(pile):
            if fort.jobs.is_reserved(item.id):
                continue
            if here is not None and here.accepts(item):
                continue
            dest = _destination_for(fort, item, room, cell)
            if dest is None:
                continue
            job = fort.jobs.make("haul", dest[0], dest[1], dest[2],
                                 labor="hauling", work=HAUL_WORK,
                                 target=item.id, priority=2)
            fort.jobs.reserve_item(item.id, job)
            room[dest] = room.get(dest, 0) + 1
            posted += 1
            break
    return posted


def _stockpile_room(fort) -> Dict[Cell, int]:
    """How full each stockpile tile already is."""
    room: Dict[Cell, int] = {}
    for pile in fort.stockpiles:
        for cell in pile.cells():
            room[cell] = len(fort.items_on_ground.get(cell, ()))
    return room


def _destination_for(
    fort, item, room: Dict[Cell, int], from_cell: Cell
) -> Optional[Cell]:
    """The nearest free stockpile tile that will take an item."""
    best: Optional[Cell] = None
    best_d = 1 << 30
    for pile in fort.stockpiles:
        if not pile.accepts(item):
            continue
        for cell in pile.cells():
            if room.get(cell, 0) >= STOCKPILE_CAPACITY:
                continue
            if not fort.local.walkable(*cell):
                continue
            d = (geometry.chebyshev(from_cell[0], from_cell[1], cell[0], cell[1])
                 + abs(from_cell[2] - cell[2]) * 4)
            if d < best_d:
                best, best_d = cell, d
    return best


# --------------------------------------------------------------------------- #
# The calendar
# --------------------------------------------------------------------------- #


def _calendar(fort) -> None:
    """Season changes, migrants, caravans and the enemies that follow them."""
    season = (fort.time.month - 1) // 3
    year = fort.time.year
    marker = year * 4 + season
    if marker == fort.season_index:
        return
    first = fort.season_index == 0
    fort.season_index = marker
    if first:
        return

    fort.log.system("It is now %s of %d." % (fort.time.season, year))
    fort.wealth = appraise(fort)
    _season_thoughts(fort)
    _appointments(fort)

    if fort.time.season == "Spring" or fort.time.season == "Autumn":
        _maybe_migrants(fort)
    if fort.time.season == "Autumn":
        _caravan(fort)
    if fort.time.season in ("Summer", "Winter"):
        _maybe_attack(fort)


def _season_thoughts(fort) -> None:
    """Dwarves notice how they are living."""
    from . import rooms

    beds = sum(1 for b in fort.buildings if b.kind == "bed" and b.built)
    dining = rooms.dining_quality(fort)
    dwarves = fort.dwarves()
    for d in dwarves:
        if beds < len(dwarves):
            d.needs.add_thought("has no bed of its own", 4)
        else:
            room = rooms.room_of(fort, d)
            if room is not None:
                d.needs.add_thought("has %s" % room.name, room.thought)
        if dining <= 0:
            d.needs.add_thought("ate without a table", 3)
        else:
            d.needs.add_thought("dined in %s dining room"
                                % rooms.quality_name(dining),
                                -min(8, dining // 4))
        if fort.stock_count("dwarven_ale", "wine", "beer") <= 0:
            d.needs.add_thought("had no drink to speak of", 8)


# --------------------------------------------------------------------------- #
# Nobles and tempers
# --------------------------------------------------------------------------- #


def _appointments(fort) -> None:
    """Fill the positions the fortress has grown into."""
    from .nobles import MANDATES, MANDATE_TICKS, POSITIONS, mandate_met

    dwarves = fort.dwarves()
    if not dwarves:
        return
    court = fort.court
    population = len(dwarves)
    held = {n.dwarf_id for n in court.nobles}

    for position in POSITIONS.values():
        if population < position.at_population:
            continue
        current = court.holder(position.id)
        if current is not None and any(d.id == current for d in dwarves):
            continue
        # Prefer somebody with the right labor and nothing else to do.
        candidates = [d for d in dwarves if d.id not in held]
        if position.labor:
            fit = [d for d in candidates if d.fort.labors.has(position.labor)]
            candidates = fit or candidates
        if not candidates:
            continue
        chosen = max(candidates, key=lambda d: d.skills.total_levels())
        court.appoint(position.id, chosen.id, fort.ticks)
        held.add(chosen.id)
        fort.log.good("%s is the new %s." % (chosen.name, position.title))

    mayor = court.noble("mayor")
    if mayor is None:
        return
    holder = fort.creatures.get(mayor.dwarf_id)
    if holder is None or holder.body.dead:
        return
    if mayor.mandate is None:
        # Only demand things the fortress has not already got. A mandate you
        # have already met is not a demand, it is a formality.
        wanted = [m for m in MANDATES
                  if not mandate_met(fort, {"target": m[0], "kind": m[1]})]
        if not wanted:
            return
        target, kind, text = fort.rng.choice(wanted)
        mayor.mandate = {"target": target, "kind": kind, "text": text,
                         "deadline": fort.ticks + MANDATE_TICKS}
        fort.log.warn("%s the mayor demands: %s" % (holder.name, text))
        return
    if mandate_met(fort, mayor.mandate):
        fort.log.good("The mayor's demand has been met.")
        holder.needs.add_thought("had a mandate obeyed", -8)
        mayor.mandate = None
    elif fort.ticks > int(mayor.mandate.get("deadline", 0)):
        fort.log.bad("%s is furious that the mandate was ignored."
                     % holder.name)
        holder.needs.add_thought("had a mandate ignored", 25)
        mayor.mandate = None


def _tantrums(fort) -> None:
    """A dwarf that has had enough stops being useful about it."""
    from .nobles import STRESS_BERSERK, STRESS_TANTRUM, STRESS_UNHAPPY
    from .nobles import TANTRUM_ODDS

    for dwarf in fort.dwarves():
        stress = dwarf.needs.stress
        if stress < STRESS_UNHAPPY:
            continue
        if not fort.rng.one_in(TANTRUM_ODDS):
            continue
        if stress >= STRESS_BERSERK:
            _go_berserk(fort, dwarf)
        elif stress >= STRESS_TANTRUM:
            _throw_tantrum(fort, dwarf)
        else:
            fort.log.warn("%s is unhappy." % dwarf.name)
            dwarf.needs.add_thought("brooded over its lot", 0)


def _throw_tantrum(fort, dwarf) -> None:
    """Break something, and upset everybody who sees it."""
    from . import dwarf as dwarf_mod

    dwarf_mod.release_job(fort, dwarf)
    breakable = [b for b in fort.buildings
                 if b.built and b.z == dwarf.z
                 and b.kind in ("table", "chair", "cabinet", "coffer", "door",
                                "statue", "bed")]
    if breakable:
        target = min(breakable, key=lambda b: geometry.chebyshev(
            dwarf.x, dwarf.y, b.x, b.y))
        fort.buildings.remove(target)
        for cx, cy, cz in target.cells():
            # dig_out, not set_tile: the door somebody just smashed may have
            # been the one holding the water back.
            fort.dig_out((cx, cy, cz), "floor")
        fort.log.bad("%s throws a tantrum and destroys a %s!"
                     % (dwarf.name, target.defn.name.lower()))
    else:
        fort.log.bad("%s throws a tantrum." % dwarf.name)
    dwarf.needs.stress = max(0, dwarf.needs.stress - 40)
    for other in fort.dwarves():
        if other is not dwarf:
            other.needs.add_thought("saw a tantrum", 4)


def _go_berserk(fort, dwarf) -> None:
    """The end of a long unhappy season."""
    from ..game import combat
    from . import dwarf as dwarf_mod

    dwarf_mod.release_job(fort, dwarf)
    fort.military.discharge(dwarf.id)
    fort.court.vacate(dwarf.id)
    dwarf.faction = "hostile"
    dwarf.fort = None
    fort.log.bad("%s has gone berserk!" % dwarf.name)
    for other in fort.dwarves():
        other.needs.add_thought("saw a friend lose their mind", 10)


def _maybe_migrants(fort) -> None:
    """A wave of dwarves turns up if the fortress looks like it is working."""
    living = len(fort.dwarves())
    if living >= 40 or fort.lost:
        return
    if fort.migrant_waves >= 1 and fort.wealth < 400 * fort.migrant_waves:
        fort.log.info("No migrants this season. Word of your fortress is thin.")
        return
    count = fort.rng.randint(2, min(8, max(3, 12 - living // 4)))
    arrivals = migrants(fort, count)
    if not arrivals:
        return
    fort.migrant_waves += 1
    fort.log.good("Some migrants have arrived, driven by rumours of %s."
                  % fort.name)
    for d in arrivals:
        fort.log.info("  %s, %s." % (d.name, dwarf_mod.display_title(d)))


def migrants(fort, count: int) -> List:
    """Bring *count* new dwarves in from the edge of the map."""
    from .labors import PROFESSION_LABORS

    professions = list(PROFESSION_LABORS.keys())
    side = fort.rng.choice(["north", "south", "east", "west"])
    entry = fort.local.edge_entry(fort.rng, side)
    out = []
    for i in range(count):
        profession = fort.rng.choice(professions)
        d = dwarf_mod.make_dwarf(fort.rng, profession)
        d.x, d.y, d.z = fort._free_spot(entry, i)
        d.wx, d.wy = fort.wx, fort.wy
        fort.add_creature(d)
        out.append(d)
    return out


def _caravan(fort) -> None:
    """The dwarven caravan arrives for the autumn trade."""
    if fort.caravan is not None:
        return
    depot = next((b for b in fort.buildings
                  if b.kind in ("table", "coffer") and b.built), None)
    goods = _caravan_goods(fort)
    fort.caravan = {
        "goods": [g.to_dict() for g in goods],
        "leaves": fort.ticks + TICKS_PER_DAY * 14,
        "coins": 800 + fort.rng.randint(0, 600),
        "traded": False,
    }
    fort.log.good("A dwarven caravan from the mountainhomes has arrived.")
    if depot is None:
        fort.log.info("Press t to trade. They will wait a fortnight.")
    else:
        fort.log.info("Press t to trade.")


def _caravan_goods(fort) -> List[Item]:
    """What the caravan has brought to sell."""
    rng = fort.rng
    stock = [
        Item("plump_helmet", "plant", count=rng.randint(20, 50)),
        Item("dwarven_ale", "alcohol", count=rng.randint(20, 60)),
        Item("meat", "meat", count=rng.randint(8, 20)),
        Item("log", "oak", count=rng.randint(6, 20)),
        Item("bandage", "pig_tail_cloth", count=rng.randint(4, 12)),
        Item("splint", "oak", count=rng.randint(2, 6)),
    ]
    for _ in range(rng.randint(2, 5)):
        stock.append(Item(
            rng.choice(["axe", "short_sword", "spear", "warhammer", "pick"]),
            rng.choice(["iron", "steel", "bronze"])))
    for _ in range(rng.randint(1, 4)):
        stock.append(Item(
            rng.choice(["mail_shirt", "helm", "greaves", "shield"]),
            rng.choice(["iron", "steel", "bronze"])))
    return stock


def _maybe_attack(fort) -> None:
    """Goblins come once you have something worth taking."""
    living = len(fort.dwarves())
    if living <= 0 or fort.wealth < 500:
        return
    if not fort.rng.chance(min(0.75, 0.2 + fort.wealth / 12000.0)):
        return
    strength = min(12, 2 + fort.wealth // 900 + fort.siege_count)
    ambush = strength <= 4
    fort.siege_count += 1
    attackers = spawn_attack(fort, strength)
    if not attackers:
        return
    if ambush:
        fort.log.bad("An ambush! Curse them!")
    else:
        fort.log.bad("A goblin siege has arrived at %s." % fort.name)
        fort.log.warn("They number %d. Get everyone inside." % len(attackers))


def spawn_attack(fort, strength: int) -> List:
    """Put a raiding party on the edge of the map."""
    side = fort.rng.choice(["north", "south", "east", "west"])
    entry = fort.local.edge_entry(fort.rng, side)
    out = []
    for i in range(strength):
        race = "goblin" if i or strength > 3 else fort.rng.choice(
            ["goblin", "kobold"])
        foe = make_creature(fort.rng, race, faction="hostile",
                            level=min(4, 1 + fort.siege_count // 2))
        foe.x, foe.y, foe.z = fort._free_spot(entry, i)
        foe.wx, foe.wy = fort.wx, fort.wy
        fort.add_creature(foe)
        out.append(foe)
    return out


# --------------------------------------------------------------------------- #
# Strange moods
# --------------------------------------------------------------------------- #


def _moods(fort, ticks: int) -> None:
    """A dwarf is seized, takes a workshop, and makes something impossible."""
    for d in fort.dwarves():
        state = d.fort
        if not state.mood:
            continue
        state.mood_ticks -= ticks
        if state.mood_ticks <= 0:
            _finish_mood(fort, d)
        return

    if not fort.rng.one_in(MOOD_ODDS):
        return
    candidates = [d for d in fort.dwarves()
                  if not d.fort.mood and d.skills.total_levels() >= 4]
    if not candidates or len(candidates) < 3:
        return
    shops = [b for b in fort.buildings
             if b.built and b.kind in MOOD_OUTPUT]
    if not shops:
        return
    d = fort.rng.choice(candidates)
    shop = fort.rng.choice(shops)
    state = d.fort
    state.mood = shop.kind
    state.mood_ticks = TICKS_PER_DAY * 2
    state.workshop = shop.id
    fort.jobs.release_all(d.id)
    fort.designations.release_all(d.id)
    state.job = None
    fort.log.warn("%s has been possessed!" % d.name)
    fort.log.info("%s has claimed a %s." % (d.name, shop.defn.name.lower()))


def _finish_mood(fort, dwarf) -> None:
    """The mood breaks and an artifact exists."""
    state = dwarf.fort
    shop = fort.building(state.workshop) if state.workshop else None
    kinds = MOOD_OUTPUT.get(state.mood or "craftsdwarf", ("gem",))
    def_id = fort.rng.choice(kinds)
    material = fort.rng.weighted({
        "steel": 3.0, "silver": 2.5, "gold": 2.0, "granite": 2.0,
        "obsidian": 1.5, "platinum": 1.0, "adamantine": 0.4,
    })
    native, translated = name_data.artifact_name(fort.rng, "dwarf")
    art = Item(def_id, material, quality=5, maker=dwarf.name)
    art.flags["artifact"] = True
    art.flags["artifact_name"] = translated
    art.flags["artifact_native"] = native
    cell = shop.center if shop is not None else (dwarf.x, dwarf.y, dwarf.z)
    fort.drop_item(art, *cell)
    fort.artifacts.append({
        "name": translated, "native": native, "maker": dwarf.name,
        "item": art.name(), "year": fort.time.year,
    })
    fort.log.good("%s has created %s, a %s!" % (
        dwarf.name, translated, art.name()))
    dwarf.needs.add_thought("created a legendary artifact", -30)
    for other in fort.dwarves():
        other.needs.add_thought("admired a legendary artifact", -5)
    dwarf.skills.set_level(
        MOOD_SKILL.get(state.mood or "", "crafting"),
        max(15, dwarf.skills.level(MOOD_SKILL.get(state.mood or "", "crafting"))))
    state.mood = ""
    state.mood_ticks = 0
    state.workshop = None


#: The skill a mood makes legendary, by workshop.
MOOD_SKILL: Dict[str, str] = {
    "craftsdwarf": "crafting", "mason": "masonry", "carpenter": "carpentry",
    "smith": "smithing",
}


# --------------------------------------------------------------------------- #
# Wealth and the end
# --------------------------------------------------------------------------- #


def appraise(fort) -> int:
    """Everything the fortress owns, in coins."""
    total = 0
    for pile in fort.items_on_ground.values():
        for item in pile:
            total += item.value
    for c in fort.creatures.values():
        if getattr(c, "fort", None) is None:
            continue
        for item in c.inventory.items:
            total += item.value
    for b in fort.buildings:
        if b.built:
            total += 20 + b.defn.work // 8
    return total


def _check_loss(fort) -> None:
    """Losing is fun."""
    if fort.lost:
        return
    if fort.dwarves():
        return
    fort.lost = True
    hostiles = fort.hostiles()
    if hostiles:
        fort.loss_reason = "overrun by %s" % hostiles[0].short_name() + "s"
    else:
        fort.loss_reason = "starved, thirsted and forgotten"
    fort.log.bad("%s has fallen." % fort.name)
    fort.log.bad("Losing is fun.")
    record_fall(fort)


def record_fall(fort, *, abandoned: bool = False) -> None:
    """Write the fortress into the world, map and all.

    Afterwards the place exists: an adventurer in this world can travel to it
    and walk through the corridors you dug.
    """
    from . import legacy

    if fort.recorded:
        return
    fort.recorded = True
    legacy.record(fort, abandoned=abandoned)
