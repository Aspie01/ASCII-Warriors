"""Fortress mode: embark, jobs, dwarves, production and the end of it all."""

from __future__ import annotations

import unittest

from ascii_warriors.data.calendar import TICKS_PER_DAY
from ascii_warriors.engine.rng import RNG
from ascii_warriors.fortress import buildings as building_mod
from ascii_warriors.fortress import designations as designation_mod
from ascii_warriors.fortress import dwarf as dwarf_mod
from ascii_warriors.fortress import labors, production, sim
from ascii_warriors.fortress.buildings import Building, Stockpile
from ascii_warriors.fortress.fortress import Fortress
from ascii_warriors.fortress.jobs import Job, JobBoard, work_rate
from ascii_warriors.game import save as save_mod
from ascii_warriors.world.worldgen import generate_world

#: One small world, generated once, shared by every test in this file.
_WORLD = None


def world():
    """A small world with a little history behind it."""
    global _WORLD
    if _WORLD is None:
        _WORLD = generate_world(RNG("fortress-tests"), size="pocket",
                                history_years=15)
    return _WORLD


def embark(seed: str = "fort") -> Fortress:
    """Found a test fortress on the most promising square."""
    from ascii_warriors.ui.fort.embark import suggest_site

    w = world()
    x, y = suggest_site(w)
    return Fortress.embark(w, x, y, RNG(seed))


def _open_spot(fort, kind: str):
    """Somewhere near the dwarves a building of this kind would fit."""
    d = fort.dwarves()[0]
    for radius in range(1, 16):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                x, y = d.x + dx, d.y + dy
                ok, _why = building_mod.can_place(fort.local, kind, x, y, d.z,
                                                  fort.buildings)
                if ok:
                    return (x, y, d.z)
    return None


def dig_room(fort, radius: int = 6) -> int:
    """Designate a block of digging around the dwarves."""
    d = fort.dwarves()[0]
    total = 0
    for z in (fort.z, fort.z - 1):
        total += fort.designations.paint_rect(
            fort.local, d.x - radius, d.y - radius, d.x + radius,
            d.y + radius, z, "dig")
    return total


class TestLabors(unittest.TestCase):
    """Labor sets and profession titles."""

    def test_defaults_cover_the_dull_work(self):
        """Everybody hauls, whatever else they do."""
        labs = labors.LaborSet()
        self.assertTrue(labs.has("hauling"))
        self.assertFalse(labs.has("mining"))

    def test_profession_adds_labors(self):
        """A miner mines."""
        labs = labors.labors_for_profession("miner")
        self.assertTrue(labs.has("mining"))
        self.assertTrue(labs.has("hauling"))

    def test_empty_labor_matches_everything(self):
        """Jobs with no labor requirement are open to all."""
        self.assertTrue(labors.LaborSet().has(""))

    def test_toggle_round_trip(self):
        """Toggling twice returns to where it started."""
        labs = labors.LaborSet()
        before = labs.has("mining")
        labs.toggle("mining")
        labs.toggle("mining")
        self.assertEqual(labs.has("mining"), before)

    def test_serialisation(self):
        """Labor sets survive a round trip."""
        labs = labors.LaborSet()
        labs.enable("mining")
        again = labors.LaborSet.from_list(labs.to_list())
        self.assertEqual(again.enabled, labs.enabled)

    def test_title_follows_the_best_skill(self):
        """A dwarf is named for what it is best at."""
        d = dwarf_mod.make_dwarf(RNG("t"), "miner")
        self.assertIn("Miner", labors.profession_title(d))

    def test_every_labor_has_a_known_category(self):
        """The labor screen groups by category and must not drop rows."""
        for lab in labors.LABORS.values():
            self.assertIn(lab.category, labors.CATEGORIES)


class TestJobBoard(unittest.TestCase):
    """Posting, claiming and releasing work."""

    def setUp(self):
        self.board = JobBoard()

    def test_post_assigns_an_id(self):
        """Every job gets a unique id."""
        a = self.board.make("dig", 1, 2, 3)
        b = self.board.make("dig", 4, 5, 6)
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(len(self.board), 2)

    def test_no_duplicate_cells(self):
        """The board can tell you a cell is already covered."""
        self.board.make("dig", 1, 2, 3)
        self.assertTrue(self.board.has_job_at("dig", (1, 2, 3)))
        self.assertFalse(self.board.has_job_at("chop", (1, 2, 3)))

    def test_remove_frees_the_cell(self):
        """A removed job stops covering its cell."""
        job = self.board.make("dig", 1, 2, 3)
        self.board.remove(job)
        self.assertFalse(self.board.has_job_at("dig", (1, 2, 3)))

    def test_item_reservations_are_exclusive(self):
        """Two jobs cannot claim the same rock."""
        a = self.board.make("haul", 0, 0, 0)
        b = self.board.make("haul", 1, 0, 0)
        self.assertTrue(self.board.reserve_item(7, a))
        self.assertFalse(self.board.reserve_item(7, b))
        self.board.remove(a)
        self.assertTrue(self.board.reserve_item(7, b))

    def test_priority_orders_the_queue(self):
        """Urgent work comes first."""
        self.board.make("haul", 0, 0, 0, priority=1)
        urgent = self.board.make("dig", 0, 0, 0, priority=9)
        self.assertEqual(self.board.unassigned()[0].id, urgent.id)

    def test_serialisation_round_trip(self):
        """The board survives a save."""
        job = self.board.make("dig", 1, 2, 3, labor="mining", work=90)
        self.board.reserve_item(4, job)
        again = JobBoard.from_dict(self.board.to_dict())
        self.assertEqual(len(again), 1)
        self.assertTrue(again.has_job_at("dig", (1, 2, 3)))
        self.assertTrue(again.is_reserved(4))


