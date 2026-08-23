"""Running the fortress.

A fortress runs itself. This module is the loop that makes it do so: it turns
standing orders into jobs, gives every dwarf a turn, moves whatever is trying to
kill them, and handles the things that arrive with the seasons.

Nothing here asks the player for anything. The player paints designations and
queues orders; the fortress works out the rest, badly, and dies of it eventually.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from ..data import creatures as creature_data
from ..data import names as name_data
from ..data.calendar import TICKS_PER_DAY, TICKS_PER_HOUR
from ..engine import geometry
from ..game import combat
from ..game.entity import make_creature
from ..game.item import Item
from ..world import tiles as tile_data
from . import animals
from . import art
from . import dwarf as dwarf_mod
from . import ghosts
from . import justice
from . import perform
from . import production
from . import social
from . import war
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

#: How deep water has to stand before it leaves mud behind it. One unit is a
#: damp patch; two is a flooded room, and a flooded room is how a fortress
#: makes farmland out of a chamber it dug through solid rock.
MUD_DEPTH = 2

#: Floors that soak: bare rock, the same set a mason can dress. A smoothed
#: floor does not take mud, which is the whole of the choice -- a fine dining
#: hall or a field, not both.
SOAKS: Tuple[str, ...] = tile_data.BARE_ROCK

#: How far the prey may drift before an invader plans its route again. A
#: siege is a walk across the map; the last few tiles of it are a fight, and
#: the fight is what the re-plan is for.
REPATH_SLACK = 4

#: How hard an invader looks for a way to the dwarves. Big, because it only
#: runs when the last route stopped applying -- see `_hostile_step`.
HOSTILE_SEARCH = 20000

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
    "butcher": "butchery", "smelter": "smelting", "wood_furnace": "smelting",
    "magma_smelter": "smelting", "magma_forge": "smithing",
}

#: Odds per step of a dwarf being seized. About one mood every three months —
#: an artifact should be an event, not a Tuesday.
MOOD_ODDS = 120000

#: A megabeast will not cross a continent for a hole in the ground with eight
#: dwarves and a barrel of ale in it.
BEAST_WEALTH = 4000

#: Odds per season once you are worth the walk, before wealth is counted.
BEAST_ODDS = 0.06

#: How many demons come up when the spire is first opened, and how many follow
#: every season afterwards. There is no upper bound on how long that goes on.
DEMON_FIRST_WAVE = 6
DEMON_WAVE = 3

#: What a strange mood produces, by the workshop the moody dwarf seizes.
MOOD_OUTPUT: Dict[str, Tuple[str, ...]] = {
    # What each workshop can make, so a mood produces something the fortress
    # could have made the slow way. The craftsdwarf's line used to promise an
    # amulet, a ring or a crown from a workshop with no recipe for any of the
    # three -- and two of the five pieces of jewellery in the item table could
    # not be produced by anything at all. The jeweller does that trade now.
    "craftsdwarf": ("gem", "mechanism", "drum", "flute"),
    "jeweler": ("crown", "amulet", "ring", "bracelet", "earring"),
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
    _burn(fort, ticks)
    _chill(fort, ticks)
    _fray(fort)
    _gravity(fort)
    _nerves(fort, ticks)
    _bodies(fort, ticks)
    _triage(fort)
    for dwarf in list(fort.dwarves()):
        dwarf_mod.take_turn(fort, dwarf, ticks)
    animals.step(fort, STEP_TICKS)
    _mingle(fort, ticks)
    perform.tick(fort, ticks)
    _night(fort, ticks)
    ghosts.haunt(fort, ticks)
    _thieves(fort)
    justice.tick(fort)
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
    from ..game import swimming as swimming_mod

    water = fort.water
    water.step(fort.local)
    _irrigate(fort)
    _magma(fort, ticks)

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
        # another matter. The odds are `swimming.stroke_chance`, which is also
        # what adventure mode asks -- the two modes used to disagree about
        # what water was, and one of them had never heard of drowning at all.
        if swimming_mod.stays_up(c, depth, fort.rng):
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


def _irrigate(fort) -> None:
    """Standing water leaves mud on bare rock, and mud will grow a crop.

    This is the way out of the trap the soil rule sets: dig below the soil
    layers and there is nowhere to farm, unless you cut a channel from the
    river, flood the chamber, and shut the gate again. Only the cells the
    water actually moved through are considered, so a still map costs
    nothing and a river does not silt up the whole level at once.
    """
    lm = fort.local
    water = fort.water
    for cell in water.moving():
        if water.at(*cell) < MUD_DEPTH or lm.tile(*cell) not in SOAKS:
            continue
        fort.dig_out(cell, "mud")
        fort.warn_once(
            "mud", "The water has left mud on the rock. Mud will take a crop.")


def _magma(fort, ticks: int) -> None:
    """Move the magma, burn what it reaches, and cast what meets water."""
    from ..world import fluids

    magma = fort.magma
    before = magma.total()
    magma.step(fort.local)

    # Burning comes before casting: a dwarf standing in magma dies of the
    # magma, not of the wall somebody made out of it a moment later.
    for c in list(fort.creatures.values()):
        if c.body.dead or magma.at(c.x, c.y, c.z) < fluids.BURN_DEPTH:
            continue
        if c.defn.has("FIREIMMUNE"):
            continue
        c.body.dead = True
        c.body.death_cause = "burned to death"
        fort.kill_creature(c)

    cast = fluids.quench(magma, fort.water, fort.local)
    if cast:
        fort._water_cache = None
        fort.warn_once("obsidian",
                       "Water meets magma. It is turning to obsidian.")
        for cell in cast:
            for c in list(fort.creatures.values()):
                if c.body.dead or (c.x, c.y, c.z) != cell:
                    continue
                c.body.dead = True
                c.body.death_cause = "encased in obsidian"
                fort.kill_creature(c)

    if magma.total() > fort._magma_mark and not magma.flooded:
        magma.flooded = True
        fort.log.bad("Magma is loose in the fortress!")

    if magma.total() != before or cast:
        _burn_items(fort)


def _burn_items(fort) -> None:
    """Anything lying in magma is gone, except the one thing that is not."""
    magma = fort.magma
    for cell in magma.moving():
        if magma.depth.get(cell, 0) <= 0 or cell not in fort.items_on_ground:
            continue
        pile = fort.items_on_ground.get(cell) or []
        keep = [i for i in pile if i.material == "adamantine"]
        if len(keep) != len(pile):
            fort.warn_once("burned", "Goods are burning in the magma.")
        if keep:
            fort.items_on_ground[cell] = keep
        else:
            fort.items_on_ground.pop(cell, None)


def _bodies(fort, ticks: int) -> None:
    """Needs, bleeding and healing, for everything on the map."""
    from ..game import needs as needs_mod

    for c in list(fort.creatures.values()):
        if c.body.dead:
            continue
        if getattr(c, "animal", None) is None:
            # Animals do not queue at the ale barrel. Their hunger lives in
            # their own state, where grazing and fodder answer it; ticking
            # dwarf needs on a cow kills the whole herd of thirst in three
            # days with a river running past the pasture.
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
    """Enemies hunt the nearest dwarf and hit it, until they have had enough."""
    routed = fort.siege is not None and fort.siege.routed
    if routed:
        for foe in fort.hostiles():
            war.retreat_step(fort, foe)
        if fort.ticks - fort.siege.fleeing_since > war.FLEE_TICKS:
            for foe in fort.hostiles():
                fort.creatures.pop(foe.id, None)
        if not fort.hostiles():
            fort.siege = None
            fort.military.all_clear(fort.log)
            fort.log.good("The last of them is gone.")
        return

    from ..game import morale as morale_mod

    targets = fort.dwarves()
    if not targets:
        return
    for foe in fort.hostiles():
        if foe.body.unconscious > 0 or foe.body.stunned > 0:
            continue
        # An individual can have had enough before the army has. `war` routs
        # a whole siege on its losses and gives the people in it no say; this
        # asks one of them, and it leaves the way a routed army leaves rather
        # than by a second set of rules. Nothing bounds how long it spends
        # retreating, and nothing needs to: an invader boxed in stops moving
        # and stops fighting, and once the shock wears off it is back in the
        # siege.
        if morale_mod.broke(foe, fort):
            if war.retreat_step(fort, foe):
                fort.creatures.pop(foe.id, None)
            continue
        prey = min(targets, key=lambda d: (
            geometry.chebyshev(foe.x, foe.y, d.x, d.y) + abs(foe.z - d.z) * 4))
        dist = geometry.chebyshev(foe.x, foe.y, prey.x, prey.y)
        if dist <= 1 and foe.z == prey.z:
            combat.timed_strike(foe, prey, rng=fort.rng, log=fort.log, ground=fort)
            if prey.body.dead:
                fort.kill_creature(prey)
            continue
        _hostile_step(fort, foe, (prey.x, prey.y, prey.z))

    # A siege is over when there is nobody left on the map who came with it,
    # however they went. The routed branch above says so for an army that
    # broke as an army; an army small enough that its members lose their
    # nerve one at a time never routs, and used to leave the alarm ringing
    # over an empty map for the rest of the fortress's life.
    if fort.siege is not None and not fort.hostiles():
        war.record(fort, won=True)
        fort.siege = None
        fort.military.all_clear(fort.log)
        fort.log.good("The last of them is gone.")


def _flier_step(fort, foe, goal: Cell) -> bool:
    """One step of a flying enemy's approach: straight at it, over whatever.

    Deliberately not A*. Wings mean the obstacle course is not a problem that
    needs solving, and a greedy step says that in one line and costs nothing.
    Pathing a flier properly was tried and measured: the flying graph has
    seven times the edges of the walking one, six rocs on a map took the
    fortress step from 1.5 ms to 100 ms, and the routes it found were *worse*
    -- the roc ended up further from the dwarves than a goblin walking.

    Returns False if it could not improve its position, so the caller can fall
    back to the walking planner and a flier boxed into a corner still moves.
    """
    pos = (foe.x, foe.y, foe.z)
    best: Optional[Cell] = None
    best_d = _flier_distance(pos, goal)
    for cell, _cost in fort.flier_neighbours(pos):
        if fort.creature_at(*cell) is not None:
            continue
        d = _flier_distance(cell, goal)
        if d < best_d:
            best, best_d = cell, d
    if best is None:
        return False
    foe.x, foe.y, foe.z = best
    return True


def _flier_distance(a: Cell, b: Cell) -> float:
    """How far a flier still has to go. Levels cost a little more than steps."""
    return (geometry.chebyshev(a[0], a[1], b[0], b[1])
            + abs(a[2] - b[2]) * 1.5)


def _hostile_step(fort, foe, goal: Cell) -> None:
    """One step of an enemy's approach.

    The route is re-planned when it stops applying, not every time the prey
    takes a step. That distinction is the whole of it: an invader walks in
    from the edge of the map aiming at a dwarf that moves every tick, and
    re-running A* once per tick per invader is what forced the search cap
    down to 2500 nodes -- which is not enough to cross an eighty by sixty map
    with a hill in the way. Measured: a goblin dropped at the north-east
    corner never moved at all for a hundred and twenty steps while the
    dwarves stood twenty-five tiles away, because every single search ran out
    of budget and the greedy fallback walked it into the hillside.
    """
    from ..game import flight

    flies = flight.can_fly(foe)
    # A flier that has run out of greedy moves plans on the *flying* graph.
    # It cannot plan on the walking one: it is standing in mid-air over a
    # hillside, which has no walking neighbours at all, so the walking
    # planner returns nothing and the greedy fallback finds nothing walkable
    # to step onto. Measured as a roc that flew two thirds of the way to the
    # dwarves and then hovered in the same cell for eighty steps. Pathing the
    # flying graph every step is what was rejected as too expensive; pathing
    # it on the rare step where greed fails, and keeping the route, is not.
    graph = fort.flier_neighbours if flies else fort.path_neighbours

    state = fort.hostile_state.setdefault(foe.id, {"path": [], "goal": None})
    pos = (foe.x, foe.y, foe.z)
    path = state["path"]
    idx = path.index(pos) if pos in path else -1
    aim = state["goal"]
    stale = (
        idx < 0 or idx + 1 >= len(path) or aim is None or aim[2] != goal[2]
        or geometry.chebyshev(aim[0], aim[1], goal[0], goal[1]) > REPATH_SLACK
    )
    # Greed gets its turn only when there is no plan to follow. A flier's plan
    # exists precisely because greed ran out of moves, so it is always a route
    # around something -- and its first step is usually *away* from the goal,
    # which is exactly the step greed undoes. Letting greed run first meant the
    # two took turns: the plan stepped the roc out of the pocket, greed dragged
    # it straight back in, and the plan was thrown away and re-planned every
    # other step. Measured on the seed that showed it worst, a roc that flew
    # sixty-four tiles' worth of map spent all hundred and twenty steps of a
    # siege moving between the same two cells and never came closer than
    # fifty-seven.
    if flies and stale and _flier_step(fort, foe, goal):
        return
    if stale:
        from ..engine.pathfind import astar

        route = astar(pos, goal, graph, dwarf_mod._heuristic,
                      max_nodes=HOSTILE_SEARCH)
        if not route:
            _shove_towards(fort, foe, goal, graph)
            return
        state["path"], state["goal"] = route, goal
        path = route
        idx = path.index(pos)
    nxt = path[idx + 1]
    if not fort.local.walkable(*nxt) and not flies:
        state["path"] = []
        return
    if fort.creature_at(*nxt) is not None:
        # Somebody it came with is standing on the next tile. Go round it
        # rather than stop: five invaders following one route in single file
        # spend the siege blocking each other, and the fortress watches an
        # army cover seventeen tiles in two hundred and fifty steps.
        state["path"] = []
        _shove_towards(fort, foe, goal, graph)
        return
    foe.x, foe.y, foe.z = nxt


def _shove_towards(fort, foe, goal: Cell, graph) -> bool:
    """One greedy step towards the goal when the plan is unavailable.

    On whichever graph the creature travels, so a flier is not asked to find
    a floor and a walker is not offered thin air. Returns whether it moved.
    """
    here = (foe.x, foe.y, foe.z)
    near = _flier_distance(here, goal)
    best = None
    for cell, _cost in graph(here):
        if fort.creature_at(*cell) is not None:
            continue
        far = _flier_distance(cell, goal)
        if far < near and (best is None or (far, cell) < best):
            best = (far, cell)
    if best is None:
        return False
    foe.x, foe.y, foe.z = best[1]
    return True


#: Odds per checked cell that magma sets a flammable neighbour alight. Low:
#: magma is usually somewhere sealed, and a fortress that catches fire the
#: instant it strikes the magma sea is one nobody digs deep in twice.
MAGMA_IGNITES = 0.05

#: Ticks between looking at the magma at all, and how many of its cells get
#: looked at when we do.
#:
#: The first cut walked every magma cell every step and copied the layer into
#: a list to do it. A mature fortress has nearly ten thousand magma cells, and
#: the measured cost was 1.43 ms a step becoming 5.78 -- a four-fold slowdown
#: bought entirely for an event that fires a handful of times a season. Magma
#: does not move much between one step and the next; there is no reason to
#: ask it anything at that rate.
MAGMA_CHECK_TICKS = 200
MAGMA_SAMPLE = 24


def _magma_sparks(fort, blaze) -> None:
    """Magma sets light to what is next to it, occasionally and cheaply."""
    magma = getattr(fort, "magma", None)
    if magma is None or not magma.depth:
        return
    if fort.ticks < getattr(fort, "_next_spark", 0):
        return
    fort._next_spark = fort.ticks + MAGMA_CHECK_TICKS
    cells = list(magma.depth)
    for _ in range(min(MAGMA_SAMPLE, len(cells))):
        x, y, z = cells[fort.rng.randint(0, len(cells) - 1)]
        if magma.depth.get((x, y, z), 0) <= 0:
            continue
        if not fort.rng.chance(MAGMA_IGNITES):
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            blaze.ignite(fort.local, (x + dx, y + dy, z))


def _burn(fort, ticks: int) -> None:
    """Fires spread, burn down and go out, and magma starts them.

    Mirrors `_flow`: the fluid layer and the fire layer are the same shape of
    problem and are stepped the same way, so a fortress with nothing alight
    pays nothing for having the system.
    """
    from ..world import fire as fire_mod

    blaze = getattr(fort, "fire", None)
    if blaze is None:
        blaze = fort.fire = fire_mod.Fire()

    _magma_sparks(fort, blaze)

    if not blaze.anything_burning:
        return
    done = blaze.step(fort.local, fort.rng, items_at=fort.items_at,
                      on_burn_out=lambda item, cell: fort.take_item(item))
    if done:
        fort._water_cache = None
    for c in list(fort.creatures.values()):
        if blaze.burning(c.x, c.y, c.z) and c.alive:
            fire_mod.burn(c, fort.rng,
                          log=fort.log if c in fort.dwarves() else None)
            if c.body.dead:
                fort.kill_creature(c)


#: How often the cold gets to work on the dwarves. They are checked as a
#: group because the weather is the same for all of them; what differs is
#: where each one is standing and what it is wearing.
CHILL_TICKS = 100


def _chill(fort, ticks: int) -> None:
    """What the season does to the fortress and to the water around it.

    A fortress dug into the rock barely notices winter, which is the point of
    digging into the rock. The dwarves working the surface farm in Winter
    notice it a great deal.
    """
    from ..world import heat

    if fort.ticks < getattr(fort, "_next_chill", 0):
        return
    span = max(ticks, fort.ticks - getattr(fort, "_last_chill", fort.ticks))
    fort._next_chill = fort.ticks + CHILL_TICKS
    fort._last_chill = fort.ticks

    for c in list(fort.creatures.values()):
        if not c.alive:
            continue
        for msg in heat.tick(c, fort.temperature_at(c.x, c.y, c.z),
                             span, fort.rng,
                             log=fort.log if c in fort.dwarves() else None):
            if msg:
                fort.log.warn(msg)
        if c.body.dead:
            fort.kill_creature(c)

    froze, thawed = fort.frost.step(
        fort.local, fort.rng, lambda cell: fort.temperature_at(*cell),
        fort.ticks, water=fort.water)
    if froze or thawed:
        # Ice is ground and water is not, so anything that cached which cells
        # can be walked or pathed through has to look again.
        fort._water_cache = None
        if froze:
            fort.warn_once("frozen", "The water is freezing over.")
            fort.clear_warning("thawed")
        if thawed:
            fort.warn_once("thawed", "The ice is breaking up.")
            fort.clear_warning("frozen")


def _fray(fort) -> None:
    """Clothes wear through, and somebody has to make more.

    v3.18 dressed every dwarf and the clothes it gave them would have
    outlasted the mountain. The point of wearing out is the industry it
    creates: a fortress with no clothier ends up with cold dwarves in rags,
    which is the loop this is for and not an accident.
    """
    from ..game import wear as wear_mod

    for dwarf in list(fort.dwarves()):
        if not wear_mod.due(dwarf, fort.ticks):
            continue
        wear_mod.mark(dwarf, fort.ticks)
        for name in wear_mod.wearing(dwarf, fort.rng):
            fort.log.warn("%s's %s has fallen apart."
                          % (dwarf.fort.nickname or dwarf.name, name))
        _reclothe(fort, dwarf)


#: What a dwarf will go and put on if it can find one lying about. Exactly
#: what `make_dwarf` hands out and no more: wanting a cloak it never owned
#: means every dwarf is permanently under-dressed, and searches every item
#: pile in the fortress for one, every day, for ever. The same `equip` job a
#: soldier uses to fetch its uniform -- a second way to pick something up and
#: put it on is a second way for it to go wrong.
WARDROBE: Tuple[str, ...] = ("tunic", "trousers", "shoes")


def _reclothe(fort, dwarf) -> None:
    """Send a dwarf to fetch clothes it is missing, if any are made."""
    from ..game import wear as wear_mod

    worn = {i.def_id for i in dwarf.inventory.equipped.values() if i is not None}
    wanted = [w for w in WARDROBE if w not in worn]
    if not wanted:
        return
    # Nothing is worth dying of thirst over. A dwarf that needs a drink more
    # than it needs a shirt gets to have the drink.
    needs = dwarf.needs
    if (needs.thirst > dwarf_mod.THIRST_URGENT
            or needs.hunger > dwarf_mod.HUNGER_URGENT
            or needs.drowsy > dwarf_mod.SLEEP_URGENT):
        return
    if any(j.kind == "equip" and j.assigned == dwarf.id
           for j in fort.jobs.jobs.values()):
        return
    item = _find_kit(fort, wanted)
    if item is None:
        if not wear_mod.dressed(dwarf):
            fort.warn_once("rags",
                           "Somebody has nothing left to wear. "
                           "The fortress needs a clothier.")
        return
    fort.clear_warning("rags")
    cell = fort.item_cell(item)
    if cell is None:
        return
    job = fort.jobs.make("equip", cell[0], cell[1], cell[2], labor="hauling",
                         work=20, target=item.id, priority=6)
    fort.jobs.assign(job, dwarf)


def _nerves(fort, ticks: int) -> None:
    """Whatever they saw, it wears off."""
    from ..game import morale as morale_mod

    for c in fort.creatures.values():
        if c.shaken:
            morale_mod.steady(c, ticks)


def _gravity(fort) -> None:
    """Anybody standing on nothing goes down.

    A backstop rather than the mechanism: `settle_above` catches the floor
    being channelled away, and this catches every other way a fortress can
    remove the ground -- a bridge retracting, a wall coming down, a save
    loaded from a version that let it happen.
    """
    from ..world import gravity

    for c in gravity.unsupported_creatures(fort):
        if gravity.settle(fort, c, fort.rng, log=fort.log) and c.body.dead:
            fort.kill_creature(c)


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
    """Sound the alarm when something arrives, lift it when the last one goes.

    This used to re-derive the alert from the current threat on every step,
    which reads as the same thing and is not. The militia screen offers the
    player an ``a`` key and prints it in the hints, and both directions of it
    were wiped by the next step: sound the alarm with nothing on the map and
    this put it out, lift it during a siege and this put it back.

    That is not a cosmetic problem, because an alarm stops the fortress. A
    civilian under one drops its job and sits in the burrow, and with nothing
    hostile on the map at all -- so that fleeing on sight cannot be blamed --
    four seeds cut 9, 21, 85 and 85 designated cells over three hundred steps
    with the alarm down, and none at all with it up. The player could watch
    the fortress stop, could see the alarm that stopped it, had a key for that
    alarm, and could not spend the one to change the other.

    So the watch acts on the *change* now. The first thing on the map raises
    the alarm and the last one leaving lifts it; in between the state belongs
    to whoever set it last. A player who would rather keep the farmers working
    while the militia holds the gate is allowed to say so, and to be wrong
    about it. Anything newly arriving sounds the alarm itself, so a second
    wave landing on a fortress that stood down still gets noticed.
    """
    military = fort.military
    threat = bool(fort.hostiles())
    if threat == military.seen_threat:
        return
    military.seen_threat = threat
    if threat:
        military.sound_alarm(fort.log)
    else:
        military.all_clear(fort.log)


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
                    _scan_burials, _scan_designations, _scan_animals,
                    _scan_fishing, _scan_buildings, _scan_farms,
                    _scan_workshops, _scan_stockpiles):
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

    # Before anybody is hurt, not after. `BANDAGE_PER_DWARF` has said the
    # hospital "tries to keep bandages in stock" since it was written and
    # nothing read it, so the only warning a player ever got was the one below
    # -- which fires when somebody is already bleeding and the cupboard is
    # bare. Bandages take a craftsdwarf and a bolt of cloth; the point of
    # saying so early is that there is still time to make some.
    want = hospital.BANDAGE_PER_DWARF * max(1, len(fort.dwarves()))
    if fort.stock_count("bandage") < want:
        fort.warn_once("bandage_stock",
                       "The hospital is low on bandages. A craftsdwarf can "
                       "make more out of cloth.")
    else:
        fort.clear_warning("bandage_stock")

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
        item = hospital.supplies(fort, treatment, near=cell)
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
        # `defend` trains as well as `train` does. A squad ordered to defend
        # the fortress used to equip itself and then stand there for the rest
        # of the game -- no training, no station, no target -- so the most
        # defensive-sounding entry in the menu was the one that left the
        # militia at the skill it embarked with.
        if squad.order in ("train", "defend") and not military.alarm:
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


def _scan_animals(fort, budget: int) -> int:
    """Milking, shearing and the walk out to the pasture with a knife."""
    posted = 0
    for beast in animals.livestock(fort):
        if posted >= budget:
            break
        cell = (beast.x, beast.y, beast.z)
        if beast.animal.slaughter:
            if fort.jobs.has_job_for("slaughter", beast.id):
                continue
            fort.jobs.make("slaughter", *cell, labor="butchery",
                           skill="butchery", work=60, target=beast.id,
                           priority=6)
            posted += 1
            continue
        if not animals.ready_to_produce(fort, beast):
            continue
        if fort.jobs.has_job_for("tend", beast.id):
            continue
        fort.jobs.make("tend", *cell, labor="farming", skill="herbalism",
                       work=40, target=beast.id, priority=4)
        posted += 1
    return posted


#: How much fish a fortress keeps on hand before it stops sending anybody
#: out to stand by the water. A larder, not a fishery.
FISH_STOCK = 30

#: How long one catch takes, and how many rods may be out at once. Fishing is
#: an afternoon; a fortress that put everybody on the bank would starve.
FISH_WORK = 300
MAX_ANGLERS = 2


def _scan_fishing(fort, budget: int) -> int:
    """Post work for the `fishing` labor.

    The labor has been in the list since there was a list, the hunter carries
    it, and `fish_food` is stocked, cooked and eaten -- and no dwarf had ever
    been given anything to do with any of it.
    """
    if budget <= 0 or fort.stock_count("fish_food") >= FISH_STOCK:
        return 0
    live = sum(1 for j in fort.jobs.jobs.values() if j.kind == "fish")
    if live >= MAX_ANGLERS:
        return 0
    spot = _fishing_spot(fort)
    if spot is None:
        return 0
    fort.jobs.make("fish", *spot, labor="fishing", skill="fishing",
                   work=FISH_WORK, priority=3)
    return 1


def _fishing_spot(fort):
    """Somewhere a dwarf can stand and reach open water."""
    lm = fort.local
    for cell in fort.water_sources():
        for dx, dy in geometry.DIRS8:
            stand = (cell[0] + dx, cell[1] + dy, cell[2])
            if not lm.walkable(*stand):
                continue
            if fort.jobs.has_job_at("fish", stand):
                continue
            return stand
    return None


def _scan_designations(fort, budget: int) -> int:
    """Turn painted designations into digging and chopping jobs.

    Round-robin over the painted cells rather than from the top every time.
    A dict walked from the beginning gives the first sixty entries the whole
    job budget for ever, and the first thing a player paints is the room they
    have not cut the stairway to yet -- so a fortress that designates a floor
    below an aquifer it then breaches never posts another job of any kind.
    Measured on a played embark: eight hundred and fifty-four designations,
    sixty of them recycled through the board every scan, seven dwarves stood
    idle beside a thousand trees marked for felling, and the fortress starved
    to death in a fortnight with a season of ale in the barrel.
    """
    live = sum(1 for j in fort.jobs.jobs.values()
               if j.kind in DESIGNATION_KINDS)
    budget = min(budget, MAX_DIG_JOBS - live)
    posted = 0
    stale: List[Cell] = []
    cells = list(fort.designations.cells.items())
    if not cells:
        return 0
    start = fort.designation_cursor % len(cells)
    looked = 0
    for cell, kind in cells[start:] + cells[:start]:
        looked += 1
        if posted >= budget:
            break
        # The expiry, not the presence. `fort.unreachable` maps a cell to the
        # tick it may be tried again, and reading it as a set meant a
        # designation nobody could reach *once* was never posted again --
        # until something happened to call `dig_out`, which is the one thing
        # a fortress that cannot dig will not do. A room designated before
        # the stairway down to it was cut deadlocked the whole board.
        if cell in fort.designations.claimed:
            continue
        if fort.ticks < fort.unreachable.get(cell, 0):
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
    fort.designation_cursor = (start + looked) % max(1, len(cells))
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
        # And it has to be this workshop's recipe. The build menu only ever
        # offers `recipes_for(kind)`, so a player cannot queue a mismatch --
        # but a save from another version, or anything queueing an order
        # without going through the menu, could, and a jeweller quietly
        # brewing ale is worse than an order that goes away.
        if recipe is None or recipe.workshop != b.kind:
            b.orders.pop(0)
            continue
        labor = SKILL_LABOR.get(recipe.skill) or WORKSHOP_LABOR.get(b.kind, "")
        if not _anybody_does(fort, labor):
            # A job nobody will take sits on the board for ever, looking like
            # the workshop is broken. Say what is actually wrong.
            fort.warn_once(
                "labor-" + labor,
                "Nobody has %s enabled, so %s waits. Press u to change that."
                % (LABORS[labor].name.lower(), recipe.name.lower()))
            continue
        cx, cy, cz = b.center
        fort.jobs.make("craft", cx, cy, cz, labor=labor, skill=recipe.skill,
                       work=recipe.work, target=b.id, priority=5)
        posted += 1
    return posted


def _anybody_does(fort, labor: str) -> bool:
    """True if some living dwarf will accept work needing this labor."""
    if not labor or labor not in LABORS:
        return True
    return any(d.fort.labors.has(labor) for d in fort.dwarves())


def _scan_burials(fort, budget: int) -> int:
    """Match a dwarf lying on the floor to an empty coffin.

    Ahead of ordinary hauling in priority, because a corpse in a stockpile is
    still a corpse nobody buried, and the refuse pile will happily accept one
    and leave it there until it rises.
    """
    from . import ghosts as ghost_mod

    if not fort.unburied:
        return 0
    empty = [b for b in fort.buildings
             if b.kind == "coffin" and b.built and b.buried is None
             and not fort.jobs.has_job_at("bury", b.center)]
    if not empty:
        fort.warn_once("coffins",
                       "There is nowhere to bury the dead. Build a coffin.")
        return 0
    posted = 0
    for who in list(fort.unburied):
        if posted >= budget or not empty:
            break
        body = ghost_mod.body_of(fort, who)
        if body is None or fort.jobs.is_reserved(body.id):
            continue
        coffin = empty.pop()
        job = fort.jobs.make("bury", *coffin.center, labor="hauling",
                             work=HAUL_WORK * 2, target=body.id, priority=3)
        fort.jobs.reserve_item(body.id, job)
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
    turned = fort.season_index // 4 != year and not first
    fort.season_index = marker
    if first:
        return

    fort.log.system("It is now %s of %d." % (fort.time.season, year))
    if turned:
        social.birthdays(fort)
    fort.wealth = appraise(fort)
    _season_thoughts(fort)
    _appointments(fort)

    _world_turns(fort)
    justice.season(fort)
    social.court(fort)
    social.season(fort)
    social.maybe_born(fort)
    _maybe_thief(fort)
    if fort.breached and fort.breach_cell and fort.rng.chance(0.5):
        spawn_demons(fort, fort.breach_cell, wave=2)

    if fort.time.season == "Spring" or fort.time.season == "Autumn":
        _maybe_migrants(fort)
    if fort.time.season == "Autumn":
        _caravan(fort)
    if fort.time.season in ("Summer", "Winter"):
        _maybe_attack(fort)
    _maybe_night_attack(fort)


def _world_turns(fort) -> None:
    """A season passes for everybody else as well.

    A fortress hears about it the way a fortress would: from whoever walked in
    off the road. One line a season, so the world is present without drowning
    out the fortress's own news.
    """
    from ..world import livingworld

    mark = len(fort.world.events)
    livingworld.advance(fort.world, fort.rng, fort.time.year)
    for ev in livingworld.news_since(fort.world, mark, 1):
        fort.log.info("Travellers bring word: %s" % ev.text)
    _maybe_beast(fort)


def _maybe_beast(fort) -> None:
    """Something out of the legends decides your fortress looks interesting.

    Goblins come for your wealth. A megabeast comes because it is a megabeast,
    and it arrives with a name, a history, and everything it has already
    killed written down in the legends screen.
    """
    from ..world import livingworld

    if fort.lost or fort.wealth < BEAST_WEALTH or not fort.dwarves():
        return
    if not fort.rng.chance(min(0.30, BEAST_ODDS + fort.wealth / 90000.0)):
        return
    if any(c.hf_id is not None and not c.body.dead
           for c in fort.creatures.values()):
        # One legend at a time. Two of the same beast is a bookkeeping error
        # standing in the wheat field.
        return
    beast = livingworld.wandering_beast(fort.world, fort.rng, fort.time.year)
    if beast is None:
        return
    foe = spawn_beast(fort, beast)
    if foe is None:
        return
    defn = creature_data.get(beast.creature_id)
    fort.log.bad("The %s %s has come to %s!" % (
        defn.name, beast.display_name, fort.name))
    dead = len(beast.kills) + beast.stats.get("renown", 0)
    if dead:
        fort.log.warn("It has killed %d that the world knows of. Get "
                      "everyone inside." % dead)
    else:
        fort.log.warn("Get everyone inside.")
    fort.military.sound_alarm(fort.log)


def spawn_beast(fort, beast):
    """Put one named megabeast on the edge of the map."""
    if not beast.creature_id:
        return None
    entry = fort.edge_arrival()
    foe = make_creature(fort.rng, beast.creature_id, faction="hostile", level=4)
    foe.name = beast.name
    if beast.titles:
        foe.title = beast.titles[-1]
    foe.hf_id = beast.id
    foe.x, foe.y, foe.z = fort._free_spot(entry, 0)
    foe.wx, foe.wy = fort.wx, fort.wy
    fort.add_creature(foe)
    return foe


def _season_thoughts(fort) -> None:
    """Dwarves notice how they are living."""
    from . import rooms

    from ..game import needs as needs_mod

    beds = sum(1 for b in fort.buildings if b.kind == "bed" and b.built)
    dining = rooms.dining_quality(fort)
    temple = rooms.temples(fort)
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
        if not temple:
            # Only once it has been wanted. A fortress in its first month is
            # not neglecting anybody.
            if d.needs.prayer > needs_mod.PRAYER_WANTED:
                d.needs.add_thought("had nowhere quiet to pray", 5)
        elif d.needs.prayer > needs_mod.PRAYER_NEGLECTED:
            d.needs.add_thought("has not prayed in a long time", 4)
        art.admire(fort, d)


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
        _blame_for_mandate(fort, mayor.mandate)
        mayor.mandate = None


def _blame_for_mandate(fort, mandate) -> None:
    """Somebody has to answer for an ignored demand.

    The manager, if there is one, because keeping the work orders straight is
    the job. Otherwise whoever was in charge of the wagon. Nobody blames the
    mayor, which is the traditional shape of the arrangement.
    """
    for position in ("manager", "expedition_leader"):
        noble = fort.court.noble(position)
        if noble is None:
            continue
        dwarf = fort.creatures.get(noble.dwarf_id)
        if dwarf is None or dwarf.body.dead:
            continue
        justice.report(fort, "neglect", dwarf,
                       str(mandate.get("target", "the demand")))
        return


#: How far apart two dwarves can be and still be talking.
MINGLE_RANGE = 1


def _mingle(fort, ticks: int) -> None:
    """Dwarves standing together get to know each other.

    No separate socialising simulation: a bond moves where a dwarf already
    is. Two miners sharing a shaft become colleagues over months; the tavern
    is quicker only because that is where everybody with nothing to do ends
    up at once, which is exactly what a tavern is for.
    """
    dwarves = fort.dwarves()
    if len(dwarves) < 2:
        return
    by_cell: Dict[Cell, List] = {}
    for d in dwarves:
        d.fort.lonely += ticks
        by_cell.setdefault((d.x, d.y, d.z), []).append(d)

    seen = set()
    for d in dwarves:
        for dx in range(-MINGLE_RANGE, MINGLE_RANGE + 1):
            for dy in range(-MINGLE_RANGE, MINGLE_RANGE + 1):
                for other in by_cell.get((d.x + dx, d.y + dy, d.z), ()):
                    if other is d:
                        continue
                    pair = (min(d.id, other.id), max(d.id, other.id))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    social.meet(fort, d, other)


#: Odds per night that a vampire in the fortress goes looking for a throat.
FEED_ODDS = 0.02

#: How far a vampire will walk for a meal. It is not fussy, but it is lazy,
#: and it is not going to cross the fortress with the lights on.
FEED_RANGE = 30


def _night(fort, ticks: int) -> None:
    """Whatever the fortress does after dark that it does not admit to.

    Three things share this step because they share a clock: the moon turns
    the cursed, the dark lets the vampire feed, and a necromancer on the map
    puts your own dead back on their feet.
    """
    from ..game import night

    for c in list(fort.creatures.values()):
        if c.body.dead:
            continue
        if night.cursed_with(c) == "werebeast":
            _turn_werebeast(fort, c, night)
        if night.is_necromancer(c) and c.faction == "hostile":
            night.necromancy_turn(fort, c)
    if fort.time.is_night() and fort.rng.chance(FEED_ODDS):
        _feed_vampires(fort, night)


def _turn_werebeast(fort, dwarf, night) -> None:
    """A cursed dwarf keeps its shape until the moon says otherwise."""
    if night.should_change(dwarf, fort.time):
        if night.transform(fort, dwarf):
            # It is not one of yours until morning. Drop the job, discharge it
            # and strip it of office -- but keep its DwarfState, because that
            # is where its labors and its bed live and it will want them back.
            dwarf_mod.release_job(fort, dwarf)
            fort.military.discharge(dwarf.id)
            fort.court.vacate(dwarf.id)
            fort.log.bad("Get everyone inside. Now.")
    elif dwarf.changed:
        night.revert(fort, dwarf)
        dwarf.faction = "fortress"


def _feed_vampires(fort, night) -> None:
    """Somebody wakes up cold, or does not wake up.

    The bite is quiet. What is loud is the body in the morning -- and whether
    anybody else was in the room. A dwarf that sleeps alone in a fine bedroom
    is a dwarf nobody can prove anything about, which is the price of giving
    everybody their own door.
    """
    for vampire in [c for c in fort.dwarves() if night.is_vampire(c)]:
        victim = _sleeping_near(fort, vampire)
        if victim is None:
            continue
        died = night.feed(fort, vampire, victim)
        witness = _witness(fort, victim, vampire)
        if died:
            fort.kill_creature(victim)
            justice.report(fort, "murder",
                           vampire if witness is not None else None,
                           victim.name)
            if witness is not None:
                fort.log.bad("%s saw %s standing over the body."
                             % (witness.name, vampire.name))
        elif witness is not None:
            justice.report(fort, "assault", vampire, victim.name)
            fort.log.warn("%s wakes to find %s bent over %s."
                          % (witness.name, vampire.name, victim.name))


def _sleeping_near(fort, vampire):
    """The nearest sleeping dwarf that is not the vampire itself."""
    from ..game import night

    best, best_d = None, None
    for d in fort.dwarves():
        if d is vampire or not d.fort.sleeping:
            continue
        if not night.can_feed_on(d):
            continue
        dist = (geometry.chebyshev(vampire.x, vampire.y, d.x, d.y)
                + abs(vampire.z - d.z) * 6)
        if dist > FEED_RANGE:
            continue
        if best_d is None or dist < best_d:
            best, best_d = d, dist
    return best


def _witness(fort, victim, vampire):
    """Anybody awake close enough to see who was standing over the bed."""
    for d in fort.dwarves():
        if d is victim or d is vampire or d.fort.sleeping:
            continue
        if d.z == victim.z and geometry.chebyshev(
                d.x, d.y, victim.x, victim.y) <= 4:
            return d
    return None


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


#: How often a dwarf at the end of its rope hits somebody instead of a table.
BRAWL_ODDS = 0.35


def _throw_tantrum(fort, dwarf) -> None:
    """Break something -- or somebody -- and upset everybody who sees it."""
    from . import dwarf as dwarf_mod

    dwarf_mod.release_job(fort, dwarf)
    if fort.rng.chance(BRAWL_ODDS) and _start_brawl(fort, dwarf):
        dwarf.needs.stress = max(0, dwarf.needs.stress - 40)
        return
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
        justice.report(fort, "vandalism", dwarf, target.defn.name.lower())
    else:
        fort.log.bad("%s throws a tantrum." % dwarf.name)
    dwarf.needs.stress = max(0, dwarf.needs.stress - 40)
    for other in fort.dwarves():
        if other is not dwarf:
            other.needs.add_thought("saw a tantrum", 4)


def _start_brawl(fort, dwarf) -> bool:
    """Take a swing at whoever is standing there. True if there was somebody.

    Barehanded, and only one blow: a fistfight in the dining hall is a crime
    and a bruise, not an execution. It can still go wrong -- a dwarf that
    punches badly enough to kill has committed the other kind of crime, and
    the sheriff's book says so.

    Barehanded said so and was not. `weapon=None` asks `melee_attack` for
    whatever the attacker is holding, so every word of the paragraph above
    was true except the first: a miner threw its tantrum with a pick. That
    went unnoticed for as long as it did because until v3.49 no dwarf was
    ever unhappy enough to throw one at all.
    """
    near = [d for d in fort.dwarves()
            if d is not dwarf and d.z == dwarf.z
            and geometry.chebyshev(dwarf.x, dwarf.y, d.x, d.y) <= 1]
    if not near:
        return False
    victim = fort.rng.choice(near)
    fort.log.bad("%s lashes out at %s!" % (dwarf.name, victim.name))
    combat.melee_attack(dwarf, victim, weapon=None, unarmed=True,
                        rng=fort.rng, log=fort.log)
    if victim.body.dead:
        fort.kill_creature(victim)
        justice.report(fort, "murder", dwarf, victim.name)
    else:
        justice.report(fort, "assault", dwarf, victim.name)
        victim.needs.add_thought("was attacked by a friend", 20)
        _hold_a_grudge(fort, victim, dwarf)
    for other in fort.dwarves():
        if other is not dwarf and other is not victim:
            other.needs.add_thought("saw a brawl", 6)
    return True


def _hold_a_grudge(fort, wronged, wrongdoer) -> None:
    """Being hit is worse from somebody you were getting on with.

    `vengefulness` and `hate_propensity` have been rolled for every dwarf
    since personalities existed and neither was ever read. A forgiving dwarf
    lets a punch go; a vengeful one does not, and v3.4's bond is the number
    that remembers it.
    """
    from ..game import personality as personality_mod

    weight = personality_mod.grudge(wronged.personality)
    if weight < 0.6:
        return
    bd = social.bond(fort, wronged, wrongdoer)
    if bd is not None:
        bd.value = max(-100, bd.value - int(round(25 * weight)))
    wronged.needs.add_thought("will not forget that", int(round(8 * weight)))


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
    _maybe_vampire(fort, arrivals)


#: Odds that a migrant wave is hiding one. It says nothing when it arrives,
#: and there is nothing on the units screen to give it away: what gives it
#: away is the corpse, and whether anybody was in the room.
VAMPIRE_ODDS = 0.10


def _maybe_vampire(fort, arrivals) -> None:
    """One of them is not what it says it is."""
    from ..game import night

    if not arrivals or fort.rng.chance(1.0 - VAMPIRE_ODDS):
        return
    if any(night.is_vampire(d) for d in fort.dwarves()):
        return
    night.afflict(fort.rng.choice(arrivals), "vampire")


def migrants(fort, count: int) -> List:
    """Bring *count* new dwarves in from the edge of the map."""
    from .labors import PROFESSION_LABORS

    professions = list(PROFESSION_LABORS.keys())
    entry = fort.edge_arrival()
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
    _caravan_news(fort)


def _caravan_news(fort) -> None:
    """The traders have walked a long way and seen things on the road."""
    from ..world import history as history_mod
    from ..world import livingworld

    told = [e for e in history_mod.recent_events(fort.world, 40)
            if e.kind in livingworld.TOLD_ABOUT
            and e.year >= fort.time.year - 1]
    for ev in told[-3:]:
        fort.log.info("The traders say: %s" % ev.text)


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
        # An embark with no tin in the rock buys its bronze, and one with no
        # trees buys the fuel to smelt with.
        Item("bar", rng.choice(["copper", "tin", "iron"]),
             count=rng.randint(2, 8)),
        Item("coal", "coal", count=rng.randint(4, 14)),
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
    """Somebody comes once you have something worth taking.

    Not "some goblins": a particular civilization, with a name, that is at war
    with the people who sent you and can only send what it actually has.
    """
    if not fort.dwarves() or fort.wealth < war.NOTICE_WEALTH:
        return
    if fort.hostiles():
        return
    if not fort.rng.chance(min(0.75, 0.2 + fort.wealth / 12000.0)):
        return
    plan = war.plan(fort)
    if plan is None:
        return
    war.launch(fort, plan)


#: Odds per season that something comes out of the dark. Half what a siege
#: is worth, because one werebeast in a dining hall is quite enough.
NIGHT_ODDS = 0.10

#: A fortress this poor is not worth the walk, for anybody.
NIGHT_WEALTH = 800


def _maybe_night_attack(fort) -> None:
    """A werebeast at the full moon, or a necromancer and what follows it.

    Not a siege: one creature, arriving alone, and the damage it does is the
    damage it leaves behind. A werebeast that bites somebody and is driven off
    has still cost you a dwarf, you just do not know which one yet.
    """
    from ..game import night

    if fort.lost or not fort.dwarves() or fort.wealth < NIGHT_WEALTH:
        return
    if fort.siege is not None or not fort.rng.chance(NIGHT_ODDS):
        return
    if night.moon_is_full(fort.time) and fort.rng.chance(0.6):
        _send_werebeast(fort)
    else:
        _send_necromancer(fort)


def _send_werebeast(fort) -> None:
    """One werewolf, at the full moon, going straight for the nearest dwarf."""
    entry = fort.edge_arrival()
    beast = make_creature(fort.rng, "werewolf", faction="hostile", level=3)
    beast.x, beast.y, beast.z = fort._free_spot(entry, 0)
    beast.wx, beast.wy = fort.wx, fort.wy
    fort.add_creature(beast)
    fort.log.bad("The moon is full, and something is howling outside.")
    fort.military.sound_alarm(fort.log)


def _send_necromancer(fort) -> None:
    """A necromancer, and whatever it can find to carry.

    It brings almost nothing. It does not need to: it needs your graveyard,
    and every dwarf you lose driving it off is one more thing to fight.
    """
    from ..world import history as history_mod

    entry = fort.edge_arrival()
    boss = make_creature(fort.rng, "necromancer", faction="hostile", level=4)
    boss.x, boss.y, boss.z = fort._free_spot(entry, 0)
    boss.wx, boss.wy = fort.wx, fort.wy
    boss.profession = "necromancer"
    living = [f for f in fort.world.figures.values()
              if "necromancer" in f.flags and f.alive(fort.time.year)]
    if living:
        fig = fort.rng.choice(living)
        boss.name = fig.name
        boss.hf_id = fig.id
    fort.add_creature(boss)
    for i in range(fort.rng.randint(1, 3)):
        kind = fort.rng.choice(["zombie", "skeleton"])
        thrall = make_creature(fort.rng, kind, faction="hostile", level=1)
        thrall.x, thrall.y, thrall.z = fort._free_spot(entry, i + 1)
        thrall.wx, thrall.wy = fort.wx, fort.wy
        fort.add_creature(thrall)
    fort.log.bad("%s has come to %s. Bury your dead deep."
                 % (boss.display_name(), fort.name))
    fort.military.sound_alarm(fort.log)


#: Odds per season that somebody tries the door while nobody is looking.
THIEF_ODDS = 0.2

#: What a thief will not bother carrying off.
THIEF_IGNORES = ("boulder", "log", "corpse", "ore", "coal")

#: The cheapest thing worth the trip.
THIEF_WANTS = 20

#: How long a kobold will keep looking before it gives up and goes home.
#: A thief that cannot reach anything must not stand in a corridor for ever.
THIEF_PATIENCE = TICKS_PER_DAY * 2

#: And a thief that cannot find its way out is gone anyway after this long.
#: ``retreat_step`` walks towards the nearest edge on one level, so a kobold
#: that robbed you five levels down will walk into a wall and stay there,
#: which is a permanent resident nobody hunts. It found a way out you did not
#: know about, the same story ``war.FLEE_TICKS`` tells about a wedged army.
THIEF_GONE = TICKS_PER_DAY * 5


def _maybe_thief(fort) -> None:
    """A kobold sneaks in for whatever is nearest the door.

    Not a siege: one creature, no announcement, and it leaves the moment it
    has something. The fortress finds out from the sheriff's book, or from
    the gap where the artifact used to be.
    """
    if fort.lost or not fort.dwarves() or fort.wealth < 400:
        return
    if any(c.thief for c in fort.creatures.values()):
        return
    if not fort.rng.chance(THIEF_ODDS):
        return
    entry = fort.edge_arrival()
    thief = make_creature(fort.rng, "kobold", faction="hostile", level=1)
    thief.x, thief.y, thief.z = fort._free_spot(entry, 0)
    thief.wx, thief.wy = fort.wx, fort.wy
    thief.thief = True
    thief.thief_since = fort.ticks
    thief.skills.set_level("sneak", 8)
    fort.add_creature(thief)


def _thieves(fort) -> None:
    """Move whatever is currently robbing you.

    A thief with something in its hands leaves by the shortest way out. So
    does one that has run out of patience: a kobold that cannot reach anything
    worth taking goes home empty-handed rather than standing in a corridor
    until somebody trips over it.
    """
    from . import war as war_mod

    for c in list(fort.creatures.values()):
        if not c.thief or c.body.dead:
            continue
        here = fort.ticks - c.thief_since
        if c.loot is None and here <= THIEF_PATIENCE:
            _thief_step(fort, c)
            continue
        out = war_mod.retreat_step(fort, c)
        if not out and here > THIEF_GONE:
            fort.creatures.pop(c.id, None)
            out = True
        if not out or c.loot is None:
            continue
        justice.report(fort, "theft", None, c.loot_name)
        fort.log.bad("A kobold thief escapes with %s!" % c.loot_name)


def _thief_step(fort, thief) -> None:
    """One step towards the nearest thing worth stealing."""
    best, best_d = None, None
    for cell, pile in fort.items_on_ground.items():
        for item in pile:
            if item.def_id in THIEF_IGNORES or item.value < THIEF_WANTS:
                continue
            dist = (geometry.chebyshev(thief.x, thief.y, cell[0], cell[1])
                    + abs(thief.z - cell[2]) * 8)
            if best_d is None or dist < best_d:
                best, best_d = (item, cell), dist
    if best is None:
        # Nothing on the floor is worth the walk. Wait for the haulers to put
        # something down, but not for ever -- patience is running.
        return
    item, cell = best
    if geometry.chebyshev(thief.x, thief.y, cell[0], cell[1]) <= 1 \
            and thief.z == cell[2]:
        fort.take_item(item)
        thief.inventory.items.append(item)
        thief.loot = item.id
        thief.loot_name = item.name()
        return
    _hostile_step(fort, thief, cell)


def spawn_demons(fort, cell, wave: int = 1) -> List:
    """Everything that was under the adamantine comes up out of the hole.

    The first wave is the one that ends most fortresses. The rest arrive at
    their leisure, because nothing can be done about the hole.
    """
    from ..world import history as history_mod

    count = DEMON_FIRST_WAVE if wave == 1 else DEMON_WAVE
    out = []
    for i in range(count):
        foe = make_creature(fort.rng, "demon", faction="hostile", level=5)
        foe.name = name_data.beast_name(fort.rng)
        foe.x, foe.y, foe.z = fort._free_spot(cell, i)
        foe.wx, foe.wy = fort.wx, fort.wy
        fort.add_creature(foe)
        out.append(foe)
    fort.military.sound_alarm(fort.log)
    fort.breach_cell = cell
    if wave == 1:
        fort.log.bad("Demons pour out of the pit. There are %d of them."
                     % len(out))
        history_mod.record(
            fort.world, fort.time.year, "beast_attack",
            "The demons of the underworld came forth at %s." % fort.name,
            [], [fort.site_id] if fort.site_id else [],
        )
    else:
        fort.log.bad("More of them come up out of the pit.")
    return out


def spawn_attack(fort, strength: int) -> List:
    """Put a raiding party on the edge of the map."""
    entry = fort.edge_arrival()
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
        civ = (fort.world.civ(fort.siege.civ_id)
               if fort.siege is not None and fort.siege.civ_id is not None
               else None)
        fort.loss_reason = ("overrun by %s" % civ.name if civ is not None
                            else "overrun by %ss" % hostiles[0].short_name())
        war.record(fort, won=False)
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
