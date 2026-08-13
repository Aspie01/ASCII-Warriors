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
    """Found a test fortress on the most promising square.

    Every embark gets its own copy of the shared world, because a fortress
    changes the world it stands in: it writes itself into history, and every
    season it plays, the world outside takes a season too. Sharing one world
    between tests means a long-running test can burn down the town another
    test was about to embark next to. The copy costs about five milliseconds.
    """
    from ascii_warriors.ui.fort.embark import suggest_site
    from ascii_warriors.world.worldgen import World

    w = World.from_dict(world().to_dict())
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
    """Designate a block of digging near the dwarves, wherever the rock is.

    Painting a fixed pair of levels under the wagon only works when the wagon
    happens to be standing on rock. Embark on a valley floor with a cavern
    under it and the same rectangle paints nothing, and every digging test
    quietly stops testing anything.
    """
    d = fort.dwarves()[0]
    total = 0
    for z in range(fort.z, max(fort.local.zmin, fort.z - 8) - 1, -1):
        total += fort.designations.paint_rect(
            fort.local, d.x - radius, d.y - radius, d.x + radius,
            d.y + radius, z, "dig")
        if total:
            break
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

        When these disagree a dwarf walks on the spot until it dies. Both
        senses of reach have to agree, not just the generous one.
        """
        lm = self.fort.local
        d = self.fort.dwarves()[0]
        goal = (d.x, d.y, d.z - 1)
        for vertical in (True, False):
            for cell in dwarf_mod.work_positions(lm, goal, vertical=vertical):
                probe = type("Probe", (), {"x": cell[0], "y": cell[1],
                                           "z": cell[2]})()
                self.assertTrue(
                    dwarf_mod.at_or_beside(probe, goal, vertical=vertical),
                    "%s can be pathed to but is not 'beside' %s"
                    % (cell, goal))

    def test_only_digging_reaches_through_a_floor(self):
        """A miner digs the rock under its feet. Nobody drinks through it."""
        d = self.fort.dwarves()[0]
        above = (d.x, d.y, d.z + 1)
        self.assertTrue(dwarf_mod.at_or_beside(d, above))
        self.assertFalse(dwarf_mod.at_or_beside(d, above, vertical=False))
        self.assertTrue(dwarf_mod.vertical_reach(Job(1, "dig", *above)))
        self.assertFalse(dwarf_mod.vertical_reach(Job(2, "haul", *above)))
        self.assertNotIn(
            (d.x, d.y, d.z),
            dwarf_mod.work_positions(self.fort.local, above, vertical=False))

    def test_a_dwarf_does_not_drink_through_the_ceiling(self):
        """It has to walk round to the barrel like everybody else.

        Standing directly below a barrel used to count as standing beside it,
        so every thirsty dwarf in the fortress crowded onto that one tile,
        shoved each other off it, and died of thirst under the ale.
        """
        from ascii_warriors.game.item import Item

        fort = embark("ceiling")
        for cell, pile in list(fort.items_on_ground.items()):
            fort.items_on_ground[cell] = [i for i in pile if not i.is_drink]
        d = fort.dwarves()[0]
        barrel = (d.x, d.y, d.z + 1)
        fort.drop_item(Item("dwarven_ale", "alcohol", count=10), *barrel)
        d.needs.thirst = dwarf_mod.THIRST_URGENT * 2
        before = d.needs.thirst
        dwarf_mod.take_turn(fort, d, 10)
        self.assertEqual(d.needs.thirst, before,
                         "the dwarf drank through a solid floor")

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
        """Doing nothing at all should still buy you two weeks.

        About supplies, not about safety: digging a room can breach a river
        and drown somebody, which is a different lesson entirely.
        """
        fort = embark("survival")
        dig_room(fort, 6)
        sim.run(fort, int(TICKS_PER_DAY * 14 / sim.STEP_TICKS))
        self.assertFalse(fort.lost, "the fortress fell: %s" % fort.loss_reason)
        went_without = [c.body.death_cause for c in fort.creatures.values()
                        if c.body.dead and c.body.death_cause in
                        ("starved to death", "died of thirst")]
        self.assertEqual(went_without, [],
                         "the embark supplies did not last a fortnight")

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
        # Goblins are a different test. What matters here is that nobody ran
        # out of food or drink over a full season.
        hungry = [c.body.death_cause for c in fort.creatures.values()
                  if c.body.dead and c.body.death_cause in
                  ("starved to death", "died of thirst")]
        self.assertEqual(hungry, [], "the food economy did not close")
        self.assertGreater(fort.stock_count("plump_helmet"), 0,
                           "the farms never kept up")
        self.assertGreater(fort.stock_count("dwarven_ale"), 0,
                           "the still never got ahead")

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
                if ":" in requirement:
                    # "bar:copper": both halves have to be real.
                    from ascii_warriors.data import materials as mat_data

                    def_id, _, material = requirement.partition(":")
                    self.assertTrue(item_data.exists(def_id), recipe.id)
                    self.assertIn(material, mat_data.MATERIALS, recipe.id)
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


class TestIndustry(unittest.TestCase):
    """Ore in the rock, fuel in the furnace, metal out of the forge."""

    def setUp(self):
        from ascii_warriors.data import materials as mat_data
        from ascii_warriors.game.item import Item

        self.mats = mat_data
        self.Item = Item

    def _shop(self, fort, kind):
        """A built workshop of this kind, near the dwarves."""
        spot = _open_spot(fort, kind)
        self.assertIsNotNone(spot, "nowhere to put a %s" % kind)
        b = Building(kind, *spot)
        b.built = True
        fort.buildings.append(b)
        return b

    def _vein(self, fort, tile_id):
        """A cell of vein of the given kind, or None."""
        return next((c for c in sorted(fort.local.veins)
                     if fort.local.tile(*c) == tile_id), None)

    # -- geology ----------------------------------------------------------- #

    def test_a_map_has_veins_and_they_are_made_of_something(self):
        """Every vein cell knows its material, and the material is real."""
        fort = embark("geology")
        self.assertTrue(fort.local.veins, "no veins anywhere on the map")
        for cell, material in fort.local.veins.items():
            self.assertIn(material, self.mats.MATERIALS, str(cell))
            self.assertIn(fort.local.tile(*cell),
                          ("ore_vein", "gem_vein", "coal_seam",
                           "adamantine_vein"), str(cell))

    def test_a_vein_is_the_same_metal_all_the_way_through(self):
        """You dig towards the iron and you get iron, not a lottery ticket."""
        fort = embark("geology")
        cell = self._vein(fort, "ore_vein")
        self.assertIsNotNone(cell, "no ore on this map")
        material = fort.local.veins[cell]
        self.assertEqual(fort._stone_here(cell), material)
        self.assertEqual(fort._stone_here(cell), material,
                         "asking twice gave two answers")

    def test_veins_survive_a_save(self):
        """What is in the rock has to still be there after a reload."""
        fort = embark("veinsave")
        again = Fortress.from_dict(fort.to_dict())
        self.assertEqual(again.local.veins, fort.local.veins)

    def test_mining_a_vein_yields_what_is_in_it(self):
        """Ore, coal and gems, not a boulder of generic rock."""
        fort = embark("mining")
        wanted = {"ore_vein": "ore", "coal_seam": "coal",
                  "gem_vein": "rough_gem"}
        seen = 0
        for tile_id, def_id in wanted.items():
            cell = self._vein(fort, tile_id)
            if cell is None:
                continue
            seen += 1
            item = fort._mined_item(cell, fort._stone_here(cell))
            self.assertEqual(item.def_id, def_id, tile_id)
            if tile_id == "ore_vein":
                self.assertEqual(item.material, fort.local.veins[cell])
        self.assertGreater(seen, 0, "the map had no veins to mine at all")

    def test_plain_rock_still_gives_a_boulder(self):
        """The ordinary case has to keep working."""
        fort = embark("mining")
        lm = fort.local
        cell = next(c for c in
                    ((x, y, z) for z in range(lm.zmin, 0)
                     for y in range(lm.height) for x in range(lm.width))
                    if lm.tile(*c) == "rock_wall")
        item = fort._mined_item(cell, fort._stone_here(cell))
        self.assertEqual(item.def_id, "boulder")

    # -- the smelter ------------------------------------------------------- #

    def test_smelting_gives_a_bar_of_the_ore_s_metal(self):
        """Iron ore makes an iron bar and nothing else."""
        recipe = production.RECIPES["smelt_ore"]
        ore = self.Item("ore", "iron")
        fuel = self.Item("charcoal", "charcoal")
        chosen = production.find_inputs(recipe, [ore, fuel])
        self.assertIsNotNone(chosen)
        self.assertEqual(production.output_material(recipe, chosen), "iron")

    def test_smelting_needs_fuel(self):
        """Ore alone is a rock."""
        recipe = production.RECIPES["smelt_ore"]
        self.assertIsNone(
            production.find_inputs(recipe, [self.Item("ore", "iron")]))
        self.assertIsNotNone(production.find_inputs(
            recipe, [self.Item("ore", "iron"), self.Item("coal", "coal")]))

    def test_bronze_needs_both_metals(self):
        """Copper on its own is copper."""
        recipe = production.RECIPES["make_bronze"]
        copper = self.Item("bar", "copper", count=4)
        fuel = self.Item("charcoal", "charcoal", count=4)
        self.assertIsNone(production.find_inputs(recipe, [copper, fuel]))
        chosen = production.find_inputs(
            recipe, [copper, self.Item("bar", "tin"), fuel])
        self.assertIsNotNone(chosen)
        self.assertEqual(production.output_material(recipe, chosen), "bronze")

    def test_steel_needs_flux(self):
        """Iron and fuel are not enough; the flux stone is the trick."""
        recipe = production.RECIPES["make_steel"]
        base = [self.Item("bar", "iron"),
                self.Item("charcoal", "charcoal", count=4)]
        self.assertIsNone(production.find_inputs(
            recipe, base + [self.Item("boulder", "granite")]))
        chosen = production.find_inputs(
            recipe, base + [self.Item("boulder", "limestone")])
        self.assertIsNotNone(chosen)
        self.assertEqual(production.output_material(recipe, chosen), "steel")

    def test_charcoal_is_charcoal_and_not_oak(self):
        """A burnt log stops being a log."""
        recipe = production.RECIPES["burn_charcoal"]
        chosen = production.find_inputs(recipe, [self.Item("log", "oak")])
        self.assertIsNotNone(chosen)
        self.assertEqual(production.output_material(recipe, chosen), "charcoal")

    # -- the forge --------------------------------------------------------- #

    def test_the_forge_works_in_metal_not_stone(self):
        """A pile of boulders is no longer a sword."""
        recipe = production.RECIPES["iron_sword"]
        stone = [self.Item("boulder", "granite", count=8),
                 self.Item("charcoal", "charcoal", count=4)]
        self.assertIsNone(production.find_inputs(recipe, stone))
        chosen = production.find_inputs(
            recipe, [self.Item("bar", "steel", count=3),
                     self.Item("charcoal", "charcoal")])
        self.assertIsNotNone(chosen)
        self.assertEqual(production.output_material(recipe, chosen), "steel")

    def test_a_better_bar_makes_a_better_weapon(self):
        """The whole point of the industry: metal you dig for is metal you
        fight with."""
        copper = self.Item("axe", "copper")
        steel = self.Item("axe", "steel")
        self.assertGreater(steel.value, copper.value)
        self.assertGreater(steel.mat.shear_yield, copper.mat.shear_yield)

    # -- the chain, in a running fortress ----------------------------------- #

    def test_the_whole_chain_runs(self):
        """Logs and ore go in one end; an axe comes out of the other."""
        fort = embark("chain")
        for d in fort.dwarves():
            d.fort.labors.enabled.update(
                {"smelting", "smithing", "weaponsmithing"})
        furnace = self._shop(fort, "wood_furnace")
        smelter = self._shop(fort, "smelter")
        forge = self._shop(fort, "smith")
        fort.drop_item(self.Item("log", "oak", count=8), *furnace.center)
        fort.drop_item(self.Item("ore", "iron", count=8), *smelter.center)
        furnace.orders.append(
            {"recipe": "burn_charcoal", "count": 4, "repeat": False})
        smelter.orders.append(
            {"recipe": "smelt_ore", "count": 4, "repeat": False})
        forge.orders.append(
            {"recipe": "iron_axe", "count": 1, "repeat": False})
        before = sum(1 for i in fort.all_items() if i.def_id == "axe")

        sim.run(fort, 900)

        self.assertGreater(fort.stock_count("charcoal") + 4, 4,
                           "the furnace never burned anything")
        axes = [i for i in fort.all_items() if i.def_id == "axe"]
        self.assertGreater(len(axes), before, "the forge made nothing")
        self.assertTrue(any(a.mat.is_metal for a in axes))

    def test_a_workshop_nobody_will_staff_says_so(self):
        """A job no dwarf accepts must not sit on the board in silence."""
        fort = embark("nolabor")
        for d in fort.dwarves():
            d.fort.labors.enabled.discard("smelting")
        smelter = self._shop(fort, "smelter")
        smelter.orders.append(
            {"recipe": "smelt_ore", "count": 1, "repeat": False})
        sim.scan_jobs(fort)
        self.assertEqual(fort.jobs.count("craft"), 0)
        self.assertTrue(any("furnace operating" in m.text.lower()
                            for m in fort.log.all()),
                        "nothing explained why the smelter is idle")

    # -- hauling and building ---------------------------------------------- #

    def test_ore_is_not_a_building_material(self):
        """Ore is for the smelter; bars are for the wall."""
        self.assertFalse(building_mod.material_matches(
            self.Item("ore", "iron"), "floodgate"))
        self.assertFalse(building_mod.material_matches(
            self.Item("charcoal", "charcoal"), "floodgate"))
        self.assertTrue(building_mod.material_matches(
            self.Item("bar", "iron"), "floodgate"))

    def test_a_metal_stockpile_takes_the_industry_and_nothing_else(self):
        """Ore beside the smelter, not scattered through the bedrooms."""
        pile = Stockpile("metal", 0, 0, 0, 3, 3)
        for def_id, material in (("ore", "iron"), ("bar", "steel"),
                                 ("coal", "coal"), ("charcoal", "charcoal")):
            self.assertTrue(pile.accepts(self.Item(def_id, material)), def_id)
        self.assertFalse(pile.accepts(self.Item("boulder", "granite")))
        self.assertFalse(pile.accepts(self.Item("meat", "meat")))
        stone = Stockpile("stone", 0, 0, 0, 3, 3)
        self.assertFalse(stone.accepts(self.Item("ore", "iron")))


class TestWar(unittest.TestCase):
    """Sieges by civilizations that exist, and what beating one costs them."""

    def setUp(self):
        from ascii_warriors.fortress import war as war_mod

        self.war = war_mod
        self.fort = embark("war")
        self.fort.wealth = 9000

    def _veterans(self, fort):
        """Dwarves who can actually win a fight."""
        for d in fort.dwarves():
            d.skills.set_level("fighter", 12)
            d.skills.set_level("axe", 12)
            d.skills.set_level("armor_use", 8)

    def _army(self, fort):
        plan = self.war.plan(fort)
        self.assertIsNotNone(plan, "nobody in the world wants to attack")
        return plan, self.war.launch(fort, plan)

    # -- who and why -------------------------------------------------------- #

    def test_a_fortress_belongs_to_a_civilization(self):
        """Somebody sent the expedition, and they have enemies."""
        civ = self.war.home_civ(self.fort)
        self.assertIsNotNone(civ)
        self.assertEqual(civ.race, "dwarf")
        self.assertEqual(self.fort.civ_id, civ.id)

    def test_the_enemies_are_real_civilizations(self):
        """Not "goblins": a nation with a name and a place on the map."""
        foes = self.war.enemies(self.fort)
        self.assertTrue(foes)
        for civ in foes:
            self.assertTrue(civ.name)
            self.assertIsNone(civ.destroyed)
            self.assertIsNot(civ, self.war.home_civ(self.fort))

    def test_nobody_walks_across_a_continent_for_a_poor_fortress(self):
        """Wealth is what gets you noticed."""
        self.fort.wealth = 0
        self.assertIsNone(self.war.plan(self.fort))

    def test_a_civilization_can_only_send_what_it_has(self):
        """Raid a nation to two villages and the sieges get smaller."""
        fort = self.fort
        civ = self.war.enemies(fort)[0]
        big = self.war.strength_for(fort, civ)
        for site in fort.world.sites:
            if site.civ_id == civ.id:
                site.population = 1
        self.assertLess(self.war.strength_for(fort, civ), big)

    def test_the_army_has_a_named_commander(self):
        """Somebody the legends screen can talk about afterwards."""
        fort = self.fort
        plan, army = self._army(fort)
        self.assertTrue(army)
        leader = fort.world.figures.get(plan.commander_hf)
        self.assertIsNotNone(leader)
        self.assertEqual(army[0].hf_id, leader.id)
        self.assertEqual(army[0].name, leader.name)
        self.assertTrue(any(leader.name in m.text for m in fort.log.all()))

    def test_only_one_army_at_a_time(self):
        """A second siege while the first is on the map is a pile-up."""
        fort = self.fort
        self._army(fort)
        before = len(fort.hostiles())
        for _ in range(20):
            sim._maybe_attack(fort)
        self.assertEqual(len(fort.hostiles()), before)

    # -- how it ends -------------------------------------------------------- #

    def test_an_army_breaks_when_it_has_lost_enough(self):
        """Fighting to the last man is a grind, not a battle."""
        fort = self.fort
        plan, army = self._army(fort)
        for foe in army[:int(len(army) * self.war.ROUT_LOSSES) + 1]:
            foe.body.death_cause = "slain"
            fort.kill_creature(foe)
        self.assertTrue(fort.siege.routed)
        self.assertTrue(any("break and run" in m.text for m in fort.log.all()))

    def test_the_routed_leave_and_the_alarm_stops(self):
        """The siege has to actually end."""
        fort = self.fort
        self._veterans(fort)
        self._army(fort)
        for _ in range(4000):
            sim.step(fort)
            if fort.siege is None:
                break
        self.assertIsNone(fort.siege, "the siege never ended")
        self.assertEqual(fort.hostiles(), [])
        self.assertEqual(fort.military.alert, "civilian")

    def test_the_stuck_are_gone_anyway(self):
        """A survivor wedged in a corridor cannot besiege you for ever."""
        fort = self.fort
        plan, army = self._army(fort)
        self.war.rout(fort)
        fort.siege.fleeing_since = fort.ticks - self.war.FLEE_TICKS - 1
        for foe in army:
            foe.x, foe.y, foe.z = fort.dwarves()[0].x, fort.dwarves()[0].y, \
                fort.dwarves()[0].z
        sim.step(fort)
        self.assertEqual(fort.hostiles(), [])

    # -- what it costs them -------------------------------------------------- #

    def test_beating_an_army_takes_it_off_the_map_for_good(self):
        """The only thing a fortress does that makes the world easier."""
        fort = self.fort
        plan, army = self._army(fort)
        civ = fort.world.civ(plan.civ_id)
        before = sum(s.population for s in fort.world.sites
                     if s.civ_id == civ.id and not s.is_ruin)
        for foe in army:
            foe.body.death_cause = "slain"
            fort.kill_creature(foe)
        after = sum(s.population for s in fort.world.sites
                    if s.civ_id == civ.id and not s.is_ruin)
        self.assertLess(after, before)

    def test_the_world_remembers_the_battle(self):
        """Win or lose, it goes in the legends."""
        fort = self.fort
        plan, army = self._army(fort)
        before = len(fort.world.events)
        for foe in army:
            foe.body.death_cause = "slain"
            fort.kill_creature(foe)
        told = [e for e in fort.world.events[before:] if e.kind == "battle"]
        self.assertTrue(told)
        self.assertIn(fort.name, told[0].text)

    def test_a_battle_is_only_recorded_once(self):
        """Every kill after the rout must not write another line."""
        fort = self.fort
        plan, army = self._army(fort)
        for foe in army:
            foe.body.death_cause = "slain"
            fort.kill_creature(foe)
        battles = [e for e in fort.world.events if e.kind == "battle"]
        self.war.record(fort, won=True)
        self.assertEqual(len([e for e in fort.world.events
                              if e.kind == "battle"]), len(battles))

    def test_a_fallen_fortress_is_recorded_as_overrun(self):
        """Losing is fun, and written down."""
        fort = self.fort
        plan, army = self._army(fort)
        civ = fort.world.civ(plan.civ_id)
        for d in list(fort.dwarves()):
            d.body.death_cause = "slain"
            fort.kill_creature(d)
        sim.step(fort)
        self.assertTrue(fort.lost)
        self.assertIn(civ.name, fort.loss_reason)
        self.assertTrue(any(e.kind == "battle" and fort.name in e.text
                            for e in fort.world.events))

    def test_a_siege_survives_a_save(self):
        """Mid-siege saves are exactly when people save."""
        fort = self.fort
        plan, army = self._army(fort)
        fort.siege.killed = 2
        again = Fortress.from_dict(fort.to_dict())
        self.assertIsNotNone(again.siege)
        self.assertEqual(again.siege.killed, 2)
        self.assertEqual(again.siege.civ_id, plan.civ_id)
        self.assertEqual(again.civ_id, fort.civ_id)


class TestAnimals(unittest.TestCase):
    """Livestock, pets, pastures and the butcher."""

    def setUp(self):
        from ascii_warriors.fortress import animals as animal_mod

        self.animals = animal_mod
        self.fort = embark("husbandry")

    def _herd(self, species=None):
        herd = self.animals.livestock(self.fort)
        if species:
            herd = [c for c in herd if c.defn.id == species]
        return herd

    # -- what you set out with --------------------------------------------- #

    def test_the_wagon_brings_animals(self):
        """A fortress arrives with dogs, cats and something to milk."""
        herd = self._herd()
        kinds = {c.defn.id for c in herd}
        self.assertIn("dog", kinds)
        self.assertIn("cow", kinds)
        self.assertTrue(any(self.animals.grazes(c) for c in herd))
        for c in herd:
            self.assertFalse(c.animal.wild)
            self.assertEqual(c.faction, "fortress")

    def test_they_do_not_all_arrive_on_one_tile(self):
        """Free spots have to be different spots."""
        where = [(c.x, c.y, c.z) for c in self._herd()]
        self.assertEqual(len(set(where)), len(where), where)

    def test_pets_belong_to_somebody(self):
        """A dog is somebody's dog."""
        pets = [c for c in self._herd() if c.defn.has("PET")]
        self.assertTrue(pets)
        self.assertTrue(any(c.animal.owner is not None for c in pets))

    def test_the_map_has_wildlife_and_none_of_it_is_undead(self):
        """Something has to be moving out there, but not the walking dead."""
        wild = self.animals.wildlife(self.fort)
        self.assertTrue(wild)
        for c in wild:
            self.assertFalse(c.defn.has("EVIL"), c.short_name())
            self.assertFalse(c.defn.has("MEGABEAST"), c.short_name())

    # -- staying alive ----------------------------------------------------- #

    def test_animals_do_not_queue_at_the_ale_barrel(self):
        """Dwarf needs on a cow kill the herd of thirst in three days."""
        fort = self.fort
        cow = self._herd("cow")[0]
        before = cow.needs.thirst
        sim.run(fort, 400)
        self.assertEqual(cow.needs.thirst, before)
        self.assertFalse(cow.body.dead)

    def test_a_grazer_eats_the_grass_it_stands_on(self):
        """And the grass remembers being eaten."""
        fort = self.fort
        cow = self._herd("cow")[0]
        fort.local.set_tile(cow.x, cow.y, cow.z, "grass")
        cow.animal.hunger = 5000
        self.animals.step(fort, 10)
        self.assertEqual(fort.local.tile(cow.x, cow.y, cow.z), "dirt")
        self.assertEqual(cow.animal.hunger, 0)
        self.assertIn((cow.x, cow.y, cow.z), fort.grazed)

    def test_grass_grows_back(self):
        """Or one herd turns the embark into a car park for ever."""
        fort = self.fort
        cell = (fort.dwarves()[0].x, fort.dwarves()[0].y, fort.dwarves()[0].z)
        fort.local.set_tile(*cell, "dirt")
        fort.grazed[cell] = fort.ticks - self.animals.REGROW_TICKS - 1
        self.animals._regrow(fort)
        self.assertEqual(fort.local.tile(*cell), "grass")
        self.assertNotIn(cell, fort.grazed)

    def test_a_mountain_fortress_feeds_its_animals_from_the_cellar(self):
        """There is no grass on a mountain. There is a food store."""
        fort = self.fort
        cow = self._herd("cow")[0]
        cow.animal.hunger = self.animals.FODDER_AT + 1
        before = fort.stock_count("plump_helmet")
        self.assertGreater(before, self.animals.FODDER_RESERVE)
        self.animals.step(fort, 10)
        self.assertEqual(cow.animal.hunger, 0)
        self.assertLess(fort.stock_count("plump_helmet"), before)

    def test_the_stores_are_not_eaten_to_the_last_plant(self):
        """The dwarves come first."""
        fort = self.fort
        for item in list(fort.all_items()):
            if item.def_id == "plump_helmet":
                item.count = self.animals.FODDER_RESERVE
        self.assertFalse(self.animals._eat_fodder(fort))

    def test_an_unfed_animal_starves_eventually(self):
        """Slowly enough to notice, surely enough to matter."""
        fort = self.fort
        for item in list(fort.all_items()):
            if item.is_edible:
                fort.take_item(item)
        cow = self._herd("cow")[0]
        cow.animal.hunger = self.animals.GRAZE_TICKS + 1
        self.animals.step(fort, 10)
        self.assertTrue(cow.body.dead)
        self.assertEqual(cow.body.death_cause, "starved to death")

    # -- pastures ----------------------------------------------------------- #

    def test_a_pasture_keeps_its_animals(self):
        """That is the whole reason to paint one."""
        fort = self.fort
        d = fort.dwarves()[0]
        pasture = self.animals.Pasture(d.x - 3, d.y - 3, d.z, 7, 7)
        fort.pastures.append(pasture)
        cow = self._herd("cow")[0]
        cow.x, cow.y, cow.z = pasture.x + 1, pasture.y + 1, pasture.z
        for _ in range(200):
            self.animals.step(fort, 10)
            self.assertTrue(pasture.contains(cow.x, cow.y, cow.z),
                            "%s left the pasture" % ((cow.x, cow.y, cow.z),))

    def test_a_loose_grazer_is_put_out_to_pasture(self):
        """Painting one is the assignment."""
        fort = self.fort
        d = fort.dwarves()[0]
        pasture = self.animals.Pasture(d.x - 2, d.y - 2, d.z, 5, 5)
        fort.pastures.append(pasture)
        cow = self._herd("cow")[0]
        cow.animal.pasture = None
        self.animals.step(fort, 10)
        self.assertEqual(cow.animal.pasture, pasture.id)

    # -- what they are for -------------------------------------------------- #

    def test_a_cow_gives_milk_and_a_sheep_gives_wool(self):
        """And not the other way round."""
        fort = self.fort
        cow = self._herd("cow")[0]
        sheep = self._herd("sheep")[0]
        self.assertEqual(self.animals.produce(fort, cow).def_id, "milk")
        self.assertEqual(self.animals.produce(fort, sheep).def_id, "wool")
        self.assertIsNone(self.animals.produce(fort, self._herd("dog")[0]))

    def test_tending_is_one_job_per_animal_however_far_it_wanders(self):
        """Post by cell and the whole fortress queues to shear one sheep."""
        fort = self.fort
        sheep = self._herd("sheep")[0]
        sheep.animal.produce_at = 0
        sim.scan_jobs(fort)
        first = fort.jobs.count("tend")
        sheep.x += 2
        sim.scan_jobs(fort)
        self.assertEqual(fort.jobs.count("tend"), first)

    def test_milk_becomes_cheese_and_wool_becomes_bandages(self):
        """The products have to lead somewhere."""
        from ascii_warriors.game.item import Item

        cheese = production.RECIPES["make_cheese"]
        self.assertIsNotNone(production.find_inputs(
            cheese, [Item("milk", "milk", count=4)]))
        spin = production.RECIPES["spin_wool"]
        self.assertIsNotNone(production.find_inputs(
            spin, [Item("wool", "wool_cloth", count=2)]))
        bandage = production.RECIPES["cloth_bandage"]
        self.assertIsNotNone(production.find_inputs(
            bandage, [Item("cloth", "wool_cloth")]))
        self.assertIsNotNone(production.find_inputs(
            bandage, [Item("hide", "leather")]))

    def test_slaughtering_gives_meat_hide_and_bone(self):
        """A cow is worth more than a rat."""
        fort = self.fort
        cow = self._herd("cow")[0]
        goods = {i.def_id: i.count for i in
                 self.animals.butcher_yield(fort, cow)}
        self.assertGreaterEqual(goods.get("meat", 0), 6)
        self.assertIn("hide", goods)
        self.assertIn("bone_item", goods)

    def test_a_butcher_comes_for_a_marked_animal(self):
        """Mark it, and somebody walks out with a knife."""
        fort = self.fort
        for d in fort.dwarves():
            d.fort.labors.enable("butchery")
        cow = self._herd("cow")[0]
        cow.animal.slaughter = True
        before = len(self._herd())
        sim.run(fort, 900)
        self.assertLess(len(self._herd()), before)
        self.assertGreater(fort.stock_count("meat"), 0)

    def test_a_herd_grows_and_then_stops(self):
        """Two of a kind make a third, but not for ever."""
        fort = self.fort
        cows = self._herd("cow")
        self.assertGreaterEqual(len(cows), 2)
        for c in cows:
            c.animal.breed_at = 1
        fort.ticks = 100
        for _ in range(self.animals.HERD_CAP * 3):
            fort.ticks += self.animals.BREED_TICKS
            self.animals._breed(fort)
        grown = len(self._herd("cow"))
        self.assertGreater(grown, len(cows))
        self.assertLessEqual(grown, self.animals.HERD_CAP + 1)

    def test_animals_survive_a_save(self):
        """Including what they are, whose they are and what is coming."""
        fort = self.fort
        cow = self._herd("cow")[0]
        cow.animal.slaughter = True
        fort.pastures.append(self.animals.Pasture(10, 10, fort.z, 4, 4))
        again = Fortress.from_dict(fort.to_dict())
        back = again.creatures[cow.id]
        self.assertTrue(self.animals.is_animal(back))
        self.assertTrue(back.animal.slaughter)
        self.assertEqual(len(again.pastures), len(fort.pastures))
        self.assertEqual(len(self.animals.livestock(again)),
                         len(self.animals.livestock(fort)))