class TestDesignations(unittest.TestCase):
    """Painting orders onto the map."""

    def setUp(self):
        self.fort = embark("designations")

    def test_dig_only_applies_to_walls(self):
        """You cannot mine thin air."""
        lm = self.fort.local
        d = self.fort.dwarves()[0]
        self.assertFalse(self.fort.designations.valid(lm, d.x, d.y, d.z, "dig"))

    def test_paint_and_clear(self):
        """A painted rectangle can be erased again."""
        painted = dig_room(self.fort, 5)
        self.assertGreater(painted, 0)
        d = self.fort.dwarves()[0]
        self.fort.designations.clear_rect(d.x - 5, d.y - 5, d.x + 5, d.y + 5,
                                          self.fort.z - 1)
        remaining = [c for c in self.fort.designations.cells
                     if c[2] == self.fort.z - 1]
        self.assertEqual(remaining, [])

    def test_claims_are_exclusive(self):
        """Two miners cannot claim one wall."""
        dig_room(self.fort, 5)
        cell = next(iter(self.fort.designations.cells))
        self.assertTrue(self.fort.designations.claim(cell, 1))
        self.assertFalse(self.fort.designations.claim(cell, 2))
        self.fort.designations.release_all(1)
        self.assertTrue(self.fort.designations.claim(cell, 2))

    def test_every_kind_renders(self):
        """The overlay needs a glyph for each designation."""
        for kind in designation_mod.KINDS:
            glyph, colour = designation_mod.render(kind)
            self.assertTrue(glyph)
            self.assertIsNotNone(colour)


class TestEmbark(unittest.TestCase):
    """What you get when the wagon stops."""

    @classmethod
    def setUpClass(cls):
        cls.fort = embark("embark")

    def test_seven_dwarves(self):
        """The starting seven, with the professions to run a fortress."""
        dwarves = self.fort.dwarves()
        self.assertEqual(len(dwarves), 7)
        professions = {d.profession for d in dwarves}
        self.assertIn("miner", professions)
        self.assertIn("farmer", professions)

    def test_dwarves_stand_on_solid_ground(self):
        """Nobody starts inside a wall."""
        for d in self.fort.dwarves():
            self.assertTrue(self.fort.local.walkable(d.x, d.y, d.z),
                            "%s is inside a wall" % d.name)

    def test_wagon_stops_outside(self):
        """Migrants and caravans need somewhere to arrive from."""
        d = self.fort.dwarves()[0]
        self.assertTrue(self.fort.local.is_outside(d.x, d.y, d.z))

    def test_supplies_are_on_the_ground(self):
        """Food, drink, wood and two picks."""
        self.assertGreater(self.fort.stock_count("dwarven_ale"), 50)
        self.assertGreater(self.fort.stock_count("plump_helmet"), 50)
        self.assertGreater(self.fort.stock_count("log"), 5)

    def test_supplies_last_the_first_fortnight(self):
        """Seven dwarves must not starve before a farm can produce."""
        heads = len(self.fort.dwarves())
        drink_days = self.fort.stock_count("dwarven_ale") / float(heads)
        food_days = self.fort.stock_count(
            "plump_helmet", "meat") / float(heads)
        self.assertGreater(drink_days, 14)
        self.assertGreater(food_days, 14)

    def test_everybody_can_reach_everybody(self):
        """A dwarf walled off from the wagon is a dead dwarf."""
        dwarves = self.fort.dwarves()
        first = dwarves[0]
        for other in dwarves[1:]:
            self.assertTrue(
                dwarf_mod.path_to(self.fort, other,
                                  (first.x, first.y, first.z)),
                "%s cannot reach %s" % (other.name, first.name))


class TestMovement(unittest.TestCase):
    """Pathing, reach and the traffic jams they cause."""

    def setUp(self):
        self.fort = embark("movement")

    def test_reach_matches_pathing_targets(self):
        """Anywhere you can path to must count as arriving.

        When these disagree a dwarf walks on the spot until it dies.
        """
        lm = self.fort.local
        d = self.fort.dwarves()[0]
        goal = (d.x, d.y, d.z - 1)
        for cell in dwarf_mod.work_positions(lm, goal):
            probe = type("Probe", (), {"x": cell[0], "y": cell[1],
                                       "z": cell[2]})()
            self.assertTrue(dwarf_mod.at_or_beside(probe, goal),
                            "%s can be pathed to but is not 'beside' %s"
                            % (cell, goal))

    def test_movement_graph_is_symmetric(self):
        """If you can walk from A to B you can walk back.

        A one-way edge is a trapdoor: A* routes through it and whoever took
        it is stranded.
        """
        lm = self.fort.local
        checked = 0
        for z in lm.levels:
            for y in range(0, lm.height, 5):
                for x in range(0, lm.width, 5):
                    if not lm.walkable(x, y, z):
                        continue
                    for n in lm.neighbours(x, y, z):
                        checked += 1
                        self.assertIn(
                            (x, y, z), set(lm.neighbours(*n)),
                            "%s -> %s is one way" % ((x, y, z), n))
        self.assertGreater(checked, 100)

    def test_a_crowd_at_one_barrel_does_not_gridlock(self):
        """Seven thirsty dwarves and one barrel of ale.

        This used to deadlock: everybody waited politely for the dwarf in
        front, and the whole fortress died of thirst two tiles from a drink.
        """
        fort = self.fort
        for d in fort.dwarves():
            d.needs.thirst = 12000
        sim.run(fort, 400)
        for d in fort.dwarves():
            self.assertLess(d.needs.thirst, 12000,
                            "%s never got a drink" % d.name)


