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
from ..world.localmap import LocalMap
from ..world.worldgen import World
from . import dwarf as dwarf_mod
from . import production
from .buildings import Building, Stockpile
from .designations import KINDS as DESIGNATION_KINDS
from .designations import Designations
from .jobs import Job, JobBoard

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
        self.designations = Designations()
        self.jobs = JobBoard()
        self.buildings: List[Building] = []
        self.stockpiles: List[Stockpile] = []
        self.creatures: Dict[int, Creature] = {}
        self.items_on_ground: Dict[Cell, List[Item]] = {}
        self.weather = Weather()
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
        #: Named objects made in strange moods, for the fortress's own legends.
        self.artifacts: List[Dict[str, Any]] = []
        #: The caravan currently parked outside, if any.
        self.caravan: Optional[Dict[str, Any]] = None
        #: Designated cells nothing can reach, and when to try them again.
        self.unreachable: Dict[Cell, int] = {}
        #: Scratch pathing state for hostiles, rebuilt freely.
        self.hostile_state: Dict[int, Dict[str, Any]] = {}
        self._water_cache: Optional[List[Cell]] = None
        self._warned: Set[str] = set()
        self._next_scan = 0
        self.site_id: Optional[int] = None

    # -- construction ------------------------------------------------------ #

    @classmethod
    def embark(
        cls, world: World, wx: int, wy: int, rng: RNG, *,
        name: str = "", professions: Sequence[str] = (),
    ) -> "Fortress":
        """Generate the map, place the starting seven and their supplies."""
        from ..data import names as name_data
        from ..world import localmap as localmap_mod
        from .labors import STARTING_SEVEN

        old = (localmap_mod.LOCAL_W, localmap_mod.LOCAL_H,
               localmap_mod.Z_BELOW, localmap_mod.Z_ABOVE)
        localmap_mod.LOCAL_W, localmap_mod.LOCAL_H = 80, 60
        localmap_mod.Z_BELOW, localmap_mod.Z_ABOVE = 10, 5
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

        wagon = fort._wagon_site()
        fort.z = wagon[2]
        for i, profession in enumerate(professions or STARTING_SEVEN):
            d = dwarf_mod.make_dwarf(rng, profession)
            spot = fort._free_spot(wagon, i)
            d.x, d.y, d.z = spot
            d.wx, d.wy = wx, wy
            fort.add_creature(d)

        fort._unload_wagon(wagon)
        fort.log.good("%s has been founded." % fort.name)
        fort.log.info("Seven dwarves, and everything they could carry.")
        fort.log.info("Press ? for help. Space starts and stops time.")
        return fort

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
        """A walkable cell close to a point."""
        for radius in range(0, 8):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
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
        self.drop_item(Item("axe", "iron"), *at)

    # -- creatures --------------------------------------------------------- #

    def add_creature(self, c: Creature) -> None:
        """Put a creature on the map."""
        self.creatures[c.id] = c

    def remove_creature(self, c: Creature) -> None:
        """Take a creature off the map."""
        self.creatures.pop(c.id, None)

    def creature_at(self, x: int, y: int, z: int) -> Optional[Creature]:
        """The living creature standing on a cell."""
        for c in self.creatures.values():
            if c.x == x and c.y == y and c.z == z and not c.body.dead:
                return c
        return None

    def dwarves(self) -> List[Creature]:
        """Every living dwarf of the fortress."""
        return [
            c for c in self.creatures.values()
            if getattr(c, "fort", None) is not None and not c.body.dead
        ]

    def hostiles(self) -> List[Creature]:
        """Every living enemy on the map."""
        return [
            c for c in self.creatures.values()
            if c.faction == "hostile" and not c.body.dead
        ]

    def kill_creature(self, c: Creature) -> None:
        """Handle a death: corpse, dropped goods, and the loss of a dwarf."""
        if not c.alive:
            return
        c.alive = False
        c.body.dead = True
        state = getattr(c, "fort", None)
        if state is not None:
            self.log.bad("%s has died: %s." % (
                c.name, c.body.death_cause or "slain"))
            if state.job is not None:
                self.abandon_job(c, state.job)
            self.designations.release_all(c.id)
            self.jobs.release_all(c.id)
            for other in self.dwarves():
                other.needs.add_thought("lost a friend to a violent death", 18)
        else:
            self.log.combat("The %s is dead." % c.short_name())
        self.drop_item(corpse_of(c), c.x, c.y, c.z)
        for item in c.inventory.remove_all():
            self.drop_item(item, c.x, c.y, c.z)

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
        return self.local.walkable(x, y, z)

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
        if job.kind == "haul":
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
        """Un-reserve everything a cancelled job had promised itself."""
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
        if job.kind == "haul":
            return [job.target] if job.target else []
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
            if not dwarf_mod.at_or_beside(dwarf, cell):
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

    def _stone_here(self, cell: Cell) -> str:
        """Which stone a wall at this cell is made of."""
        tid = self.local.tile(*cell)
        if tid == "ore_vein":
            return self.rng.choice(["copper", "iron", "silver", "gold"])
        if tid == "gem_vein":
            return self.rng.choice(
                ["ruby", "sapphire", "emerald", "amethyst", "topaz", "diamond"])
        if tid == "soil_wall":
            return ""
        return self.local.stone

    def _finish_dig(self, dwarf, job: Job) -> None:
        cell = job.cell
        material = self._stone_here(cell)
        self.local.set_tile(cell[0], cell[1], cell[2], "floor")
        if material:
            boulder = Item("boulder", material)
            self.drop_item(boulder, *cell)
            if material in ("ruby", "sapphire", "emerald", "amethyst", "topaz",
                            "diamond"):
                self.log.good("%s has struck %s!" % (dwarf.name, material))
                dwarf.needs.add_thought("struck a rich vein", -10)
        self._reveal_around(cell)

    def _finish_channel(self, dwarf, job: Job) -> None:
        cell = job.cell
        material = self._stone_here(cell)
        self.local.set_tile(cell[0], cell[1], cell[2], "air")
        below = (cell[0], cell[1], cell[2] - 1)
        if self.local.in_bounds(*below):
            self.local.set_tile(below[0], below[1], below[2], "ramp_up")
            if material:
                self.drop_item(Item("boulder", material), *below)
        self._reveal_around(cell)

    def _finish_stairs(self, dwarf, job: Job) -> None:
        cell = job.cell
        material = self._stone_here(cell)
        self.local.set_tile(cell[0], cell[1], cell[2], "stair_updown")
        if material:
            self.drop_item(Item("boulder", material), *cell)
        self._reveal_around(cell)

    def _finish_ramp(self, dwarf, job: Job) -> None:
        cell = job.cell
        material = self._stone_here(cell)
        self.local.set_tile(cell[0], cell[1], cell[2], "ramp_up")
        if material:
            self.drop_item(Item("boulder", material), *cell)
        self._reveal_around(cell)

    def _finish_smooth(self, dwarf, job: Job) -> None:
        cell = job.cell
        self.local.set_tile(cell[0], cell[1], cell[2], "wall_constructed")
        dwarf.needs.add_thought("admired a smoothed wall", -1)

    def _finish_chop(self, dwarf, job: Job) -> None:
        cell = job.cell
        self.local.set_tile(cell[0], cell[1], cell[2], "grass")
        above = (cell[0], cell[1], cell[2] + 1)
        if self.local.in_bounds(*above) and self.local.tile(*above) == "tree":
            self.local.set_tile(above[0], above[1], above[2], "air")
        self.drop_item(Item("log", self.rng.choice(["oak", "pine", "willow"])),
                       *cell)

    def _finish_gather(self, dwarf, job: Job) -> None:
        cell = job.cell
        self.local.set_tile(cell[0], cell[1], cell[2], "grass")
        self.drop_item(Item("plump_helmet", "plant",
                            count=self.rng.randint(2, 5)), *cell)

    def _finish_remove(self, dwarf, job: Job) -> None:
        cell = job.cell
        self.local.set_tile(cell[0], cell[1], cell[2], "floor")
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
        for cx, cy, cz in b.cells():
            self.local.set_tile(cx, cy, cz, b.defn.tile)
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
        level = dwarf.skills.level(recipe.skill)
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
            "designations": self.designations.to_dict(),
            "jobs": self.jobs.to_dict(),
            "buildings": [b.to_dict() for b in self.buildings],
            "stockpiles": [s.to_dict() for s in self.stockpiles],
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
            "artifacts": self.artifacts,
            "caravan": self.caravan,
            "unreachable": {"%d,%d,%d" % c: t
                            for c, t in self.unreachable.items()},
            "warned": sorted(self._warned),
            "next_scan": self._next_scan,
            "site_id": self.site_id,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Fortress":
        """Rebuild a fortress from :meth:`to_dict`."""
        world = World.from_dict(d["world"])
        local = LocalMap.from_dict(d["local"])
        rng = RNG.from_dict(d["rng"])
        fort = cls(world, local, rng, name=str(d.get("name", "Fortress")),
                   wx=int(d.get("wx", 0)), wy=int(d.get("wy", 0)))
        fort.z = int(d.get("z", 0))
        fort.time = GameTime.from_dict(d.get("time") or {})
        fort.log = MessageLog.from_dict(d.get("log") or {})
        fort.weather = Weather.from_dict(d.get("weather") or {})
        fort.designations = Designations.from_dict(d.get("designations") or {})
        fort.jobs = JobBoard.from_dict(d.get("jobs") or {})
        fort.buildings = [Building.from_dict(b) for b in d.get("buildings", [])]
        fort.stockpiles = [Stockpile.from_dict(s) for s in d.get("stockpiles", [])]

        states = d.get("dwarf_state") or {}
        for cd in d.get("creatures", []):
            c = Creature.from_dict(cd)
            fort.creatures[c.id] = c
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
        fort.artifacts = list(d.get("artifacts") or [])
        fort.caravan = d.get("caravan")
        fort.unreachable = {
            tuple(int(v) for v in k.split(",")): int(t)
            for k, t in (d.get("unreachable") or {}).items()
        }
        fort._warned = set(d.get("warned", []))
        fort._next_scan = int(d.get("next_scan", 0))
        fort.site_id = d.get("site_id")
        return fort

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Fortress(%s, %d dwarves, %s)" % (
            self.name, len(self.dwarves()), self.time.date_str())