class TestTheDeep(unittest.TestCase):
    """Magma, adamantine, and what is under the adamantine."""

    def setUp(self):
        from ascii_warriors.world import fluids

        self.fluids = fluids
        self.fort = embark("thedeep")

    def _tube_cells(self, fort):
        """The magma pipe: everything molten above the sea."""
        return {c for c in fort.magma.depth if c[2] > fort.magma_floor}

    def _wall_beside(self, fort, cells):
        """A rock cell touching one of these, to mine through."""
        lm = fort.local
        for x, y, z in sorted(cells):
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                side = (x + dx, y + dy, z)
                if side in cells:
                    continue
                if not self.fluids.can_hold(lm, side) and lm.in_bounds(*side):
                    return side
        return None

    # -- the shape of the world -------------------------------------------- #

    def test_there_is_a_sea_at_the_bottom_and_stone_that_says_so(self):
        """The warning has to be there before the mistake is possible."""
        fort = self.fort
        lm = fort.local
        self.assertGreater(fort.magma.total(), 0, "no magma anywhere")
        sea = [c for c in fort.magma.depth if c[2] <= fort.magma_floor]
        self.assertGreater(len(sea), 1000, "the sea is a puddle")
        warm = sum(1 for y in range(lm.height) for x in range(lm.width)
                   if lm.tile(x, y, fort.magma_floor + 1) == "warm_stone")
        self.assertGreater(warm, 100, "nothing warns you about the sea")

    def test_a_pipe_of_magma_reaches_the_working_levels(self):
        """A sea at the bottom of the world nobody can reach is scenery."""
        tube = self._tube_cells(self.fort)
        self.assertTrue(tube, "no magma above the sea at all")
        self.assertGreater(max(c[2] for c in tube), self.fort.magma_floor + 3,
                           "the pipe does not come up far enough to matter")

    def test_the_spire_is_adamantine_and_hollow(self):
        """The last mistake a fortress makes has to be there to be made."""
        fort = self.fort
        ada = [c for c, m in fort.local.veins.items() if m == "adamantine"]
        self.assertTrue(ada, "no adamantine in the world")
        self.assertTrue(fort.hollow, "the spire is solid: nothing to breach")
        for cell in fort.hollow:
            self.assertEqual(fort.local.veins.get(cell), "adamantine")

    def test_mining_adamantine_gives_adamantine(self):
        """It is ore like any other, until you smelt it."""
        fort = self.fort
        cell = next(c for c, m in fort.local.veins.items()
                    if m == "adamantine")
        item = fort._mined_item(cell, fort._stone_here(cell))
        self.assertEqual(item.def_id, "ore")
        self.assertEqual(item.material, "adamantine")

    # -- magma behaving like magma ----------------------------------------- #

    def test_the_sea_stays_where_it_is(self):
        """Left alone, the deep is quiet. It is also cheap."""
        fort = self.fort
        before = fort.magma.total()
        for _ in range(200):
            fort.magma.step(fort.local)
        self.assertEqual(fort.magma.total(), before,
                         "the magma sea climbed out on its own")

    def test_the_deep_does_not_cost_the_game_anything(self):
        """Ten thousand cells of magma must not slow the fortress down."""
        import time

        fort = self.fort
        for _ in range(20):
            sim.step(fort)
        start = time.time()
        for _ in range(200):
            sim.step(fort)
        per_step = (time.time() - start) * 1000 / 200
        self.assertLess(per_step, 5.0,
                        "%.2f ms a step with a magma sea is too slow"
                        % per_step)

    def test_mining_into_the_pipe_lets_it_out(self):
        """The whole danger of the thing."""
        fort = self.fort
        tube = self._tube_cells(fort)
        wall = self._wall_beside(fort, tube)
        self.assertIsNotNone(wall, "the pipe has no rock around it")
        fort.dig_out(wall, "floor")
        for _ in range(300):
            sim.step(fort)
        loose = [c for c in fort.magma.depth
                 if c not in tube and c[2] > fort.magma_floor]
        self.assertTrue(loose, "digging into a magma pipe did nothing")
        self.assertTrue(fort.magma.flooded)

    def test_a_sealed_pipe_is_not_a_reason_to_run(self):
        """A corridor beside the pipe has magma one tile away all the way.

        Treating that as a threat makes every dwarf who walks down it turn
        round, walk back, turn round again, and die of thirst next to a
        barrel of ale. Only loose magma is worth running from.
        """
        fort = self.fort
        tube = self._tube_cells(fort)
        self.assertTrue(tube)
        beside = None
        for x, y, z in sorted(tube):
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                cand = (x + dx, y + dy, z)
                if cand not in tube and fort.magma.at(*cand) == 0:
                    beside = cand
                    break
            if beside:
                break
        self.assertIsNotNone(beside)
        self.assertFalse(dwarf_mod._magma_near(fort, beside),
                         "a sealed pipe next door counts as an emergency")
        fort.magma.set(beside, 0)
        loose = (beside[0], beside[1] + 1, beside[2])
        fort.magma.set(loose, 2)
        self.assertTrue(dwarf_mod._magma_near(fort, beside),
                        "loose magma next door does not count as one")

    def test_nothing_walkable_touches_the_magma(self):
        """Not even diagonally.

        Open magma beside a floor is held back by bookkeeping the player
        cannot see, and it makes a nonsense of both the map and the dwarves
        standing on it.
        """
        fort = self.fort
        lm = fort.local
        for (x, y, z) in fort.magma.depth:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1),
                           (-1, 1), (-1, -1)):
                side = (x + dx, y + dy, z)
                if not lm.in_bounds(*side) or fort.magma.at(*side) > 0:
                    continue
                self.assertFalse(lm.walkable(*side),
                                 "%s is walkable and touches magma at %s"
                                 % (side, (x, y, z)))

    def test_magma_kills_what_stands_in_it(self):
        """Wading is not an option at any depth."""
        fort = self.fort
        d = fort.dwarves()[0]
        fort.magma.set((d.x, d.y, d.z), 2)
        sim.step(fort)
        self.assertTrue(d.body.dead)
        self.assertEqual(d.body.death_cause, "burned to death")

    def test_dwarves_will_not_path_through_magma(self):
        """Not even a puddle of it."""
        fort = self.fort
        d = fort.dwarves()[0]
        here = (d.x, d.y, d.z)
        first = [c for c, _cost in fort.path_neighbours(here)]
        self.assertTrue(first)
        fort.magma.set(first[0], 1)
        again = [c for c, _cost in fort.path_neighbours(here)]
        self.assertNotIn(first[0], again)

    def test_magma_and_water_make_obsidian(self):
        """The oldest trick in the fortress."""
        fort = self.fort
        d = fort.dwarves()[0]
        cell = (d.x + 2, d.y, d.z)
        fort.magma.set(cell, 5)
        fort.water.set((cell[0] + 1, cell[1], cell[2]), 5)
        cast = self.fluids.quench(fort.magma, fort.water, fort.local)
        self.assertIn(cell, cast)
        self.assertEqual(fort.local.tile(*cell), "obsidian_wall")
        self.assertEqual(fort.magma.at(*cell), 0)

    def test_goods_in_magma_burn_except_the_one_thing(self):
        """Adamantine is the exception to most things."""
        from ascii_warriors.game.item import Item

        fort = self.fort
        d = fort.dwarves()[0]
        cell = (d.x + 3, d.y, d.z)
        fort.drop_item(Item("boulder", "granite"), *cell)
        fort.drop_item(Item("bar", "adamantine"), *cell)
        fort.magma.set(cell, 4)
        sim._burn_items(fort)
        left = [i.def_id for i in fort.items_at(*cell)]
        self.assertEqual(left, ["bar"])

    # -- the industry it pays for ------------------------------------------ #

    def test_a_magma_workshop_needs_magma_under_it(self):
        """That is the entire engineering problem, in one rule."""
        fort = self.fort
        d = fort.dwarves()[0]
        ok, why = building_mod.can_place(fort.local, "magma_smelter",
                                         d.x, d.y, d.z, fort.buildings,
                                         fort.magma)
        self.assertFalse(ok)
        self.assertIn("magma", why.lower())

    def test_magma_workshops_work_without_fuel(self):
        """The reward for getting the magma where you wanted it."""
        smelt = production.RECIPES["magma_smelt_ore"]
        self.assertEqual(smelt.workshop, "magma_smelter")
        self.assertNotIn("FUEL", [req for req, _n in smelt.inputs])
        forge = production.RECIPES["magma_iron_axe"]
        self.assertEqual(forge.workshop, "magma_forge")
        self.assertNotIn("FUEL", [req for req, _n in forge.inputs])

    # -- and what is under it ---------------------------------------------- #

    def test_breaching_the_spire_lets_them_out(self):
        """Dig too greedily and too deep."""
        fort = self.fort
        cell = sorted(fort.hollow)[0]
        before = len(fort.hostiles())
        fort.dig_out(cell, "floor")
        self.assertTrue(fort.breached)
        demons = [c for c in fort.hostiles() if c.defn.id == "demon"]
        self.assertGreater(len(demons), before)
        self.assertTrue(any("hollow" in m.text.lower()
                            for m in fort.log.all()))

    def test_the_world_hears_about_the_pit(self):
        """It is the last thing that happens, so it goes in the legends."""
        fort = self.fort
        before = len(fort.world.events)
        fort.dig_out(sorted(fort.hollow)[0], "floor")
        told = [e for e in fort.world.events[before:]
                if "demons" in e.text.lower()]
        self.assertTrue(told)

    def test_the_pit_keeps_giving(self):
        """There is no closing it, which is the point of the adamantine."""
        fort = self.fort
        fort.dig_out(sorted(fort.hollow)[0], "floor")
        first = len([c for c in fort.hostiles() if c.defn.id == "demon"])
        sim.spawn_demons(fort, fort.breach_cell, wave=2)
        self.assertGreater(
            len([c for c in fort.hostiles() if c.defn.id == "demon"]), first)

    def test_the_deep_survives_a_save(self):
        """Magma, the pit and the hollow all have to come back."""
        fort = self.fort
        fort.magma.set((fort.dwarves()[0].x + 4, fort.dwarves()[0].y,
                        fort.dwarves()[0].z), 3)
        again = Fortress.from_dict(fort.to_dict())
        self.assertEqual(again.magma.total(), fort.magma.total())
        self.assertEqual(again.hollow, fort.hollow)
        self.assertEqual(again.magma_floor, fort.magma_floor)
        self.assertEqual(again.breached, fort.breached)