class TestSimulation(unittest.TestCase):
    """The loop that runs the place."""

    def test_time_advances(self):
        """Steps move the clock."""
        fort = embark("time")
        before = fort.time.ticks
        sim.run(fort, 50)
        self.assertEqual(fort.time.ticks - before, 50 * sim.STEP_TICKS)

    def test_designations_become_jobs(self):
        """Painting is not digging until the scan turns it into work."""
        fort = embark("jobs")
        dig_room(fort, 5)
        self.assertEqual(len(fort.jobs), 0)
        sim.scan_jobs(fort)
        self.assertGreater(fort.jobs.count("dig"), 0)

    def test_only_miners_are_offered_mining(self):
        """Labors gate the job board."""
        fort = embark("labor-gate")
        dig_room(fort, 5)
        sim.scan_jobs(fort)
        for d in fort.dwarves():
            if d.fort.labors.has("mining"):
                continue
            for job in fort.jobs.for_dwarf(d):
                self.assertNotEqual(job.kind, "dig")

    def test_digging_removes_walls(self):
        """Given time, a designated block becomes a room."""
        fort = embark("digging")
        painted = dig_room(fort, 5)
        self.assertGreater(painted, 0)
        sim.run(fort, 2500)
        self.assertLess(len(fort.designations), painted,
                        "no digging happened at all")

    def test_embark_supplies_last_a_fortnight(self):
        """Doing nothing at all should still buy you two weeks."""
        fort = embark("survival")
        dig_room(fort, 6)
        sim.run(fort, int(TICKS_PER_DAY * 14 / sim.STEP_TICKS))
        self.assertFalse(fort.lost, "the fortress fell: %s" % fort.loss_reason)
        self.assertEqual(len(fort.dwarves()), 7)

    def test_a_farming_fortress_survives_a_season(self):
        """Food in, drink out: the economy has to actually close.

        A farm feeding a still is the whole loop fortress mode is built on.
        If it does not sustain seven dwarves, nothing else matters.
        """
        fort = embark("economy")
        d = fort.dwarves()[0]
        placed = 0
        for kind in ("farm", "farm", "still"):
            spot = _open_spot(fort, kind)
            if spot is None:
                continue
            fort.buildings.append(Building(kind, *spot))
            placed += 1
        self.assertEqual(placed, 3, "nowhere to put the farms and the still")
        sim.run(fort, 600)
        still = next(b for b in fort.buildings if b.kind == "still")
        self.assertTrue(still.built, "the still was never finished")
        still.orders.append({"recipe": "brew_ale", "count": 1, "repeat": True})
        sim.run(fort, int(TICKS_PER_DAY * 90 / sim.STEP_TICKS))
        self.assertFalse(fort.lost, "the fortress fell: %s" % fort.loss_reason)
        self.assertGreaterEqual(len(fort.dwarves()), 7)
        self.assertGreater(fort.stock_count("plump_helmet"), 0,
                           "the farms never kept up")

    def test_losing_is_recorded(self):
        """When the last dwarf dies the fortress falls, and history says so."""
        fort = embark("losing")
        events_before = len(fort.world.events)
        for d in list(fort.dwarves()):
            d.body.dead = True
            d.body.death_cause = "test"
        sim.step(fort)
        self.assertTrue(fort.lost)
        self.assertGreater(len(fort.world.events), events_before)

    def test_stress_fades(self):
        """A dwarf that had one good day does not stay ecstatic for ever."""
        fort = embark("stress")
        d = fort.dwarves()[0]
        d.needs.add_thought("something wonderful", -100)
        start = d.needs.stress
        sim.run(fort, 400)
        self.assertGreater(d.needs.stress, start)

    def test_unconscious_creatures_sleep_it_off(self):
        """Collapsing from exhaustion must not be a permanent coma."""
        fort = embark("coma")
        d = fort.dwarves()[0]
        d.needs.drowsy = 40000
        d.body.unconscious = 500
        d.needs.tick(200, d, fort)
        self.assertLess(d.needs.drowsy, 40000)


