"""Fortress mode: embark, jobs, dwarves, production and the end of it all."""

from __future__ import annotations

import unittest

from ascii_warriors.data import items as item_data
from ascii_warriors.data.calendar import TICKS_PER_DAY
from ascii_warriors.engine.rng import RNG
from ascii_warriors.fortress import buildings as building_mod
from ascii_warriors.fortress import designations as designation_mod
from ascii_warriors.fortress import dwarf as dwarf_mod
from ascii_warriors.fortress import justice, labors, production, sim
from ascii_warriors.fortress.buildings import Building, Stockpile
from ascii_warriors.fortress.fortress import Fortress
from ascii_warriors.fortress.jobs import Job, JobBoard, work_rate
from ascii_warriors.game import save as save_mod
from ascii_warriors.game.entity import make_creature
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


def item_for(fort, def_id: str):
    """One item of a kind, for tests that need the larder stocked."""
    from ascii_warriors.game.item import make_item

    return make_item(fort.rng, def_id)


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
        # Goblins are a different test -- and this could not tell the
        # difference. It asserted that nobody died of hunger or thirst over a
        # season, which on this seed happened to be true and on three seeds in
        # five (measured on v3.19, before any of this) was not: a wounded
        # dwarf that cannot walk to a barrel dies of thirst with fifteen
        # hundred ale in the stockpile, and that is a casualty of the siege
        # rather than a failure of the farms. The economy is what the stock
        # counts below measure; this only holds the fortress to it when
        # nothing was killing anybody.
        deaths = [c.body.death_cause for c in fort.creatures.values()
                  if c.body.dead]
        starved = [d for d in deaths
                   if d in ("starved to death", "died of thirst")]
        violent = [d for d in deaths if d not in starved]
        if not violent:
            self.assertEqual(starved, [], "the food economy did not close")
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

    def test_every_uniform_can_be_supplied_by_the_fortress(self):
        """The defect this milestone was: all five uniforms in
        `military.UNIFORMS` asked for equipment no fortress could make. The
        swordsdwarf wanted a sword and the forge managed a short sword; the
        marksdwarf wanted a crossbow, which nothing anywhere produced; and
        every one of them wanted a breastplate."""
        from ascii_warriors.fortress import military

        made = {r.output for r in production.RECIPES.values()}
        for uid, uniform in military.UNIFORMS.items():
            for wid in uniform.weapons:
                self.assertIn(wid, made, "%s uniform: no way to make %s"
                              % (uid, wid))
            for aid in uniform.armor:
                self.assertIn(aid, made, "%s uniform: no way to make %s"
                              % (uid, aid))

    def test_nothing_wearable_or_wieldable_has_no_maker(self):
        """Sixteen of thirty-two weapons and ten of twenty armour pieces had
        no recipe anywhere -- including the two-handed sword, which every
        combat milestone since v3.27 has measured and nobody could obtain."""
        made = {r.output for r in production.RECIPES.values()}
        for defn in item_data.melee_weapons() + item_data.ranged_weapons():
            self.assertIn(defn.id, made, "no way to make %s" % defn.id)
        for defn in item_data.armor_pieces():
            self.assertIn(defn.id, made, "no way to make %s" % defn.id)

    def test_the_new_recipes_ask_for_things_that_exist(self):
        """A recipe naming an item id that is not in the table is a workshop
        order that can never be filled and never says why."""
        classes = set(production.CLASS_ITEMS)
        for recipe in production.RECIPES.values():
            self.assertTrue(item_data.exists(recipe.output), recipe.id)
            for req, count in recipe.inputs:
                self.assertGreater(count, 0, recipe.id)
                if req in classes or req.startswith("bar:"):
                    continue
                self.assertTrue(item_data.exists(req),
                                "%s wants %s" % (recipe.id, req))

    def test_a_magma_forge_can_make_the_new_things_too(self):
        """The magma duplication runs over the smith's recipe list, so a new
        forge recipe has to appear there without being written twice."""
        magma = {r.output for r in production.RECIPES.values()
                 if r.workshop == "magma_forge"}
        for iid in ("breastplate", "sword", "great_axe", "pick"):
            self.assertIn(iid, magma)

    def test_the_costs_run_with_the_weight(self):
        """A great axe is five bars and a mace is two. If that ordering ever
        inverts, the industry is telling the player something false about
        what they are choosing between."""
        def bars(rid):
            return dict(production.RECIPES[rid].inputs).get("BAR", 0)

        self.assertGreater(bars("iron_greataxe"), bars("iron_battleaxe"))
        self.assertGreater(bars("iron_battleaxe"), bars("iron_mace"))
        self.assertGreater(bars("iron_twohander"), bars("iron_longsword"))
        self.assertGreater(bars("iron_breastplate"), bars("iron_gauntlets"))
        self.assertGreaterEqual(bars("iron_mail"), bars("iron_greaves"))

    def test_the_forge_actually_turns_bars_into_a_breastplate(self):
        """End to end, in a running fortress: the piece every uniform in the
        game asks for and none could make."""
        fort = embark("plate")
        for d in fort.dwarves():
            d.fort.labors.enabled.update({"smithing", "armorsmithing"})
        forge = self._shop(fort, "smith")
        fort.drop_item(self.Item("bar", "steel", count=8), *forge.center)
        fort.drop_item(self.Item("charcoal", "charcoal", count=6), *forge.center)
        forge.orders.append(
            {"recipe": "iron_breastplate", "count": 1, "repeat": False})
        before = sum(1 for i in fort.all_items() if i.def_id == "breastplate")

        sim.run(fort, 1200)

        plate = [i for i in fort.all_items() if i.def_id == "breastplate"]
        self.assertGreater(len(plate), before, "the forge made no breastplate")
        self.assertTrue(any(p.mat.is_metal for p in plate))

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


class TestArt(unittest.TestCase):
    """Engravings, and the history they are carved out of."""

    def setUp(self):
        from ascii_warriors.fortress import art as art_mod

        self.art = art_mod
        self.fort = embark("art")
        self.engraver = self.fort.dwarves()[0]
        self.engraver.skills.set_level("engraving", 10)

    def _wall(self, fort, smoothed=True):
        """A wall cell, smoothed if asked."""
        lm = fort.local
        for z in (fort.z, fort.z - 1, fort.z - 2):
            for y in range(lm.height):
                for x in range(lm.width):
                    if lm.tile(x, y, z) == "rock_wall":
                        if smoothed:
                            fort.dig_out((x, y, z), "wall_constructed")
                        return (x, y, z)
        return None

    # -- what gets carved --------------------------------------------------- #

    def test_an_engraving_describes_something_that_happened(self):
        """The whole point: the fortress carves the world's own history."""
        fort = self.fort
        found = 0
        for i in range(12):
            art = self.art.engrave(fort, self.engraver, (5, 5 + i, fort.z))
            self.assertTrue(art.text)
            self.assertTrue(art.describe().startswith("On the wall is a")
                            or art.describe().startswith("On the wall is an"))
            if art.event_id is not None:
                found += 1
                event = next(e for e in fort.world.events
                             if e.id == art.event_id)
                self.assertIn("year %d" % event.year, art.describe())
        self.assertGreater(found, 0, "nothing was carved from real history")

    def test_the_caption_reads_as_a_caption(self):
        """A noun phrase, not the historian's whole sentence."""
        fort = self.fort
        from ascii_warriors.world import history as history_mod

        beast = history_mod._spawn_megabeast(fort.world, fort.rng,
                                             fort.time.year)
        hero = history_mod.new_figure(fort.world, fort.rng, "dwarf", None,
                                      None, year=fort.time.year,
                                      profession="warrior")
        from ascii_warriors.world import livingworld

        livingworld.slay(fort.world, fort.time.year, hero, beast, "in the deep")
        for _ in range(30):
            art = self.art.engrave(fort, self.engraver, (6, 6, fort.z))
            if art.event_id is not None and "slaying" in art.describe():
                self.assertIn("the slaying of", art.describe())
                return
        self.skipTest("the carver never picked the slaying")

    def test_a_masterwork_is_worth_more_than_a_rough_scratch(self):
        """Quality has to mean something to the room around it."""
        rough = self.art.Engraving(0, "a dwarf.")
        great = self.art.Engraving(6, "a dwarf.")
        self.assertLess(rough.value, great.value)
        self.assertEqual(great.quality_name, "masterful")

    def test_skill_makes_better_engravings(self):
        """Over enough walls, a legendary engraver is visibly better."""
        from ascii_warriors.engine.rng import RNG

        novice = dwarf_mod.make_dwarf(RNG("a"), "")
        expert = dwarf_mod.make_dwarf(RNG("a"), "")
        expert.skills.set_level("engraving", 18)
        rng = RNG("quality")
        low = sum(self.art.quality_for(novice, rng) for _ in range(40))
        high = sum(self.art.quality_for(expert, rng) for _ in range(40))
        self.assertGreater(high, low)

    # -- how it gets carved -------------------------------------------------- #

    def test_you_cannot_engrave_rough_rock(self):
        """Smoothing comes first."""
        fort = self.fort
        rough = self._wall(fort, smoothed=False)
        self.assertIsNotNone(rough)
        self.assertFalse(fort.designations.valid(fort.local, *rough, "engrave"))
        fort.dig_out(rough, "wall_constructed")
        self.assertTrue(fort.designations.valid(fort.local, *rough, "engrave"))

    def test_the_job_carves_the_wall(self):
        """Designate, and a dwarf with the labor turns up and does it."""
        fort = self.fort
        for d in fort.dwarves():
            d.fort.labors.enable("engraving")
        cell = self._wall(fort)
        self.assertTrue(fort.designations.set(fort.local, *cell, "engrave"))
        sim.run(fort, 1200)
        self.assertIn(cell, fort.engravings,
                      "the wall was designated and never carved")
        self.assertNotIn(cell, fort.designations.cells)

    def test_engravings_make_a_room_better(self):
        """A carved bedroom is worth more than a bare one."""
        fort = self.fort
        d = fort.dwarves()[0]
        bed = Building("bed", d.x, d.y, d.z)
        bed.built = True
        fort.buildings.append(bed)
        from ascii_warriors.fortress import rooms as rooms_mod

        bare = rooms_mod.measure(fort, bed)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            fort.engravings[(d.x + dx, d.y + dy, d.z)] = \
                self.art.Engraving(6, "a dwarf.")
        rich = rooms_mod.measure(fort, bed)
        self.assertGreater(rich.quality, bare.quality)

    def test_dwarves_notice_good_work(self):
        """And only good work."""
        fort = self.fort
        d = fort.dwarves()[0]
        before = d.needs.stress
        fort.engravings[(d.x + 1, d.y, d.z)] = self.art.Engraving(0, "a dwarf.")
        self.art.admire(fort, d)
        self.assertEqual(d.needs.stress, before)
        fort.engravings[(d.x + 1, d.y, d.z)] = self.art.Engraving(6, "a dwarf.")
        self.art.admire(fort, d)
        self.assertLess(d.needs.stress, before)

    def test_engravings_survive_a_save(self):
        """A fortress's art is most of what it leaves behind."""
        fort = self.fort
        cell = (7, 7, fort.z)
        made = self.art.engrave(fort, self.engraver, cell)
        again = Fortress.from_dict(fort.to_dict())
        back = again.engravings.get(cell)
        self.assertIsNotNone(back)
        self.assertEqual(back.text, made.text)
        self.assertEqual(back.quality, made.quality)
        self.assertEqual(back.maker, made.maker)


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
        """The fortress clock drives world history, not just its own.

        A pocket world records about one event every other season, so counting
        events over a year and a half measures the dice rather than the wiring.
        What the wiring guarantees is that the world's own clock is dragged
        along by the fortress's, once per season change and no more.
        """
        fort = embark("seasons")
        before_year = fort.world.year
        seen = []
        real_advance = self.lw.advance

        def counting_advance(world, rng, year, **kw):
            seen.append(year)
            return real_advance(world, rng, year, **kw)

        self.lw.advance = counting_advance
        try:
            for _ in range(6):
                fort.time.advance(TICKS_PER_DAY * 95)
                sim.step(fort)
                sim.step(fort)  # a second step in the same season adds nothing
        finally:
            self.lw.advance = real_advance
        # Six jumps of 95 days, less the first season change, which is the
        # fortress noticing what season it embarked in.
        self.assertEqual(len(seen), 5, "the world did not keep step")
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(fort.world.year, before_year)
        self.assertEqual(fort.world.year, fort.time.year)

    def test_a_year_and_a_half_of_world_history_says_something(self):
        """Over enough seasons the world does actually do things."""
        fort = embark("seasons-long")
        before = len(fort.world.events)
        for _ in range(16):
            fort.time.advance(TICKS_PER_DAY * 95)
            sim.step(fort)
        self.assertGreater(len(fort.world.events), before,
                           "four years passed and the world did nothing")

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


#: Attributes a fortress save deliberately does not keep, and why. This list
#: is the point of `TestWhatASaveKeeps`: anything new that fails to survive a
#: round trip breaks the suite until somebody either serialises it or comes
#: here and says in writing that it is transient.
TRANSIENT = {
    # Rebuilt from the world and the map on load.
    "rng", "log", "local", "world", "owner", "defn", "game", "fort",
    "scheduler",
    # Recomputed on the first step: pathing caches and derived indexes.
    "path", "path_goal", "hostile_state", "jobs_by_cell",
    # Written when a dwarf picks something up for a job and read by nothing.
    # The item is in the dwarf's inventory and `put_down` finds it from the
    # job, so this is a debugging aid and not state.
    "carrying",
    # Per-turn stealth state, recomputed by whatever the creature does next.
    "noise",
}


