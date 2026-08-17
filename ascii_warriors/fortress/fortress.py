"""The fortress: the game state for fortress mode."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..data.calendar import GameTime, TICKS_PER_HOUR
from ..engine import geometry
from ..engine.rng import RNG
from ..game.entity import Creature
from ..game.item import Item, corpse_of
from ..game.log import MessageLog
from ..game.weather import Weather, starting_weather
from ..world import tiles as tile_data
from ..world.fire import Fire as FireLayer
from ..world.heat import Frost
from ..world.fluids import (Magma, Water, can_hold, seed_from_terrain,
                            seed_magma)
from ..world.localmap import LocalMap
from ..world.worldgen import World
from . import dwarf as dwarf_mod
from . import production
from .buildings import GATE_TILES, Building, Stockpile
from .designations import KINDS as DESIGNATION_KINDS
from .designations import Designations
from .jobs import Job, JobBoard
from .military import Military
from .nobles import Court

Cell = Tuple[int, int, int]

#: How much fortress time passes per simulation step.
STEP_TICKS = 10

#: Plump helmets held back from the kitchen so there is always something to sow.
SEED_RESERVE = 6

#: Days of food per dwarf a workshop may not consume. Without this a still on
#: repeat cheerfully brews the entire larder into ale and everybody starves
#: surrounded by drink.
FOOD_RESERVE_DAYS = 8

#: Item kinds that count as the fortress's larder.
FOOD_KINDS = ("meat", "cooked_meat", "prepared_meal", "bread", "cheese",
              "fish_food", "plump_helmet", "berries", "cave_wheat")


class Fortress:
    """One fortress: the map, its dwarves, and everything they are doing."""

    def __init__(
        self, world: World, local: LocalMap, rng: RNG, *, name: str = "",
        wx: int = 0, wy: int = 0,
    ) -> None:
        self.world = world
        self.local = local
        self.rng = rng
        self.name = name or "Fortress"
        self.wx = wx
        self.wy = wy
        self.time = GameTime.at(world.year, 1, 1, 8, 0)
        self.log = MessageLog()
        #: Everything currently alight on this map.
        self.fire = FireLayer()
        #: What the winter has taken of the water.
        self.frost = Frost()
        self.designations = Designations()
        self.jobs = JobBoard()
        self.buildings: List[Building] = []
        self.stockpiles: List[Stockpile] = []
        self.military = Military()
        self.court = Court()
        self.creatures: Dict[int, Creature] = {}
        #: Rectangles the fortress keeps its grazing animals on.
        self.pastures: List[Any] = []
        #: Cell -> the tick its grass was eaten, so it can grow back.
        self.grazed: Dict[Cell, int] = {}
        #: Cell -> what an engraver carved on that wall.
        self.engravings: Dict[Cell, Any] = {}
        #: Dwarf id -> the tick it died, for as long as it is above ground.
        #: Emptied by burial, and the reason a fortress needs coffins.
        self.unburied: Dict[int, int] = {}
        #: Dwarf id -> the ghost of it, for the ones that waited too long.
        self.ghosts: Dict[int, Any] = {}
        #: Everything anybody has been caught doing, and some things nobody
        #: has been caught doing.
        self.crimes: List[Any] = []
        #: ``(lower id, higher id)`` -> what those two dwarves are to each
        #: other. One entry per pair, so there is only ever one answer.
        self.bonds: Dict[Tuple[int, int], Any] = {}
        self.items_on_ground: Dict[Cell, List[Item]] = {}
        self.weather = Weather()
        self.water = Water()
        #: Creature id -> steps spent under water. Held breath is not saved:
        #: a dwarf loaded out of a flooded room starts the count again.
        self.drowning: Dict[int, int] = {}
        #: Wet rock. Dig one of these and it never stops leaking.
        self.aquifer: Set[Cell] = set()
        self.magma = Magma()
        #: The top of the magma sea, and the empty heart of the adamantine
        #: spire. Mine into the second one and you have made the last mistake
        #: this fortress will make.
        self.magma_floor = 0
        self.hollow: Set[Cell] = set()
        #: Set once the spire has been opened. There is no closing it.
        self.breached = False
        #: Where it was opened, because they keep coming up out of it.
        self.breach_cell: Optional[Cell] = None
        self.paused = True
        self.speed = 1
        self.z = 0
        self.ticks = 0
        self.season_index = 0
        self.year_founded = world.year
        self.lost = False
        self.loss_reason = ""
        self.wealth = 0
        self.migrant_waves = 0
        self.siege_count = 0
        #: The civilization that sent the expedition here.
        self.civ_id: Optional[int] = None
        #: The army on the map, if there is one.
        self.siege: Optional[Any] = None
        #: Named objects made in strange moods, for the fortress's own legends.
        self.artifacts: List[Dict[str, Any]] = []
        #: The caravan currently parked outside, if any.
        self.caravan: Optional[Dict[str, Any]] = None
        #: Designated cells nothing can reach, and when to try them again.
        self.unreachable: Dict[Cell, int] = {}
        #: Scratch pathing state for hostiles, rebuilt freely.
        self.hostile_state: Dict[int, Dict[str, Any]] = {}
        self._water_cache: Optional[List[Cell]] = None
        #: Most water the map has ever held, for the flood warning.
        self._water_mark = 0
        #: The magma the map started with. Any more than this is loose.
        self._magma_mark = 0
        self._warned: Set[str] = set()
        self._next_scan = 0
        #: When the sheriff next looks at the book.
        self._next_court = 0
        self.site_id: Optional[int] = None
        #: Set once the fortress has been written into world history.
        self.recorded = False

    # -- construction ------------------------------------------------------ #

    @classmethod
    def embark(
        cls, world: World, wx: int, wy: int, rng: RNG, *,
        name: str = "", professions: Sequence[str] = (),
    ) -> "Fortress":
        """Generate the map, place the starting seven and their supplies."""
        from ..data import names as name_data
        from ..world import localmap as localmap_mod
        from . import animals as animal_mod
        from . import perform as perform_mod
        from .labors import STARTING_SEVEN

        old = (localmap_mod.LOCAL_W, localmap_mod.LOCAL_H,
               localmap_mod.Z_BELOW, localmap_mod.Z_ABOVE)
        localmap_mod.LOCAL_W, localmap_mod.LOCAL_H = 80, 60
        # Three levels deeper than anywhere else: the caverns keep the bottom
        # of an ordinary map, and the magma sea needs somewhere to be under
        # them.
        localmap_mod.Z_BELOW, localmap_mod.Z_ABOVE = 13, 5
        try:
            local, _pop = localmap_mod.generate_local(
                world, wx, wy, rng.sub("fortress-%d-%d" % (wx, wy)))
        finally:
            (localmap_mod.LOCAL_W, localmap_mod.LOCAL_H,
             localmap_mod.Z_BELOW, localmap_mod.Z_ABOVE) = old

        if not name:
            name = name_data.site_name(rng, "dwarf", "fortress")[1]
        fort = cls(world, local, rng, name=name, wx=wx, wy=wy)

        tile = world.tile(wx, wy)
        fort.weather = starting_weather(
            rng, tile.biome, tile.temperature, fort.time.season)

        fort.water = seed_from_terrain(local)
        fort._water_mark = fort.water.total()

        # The deep first: it eats the bottom levels, and an aquifer laid down
        # there would go into the magma with them.
        deep = localmap_mod.carve_deep(local, rng)
        fort.magma_floor = int(deep["floor"])
        fort.hollow = set(deep["hollow"])
        fort.magma = seed_magma(local, fort.magma_floor, deep.get("tube"))
        fort._magma_mark = fort.magma.total()
        fort._lay_aquifer(rng)
        wagon = fort._wagon_site()
        fort.z = wagon[2]
        for i, profession in enumerate(professions or STARTING_SEVEN):
            d = dwarf_mod.make_dwarf(rng, profession)
            spot = fort._free_spot(wagon, i)
            d.x, d.y, d.z = spot
            d.wx, d.wy = wx, wy
            fort.add_creature(d)

        fort._unload_wagon(wagon)
        fort._unload_animals(wagon, rng)
        animal_mod.spawn_wildlife(fort, rng)
        perform_mod.teach_embark(fort)
        fort.log.good("%s has been founded." % fort.name)
        fort.log.info("Seven dwarves, and everything they could carry.")
        fort._say_what_the_ground_is()
        fort.log.info("Press ? for help. Space starts and stops time.")
        return fort

    def _say_what_the_ground_is(self) -> None:
        """Tell the player where the farmland is, because it is not obvious.

        The surface of a fortress map is ramps, trees and undergrowth, and
        almost none of it is nine flat tiles of open ground. The soil is
        underneath it, a level or two down, and finding that out by failing
        to place a farm plot is a worse way to learn it.
        """
        tid = tile_data.soil_tile(self.local.soil)
        ground = tile_data.get(tid)
        if not tile_data.is_soil(tid):
            self.log.bad(
                "There is nothing but %s under the snow here. Nothing will "
                "grow in it." % ground.name)
            return
        self.log.info(
            "Crops want soil. There is %s a level or two under your feet."
            % ground.name)

    def _lay_aquifer(self, rng: RNG) -> None:
        """Soak one layer of rock, in a wet enough place.

        An aquifer is a whole z-level of stone that bleeds water when you cut
        into it. It is the reason dwarves learn to dig around things.
        """
        tile = self.world.tile(self.wx, self.wy)
        if tile.rainfall < 0.35 or tile.is_ocean:
            return
        if not rng.chance(0.25 + tile.rainfall * 0.45):
            return
        lm = self.local
        # Pick a layer that is actually mostly rock. Choosing by depth below
        # the surface puts the aquifer in open air on a map with a valley in
        # the middle of it.
        best_z, best = None, 0
        top = max(lm.surface) if lm.surface else 0
        # Above the warm stone: wet rock over the magma sea is not wet for
        # long, and an aquifer inside the sea is not an aquifer at all.
        for z in range(self.magma_floor + 2, min(top, lm.zmax)):
            count = 0
            for y in range(0, lm.height, 2):
                for x in range(0, lm.width, 2):
                    t = tile_data.get(lm.tile(x, y, z))
                    if t.has("DIGGABLE") and t.has("WALL"):
                        count += 1
            # Shallower layers are more interesting: an aquifer you only meet
            # at the bottom of the map is an aquifer you never meet.
            score = count * (1.0 + 0.15 * (z - lm.zmin))
            if score > best:
                best_z, best = z, score
        if best_z is None:
            return
        z = best_z
        wet = set()
        for y in range(lm.height):
            for x in range(lm.width):
                tid = lm.tile(x, y, z)
                if tile_data.get(tid).has("DIGGABLE") \
                        and tile_data.get(tid).has("WALL"):
                    wet.add((x, y, z))
        if len(wet) < 200:
            return
        self.aquifer = wet
        self.log.info("The rock here is damp. There is water in it somewhere.")

    def _wagon_site(self) -> Cell:
        """Open ground near the middle of the map, on the surface.

        The wagon has to stop outside; a fortress that starts underground has
        nowhere for migrants or caravans to arrive from.
        """
        lm = self.local
        cx, cy = lm.width // 2, lm.height // 2
        best: Optional[Cell] = None
        best_d = 1 << 30
        for radius in range(0, max(lm.width, lm.height) // 2):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    x, y = cx + dx, cy + dy
                    if not lm.in_bounds(x, y, 0):
                        continue
                    z = lm.surface_z(x, y)
                    if not lm.walkable(x, y, z):
                        continue
                    if not lm.is_outside(x, y, z):
                        continue
                    open_around = sum(
                        1 for ddx, ddy in geometry.DIRS8
                        if lm.walkable(x + ddx, y + ddy, lm.surface_z(
                            x + ddx, y + ddy))
                    )
                    if open_around < 6:
                        continue
                    d = radius
                    if d < best_d:
                        best, best_d = (x, y, z), d
            if best is not None:
                return best
        return self.local.central_open(self.rng)

    def _free_spot(self, near: Cell, offset: int) -> Cell:
        """A walkable cell close to a point, a different one per offset.

        One ring at a time, each cell counted once. Scanning the whole square
        at every radius counts the middle over and over, so two callers with
        different offsets are handed the same tile and a wagonload of migrants
        arrives standing on top of each other.
        """
        for radius in range(0, 14):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    cell = (near[0] + dx, near[1] + dy, near[2])
                    if not self.local.walkable(*cell):
                        continue
                    if self.creature_at(*cell) is not None:
                        continue
                    if offset <= 0:
                        return cell
                    offset -= 1
        return near

    def _unload_wagon(self, at: Cell) -> None:
        """Drop the embark supplies on the ground."""
        rng = self.rng
        # Enough to dig in, raise a still and get a crop planted, and no more.
        supplies = [
            ("plump_helmet", "plant", 120),
            ("dwarven_ale", "alcohol", 150),
            ("meat", "meat", 20),
            ("log", "oak", 14),
            ("boulder", "granite", 8),
            # Enough metal for one thing at the forge. After that you dig for
            # it, or you buy it.
            ("bar", "copper", 4),
            ("charcoal", "charcoal", 6),
            ("bandage", "pig_tail_cloth", 8),
            ("splint", "oak", 4),
            ("torch", "oak", 6),
            ("coin", "silver", 200),
        ]
        for def_id, material, count in supplies:
            item = Item(def_id, material, count=count)
            if item.is_light:
                item.charges = 3000
            self.drop_item(item, *at)
        for _ in range(2):
            self.drop_item(Item("pick", "iron"), *at)

    def _unload_animals(self, at: Cell, rng: RNG) -> None:
        """The livestock that walked here behind the wagon."""
        from . import animals as animal_mod

        dwarves = self.dwarves()
        for i, (species, female) in enumerate(animal_mod.EMBARK_ANIMALS):
            beast = animal_mod.make_animal(rng, species, female=female,
                                           age=rng.randint(2, 5))
            beast.x, beast.y, beast.z = self._free_spot(at, i + 8)
            beast.wx, beast.wy = self.wx, self.wy
            if beast.defn.has("PET") and dwarves:
                beast.animal.owner = dwarves[i % len(dwarves)].id
            self.add_creature(beast)
        self.drop_item(Item("axe", "iron"), *at)

    # -- creatures --------------------------------------------------------- #

    def add_creature(self, c: Creature) -> None:
        """Put a creature on the map."""
        self.creatures[c.id] = c

    def remove_creature(self, c: Creature) -> None:
        """Take a creature off the map.

        For anything that leaves rather than dies. Its bonds go with it: the
        dead keep theirs, because who the dead were close to is what the
        survivors are grieving, but nobody grieves somebody who walked out.
        """
        self.creatures.pop(c.id, None)
        if self.bonds:
            from . import social as social_mod

            social_mod.forget(self, c.id)

    def creature_at(self, x: int, y: int, z: int) -> Optional[Creature]:
        """The living creature standing on a cell."""
        for c in self.creatures.values():
            if c.x == x and c.y == y and c.z == z and not c.body.dead:
                return c
        return None

    def pasture(self, pid) -> Optional[Any]:
        """Look a pasture up by id."""
        if pid is None:
            return None
        return next((p for p in self.pastures if p.id == pid), None)

    def pasture_at(self, x: int, y: int, z: int) -> Optional[Any]:
        """The pasture covering a cell, if any."""
        return next((p for p in self.pastures if p.contains(x, y, z)), None)

    def dwarves(self) -> List[Creature]:
        """Every living dwarf of the fortress.

        Not one that is currently wearing another shape. A werebeast keeps its
        labors, its bed and its name -- it gets them back at dawn -- but for
        tonight it is not yours, and nothing that iterates the roster should
        hand it a job or count on it holding a door.
        """
        return [
            c for c in self.creatures.values()
            if getattr(c, "fort", None) is not None and not c.body.dead
            and not c.changed
        ]

    def hostiles(self) -> List[Creature]:
        """Every living enemy on the map.

        Thieves are not in here. One kobold with its eye on a mug is not a
        reason to sound the alarm, send the militia and stop everybody
        drinking; it is a reason to notice the mug is gone.
        """
        return [
            c for c in self.creatures.values()
            if c.faction == "hostile" and not c.body.dead and not c.thief
        ]

    def kill_creature(self, c: Creature) -> None:
        """Handle a death: corpse, dropped goods, and the loss of a dwarf."""
        if not c.alive:
            return
        c.alive = False
        c.body.dead = True
        # The same shock the adventure map takes: everybody on its side who
        # was near enough to watch it happen.
        from ..game import morale as morale_mod

        morale_mod.saw_death(self, c)
        state = getattr(c, "fort", None)
        if state is not None:
            self.log.bad("%s has died: %s." % (
                c.name, c.body.death_cause or "slain"))
            if state.job is not None:
                self.abandon_job(c, state.job)
            self.designations.release_all(c.id)
            self.jobs.release_all(c.id)
            # Everybody who knew them feels it, and nobody else pretends to.
            from . import social as social_mod

            social_mod.grieve(self, c)
            for other in self.dwarves():
                other.needs.add_thought("saw a death in the fortress", 5)
            # It is now waiting for a coffin, and it will not wait for ever.
            self.unburied[c.id] = self.ticks
        else:
            self.log.combat("The %s is dead." % c.short_name())
            self._record_kill(c)
            if c.faction == "hostile":
                from . import war as war_mod

                war_mod.on_kill(self, c)
        self.drop_item(corpse_of(c), c.x, c.y, c.z)
        for item in c.inventory.remove_all():
            self.drop_item(item, c.x, c.y, c.z)

    def _record_kill(self, c: Creature) -> None:
        """Write a legend's death into the world that remembers it.

        Killing a megabeast is the biggest thing most fortresses ever do, and
        it should be in the legends screen afterwards with your fortress named
        in it.
        """
        if getattr(c, "hf_id", None) is None:
            return
        from ..world import history as history_mod

        fig = self.world.figures.get(c.hf_id)
        if fig is None or fig.died is not None:
            return
        fig.died = self.time.year
        fig.death_cause = "slain at %s" % self.name
        history_mod.record(
            self.world, self.time.year, "beast_slain",
            "The %s %s was slain at %s." % (
                c.short_name(), fig.display_name, self.name),
            [fig.id], [self.site_id] if self.site_id else [],
        )
        self.log.good("The %s %s is dead. %s will be remembered for it."
                      % (c.short_name(), fig.display_name, self.name))
        for d in self.dwarves():
            d.needs.add_thought("was part of something legendary", -20)

    # -- items ------------------------------------------------------------- #

    def drop_item(self, item: Item, x: int, y: int, z: int) -> None:
        """Put an item on the floor."""
        pile = self.items_on_ground.setdefault((x, y, z), [])
        for existing in pile:
            if existing.stack_with(item):
                return
        pile.append(item)

    def take_item(self, item: Item) -> bool:
        """Lift an item off the floor."""
        cell = self.item_cell(item)
        if cell is None:
            return False
        pile = self.items_on_ground[cell]
        pile.remove(item)
        if not pile:
            del self.items_on_ground[cell]
        return True

    def settle_above(self, cell: Cell) -> None:
        """Drop anything left standing on a floor that has just gone."""
        from ..world import gravity

        above = (cell[0], cell[1], cell[2] + 1)
        for c in list(self.creatures.values()):
            if c.body.dead or (c.x, c.y, c.z) not in (cell, above):
                continue
            if gravity.settle(self, c, self.rng, log=self.log) and c.body.dead:
                self.kill_creature(c)
        for spot in (cell, above):
            gravity.settle_items(self, spot)
        self._water_cache = None

    def item_cell(self, item: Item) -> Optional[Cell]:
        """Where an item is lying, or ``None`` if it is carried."""
        for cell, pile in self.items_on_ground.items():
            if item in pile:
                return cell
        return None

    def items_at(self, x: int, y: int, z: int) -> List[Item]:
        """Items on a cell."""
        return self.items_on_ground.get((x, y, z), [])

    def all_items(self) -> List[Item]:
        """Every item lying on the ground anywhere."""
        out: List[Item] = []
        for pile in self.items_on_ground.values():
            out.extend(pile)
        return out

    def find_item(self, item_id: int) -> Optional[Item]:
        """Look an item up by id."""
        for pile in self.items_on_ground.values():
            for item in pile:
                if item.id == item_id:
                    return item
        for c in self.creatures.values():
            for item in c.inventory.items:
                if item.id == item_id:
                    return item
        return None

    def food_stock(self) -> int:
        """Everything edible the fortress is sitting on."""
        return self.stock_count(*FOOD_KINDS)

    def food_reserve(self) -> int:
        """How much of the larder workshops are not allowed to touch."""
        return max(SEED_RESERVE,
                   len(self.dwarves()) * FOOD_RESERVE_DAYS)

    def stock_count(self, *def_ids: str) -> int:
        """How many units of the given item kinds the fortress holds."""
        total = 0
        for pile in self.items_on_ground.values():
            for item in pile:
                if item.def_id in def_ids:
                    total += item.count
        return total

    def find_consumable(self, dwarf, *, drink: bool) -> Optional[Item]:
        """The nearest food or drink a dwarf could go and consume."""
        best: Optional[Item] = None
        best_d = 1 << 30
        # Never eat the last few mushrooms while there is a plot to plant them
        # in. A fortress that eats its seed corn does not get a second spring.
        reserve = (SEED_RESERVE
                   if any(b.kind == "farm" for b in self.buildings) else 0)
        seeds_left = self.stock_count("plump_helmet") if reserve else 0
        for cell, pile in self.items_on_ground.items():
            if cell[2] != dwarf.z and abs(cell[2] - dwarf.z) > 6:
                continue
            for item in pile:
                if drink and not item.is_drink:
                    continue
                # Ale counts as food as well as drink, and a dwarf offered the
                # choice will happily eat a fortnight of it as a snack.
                if not drink and (not item.is_edible or item.is_corpse
                                  or item.is_drink):
                    continue
                if (reserve and not drink and item.def_id == "plump_helmet"
                        and seeds_left <= reserve):
                    continue
                d = (geometry.chebyshev(dwarf.x, dwarf.y, cell[0], cell[1])
                     + abs(dwarf.z - cell[2]) * 3)
                if d < best_d:
                    best, best_d = item, d
        return best

    def consume(self, dwarf, item: Item, *, drink: bool) -> None:
        """Eat or drink one unit of an item lying on the floor."""
        if drink:
            dwarf.needs.drink(item)
            self.clear_warning("thirst")
            if item.material == "alcohol":
                dwarf.needs.add_thought("had a drink", -3)
        else:
            dwarf.needs.eat(item)
            self.clear_warning("hunger")
            if item.quality >= 2 or item.def_id == "prepared_meal":
                dwarf.needs.add_thought("ate a fine meal", -6)
        item.count -= 1
        if item.count <= 0:
            self.take_item(item)

    # -- terrain ----------------------------------------------------------- #

    def is_passable(self, x: int, y: int, z: int) -> bool:
        """True if a dwarf could stand there."""
        return (self.local.walkable(x, y, z)
                and not self.water.deep(x, y, z)
                and self.magma.at(x, y, z) <= 0)

    def path_neighbours(self, node: Cell):
        """Neighbours for pathing, avoiding water a dwarf would drown in.

        Wading is fine. Swimming is how a hauler carrying a rock dies, so the
        route planner simply refuses to go that way.
        """
        from ..world.fluids import SWIM_DEPTH

        depth = self.water.depth
        magma = self.magma.depth
        for cell, cost in self.local.path_neighbours(node):
            water = depth.get(cell, 0)
            if water >= SWIM_DEPTH or magma.get(cell, 0) > 0:
                # No amount of any depth of magma is worth walking through.
                continue
            yield (cell, cost + water * 0.8)

    def flier_neighbours(self, node: Cell):
        """Pathing neighbours for something that flies over the fortress.

        The walking graph refuses deep water and magma because a hauler
        carrying a rock drowns in one and dies in the other. A roc does
        neither, and a wall it can go over is not a wall.
        """
        magma = self.magma.depth
        for cell, cost in self.local.flier_neighbours(node):
            if magma.get(cell, 0) > 0:
                continue
            yield (cell, cost)

    def water_sources(self) -> List[Cell]:
        """Every cell a dwarf could drink from: open water and built wells.

        Cached, because scanning eighty thousand cells for a thirsty dwarf on
        every step is not a good use of anybody's afternoon.
        """
        if self._water_cache is None:
            cells: List[Cell] = []
            lm = self.local
            for z, level in lm.levels.items():
                for i, tid in enumerate(level):
                    if tid in ("shallow_water", "water", "well"):
                        cells.append((i % lm.width, i // lm.width, z))
            self._water_cache = cells
        wells = [b.center for b in self.buildings
                 if b.kind == "well" and b.built]
        return self._water_cache + wells

    def invalidate_water(self) -> None:
        """Forget the cached water map after the terrain changes."""
        self._water_cache = None

    def nearest_water(self, dwarf) -> Optional[Cell]:
        """The closest cell a dwarf could drink from."""
        best: Optional[Cell] = None
        best_d = 1 << 30
        for cell in self.water_sources():
            d = (geometry.chebyshev(dwarf.x, dwarf.y, cell[0], cell[1])
                 + abs(dwarf.z - cell[2]) * 4)
            if d < best_d:
                best, best_d = cell, d
        return best

    def bed_for(self, dwarf) -> Optional[Building]:
        """The bed assigned to a dwarf, claiming a free one if it has none."""
        state = dwarf.fort
        if state.bed is not None:
            bed = self.building(state.bed)
            if bed is not None and bed.built:
                return bed
            state.bed = None
        for b in self.buildings:
            if b.kind in ("bed", "hospital") and b.built and b.owner is None:
                b.owner = dwarf.id
                state.bed = b.id
                return b
        return None

    def building(self, bid: int) -> Optional[Building]:
        """Look a building up by id."""
        for b in self.buildings:
            if b.id == bid:
                return b
        return None

    def building_at(self, x: int, y: int, z: int) -> Optional[Building]:
        """The building occupying a cell."""
        for b in self.buildings:
            if (x, y, z) in b.cells():
                return b
        return None

    def stockpile_at(self, x: int, y: int, z: int) -> Optional[Stockpile]:
        """The stockpile covering a cell."""
        for s in self.stockpiles:
            if s.contains(x, y, z):
                return s
        return None

    def warn_once(self, key: str, text: str) -> None:
        """Log a warning the first time a problem appears."""
        if key in self._warned:
            return
        self._warned.add(key)
        self.log.warn(text)

    def clear_warning(self, key: str) -> None:
        """Allow a warning to fire again."""
        self._warned.discard(key)

    # -- job lifecycle ----------------------------------------------------- #

    def prepare_job(self, dwarf, job: Job) -> bool:
        """Reserve whatever a job needs before a dwarf commits to it."""
        if job.kind in DESIGNATION_KINDS:
            return self.designations.claim(job.cell, dwarf.id)
        if job.kind in ("haul", "bury"):
            item = self.find_item(job.target) if job.target else None
            if item is None or self.item_cell(item) is None:
                self.jobs.remove(job)
                return False
        return True

    def cancel_preparation(self, dwarf, job: Job) -> None:
        """Undo :meth:`prepare_job` when the dwarf cannot get there."""
        if job.kind in DESIGNATION_KINDS:
            self.designations.release(job.cell)

    def abandon_job(self, dwarf, job: Job) -> None:
        """A dwarf gives up on a job, putting down whatever it was carrying."""
        self.cancel_preparation(dwarf, job)
        self.put_down(dwarf, job)
        self.jobs.release(job)

    def complete_job(self, dwarf, job: Job) -> None:
        """Apply a finished job's effect."""
        handler = getattr(self, "_finish_" + job.kind, None)
        if handler is not None:
            handler(dwarf, job)
        self.jobs.remove(job)
        if job.kind in DESIGNATION_KINDS:
            self.designations.clear(job.cell)

    def release_job_items(self, job: Job) -> None:
        """Un-reserve everything a cancelled job had promised itself.

        Whoever was carrying the goods puts them down. A job that is deleted
        while a dwarf still holds its materials takes those materials out of
        the fortress permanently.
        """
        holder = self.creatures.get(job.assigned) if job.assigned else None
        if holder is not None and getattr(holder, "fort", None) is not None:
            self.put_down(holder, job)
        for item_id, owner in list(self.jobs.reserved_items.items()):
            if owner == job.id:
                del self.jobs.reserved_items[item_id]
        if job.kind == "build":
            b = self.building(job.target) if job.target else None
            if b is not None and not b.built:
                b.materials.clear()

    # -- fetching ---------------------------------------------------------- #

    def job_items(self, job: Job) -> List[int]:
        """Item ids a job needs in hand before the work can start."""
        if job.kind in ("haul", "equip", "bury"):
            return [job.target] if job.target else []
        if job.kind == "treat":
            return [job.carrying] if job.carrying else []
        if job.kind == "build":
            b = self.building(job.target) if job.target else None
            return list(b.materials) if b is not None and not b.built else []
        return []

    def fetch_target(self, dwarf, job: Job) -> Optional[Cell]:
        """Where a dwarf must go to collect the next thing a job needs."""
        for item_id in self.job_items(job):
            item = self.find_item(item_id)
            if item is None:
                continue
            if dwarf.inventory.contains(item):
                continue
            cell = self.item_cell(item)
            if cell is not None:
                return cell
        return None

    def pick_up_for(self, dwarf, job: Job) -> bool:
        """Lift the next item a job needs off the floor. False if it is gone."""
        for item_id in self.job_items(job):
            item = self.find_item(item_id)
            if item is None or dwarf.inventory.contains(item):
                continue
            cell = self.item_cell(item)
            if cell is None:
                continue
            if not dwarf_mod.at_or_beside(dwarf, cell, vertical=False):
                continue
            self.take_item(item)
            # Appended rather than added: stacking would change the item's
            # identity, and the job is holding on to its id.
            dwarf.inventory.items.append(item)
            dwarf.fort.carrying = item.id
            return True
        return False

    def put_down(self, dwarf, job: Job) -> None:
        """Drop everything a dwarf had picked up for a job."""
        for item_id in self.job_items(job):
            item = next((i for i in dwarf.inventory.items if i.id == item_id),
                        None)
            if item is None:
                continue
            dwarf.inventory.items.remove(item)
            self.drop_item(item, dwarf.x, dwarf.y, dwarf.z)
        dwarf.fort.carrying = None

    # -- job completion handlers ------------------------------------------- #

    def dig_out(self, cell: Cell, tile: str) -> None:
        """Change a tile because somebody dug or built it.

        Everything that opens rock up has to go through here, so the water
        finds out. A tunnel that reaches an aquifer or a riverbed and does not
        flood is a bug the player cannot see until it is too late to matter.
        """
        was_aquifer = cell in self.aquifer
        was_hollow = cell in self.hollow
        warm = self.local.tile(*cell) == "warm_stone"
        held_before = can_hold(self.local, cell)
        self.local.set_tile(cell[0], cell[1], cell[2], tile)
        self._water_cache = None
        if held_before or not can_hold(self.local, cell):
            # Smoothing a wall, or turning a floor into a farm plot, changes
            # nothing the water cares about. The bank still holds.
            return
        self.water.unseal(cell)
        self.magma.unseal(cell)
        if warm:
            self.warn_once(
                "warm", "The stone here is warm. There is magma below it.")
        if was_hollow:
            self.hollow.discard(cell)
            self._breach_the_spire(cell)
        if was_aquifer:
            self.aquifer.discard(cell)
            self.water.add_source(cell, 1)
            self.warn_once(
                "aquifer",
                "You have breached an aquifer. The water will not stop.")

    def _breach_the_spire(self, cell: Cell) -> None:
        """Somebody mined into the hollow. Everything after this is a story.

        Demons come up out of it for as long as the fortress lasts. There is
        no sealing it: the point of the adamantine is that it costs more than
        you have.
        """
        from . import sim as sim_mod

        if self.breached:
            sim_mod.spawn_demons(self, cell, wave=2)
            return
        self.breached = True
        self.log.bad("You have struck something hollow. Cold air comes up "
                     "out of it.")
        self.log.bad("The dead of the underworld are coming.")
        sim_mod.spawn_demons(self, cell, wave=1)

    # -- levers and gates -------------------------------------------------- #

    def levers(self) -> List[Building]:
        """Every built lever."""
        return [b for b in self.buildings if b.kind == "lever" and b.built]

    def light_at(self, x: int, y: int, z: int) -> float:
        """Ambient light at a cell, 0..1.

        The same question a Game answers, so the stealth roll can be asked in
        either mode without knowing which one it is standing in. A fortress
        has no torches to track: underground is dark, and the surface follows
        the sky.
        """
        if self.local.is_outside(x, y, z):
            return self.time.light_level() * self.weather.light_modifier()
        return 0.12

    def temperature_at(self, x: int, y: int, z: int) -> float:
        """How cold or hot a cell is, in degrees.

        Also the same question a Game answers, and the reason a fortress is
        dug downwards: the rock does not care what month it is, so the
        difference between a hard winter and a comfortable one is how much of
        your fortress is above the surface.
        """
        from ..data import biomes as biome_data
        from ..world import heat

        tile = self.world.tile(self.wx, self.wy)
        outside = self.local.is_outside(x, y, z)
        air = heat.ambient(
            tile.temperature, biome=biome_data.get(tile.biome),
            season=self.time.season, hour=self.time.hour,
            weather=self.weather.kind,
            depth=max(0, self.local.surface_z(x, y) - z), outside=outside)
        return air + heat.source_heat(
            (x, y, z), fire=self.fire, magma=self.magma)

    def tavern(self) -> Optional[Building]:
        """Where the fortress drinks, if it has built anywhere to."""
        for b in self.buildings:
            if b.kind == "tavern" and b.built:
                return b
        return None

    def gates(self) -> List[Building]:
        """Everything a lever could be linked to."""
        return [b for b in self.buildings if b.built and b.is_gate]

    def link(self, lever: Building, gate: Building) -> bool:
        """Connect a lever to a gate, or disconnect it if already linked."""
        if gate.id in lever.links:
            lever.links.remove(gate.id)
            return False
        lever.links.append(gate.id)
        return True

    def set_gate(self, gate: Building, shut: bool) -> None:
        """Open or close one gate and repaint its tiles."""
        gate.shut = shut
        tile = gate.gate_tile()
        for cx, cy, cz in gate.cells():
            self.local.set_tile(cx, cy, cz, tile)
            self.water.unseal((cx, cy, cz))
        self._water_cache = None

    def pull_lever(self, lever: Building) -> int:
        """Throw a lever. Returns how many gates moved."""
        moved = 0
        for gid in lever.links:
            gate = self.building(gid)
            if gate is None or not gate.built:
                continue
            self.set_gate(gate, not gate.shut)
            moved += 1
        lever.shut = not lever.shut
        lever.pending = False
        if moved:
            self.log.system("A lever is pulled: %d %s." % (
                moved, "gate moves" if moved == 1 else "gates move"))
        else:
            self.log.warn("A lever is pulled, and nothing happens.")
        return moved

    def _finish_tend(self, dwarf, job: Job) -> None:
        """Milk a cow or shear a sheep."""
        from . import animals as animal_mod

        beast = self.creatures.get(job.target) if job.target else None
        if beast is None or beast.body.dead:
            return
        made = animal_mod.produce(self, beast)
        if made is None:
            return
        self.drop_item(made, beast.x, beast.y, beast.z)
        dwarf.add_exp("herbalism", 15)

    def _finish_slaughter(self, dwarf, job: Job) -> None:
        """The end of the line for one animal.

        Butchering here rather than dropping a corpse for the butcher's shop:
        the animal is standing in front of the dwarf with the knife, and a
        fortress that has to haul its own cows to a workshop twice over is a
        fortress nobody wants to run.
        """
        from . import animals as animal_mod

        beast = self.creatures.get(job.target) if job.target else None
        if beast is None or beast.body.dead:
            return
        goods = animal_mod.butcher_yield(self, beast)
        beast.body.dead = True
        beast.body.death_cause = "slaughtered"
        beast.animal.slaughter = False
        self.kill_creature(beast)
        # The carcass is the meat: no corpse as well, or it butchers twice.
        pile = self.items_on_ground.get((beast.x, beast.y, beast.z)) or []
        self.items_on_ground[(beast.x, beast.y, beast.z)] = [
            i for i in pile if not i.is_corpse
        ]
        for item in goods:
            self.drop_item(item, beast.x, beast.y, beast.z)
        dwarf.add_exp("butchery", 25)
        self.log.info("%s has butchered a %s." % (dwarf.name,
                                                  beast.short_name()))

    def _finish_pull(self, dwarf, job: Job) -> None:
        """A dwarf reaches a lever and throws it."""
        lever = self.building(job.target) if job.target else None
        if lever is None or not lever.built:
            return
        self.pull_lever(lever)

    def _stone_here(self, cell: Cell) -> str:
        """Which material a wall at this cell is made of."""
        tid = self.local.tile(*cell)
        if tid in ("ore_vein", "gem_vein", "coal_seam", "adamantine_vein"):
            # What the vein is made of was decided when the map was made, so a
            # fortress can plan around what it has found.
            return self.local.veins.get(cell, "copper")
        if tid == "soil_wall":
            return ""
        return self.local.stone

    def _dug_floor(self, cell: Cell) -> str:
        """The ground a dug-out wall leaves behind.

        Soil leaves soil, and soil is what a crop grows in. Rock leaves bare
        rock, which is why the farms are in the top few levels and everything
        below them is a fortress rather than a field.
        """
        if self.local.tile(*cell) == "soil_wall":
            return tile_data.soil_tile(self.local.soil)
        return "floor"

    def _mined_item(self, cell: Cell, material: str) -> Optional[Item]:
        """What falls out of a wall when it is dug: ore, coal, gem or rock."""
        if not material:
            return None
        tid = self.local.tile(*cell)
        if tid == "coal_seam":
            return Item("coal", "coal", count=2)
        if tid == "gem_vein":
            return Item("rough_gem", material)
        if tid in ("ore_vein", "adamantine_vein"):
            return Item("ore", material)
        return Item("boulder", material)

    def _finish_dig(self, dwarf, job: Job) -> None:
        cell = job.cell
        material = self._stone_here(cell)
        found = self._mined_item(cell, material)
        rich = self.local.tile(*cell) in ("ore_vein", "gem_vein")
        self.dig_out(cell, self._dug_floor(cell))
        if found is not None:
            self.drop_item(found, *cell)
            if rich:
                self.log.good("%s has struck %s!" % (dwarf.name, material))
                dwarf.needs.add_thought("struck a rich vein", -10)
        self._reveal_around(cell)

    def _finish_channel(self, dwarf, job: Job) -> None:
        cell = job.cell
        found = self._mined_item(cell, self._stone_here(cell))
        self.dig_out(cell, "air")
        below = (cell[0], cell[1], cell[2] - 1)
        if self.local.in_bounds(*below):
            # Through dig_out as well: channelling cuts two tiles open, and
            # the lower one is as good a way into an aquifer as the upper.
            self.dig_out(below, "ramp_up")
            if found is not None:
                self.drop_item(found, *below)
        self._reveal_around(cell)
        # The floor is gone. Whoever was standing on it goes with it, which
        # is the one thing channelling has never done and the whole reason a
        # dwarf is told to dig from below.
        self.settle_above(cell)

    def _finish_stairs(self, dwarf, job: Job) -> None:
        cell = job.cell
        found = self._mined_item(cell, self._stone_here(cell))
        self.dig_out(cell, "stair_updown")
        if found is not None:
            self.drop_item(found, *cell)
        self._reveal_around(cell)

    def _finish_ramp(self, dwarf, job: Job) -> None:
        cell = job.cell
        found = self._mined_item(cell, self._stone_here(cell))
        self.dig_out(cell, "ramp_up")
        if found is not None:
            self.drop_item(found, *cell)
        self._reveal_around(cell)

    def _finish_smooth(self, dwarf, job: Job) -> None:
        cell = job.cell
        wall = tile_data.get(self.local.tile(*cell)).has("WALL")
        self.dig_out(cell, "wall_constructed" if wall else "floor_constructed")
        dwarf.needs.add_thought(
            "admired a smoothed wall" if wall else "walked on a smooth floor",
            -1)

    def _finish_engrave(self, dwarf, job: Job) -> None:
        """Carve something that happened into a wall that has been smoothed."""
        from . import art as art_mod

        art_mod.engrave(self, dwarf, job.cell)

    def _finish_chop(self, dwarf, job: Job) -> None:
        cell = job.cell
        self.dig_out(cell, "grass")
        above = (cell[0], cell[1], cell[2] + 1)
        if self.local.in_bounds(*above) and self.local.tile(*above) == "tree":
            self.dig_out(above, "air")
        self.drop_item(Item("log", self.rng.choice(["oak", "pine", "willow"])),
                       *cell)

    def _finish_fish(self, dwarf, job: Job) -> None:
        """A dwarf comes back from the water, with or without anything."""
        from ..game import foraging

        if not self.rng.chance(foraging.fish_chance(dwarf)):
            dwarf.add_exp("fishing", 10)
            return
        count = self.rng.randint(*foraging.FISH_YIELD)
        self.drop_item(Item("fish_food", "meat", count=count), *job.cell)
        dwarf.add_exp("fishing", 25)

    def _finish_gather(self, dwarf, job: Job) -> None:
        cell = job.cell
        self.dig_out(cell, "grass")
        self.drop_item(Item("plump_helmet", "plant",
                            count=self.rng.randint(2, 5)), *cell)

    def _finish_sand(self, dwarf, job: Job) -> None:
        """A bag of sand off the desert floor. The desert stays where it is."""
        self.drop_item(Item("sand", "sand"), *job.cell)
        dwarf.add_exp("glassmaking", 8)

    def _finish_remove(self, dwarf, job: Job) -> None:
        cell = job.cell
        self.dig_out(cell, "floor")
        b = self.building_at(*cell)
        if b is not None:
            self.buildings.remove(b)

    def _finish_haul(self, dwarf, job: Job) -> None:
        item = next((i for i in dwarf.inventory.items if i.id == job.target),
                    None)
        if item is None:
            return
        dwarf.inventory.items.remove(item)
        dwarf.fort.carrying = None
        self.drop_item(item, job.x, job.y, job.z)

    def _finish_bury(self, dwarf, job: Job) -> None:
        """A dwarf carries one of its own to a coffin and closes it."""
        from . import ghosts as ghost_mod

        body = next((i for i in dwarf.inventory.items if i.id == job.target),
                    None)
        # The coffin is where the job is: no second target field needed, and
        # no way for the two to disagree.
        coffin = self.building_at(*job.cell)
        if body is None or coffin is None or coffin.kind != "coffin" \
                or coffin.buried is not None:
            return
        dwarf.inventory.items.remove(body)
        dwarf.fort.carrying = None
        who = body.flags.get("who")
        coffin.buried = who
        coffin.buried_name = str(body.flags.get("name", "somebody"))
        self.unburied.pop(who, None)
        self.log.info("%s has been laid to rest." % coffin.buried_name)
        for other in self.dwarves():
            other.needs.add_thought("saw a friend buried", -4)
        if who is not None:
            ghost_mod.lay(self, who)

    def _finish_build(self, dwarf, job: Job) -> None:
        b = self.building(job.target) if job.target else None
        if b is None:
            return
        material_name = ""
        for item_id in list(b.materials):
            item = next((i for i in dwarf.inventory.items if i.id == item_id),
                        None)
            carried = item is not None
            if item is None:
                item = self.find_item(item_id)
            if item is None:
                continue
            material_name = material_name or item.mat.adjective
            item.count -= 1
            self.jobs.release_item(item_id)
            if not carried:
                if item.count <= 0:
                    self.take_item(item)
                continue
            dwarf.inventory.items.remove(item)
            if item.count > 0:
                # A dwarf sent for one log fetches the whole stack. Whatever it
                # did not nail down goes back on the floor where it can be used.
                self.drop_item(item, *b.center)
        dwarf.fort.carrying = None
        b.material_name = material_name
        b.built = True
        if b.is_gate:
            # A gate is built in whatever state its own tile says it is in: a
            # drawbridge lies down, a floodgate stands shut. Get this wrong and
            # the first pull of the lever appears to do nothing.
            b.shut = b.defn.tile == GATE_TILES[b.kind][1]
        for cx, cy, cz in b.cells():
            self.dig_out((cx, cy, cz), b.defn.tile)
        self.log.good("%s has completed a %s." % (dwarf.name, b.defn.name.lower()))
        if b.kind == "statue":
            for d in self.dwarves():
                d.needs.add_thought("admired a fine statue", -4)

    def _finish_craft(self, dwarf, job: Job) -> None:
        b = self.building(job.target) if job.target else None
        if b is None or not b.orders:
            return
        order = b.orders[0]
        recipe = production.RECIPES.get(order.get("recipe", ""))
        if recipe is None:
            b.orders.pop(0)
            return

        pool = [
            item for cell, pile in self.items_on_ground.items() for item in pile
            if cell[2] == b.z or abs(cell[2] - b.z) <= 4
        ]
        if self.food_stock() <= self.food_reserve():
            pool = [i for i in pool if not i.is_edible or i.is_drink]
            self.warn_once("larder",
                           "Workshops are idle: the fortress needs the food "
                           "more than the produce.")
        elif any(f.kind == "farm" for f in self.buildings) \
                and self.stock_count("plump_helmet") <= SEED_RESERVE:
            pool = [i for i in pool if i.def_id != "plump_helmet"]
        chosen = production.find_inputs(recipe, pool)
        if chosen is None:
            self.warn_once("inputs-" + recipe.id,
                           "%s: nothing to make it from." % recipe.name)
            # Do not cancel the order. A shortage now is not a shortage for
            # ever, and a standing order the player set should outlive one.
            order["blocked_until"] = self.ticks + TICKS_PER_HOUR
            b.orders.append(b.orders.pop(0))
            return
        self.clear_warning("inputs-" + recipe.id)

        for item, count in chosen:
            item.count -= count
            if item.count <= 0:
                self.take_item(item)
        material = production.output_material(recipe, chosen)
        quality = self._quality_for(dwarf, recipe)
        product = Item(recipe.output, material, quality=quality,
                       count=recipe.out_count, maker=dwarf.name)
        self.drop_item(product, *b.center)
        dwarf.add_exp(recipe.skill, 20)
        if quality >= 4:
            self.log.good("%s has created %s!" % (dwarf.name, product.name()))
            dwarf.needs.add_thought("made a masterpiece", -12)

        if order.get("repeat"):
            b.orders.append(b.orders.pop(0))
        else:
            order["count"] = int(order.get("count", 1)) - 1
            if order["count"] <= 0:
                b.orders.pop(0)

    def _quality_for(self, dwarf, recipe) -> int:
        """Roll the quality of a crafted item."""
        from ..game.skills import ability

        level = ability(dwarf, recipe.skill)
        roll = self.rng.random() + level * 0.035
        if roll > 1.15:
            return 5
        if roll > 1.0:
            return 4
        if roll > 0.85:
            return 3
        if roll > 0.65:
            return 2
        if roll > 0.4:
            return 1
        return 0

    def _finish_equip(self, dwarf, job: Job) -> None:
        """A soldier picks up its kit and puts it on."""
        item = next((i for i in dwarf.inventory.items if i.id == job.target),
                    None)
        if item is None:
            return
        self.jobs.release_item(item.id)
        dwarf.fort.carrying = None
        for msg in dwarf.inventory.auto_equip():
            pass
        if item.is_weapon:
            self.log.info("%s takes up %s." % (dwarf.name, item.name(article=True)))

    def _finish_treat(self, dwarf, job: Job) -> None:
        """A doctor gets to a patient and does what it can.

        The supplies go back on the floor whatever happens, including when the
        patient stopped bleeding on the way over. A doctor that pockets the
        fortress's only bandages is worse than no doctor.
        """
        from . import hospital

        try:
            patient = self.creatures.get(job.target)
            if patient is None or patient.body.dead:
                return
            care = hospital.needs_care(patient)
            if not care:
                return
            part_id, treatment = care[0]
            hospital.treat(self, dwarf, patient, part_id, treatment)
        finally:
            self.return_supplies(dwarf, job)

    def return_supplies(self, dwarf, job: Job) -> None:
        """Put down whatever a job had a dwarf carrying, and un-reserve it."""
        if job.carrying is not None:
            self.jobs.release_item(job.carrying)
        for item in list(dwarf.inventory.items):
            if item.id != job.carrying:
                continue
            dwarf.inventory.items.remove(item)
            if item.count > 0:
                self.drop_item(item, dwarf.x, dwarf.y, dwarf.z)
        dwarf.fort.carrying = None

    def _finish_train(self, dwarf, job: Job) -> None:
        """A bout of sparring is over."""
        from . import military as military_mod

        squad = self.military.squad_of(dwarf.id)
        if squad is None:
            return
        for skill in military_mod.TRAINING_SKILLS:
            dwarf.add_exp(skill, 12)
        dwarf.add_exp(squad.defn.skill, 20)
        dwarf.needs.add_thought("trained with the squad", -2)

    def _finish_plant(self, dwarf, job: Job) -> None:
        b = self.building(job.target) if job.target else None
        if b is None:
            return
        seeds = [i for i in self.all_items() if i.def_id == "plump_helmet"]
        if not seeds:
            return
        seeds[0].count -= 1
        if seeds[0].count <= 0:
            self.take_item(seeds[0])
        b.planted = True
        b.growth = 0
        b.crop = "plump_helmet"
        dwarf.add_exp("herbalism", 20)

    def _finish_harvest(self, dwarf, job: Job) -> None:
        b = self.building(job.target) if job.target else None
        if b is None:
            return
        per_tile = 5 + dwarf.skills.level("herbalism") // 2
        yield_n = len(b.cells()) * per_tile
        self.drop_item(Item("plump_helmet", "plant", count=yield_n), *b.center)
        b.planted = False
        b.growth = 0
        for cx, cy, cz in b.cells():
            self.local.set_tile(cx, cy, cz, "farm")
        dwarf.add_exp("herbalism", 40)
        self.log.good("%s has harvested %d plump helmets." % (dwarf.name, yield_n))

    def _reveal_around(self, cell: Cell) -> None:
        """Digging can break into a cavern; nothing to do but note it."""
        x, y, z = cell
        for dx, dy in geometry.DIRS4:
            tid = self.local.tile(x + dx, y + dy, z)
            if tid == "stone_floor":
                self.warn_once(
                    "cavern", "You have broken into a natural cavern.")
                return

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the whole fortress."""
        return {
            "world": self.world.to_dict(),
            "local": self.local.to_dict(),
            "rng": self.rng.to_dict(),
            "name": self.name,
            "wx": self.wx, "wy": self.wy, "z": self.z,
            "time": self.time.to_dict(),
            "log": self.log.to_dict(),
            "weather": self.weather.to_dict(),
            # Held breath. Adventure mode has saved this since v3.29 and the
            # fortress had not, so a fortress save handed everybody drowning
            # in it a fresh lungful.
            "drowning": {str(k): v for k, v in self.drowning.items()},
            "water": self.water.to_dict(),
            "magma": self.magma.to_dict(),
            "fire": self.fire.to_list(),
            "frost": self.frost.to_list(),
            "magma_floor": self.magma_floor,
            "magma_mark": self._magma_mark,
            # Its opposite number was saved and this was not, so every load
            # reset the high-water mark to nothing and the next step compared
            # a river against zero. Any fortress holding more than FLOOD_WARN
            # announced it was flooding the moment it came back.
            "water_mark": self._water_mark,
            "hollow": ["%d,%d,%d" % c for c in self.hollow],
            "breached": self.breached,
            "breach_cell": ("%d,%d,%d" % self.breach_cell
                            if self.breach_cell else ""),
            "aquifer": ["%d,%d,%d" % c for c in self.aquifer],
            "designations": self.designations.to_dict(),
            "jobs": self.jobs.to_dict(),
            "buildings": [b.to_dict() for b in self.buildings],
            "stockpiles": [s.to_dict() for s in self.stockpiles],
            "pastures": [p.to_dict() for p in self.pastures],
            "grazed": {"%d,%d,%d" % c: t for c, t in self.grazed.items()},
            "engravings": {"%d,%d,%d" % c: a.to_dict()
                           for c, a in self.engravings.items()},
            "unburied": {str(k): v for k, v in self.unburied.items()},
            "ghosts": [g.to_dict() for g in self.ghosts.values()],
            "crimes": [c.to_dict() for c in self.crimes],
            "bonds": [b.to_dict() for b in self.bonds.values()],
            "animal_state": {
                str(c.id): c.animal.to_dict()
                for c in self.creatures.values()
                if getattr(c, "animal", None) is not None
            },
            "military": self.military.to_dict(),
            "court": self.court.to_dict(),
            "creatures": [c.to_dict() for c in self.creatures.values()],
            "dwarf_state": {
                str(c.id): c.fort.to_dict()
                for c in self.creatures.values()
                if getattr(c, "fort", None) is not None
            },
            "items": {
                "%d,%d,%d" % cell: [i.to_dict() for i in pile]
                for cell, pile in self.items_on_ground.items() if pile
            },
            "ticks": self.ticks,
            "season_index": self.season_index,
            "year_founded": self.year_founded,
            "lost": self.lost,
            "loss_reason": self.loss_reason,
            "wealth": self.wealth,
            "migrant_waves": self.migrant_waves,
            "siege_count": self.siege_count,
            "civ_id": self.civ_id,
            "siege": self.siege.to_dict() if self.siege is not None else None,
            "artifacts": self.artifacts,
            "caravan": self.caravan,
            "unreachable": {"%d,%d,%d" % c: t
                            for c, t in self.unreachable.items()},
            "warned": sorted(self._warned),
            "next_scan": self._next_scan,
            "next_court": self._next_court,
            "site_id": self.site_id,
            "recorded": self.recorded,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Fortress":
        """Rebuild a fortress from :meth:`to_dict`."""
        return cls.restore(World.from_dict(d["world"]), d)

    @classmethod
    def restore(cls, world: World, d: Mapping[str, Any]) -> "Fortress":
        """Rebuild a fortress into a world that already exists.

        Split out of `from_dict` because a reclaim needs exactly this and
        must not have a *copy* of the world: the site, the legends and the
        artifacts an expedition is walking back into are the ones the rest of
        the game is holding. Everything but `local` and `rng` is optional, so
        a caller with only part of a fortress -- which is all a preserved
        ruin is -- gets empty job boards and an empty court rather than a
        crash.
        """
        local = LocalMap.from_dict(d["local"])
        rng = RNG.from_dict(d["rng"])
        fort = cls(world, local, rng, name=str(d.get("name", "Fortress")),
                   wx=int(d.get("wx", 0)), wy=int(d.get("wy", 0)))
        fort.z = int(d.get("z", 0))
        if d.get("time"):
            # Only when the payload has one. `GameTime.from_dict({})` is the
            # year 0, and `__init__` has already set the clock to the world's
            # own year -- which is what a reclaim wants, and what it silently
            # did not get: its second fall was recorded as happening in year 0.
            fort.time = GameTime.from_dict(d["time"])
        fort.log = MessageLog.from_dict(d.get("log") or {})
        fort.weather = Weather.from_dict(d.get("weather") or {})
        fort.drowning = {
            int(k): int(v) for k, v in (d.get("drowning") or {}).items()
        }
        fort.water = Water.from_dict(d.get("water") or {})
        fort.magma = Magma.from_dict(d.get("magma") or {})
        fort.fire = FireLayer.from_list(d.get("fire") or [])
        fort.frost = Frost.from_list(d.get("frost") or [])
        fort.magma_floor = int(d.get("magma_floor", 0))
        # A payload without them -- an older save, or a preserved ruin -- gets
        # what it is loading with, which is what a high-water mark means. Zero
        # is the wrong answer for both: the magma check has no threshold at
        # all, so a reclaim with a magma sea under it would report the sea
        # itself as a breach on its first step.
        # A payload without them -- an older save, or a preserved ruin -- gets
        # what it is loading with, which is what a high-water mark means. Zero
        # is the wrong answer for both: the magma check has no threshold at
        # all, so a reclaim with a magma sea under it would report the sea
        # itself as a breach on its first step.
        fort._magma_mark = int(d.get("magma_mark", fort.magma.total()))
        fort._water_mark = int(d.get("water_mark", fort.water.total()))
        fort.hollow = {
            tuple(int(v) for v in k.split(",")) for k in d.get("hollow", [])
        }
        fort.breached = bool(d.get("breached", False))
        cell = str(d.get("breach_cell", ""))
        fort.breach_cell = (tuple(int(v) for v in cell.split(","))
                            if cell else None)
        fort.aquifer = {
            tuple(int(v) for v in k.split(",")) for k in d.get("aquifer", [])
        }
        fort.designations = Designations.from_dict(d.get("designations") or {})
        fort.jobs = JobBoard.from_dict(d.get("jobs") or {})
        fort.buildings = [Building.from_dict(b) for b in d.get("buildings", [])]
        fort.stockpiles = [Stockpile.from_dict(s) for s in d.get("stockpiles", [])]
        from . import animals as animal_mod

        fort.pastures = [animal_mod.Pasture.from_dict(p)
                         for p in d.get("pastures", [])]
        fort.grazed = {
            tuple(int(v) for v in k.split(",")): int(t)
            for k, t in (d.get("grazed") or {}).items()
        }
        from . import art as art_mod

        fort.engravings = {
            tuple(int(v) for v in k.split(",")): art_mod.Engraving.from_dict(a)
            for k, a in (d.get("engravings") or {}).items()
        }
        from . import ghosts as ghost_mod

        fort.unburied = {int(k): int(v)
                         for k, v in (d.get("unburied") or {}).items()}
        ghost_mod.from_list(fort, d.get("ghosts") or [])
        from . import justice as justice_mod

        fort.crimes = [justice_mod.Crime.from_dict(c)
                       for c in d.get("crimes", [])]
        from . import social as social_mod

        fort.bonds = {}
        for raw in d.get("bonds", []):
            bond = social_mod.Bond.from_dict(raw)
            fort.bonds[bond.key] = bond
        fort.military = Military.from_dict(d.get("military") or {})
        fort.court = Court.from_dict(d.get("court") or {})

        states = d.get("dwarf_state") or {}
        beasts = d.get("animal_state") or {}
        for cd in d.get("creatures", []):
            c = Creature.from_dict(cd)
            fort.creatures[c.id] = c
            ad = beasts.get(str(c.id))
            if ad is not None:
                c.animal = animal_mod.Animal.from_dict(ad)
            sd = states.get(str(c.id))
            if sd is not None:
                state = dwarf_mod.DwarfState.from_dict(sd)
                c.fort = state
                c.labors = state.labors
                c.job = None
                job_id = sd.get("job")
                if job_id is not None:
                    state.job = fort.jobs.jobs.get(int(job_id))
        fort.items_on_ground = {
            tuple(int(v) for v in k.split(",")): [Item.from_dict(i) for i in pile]
            for k, pile in (d.get("items") or {}).items()
        }
        fort.ticks = int(d.get("ticks", 0))
        fort.season_index = int(d.get("season_index", 0))
        fort.year_founded = int(d.get("year_founded", world.year))
        fort.lost = bool(d.get("lost", False))
        fort.loss_reason = str(d.get("loss_reason", ""))
        fort.wealth = int(d.get("wealth", 0))
        fort.migrant_waves = int(d.get("migrant_waves", 0))
        fort.siege_count = int(d.get("siege_count", 0))
        fort.civ_id = d.get("civ_id")
        siege = d.get("siege")
        if siege:
            from .war import Siege

            fort.siege = Siege.from_dict(siege)
        fort.artifacts = list(d.get("artifacts") or [])
        fort.caravan = d.get("caravan")
        fort.unreachable = {
            tuple(int(v) for v in k.split(",")): int(t)
            for k, t in (d.get("unreachable") or {}).items()
        }
        fort._warned = set(d.get("warned", []))
        fort._next_scan = int(d.get("next_scan", 0))
        fort._next_court = int(d.get("next_court", 0))
        fort.site_id = d.get("site_id")
        fort.recorded = bool(d.get("recorded", False))
        return fort

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Fortress(%s, %d dwarves, %s)" % (
            self.name, len(self.dwarves()), self.time.date_str())