class TestBuildings(unittest.TestCase):
    """Putting things up and using them."""

    def setUp(self):
        self.fort = embark("buildings")

    def _flat_spot(self):
        """Open ground the dwarves can reach."""
        d = self.fort.dwarves()[0]
        for radius in range(1, 12):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    x, y = d.x + dx, d.y + dy
                    ok, _why = building_mod.can_place(
                        self.fort.local, "carpenter", x, y, d.z,
                        self.fort.buildings)
                    if ok:
                        return (x, y, d.z)
        self.fail("nowhere to build")

    def test_every_building_kind_is_coherent(self):
        """Definitions must not point at tiles or labors that do not exist."""
        from ascii_warriors.world import tiles as tile_data

        for k in building_mod.KINDS.values():
            self.assertTrue(tile_data.exists(k.tile), k.id)
            self.assertIn(k.labor, labors.LABORS, k.id)
            self.assertIn(k.category, building_mod.BUILD_CATEGORIES, k.id)

    def test_building_gets_built(self):
        """A planned workshop becomes a real one."""
        x, y, z = self._flat_spot()
        shop = Building("carpenter", x, y, z)
        self.fort.buildings.append(shop)
        sim.run(self.fort, 900)
        self.assertTrue(shop.built, "the carpenter's workshop was never built")

    def test_building_consumes_its_material(self):
        """Wood goes in, workshop comes out."""
        wood_before = self.fort.stock_count("log")
        x, y, z = self._flat_spot()
        self.fort.buildings.append(Building("carpenter", x, y, z))
        sim.run(self.fort, 900)
        self.assertLess(self.fort.stock_count("log"), wood_before)

    def test_workshop_produces(self):
        """An order at a built workshop yields an item."""
        x, y, z = self._flat_spot()
        shop = Building("carpenter", x, y, z)
        self.fort.buildings.append(shop)
        sim.run(self.fort, 900)
        self.assertTrue(shop.built)
        shop.orders.append({"recipe": "wood_bed", "count": 1})
        beds_before = self.fort.stock_count("bed")
        sim.run(self.fort, 900)
        self.assertGreater(self.fort.stock_count("bed"), beds_before)

    def test_repeat_orders_survive_a_shortage(self):
        """A standing order outlives one missing input."""
        x, y, z = self._flat_spot()
        shop = Building("still", x, y, z)
        shop.built = True
        self.fort.buildings.append(shop)
        shop.orders.append({"recipe": "brew_ale", "count": 1, "repeat": True})
        # Take every plant away, so the order cannot possibly be filled.
        for pile in list(self.fort.items_on_ground.values()):
            for item in list(pile):
                if item.def_id == "plump_helmet":
                    self.fort.take_item(item)
        d = self.fort.dwarves()[0]
        job = self.fort.jobs.make("craft", *shop.center, target=shop.id)
        self.fort.complete_job(d, job)
        self.assertEqual(len(shop.orders), 1, "the standing order was lost")

    def test_stockpile_accepts_the_right_things(self):
        """A food pile takes food and refuses rocks."""
        from ascii_warriors.game.item import Item

        pile = Stockpile("food", 0, 0, 0, 3, 3)
        self.assertTrue(pile.accepts(Item("plump_helmet", "plant")))
        self.assertFalse(pile.accepts(Item("boulder", "granite")))

    def test_hauling_moves_goods_into_a_pile(self):
        """Loose goods end up where you asked for them."""
        fort = self.fort
        d = fort.dwarves()[0]
        pile = Stockpile("all", d.x + 3, d.y + 3, d.z, 4, 4)
        fort.stockpiles.append(pile)
        cells = set(pile.cells())
        before = sum(len(fort.items_on_ground.get(c, ())) for c in cells)
        sim.run(fort, 1200)
        after = sum(len(fort.items_on_ground.get(c, ())) for c in cells)
        self.assertGreater(after, before, "nothing was ever hauled")


class TestFarming(unittest.TestCase):
    """Plump helmets, and whether they arrive in time."""

    def test_farm_grows_and_is_harvested(self):
        """Plant, wait, harvest, replant."""
        fort = embark("farming")
        d = fort.dwarves()[0]
        spot = None
        for radius in range(1, 12):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    ok, _why = building_mod.can_place(
                        fort.local, "farm", d.x + dx, d.y + dy, d.z,
                        fort.buildings)
                    if ok:
                        spot = (d.x + dx, d.y + dy, d.z)
                        break
                if spot:
                    break
            if spot:
                break
        self.assertIsNotNone(spot, "nowhere to farm")
        farm = Building("farm", *spot)
        fort.buildings.append(farm)
        sim.run(fort, 400)
        self.assertTrue(farm.built)
        sim.run(fort, int(TICKS_PER_DAY * 9 / sim.STEP_TICKS))
        self.assertTrue(
            any("harvested" in m.text for m in fort.log.all()),
            "the farm never produced anything")

    def test_seed_corn_is_protected(self):
        """A fortress with a farm will not eat its last mushrooms."""
        fort = embark("seeds")
        d = fort.dwarves()[0]
        fort.buildings.append(Building("farm", d.x, d.y, d.z))
        for pile in list(fort.items_on_ground.values()):
            for item in list(pile):
                if item.def_id == "plump_helmet":
                    item.count = 3
        d.needs.hunger = 99999
        found = fort.find_consumable(d, drink=False)
        self.assertTrue(found is None or found.def_id != "plump_helmet")