class TestLivingWorld(unittest.TestCase):
    """The world outside the fortress keeps happening."""

    def setUp(self):
        from ascii_warriors.world import history as history_mod
        from ascii_warriors.world import livingworld

        self.history = history_mod
        self.lw = livingworld

    def _beast(self, fort):
        """A megabeast in the world's history, alive right now."""
        beast = self.lw.wandering_beast(fort.world, fort.rng, fort.time.year)
        if beast is None:
            beast = self.history._spawn_megabeast(fort.world, fort.rng,
                                                  fort.time.year)
        return beast

    def test_a_season_passing_moves_the_world(self):
        """The fortress clock drives world history, not just its own."""
        fort = embark("seasons")
        before = len(fort.world.events)
        for _ in range(6):
            fort.time.advance(TICKS_PER_DAY * 95)
            sim.step(fort)
        self.assertGreater(len(fort.world.events), before,
                           "a year and a half passed and the world did not")

    def test_travellers_bring_word(self):
        """What happens out there has to reach the player."""
        fort = embark("word")
        for _ in range(12):
            sim._world_turns(fort)
            fort.time.advance(TICKS_PER_DAY * 95)
        self.assertTrue(
            any("word" in m.text.lower() for m in fort.log.all()),
            "three years of world history and nobody mentioned any of it")

    def test_the_caravan_brings_news(self):
        """Traders have walked a long way and seen things on the road."""
        fort = embark("caravannews")
        self.history.record(fort.world, fort.time.year, "site_destroyed",
                            "Testfall was destroyed by a very large frog.")
        sim._caravan_news(fort)
        self.assertTrue(any("very large frog" in m.text
                            for m in fort.log.all()))

    def test_a_megabeast_arrives_with_its_history(self):
        """Not a generic monster: the one from the legends screen."""
        fort = embark("beast")
        beast = self._beast(fort)
        foe = sim.spawn_beast(fort, beast)
        self.assertIsNotNone(foe)
        self.assertEqual(foe.hf_id, beast.id)
        self.assertEqual(foe.name, beast.name)
        self.assertEqual(foe.faction, "hostile")
        self.assertIn(foe.id, fort.creatures)

    def test_one_legend_at_a_time(self):
        """Two copies of the same beast is a bookkeeping error with teeth."""
        fort = embark("onebeast")
        fort.wealth = 100000
        sim.spawn_beast(fort, self._beast(fort))
        for _ in range(40):
            sim._maybe_beast(fort)
        named = [c for c in fort.creatures.values()
                 if c.hf_id is not None and not c.body.dead]
        self.assertEqual(len(named), 1, [c.name for c in named])

    def test_a_poor_fortress_is_beneath_notice(self):
        """Nothing legendary walks across a continent for seven dwarves."""
        fort = embark("poorbeast")
        fort.wealth = 0
        for _ in range(50):
            sim._maybe_beast(fort)
        self.assertEqual([c for c in fort.creatures.values()
                          if c.hf_id is not None], [])

    def test_killing_a_beast_writes_the_fortress_into_the_legends(self):
        """The biggest thing a fortress ever does should be remembered."""
        fort = embark("slain")
        beast = self._beast(fort)
        foe = sim.spawn_beast(fort, beast)
        before = len(fort.world.events)
        foe.body.death_cause = "slain by the militia"
        fort.kill_creature(foe)
        fig = fort.world.figures[beast.id]
        self.assertEqual(fig.died, fort.time.year)
        told = [e for e in fort.world.events[before:] if e.kind == "beast_slain"]
        self.assertTrue(told, "the world never heard about it")
        self.assertIn(fort.name, told[0].text)

    def test_a_dead_beast_is_not_killed_twice(self):
        """A second death would rewrite the first one's date."""
        fort = embark("slaintwice")
        beast = self._beast(fort)
        foe = sim.spawn_beast(fort, beast)
        fort.kill_creature(foe)
        year = fort.world.figures[beast.id].died
        fort.time.advance(TICKS_PER_DAY * 400)
        fort._record_kill(foe)
        self.assertEqual(fort.world.figures[beast.id].died, year)


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

        commands = set("dbpnwujzotk?+-<>mhL")
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
                # A hospital is beds, bandages and somebody who knows what
                # they are doing. With nobody trained, whether a bleeding
                # dwarf lives is a coin flip on the fumble roll, and this
                # helper is used to test the hospital, not the dice.
                d.skills.set_level("wound_dressing", 5)
                d.skills.set_level("diagnose", 4)
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
        # The doctor starts next to the patient. Whether one can cross the
        # fortress before a four-point bleed finishes is the next test's
        # question; this one is about the chain working at all, and a race
        # against the clock decided by where everybody happened to be
        # standing tests the map, not the hospital.
        from ascii_warriors.game.item import Item

        doctor = fort.dwarves()[0]
        doctor.x, doctor.y, doctor.z = patient.x + 1, patient.y, patient.z
        # Bandages within reach as well. A doctor that has to cross the
        # fortress for supplies loses the race against a four-point bleed
        # every time, which is a fact about hospital layout, not about
        # whether treatment works.
        fort.drop_item(Item("bandage", "pig_tail_cloth", count=4),
                       patient.x, patient.y, patient.z)
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