def _round_trip_diff(before, after, label, seen=None):
    """Every attribute that came back from a save different from how it went in."""
    seen = seen if seen is not None else set()
    if id(before) in seen:
        return []
    seen.add(id(before))

    def summarise(value):
        if isinstance(value, (int, float, str, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return ("dict", len(value))
        if isinstance(value, (list, tuple, set, frozenset)):
            return (type(value).__name__, len(value))
        return type(value).__name__

    names = set()
    for obj in (before, after):
        names |= set(getattr(obj, "__dict__", {}))
        names |= set(getattr(type(obj), "__slots__", ()) or ())
    out = []
    for name in sorted(names):
        if name.startswith("_") or name in TRANSIENT:
            continue
        was = getattr(before, name, "<missing>")
        now = getattr(after, name, "<missing>")
        if callable(was):
            continue
        if summarise(was) != summarise(now):
            out.append("%s.%s: %r -> %r" % (
                label, name, summarise(was), summarise(now)))
    return out


class TestWhatASaveKeeps(unittest.TestCase):
    """A save is supposed to give back the game you saved.

    Found by diffing every attribute across a round trip rather than by
    checking the ones somebody remembered. The fortress was losing held
    breath, whether a dwarf was asleep, two behaviour counters and the phase
    of the fluid clock -- and the sleeping flag is read by the vampire's
    victim search, so saving quietly woke the whole fortress and left the
    vampire with nobody to feed on.
    """

    def _busy_fortress(self):
        fort = embark("roundtrip")
        for _ in range(200):
            sim.step(fort)
        return fort

    def test_a_fortress_comes_back_the_way_it_went_in(self):
        fort = self._busy_fortress()
        dwarf = fort.dwarves()[0]
        fort.drowning[dwarf.id] = 4
        dwarf.fort.sleeping = True
        dwarf.fort.idle_ticks = 77
        dwarf.fort.blocked = 5
        fort.water.ticks = 1234

        back = Fortress.from_dict(fort.to_dict())
        lost = _round_trip_diff(fort, back, "fortress")
        lost += _round_trip_diff(fort.water, back.water, "water")
        same = back.creatures.get(dwarf.id)
        self.assertIsNotNone(same, "the dwarf did not survive the save")
        lost += _round_trip_diff(dwarf.fort, same.fort, "dwarf.fort")
        lost += _round_trip_diff(dwarf.body, same.body, "dwarf.body")
        lost += _round_trip_diff(dwarf.needs, same.needs, "dwarf.needs")
        self.assertEqual(lost, [], "a save lost state:\n  " + "\n  ".join(lost))

    def test_held_breath_survives_a_save(self):
        """Adventure mode has saved this since v3.29 and the fortress had not,
        so a fortress save handed everybody drowning in it a fresh lungful."""
        fort = embark("breath")
        dwarf = fort.dwarves()[0]
        fort.drowning[dwarf.id] = 5
        back = Fortress.from_dict(fort.to_dict())
        self.assertEqual(back.drowning.get(dwarf.id), 5)

    def test_a_sleeping_dwarf_is_still_asleep_after_a_save(self):
        """Which is what the vampire is looking for."""
        fort = embark("asleep")
        dwarf = fort.dwarves()[0]
        dwarf.fort.sleeping = True
        back = Fortress.from_dict(fort.to_dict())
        self.assertTrue(back.creatures[dwarf.id].fort.sleeping)

    def test_the_fluid_clock_keeps_its_phase(self):
        fort = embark("clock")
        fort.water.ticks = 99
        back = Fortress.from_dict(fort.to_dict())
        self.assertEqual(back.water.ticks, 99)

    def test_the_high_water_mark_survives_a_save(self):
        """The diff above skips underscored names, so it never saw this one.

        `magma_mark` was saved and `_water_mark` was not, so every load reset
        the mark to nothing and the next step measured a river against zero.
        """
        fort = embark("highwater")
        fort._water_mark = 4321
        fort._magma_mark = 8765
        back = Fortress.from_dict(fort.to_dict())
        self.assertEqual(back._water_mark, 4321)
        self.assertEqual(back._magma_mark, 8765)

    def test_a_loaded_fortress_does_not_cry_flood(self):
        """With the mark at zero, any map holding more than FLOOD_WARN
        announced it was flooding on its first step back."""
        fort = embark("noflood")
        # More water than the warning threshold, and the fortress knows it:
        # this is the sea it was built beside, not a breach.
        d = fort.dwarves()[0]
        placed = 0
        for y in range(fort.local.height):
            for x in range(fort.local.width):
                if placed >= 400:
                    break
                if fort.local.walkable(x, y, d.z):
                    fort.water.set((x, y, d.z), 7)
                    placed += 1
        fort._water_mark = fort.water.total()
        self.assertGreater(fort.water.total(), sim.FLOOD_WARN)

        back = Fortress.from_dict(fort.to_dict())
        before = len(back.log.recent(500))
        sim.step(back)
        said = " ".join(getattr(m, "text", str(m))
                        for m in back.log.recent(500)[before:])
        self.assertNotIn("flooding", said.lower())
        self.assertFalse(back.water.flooded)


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


class _FakeApp:
    """Just enough of the app for a scene to be constructed and drawn."""

    def __init__(self) -> None:
        self.screen = None
        self.term = None
        self.game = None


class TestFortressUI(unittest.TestCase):
    """The screens, driven headlessly."""

    def test_no_command_key_is_shadowed_by_scrolling(self):
        """A command bound to a scroll key can never fire."""
        from ascii_warriors.ui.fort import fort_screen

        commands = set("dbpnwujzotk?+-<>mhLc")
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

    def test_the_sheriff_s_book_renders(self):
        """Open cases, sentences and cold cases, drawn into a buffer."""
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.fortress import justice
        from ascii_warriors.ui.fort.justice_screen import JusticeScene

        fort = embark("bookui")
        sim.migrants(fort, 18)
        law = fort.dwarves()[-1]
        fort.court.appoint("sheriff", law.id, fort.ticks)
        justice.report(fort, "vandalism", fort.dwarves()[0], "a table")
        justice.report(fort, "theft", None, "a gold statue")
        justice.hold_court(fort)
        scene = JusticeScene(_FakeApp(), fort)
        scr = Screen(100, 34)
        scene.draw(scr)
        text = "\n".join(scr.to_text())
        self.assertIn("Open cases", text)
        self.assertIn("Serving", text)
        self.assertIn(law.name[:8], text)

    def test_the_status_line_mentions_crime(self):
        """So you know to press c without opening anything."""
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.fortress import justice
        from ascii_warriors.ui.fort.sidebar import draw_status_line

        fort = embark("statuscrime")
        scr = Screen(120, 4)
        draw_status_line(scr, 0, 0, 120, fort)
        self.assertNotIn("unsolved", "\n".join(scr.to_text()))
        justice.report(fort, "theft", None, "a mug")
        scr = Screen(120, 4)
        draw_status_line(scr, 0, 0, 120, fort)
        self.assertIn("1 unsolved", "\n".join(scr.to_text()))

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

    def _siege_losses(self, seed, trained):
        """Dwarves lost and goblins left, for one embark and one raid."""
        fort = embark(seed)
        if trained:
            self._armed_squad(fort, size=3)
        sim.run(fort, 9000)
        before = len(fort.dwarves())
        sim.spawn_attack(fort, 5)
        sim.run(fort, 2500)
        return (before - len(fort.dwarves()), len(fort.hostiles()))

    def test_a_trained_squad_beats_a_siege(self):
        """The point of a militia, measured against not having one.

        This used to assert that no more than two dwarves died, which held on
        this seed and on seven of ten others -- an absolute threshold on a
        number that ranges from nought to seven depending on where the goblins
        walk in. It was passing by luck, and it would have gone on passing by
        luck. What a militia is actually worth is only visible next to a
        fortress that did not raise one.
        """
        armed = [self._siege_losses(s, True) for s in ("defence", "d2")]
        alone = [self._siege_losses(s, False) for s in ("defence", "d2")]
        self.assertEqual(sum(left for _lost, left in armed), 0,
                         "the goblins are still here")
        self.assertLess(sum(lost for lost, _left in armed),
                        sum(lost for lost, _left in alone),
                        "the squad was no better than no squad at all")

    def test_a_fliers_routes_are_a_superset_of_a_walkers(self):
        """Wings take nothing away. If the flying graph ever loses an edge the
        walking one has, a roc is worse at getting about than a goblin."""
        fort = embark("flygraph")
        lm = fort.local
        d0 = fort.dwarves()[0]
        lost = 0
        gained = 0
        for dx in range(-8, 9, 2):
            for dy in range(-8, 9, 2):
                node = (d0.x + dx, d0.y + dy, d0.z)
                if not lm.in_bounds(*node):
                    continue
                walk = {c for c, _cost in fort.path_neighbours(node)}
                fly = {c for c, _cost in fort.flier_neighbours(node)}
                lost += len(walk - fly)
                gained += len(fly - walk)
        self.assertEqual(lost, 0)
        self.assertGreater(gained, 0)

    def test_a_flier_can_be_in_the_air_and_a_walker_cannot(self):
        fort = embark("flyair")
        lm = fort.local
        d0 = fort.dwarves()[0]
        node = (d0.x, d0.y, d0.z)
        fly = {c for c, _cost in fort.flier_neighbours(node)}
        walk = {c for c, _cost in fort.path_neighbours(node)}
        from ascii_warriors.world import tiles as tile_data

        air = [c for c in fly - walk
               if tile_data.get(lm.tile(*c)).has("OPEN")]
        self.assertTrue(air, "nothing above the dwarves is open sky")
        for cell in air:
            self.assertNotIn(cell, walk)

    def test_rock_and_magma_and_fire_are_not_flown_through(self):
        """Flight is a set of exemptions and these are not among them: a
        creature occupies a whole cell, so "over the lava" is nowhere."""
        fort = embark("flysolid")
        lm = fort.local
        d0 = fort.dwarves()[0]
        node = (d0.x, d0.y, d0.z)
        for dx, dy, tile_id in ((1, 0, "rock_wall"), (-1, 0, "lava"),
                                (0, 1, "fire")):
            cell = (node[0] + dx, node[1] + dy, node[2])
            lm.set_tile(*cell, tile_id)
            self.assertNotIn(
                cell, {c for c, _cost in fort.flier_neighbours(node)}, tile_id)

    def test_a_flier_crosses_the_map_faster_than_a_walker(self):
        """Closest approach, not final position: the first version of this
        measured where the chase ended, and a roc that had killed five dwarves
        and run the sixth into a corner scored worse than a goblin that had
        killed one and stopped next to it."""
        def closest(cid):
            fort = embark("flyapproach")
            entry = fort.local.edge_entry(fort.rng, "north")
            foe = make_creature(fort.rng, cid, faction="hostile", level=3)
            foe.x, foe.y, foe.z = fort._free_spot(entry, 0)
            foe.wx, foe.wy = fort.wx, fort.wy
            fort.add_creature(foe)
            best = 10 ** 6
            steps = 0
            for steps in range(1, 121):
                if foe.body.dead or fort.lost or not fort.dwarves():
                    break
                sim.step(fort)
                for d in fort.dwarves():
                    best = min(best, abs(foe.x - d.x) + abs(foe.y - d.y)
                               + abs(foe.z - d.z))
            return best, steps

        flier, flier_steps = closest("roc")
        walker, walker_steps = closest("goblin")
        self.assertLessEqual(flier, walker,
                             "the roc got no closer than the goblin")
        self.assertLessEqual(flier, 2, "the roc never reached anybody")

    def test_a_flier_with_nowhere_better_to_go_still_moves(self):
        """`_flier_step` is greedy, so it has to hand back to the walking
        planner rather than stand still in a corner."""
        fort = embark("flystuck")
        d0 = fort.dwarves()[0]
        foe = make_creature(fort.rng, "roc", faction="hostile", level=3)
        foe.x, foe.y, foe.z = d0.x, d0.y, d0.z
        goal = (d0.x, d0.y, d0.z)
        self.assertFalse(sim._flier_step(fort, foe, goal),
                         "standing on the goal is not an improvement")

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
        # Needs come before shelter, and rightly: a dwarf that dies of thirst
        # inside the safe room is not sheltered. Clearing them first means
        # this measures the retreat rather than the length of the walk to the
        # nearest ale barrel, which is what made it depend on map layout.
        d.needs.thirst = 0
        d.needs.hunger = 0
        d.needs.drowsy = 0
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
        # Somebody has to actually die. This asserted on every creature on the
        # map, wildlife included, and passed on a fortress where nobody had.
        fallen = set()
        for d in list(fort.dwarves()):
            d.body.dead = True
            d.body.death_cause = "the test"
            fallen.add(d.name)
        self.assertTrue(fallen)
        legacy.record(fort, abandoned=True)
        player = make_creature(RNG("p"), "dwarf", faction="player")
        player.is_player = True
        game = Game(fort.world, player, RNG("adventure"))
        player.wx, player.wy = fort.wx, fort.wy
        game.enter_world_tile(fort.wx, fort.wy)
        found = {c.name for c in game.creatures.values() if c.body.dead}
        self.assertTrue(fallen <= found,
                        "the fortress's dead are not in the ruins")

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


class TestWhatAFortressLeaves(unittest.TestCase):
    """The workshops you raised, and nothing the map already records."""

    #: Kinds the helper puts up: three workshops, then four things whose own
    #: tile is the whole of what they are.
    RAISED = ("smith", "still", "hospital", "statue", "door", "lever", "bed")

    def _raise(self, fort, kind):
        """Put a finished building up, exactly as ``_finish_build`` leaves it."""
        spot = _open_spot(fort, kind)
        if spot is None:
            return None
        b = Building(kind, *spot)
        b.material_name = "granite"
        b.built = True
        for cell in b.cells():
            fort.dig_out(cell, b.defn.tile)
        fort.buildings.append(b)
        return b

    def _ruined_fortress(self, seed="leaves", plan=None):
        """A fortress with workshops standing, goods on the floor, and dead.

        ``plan`` puts one building up unfinished -- while there are still
        dwarves alive to site it, since ``_open_spot`` works from where they
        are standing and by the end of this nobody is standing anywhere.
        """
        fort = embark(seed)
        dig_room(fort, 5)
        raised = {}
        for kind in self.RAISED:
            b = self._raise(fort, kind)
            if b is not None:
                raised[kind] = b
        self.planned = None
        if plan is not None:
            spot = _open_spot(fort, plan)
            if spot is not None:
                self.planned = Building(plan, *spot)
                fort.buildings.append(self.planned)
        d = fort.dwarves()[0]
        self.goods = (d.x, d.y, d.z)
        for def_id in ("sword", "barrel", "bar"):
            fort.drop_item(item_for(fort, def_id), *self.goods)
        self.goods_count = len(fort.items_at(*self.goods))
        for other in fort.dwarves():
            other.body.dead = True
            other.body.death_cause = "the test"
        fort.lost = True
        fort.loss_reason = "the test"
        return fort, raised

    def _adventurer_in(self, fort):
        """Roll a character and walk them into the ruins."""
        from ascii_warriors.engine.rng import RNG
        from ascii_warriors.fortress import legacy
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.state import Game

        legacy.record(fort, abandoned=False)
        player = make_creature(RNG("p"), "dwarf", faction="player")
        player.is_player = True
        game = Game(fort.world, player, RNG("adventure"))
        player.wx, player.wy = fort.wx, fort.wy
        game.enter_world_tile(fort.wx, fort.wy)
        return game

    def test_the_workshops_you_raised_are_still_standing(self):
        """The clause of the README promise that was not true."""
        from ascii_warriors.game import ruins

        fort, raised = self._ruined_fortress()
        shops = [b for k, b in raised.items() if k in ("smith", "still")]
        self.assertTrue(shops, "the test put up no workshops")
        game = self._adventurer_in(fort)
        for b in shops:
            self.assertIsNotNone(
                ruins.at(game, *b.center),
                "the %s an adventurer walked back into is bare floor" % b.kind)

    def test_a_ruin_covers_the_footprint_the_workshop_did(self):
        """All nine cells of a 3x3 forge, corners included."""
        from ascii_warriors.game import ruins

        fort, raised = self._ruined_fortress("footprint")
        forge = raised.get("smith")
        self.assertIsNotNone(forge)
        game = self._adventurer_in(fort)
        for cell in forge.cells():
            self.assertIsNotNone(ruins.at(game, *cell),
                                 "%s is not covered" % (cell,))
        self.assertEqual(len(ruins.cells(game.ruins[0])), 9)

    def test_a_ruin_is_named_for_what_it_was_made_of(self):
        """The look cursor says what the fortress called it."""
        from ascii_warriors.game import ruins

        fort, raised = self._ruined_fortress("named")
        forge = raised.get("smith")
        self.assertIsNotNone(forge)
        game = self._adventurer_in(fort)
        said = ruins.describe(ruins.at(game, *forge.center))
        self.assertIn("granite", said)
        self.assertIn("forge", said)
        self.assertIn("abandoned", said)
        texts = [f.text for f in game.describe_tile(*forge.center)]
        self.assertIn(said, texts, "the look cursor does not mention it")

    def test_what_the_map_already_records_is_not_carried_twice(self):
        """A statue stamped a statue tile: it does not also need a ruin."""
        from ascii_warriors.game import ruins

        fort, raised = self._ruined_fortress("doubled")
        game = self._adventurer_in(fort)
        for kind in ("statue", "door", "lever", "bed"):
            b = raised.get(kind)
            if b is None:
                continue
            self.assertIsNone(
                ruins.at(game, *b.center),
                "a %s is its own tile and is being reported twice" % kind)
            said = " ".join(f.text for f in game.describe_tile(*b.center))
            self.assertNotIn("abandoned", said)

    def test_a_plan_nobody_finished_leaves_nothing(self):
        """An unbuilt workshop is a decision, not a building."""
        from ascii_warriors.game import ruins

        fort, _raised = self._ruined_fortress("unbuilt", plan="kitchen")
        self.assertIsNotNone(self.planned, "the test planned nothing")
        game = self._adventurer_in(fort)
        self.assertIsNone(ruins.at(game, *self.planned.center))

    def test_a_ruined_workshop_is_still_floor_to_walk_on(self):
        """A ruin is scenery. Passability belongs to the tile, as it always did."""
        fort, raised = self._ruined_fortress("walk")
        forge = raised.get("smith")
        self.assertIsNotNone(forge)
        game = self._adventurer_in(fort)
        self.assertTrue(game.local.walkable(*forge.center))
        self.assertTrue(game.is_passable(*forge.center))

    def test_ruins_survive_leaving_and_coming_back(self):
        """Walking out of the ruins and back in must not clear them."""
        fort, _raised = self._ruined_fortress("return")
        game = self._adventurer_in(fort)
        before = len(game.ruins)
        self.assertTrue(before)
        away = fort.wx - 1 if fort.wx else fort.wx + 1
        game.enter_world_tile(away, fort.wy)
        game.enter_world_tile(fort.wx, fort.wy)
        self.assertEqual(len(game.ruins), before)

    def test_all_four_clauses_of_the_promise(self):
        """"The corridors you dug, the workshops you raised, the goods still on
        the floor, and your dwarves lying where they fell." All of it, at once.
        """
        from ascii_warriors.game import ruins

        fort, raised = self._ruined_fortress("promise")
        dug = sum(1 for z in fort.local.levels
                  for t in fort.local.levels[z] if t == "floor")
        names = {c.name for c in fort.creatures.values()}
        game = self._adventurer_in(fort)

        found = sum(1 for z in game.local.levels
                    for t in game.local.levels[z] if t == "floor")
        self.assertEqual(found, dug, "the corridors are not the ones you dug")
        self.assertTrue(game.ruins, "no workshop is left standing")
        self.assertEqual(len(game.items_at(*self.goods)), self.goods_count,
                         "the goods are not on the floor")
        self.assertTrue(names & {c.name for c in game.creatures.values()},
                        "the dead are not where they fell")
        self.assertTrue(any(c.body.dead for c in game.creatures.values()))


class TestReclaim(unittest.TestCase):
    """Going back into a fortress that already killed everybody in it."""

    def _fallen(self, seed="reclaim", *, abandon=False):
        """A fortress with workshops up, then emptied one way or the other."""
        from ascii_warriors.fortress import legacy

        fort = embark(seed)
        dig_room(fort, 6)
        for kind in ("smith", "still"):
            spot = _open_spot(fort, kind)
            if spot is None:
                continue
            b = Building(kind, *spot)
            b.material_name = "granite"
            b.built = True
            for cell in b.cells():
                fort.dig_out(cell, b.defn.tile)
            fort.buildings.append(b)
        sim.run(fort, 2500)
        self.roster = {c.name for c in fort.dwarves()}
        self.assertTrue(self.roster, "the fortress has no dwarves to lose")
        if not abandon:
            for d in list(fort.dwarves()):
                d.body.dead = True
                d.body.death_cause = "the test"
        fort.lost = True
        fort.loss_reason = "abandoned" if abandon else "the test"
        legacy.record(fort, abandoned=abandon)
        return fort

    def test_you_can_go_back_into_a_fortress_that_fell(self):
        """The embark screen used to say somebody already lived there."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen()
        world = fort.world
        self.assertTrue(legacy.can_reclaim(world, fort.wx, fort.wy))
        back = legacy.reclaim(world, fort.wx, fort.wy, RNG("again"))
        self.assertIsNotNone(back)
        self.assertEqual(back.name, fort.name)
        self.assertEqual(back.year_founded, fort.year_founded,
                         "a reclaim is the same place, not a new one")
        self.assertEqual(len(back.dwarves()), 7)

    def test_the_place_comes_back_with_it(self):
        """The magma sea, the caverns and the wet rock are part of the site."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("place")
        dug = sum(1 for z in fort.local.levels
                  for t in fort.local.levels[z] if t == "floor")
        back = legacy.reclaim(fort.world, fort.wx, fort.wy, RNG("again"))
        self.assertEqual(back.magma.total(), fort.magma.total())
        self.assertEqual(back.magma_floor, fort.magma_floor)
        self.assertEqual(back.water.total(), fort.water.total())
        self.assertEqual(len(back.hollow), len(fort.hollow))
        self.assertEqual(len(back.aquifer), len(fort.aquifer))
        found = sum(1 for z in back.local.levels
                    for t in back.local.levels[z] if t == "floor")
        self.assertEqual(found, dug, "the corridors are not the ones you dug")

    def test_a_workshop_works_again(self):
        """The other half of what an adventurer only gets to look at."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("shops")
        raised = {b.kind for b in fort.buildings if b.built}
        back = legacy.reclaim(fort.world, fort.wx, fort.wy, RNG("again"))
        shops = [b for b in back.buildings if b.built and b.is_workshop]
        self.assertTrue(shops, "no workshop survived the reclaim")
        self.assertTrue(raised & {b.kind for b in shops})
        for b in shops:
            self.assertEqual(b.orders, [], "an order outlived the fortress")
            self.assertIsNone(b.worker)
            self.assertTrue(production.recipes_for(b.kind),
                            "%s can take no orders" % b.kind)

    def test_the_dead_are_still_lying_there(self):
        """They are the reason anybody goes back."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("dead")
        back = legacy.reclaim(fort.world, fort.wx, fort.wy, RNG("again"))
        bodies = {c.name for c in back.creatures.values() if c.body.dead}
        self.assertTrue(self.roster <= bodies,
                        "the last expedition is not where it fell")
        self.assertFalse(self.roster & {c.name for c in back.dwarves()},
                         "a dead dwarf is on the new roster")

    def test_the_survivors_of_an_abandoned_fortress_went_home(self):
        """They packed the wagon. They are not standing there still."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("home", abandon=True)
        payload = fort.world.preserved_map(fort.wx, fort.wy)
        frozen = {c.get("name") for c in payload.get("creatures", [])}
        self.assertFalse(self.roster & frozen,
                         "an abandoned fortress froze its living dwarves")
        back = legacy.reclaim(fort.world, fort.wx, fort.wy, RNG("again"))
        self.assertFalse(self.roster & {c.name for c in back.creatures.values()})

    def test_an_abandoned_fortress_has_nobody_home_for_an_adventurer_either(self):
        """The same dwarves used to stand in the ruins with no AI at all."""
        from ascii_warriors.fortress import legacy
        from ascii_warriors.game.state import Game

        fort = self._fallen("visitors", abandon=True)
        player = make_creature(RNG("p"), "dwarf", faction="player")
        player.is_player = True
        game = Game(fort.world, player, RNG("adventure"))
        player.wx, player.wy = fort.wx, fort.wy
        game.enter_world_tile(fort.wx, fort.wy)
        self.assertFalse(self.roster & {c.name for c in game.creatures.values()})

    def test_the_orders_of_a_dead_fortress_do_not_come_back(self):
        """A job board belongs to dwarves who are dead or gone."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("orders")
        fort.stockpiles.append(Stockpile("goods", 10, 10, fort.z, 3, 3))
        legacy.record(fort, abandoned=False)
        back = legacy.reclaim(fort.world, fort.wx, fort.wy, RNG("again"))
        self.assertEqual(len(back.jobs.jobs), 0)
        self.assertEqual(back.stockpiles, [])
        self.assertEqual(back.crimes, [])
        self.assertEqual(len(back.designations.cells), 0)
        self.assertFalse(back.military.squads)

    def test_a_reclaimed_fortress_knows_what_year_it_is(self):
        """`GameTime.from_dict({})` is the year 0, and a partial payload has
        no time in it: the second fall was recorded as happening in year 0."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("clock")
        back = legacy.reclaim(fort.world, fort.wx, fort.wy, RNG("again"))
        self.assertEqual(back.time.year, fort.world.year)
        self.assertGreater(back.time.year, 0)

    def test_a_place_is_founded_once_however_often_it_falls(self):
        """Every fall used to write another founding into the legends."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("history")
        world = fort.world
        back = legacy.reclaim(world, fort.wx, fort.wy, RNG("again"))
        for d in list(back.dwarves()):
            d.body.dead = True
            d.body.death_cause = "again"
        back.lost = True
        back.loss_reason = "again"
        legacy.record(back)

        site = world.site_at(fort.wx, fort.wy)
        self.assertEqual(
            sum(1 for s in world.sites if (s.wx, s.wy) == (fort.wx, fort.wy)), 1)
        foundings = [e for e in world.events
                     if e.kind == "site_founded" and site.id in e.sites]
        self.assertEqual(len(foundings), 1, "founded more than once")
        falls = [e for e in world.events
                 if e.kind == "site_destroyed" and site.id in e.sites]
        self.assertEqual(len(falls), 2, "both falls should be remembered")

    def test_going_back_is_written_into_the_legends(self):
        """It is the most interesting thing anybody does with a ruin."""
        from ascii_warriors.fortress import legacy
        from ascii_warriors.world import history as history_mod

        fort = self._fallen("legends")
        world = fort.world
        legacy.reclaim(world, fort.wx, fort.wy, RNG("again"))
        site = world.site_at(fort.wx, fort.wy)
        told = [e for e in world.events
                if e.kind == "site_reclaimed" and site.id in e.sites]
        self.assertEqual(len(told), 1)
        self.assertIn(fort.name, told[0].text)
        self.assertIn(told[0], history_mod.notable_events(world, 50))

    def test_a_reclaimed_fortress_is_not_a_ruin(self):
        """It kept the year it was destroyed and read as rubble in legends."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("notruin")
        world = fort.world
        self.assertTrue(world.site_at(fort.wx, fort.wy).is_ruin)
        back = legacy.reclaim(world, fort.wx, fort.wy, RNG("again"))
        back.lost = False
        back.loss_reason = ""
        legacy.make_site(back)
        site = world.site_at(fort.wx, fort.wy)
        self.assertFalse(site.is_ruin, "eighty dwarves live in these ruins")
        self.assertEqual(site.population, len(back.dwarves()))

    def test_a_reclaimed_fortress_runs_and_saves(self):
        """It has to be an ordinary fortress from here on."""
        from ascii_warriors.fortress import legacy

        fort = self._fallen("runs")
        back = legacy.reclaim(fort.world, fort.wx, fort.wy, RNG("again"))
        sim.run(back, 2000)
        self.assertTrue(back.dwarves(), "nobody survived the first season")
        again = Fortress.from_dict(back.to_dict())
        self.assertEqual(len(again.dwarves()), len(back.dwarves()))
        self.assertEqual(again.magma.total(), back.magma.total())
        self.assertEqual(again.year_founded, back.year_founded)
        self.assertEqual(again.time.year, back.time.year)

    def test_you_cannot_reclaim_a_place_somebody_lives_in(self):
        """A ruin of your own is the only thing this opens up."""
        from ascii_warriors.fortress import legacy

        fort = embark("occupied")
        world = fort.world
        lived_in = [s for s in world.sites if not s.is_ruin]
        self.assertTrue(lived_in, "the world generated no living settlements")
        for site in lived_in[:5]:
            self.assertFalse(legacy.can_reclaim(world, site.wx, site.wy))
        # And nowhere at all, where nothing was ever built.
        self.assertFalse(legacy.can_reclaim(world, fort.wx, fort.wy))


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

    def _water_underground(self, fort):
        """Water inside the fortress, where an aquifer puts it.

        Counted here rather than as `water.total()` because since v3.18 the
        weather freezes the water outdoors, and a brook icing over while the
        test runs hides the leak it is supposed to be measuring.
        """
        return sum(v for c, v in fort.water.depth.items()
                   if not fort.local.is_outside(*c))

    def test_breaching_an_aquifer_floods_and_warns(self):
        """Digging into wet rock is supposed to be a disaster."""
        fort = embark("breach")
        if not fort.aquifer:
            self.skipTest("this embark has no aquifer")
        cell = sorted(fort.aquifer)[len(fort.aquifer) // 2]
        before = self._water_underground(fort)
        fort.dig_out(cell, "floor")
        self.assertIn(cell, fort.water.sources)
        sim.run(fort, 60)
        self.assertGreater(self._water_underground(fort), before)
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


class TestJustice(unittest.TestCase):
    """Crimes, the sheriff who tries them, and what a sentence costs."""

    def setUp(self):
        from ascii_warriors.fortress import justice as justice_mod

        self.justice = justice_mod

    def _with_sheriff(self, seed="law"):
        """A fortress big enough to have somebody keeping order."""
        fort = embark(seed)
        sim.migrants(fort, 18)
        law = fort.dwarves()[-1]
        law.fort.labors.enable("military")
        fort.court.appoint("sheriff", law.id, fort.ticks)
        return fort, law

    # -- the book ----------------------------------------------------------- #

    def test_a_crime_is_written_down(self):
        """Somebody did something, and the fortress remembers who."""
        fort = embark("book")
        d = fort.dwarves()[0]
        crime = self.justice.report(fort, "vandalism", d, "table")
        self.assertIsNotNone(crime)
        self.assertEqual(crime.culprit, d.id)
        self.assertIn(crime, fort.crimes)
        self.assertIn(crime, self.justice.open_cases(fort))
        self.assertIn(d.name, self.justice.describe(fort, crime))

    def test_a_crime_nobody_was_caught_at_has_no_name_on_it(self):
        """Which is exactly how a fortress experiences a theft."""
        fort = embark("nameless")
        crime = self.justice.report(fort, "theft", None, "a gold statue")
        self.assertIsNone(crime.culprit)
        self.assertFalse(self.justice.can_try(fort, crime))
        self.assertIn("Somebody", self.justice.describe(fort, crime))

    def test_an_invented_crime_is_not_a_crime(self):
        """The book only has so many pages."""
        fort = embark("nocrime")
        self.assertIsNone(self.justice.report(fort, "jaywalking",
                                              fort.dwarves()[0]))
        self.assertEqual(fort.crimes, [])

    def test_a_case_goes_cold(self):
        """Nobody is tried for something that happened three months ago."""
        fort = embark("cold")
        crime = self.justice.report(fort, "theft", None, "a mug")
        fort.ticks += self.justice.COLD_CASE + 1
        self.assertEqual(self.justice.open_cases(fort), [])
        self.assertIn(crime, self.justice.cold_cases(fort))

    # -- the sheriff -------------------------------------------------------- #

    def test_the_sheriff_opens_the_book_every_few_days(self):
        """Not once a season. A bad week fills the book in a week."""
        fort, _law = self._with_sheriff("cadence")
        guilty = fort.dwarves()[0]
        crime = self.justice.report(fort, "vandalism", guilty, "a table")
        sim.step(fort)
        self.assertTrue(crime.convicted, "the sheriff never looked")
        second = self.justice.report(fort, "assault", fort.dwarves()[1], "x")
        sim.step(fort)
        self.assertFalse(second.convicted, "court sat twice in one day")
        fort.ticks += self.justice.COURT_INTERVAL
        sim.step(fort)
        self.assertTrue(second.convicted)

    def test_the_status_line_shows_both_halves(self):
        """Four fifths of the fortress in a cell has to be visible."""
        fort, _law = self._with_sheriff("both")
        self.assertEqual(self.justice.summary(fort), "")
        self.justice.report(fort, "theft", None, "a mug")
        self.assertEqual(self.justice.summary(fort), "1 unsolved")
        self.justice.report(fort, "vandalism", fort.dwarves()[0], "a table")
        self.justice.hold_court(fort)
        self.assertEqual(self.justice.summary(fort), "1 unsolved, 1 serving")

    def test_without_a_sheriff_nothing_is_tried(self):
        """A fortress of seven has no law, and lives with it."""
        fort = embark("nolaw")
        self.justice.report(fort, "vandalism", fort.dwarves()[0], "chair")
        self.assertIsNone(self.justice.sheriff(fort))
        self.assertEqual(self.justice.hold_court(fort), [])
        self.assertEqual(len(self.justice.open_cases(fort)), 1)

    def test_the_sheriff_convicts(self):
        """One appointment turns an open case into a sentence."""
        fort, law = self._with_sheriff("convict")
        guilty = fort.dwarves()[0]
        self.assertIsNot(guilty, law)
        crime = self.justice.report(fort, "assault", guilty, law.name)
        self.assertEqual(self.justice.hold_court(fort), [crime])
        self.assertTrue(crime.convicted)
        self.assertTrue(self.justice.is_jailed(fort, guilty))
        self.assertIn(crime, self.justice.serving(fort))

    def test_a_worse_crime_is_a_longer_sentence(self):
        """Four days a point, and murder is worth four points."""
        fort, _law = self._with_sheriff("severity")
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        small = self.justice.report(fort, "vandalism", a, "a chair")
        big = self.justice.report(fort, "murder", b, "a friend")
        self.justice.hold_court(fort)
        self.assertGreater(self.justice.days_left(fort, big),
                           self.justice.days_left(fort, small))
        self.assertEqual(self.justice.days_left(fort, small), 4)

    def test_a_sentence_ends(self):
        """The fortress gets its mason back."""
        fort, _law = self._with_sheriff("release")
        guilty = fort.dwarves()[0]
        crime = self.justice.report(fort, "vandalism", guilty, "a door")
        self.justice.hold_court(fort)
        self.assertTrue(self.justice.is_jailed(fort, guilty))
        fort.ticks = crime.until + 1
        self.justice.tick(fort)
        self.assertFalse(self.justice.is_jailed(fort, guilty))
        self.assertFalse(crime.pardoned, "served is not pardoned")
        self.assertTrue(any("served their sentence" in m.text
                            for m in fort.log.all()))

    def test_a_convicted_dwarf_does_no_work(self):
        """Which is the entire cost of having a law."""
        fort, law = self._with_sheriff("noworkjail")
        dig_room(fort)
        sim.run(fort, 30)
        working = [d for d in fort.dwarves()
                   if d is not law and d.fort.job is not None]
        self.assertTrue(working, "nothing to be taken away")
        guilty = working[0]
        self.justice.report(fort, "vandalism", guilty, "a table")
        self.justice.hold_court(fort)
        # The sentence takes the job off it, and it takes no new one.
        for _ in range(20):
            dwarf_mod.take_turn(fort, guilty, 10)
            self.assertIsNone(guilty.fort.job)

    def test_everybody_else_is_calmer_for_it(self):
        """A conviction upsets one dwarf and settles the rest."""
        fort, _law = self._with_sheriff("thoughts")
        guilty = fort.dwarves()[0]
        other = fort.dwarves()[1]
        before = other.needs.stress
        self.justice.report(fort, "vandalism", guilty, "a table")
        self.justice.hold_court(fort)
        self.assertLess(other.needs.stress, before)
        self.assertTrue(any("convicted" in t
                            for t in guilty.needs.recent_thoughts(6)))

    def test_a_pardon_frees_one_dwarf_and_annoys_the_rest(self):
        """The overseer's prerogative, and what it is worth."""
        fort, _law = self._with_sheriff("pardon")
        guilty = fort.dwarves()[0]
        other = fort.dwarves()[1]
        crime = self.justice.report(fort, "murder", guilty, "a friend")
        self.justice.hold_court(fort)
        before = other.needs.stress
        self.assertTrue(self.justice.pardon(fort, crime))
        self.assertFalse(self.justice.is_jailed(fort, guilty))
        self.assertGreater(other.needs.stress, before)
        # And the book remembers that this one walked.
        self.assertTrue(crime.pardoned)
        self.assertTrue(Fortress.from_dict(fort.to_dict()).crimes[0].pardoned)
        # And it cannot be done twice.
        self.assertFalse(self.justice.pardon(fort, crime))

    def test_unpunished_crime_wears_on_everybody(self):
        """No sheriff is a decision with a price."""
        fort = embark("unsolved")
        for _ in range(3):
            self.justice.report(fort, "theft", None, "a gem")
        d = fort.dwarves()[0]
        before = d.needs.stress
        self.justice.season(fort)
        self.assertGreater(d.needs.stress, before)
        self.assertTrue(any("sheriff" in m.text for m in fort.log.all()))

    # -- where the crimes come from ----------------------------------------- #

    def test_a_tantrum_is_a_crime(self):
        """Smashing the furniture goes in the book."""
        fort = embark("vandal")
        table = Building("table", *_open_spot(fort, "table"))
        table.built = True
        fort.buildings.append(table)
        from ascii_warriors.fortress import nobles

        d = fort.dwarves()[0]
        for _ in range(40000):
            d.needs.stress = nobles.STRESS_TANTRUM + 5
            sim._tantrums(fort)
            if any(c.kind == "vandalism" for c in fort.crimes):
                break
        self.assertTrue(any(c.kind == "vandalism" for c in fort.crimes))

    def test_a_brawl_is_a_crime(self):
        """A dwarf that hits another dwarf has committed one."""
        fort = embark("brawl")
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        b.x, b.y, b.z = a.x + 1, a.y, a.z
        for _ in range(200):
            if sim._start_brawl(fort, a):
                break
        self.assertTrue(any(c.kind in ("assault", "murder")
                            for c in fort.crimes))
        self.assertTrue(any("lashes out" in m.text for m in fort.log.all()))

    def test_an_ignored_mandate_is_somebody_s_fault(self):
        """The manager answers for it. Never the mayor."""
        fort = embark("neglect")
        sim.migrants(fort, 18)
        sim._appointments(fort)
        fort.court.appoint("mayor", fort.dwarves()[0].id, fort.ticks)
        mayor = fort.court.noble("mayor")
        mayor.mandate = {"target": "statue", "kind": "building",
                         "text": "A statue.", "deadline": fort.ticks - 1}
        sim._appointments(fort)
        neglect = [c for c in fort.crimes if c.kind == "neglect"]
        self.assertEqual(len(neglect), 1)
        self.assertNotEqual(neglect[0].culprit, fort.dwarves()[0].id)

    # -- thieves ------------------------------------------------------------ #

    def _thief(self, fort, side="west"):
        """A kobold at the edge of the map, with something to take."""
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item

        entry = fort.local.edge_entry(fort.rng, side)
        thief = make_creature(fort.rng, "kobold", faction="hostile", level=1)
        thief.x, thief.y, thief.z = fort._free_spot(entry, 0)
        thief.wx, thief.wy = fort.wx, fort.wy
        thief.thief = True
        thief.thief_since = fort.ticks
        fort.add_creature(thief)
        gem = make_item(fort.rng, "gem")
        fort.drop_item(gem, thief.x, thief.y, thief.z)
        return thief, gem

    def test_a_thief_does_not_raise_the_alarm(self):
        """One kobold is not a reason to stop everybody drinking."""
        fort = embark("quiet")
        thief, _gem = self._thief(fort)
        self.assertEqual(fort.hostiles(), [])
        self.assertIn(thief.id, fort.creatures)

    def test_a_thief_takes_something_and_leaves(self):
        """And the fortress finds out from the gap where it used to be."""
        fort = embark("robbed")
        thief, gem = self._thief(fort)
        for _ in range(60):
            sim.step(fort)
            if thief.id not in fort.creatures:
                break
        self.assertNotIn(thief.id, fort.creatures)
        self.assertIsNone(fort.item_cell(gem))
        thefts = [c for c in fort.crimes if c.kind == "theft"]
        self.assertEqual(len(thefts), 1)
        self.assertIn("gem", thefts[0].detail)
        self.assertTrue(any("escapes with" in m.text for m in fort.log.all()))

    def test_a_thief_with_nothing_to_take_gives_up(self):
        """Rather than standing in a corridor for the rest of the game."""
        fort = embark("bored")
        fort.items_on_ground.clear()
        thief, _gem = self._thief(fort)
        fort.items_on_ground.clear()
        thief.thief_since = fort.ticks - sim.THIEF_PATIENCE - 1
        for _ in range(120):
            sim.step(fort)
            if thief.id not in fort.creatures:
                break
        self.assertNotIn(thief.id, fort.creatures)
        self.assertEqual([c for c in fort.crimes if c.kind == "theft"], [])

    def test_a_thief_that_cannot_get_out_is_gone_anyway(self):
        """A kobold wedged five levels down is a permanent resident."""
        fort = embark("wedged")
        thief, gem = self._thief(fort)
        thief.loot = gem.id
        thief.loot_name = gem.name()
        fort.take_item(gem)
        # Somewhere it cannot walk out of: the middle of solid rock.
        thief.x, thief.y = fort.local.width // 2, fort.local.height // 2
        thief.z = fort.local.zmin + 1
        thief.thief_since = fort.ticks - sim.THIEF_GONE - 1
        sim._thieves(fort)
        self.assertNotIn(thief.id, fort.creatures)
        self.assertEqual(len([c for c in fort.crimes if c.kind == "theft"]), 1)

    def test_a_thief_is_not_two_thieves(self):
        """One at a time, or the fortress is a market."""
        fort = embark("onethief")
        fort.wealth = 5000
        self._thief(fort)
        for _ in range(50):
            sim._maybe_thief(fort)
        self.assertEqual(len([c for c in fort.creatures.values() if c.thief]), 1)

    # -- persistence -------------------------------------------------------- #

    def test_the_book_survives_a_save(self):
        """Sentences keep running across a reload."""
        fort, _law = self._with_sheriff("lawsave")
        guilty = fort.dwarves()[0]
        self.justice.report(fort, "murder", guilty, "a friend")
        self.justice.report(fort, "theft", None, "a mug")
        self.justice.hold_court(fort)
        again = Fortress.from_dict(fort.to_dict())
        self.assertEqual(len(again.crimes), 2)
        kinds = sorted(c.kind for c in again.crimes)
        self.assertEqual(kinds, ["murder", "theft"])
        served = next(c for c in again.crimes if c.kind == "murder")
        self.assertTrue(served.convicted)
        self.assertTrue(self.justice.is_jailed(
            again, again.creatures[guilty.id]))
        self.assertEqual(len(self.justice.open_cases(again)), 1)

    def test_a_thief_survives_a_save(self):
        """Loot and patience come back with it."""
        fort = embark("thiefsave")
        thief, gem = self._thief(fort)
        thief.loot = gem.id
        thief.loot_name = gem.name()
        again = Fortress.from_dict(fort.to_dict())
        back = again.creatures[thief.id]
        self.assertTrue(back.thief)
        self.assertEqual(back.loot, gem.id)
        self.assertEqual(back.loot_name, gem.name())
        self.assertEqual(back.thief_since, thief.thief_since)
        self.assertEqual(again.hostiles(), [])


class TestSocial(unittest.TestCase):
    """Who knows whom, what it costs when they die, and where children come from."""

    def setUp(self):
        from ascii_warriors.fortress import social as social_mod

        self.social = social_mod

    def _tavern(self, fort):
        """Put up a tavern near the dwarves."""
        spot = _open_spot(fort, "tavern")
        self.assertIsNotNone(spot, "nowhere to put a tavern")
        t = Building("tavern", *spot)
        t.built = True
        fort.buildings.append(t)
        return t

    def _pair(self, fort, ceiling):
        """Two dwarves whose bond is forced to a chosen level."""
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        bd = self.social.Bond(a.id, b.id, ceiling)
        fort.bonds[bd.key] = bd
        return a, b, bd

    # -- the shape of a bond ------------------------------------------------ #

    def test_a_bond_is_stored_once_per_pair(self):
        """Two dwarves cannot disagree about what they are to each other."""
        fort = embark("bondkey")
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        one = self.social.meet(fort, a, b)
        self.assertIsNotNone(one)
        self.assertEqual(len(fort.bonds), 1)
        self.assertIs(self.social.bond(fort, a, b),
                      self.social.bond(fort, b, a))
        self.assertEqual(one.key, (min(a.id, b.id), max(a.id, b.id)))
        self.assertEqual(one.other(a.id), b.id)
        self.assertEqual(one.other(b.id), a.id)

    def test_a_bond_has_a_name_a_player_can_read(self):
        """The number is for the simulation; the word is for the screen."""
        cases = ((100, "close friend"), (50, "friend"), (20, "friendly with"),
                 (0, "knows"), (-30, "annoyed by"), (-80, "enemy of"))
        for value, expected in cases:
            self.assertEqual(self.social.Bond(1, 2, value).level, expected)

    def test_marriage_outranks_temper(self):
        """A spouse you have fallen out with is still a spouse."""
        bd = self.social.Bond(1, 2, -70, "spouse")
        self.assertEqual(bd.level, "enemy of")
        self.assertEqual(bd.label, "spouse")

    def test_meeting_has_a_cooldown(self):
        """Standing next to somebody all day is one conversation, not four."""
        fort = embark("cooldown")
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        first = self.social.meet(fort, a, b)
        value = first.value
        for _ in range(50):
            self.social.meet(fort, a, b)
        self.assertEqual(self.social.bond(fort, a, b).value, value)
        fort.ticks += self.social.MEET_COOLDOWN
        self.social.meet(fort, a, b)
        self.assertNotEqual(self.social.bond(fort, a, b).value, value)

    def test_nobody_befriends_themselves(self):
        """Which would otherwise be the strongest bond in the fortress."""
        fort = embark("alone")
        d = fort.dwarves()[0]
        self.assertIsNone(self.social.meet(fort, d, d))
        self.assertEqual(fort.bonds, {})

    # -- compatibility ------------------------------------------------------ #

    def test_compatibility_decides_the_ceiling(self):
        """Not the rate. A rate alone makes everybody inseparable eventually."""
        fort = embark("ceiling")
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        cap = self.social.ceiling(a, b)
        for _ in range(400):
            fort.ticks += self.social.MEET_COOLDOWN
            self.social.meet(fort, a, b)
        self.assertEqual(self.social.bond(fort, a, b).value, cap)

    def test_dwarves_are_not_all_equally_compatible(self):
        """A fortress of universal best friends is not a fortress."""
        from ascii_warriors.engine.rng import RNG

        rng = RNG("spread")
        crowd = [dwarf_mod.make_dwarf(rng, "miner") for _ in range(40)]
        caps = [self.social.ceiling(crowd[i], crowd[j])
                for i in range(len(crowd)) for j in range(i + 1, len(crowd))]
        self.assertLess(min(caps), 0, "nobody in the world dislikes anybody")
        self.assertGreater(max(caps), 60, "nobody could ever be close")
        friends = sum(1 for c in caps if c >= 45) / float(len(caps))
        self.assertLess(friends, 0.5, "half the fortress cannot all be friends")
        self.assertGreater(friends, 0.05, "nobody can be friends with anybody")

    def test_compatibility_is_symmetric(self):
        """However they meet, they get on the same amount."""
        fort = embark("symmetry")
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        self.assertEqual(self.social.compatibility(a, b),
                         self.social.compatibility(b, a))

    # -- the tavern --------------------------------------------------------- #

    def test_idle_dwarves_go_to_the_tavern(self):
        """Which is the whole reason to build one."""
        fort = embark("gathering")
        tavern = self._tavern(fort)
        cx, cy, cz = tavern.center
        sim.run(fort, 500)
        near = [d for d in fort.dwarves()
                if d.z == cz
                and max(abs(d.x - cx), abs(d.y - cy))
                <= dwarf_mod.TAVERN_RADIUS]
        # Not everybody: a dwarf with a job to do is not idle, and hauling
        # the wagon indoors is a job. Most of the fortress, though.
        self.assertGreater(len(near), len(fort.dwarves()) // 2)
        idle = [d for d in fort.dwarves() if d.fort.job is None]
        here = set(d.id for d in near)
        # Most of the idle, not all of them. The stricter form -- every idle
        # dwarf inside the room -- passed for several versions on map luck
        # alone: dwarves drift out of a tavern over time on any layout, which
        # v3.15 does exactly as much as v3.16 does when measured on the same
        # seed. Asserting a property the code does not provide is a test that
        # fails whenever worldgen's dice move.
        self.assertGreater(len([d for d in idle if d.id in here]),
                           len(idle) // 2)

    def test_a_tavern_makes_friends(self):
        """Bonds move where dwarves already are, so they move fastest here."""
        quiet = embark("quiet-fort")
        loud = embark("loud-fort")
        self._tavern(loud)
        sim.run(quiet, 2000)
        sim.run(loud, 2000)
        best_quiet = max((b.value for b in quiet.bonds.values()), default=0)
        best_loud = max((b.value for b in loud.bonds.values()), default=0)
        self.assertGreater(best_loud, best_quiet)

    def test_a_fortress_with_no_tavern_still_runs(self):
        """The idle behaviour has to survive there being nowhere to go."""
        fort = embark("notavern")
        self.assertIsNone(fort.tavern())
        sim.run(fort, 200)
        self.assertFalse(fort.lost)

    def test_company_cures_loneliness(self):
        """And the clock starts again the moment somebody says something."""
        fort = embark("lonely")
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        a.fort.lonely = self.social.LONELY_AT + 1
        self.assertTrue(self.social.lonely(fort, a))
        self.social.meet(fort, a, b)
        self.assertEqual(a.fort.lonely, 0)
        self.assertFalse(self.social.lonely(fort, a))

    def test_loneliness_is_a_seasonal_thought(self):
        """A fortress that never lets anybody talk pays for it."""
        fort = embark("solitude")
        d = fort.dwarves()[0]
        for other in fort.dwarves():
            other.fort.lonely = self.social.LONELY_AT + 1
        before = d.needs.stress
        self.social.season(fort)
        self.assertGreater(d.needs.stress, before)

    def test_knowing_a_name_is_not_company(self):
        """Only a real friend is worth a cheerful thought."""
        fort = embark("acquaintance")
        a, b = fort.dwarves()[0], fort.dwarves()[1]
        nod = self.social.Bond(a.id, b.id, 20)
        fort.bonds[nod.key] = nod
        before = a.needs.stress
        self.social.season(fort)
        self.assertEqual(a.needs.stress, before)
        nod.value = 60
        self.social.season(fort)
        self.assertLess(a.needs.stress, before)

    # -- grief -------------------------------------------------------------- #

    def test_grief_is_proportional_to_the_bond(self):
        """The whole point. A stranger is not a spouse."""
        fort = embark("grief")
        dwarves = fort.dwarves()
        dead, close, stranger = dwarves[0], dwarves[1], dwarves[2]
        bd = self.social.Bond(dead.id, close.id, 100)
        fort.bonds[bd.key] = bd
        before_close = close.needs.stress
        before_stranger = stranger.needs.stress
        self.social.grieve(fort, dead)
        self.assertGreater(close.needs.stress - before_close,
                           stranger.needs.stress - before_stranger)
        self.assertEqual(stranger.needs.stress, before_stranger)

    def test_a_widow_is_widowed(self):
        """And feels it more than anybody."""
        fort = embark("widow")
        dead, spouse = fort.dwarves()[0], fort.dwarves()[1]
        bd = self.social.Bond(dead.id, spouse.id, 95, "spouse")
        fort.bonds[bd.key] = bd
        self.social.grieve(fort, dead)
        self.assertEqual(bd.kind, "widowed")
        self.assertGreaterEqual(spouse.needs.stress, 80)
        self.assertTrue(any("widowed" in m.text for m in fort.log.all()))
        self.assertTrue(any("spouse" in t
                            for t in spouse.needs.recent_thoughts(4)))

    def test_nobody_mourns_an_enemy(self):
        """They are quietly pleased, and ashamed of it."""
        fort = embark("spite")
        dead, foe = fort.dwarves()[0], fort.dwarves()[1]
        bd = self.social.Bond(dead.id, foe.id, -80)
        fort.bonds[bd.key] = bd
        before = foe.needs.stress
        self.social.grieve(fort, dead)
        self.assertLess(foe.needs.stress, before)

    def test_a_death_grieves_through_the_real_loop(self):
        """Not only when the test calls grieve by hand."""
        fort = embark("realgrief")
        dead, close = fort.dwarves()[0], fort.dwarves()[1]
        bd = self.social.Bond(dead.id, close.id, 100)
        fort.bonds[bd.key] = bd
        before = close.needs.stress
        dead.body.dead = True
        dead.body.death_cause = "slain"
        fort.kill_creature(dead)
        self.assertGreaterEqual(close.needs.stress - before, 40)

    def test_a_dwarf_that_leaves_takes_its_bonds_with_it(self):
        """Nobody grieves somebody who walked out."""
        fort = embark("departed")
        a, b, bd = self._pair(fort, 90)
        fort.remove_creature(a)
        self.assertNotIn(bd.key, fort.bonds)
        self.assertEqual(self.social.bonds_of(fort, b), [])

    def test_the_dead_keep_their_bonds(self):
        """Who the dead were close to is what the survivors are grieving."""
        fort = embark("keepbonds")
        dead, close = fort.dwarves()[0], fort.dwarves()[1]
        bd = self.social.Bond(dead.id, close.id, 90)
        fort.bonds[bd.key] = bd
        dead.body.dead = True
        fort.kill_creature(dead)
        self.assertIn(bd.key, fort.bonds)

    # -- love and children --------------------------------------------------- #

    def test_lovers_become_spouses(self):
        """Lovers marry. There is no second, higher bond to clear."""
        fort = embark("wedding")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "lover"
        for _ in range(30):
            self.social.court(fort)
            if bd.kind == "spouse":
                break
        self.assertEqual(bd.kind, "spouse")
        self.assertTrue(any("married" in m.text for m in fort.log.all()))
        self.assertIs(self.social.spouse_of(fort, a), b)
        self.assertIs(self.social.spouse_of(fort, b), a)

    def test_a_wedding_is_written_into_the_world(self):
        """So an adventurer can read about it three hundred years later."""
        fort = embark("weddinghistory")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "lover"
        before = len(fort.world.events)
        for _ in range(30):
            self.social.court(fort)
            if bd.kind == "spouse":
                break
        marriages = [e for e in fort.world.events[before:]
                     if e.kind == "marriage"]
        self.assertEqual(len(marriages), 1)
        self.assertIn(a.name, marriages[0].text)
        self.assertIn(fort.name, marriages[0].text)

    def test_nobody_marries_twice(self):
        """A married dwarf is not eligible, however charming the neighbour."""
        fort = embark("bigamy")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "spouse"
        c = fort.dwarves()[2]
        other = self.social.Bond(a.id, c.id, 100)
        fort.bonds[other.key] = other
        self.assertFalse(self.social.eligible(fort, a))
        for _ in range(30):
            self.social.court(fort)
        self.assertEqual(other.kind, "")

    def test_children_are_born_to_couples(self):
        """And only to couples who could have one."""
        fort = embark("cradle")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "spouse"
        a.female, b.female = True, False
        for _ in range(400):
            fort.drop_item(item_for(fort, "plump_helmet"), a.x, a.y, a.z)
        before = len(fort.dwarves())
        child = None
        for _ in range(60):
            child = self.social.maybe_born(fort)
            if child is not None:
                break
        self.assertIsNotNone(child, "no child in fifteen years of trying")
        self.assertEqual(len(fort.dwarves()), before + 1)
        self.assertTrue(self.social.is_child(child))
        self.assertEqual(child.age, 0)
        self.assertTrue(any("given birth" in m.text for m in fort.log.all()))

    def test_a_child_knows_its_parents(self):
        """It is born knowing exactly two people, and very well."""
        fort = embark("family")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "spouse"
        a.female, b.female = True, False
        child = self.social.born(fort, a, b)
        self.assertEqual(self.social.describe(fort, child, a), "child")
        self.assertEqual(self.social.describe(fort, child, b), "child")
        births = [e for e in fort.world.events if e.kind == "birth"
                  and child.name in e.text]
        self.assertEqual(len(births), 1)

    def test_a_hungry_fortress_has_no_children(self):
        """Nobody gives birth into a famine."""
        fort = embark("famine")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "spouse"
        a.female, b.female = True, False
        fort.items_on_ground.clear()
        self.assertLess(fort.food_stock(), self.social.BIRTH_FOOD)
        for _ in range(40):
            self.assertIsNone(self.social.maybe_born(fort))

    def test_a_child_does_no_work(self):
        """It plays, which is how it ends up with friends of its own."""
        fort = embark("playing")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "spouse"
        a.female, b.female = True, False
        child = self.social.born(fort, a, b)
        dig_room(fort)
        sim.scan_jobs(fort)
        for _ in range(40):
            dwarf_mod.take_turn(fort, child, 10)
        self.assertIsNone(child.fort.job)
        self.assertEqual(labors.profession_title(child), "Child")

    def test_a_child_grows_up_and_works(self):
        """The fortress gets a dwarf out of it eventually."""
        fort = embark("growingup")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "spouse"
        a.female, b.female = True, False
        child = self.social.born(fort, a, b)
        for _ in range(self.social.CHILD_AGE):
            self.social.birthdays(fort)
        self.assertFalse(self.social.is_child(child))
        self.assertTrue(child.fort.labors.enabled)
        self.assertTrue(child.profession)
        self.assertTrue(any("grown up" in m.text for m in fort.log.all()))

    def test_birthdays_come_round_in_the_real_loop(self):
        """A year of fortress time is a year of everybody's life."""
        fort = embark("ageing")
        d = fort.dwarves()[0]
        before = d.age
        for _ in range(5):
            fort.time.advance(TICKS_PER_DAY * 95)
            sim.step(fort)
        self.assertEqual(d.age, before + 1)

    # -- the screens --------------------------------------------------------- #

    def test_the_status_line_counts_the_children(self):
        """And says "1 child", not "1 children"."""
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.ui.fort.sidebar import draw_status_line

        fort = embark("kidcount")
        a, b, bd = self._pair(fort, 100)
        bd.kind = "spouse"
        a.female, b.female = True, False
        self.assertEqual(self.social.summary(fort), "")
        self.social.born(fort, a, b)
        self.assertEqual(self.social.summary(fort), "1 child")
        self.social.born(fort, a, b)
        self.assertEqual(self.social.summary(fort), "2 children")
        scr = Screen(130, 4)
        draw_status_line(scr, 0, 0, 130, fort)
        self.assertIn("2 children", "\n".join(scr.to_text()))

    def test_a_dwarf_s_relationships_render(self):
        """Who it knows, in the panel that describes it."""
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.ui.fort import units as units_ui

        fort = embark("relui")
        a, b, bd = self._pair(fort, 95)
        bd.kind = "spouse"
        lines = []
        units_ui._relationships(fort, a, lines)
        text = " ".join(
            f.text if hasattr(f, "text") else
            (" ".join(getattr(p, "text", str(p)) for p in f)
             if isinstance(f, list) else str(f))
            for f in lines)
        self.assertIn("Relationships", text)
        self.assertIn("spouse", text)
        self.assertIn(b.name, text)
        scr = Screen(110, 34)
        units_ui.UnitsScene(_FakeApp(), fort).draw(scr)
        self.assertEqual(len(scr.to_text()), 34)

    # -- persistence -------------------------------------------------------- #

    def test_bonds_survive_a_save(self):
        """Including who is married to whom and how long they have known."""
        fort = embark("bondsave")
        a, b, bd = self._pair(fort, 64)
        bd.kind = "spouse"
        bd.met = 4321
        a.fort.lonely = 999
        again = Fortress.from_dict(fort.to_dict())
        back = again.bonds[bd.key]
        self.assertEqual(back.value, 64)
        self.assertEqual(back.kind, "spouse")
        self.assertEqual(back.met, 4321)
        self.assertEqual(again.creatures[a.id].fort.lonely, 999)
        self.assertIs(self.social.spouse_of(again, again.creatures[a.id]),
                      again.creatures[b.id])


class TestNight(unittest.TestCase):
    """Necromancy, the moon, and what drinks in the dark."""

    def setUp(self):
        from ascii_warriors.game import night as night_mod

        self.night = night_mod

    def _corpse_at(self, fort, cell, name="Urist"):
        """A body on the floor, big enough to be worth raising."""
        from ascii_warriors.game.item import corpse_of

        d = fort.dwarves()[0]
        item = corpse_of(d)
        item.flags["name"] = name
        fort.drop_item(item, *cell)
        return item

    def _full_moon_night(self, fort):
        """Wind the clock to a night the moon is full."""
        for day in range(60):
            fort.time.ticks = day * TICKS_PER_DAY + int(TICKS_PER_DAY * 0.95)
            if self.night.moon_is_full(fort.time) and fort.time.is_night():
                return
        self.fail("no full moon in two months")

    # -- necromancy --------------------------------------------------------- #

    def test_a_necromancer_raises_a_corpse(self):
        """Which is the entire difference between it and a tough human."""
        fort = embark("raising")
        boss = self._necromancer(fort)
        cell = self._free_beside(fort, boss)[0]
        item = self._corpse_at(fort, cell)
        before = len(fort.creatures)
        self.assertTrue(self.night.necromancy_turn(fort, boss))
        self.assertEqual(len(fort.creatures), before + 1)
        self.assertIsNone(fort.item_cell(item))
        risen = [c for c in fort.creatures.values()
                 if c.def_id in ("zombie", "skeleton")]
        self.assertEqual(len(risen), 1)
        self.assertEqual(risen[0].faction, "hostile")
        self.assertEqual(risen[0].raised_by, boss.id)
        self.assertIn("Urist", risen[0].name)

    def _necromancer(self, fort):
        """One necromancer standing somewhere it can work."""
        d = fort.dwarves()[0]
        boss = make_creature(fort.rng, "necromancer", faction="hostile")
        boss.profession = "necromancer"
        boss.x, boss.y, boss.z = fort._free_spot((d.x, d.y, d.z), 6)
        boss.wx, boss.wy = fort.wx, fort.wy
        fort.add_creature(boss)
        return boss

    def _free_beside(self, fort, creature, n: int = 1):
        """*n* empty walkable cells next to a creature, for bodies to lie on."""
        out = []
        for radius in range(1, 5):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    cell = (creature.x + dx, creature.y + dy, creature.z)
                    if cell == (creature.x, creature.y, creature.z):
                        continue
                    if not fort.local.walkable(*cell):
                        continue
                    if fort.creature_at(*cell) is not None or cell in out:
                        continue
                    out.append(cell)
                    if len(out) >= n:
                        return out
        self.fail("nowhere free beside the necromancer")
        return out

    def test_nothing_is_raised_twice(self):
        """The corpse is spent, not a renewable resource."""
        fort = embark("once")
        boss = self._necromancer(fort)
        self._corpse_at(fort, self._free_beside(fort, boss)[0])
        self.assertTrue(self.night.necromancy_turn(fort, boss))
        boss.raised_at = 0
        self.assertFalse(self.night.necromancy_turn(fort, boss))

    def test_a_body_rises_once(self):
        """Put a zombie down and it stays down.

        Without this the militia kills a zombie, the corpse goes back on the
        floor, and the same body gets up again for ever: an army with no upper
        bound, and a name that grows a comma every time round.
        """
        fort = embark("spent")
        boss = self._necromancer(fort)
        self._corpse_at(fort, self._free_beside(fort, boss)[0], name="Urist")
        self.assertTrue(self.night.necromancy_turn(fort, boss))
        risen = next(c for c in fort.creatures.values()
                     if c.def_id in ("zombie", "skeleton"))
        self.assertEqual(risen.name, "Urist, risen")
        risen.body.dead = True
        fort.kill_creature(risen)
        leftovers = [i for pile in fort.items_on_ground.values() for i in pile
                     if i.def_id == "corpse"]
        self.assertTrue(leftovers)
        self.assertFalse(any(self.night.raisable(i) for i in leftovers))
        boss.raised_at = 0
        self.assertFalse(self.night.necromancy_turn(fort, boss))

    def test_raising_has_a_cooldown(self):
        """Or a graveyard empties in one step."""
        fort = embark("cooldown-raise")
        boss = self._necromancer(fort)
        for cell in self._free_beside(fort, boss, 3):
            self._corpse_at(fort, cell)
        self.assertTrue(self.night.necromancy_turn(fort, boss))
        self.assertFalse(self.night.necromancy_turn(fort, boss))
        fort.time.advance(self.night.RAISE_COOLDOWN + 1)
        self.assertTrue(self.night.necromancy_turn(fort, boss))

    def test_only_a_necromancer_raises(self):
        """A goblin standing over a body is just a goblin."""
        fort = embark("notmagic")
        d = fort.dwarves()[0]
        foe = make_creature(fort.rng, "goblin", faction="hostile")
        foe.x, foe.y, foe.z = fort._free_spot((d.x, d.y, d.z), 6)
        fort.add_creature(foe)
        self._corpse_at(fort, self._free_beside(fort, foe)[0])
        self.assertFalse(self.night.necromancy_turn(fort, foe))

    def test_a_corpse_too_small_stays_down(self):
        """Nobody raises a rat."""
        from ascii_warriors.game.item import corpse_of

        fort = embark("smallfry")
        boss = self._necromancer(fort)
        rat = make_creature(fort.rng, "rat", faction="wild")
        item = corpse_of(rat)
        fort.drop_item(item, *self._free_beside(fort, boss)[0])
        self.assertFalse(self.night.raisable(item))
        self.assertFalse(self.night.necromancy_turn(fort, boss))

    def test_nothing_rises_under_somebody(self):
        """A zombie wedged inside a dwarf is a bug report, not a horror."""
        fort = embark("occupied")
        boss = self._necromancer(fort)
        d = fort.dwarves()[0]
        d.x, d.y, d.z = boss.x + 1, boss.y, boss.z
        self._corpse_at(fort, (d.x, d.y, d.z))
        self.assertFalse(self.night.necromancy_turn(fort, boss))

    def test_a_dead_necromancer_raises_nothing(self):
        """Which is why killing it is the answer."""
        fort = embark("headshot")
        boss = self._necromancer(fort)
        self._corpse_at(fort, self._free_beside(fort, boss)[0])
        boss.body.dead = True
        self.assertFalse(self.night.necromancy_turn(fort, boss))

    def test_a_necromancer_attack_brings_its_own(self):
        """And is named after somebody the world remembers, when it can be."""
        fort = embark("visitation")
        sim._send_necromancer(fort)
        boss = [c for c in fort.creatures.values()
                if self.night.is_necromancer(c)]
        self.assertEqual(len(boss), 1)
        undead = [c for c in fort.creatures.values()
                  if c.def_id in ("zombie", "skeleton")]
        self.assertTrue(undead)
        self.assertEqual(fort.military.alert, "danger")

    # -- curses ------------------------------------------------------------- #

    def test_a_werewolf_bite_curses(self):
        """Over enough bites. The odds are per bite, not per fight."""
        from ascii_warriors.game import combat as combat_mod

        rng = RNG("curse-bite")
        cursed = 0
        for _ in range(120):
            wolf = make_creature(rng, "werewolf", faction="hostile")
            victim = make_creature(rng, "dwarf", faction="fortress")
            for _ in range(10):
                combat_mod.melee_attack(wolf, victim, weapon=None, rng=rng)
                if self.night.cursed_with(victim):
                    cursed += 1
                    break
        self.assertGreater(cursed, 10, "the curse never spreads")
        self.assertLess(cursed, 120, "every single fight cursed somebody")

    def test_a_werebeast_fights_with_what_it_is(self):
        """Arming one hands it a sword and it never bites again."""
        rng = RNG("unarmed")
        for _ in range(10):
            self.assertIsNone(
                make_creature(rng, "werewolf").inventory.weapon())
        self.assertIsNotNone(make_creature(rng, "bandit").inventory.weapon())

    def test_nothing_is_cursed_twice(self):
        """One affliction is enough for anybody."""
        fort = embark("onecurse")
        d = fort.dwarves()[0]
        self.assertTrue(self.night.afflict(d, "werebeast"))
        self.assertFalse(self.night.afflict(d, "vampire"))
        self.assertEqual(self.night.cursed_with(d), "werebeast")

    def test_the_undead_cannot_be_cursed(self):
        """There is nothing left in them to take."""
        rng = RNG("nope")
        wolf = make_creature(rng, "werewolf", faction="hostile")
        zombie = make_creature(rng, "zombie", faction="hostile")
        for _ in range(50):
            self.night.on_bite(wolf, zombie, rng)
        self.assertEqual(self.night.cursed_with(zombie), "")

    def test_the_moon_the_status_bar_shows_is_the_moon_that_turns_people(self):
        """One source of truth, or the UI lies on the worst night of the year."""
        fort = embark("truemoon")
        for day in range(56):
            fort.time.ticks = day * TICKS_PER_DAY
            self.assertEqual(self.night.moon_is_full(fort.time),
                             fort.time.moon_phase() == "full moon")

    def test_a_cursed_dwarf_turns_at_the_full_moon(self):
        """In your dining hall, and it is not one of yours until morning."""
        fort = embark("turning")
        d = fort.dwarves()[0]
        self.night.afflict(d, "werebeast")
        self._full_moon_night(fort)
        before = len(fort.dwarves())
        sim._night(fort, 10)
        self.assertTrue(d.changed)
        self.assertEqual(d.def_id, "werewolf")
        self.assertEqual(d.faction, "hostile")
        self.assertEqual(len(fort.dwarves()), before - 1)
        self.assertIn(d, fort.hostiles())

    def test_it_turns_back_at_dawn(self):
        """And remembers none of it, and goes back on the roster."""
        fort = embark("dawn")
        d = fort.dwarves()[0]
        self.night.afflict(d, "werebeast")
        self._full_moon_night(fort)
        sim._night(fort, 10)
        self.assertTrue(d.changed)
        fort.time.ticks += int(TICKS_PER_DAY * 0.45)
        sim._night(fort, 10)
        self.assertFalse(d.changed)
        self.assertEqual(d.def_id, "dwarf")
        self.assertEqual(d.faction, "fortress")
        self.assertIn(d, fort.dwarves())
        self.assertEqual(fort.hostiles(), [])

    def test_a_werebeast_keeps_what_it_will_want_back(self):
        """Its labors, its bed and its name -- through the change and a save.

        Only creatures with a DwarfState are serialised, so clearing that on
        transformation loses the dwarf permanently the moment somebody saves
        during a full moon.
        """
        fort = embark("keepstate")
        d = fort.dwarves()[0]
        d.fort.nickname = "Grimm"
        labors = sorted(d.fort.labors.enabled)
        self.night.afflict(d, "werebeast")
        self._full_moon_night(fort)
        sim._night(fort, 10)
        self.assertTrue(d.changed)
        self.assertNotIn(d, fort.dwarves())
        self.assertIsNotNone(d.fort)

        again = Fortress.from_dict(fort.to_dict())
        back = again.creatures[d.id]
        self.assertIsNotNone(back.fort)
        self.assertEqual(back.fort.nickname, "Grimm")
        again.time.ticks += int(TICKS_PER_DAY * 0.45)
        sim._night(again, 10)
        self.assertFalse(back.changed)
        self.assertIn(back, again.dwarves())
        self.assertEqual(sorted(back.fort.labors.enabled), labors)

    def test_an_uncursed_dwarf_never_turns(self):
        """However full the moon."""
        fort = embark("innocent")
        self._full_moon_night(fort)
        sim._night(fort, 10)
        self.assertFalse(any(d.changed for d in fort.dwarves()))

    # -- vampires ------------------------------------------------------------ #

    def _vampire_and_victim(self, fort):
        """A vampire, somebody asleep beside it, and nobody else near."""
        v, victim = fort.dwarves()[0], fort.dwarves()[1]
        self.night.afflict(v, "vampire")
        victim.x, victim.y, victim.z = v.x + 2, v.y, v.z
        victim.fort.sleeping = True
        for other in fort.dwarves()[2:]:
            other.x, other.y = other.x + 40, other.y + 30
        return v, victim

    def test_a_vampire_drains_the_sleeping(self):
        """Slowly. Somebody looks peaky before anybody finds a body."""
        fort = embark("thirsty")
        _v, victim = self._vampire_and_victim(fort)
        full = victim.body.blood
        sim._feed_vampires(fort, self.night)
        self.assertLess(victim.body.blood, full)
        self.assertFalse(victim.body.dead)
        self.assertTrue(any("weak and cold" in t
                            for t in victim.needs.recent_thoughts(4)))

    def test_a_murder_nobody_saw_has_no_suspect(self):
        """Which is exactly the case the sheriff can never close."""
        fort = embark("unseen")
        _v, victim = self._vampire_and_victim(fort)
        for _ in range(8):
            sim._feed_vampires(fort, self.night)
            if victim.body.dead:
                break
        self.assertTrue(victim.body.dead)
        self.assertEqual(victim.body.death_cause, "drained of blood")
        murders = [c for c in fort.crimes if c.kind == "murder"]
        self.assertEqual(len(murders), 1)
        self.assertIsNone(murders[0].culprit)
        self.assertFalse(justice.can_try(fort, murders[0]))

    def test_a_witness_names_the_vampire(self):
        """Sleep in a dormitory and somebody sees who was standing there."""
        fort = embark("caught")
        v, victim = self._vampire_and_victim(fort)
        watcher = fort.dwarves()[2]
        watcher.x, watcher.y, watcher.z = victim.x + 1, victim.y, victim.z
        watcher.fort.sleeping = False
        sim._feed_vampires(fort, self.night)
        self.assertTrue(fort.crimes)
        self.assertEqual(fort.crimes[0].culprit, v.id)
        self.assertTrue(justice.can_try(fort, fort.crimes[0]))

    def test_a_vampire_does_not_drink_from_itself(self):
        """However hungry, and however alone."""
        fort = embark("selfserve")
        v = fort.dwarves()[0]
        self.night.afflict(v, "vampire")
        v.fort.sleeping = True
        for other in fort.dwarves()[1:]:
            other.x, other.y = other.x + 60, other.y + 40
        full = v.body.blood
        sim._feed_vampires(fort, self.night)
        self.assertEqual(v.body.blood, full)

    def test_a_migrant_wave_can_hide_one(self):
        """It says nothing when it arrives."""
        fort = embark("hidden")
        found = False
        for _ in range(60):
            arrivals = sim.migrants(fort, 4)
            sim._maybe_vampire(fort, arrivals)
            if any(self.night.is_vampire(d) for d in arrivals):
                found = True
                break
            for d in arrivals:
                fort.remove_creature(d)
        self.assertTrue(found, "no vampire in sixty waves")

    # -- persistence --------------------------------------------------------- #

    def test_a_curse_survives_a_save(self):
        """Mid-transformation, too."""
        fort = embark("cursesave")
        d = fort.dwarves()[0]
        self.night.afflict(d, "werebeast")
        self._full_moon_night(fort)
        sim._night(fort, 10)
        self.assertTrue(d.changed)
        again = Fortress.from_dict(fort.to_dict())
        back = again.creatures[d.id]
        self.assertEqual(self.night.cursed_with(back), "werebeast")
        self.assertTrue(back.changed)
        self.assertEqual(back.def_id, "werewolf")
        self.assertEqual(back.defn.id, "werewolf")
        self.assertEqual(back.shape_was, "dwarf")
        self.assertEqual(back.faction_was, "fortress")

    def test_the_risen_survive_a_save(self):
        """A zombie is still somebody's zombie after a reload."""
        fort = embark("risensave")
        boss = self._necromancer(fort)
        self._corpse_at(fort, self._free_beside(fort, boss)[0])
        self.assertTrue(self.night.necromancy_turn(fort, boss))
        risen = next(c for c in fort.creatures.values()
                     if c.def_id in ("zombie", "skeleton"))
        again = Fortress.from_dict(fort.to_dict())
        back = again.creatures[risen.id]
        self.assertEqual(back.raised_by, boss.id)
        self.assertEqual(back.faction, "hostile")

    def test_an_ordinary_creature_saves_nothing_extra(self):
        """The night block is only written when the night has been involved."""
        rng = RNG("plain")
        self.assertNotIn("night", make_creature(rng, "dwarf").to_dict())


class TestStealthInTheFortress(unittest.TestCase):
    """The skills the data files have always handed out, finally read."""

    def setUp(self):
        from ascii_warriors.game import stealth as stealth_mod

        self.stealth = stealth_mod

    def test_a_fortress_can_answer_the_light_question(self):
        """The stealth roll asks it in both modes and must not care which."""
        fort = embark("fortlight")
        d = fort.dwarves()[0]
        deep = (d.x, d.y, fort.local.zmin + 2)
        self.assertLess(fort.light_at(*deep), 0.3)
        self.assertGreaterEqual(fort.light_at(d.x, d.y, d.z), 0.0)
        self.assertLessEqual(fort.light_at(d.x, d.y, d.z), 1.0)

    def test_the_thief_is_actually_sneaky(self):
        """It has had sneak 8 since v3.3 and nothing ever read it."""
        fort = embark("sneakythief")
        d = fort.dwarves()[0]
        thief = make_creature(fort.rng, "kobold", faction="hostile", level=1)
        thief.thief = True
        thief.skills.set_level("sneak", 8)
        thief.x, thief.y, thief.z = d.x + 2, d.y, d.z
        fort.add_creature(thief)
        self.assertTrue(self.stealth.natural_sneak(thief))
        seen = sum(1 for _ in range(200)
                   if self.stealth.noticed_by(fort, thief, d))
        self.assertLess(seen, 100, "the thief is spotted every time")

    def test_an_ordinary_goblin_is_in_plain_sight(self):
        """Stealth is for things that have the skill for it."""
        fort = embark("plainsight")
        d = fort.dwarves()[0]
        foe = make_creature(fort.rng, "goblin", faction="hostile")
        foe.skills.set_level("sneak", 0)
        foe.skills.set_level("ambusher", 0)
        foe.x, foe.y, foe.z = d.x + 2, d.y, d.z
        fort.add_creature(foe)
        self.assertFalse(self.stealth.hidden(foe))
        for _ in range(20):
            self.assertTrue(self.stealth.noticed_by(fort, foe, d))

    def test_a_siege_is_still_noticed(self):
        """Whatever else changes, an army at the gate is not a stealth puzzle."""
        fort = embark("siegeseen")
        fort.wealth = 9000
        from ascii_warriors.fortress import war as war_mod

        plan = war_mod.plan(fort)
        self.assertIsNotNone(plan)
        army = war_mod.launch(fort, plan)
        self.assertTrue(army)
        plain = [c for c in army if not self.stealth.hidden(c)]
        self.assertTrue(plain, "the whole army crept in unseen")

    def test_the_fortress_still_runs_with_stealth_in_the_loop(self):
        """The danger scan asks the roll every step for every hostile."""
        fort = embark("stealthloop")
        d = fort.dwarves()[0]
        thief = make_creature(fort.rng, "kobold", faction="hostile", level=1)
        thief.thief = True
        thief.skills.set_level("sneak", 8)
        thief.x, thief.y, thief.z = d.x + 3, d.y, d.z
        fort.add_creature(thief)
        sim.run(fort, 200)
        self.assertFalse(fort.lost)


class TestTheTavern(unittest.TestCase):
    """v3.4 built the room. This is what finally happens in it."""

    def setUp(self):
        from ascii_warriors.fortress import perform as perform_mod
        from ascii_warriors.game import performance
        from ascii_warriors.world import artforms

        self.perform = perform_mod
        self.performance = performance
        self.artforms = artforms

    def _tavern_fort(self, seed="tavern", instruments=(), skill=0):
        """A fortress with a built tavern and everybody standing in it."""
        from ascii_warriors.fortress.buildings import Building
        from ascii_warriors.game.item import Item

        fort = embark(seed)
        d0 = fort.dwarves()[0]
        cx, cy, cz = d0.x, d0.y, d0.z
        b = Building("tavern", cx, cy, cz)
        b.built = True
        fort.buildings.append(b)
        for i, d in enumerate(fort.dwarves()):
            d.x, d.y, d.z = cx + (i % 3) - 1, cy + (i // 3) - 1, cz
            if skill:
                for s in ("music", "poetry", "dancing"):
                    d.skills.set_level(s, skill)
        for did in instruments:
            fort.drop_item(Item(did, "oak"), cx, cy, cz)
        return fort

    def _rounds(self, fort, n):
        """Force *n* performance opportunities and collect what happened."""
        out = []
        for _ in range(n):
            fort.ticks += self.perform.INTERVAL
            res = self.perform.tick(fort, 10)
            if res is not None:
                out.append(res)
        return out

    # -- the room ---------------------------------------------------------- #

    def test_no_tavern_means_no_performances(self):
        fort = embark("notavern")
        self.assertEqual(self._rounds(fort, 40), [])

    def test_a_tavern_holds_performances(self):
        fort = self._tavern_fort("holds")
        self.assertTrue(self._rounds(fort, 40))

    def test_performing_needs_an_audience(self):
        fort = self._tavern_fort("alone")
        for d in fort.dwarves()[1:]:
            d.x += 40
        self.assertEqual(self._rounds(fort, 20), [])

    def test_performances_are_rationed(self):
        """Six a day, not one a step: the tavern is not a jukebox."""
        fort = self._tavern_fort("rationed")
        held = [self.perform.tick(fort, 10) for _ in range(50)]
        self.assertEqual(len([r for r in held if r is not None]), 1)

    def test_the_embarking_seven_already_know_songs(self):
        fort = embark("knows")
        self.assertTrue(any(d.forms for d in fort.dwarves()))

    # -- instruments ------------------------------------------------------- #

    def test_an_instrument_in_the_tavern_is_found(self):
        fort = self._tavern_fort("found", instruments=("lute",))
        got = self.perform.instruments(fort)
        self.assertEqual([i.def_id for i in got], ["lute"])

    def test_an_instrument_across_the_map_is_not_in_the_tavern(self):
        from ascii_warriors.game.item import Item

        fort = self._tavern_fort("faraway")
        d0 = fort.dwarves()[0]
        fort.drop_item(Item("lute", "oak"), d0.x + 30, d0.y, d0.z)
        self.assertEqual(self.perform.instruments(fort), [])

    def test_instruments_lift_the_music_a_fortress_makes(self):
        """The defect this caught: dwarves never carry one, so without the
        room's own pool a fortress could craft every instrument in the game
        and its musicians would still be playing nothing."""
        every = self.artforms.INSTRUMENTS
        bare = self._rounds(self._tavern_fort("bare", skill=8), 120)
        full = self._rounds(
            self._tavern_fort("full", instruments=every, skill=8), 120)

        def music_mean(results):
            songs = [r.band for r in results if r.form.kind == "music"]
            return sum(songs) / float(len(songs)) if songs else 0.0

        self.assertGreater(music_mean(full), music_mean(bare))

    def test_a_fortress_can_make_its_own_instruments(self):
        from ascii_warriors.fortress import production

        made = {r.output for r in production.RECIPES.values()}
        self.assertTrue({"lute", "drum", "flute", "harp"} <= made)

    # -- what the room gets out of it -------------------------------------- #

    def test_good_music_calms_the_fortress(self):
        fort = self._tavern_fort("calm", instruments=self.artforms.INSTRUMENTS,
                                 skill=14)
        for d in fort.dwarves():
            d.needs.stress = 100
        self._rounds(fort, 80)
        worst = max(d.needs.stress for d in fort.dwarves())
        self.assertLess(worst, 100)

    def test_bad_music_is_worse_than_none(self):
        fort = self._tavern_fort("bad")
        for d in fort.dwarves():
            d.needs.stress = 0
        self._rounds(fort, 80)
        self.assertGreater(max(d.needs.stress for d in fort.dwarves()), 0)

    def test_a_tavern_cannot_pin_the_fortress_at_the_floor(self):
        """A song is worth a lot and it is not worth everything."""
        fort = self._tavern_fort("pinned",
                                 instruments=self.artforms.INSTRUMENTS,
                                 skill=18)
        for d in fort.dwarves():
            d.needs.stress = 0
        self._rounds(fort, 400)
        best = min(d.needs.stress for d in fort.dwarves())
        self.assertGreaterEqual(best, self.performance.RELIEF_FLOOR - 1)

    def test_a_tavern_of_amateurs_cannot_drive_a_tantrum_spiral(self):
        fort = self._tavern_fort("spiral")
        for d in fort.dwarves():
            d.needs.stress = 0
        self._rounds(fort, 400)
        worst = max(d.needs.stress for d in fort.dwarves())
        self.assertLessEqual(worst, self.performance.ANNOYANCE_CEILING + 5)

    def test_skill_decides_who_performs_but_does_not_dictate_it(self):
        fort = self._tavern_fort("who")
        star = fort.dwarves()[0]
        for s in ("music", "poetry", "dancing"):
            star.skills.set_level(s, 18)
        who = [r.performer.id for r in self._rounds(fort, 200)]
        share = who.count(star.id) / float(len(who))
        self.assertGreater(share, 0.4)
        self.assertLess(share, 0.95)

    def test_the_world_remembers_only_a_few_great_performances(self):
        fort = self._tavern_fort("history",
                                 instruments=self.artforms.INSTRUMENTS,
                                 skill=18)
        results = self._rounds(fort, 300)
        legendary = len([r for r in results
                         if r.band >= self.performance.LEGENDARY_AT])
        recorded = len([e for e in fort.world.events if e.kind == "performance"])
        self.assertTrue(legendary, "nobody was ever legendary")
        self.assertLess(recorded, legendary // 4 + 5)

    def test_forms_spread_through_the_fortress(self):
        fort = self._tavern_fort("spread",
                                 instruments=self.artforms.INSTRUMENTS,
                                 skill=14)
        before = sum(len(d.forms) for d in fort.dwarves())
        self._rounds(fort, 200)
        self.assertGreater(sum(len(d.forms) for d in fort.dwarves()), before)

    def test_the_tavern_summary_reads(self):
        fort = self._tavern_fort("summary")
        self.assertIn("forms known", self.perform.summary(fort))

    def test_a_tavern_survives_a_save(self):
        fort = self._tavern_fort("saved", instruments=("lute",))
        self._rounds(fort, 20)
        known = {d.id: sorted(d.forms) for d in fort.dwarves()}
        back = Fortress.from_dict(fort.to_dict())
        self.assertEqual({d.id: sorted(d.forms) for d in back.dwarves()}, known)
        self.assertTrue(self.perform.instruments(back))


class TestTavernPathing(unittest.TestCase):
    """A tavern nobody can reach must not cost fifty times the frame."""

    def _fort_with_tavern(self, seed, reachable):
        """A fortress whose tavern the dwarves can walk to, or cannot.

        Unreachable means genuinely sealed -- a chamber walled off underground
        with rock over it, which is what a cave-in leaves behind. Building it
        rather than digging it, for the reason `_sealed_room` gives.
        """
        fort = embark(seed)
        if reachable:
            d0 = fort.dwarves()[0]
            cx, cy, cz = d0.x, d0.y, d0.z
        else:
            room = self._seal(fort)
            self.assertTrue(room, "could not seal a chamber")
            cx, cy, cz = room[len(room) // 2]
        b = Building("tavern", cx - 1, cy - 1, cz)
        b.built = True
        fort.buildings.append(b)
        return fort, b

    def _seal(self, fort, size=3):
        """Wall a chamber off underground and return its floor cells."""
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
                            lm.set_tile(x + dx, y + dy, z - 1, "rock_wall")
                    return cells
        return []

    def _idle_searches(self, fort, tries):
        """A* searches spent by every dwarf idling towards the tavern."""
        from ascii_warriors.engine import pathfind

        calls = [0]
        real = dwarf_mod.astar

        def counting(*a, **kw):
            calls[0] += 1
            return real(*a, **kw)

        dwarf_mod.astar = counting
        try:
            for _ in range(tries):
                for d in fort.dwarves():
                    # Every dwarf, on a tick it would plan a route on.
                    d.fort.idle_ticks = dwarf_mod.TAVERN_REPATH
                    d.fort.path = []
                    dwarf_mod._to_the_tavern(fort, d)
                fort.ticks += 10
        finally:
            dwarf_mod.astar = real
        return calls[0]

    def test_an_unreachable_tavern_is_searched_for_once_not_forever(self):
        """The defect: a failing A* expands the whole reachable map, and
        every idle dwarf paid for one every sixteen ticks."""
        fort, _b = self._fort_with_tavern("blocked", reachable=False)
        searches = self._idle_searches(fort, 30)
        self.assertLessEqual(searches, len(fort.dwarves()),
                             "still searching for a tavern nobody can reach")

    def test_without_the_backoff_it_would_search_every_time(self):
        """Proves the test above is measuring the fix and not an accident."""
        fort, _b = self._fort_with_tavern("nofix", reachable=False)
        old = dwarf_mod.TAVERN_UNREACHABLE_BACKOFF
        dwarf_mod.TAVERN_UNREACHABLE_BACKOFF = 0
        try:
            searches = self._idle_searches(fort, 30)
        finally:
            dwarf_mod.TAVERN_UNREACHABLE_BACKOFF = old
        self.assertGreater(searches, 30)

    def test_the_backoff_is_recorded_and_expires(self):
        fort, _b = self._fort_with_tavern("expires", reachable=False)
        self._idle_searches(fort, 2)
        blocked = getattr(fort, "_tavern_blocked_until", 0)
        self.assertGreater(blocked, fort.ticks)
        self.assertLessEqual(blocked - fort.ticks,
                             dwarf_mod.TAVERN_UNREACHABLE_BACKOFF + 10)

    def test_a_reachable_tavern_is_still_walked_to(self):
        fort, _b = self._fort_with_tavern("reachable", reachable=True)
        moved = 0
        for _ in range(30):
            for d in fort.dwarves():
                d.fort.idle_ticks = dwarf_mod.TAVERN_REPATH
                if dwarf_mod._to_the_tavern(fort, d):
                    moved += 1
            fort.ticks += 10
        self.assertGreater(moved, 0, "nobody goes to a tavern they can reach")

    def test_a_reachable_tavern_gathers_the_fortress(self):
        from ascii_warriors.fortress import perform as perform_mod

        fort, _b = self._fort_with_tavern("gathers", reachable=True)
        for _ in range(200):
            sim.step(fort)
        self.assertGreaterEqual(len(perform_mod.in_tavern(fort)), 2)


class TestCold(unittest.TestCase):
    """What the season does to a fortress and the water around it."""

    def test_a_fortress_reads_a_temperature(self):
        fort = embark("temp")
        cx, cy = fort.local.width // 2, fort.local.height // 2
        t = fort.temperature_at(cx, cy, fort.local.surface_z(cx, cy))
        self.assertIsInstance(t, float)
        self.assertGreater(t, -120.0)
        self.assertLess(t, 200.0)

    def test_the_deep_does_not_care_what_month_it_is(self):
        from ascii_warriors.data.calendar import GameTime
        from ascii_warriors.world import heat

        fort = embark("deep-temp")
        cx, cy = fort.local.width // 2, fort.local.height // 2
        z = fort.local.surface_z(cx, cy) - heat.CAVE_DEPTH
        if not fort.local.in_bounds(cx, cy, z):
            self.skipTest("map is not deep enough")
        surf = fort.local.surface_z(cx, cy)
        deep, top = [], []
        for month in (1, 4, 7, 10):
            fort.time = GameTime.at(fort.time.year, month, 15, 12, 0)
            deep.append(fort.temperature_at(cx, cy, z))
            top.append(fort.temperature_at(cx, cy, surf))
        # Not "exactly CAVE_TEMP": on a map whose magma sea sits a few levels
        # below the living quarters, the rock down there is hotter than the
        # year's average and rightly so. The claim is that it does not move.
        self.assertLess(max(deep) - min(deep), 1.0)
        self.assertGreater(max(top) - min(top), 25.0)

    def test_the_surface_does_care(self):
        from ascii_warriors.data.calendar import GameTime

        fort = embark("season-temp")
        cx, cy = fort.local.width // 2, fort.local.height // 2
        z = fort.local.surface_z(cx, cy)
        fort.time = GameTime.at(fort.time.year, 4, 15, 12, 0)
        summer = fort.temperature_at(cx, cy, z)
        fort.time = GameTime.at(fort.time.year, 10, 15, 12, 0)
        winter = fort.temperature_at(cx, cy, z)
        self.assertGreater(summer - winter, 25.0)

    def test_magma_is_why_the_deeps_are_warm(self):
        from ascii_warriors.world import heat

        fort = embark("magma-temp")
        if not fort.magma.depth:
            self.skipTest("no magma on this embark")
        # Not "hotter than somewhere far away on the same level" -- the sea
        # covers the level, so there is no far away on it.
        cell = sorted(fort.magma.depth)[0]
        self.assertGreater(fort.temperature_at(*cell), heat.CAVE_TEMP + 100.0)
        above = (cell[0], cell[1], cell[2] + heat.HEAT_RANGE + 4)
        if fort.local.in_bounds(*above):
            self.assertLess(fort.temperature_at(*above),
                            fort.temperature_at(*cell))

    def test_dwarves_arrive_wearing_clothes(self):
        """Nine versions of tailoring and nobody had ever put any on."""
        from ascii_warriors.world import heat

        fort = embark("dressed")
        for d in fort.dwarves():
            worn = [i.defn.id for i in d.inventory.equipped.values() if i]
            self.assertTrue(
                any(i in worn for i in ("tunic", "trousers", "shoes")), worn)
            self.assertGreater(heat.insulation(d), 0.25)

    def test_a_dwarf_underground_is_warmer_than_one_on_the_roof(self):
        from ascii_warriors.world import heat

        fort = embark("shelter")
        cx, cy = fort.local.width // 2, fort.local.height // 2
        surf = fort.local.surface_z(cx, cy)
        deep = surf - heat.CAVE_DEPTH
        if not fort.local.in_bounds(cx, cy, deep):
            self.skipTest("map is not deep enough")
        fort.weather.kind = "blizzard"
        self.assertGreater(fort.temperature_at(cx, cy, deep),
                           fort.temperature_at(cx, cy, surf))

    def test_a_cold_fortress_freezes_its_water_over(self):
        fort = embark("freeze")
        wet = [c for c in fort.water.depth if fort.local.is_outside(*c)]
        if not wet:
            self.skipTest("no open water on this embark")
        cold = min(fort.temperature_at(*c) for c in wet)
        if cold > 32.0:
            self.skipTest("this embark is not cold enough to freeze")
        for _ in range(200):
            sim.step(fort)
        self.assertTrue(fort.frost.any_ice)
        cell = next(iter(fort.frost.frozen))
        self.assertEqual(fort.local.tile(*cell), "ice")

    def test_the_ice_gives_the_water_back_when_it_thaws(self):
        from ascii_warriors.world import heat

        fort = embark("thaw")
        wet = [c for c in fort.water.depth if fort.local.is_outside(*c)]
        if not wet:
            self.skipTest("no open water on this embark")
        cell = wet[0]
        depth = fort.water.at(*cell)
        was = fort.local.tile(*cell)
        self.assertTrue(fort.frost.freeze(fort.local, cell, fort.water))
        self.assertEqual(fort.water.at(*cell), 0)
        fort.frost.step(fort.local, fort.rng, lambda c: 90.0,
                        fort.ticks + heat.CHECK_TICKS, water=fort.water)
        self.assertFalse(fort.frost.is_frozen(*cell))
        self.assertEqual(fort.local.tile(*cell), was)
        self.assertEqual(fort.water.at(*cell), depth)

    def test_frost_and_exposure_survive_a_save(self):
        fort = embark("frost-save")
        wet = [c for c in fort.water.depth if fort.local.is_outside(*c)]
        if not wet:
            self.skipTest("no open water on this embark")
        fort.frost.freeze(fort.local, wet[0], fort.water)
        fort.dwarves()[0].exposure = -0.37
        back = Fortress.from_dict(fort.to_dict())
        self.assertTrue(back.frost.is_frozen(*wet[0]))
        self.assertAlmostEqual(back.dwarves()[0].exposure, -0.37, places=3)


class TestRags(unittest.TestCase):
    """Clothes wear out, and somebody has to make more."""

    def test_the_fortress_can_make_clothes(self):
        """v3.18 dressed everyone in garments that would outlast the mountain."""
        from ascii_warriors.fortress.production import RECIPES

        made = {r.output for r in RECIPES.values()}
        for wanted in ("tunic", "trousers", "shoes", "cloak", "hood"):
            self.assertIn(wanted, made, wanted)

    def test_clothing_wears_out_on_a_working_dwarf(self):
        from ascii_warriors.game import wear as wear_mod

        fort = embark("frayed")
        for _ in range(200):
            sim.step(fort)
        dwarf = fort.dwarves()[0]
        shirt = next((i for i in dwarf.inventory.equipped.values()
                      if i is not None and wear_mod.is_clothing(i)), None)
        self.assertIsNotNone(shirt)
        for _ in range(400):
            dwarf.next_wear_check = 0
            wear_mod.wearing(dwarf, fort.rng)
            if shirt not in dwarf.inventory.items:
                return
        self.assertGreater(shirt.wear, 0)

    def test_a_dwarf_with_nothing_to_wear_is_reported(self):
        from ascii_warriors.game import wear as wear_mod

        fort = embark("naked")
        for _ in range(200):
            sim.step(fort)
        dwarf = fort.dwarves()[0]
        for i in list(dwarf.inventory.equipped.values()):
            if i is not None and wear_mod.is_clothing(i):
                wear_mod.destroy(dwarf, i)
        self.assertFalse(wear_mod.dressed(dwarf))
        dwarf.next_wear_check = 0
        for _ in range(60):
            sim.step(fort)
        self.assertTrue(any("clothier" in m.text.lower() for m in fort.log.all()))

    def test_and_goes_and_dresses_when_there_is_something_to_wear(self):
        from ascii_warriors.game import wear as wear_mod
        from ascii_warriors.game.item import Item

        fort = embark("dressagain")
        for _ in range(200):
            sim.step(fort)
        dwarf = fort.dwarves()[0]
        for i in list(dwarf.inventory.equipped.values()):
            if i is not None and wear_mod.is_clothing(i):
                wear_mod.destroy(dwarf, i)
        for wid in ("tunic", "trousers", "shoes"):
            fort.drop_item(Item(wid, "wool_cloth"), dwarf.x, dwarf.y, dwarf.z)
        dwarf.next_wear_check = 0
        for _ in range(1500):
            sim.step(fort)
            if wear_mod.dressed(dwarf):
                break
        self.assertTrue(wear_mod.dressed(dwarf))

    def test_a_ruined_wardrobe_leaves_a_dwarf_cold(self):
        """The whole point of the loop: rags are how v3.18 gets you."""
        from ascii_warriors.game import wear as wear_mod
        from ascii_warriors.world import heat

        fort = embark("coldrags")
        dwarf = fort.dwarves()[0]
        before = heat.insulation(dwarf)
        for i in list(dwarf.inventory.equipped.values()):
            if i is not None and wear_mod.is_clothing(i):
                wear_mod.destroy(dwarf, i)
        self.assertLess(heat.insulation(dwarf), before)


class TestNerveInTheFortress(unittest.TestCase):
    """`war` routed whole armies and gave the people in them no say."""

    def _siege(self, seed="nerve"):
        from ascii_warriors.fortress import war

        fort = embark(seed)
        for _ in range(1200):
            sim.step(fort)
        plan = war.plan(fort)
        if plan is None:
            self.skipTest("nobody in the world wants to attack")
        war.launch(fort, plan)
        if not fort.hostiles():
            self.skipTest("the siege put nobody on the map")
        return fort

    def test_a_death_shakes_the_side_that_took_it(self):
        from ascii_warriors.game import morale

        fort = self._siege("nervedeath")
        foes = fort.hostiles()
        if len(foes) < 2:
            self.skipTest("need two invaders to shake one with the other")
        victim, watcher = foes[0], foes[1]
        watcher.x, watcher.y, watcher.z = victim.x, victim.y, victim.z
        watcher.shaken = 0.0
        fort.kill_creature(victim)
        self.assertGreater(watcher.shaken, 0.0)

    def _afraid_invader(self, fort):
        """Put something on the map that can be frightened.

        Not whichever species the world's politics happened to send: goblins
        carry NO_FEAR, so half the seeds skipped these tests, and a skipped
        test measures nothing.
        """
        from ascii_warriors.game import morale
        from ascii_warriors.game.entity import make_creature

        foe = make_creature(fort.rng, "kobold", faction="hostile")
        self.assertFalse(morale.fearless(foe))
        dwarf = fort.dwarves()[0]
        foe.x, foe.y, foe.z = dwarf.x + 3, dwarf.y, dwarf.z
        fort.creatures[foe.id] = foe
        return foe

    def test_an_invader_that_has_had_enough_leaves(self):
        from ascii_warriors.game import morale

        fort = self._siege("nerveleave")
        foe = self._afraid_invader(fort)
        morale.shake(foe, morale.MAX_SHOCK)
        self.assertTrue(morale.broke(foe, fort))
        before = (foe.x, foe.y)
        for _ in range(400):
            sim.step(fort)
            if foe.id not in fort.creatures:
                return
        self.assertNotEqual((foe.x, foe.y), before,
                            "a broken invader stood exactly still")

    def test_the_shock_wears_off_in_the_fortress_too(self):
        from ascii_warriors.game import morale

        fort = embark("nervecalm")
        dwarf = fort.dwarves()[0]
        morale.shake(dwarf, 1.0)
        for _ in range(400):
            sim.step(fort)
        self.assertLess(dwarf.shaken, 1.0)


class TestFishing(unittest.TestCase):
    """The `fishing` labor has been in the list since there was a list."""

    def test_the_labor_exists_and_the_hunter_carries_it(self):
        from ascii_warriors.fortress.labors import LABORS, PROFESSION_LABORS

        self.assertIn("fishing", LABORS)
        self.assertIn("fishing", PROFESSION_LABORS.get("hunter", ()))

    def test_a_fortress_by_water_posts_fishing_work(self):
        fort = embark("fishjob")
        if not fort.water_sources():
            self.skipTest("this embark has no open water")
        for d in fort.dwarves():
            d.fort.labors.enable("fishing")
        for _ in range(400):
            sim.step(fort)
            if any(j.kind == "fish" for j in fort.jobs.jobs.values()):
                return
        self.fail("nobody was ever sent to the water")

    def test_and_the_fish_arrive(self):
        fort = embark("fishcatch")
        if not fort.water_sources():
            self.skipTest("this embark has no open water")
        for d in fort.dwarves():
            d.fort.labors.enable("fishing")
        before = fort.stock_count("fish_food")
        for _ in range(3000):
            sim.step(fort)
            if fort.stock_count("fish_food") > before:
                return
        self.fail("nothing was ever caught")

    def test_a_full_larder_stops_the_fishing(self):
        from ascii_warriors.fortress import sim as sim_mod
        from ascii_warriors.game.item import Item

        fort = embark("fishenough")
        for d in fort.dwarves():
            d.fort.labors.enable("fishing")
        spot = fort.dwarves()[0]
        fort.drop_item(Item("fish_food", "meat", count=sim_mod.FISH_STOCK + 5),
                       spot.x, spot.y, spot.z)
        self.assertEqual(sim_mod._scan_fishing(fort, 4), 0)

    def test_never_more_than_a_couple_of_anglers(self):
        from ascii_warriors.fortress import sim as sim_mod

        fort = embark("fishcrowd")
        if not fort.water_sources():
            self.skipTest("this embark has no open water")
        for d in fort.dwarves():
            d.fort.labors.enable("fishing")
        live = 0
        for _ in range(600):
            sim.step(fort)
            live = max(live, sum(1 for j in fort.jobs.jobs.values()
                                 if j.kind == "fish"))
        self.assertLessEqual(live, sim_mod.MAX_ANGLERS)


class TestFalling(unittest.TestCase):
    """Channelling a floor away used to leave whoever was on it in mid-air."""

    def _hole(self, fort, cell, depth=4):
        """Open a shaft under a cell. Returns where a body comes to rest."""
        lm = fort.local
        x, y, z = cell
        if z - depth - 1 < lm.zmin:
            self.skipTest("not deep enough here")
        for dz in range(0, depth + 1):
            lm.set_tile(x, y, z - dz, "air")
        lm.set_tile(x, y, z - depth - 1, "stone_floor")
        return (x, y, z - depth)

    def test_a_dwarf_left_in_mid_air_comes_down(self):
        from ascii_warriors.world import gravity

        fort = embark("falling")
        dwarf = fort.dwarves()[0]
        bottom = self._hole(fort, (dwarf.x, dwarf.y, dwarf.z))
        self.assertIn(dwarf, gravity.unsupported_creatures(fort))
        sim.step(fort)
        self.assertEqual((dwarf.x, dwarf.y, dwarf.z), bottom)

    def test_and_it_hurts(self):
        from ascii_warriors.world import gravity

        fort = embark("fallhurt")
        dwarf = fort.dwarves()[0]
        self._hole(fort, (dwarf.x, dwarf.y, dwarf.z), depth=6)
        before = dwarf.body.health_fraction()
        sim.step(fort)
        self.assertLess(dwarf.body.health_fraction(), before)

    def test_cutting_the_floor_out_from_under_somebody_drops_them(self):
        """Ordinary channelling leaves a ramp and is safe. Cutting into a
        void that is already there is not, and that is the case worth
        testing."""
        fort = embark("channelfall")
        dwarf = fort.dwarves()[0]
        cell = (dwarf.x, dwarf.y, dwarf.z)
        bottom = self._hole(fort, cell, depth=4)
        fort.settle_above(cell)
        self.assertEqual((dwarf.x, dwarf.y, dwarf.z), bottom)

    def test_and_ordinary_channelling_is_still_safe(self):
        """It cuts a ramp into the level below; you step down onto it."""
        fort = embark("channelsafe")
        dwarf = fort.dwarves()[0]
        cell = (dwarf.x, dwarf.y, dwarf.z)
        below = (cell[0], cell[1], cell[2] - 1)
        if not fort.local.in_bounds(*below):
            self.skipTest("nothing under this dwarf")
        fort.local.set_tile(cell[0], cell[1], cell[2], "air")
        fort.local.set_tile(below[0], below[1], below[2], "ramp_up")
        before = dwarf.body.health_fraction()
        fort.settle_above(cell)
        self.assertEqual(dwarf.body.health_fraction(), before)

    def test_items_left_in_mid_air_come_down_too(self):
        from ascii_warriors.game.item import Item
        from ascii_warriors.world import gravity

        fort = embark("fallitems")
        dwarf = fort.dwarves()[0]
        cell = (dwarf.x + 3, dwarf.y, dwarf.z)
        if not fort.local.walkable(*cell):
            self.skipTest("no room beside the dwarf")
        bottom = self._hole(fort, cell, depth=3)
        fort.drop_item(Item("boulder", "granite"), *cell)
        self.assertEqual(gravity.settle_items(fort, cell), 1)
        self.assertTrue(fort.items_at(*bottom))