class TestProduction(unittest.TestCase):
    """Recipes and what comes out of them."""

    def test_every_recipe_is_makeable(self):
        """Recipes must name real workshops, skills and items."""
        from ascii_warriors.data import items as item_data
        from ascii_warriors.game import skills as skill_mod

        for recipe in production.RECIPES.values():
            self.assertIn(recipe.workshop, building_mod.KINDS, recipe.id)
            self.assertTrue(skill_mod.exists(recipe.skill), recipe.id)
            self.assertTrue(item_data.exists(recipe.output),
                            "%s makes a nonexistent %s"
                            % (recipe.id, recipe.output))
            for requirement, count in recipe.inputs:
                self.assertGreater(count, 0, recipe.id)
                if requirement in production.CLASS_ITEMS:
                    continue
                self.assertTrue(item_data.exists(requirement),
                                "%s needs a nonexistent %s"
                                % (recipe.id, requirement))

    def test_every_workshop_can_make_something(self):
        """A workshop with no recipes is a trap for the player."""
        for kind in building_mod.WORKSHOP_KINDS:
            self.assertTrue(production.recipes_for(kind), kind)

    def test_find_inputs_reports_shortages(self):
        """Not enough wood means no bed."""
        from ascii_warriors.game.item import Item

        recipe = production.RECIPES["wood_bed"]
        self.assertIsNone(production.find_inputs(recipe, []))
        self.assertIsNotNone(
            production.find_inputs(recipe, [Item("log", "oak", count=2)]))

    def test_output_material_follows_the_input(self):
        """A bed made of oak is an oak bed."""
        from ascii_warriors.game.item import Item

        recipe = production.RECIPES["wood_bed"]
        log = Item("log", "oak")
        self.assertEqual(production.output_material(recipe, [(log, 1)]), "oak")


class TestWorkRate(unittest.TestCase):
    """How fast work goes, and how fast skill follows."""

    def test_skill_helps(self):
        """A skilled dwarf works faster than a novice."""
        novice = dwarf_mod.make_dwarf(RNG("a"), "")
        expert = dwarf_mod.make_dwarf(RNG("a"), "")
        expert.skills.set_level("mining", 15)
        job = Job(1, "dig", 0, 0, 0, skill="mining")
        self.assertGreater(work_rate(expert, job), work_rate(novice, job))

    def test_a_job_takes_roughly_its_work_value_in_ticks(self):
        """``work`` should read as "about this many ticks of labour"."""
        d = dwarf_mod.make_dwarf(RNG("a"), "miner")
        job = Job(1, "dig", 0, 0, 0, skill="mining", work=90)
        rate = work_rate(d, job)
        ticks = 90 * 100 / float(rate)
        self.assertGreater(ticks, 20)
        self.assertLess(ticks, 400)


class TestSaveLoad(unittest.TestCase):
    """Fortresses survive being written to disk."""

    def test_round_trip(self):
        """Everything that matters comes back."""
        fort = embark("save")
        dig_room(fort, 5)
        d = fort.dwarves()[0]
        fort.stockpiles.append(Stockpile("all", d.x + 3, d.y + 3, d.z, 3, 3))
        fort.buildings.append(Building("carpenter", d.x - 5, d.y - 5, d.z))
        sim.run(fort, 400)

        again = Fortress.from_dict(fort.to_dict())
        self.assertEqual(again.name, fort.name)
        self.assertEqual(len(again.dwarves()), len(fort.dwarves()))
        self.assertEqual(len(again.designations), len(fort.designations))
        self.assertEqual(len(again.jobs), len(fort.jobs))
        self.assertEqual(len(again.buildings), len(fort.buildings))
        self.assertEqual(len(again.stockpiles), len(fort.stockpiles))
        self.assertEqual(again.time.ticks, fort.time.ticks)
        self.assertEqual(again.stock_count("dwarven_ale"),
                         fort.stock_count("dwarven_ale"))

    def test_a_loaded_fortress_keeps_working(self):
        """Dwarves pick their jobs back up after a load."""
        fort = embark("resume")
        d = fort.dwarves()[0]
        painted = 0
        for z in (fort.z - 2, fort.z - 3):
            painted += fort.designations.paint_rect(
                fort.local, d.x - 9, d.y - 9, d.x + 9, d.y + 9, z, "dig")
        self.assertGreater(painted, 50)
        sim.run(fort, 200)
        again = Fortress.from_dict(fort.to_dict())
        before = len(again.designations)
        self.assertGreater(before, 0)
        sim.run(again, 1200)
        self.assertLess(len(again.designations), before)

    def test_dwarf_state_survives(self):
        """Labors, nicknames and beds are not lost in the save."""
        fort = embark("dwarfstate")
        d = fort.dwarves()[0]
        d.fort.nickname = "Urist"
        d.fort.labors.enable("mining")
        again = Fortress.from_dict(fort.to_dict())
        same = again.creatures[d.id]
        self.assertEqual(same.fort.nickname, "Urist")
        self.assertTrue(same.fort.labors.has("mining"))

    def test_save_file_round_trip(self):
        """Through the real save path, gzip and all."""
        import tempfile

        fort = embark("savefile")
        with tempfile.TemporaryDirectory() as tmp:
            import os

            old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = tmp
            try:
                path = save_mod.save_fortress(fort)
                self.assertTrue(path.exists())
                listed = save_mod.list_fortresses()
                self.assertEqual(len(listed), 1)
                loaded = save_mod.load_fortress(path)
                self.assertEqual(loaded.name, fort.name)
            finally:
                if old is None:
                    del os.environ["ASCII_WARRIORS_SAVE_DIR"]
                else:
                    os.environ["ASCII_WARRIORS_SAVE_DIR"] = old