class TestRooms(unittest.TestCase):
    """Furnished space, and what it is worth to whoever lives in it."""

    def setUp(self):
        from ascii_warriors.fortress import rooms

        self.rooms = rooms
        self.fort = embark("rooms")

    def _furnish(self, kinds):
        """Put furniture down around one spot and call it built."""
        spot = _open_spot(self.fort, "bed")
        self.assertIsNotNone(spot, "nowhere to furnish")
        first = None
        for i, kind in enumerate(kinds):
            b = Building(kind, spot[0] + i % 3, spot[1] + i // 3, spot[2])
            b.built = True
            self.fort.buildings.append(b)
            first = first or b
        return first

    def test_a_bare_bed_is_a_meagre_room(self):
        """One bed in a corridor is not a bedroom to be proud of."""
        bed = self._furnish(["bed"])
        room = self.rooms.measure(self.fort, bed)
        self.assertEqual(room.kind, "bedroom")
        self.assertLess(room.quality, 26)

    def test_furniture_improves_a_room(self):
        """More in it, better it is.

        Measured on the same bed in the same place: two rooms in two different
        corners of the map differ for reasons that have nothing to do with
        what is in them.
        """
        bed = self._furnish(["bed"])
        bare = self.rooms.measure(self.fort, bed)
        for i, kind in enumerate(("cabinet", "coffer", "statue")):
            extra = Building(kind, bed.x + 1 + i, bed.y, bed.z)
            extra.built = True
            self.fort.buildings.append(extra)
        rich = self.rooms.measure(self.fort, bed)
        self.assertGreater(rich.quality, bare.quality)
        self.assertLessEqual(rich.thought, bare.thought)

    def test_a_better_room_is_a_better_thought(self):
        """Quality has to translate into happiness or it means nothing."""
        bed = self._furnish(["bed"])
        for i, kind in enumerate(("cabinet", "coffer", "statue", "statue")):
            extra = Building(kind, bed.x + 1 + i, bed.y, bed.z)
            extra.built = True
            self.fort.buildings.append(extra)
        rich = self.rooms.measure(self.fort, bed)
        self.assertLess(rich.thought, 0)

    def test_a_room_does_not_swallow_the_map(self):
        """A bed in the open does not claim the whole level as its bedroom."""
        bed = self._furnish(["bed"])
        room = self.rooms.measure(self.fort, bed)
        self.assertLessEqual(len(room.cells), 100)

    def test_quality_names_cover_every_value(self):
        """The naming ladder must not have a hole in it."""
        for quality in range(0, 120, 3):
            self.assertTrue(self.rooms.quality_name(quality))

    def test_a_dwarf_with_a_bed_has_a_bedroom(self):
        """The link between an assigned bed and the room around it."""
        bed = self._furnish(["bed", "cabinet"])
        d = self.fort.dwarves()[0]
        bed.owner = d.id
        d.fort.bed = bed.id
        room = self.rooms.room_of(self.fort, d)
        self.assertIsNotNone(room)
        self.assertEqual(room.kind, "bedroom")


class TestNobles(unittest.TestCase):
    """Appointments, mandates and tempers."""

    def setUp(self):
        from ascii_warriors.fortress import nobles

        self.nobles = nobles

    def test_positions_appear_with_population(self):
        """A fortress of seven has a leader and nothing else."""
        fort = embark("court")
        sim._appointments(fort)
        self.assertIsNotNone(fort.court.holder("expedition_leader"))
        self.assertIsNone(fort.court.holder("mayor"))

    def test_a_big_fortress_appoints_a_mayor(self):
        """And the mayor immediately wants something."""
        fort = embark("mayor")
        sim.migrants(fort, 18)
        sim._appointments(fort)
        mayor = fort.court.noble("mayor")
        self.assertIsNotNone(mayor)
        self.assertIsNotNone(mayor.mandate)
        self.assertTrue(mayor.mandate.get("text"))
        # And it is for something the fortress does not already have.
        self.assertFalse(self.nobles.mandate_met(fort, mayor.mandate))

    def test_a_mandate_can_be_satisfied(self):
        """Building the thing clears the demand and pleases the mayor."""
        fort = embark("mandate")
        sim.migrants(fort, 18)
        sim._appointments(fort)
        mayor = fort.court.noble("mayor")
        self.assertIsNotNone(mayor.mandate)
        mayor.mandate = {"target": "statue", "kind": "building",
                         "text": "A statue.", "deadline": fort.ticks + 99999}
        statue = Building("statue", 4, 4, fort.z)
        statue.built = True
        fort.buildings.append(statue)
        sim._appointments(fort)
        self.assertIsNone(mayor.mandate)

    def test_one_dwarf_holds_one_position(self):
        """Nobody is both mayor and sheriff."""
        fort = embark("onejob")
        sim.migrants(fort, 20)
        sim._appointments(fort)
        holders = [n.dwarf_id for n in fort.court.nobles]
        self.assertEqual(len(holders), len(set(holders)))

    def test_a_dead_noble_is_replaced(self):
        """The post outlives the dwarf."""
        fort = embark("succession")
        sim._appointments(fort)
        leader_id = fort.court.holder("expedition_leader")
        fort.creatures[leader_id].body.dead = True
        sim._appointments(fort)
        self.assertNotEqual(fort.court.holder("expedition_leader"), leader_id)

    def test_a_miserable_dwarf_throws_a_tantrum(self):
        """Unhappiness has to do something or it is just a number."""
        fort = embark("tantrum")
        table = Building("table", *_open_spot(fort, "table"))
        table.built = True
        fort.buildings.append(table)
        d = fort.dwarves()[0]
        d.needs.stress = self.nobles.STRESS_TANTRUM + 5
        for _ in range(40000):
            sim._tantrums(fort)
            if any("tantrum" in m.text for m in fort.log.all()):
                break
        self.assertTrue(any("tantrum" in m.text for m in fort.log.all()))

    def test_a_berserk_dwarf_becomes_the_enemy(self):
        """The last stage of a bad season."""
        fort = embark("berserk")
        d = fort.dwarves()[0]
        d.needs.stress = self.nobles.STRESS_BERSERK + 10
        for _ in range(40000):
            sim._tantrums(fort)
            if fort.hostiles():
                break
        self.assertEqual(len(fort.hostiles()), 1)
        self.assertNotIn(d, fort.dwarves())
        sim.run(fort, 50)  # and the fortress keeps running

    def test_the_court_survives_a_save(self):
        """Appointments and mandates come back."""
        fort = embark("courtsave")
        sim._appointments(fort)
        fort.court.appoint("mayor", fort.dwarves()[1].id, fort.ticks)
        fort.court.noble("mayor").mandate = {
            "target": "statue", "kind": "building", "text": "A statue.",
            "deadline": 999}
        again = Fortress.from_dict(fort.to_dict())
        self.assertEqual(len(again.court.nobles), len(fort.court.nobles))
        self.assertEqual(again.court.holder("mayor"),
                         fort.court.holder("mayor"))
        self.assertEqual(again.court.noble("mayor").mandate["target"], "statue")


class TestLegacy(unittest.TestCase):
    """A fortress that ends becomes a place."""

    def _ended_fortress(self, seed="legacy"):
        """Build a little, then abandon it.

        On a private copy of the world: recording a fortress adds a site, and
        a site changes where every later test would choose to embark.
        """
        fort = embark(seed)
        dig_room(fort, 5)
        for kind in ("carpenter", "bed", "statue"):
            spot = _open_spot(fort, kind)
            if spot is not None:
                fort.buildings.append(Building(kind, *spot))
        sim.run(fort, 2000)
        fort.artifacts.append({
            "name": "Goldenpeak", "native": "Kadolmomuz", "maker": "Urist",
            "item": "steel warhammer", "def_id": "warhammer",
            "material": "steel", "year": fort.time.year})
        fort.lost = True
        fort.loss_reason = "abandoned"
        return fort

    def test_ending_puts_the_fortress_on_the_world_map(self):
        """It becomes a site with a name and a founding date."""
        from ascii_warriors.fortress import legacy

        fort = self._ended_fortress()
        before = len(fort.world.sites)
        site = legacy.record(fort, abandoned=True)
        self.assertEqual(len(fort.world.sites), before + 1)
        self.assertEqual(site.name, fort.name)
        self.assertEqual((site.wx, site.wy), (fort.wx, fort.wy))
        self.assertEqual(fort.world.tile(fort.wx, fort.wy).site_id, site.id)

    def test_ending_writes_history(self):
        """Founding, ending and any artifacts all reach the legends."""
        from ascii_warriors.fortress import legacy

        fort = self._ended_fortress("history")
        events_before = len(fort.world.events)
        arts_before = len(fort.world.artifacts)
        legacy.record(fort, abandoned=True)
        self.assertGreaterEqual(len(fort.world.events), events_before + 3)
        self.assertEqual(len(fort.world.artifacts), arts_before + 1)
        texts = " ".join(e.text for e in fort.world.events)
        self.assertIn(fort.name, texts)
        self.assertIn("Goldenpeak", texts)

    def test_recording_happens_only_once(self):
        """Two endings must not create two sites."""
        fort = self._ended_fortress("once")
        sim.record_fall(fort, abandoned=True)
        sites = len(fort.world.sites)
        sim.record_fall(fort, abandoned=True)
        self.assertEqual(len(fort.world.sites), sites)

    def test_an_adventurer_can_walk_into_the_ruins(self):
        """The whole point: the map you dug is the map you walk into."""
        from ascii_warriors.engine.rng import RNG
        from ascii_warriors.fortress import legacy
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.state import Game

        fort = self._ended_fortress("visit")
        legacy.record(fort, abandoned=True)
        dug = sum(1 for z in fort.local.levels
                  for t in fort.local.levels[z] if t == "floor")

        player = make_creature(RNG("p"), "dwarf", faction="player")
        player.is_player = True
        game = Game(fort.world, player, RNG("adventure"))
        player.wx, player.wy = fort.wx, fort.wy
        game.enter_world_tile(fort.wx, fort.wy)

        self.assertEqual(game.local.width, fort.local.width)
        self.assertEqual(game.local.height, fort.local.height)
        self.assertEqual(game.local.zmin, fort.local.zmin)
        found = sum(1 for z in game.local.levels
                    for t in game.local.levels[z] if t == "floor")
        self.assertEqual(found, dug, "the corridors are not the ones you dug")
        self.assertTrue(game.local.walkable(player.x, player.y, player.z))

    def test_the_dead_are_still_there(self):
        """Your dwarves lie where they fell."""
        from ascii_warriors.engine.rng import RNG
        from ascii_warriors.fortress import legacy
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.state import Game

        fort = self._ended_fortress("dead")
        names = {c.name for c in fort.creatures.values()}
        legacy.record(fort, abandoned=True)
        player = make_creature(RNG("p"), "dwarf", faction="player")
        player.is_player = True
        game = Game(fort.world, player, RNG("adventure"))
        player.wx, player.wy = fort.wx, fort.wy
        game.enter_world_tile(fort.wx, fort.wy)
        found = {c.name for c in game.creatures.values()}
        self.assertTrue(names & found,
                        "none of the fortress's dwarves are in the ruins")

    def test_ordinary_tiles_still_generate_normally(self):
        """Preserving one square must not preserve the whole world."""
        from ascii_warriors.engine.rng import RNG
        from ascii_warriors.fortress import legacy
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.state import Game

        fort = self._ended_fortress("normal")
        legacy.record(fort, abandoned=True)
        player = make_creature(RNG("p"), "dwarf", faction="player")
        player.is_player = True
        game = Game(fort.world, player, RNG("adventure"))
        wx = fort.wx - 3 if fort.wx >= 3 else fort.wx + 3
        player.wx, player.wy = wx, fort.wy
        game.enter_world_tile(wx, fort.wy)
        self.assertNotEqual(game.local.width, fort.local.width)

    def test_the_preserved_map_survives_a_world_save(self):
        """The ruins have to be in the save, or they vanish on reload."""
        from ascii_warriors.fortress import legacy
        from ascii_warriors.world.worldgen import World

        fort = self._ended_fortress("worldsave")
        legacy.record(fort, abandoned=True)
        again = World.from_dict(fort.world.to_dict())
        payload = again.preserved_map(fort.wx, fort.wy)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["name"], fort.name)
        self.assertTrue(legacy.describe(payload))