class TestEvents(unittest.TestCase):
    """Migrants, sieges, moods and caravans."""

    def test_migrants_arrive_and_can_work(self):
        """A wave lands on walkable ground with labors enabled."""
        fort = embark("migrants")
        before = len(fort.dwarves())
        arrivals = sim.migrants(fort, 4)
        self.assertEqual(len(arrivals), 4)
        self.assertEqual(len(fort.dwarves()), before + 4)
        for d in arrivals:
            self.assertTrue(fort.local.walkable(d.x, d.y, d.z))
            self.assertIsNotNone(getattr(d, "fort", None))

    def test_attackers_are_hostile(self):
        """A siege spawns enemies, not more dwarves."""
        fort = embark("siege")
        attackers = sim.spawn_attack(fort, 3)
        self.assertEqual(len(attackers), 3)
        self.assertEqual(len(fort.hostiles()), 3)
        for foe in attackers:
            self.assertTrue(fort.local.walkable(foe.x, foe.y, foe.z))

    def test_hostiles_close_on_dwarves(self):
        """Enemies must actually come for you."""
        fort = embark("hostiles")
        foe = sim.spawn_attack(fort, 1)[0]
        target = fort.dwarves()[0]
        from ascii_warriors.engine import geometry

        start = geometry.chebyshev(foe.x, foe.y, target.x, target.y)
        for _ in range(200):
            sim._hostiles(fort, sim.STEP_TICKS)
        now = geometry.chebyshev(foe.x, foe.y, target.x, target.y)
        self.assertLess(now, start, "the goblin never moved towards anybody")

    def test_a_mood_makes_an_artifact(self):
        """The dwarf comes out of it holding something legendary."""
        fort = embark("mood")
        d = fort.dwarves()[0]
        shop = Building("craftsdwarf", d.x, d.y, d.z)
        shop.built = True
        fort.buildings.append(shop)
        d.fort.mood = "craftsdwarf"
        d.fort.workshop = shop.id
        d.fort.mood_ticks = 1
        sim._moods(fort, 10)
        self.assertEqual(len(fort.artifacts), 1)
        self.assertEqual(d.fort.mood, "")

    def test_caravan_brings_goods(self):
        """Autumn brings somebody to trade with."""
        fort = embark("caravan")
        sim._caravan(fort)
        self.assertIsNotNone(fort.caravan)
        self.assertGreater(len(fort.caravan["goods"]), 0)

    def test_wealth_counts_what_you_own(self):
        """Appraisal is not zero for a fortress with a full wagon."""
        fort = embark("wealth")
        self.assertGreater(sim.appraise(fort), 0)


class TestFortressUI(unittest.TestCase):
    """The screens, driven headlessly."""

    def test_no_command_key_is_shadowed_by_scrolling(self):
        """A command bound to a scroll key can never fire."""
        from ascii_warriors.ui.fort import fort_screen

        commands = set("dbpujzotk?+-<>")
        for key in commands:
            self.assertIsNone(fort_screen.scroll_delta(key),
                              "%r scrolls the map and cannot be a command" % key)

    def test_designation_keys_do_not_scroll(self):
        """Same for the designation submenu."""
        from ascii_warriors.ui.fort import designate, fort_screen

        for key, _kind in designate.BINDINGS:
            self.assertIsNone(fort_screen.scroll_delta(key), key)
        self.assertIsNone(fort_screen.scroll_delta("x"))

    def test_map_renders_without_crashing(self):
        """Draw the whole fortress view into a buffer."""
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.ui.fort import render

        fort = embark("render")
        scr = Screen(100, 34)
        render.draw_map(scr, fort, 0, 1, 66, 26, 0, 0,
                        cursor=(10, 10, fort.z),
                        region=(4, 4, 9, 9), ghost=("C", 12, 12, 3, 3))
        text = scr.to_text()
        self.assertEqual(len(text), 34)

    def test_every_screen_cell_holds_a_colour(self):
        """A stray string in the colour buffer crashes the renderer later."""
        from ascii_warriors.engine.colors import Color
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.ui.fort import render
        from ascii_warriors.ui.fort.sidebar import draw_log, draw_sidebar
        from ascii_warriors.ui.fort.sidebar import draw_status_line

        fort = embark("colours")
        scr = Screen(100, 34)
        draw_status_line(scr, 0, 0, 100, fort, "Designate")
        render.draw_map(scr, fort, 0, 1, 66, 26, 0, 0)
        draw_sidebar(scr, 69, 1, 31, 26, fort)
        draw_log(scr, 0, 27, 100, 7, fort)
        for buffer in (scr.fgs, scr.bgs):
            for value in buffer:
                self.assertIsInstance(value, Color)

    def test_embark_suggestion_is_habitable(self):
        """The suggested site must not be underwater or occupied."""
        from ascii_warriors.ui.fort.embark import suggest_site

        w = world()
        x, y = suggest_site(w)
        tile = w.tile(x, y)
        self.assertFalse(tile.is_ocean)
        self.assertFalse(tile.is_lake)
        self.assertIsNone(tile.site_id)


if __name__ == "__main__":
    unittest.main()


class TestMilitary(unittest.TestCase):
    """Squads, uniforms, training and the alarm."""

    def setUp(self):
        from ascii_warriors.fortress import military

        self.military = military

    def _armed_squad(self, fort, size=3, uniform="axe"):
        """Raise a squad, give the fortress kit to arm it, and a barracks."""
        from ascii_warriors.game.item import Item

        spot = _open_spot(fort, "barracks")
        self.assertIsNotNone(spot, "nowhere to put a barracks")
        fort.buildings.append(Building("barracks", *spot))
        d0 = fort.dwarves()[0]
        for _ in range(size + 1):
            for def_id, mat in (("battle_axe", "steel"), ("mail_shirt", "iron"),
                                ("helm", "iron"), ("shield", "iron"),
                                ("greaves", "iron"), ("high_boots", "leather"),
                                ("gauntlets", "iron")):
                fort.drop_item(Item(def_id, mat), d0.x, d0.y, d0.z)
        squad = fort.military.add_squad("The Test Guard", uniform)
        for d in fort.dwarves()[:size]:
            fort.military.enlist(squad, d.id)
        return squad

    def test_every_uniform_names_real_items(self):
        """A uniform that asks for a nonexistent axe arms nobody."""
        from ascii_warriors.data import items as item_data
        from ascii_warriors.game import skills as skill_mod

        for uniform in self.military.UNIFORMS.values():
            self.assertTrue(uniform.weapons, uniform.id)
            self.assertTrue(skill_mod.exists(uniform.skill), uniform.id)
            for def_id in uniform.weapons + uniform.armor:
                self.assertTrue(item_data.exists(def_id),
                                "%s wants a nonexistent %s"
                                % (uniform.id, def_id))

    def test_enlisting_moves_a_dwarf_between_squads(self):
        """A dwarf belongs to at most one squad."""
        fort = embark("enlist")
        a = fort.military.add_squad("A", "axe")
        b = fort.military.add_squad("B", "hammer")
        d = fort.dwarves()[0]
        fort.military.enlist(a, d.id)
        fort.military.enlist(b, d.id)
        self.assertFalse(a.has(d.id))
        self.assertTrue(b.has(d.id))
        self.assertEqual(fort.military.squad_of(d.id), b)

    def test_squad_size_is_capped(self):
        """A squad will not take an eleventh dwarf."""
        fort = embark("squadsize")
        squad = fort.military.add_squad("Full", "axe")
        squad.members = list(range(self.military.SQUAD_SIZE))
        self.assertFalse(fort.military.enlist(squad, 999))

    def test_soldiers_arm_themselves(self):
        """A squad finds and puts on the kit its uniform calls for."""
        fort = embark("arming")
        squad = self._armed_squad(fort)
        sim.run(fort, 2000)
        ready, total = self.military.readiness(squad, fort)
        self.assertEqual(ready, total, "the squad never armed itself")
        for dwarf_id in squad.members:
            d = fort.creatures[dwarf_id]
            self.assertIsNotNone(d.inventory.weapon())

    def test_the_whole_squad_trains(self):
        """Training must not concentrate on whoever grabs the job first."""
        fort = embark("training")
        squad = self._armed_squad(fort, size=3)
        sim.run(fort, 9000)
        levels = [fort.creatures[i].skills.level("fighter")
                  for i in squad.members]
        self.assertTrue(all(lv >= 3 for lv in levels),
                        "only some of the squad trained: %s" % levels)

    def test_a_trained_squad_beats_a_siege(self):
        """The point of a militia."""
        fort = embark("defence")
        squad = self._armed_squad(fort, size=3)
        sim.run(fort, 9000)
        before = len(fort.dwarves())
        sim.spawn_attack(fort, 5)
        sim.run(fort, 2500)
        self.assertEqual(len(fort.hostiles()), 0, "the goblins are still here")
        self.assertGreaterEqual(len(fort.dwarves()), before - 2)

    def test_the_alarm_raises_and_lifts_itself(self):
        """Somebody has to notice the goblins."""
        fort = embark("alarm")
        self.assertFalse(fort.military.alarm)
        sim.spawn_attack(fort, 2)
        sim.step(fort)
        self.assertTrue(fort.military.alarm)
        for foe in fort.hostiles():
            foe.body.dead = True
        sim.step(fort)
        self.assertFalse(fort.military.alarm)

    def test_civilians_shelter_in_the_burrow(self):
        """Under alarm, a civilian heads for the safe room."""
        fort = embark("burrow")
        d = fort.dwarves()[0]
        # A burrow a few tiles away, on walkable ground.
        cells = [(d.x + dx, d.y + dy) for dx in range(3, 6) for dy in range(0, 3)
                 if fort.local.walkable(d.x + dx, d.y + dy, d.z)]
        self.assertTrue(cells, "no walkable ground for a burrow")
        fort.military.burrow = (cells[0][0], cells[0][1], d.z, 3, 3)
        fort.military.sound_alarm()
        for _ in range(120):
            dwarf_mod.take_turn(fort, d, sim.STEP_TICKS)
        self.assertTrue(fort.military.in_burrow(d.x, d.y, d.z),
                        "%s never reached shelter" % d.name)

    def test_traps_hurt_intruders(self):
        """A weapon trap is worth more than a dwarf with an axe."""
        from ascii_warriors.game.item import Item

        fort = embark("trapped")
        spot = _open_spot(fort, "weapon_trap")
        fort.drop_item(Item("battle_axe", "steel"), *spot)
        trap = Building("weapon_trap", *spot)
        fort.buildings.append(trap)
        sim.run(fort, 800)
        self.assertTrue(trap.built, "the trap was never built")
        foe = sim.spawn_attack(fort, 1)[0]
        foe.x, foe.y, foe.z = spot
        before = foe.body.health_fraction()
        for _ in range(3):
            sim._traps(fort)
        self.assertLess(foe.body.health_fraction(), before,
                        "the goblin walked over the trap unharmed")

    def test_military_survives_a_save(self):
        """Squads and the burrow come back."""
        fort = embark("milsave")
        squad = fort.military.add_squad("Keepers", "hammer")
        fort.military.enlist(squad, fort.dwarves()[0].id)
        squad.order = "station"
        squad.station = (10, 10, fort.z)
        fort.military.burrow = (5, 5, fort.z, 4, 4)
        again = Fortress.from_dict(fort.to_dict())
        self.assertEqual(len(again.military.squads), 1)
        back = again.military.squads[0]
        self.assertEqual(back.name, "Keepers")
        self.assertEqual(back.uniform, "hammer")
        self.assertEqual(back.station, (10, 10, fort.z))
        self.assertEqual(again.military.burrow, (5, 5, fort.z, 4, 4))