class TestWater(unittest.TestCase):
    """Water that moves, and the engineering that controls it."""

    def setUp(self):
        from ascii_warriors.world import fluids

        self.fluids = fluids

    def _sealed_room(self, fort, size=3):
        """Wall a small chamber off underground and return its floor cells.

        Built rather than dug: the caverns leave no block of rock big enough
        to hollow out, and a chamber with a way out is no test at all — water
        drains through the hole and a drowning dwarf simply walks away.
        """
        lm = fort.local
        for z in range(lm.zmin + 2, lm.zmax - 2):
            for y in range(2, lm.height - size - 3):
                for x in range(2, lm.width - size - 3):
                    cells = [(x + dx, y + dy, z)
                             for dx in range(size) for dy in range(size)]
                    if any(not lm.walkable(*c) or lm.is_outside(*c)
                           for c in cells):
                        continue
                    for dx in range(-1, size + 1):
                        for dy in range(-1, size + 1):
                            side = (x + dx, y + dy, z)
                            if side not in cells:
                                lm.set_tile(*side, "rock_wall")
                            lm.set_tile(x + dx, y + dy, z + 1, "rock_wall")
                            # Two levels of rock underneath, so a test can
                            # open the floor and the water still has a bottom.
                            lm.set_tile(x + dx, y + dy, z - 1, "rock_wall")
                            lm.set_tile(x + dx, y + dy, z - 2, "rock_wall")
                    fort._water_cache = None
                    fort.water.wake_all()
                    return cells
        return []

    # -- the fluid layer --------------------------------------------------- #

    def test_water_falls(self):
        """It goes down before it goes sideways."""
        fort = embark("falls")
        room = self._sealed_room(fort, 3)
        self.assertTrue(room)
        top = room[0]
        below = (top[0], top[1], top[2] - 1)
        fort.dig_out(below, "floor")
        fort.water.set(top, 4)
        for _ in range(6):
            fort.water.step(fort.local)
        self.assertGreater(fort.water.at(*below), 0,
                           "water did not fall into the space below it")

    def test_water_spreads(self):
        """A deep pile evens out with its neighbours."""
        fort = embark("spread")
        room = self._sealed_room(fort, 3)
        self.assertTrue(room)
        fort.water.set(room[4], 7)
        for _ in range(20):
            fort.water.step(fort.local)
        wet = sum(1 for c in room if fort.water.at(*c) > 0)
        self.assertGreater(wet, 1, "the water never spread at all")

    def test_water_is_conserved_when_it_has_nowhere_to_go(self):
        """A sealed room holds exactly what you poured into it."""
        fort = embark("conserve")
        room = self._sealed_room(fort, 3)
        self.assertTrue(room)
        # Seal the floor below so nothing drains away.
        fort.water.sources.clear()
        fort.water.infinite.clear()
        fort.water.depth.clear()
        fort.water.set(room[4], 6)
        before = fort.water.total()
        for _ in range(30):
            fort.water.step(fort.local)
        self.assertLessEqual(fort.water.total(), before)

    def test_a_river_does_not_flood_the_map_on_its_own(self):
        """Left alone, natural water stays exactly where it is."""
        fort = embark("river")
        before = fort.water.total()
        for _ in range(300):
            fort.water.step(fort.local)
        self.assertEqual(fort.water.total(), before,
                         "the river crept across the countryside")

    def test_only_an_opening_breaks_the_bank(self):
        """A mason smoothing a wall must not flood the fortress.

        Every job that changes a tile goes through dig_out: digging, but also
        smoothing, laying a farm plot, gathering plants. Only the ones that
        actually open the rock up may break the bank, or the river pours over
        its own shore because somebody polished a wall beside it.
        """
        fort = embark("bank")
        lm = fort.local
        self.assertTrue(fort.water.sealed, "this embark has no natural water")

        # A stretch of bank with solid rock beside it: where a player would
        # dig the trench that brings the river indoors.
        shore = wall = None
        for cell in sorted(fort.water.sealed):
            x, y, z = cell
            for side in ((x - 1, y, z), (x + 1, y, z),
                         (x, y - 1, z), (x, y + 1, z)):
                if not lm.in_bounds(*side) or self.fluids.can_hold(lm, side):
                    continue
                shore, wall = cell, side
                break
            if wall is not None:
                break
        self.assertIsNotNone(wall, "no solid rock beside the water at all")

        before = fort.water.total()
        fort.dig_out(wall, "wall_constructed")   # smoothed, still a wall
        self.assertIn(shore, fort.water.sealed)
        for _ in range(30):
            fort.water.step(lm)
        self.assertEqual(fort.water.total(), before,
                         "the bank leaked without anybody digging it")

        fort.dig_out(wall, "floor")              # and now cut into it
        self.assertNotIn(shore, fort.water.sealed)
        for _ in range(30):
            fort.water.step(lm)
        self.assertGreater(fort.water.total(), before,
                           "digging into the bank let nothing in")

    def test_the_water_step_is_cheap(self):
        """It runs every simulation step, so it has to be nearly free."""
        import time

        fort = embark("cheap")
        for _ in range(20):
            fort.water.step(fort.local)
        start = time.time()
        for _ in range(200):
            fort.water.step(fort.local)
        per_step = (time.time() - start) * 1000 / 200
        self.assertLess(per_step, 5.0,
                        "%.2f ms per water step is too slow" % per_step)

    def test_water_survives_a_save(self):
        """Depths, sources and the sealed bank all come back."""
        fort = embark("watersave")
        room = self._sealed_room(fort, 3)
        if room:
            fort.water.set(room[0], 5)
            fort.water.add_source(room[1], 1)
        again = Fortress.from_dict(fort.to_dict())
        self.assertEqual(again.water.total(), fort.water.total())
        self.assertEqual(again.water.sources, fort.water.sources)
        self.assertEqual(len(again.water.infinite), len(fort.water.infinite))

    # -- aquifers ---------------------------------------------------------- #

    def test_a_wet_site_has_an_aquifer(self):
        """The test world is rainy, so this should nearly always fire."""
        found = [len(embark("aq%d" % i).aquifer) for i in range(3)]
        self.assertTrue(any(n > 0 for n in found),
                        "no aquifer on any of three wet embarks")

    def test_breaching_an_aquifer_floods_and_warns(self):
        """Digging into wet rock is supposed to be a disaster."""
        fort = embark("breach")
        if not fort.aquifer:
            self.skipTest("this embark has no aquifer")
        cell = sorted(fort.aquifer)[len(fort.aquifer) // 2]
        before = fort.water.total()
        fort.dig_out(cell, "floor")
        self.assertIn(cell, fort.water.sources)
        sim.run(fort, 60)
        self.assertGreater(fort.water.total(), before)
        self.assertTrue(any("aquifer" in m.text.lower()
                            for m in fort.log.all()))

    def test_a_breached_aquifer_does_not_stop_at_a_puddle(self):
        """The leak has to keep working its way outward.

        Water levels out to within one unit of itself and then has nothing
        worth moving. An aquifer has a whole rock layer of pressure behind
        it, so it must push past that: otherwise breaching one leaves a
        puddle and a shrug, and the danger the layer exists for never lands.
        """
        fort = embark("puddle")
        if not fort.aquifer:
            self.skipTest("this embark has no aquifer")
        cell = sorted(fort.aquifer)[len(fort.aquifer) // 2]
        fort.dig_out(cell, "floor")
        for _ in range(200):
            fort.water.step(fort.local)
        early = fort.water.total()
        for _ in range(400):
            fort.water.step(fort.local)
        self.assertGreater(fort.water.total(), early, "the leak sealed itself")

    # -- drowning ---------------------------------------------------------- #

    def test_a_dwarf_drowns_in_a_flooded_room(self):
        """Deep water kills."""
        fort = embark("drowned")
        room = self._sealed_room(fort, 3)
        self.assertTrue(room)
        d = fort.dwarves()[0]
        d.x, d.y, d.z = room[4]
        fort.water.add_source(room[4], 7)
        for _ in range(60):
            sim.step(fort)
            if d.body.dead:
                break
        self.assertTrue(d.body.dead)
        self.assertEqual(d.body.death_cause, "drowned")

    def test_dwarves_will_not_path_through_deep_water(self):
        """Wading is fine; swimming with a rock is not."""
        from ascii_warriors.world.fluids import SWIM_DEPTH

        fort = embark("nopath")
        d = fort.dwarves()[0]
        here = (d.x, d.y, d.z)
        neighbours = [c for c, _cost in fort.path_neighbours(here)]
        self.assertTrue(neighbours)
        flooded = neighbours[0]
        fort.water.set(flooded, SWIM_DEPTH + 1)
        again = [c for c, _cost in fort.path_neighbours(here)]
        self.assertNotIn(flooded, again)

    # -- levers and gates -------------------------------------------------- #

    def _gate_and_lever(self, fort):
        """Build a floodgate and a lever, already linked."""
        gate = Building("floodgate", *_open_spot(fort, "floodgate"))
        gate.built = True
        fort.buildings.append(gate)
        fort.set_gate(gate, True)
        lever = Building("lever", *_open_spot(fort, "lever"))
        lever.built = True
        fort.buildings.append(lever)
        fort.link(lever, gate)
        return lever, gate

    def test_every_gate_kind_has_both_its_tiles(self):
        """A gate with a missing tile would vanish when it opened."""
        from ascii_warriors.fortress.buildings import GATE_TILES, KINDS
        from ascii_warriors.world import tiles as tile_data

        for kind, (open_tile, shut_tile) in GATE_TILES.items():
            self.assertIn(kind, KINDS)
            self.assertTrue(tile_data.exists(open_tile), kind)
            self.assertTrue(tile_data.exists(shut_tile), kind)
            self.assertTrue(tile_data.get(open_tile).walk, kind)
            # The shut state must stop water, which is what a gate is for.
            shut = tile_data.get(shut_tile)
            blocks = not shut.walk or (shut.has("DOOR") and not shut.has("OPEN"))
            self.assertTrue(blocks, "%s does not hold water when shut" % kind)

    def test_pulling_a_lever_opens_a_gate(self):
        """And pulling it again shuts it."""
        fort = embark("lever")
        lever, gate = self._gate_and_lever(fort)
        self.assertTrue(gate.shut)
        self.assertFalse(fort.local.walkable(*gate.center))
        fort.pull_lever(lever)
        self.assertFalse(gate.shut)
        self.assertTrue(fort.local.walkable(*gate.center))
        fort.pull_lever(lever)
        self.assertTrue(gate.shut)
        self.assertFalse(fort.local.walkable(*gate.center))

    def test_a_gate_is_built_in_the_state_its_tile_shows(self):
        """A drawbridge is finished lying down, a floodgate finished shut.

        The flag and the tile have to agree, or the first pull of the lever
        sets the flag the way it already looked and appears to do nothing.
        """
        fort = embark("gatebuild")
        for kind, shut in (("drawbridge", False), ("floodgate", True)):
            gate = Building(kind, *_open_spot(fort, kind))
            fort.buildings.append(gate)
            d = fort.dwarves()[0]
            job = fort.jobs.make("build", *gate.center, target=gate.id)
            fort._finish_build(d, job)
            self.assertEqual(gate.shut, shut, kind)
            self.assertEqual(fort.local.tile(*gate.center), gate.gate_tile(),
                             kind)

    def test_a_dwarf_pulls_a_requested_lever(self):
        """The player asks; somebody walks over and does it."""
        fort = embark("pull")
        lever, gate = self._gate_and_lever(fort)
        lever.pending = True
        sim.run(fort, 600)
        self.assertFalse(lever.pending, "nobody ever pulled the lever")
        self.assertFalse(gate.shut)

    def test_a_shut_gate_holds_water_back(self):
        """The entire point of a floodgate."""
        fort = embark("holdback")
        room = self._sealed_room(fort, 3)
        self.assertTrue(room)
        # Put a floodgate in the doorway of a flooded cell's only exit.
        gate = Building("floodgate", *room[0])
        gate.built = True
        fort.buildings.append(gate)
        fort.set_gate(gate, True)
        fort.water.set(room[4], 6)
        for _ in range(30):
            fort.water.step(fort.local)
        self.assertEqual(fort.water.at(*room[0]), 0,
                         "water got through a shut floodgate")

    def test_linking_toggles(self):
        """Linking a lever twice unlinks it."""
        fort = embark("link")
        lever, gate = self._gate_and_lever(fort)
        self.assertIn(gate.id, lever.links)
        fort.link(lever, gate)
        self.assertNotIn(gate.id, lever.links)

    def test_levers_survive_a_save(self):
        """Links and gate states come back."""
        fort = embark("leversave")
        lever, gate = self._gate_and_lever(fort)
        fort.pull_lever(lever)
        again = Fortress.from_dict(fort.to_dict())
        back_lever = next(b for b in again.buildings if b.kind == "lever")
        back_gate = next(b for b in again.buildings if b.kind == "floodgate")
        self.assertEqual(back_lever.links, [back_gate.id])
        self.assertEqual(back_gate.shut, gate.shut)

    def test_a_mechanism_can_be_made(self):
        """Levers need mechanisms, so somebody has to be able to make one."""
        from ascii_warriors.data import items as item_data
        from ascii_warriors.fortress import production

        self.assertTrue(item_data.exists("mechanism"))
        recipe = production.RECIPES.get("mechanisms")
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.output, "mechanism")