class TestHospital(unittest.TestCase):
    """Wounds, doctors and beds."""

    def _wound(self, dwarf, bleeding=6):
        """Open a survivable but serious cut."""
        from ascii_warriors.game.body import Wound

        pid = dwarf.body.order[5]
        dwarf.body.parts[pid].wounds.append(
            Wound(pid, "muscle", 0.5, "edge", bleeding=bleeding, pain=8))
        return pid

    def _ward(self, fort, doctors=True, beds=3):
        """Build a hospital and stock it."""
        from ascii_warriors.game.item import Item

        for _ in range(beds):
            spot = _open_spot(fort, "hospital")
            if spot is not None:
                fort.buildings.append(Building("hospital", *spot))
        d0 = fort.dwarves()[0]
        fort.drop_item(Item("bandage", "pig_tail_cloth", count=10),
                       d0.x, d0.y, d0.z)
        for d in fort.dwarves():
            if doctors:
                d.fort.labors.enable("medicine")
            else:
                d.fort.labors.disable("medicine")
        sim.run(fort, 700)

    def test_resting_does_not_instantly_cure_everything(self):
        """Lying down closes wounds over time, not on the first tick."""
        fort = embark("resting")
        d = fort.dwarves()[0]
        self._wound(d, bleeding=8)
        before = d.body.bleeding_rate()
        d.body.rest_heal(30, 1.0)
        self.assertGreater(d.body.bleeding_rate(), 0.0,
                           "one moment of rest closed an open wound")
        self.assertLessEqual(d.body.bleeding_rate(), before)

    def test_rest_does_eventually_close_a_wound(self):
        """It has to converge, or nobody ever recovers."""
        fort = embark("resting2")
        d = fort.dwarves()[0]
        self._wound(d, bleeding=4)
        for _ in range(200):
            d.body.rest_heal(30, 1.0)
        self.assertEqual(d.body.bleeding_rate(), 0.0)

    def test_the_hurt_stop_working(self):
        """A bleeding dwarf does not carry on hauling rocks."""
        fort = embark("stopwork")
        dig_room(fort, 5)
        sim.run(fort, 300)
        d = fort.dwarves()[0]
        self._wound(d, bleeding=4)
        sim.step(fort)
        self.assertTrue(d.fort.job is None or d.fort.job.kind == "treat")

    def test_a_doctor_binds_a_wound(self):
        """The whole chain: notice, assign, walk, bandage, stop bleeding."""
        fort = embark("binding")
        self._ward(fort)
        patient = fort.dwarves()[3]
        # Serious enough to kill without help, slow enough to be treatable.
        self._wound(patient, bleeding=4)
        for _ in range(600):
            sim.step(fort)
            if patient.body.bleeding_rate() == 0 or patient.body.dead:
                break
        bound = [m.text for m in fort.log.all() if "binds" in m.text]
        self.assertTrue(bound, "nobody ever bandaged the patient")
        self.assertFalse(patient.body.dead)

    def test_a_hospital_saves_a_dwarf_that_would_have_died(self):
        """The point of a hospital."""
        def run(with_doctors):
            fort = embark("saved")
            self._ward(fort, doctors=with_doctors)
            patient = fort.dwarves()[3]
            self._wound(patient, bleeding=4)
            for _ in range(900):
                sim.step(fort)
                if patient.body.dead or patient.body.bleeding_rate() == 0:
                    break
            return patient.body.dead

        self.assertTrue(run(False), "the control case did not die; retune it")
        self.assertFalse(run(True), "the hospital did not save the patient")

    def test_supplies_are_never_lost(self):
        """A doctor must not pocket the fortress's only bandages."""
        fort = embark("supplies")
        self._ward(fort)
        before = fort.stock_count("bandage")
        patient = fort.dwarves()[3]
        self._wound(patient, bleeding=3)
        sim.run(fort, 500)
        carried = sum(i.count for c in fort.creatures.values()
                      for i in c.inventory.items if i.def_id == "bandage")
        self.assertLessEqual(carried, 0,
                             "%d bandages are stuck in a pocket" % carried)
        self.assertGreater(fort.stock_count("bandage"), before - 4)

    def test_a_ward_with_no_doctor_warns(self):
        """Silence is the wrong response to a bleeding dwarf."""
        fort = embark("nodoc")
        self._ward(fort, doctors=False)
        self._wound(fort.dwarves()[3], bleeding=4)
        sim.run(fort, 30)
        self.assertTrue(
            any("treat" in m.text for m in fort.log.all()),
            "no warning that nobody can treat the wounded")

    def test_health_summary_reads_sensibly(self):
        """The health screen's rows."""
        from ascii_warriors.fortress import hospital

        fort = embark("summary")
        self.assertEqual(hospital.summary(fort), [])
        self._wound(fort.dwarves()[0], bleeding=5)
        rows = hospital.summary(fort)
        self.assertEqual(len(rows), 1)
        name, condition, wanted = rows[0]
        self.assertTrue(name)
        self.assertTrue(condition)
        self.assertIn("bandage", wanted)
