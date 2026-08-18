"""Tests for world generation, history, local maps and the game loop."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from ascii_warriors.data import biomes
from ascii_warriors.engine.pathfind import bfs_reachable
from ascii_warriors.engine.rng import RNG
from ascii_warriors.game.state import Game
from ascii_warriors.world import legends, tiles
from ascii_warriors.world.localmap import LocalMap, generate_local
from ascii_warriors.world.worldgen import World, generate_world, summarize, world_hash


def _world(seed="test", size="pocket", years=40):
    return generate_world(RNG(seed), size=size, history_years=years)


class TestWorldGen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = _world()

    def test_shape_and_content(self):
        w = self.world
        self.assertEqual(w.width, 33)
        self.assertEqual(w.height, 33)
        self.assertTrue(w.name)
        self.assertTrue(w.regions)
        self.assertTrue(w.civs)
        self.assertTrue(w.sites)
        self.assertTrue(w.figures)
        self.assertTrue(w.events)

    def test_every_biome_is_known(self):
        for row in self.world.tiles:
            for t in row:
                self.assertTrue(biomes.exists(t.biome), t.biome)

    def test_has_land_and_sea(self):
        ocean = sum(1 for row in self.world.tiles for t in row if t.is_ocean)
        total = self.world.width * self.world.height
        self.assertGreater(ocean, 0)
        self.assertLess(ocean, total)
        self.assertTrue(self.world.land_tiles())

    def test_determinism(self):
        a = _world("same")
        b = _world("same")
        self.assertEqual(world_hash(a), world_hash(b))
        self.assertEqual(len(a.events), len(b.events))
        self.assertEqual([c.name for c in a.civs], [c.name for c in b.civs])

    def test_different_seeds_differ(self):
        self.assertNotEqual(world_hash(_world("one")), world_hash(_world("two")))

    def test_progress_callback(self):
        seen = []
        generate_world(RNG("prog"), size="pocket", history_years=10,
                       progress=lambda label, frac: seen.append((label, frac)))
        self.assertTrue(seen)
        self.assertTrue(all(0.0 <= f <= 1.0 for _l, f in seen))

    def test_summary(self):
        self.assertTrue(summarize(self.world))

    def test_tiles_clamp_out_of_bounds(self):
        self.assertIsNotNone(self.world.tile(-5, -5))
        self.assertFalse(self.world.in_bounds(-1, 0))

    def test_round_trip(self):
        clone = World.from_dict(json.loads(json.dumps(self.world.to_dict())))
        self.assertEqual(world_hash(clone), world_hash(self.world))
        self.assertEqual(len(clone.sites), len(self.world.sites))
        self.assertEqual(len(clone.figures), len(self.world.figures))
        self.assertEqual(len(clone.events), len(self.world.events))
        self.assertEqual(len(clone.artifacts), len(self.world.artifacts))


class TestEveryBiomeCanHappen(unittest.TestCase):
    """Three biomes were arithmetically impossible and two never happened.

    `biomes.classify` wants rainfall below 0.16 for a desert and drainage
    outside 0.22..0.72 for a swamp or badlands. The generator produced
    rainfall in 0.236..0.941 and drainage in 0.210..0.796, so across fifteen
    worlds and 73,615 tiles there were no deserts, no badlands, no swamps
    worth the name -- and the comment above the rainfall code claimed a rain
    shadow the code had never had.
    """

    #: `river` is a habitat tag rather than a terrain type: `classify` never
    #: returns it and no tile is ever one. Carp and pike list it as where they
    #: live, and `Game._wildlife_for` asks for river creatures when the tile
    #: has a river on it. Anything else here must be real ground.
    HABITAT_ONLY = {"river"}

    @classmethod
    def setUpClass(cls):
        from ascii_warriors.data import biomes as biome_data

        cls.biome_data = biome_data
        cls.seen = {}
        cls.rain = []
        cls.drain = []
        for seed in ("aa", "bb", "cc", "dd", "ee", "ff"):
            world = _world(seed, size="small", years=5)
            for row in world.tiles:
                for t in row:
                    cls.seen[t.biome] = cls.seen.get(t.biome, 0) + 1
                    if not t.is_ocean:
                        cls.rain.append(t.rainfall)
                        cls.drain.append(t.drainage)

    def test_every_terrain_biome_turns_up_somewhere(self):
        missing = [b.id for b in self.biome_data.BIOMES.values()
                   if b.id not in self.HABITAT_ONLY and b.id not in self.seen]
        self.assertEqual(missing, [],
                         "biomes no world can contain: %s" % missing)

    def test_the_climate_reaches_the_thresholds_the_classifier_wants(self):
        """The defect in one line: the ranges did not overlap."""
        self.assertLess(min(self.rain), 0.16,
                        "no tile is dry enough to be a desert")
        self.assertGreater(max(self.rain), 0.70, "nowhere is properly wet")
        self.assertLess(min(self.drain), 0.22, "nothing drains badly enough")
        self.assertGreater(max(self.drain), 0.72, "nothing drains well enough")

    def test_it_is_not_a_desert_planet(self):
        """The first fix overcorrected: desert went from 0% to 60% of land
        and temperate forest from 40% to 1.4%."""
        land = len(self.rain)
        desert = self.seen.get("desert", 0) + self.seen.get("badlands", 0)
        self.assertLess(desert, land * 0.30,
                        "the world is mostly desert")
        wooded = sum(self.seen.get(b, 0) for b in
                     ("temperate_forest", "temperate_broadleaf", "taiga",
                      "tropical_forest", "jungle"))
        self.assertGreater(wooded, land * 0.15, "the trees are gone")

    def test_a_rain_shadow_actually_exists(self):
        """The comment promised one for a long time before there was one."""
        from ascii_warriors.world import worldgen

        flat = [[0.5] * 12 for _ in range(12)]
        ridge = [row[:] for row in flat]
        for y in range(12):
            ridge[y][5] = 0.95
        wind = (1, 0)
        # Downwind of the ridge is drier than the same spot without it.
        with_ridge = worldgen._rain_shadow(ridge, 8, 6, wind, 12, 12)
        without = worldgen._rain_shadow(flat, 8, 6, wind, 12, 12)
        self.assertGreater(with_ridge, without)
        # Upwind of it is not.
        self.assertEqual(worldgen._rain_shadow(ridge, 2, 6, wind, 12, 12),
                         without)

    def test_dry_land_is_somewhere_in_particular(self):
        """Not scattered noise: the dry belt and the lee of ranges."""
        world = _world("bands", size="small", years=5)
        dry = [(x, y) for y in range(world.height)
               for x in range(world.width)
               if not world.tiles[y][x].is_ocean
               and world.tiles[y][x].rainfall < 0.20]
        if len(dry) < 12:
            self.skipTest("this world happens to be a wet one")
        # Dry tiles should touch each other: a belt, not confetti.
        dryset = set(dry)
        touching = sum(1 for x, y in dry
                       if any((nx, ny) in dryset
                              for nx, ny in world.neighbours(x, y)))
        self.assertGreater(touching, len(dry) * 0.6,
                           "the dry ground is scattered noise")


class TestHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = _world("history", "small", 120)

    def test_nobody_dies_before_birth(self):
        for fig in self.world.figures.values():
            if fig.died is not None:
                self.assertGreaterEqual(fig.died, fig.born, fig.name)

    def test_events_reference_real_things(self):
        for ev in self.world.events:
            self.assertTrue(ev.text)
            self.assertGreaterEqual(ev.year, 0)
            for fid in ev.figures:
                self.assertIn(fid, self.world.figures)
            for sid in ev.sites:
                self.assertIsNotNone(self.world.site(sid), sid)
            for cid in ev.civs:
                self.assertIsNotNone(self.world.civ(cid), cid)

    def test_civs_have_leaders_and_sites(self):
        for civ in self.world.civs:
            if civ.destroyed is not None:
                continue
            self.assertIsNotNone(civ.leader_hf)
            self.assertIn(civ.leader_hf, self.world.figures)

    def test_settlements_are_populated(self):
        for site in self.world.sites:
            if site.is_settlement:
                self.assertGreater(site.population, 0, site.name)

    def test_artifacts_are_well_formed(self):
        from ascii_warriors.data import items as item_data
        from ascii_warriors.data import materials as mat_data

        for art in self.world.artifacts:
            self.assertTrue(item_data.exists(art.item_def))
            self.assertTrue(mat_data.exists(art.material))
            self.assertTrue(art.name)
            self.assertNotIn("{", art.description)

    def test_beast_slaying_is_recorded(self):
        kinds = {e.kind for e in self.world.events}
        self.assertIn("beast_attack", kinds)
        self.assertTrue({"founded_site", "became_leader"} & kinds)

    def test_legends_render(self):
        world = self.world
        self.assertTrue(legends.world_summary(world))
        fig_id = next(iter(world.figures))
        self.assertTrue(legends.figure_lines(world, fig_id))
        self.assertTrue(legends.site_lines(world, world.sites[0].id))
        self.assertTrue(legends.civ_lines(world, world.civs[0].id))
        if world.artifacts:
            self.assertTrue(legends.artifact_lines(world, world.artifacts[0].id))
        self.assertTrue(legends.timeline(world, year_from=1))
        self.assertTrue(legends.figure_lines(world, 10 ** 9))

    def test_legends_search(self):
        site = self.world.sites[0]
        hits = legends.search(self.world, site.name[:6])
        self.assertTrue(hits)
        self.assertEqual(legends.search(self.world, ""), [])


class TestLivingWorld(unittest.TestCase):
    """History that keeps happening after the world is generated."""

    def setUp(self):
        from ascii_warriors.world import livingworld

        self.lw = livingworld
        self.world = _world("living", "pocket", 30)
        self.rng = RNG("seasons")

    def _play(self, years: int):
        """Run the world forward and return the events it recorded."""
        mark = len(self.world.events)
        for year in range(self.world.year, self.world.year + years):
            for _ in range(self.lw.SEASONS_PER_YEAR):
                self.lw.advance(self.world, self.rng, year)
        return self.world.events[mark:]

    def test_a_season_of_play_writes_history(self):
        """Ten years of playing should read like ten years of the world."""
        new = self._play(10)
        self.assertGreater(len(new), 10, "the world barely moved in a decade")
        self.assertLess(len(new), 400, "the world had an apocalypse")

    def test_the_events_are_well_formed(self):
        """Anything the living world records has to survive legends."""
        for ev in self._play(6):
            self.assertTrue(ev.text)
            self.assertGreaterEqual(ev.year, 1)
            for fid in ev.figures:
                self.assertIn(fid, self.world.figures)
            for sid in ev.sites:
                self.assertIsNotNone(self.world.site(sid), ev.text)
            for cid in ev.civs:
                self.assertIsNotNone(self.world.civ(cid), ev.text)

    def test_the_world_moves_on_without_you(self):
        """Beasts, heroes and rulers: somebody has to be doing something."""
        kinds = {e.kind for e in self._play(15)}
        self.assertTrue(
            kinds & {"beast_attack", "hero_rose", "war_declared",
                     "artifact_created", "became_leader", "plague"},
            "fifteen years passed and nothing of note happened: %s" % kinds)

    def test_populations_stay_sane(self):
        """A living world must not depopulate itself in a few decades."""
        self._play(20)
        alive = [s for s in self.world.sites
                 if s.is_settlement and not s.is_ruin]
        self.assertTrue(alive, "every settlement in the world was wiped out")
        for site in alive:
            self.assertGreater(site.population, 0, site.name)

    def test_a_slain_beast_stays_slain(self):
        """The dead do not go on rampaging."""
        from ascii_warriors.world import history as history_mod

        beast = history_mod._spawn_megabeast(self.world, self.rng,
                                             self.world.year)
        self.assertIsNotNone(beast)
        hero = history_mod.new_figure(self.world, self.rng, "dwarf", None,
                                      None, year=self.world.year,
                                      profession="warrior")
        self.lw.slay(self.world, self.world.year, hero, beast, "in the hills")
        self.assertIsNotNone(beast.died)
        self.assertIn(beast.id, hero.kills)
        self._play(5)
        for ev in self.world.events:
            if ev.kind == "beast_attack" and beast.id in ev.figures:
                self.assertLessEqual(ev.year, beast.died)

    def test_the_season_index_changes_once_a_season(self):
        """The hook everything hangs off has to be a clean edge."""
        from ascii_warriors.data.calendar import GameTime, TICKS_PER_DAY

        t = GameTime.at(100, 1, 1, 8, 0)
        marks = []
        for _ in range(8):
            marks.append(self.lw.season_index(t))
            t.advance(TICKS_PER_DAY * 90)
        self.assertEqual(len(set(marks)), len(marks), marks)
        self.assertEqual(marks, sorted(marks))

    def test_news_only_carries_what_people_repeat(self):
        """Nobody walks three hundred miles to report a birth."""
        mark = len(self.world.events)
        self._play(8)
        for ev in self.lw.news_since(self.world, mark, 5):
            self.assertIn(ev.kind, self.lw.TOLD_ABOUT)


class TestLocalMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = _world("local", "small", 60)

    def test_wilderness_map(self):
        land = [
            (x, y) for (x, y) in self.world.land_tiles()
            if self.world.tile(x, y).site_id is None
        ]
        wx, wy = land[len(land) // 2]
        lm, pop = generate_local(self.world, wx, wy, RNG("w"))
        self.assertEqual(lm.width, 64)
        self.assertEqual(lm.height, 48)
        self.assertEqual(pop, [])
        start = lm.random_open(RNG("s"))
        self.assertTrue(lm.walkable(*start))

    def test_every_tile_id_is_known(self):
        land = [(x, y) for (x, y) in self.world.land_tiles()][:1]
        for wx, wy in land:
            lm, _pop = generate_local(self.world, wx, wy, RNG("t"))
            for level in lm.levels.values():
                for tid in set(level):
                    self.assertTrue(tiles.exists(tid), tid)

    def test_site_maps_are_connected(self):
        towns = [
            s for s in self.world.sites
            if s.kind in ("town", "city", "hamlet") and not s.is_ruin
        ]
        self.assertTrue(towns)
        site = towns[0]
        lm, pop = generate_local(self.world, site.wx, site.wy, RNG("c"), site=site)
        self.assertTrue(pop)
        start = lm.edge_entry(RNG("e"), "west")
        reachable = bfs_reachable(start, lm.path_neighbours, max_nodes=200000)
        unreachable = [
            p for p in pop if (p["x"], p["y"], p["z"]) not in reachable
        ]
        self.assertLessEqual(len(unreachable), max(2, len(pop) // 8))

    def test_every_site_kind_builds(self):
        kinds = {}
        for s in self.world.sites:
            kinds.setdefault(s.kind, s)
        for kind, site in kinds.items():
            lm, pop = generate_local(self.world, site.wx, site.wy,
                                     RNG("k-%s" % kind), site=site)
            self.assertIsInstance(lm, LocalMap)
            self.assertIsInstance(pop, list)
            for spec in pop:
                self.assertTrue(lm.in_bounds(spec["x"], spec["y"], spec["z"]),
                                "%s: %s" % (kind, spec))

    def test_central_entry_is_walkable(self):
        towns = [s for s in self.world.sites if s.is_settlement]
        site = towns[0]
        lm, _pop = generate_local(self.world, site.wx, site.wy, RNG("ce"),
                                  site=site)
        x, y, z = lm.central_open(RNG("q"))
        self.assertTrue(lm.walkable(x, y, z))

    def test_round_trip(self):
        wx, wy = self.world.land_tiles()[0]
        lm, _pop = generate_local(self.world, wx, wy, RNG("rt"))
        clone = LocalMap.from_dict(json.loads(json.dumps(lm.to_dict())))
        self.assertEqual(clone.surface, lm.surface)
        for z in lm.levels:
            self.assertEqual(clone.levels[z], lm.levels[z])


class TestGameLoop(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        rng = RNG("loop")
        self.world = generate_world(rng.sub("w"), size="pocket", history_years=30)
        self.game = Game.new_game(
            self.world, {"race": "dwarf", "profession": "warrior",
                         "name": "Urist Testhammer"}, rng)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def test_time_passing_moves_the_world(self):
        """An adventurer's clock drives world history too."""
        from ascii_warriors.data.calendar import TICKS_PER_DAY

        g = self.game
        before = len(g.world.events)
        for _ in range(8):
            g._tick_world(TICKS_PER_DAY * 46)
        self.assertGreater(len(g.world.events), before,
                           "a year on the road and the world stood still")
        self.assertTrue(any("Word reaches you" in m.text
                            for m in g.log.all()),
                        "the player was never told any of it")

    def test_a_quest_somebody_else_finishes_fails(self):
        """The point of a living world: it does not hold the door for you."""
        from ascii_warriors.game.quests import Quest
        from ascii_warriors.world import history as history_mod

        g = self.game
        beast = history_mod._spawn_megabeast(g.world, g.rng, g.time.year)
        self.assertIsNotNone(beast)
        q = Quest("slay_beast", "Slay the beast", "Go and kill it.")
        q.target_hf = beast.id
        g.quests.accept(q)

        g.quests.world_changed(g)
        self.assertEqual(q.state, "active", "it died before anything happened")

        beast.died = g.time.year
        beast.death_cause = "slain by somebody quicker"
        g.quests.world_changed(g)
        self.assertEqual(q.state, "failed")
        self.assertTrue(any("dead already" in m.text for m in g.log.all()))

    def test_an_offered_quest_for_a_dead_target_is_withdrawn(self):
        """Nobody offers you work that is already done."""
        from ascii_warriors.game.quests import Quest
        from ascii_warriors.world import history as history_mod

        g = self.game
        beast = history_mod._spawn_megabeast(g.world, g.rng, g.time.year)
        q = Quest("slay_beast", "Slay the beast", "Go and kill it.")
        q.target_hf = beast.id
        g.quests.offer(q)
        beast.died = g.time.year
        g.quests.world_changed(g)
        self.assertNotIn(q, g.quests.offered)

    def test_rumours_carry_recent_news(self):
        """A tavern that only knows ancient history is a dead world."""
        from ascii_warriors.game import conversation
        from ascii_warriors.world import history as history_mod

        g = self.game
        # Ten years on, so nothing from the generated history counts as news
        # and only the thing that just happened does.
        g.world.year += 10
        history_mod.record(g.world, g.world.year, "site_destroyed",
                           "Newsville was destroyed by a very large frog.")
        lines = conversation.rumor_lines(g, n=3)
        self.assertTrue(any("very large frog" in line for line in lines),
                        lines)

    def test_the_world_clock_survives_a_save(self):
        """Reloading must not replay or skip a season of history."""
        from ascii_warriors.data.calendar import TICKS_PER_DAY

        g = self.game
        g._tick_world(TICKS_PER_DAY * 100)
        clone = Game.from_dict(json.loads(json.dumps(g.to_dict())))
        self.assertEqual(clone._season_mark, g._season_mark)
        before = len(clone.world.events)
        clone._tick_world(10)
        self.assertEqual(len(clone.world.events), before,
                         "loading a game ran a season of history again")

    def test_new_game_state(self):
        g = self.game
        self.assertIsNotNone(g.local)
        self.assertIn(g.player.id, g.creatures)
        self.assertTrue(g.local.walkable(g.player.x, g.player.y, g.player.z))
        self.assertTrue(g.visible)
        self.assertTrue(g.player.inventory.items)
        self.assertIsNotNone(g.player.inventory.weapon())

    def test_turns_advance_time(self):
        g = self.game
        from ascii_warriors.game import actions

        before = g.time.ticks
        for _ in range(120):
            dx, dy = g.rng.dir8()
            cost = actions.move_or_attack(g, dx, dy)
            if cost:
                g.player_acts(cost)
            if g.game_over:
                break
        self.assertGreater(g.time.ticks, before)
        self.assertGreater(g.turn, 0)

    def test_travel_between_tiles(self):
        g = self.game
        start = (g.player.wx, g.player.wy)
        moved = False
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            if g.travel_step(dx, dy):
                moved = True
                break
        self.assertTrue(moved)
        self.assertNotEqual((g.player.wx, g.player.wy), start)
        self.assertTrue(g.local.walkable(g.player.x, g.player.y, g.player.z))

    def test_conversation_uses_real_history(self):
        from ascii_warriors.game import conversation

        g = self.game
        npcs = [
            c for c in g.creatures.values()
            if c.defn.has("CAN_SPEAK") and not c.is_player
        ]
        if not npcs:
            self.skipTest("no speakers at this start location")
        npc = npcs[0]
        for topic in ("greet", "ask_site", "ask_rumors", "ask_directions",
                      "ask_beast", "ask_troubles", "ask_self", "request_quest"):
            frags = conversation.say(g.player, npc, topic, g)
            self.assertTrue(frags, topic)
            for f in frags:
                self.assertNotIn("{", f.text)

    def test_quest_generation(self):
        from ascii_warriors.game import quests

        g = self.game
        npcs = [c for c in g.creatures.values() if c.defn.has("CAN_SPEAK")
                and not c.is_player]
        if not npcs:
            self.skipTest("no speakers at this start location")
        made = 0
        for npc in npcs[:6]:
            q = quests.generate_quest(g.rng, g, npc)
            if q is not None:
                made += 1
                self.assertTrue(q.title)
                self.assertTrue(q.description)
                self.assertTrue(q.detail_lines())
                self.assertGreater(q.reward, 0)
        self.assertGreater(made, 0)

    def test_death_writes_into_legends(self):
        g = self.game
        before = len(g.world.events)
        g.player.body.dead = True
        g.player.body.death_cause = "test"
        g.end_game("test")
        self.assertTrue(g.game_over)
        self.assertGreater(len(g.world.events), before)
        self.assertIsNotNone(g.player.hf_id)

    def test_save_load_round_trip(self):
        from ascii_warriors.game import save as save_mod

        g = self.game
        from ascii_warriors.game import actions

        for _ in range(20):
            dx, dy = g.rng.dir8()
            cost = actions.move_or_attack(g, dx, dy)
            if cost:
                g.player_acts(cost)
        path = save_mod.save_game(g, g.player.name)
        self.assertTrue(path.exists())
        loaded = save_mod.load_game(path)
        self.assertEqual(loaded.player.name, g.player.name)
        self.assertEqual(loaded.turn, g.turn)
        self.assertEqual(loaded.time.ticks, g.time.ticks)
        self.assertEqual((loaded.player.x, loaded.player.y, loaded.player.z),
                         (g.player.x, g.player.y, g.player.z))
        self.assertEqual((loaded.player.wx, loaded.player.wy),
                         (g.player.wx, g.player.wy))
        self.assertEqual(len(loaded.world.events), len(g.world.events))
        self.assertEqual(len(loaded.creatures), len(g.creatures))
        self.assertEqual(loaded.local.tile(5, 5, 0), g.local.tile(5, 5, 0))

        metas = save_mod.list_saves()
        self.assertTrue(metas)
        self.assertTrue(save_mod.describe(metas[0]))
        save_mod.delete_save(metas[0]["path"])
        self.assertFalse(save_mod.list_saves())


class TestResidents(unittest.TestCase):
    """The people in the legends are the people in the town."""

    @classmethod
    def setUpClass(cls):
        cls.world = _world("residents", size="small", years=120)

    def _living(self):
        return [f for f in self.world.figures.values()
                if f.died is None and f.site_id is not None]

    def _inhabited(self):
        """Sites somebody actually lives in, with resident figures."""
        homes = {f.site_id for f in self._living()}
        return [s for s in self.world.sites
                if s.id in homes and not s.is_ruin]

    def _walk_into(self, site):
        from ascii_warriors.game.entity import make_creature

        player = make_creature(RNG("p"), "human", faction="player")
        player.is_player = True
        game = Game(self.world, player, RNG("g%d" % site.id))
        player.wx, player.wy = site.wx, site.wy
        game.enter_world_tile(site.wx, site.wy)
        return game

    def test_the_legends_of_a_town_are_standing_in_it(self):
        """Only a site's ruler and owner were ever placed: 8 of 356."""
        met = figures = 0
        for site in self._inhabited()[:12]:
            game = self._walk_into(site)
            met += sum(1 for c in game.creatures.values() if c.hf_id is not None)
            figures += sum(1 for f in self._living() if f.site_id == site.id)
        self.assertTrue(figures, "no site has resident figures to place")
        self.assertGreater(met, figures // 2,
                           "most of a town's legends are still unmeetable")

    def test_nobody_is_given_two_faces(self):
        """One figure, one body: a person cannot be in the town twice."""
        for site in self._inhabited()[:8]:
            game = self._walk_into(site)
            ids = [c.hf_id for c in game.creatures.values()
                   if c.hf_id is not None]
            self.assertEqual(len(ids), len(set(ids)),
                             "%s has somebody standing in two places" % site.name)

    def test_a_name_never_lands_on_the_wrong_creature(self):
        """Nobody wears a body of the wrong race.

        Two ways to get this wrong. `name_the_locals` could hand a slot to a
        figure that cannot be it; and the builders stamp the ruler's id onto
        whatever they built first, which left a goblin civilization's human
        ruler standing there as a goblin.
        """
        from ascii_warriors.data import creatures as creature_data

        checked = 0
        for site in self._inhabited()[:12]:
            game = self._walk_into(site)
            for c in game.creatures.values():
                if c.hf_id is None:
                    continue
                fig = self.world.figures.get(c.hf_id)
                self.assertIsNotNone(fig)
                defn = creature_data.get(c.def_id)
                if "monster" in fig.flags:
                    # A named megabeast in its own lair. `new_figure` gives
                    # every figure a `race` and a monster's is the "human" it
                    # was made with, so `creature_id` is what it actually is --
                    # which is the field the lair and the quest both use.
                    self.assertEqual(c.def_id, fig.creature_id,
                                     "%s is drawn as a %s" % (fig.name, c.def_id))
                    checked += 1
                    continue
                # A creature with no civ of its own -- guard, merchant, bandit
                # -- is a job rather than a race, and contradicts nobody.
                if defn.civ:
                    self.assertEqual(defn.civ, fig.race,
                                     "%s the %s is drawn as a %s"
                                     % (fig.name, fig.race, c.def_id))
                else:
                    self.assertTrue(defn.has("CIVILIZED"),
                                    "%s is a %s" % (fig.name, c.def_id))
                checked += 1
        self.assertTrue(checked, "no figures were placed at all")

    def test_a_job_slot_only_takes_the_towns_own_people(self):
        """`hammerdwarf` and `elf_archer` carry no `civ` of their own, so a
        rule of job-slots-are-open-to-anybody put three goblins' names on
        three dwarven hammerers -- a dwarf fortress had eleven goblins on its
        rolls, from whatever changed hands there."""
        from ascii_warriors.data import creatures as creature_data
        from ascii_warriors.world import residents

        dwarf_site = next((s for s in self._inhabited() if s.race == "dwarf"),
                          None)
        if dwarf_site is None:
            self.skipTest("no dwarven site in this world")
        goblin = next((f for f in self._living() if f.race == "goblin"), None)
        dwarf = next((f for f in self._living() if f.race == "dwarf"), None)
        self.assertIsNotNone(goblin)
        self.assertIsNotNone(dwarf)

        hammerer = creature_data.get("hammerdwarf")
        self.assertIsNone(hammerer.civ, "the premise of this test has changed")
        self.assertFalse(residents.could_be(hammerer, goblin, dwarf_site))
        self.assertTrue(residents.could_be(hammerer, dwarf, dwarf_site))
        # And nothing that cannot hold a name gets one.
        self.assertFalse(residents.could_be(creature_data.get("troll"),
                                            goblin, dwarf_site))
        self.assertFalse(residents.could_be(creature_data.get("zombie"),
                                            dwarf, dwarf_site))

    def test_the_ruler_keeps_their_own_body(self):
        """The one figure that was already placed must not be displaced."""
        from ascii_warriors.world import residents

        for site in self._inhabited():
            if site.ruler_hf is None:
                continue
            fig = self.world.figures.get(site.ruler_hf)
            if fig is None or fig.died is not None:
                continue
            game = self._walk_into(site)
            here = [c for c in game.creatures.values()
                    if c.hf_id == site.ruler_hf]
            self.assertEqual(len(here), 1,
                             "%s lost its ruler" % site.name)
            return
        self.skipTest("no site in this world has a living ruler")

    def test_the_notable_are_placed_before_the_unremarkable(self):
        """There are more figures than slots, so the order is the whole game."""
        from ascii_warriors.world import residents

        site = max(self._inhabited(),
                   key=lambda s: sum(1 for f in self._living()
                                     if f.site_id == s.id))
        ranked = residents.residents(self.world, site)
        scores = [residents.notability(self.world, f) for f in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_a_retired_adventurer_can_be_met(self):
        """`renown.retire` has promised this in its docstring all along."""
        from ascii_warriors.game import renown
        from ascii_warriors.game.entity import make_creature

        site = next(s for s in self._inhabited() if s.is_settlement)
        player = make_creature(RNG("rhona"), site.race or "human",
                               faction="player")
        player.is_player = True
        game = Game(self.world, player, RNG("retire"))
        player.name = "Rhona the Bold"
        player.wx, player.wy = site.wx, site.wy
        game.enter_world_tile(site.wx, site.wy)
        renown.retire(game)
        hero = self.world.figures.get(player.hf_id)
        self.assertIsNotNone(hero)
        self.assertIn("retired", hero.flags)

        after = self._walk_into(site)
        found = [c for c in after.creatures.values() if c.hf_id == hero.id]
        self.assertTrue(found, "the next adventurer cannot find them")
        self.assertEqual(found[0].name, "Rhona the Bold")

    def test_they_will_tell_you_what_they_did(self):
        """`ask_self` gave name, trade and temperament and never a deed,
        though `ask_beast` two branches below quoted a monster's history."""
        from ascii_warriors.game import conversation
        from ascii_warriors.world import history as history_mod

        for site in self._inhabited()[:12]:
            game = self._walk_into(site)
            for c in game.creatures.values():
                if c.hf_id is None:
                    continue
                deeds = [e for e in history_mod.events_about(self.world, c.hf_id)
                         if e.kind != "birth"]
                if not deeds:
                    continue
                said = " ".join(
                    f.text for f in
                    conversation.say(game.player, c, "ask_self", game))
                self.assertTrue(
                    any(e.text in said for e in deeds),
                    "%s will not say what they are known for" % c.name)
                return
        self.skipTest("no placed figure in this world has a deed to tell")

    def test_asking_about_one_figure_is_about_that_figure(self):
        """`rumor_lines` took an `hf_id` and ignored it entirely."""
        from ascii_warriors.game import conversation
        from ascii_warriors.world import history as history_mod

        site = self._inhabited()[0]
        game = self._walk_into(site)
        who = next((f for f in self._living()
                    if [e for e in history_mod.events_about(self.world, f.id)
                        if e.kind != "birth"]), None)
        self.assertIsNotNone(who)
        deeds = [e.text for e in history_mod.events_about(self.world, who.id)
                 if e.kind != "birth"]
        lines = conversation.rumor_lines(game, hf_id=who.id, n=3)
        self.assertTrue(lines)
        for line in lines:
            self.assertTrue(any(d in line for d in deeds),
                            "asked about one person, told about another: %r"
                            % line)


class TestPersonalityReadsLikeEnglish(unittest.TestCase):
    """Every personality line in the game was ungrammatical.

    The phrases were third-person singular ("is a coward", "prefers
    solitude"), the one thing that reads them prefixes "They ", and where the
    phrase began "is " the code deleted it -- so the character sheet said
    "They has no vanity." and "They a coward."
    """

    def _lines(self, n=40):
        from ascii_warriors.game.entity import make_creature

        out = []
        for i in range(n):
            c = make_creature(RNG("p%d" % i), "human")
            out.extend(c.personality.describe())
        return out

    def test_no_singular_verb_follows_they(self):
        bad = ("They is ", "They has ", "They does ")
        for line in self._lines():
            for prefix in bad:
                self.assertFalse(line.startswith(prefix), line)

    def test_every_sentence_has_a_verb(self):
        """"They a coward." and "They deeply intolerant." were what deleting
        the copula produced."""
        for line in self._lines():
            self.assertTrue(line.startswith("They "), line)
            rest = line[5:].rstrip(".")
            self.assertTrue(rest, line)
            self.assertNotIn(rest.split(" ")[0], ("a", "an", "the"),
                             "no verb in %r" % line)

    def test_no_phrase_is_conjugated_for_a_singular_subject(self):
        """The precise shape of the bug: "prefers", "has", "nurses". No verb
        in its base form ends in s, so the first word of a phrase must not."""
        from ascii_warriors.data.descriptors import _FACET_PHRASES

        for facet, pair in _FACET_PHRASES.items():
            for phrase in pair:
                first = phrase.split(" ")[0]
                self.assertFalse(first.endswith("s"),
                                 "%s: %r is third-person singular"
                                 % (facet, phrase))

    def test_every_phrase_in_the_table_fits_both_persons(self):
        from ascii_warriors.data.descriptors import _FACET_PHRASES
        from ascii_warriors.game.conversation import _in_first_person

        for facet, (high, low) in _FACET_PHRASES.items():
            for phrase in (high, low):
                third = "They %s." % phrase
                first = _in_first_person(third)
                self.assertTrue(first.startswith("I "), (facet, first))
                self.assertNotIn("I are ", first, facet)
                self.assertNotIn("themselves", first, facet)
                self.assertNotIn("their ", first, facet)

    def test_a_person_speaks_of_themselves_in_the_first_person(self):
        from ascii_warriors.game.conversation import _in_first_person

        self.assertEqual(_in_first_person("They are a coward."),
                         "I am a coward.")
        self.assertEqual(_in_first_person("They have no vanity."),
                         "I have no vanity.")
        self.assertEqual(_in_first_person("They look out only for themselves."),
                         "I look out only for myself.")
        self.assertEqual(_in_first_person("They speak their mind forcefully."),
                         "I speak my mind forcefully.")





class TestGods(unittest.TestCase):
    """Every temple in the game was furnished and had nothing to worship."""

    @classmethod
    def setUpClass(cls):
        cls.world = _world("gods", size="small", years=80)

    def test_every_people_keeps_a_pantheon(self):
        from ascii_warriors.world import religion

        self.assertTrue(self.world.gods)
        for civ in self.world.civs:
            gods = religion.gods_of(self.world, civ.id)
            self.assertGreaterEqual(len(gods), religion.MIN_GODS, civ.name)
            self.assertLessEqual(len(gods), religion.MAX_GODS, civ.name)

    def test_the_gods_have_names_of_their_own(self):
        """A fresh `rng.sub("god")` per god is the same sub-RNG every time,
        which named every god of a people the same thing."""
        names = [g.name for g in self.world.gods]
        self.assertEqual(len(names), len(set(names)))
        for g in self.world.gods:
            self.assertTrue(g.name)
            self.assertTrue(g.spheres)
            self.assertIn(g.spheres[0], [s for s, _e in
                                         __import__(
                                             "ascii_warriors.world.religion",
                                             fromlist=["religion"]).SPHERES])

    def test_a_god_is_the_same_god_every_time_you_ask(self):
        """Worship is derived rather than stored, so it has to be stable."""
        from ascii_warriors.world import religion

        for fig in list(self.world.figures.values())[:40]:
            first = religion.deity_of(self.world, fig)
            self.assertIs(first, religion.deity_of(self.world, fig))

    def test_a_trade_looks_to_its_own_sphere(self):
        from ascii_warriors.world import religion

        matched = 0
        for fig in self.world.figures.values():
            want = religion.SPHERE_FOR_PROFESSION.get(fig.profession)
            god = religion.deity_of(self.world, fig)
            if god is None or want is None:
                continue
            if want in god.spheres:
                matched += 1
            else:
                # Only acceptable when their people keep no god of it.
                pantheon = religion.gods_of(self.world, fig.civ_id)
                self.assertFalse(
                    any(want in g.spheres for g in pantheon),
                    "%s the %s ignores their own god of %s"
                    % (fig.name, fig.profession, want))
        self.assertGreater(matched, 0, "nobody looks to their own trade")

    def test_gods_survive_a_world_save(self):
        from ascii_warriors.world import religion
        from ascii_warriors.world.worldgen import World

        back = World.from_dict(self.world.to_dict())
        self.assertEqual(len(back.gods), len(self.world.gods))
        self.assertEqual([g.id for g in back.gods],
                         [g.id for g in self.world.gods])
        self.assertEqual([g.summary() for g in back.gods],
                         [g.summary() for g in self.world.gods])
        # And the derived worship gives the same answers on the far side.
        for fig in list(self.world.figures.values())[:20]:
            was = religion.deity_of(self.world, fig)
            now = religion.deity_of(back, back.figures[fig.id])
            self.assertEqual(was.id if was else None, now.id if now else None)

    def test_a_world_saved_before_gods_still_loads(self):
        """Five counters rather than six, and no `gods` key at all."""
        from ascii_warriors.world.worldgen import World

        blob = self.world.to_dict()
        blob.pop("gods", None)
        blob["counters"] = blob["counters"][:5]
        back = World.from_dict(blob)
        self.assertEqual(back.gods, [])
        self.assertGreater(back.next_id("deity"), 0)

    def test_the_legends_screen_has_a_page_for_a_god(self):
        from ascii_warriors.world import legends, religion

        god = self.world.gods[0]
        lines = legends.deity_lines(self.world, god.id)
        text = " ".join(f.text for f in lines)
        self.assertIn(god.name, text)
        self.assertIn(god.spheres[0], text)
        # And a figure's page says who they hold to.
        fig = next(f for f in self.world.figures.values()
                   if religion.deity_of(self.world, f) is not None)
        page = " ".join(f.text for f in legends.figure_lines(self.world, fig.id))
        self.assertIn(religion.deity_of(self.world, fig).name, page)


class TestPrayer(unittest.TestCase):
    """An altar you can do something with."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        self.world = _world("prayer", size="pocket", years=30)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _at_an_altar(self):
        """A player standing on an altar in the first settlement there is.

        Whether a generated town happens to have laid one is not this test's
        business, and skipping when it has not is how two tests went quiet:
        any change to the map generator moves the buildings and the coverage
        vanishes without anything going red. If there is no altar, put one
        down and stand on it.
        """
        from ascii_warriors.game.entity import make_creature

        player = make_creature(RNG("p"), "human", faction="player")
        player.is_player = True
        game = Game(self.world, player, RNG("pray"))
        site = next(s for s in self.world.sites
                    if s.is_settlement and not s.is_ruin)
        player.wx, player.wy = site.wx, site.wy
        game.enter_world_tile(site.wx, site.wy)
        lm = game.local
        for z in lm.levels:
            for y in range(lm.height):
                for x in range(lm.width):
                    if lm.tile(x, y, z) == "altar":
                        player.x, player.y, player.z = x, y, z
                        return game, player
        for z in sorted(lm.levels, reverse=True):
            for y in range(1, lm.height - 1):
                for x in range(1, lm.width - 1):
                    if lm.walkable(x, y, z) and not lm.is_outside(x, y, z):
                        lm.set_tile(x, y, z, "altar")
                        player.x, player.y, player.z = x, y, z
                        return game, player
        return game, None

    def test_praying_at_an_altar_settles_you(self):
        from ascii_warriors.game import actions

        game, player = self._at_an_altar()
        if player is None:
            self.skipTest("no altar in this world's settlements")
        player.needs.prayer = 200000
        before = len(game.log.recent(50))
        cost = actions.pray_here(game)
        self.assertEqual(cost, actions.PRAY_TURNS)
        self.assertEqual(player.needs.prayer, 0)
        said = " ".join(getattr(m, "text", str(m))
                        for m in game.log.recent(50)[before:])
        self.assertIn("thanks", said.lower())

    def test_praying_anywhere_else_does_nothing(self):
        from ascii_warriors.game import actions

        game, player = self._at_an_altar()
        if player is None:
            self.skipTest("no altar in this world's settlements")
        # Step off the altar.
        player.x += 1 if game.local.tile(player.x + 1, player.y,
                                         player.z) != "altar" else -1
        player.needs.prayer = 200000
        cost = actions.pray_here(game)
        self.assertEqual(cost, actions.FREE)
        self.assertEqual(player.needs.prayer, 200000)

    def test_the_want_grows_and_a_save_keeps_it(self):
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.needs import PRAYER_WANTED

        c = make_creature(RNG("q"), "dwarf")
        self.assertEqual(c.needs.prayer, 0)
        # Fed and watered the whole way, so the only thing accumulating is the
        # want of a quiet place. Ticking a week in one go kills them of thirst
        # and proves nothing about prayer.
        step = 600
        for _ in range((PRAYER_WANTED // step) + 2):
            c.needs.tick(step, c, None)
            c.needs.hunger = 0
            c.needs.thirst = 0
            c.needs.drowsy = 0
        self.assertGreater(c.needs.prayer, PRAYER_WANTED)
        self.assertFalse(c.body.dead, "somebody died of wanting a temple")
        from ascii_warriors.game.needs import Needs

        back = Needs.from_dict(c.needs.to_dict())
        self.assertEqual(back.prayer, c.needs.prayer)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestTheBeastAndItsLair(unittest.TestCase):
    """A named beast has somewhere to be, and the quest knows where.

    Found by taking the README at its word -- "Every quest points at something
    that exists" -- and going to look. Every target did exist. None of them was
    there. A megabeast was a name and a body count: `_spawn_megabeast` gave it
    no home, it raided a random settlement each year from nowhere in
    particular, and `_quest_slay_beast` therefore had nothing to point at and
    named `rng.choice(lairs)` instead. Meanwhile `build_lair` put a beast of a
    random species, with no `hf_id`, in every lair. Three halves, none of them
    joined, and a whole quest kind that nobody could finish.
    """

    def _world(self, seed="lair", years=150):
        return generate_world(RNG(seed).sub("w"), size="small",
                              history_years=years)

    def _beasts(self, world):
        return [f for f in world.figures.values()
                if "monster" in f.flags and f.alive(world.year)]

    def test_a_living_beast_lairs_somewhere(self):
        """It has to be findable, which means it has to be somewhere."""
        world = self._world()
        beasts = self._beasts(world)
        self.assertTrue(beasts, "no megabeast survived the history")
        homeless = [f.display_name for f in beasts if f.site_id is None]
        self.assertEqual(homeless, [], "beasts with nowhere to be")
        for f in beasts:
            site = next((s for s in world.sites if s.id == f.site_id), None)
            self.assertIsNotNone(site, "%s lairs nowhere real" % f.display_name)
            self.assertIn(site.kind, ("lair", "cave"))

    def test_no_two_beasts_share_a_cave(self):
        """Or the quest naming the place still sends you at the wrong one."""
        world = self._world("shared")
        homes = [f.site_id for f in self._beasts(world)]
        self.assertEqual(len(homes), len(set(homes)), "two beasts, one cave")

    def test_the_lair_holds_the_beast_the_histories_name(self):
        """Right species, right name, and the id that ties it to the story."""
        world = self._world("occupied")
        beasts = self._beasts(world)
        self.assertTrue(beasts)
        checked = 0
        for fig in beasts:
            site = next((s for s in world.sites if s.id == fig.site_id), None)
            if site is None:
                continue
            _lm, pop = generate_local(world, site.wx, site.wy,
                                      RNG("pop%d" % fig.id), site=site)
            named = [p for p in pop if p.get("hf_id") == fig.id]
            self.assertEqual(len(named), 1,
                             "%s is not in its own lair" % fig.display_name)
            self.assertEqual(named[0]["def_id"], fig.creature_id)
            checked += 1
        self.assertGreater(checked, 0, "no lair was built at all")

    def test_a_cave_with_nobody_in_it_still_builds(self):
        """The fallback: most caves have no megabeast, and still need filling."""
        world = self._world("empty")
        taken = {f.site_id for f in self._beasts(world)}
        spare = [s for s in world.sites
                 if s.kind in ("lair", "cave") and s.id not in taken
                 and not s.is_ruin]
        self.assertTrue(spare, "every cave in the world has a beast in it")
        site = spare[0]
        _lm, pop = generate_local(world, site.wx, site.wy, RNG("spare"),
                                  site=site)
        self.assertTrue(pop, "an unoccupied cave came out empty")


class TestTheNecromancersTower(unittest.TestCase):
    """A necromancer with somewhere to be, and it is the place the story says.

    The histories wrote both halves and joined neither. "%s learned the secrets
    of life and death and fled into the wilderness" fired at five percent a
    year, so a world got six to eleven of them; towers are one weight in
    seventeen at worldgen and are downgraded to ruins unless the tile is evil,
    so a world got none or one. Measured over three worlds: twenty-six named
    necromancers and one tower between them, and every necromancer's
    ``site_id`` still pointed at the town it is on record as having fled.

    That was not a cosmetic gap. The help screen says the secret of raising the
    dead is a slab in a necromancer's tower, and a slab rides in on a creature
    whose profession is ``necromancer`` -- which only ``build_tower`` creates.
    Two worlds in three had no tower, so the whole night half of the game was
    written, tested at the machinery, and unreachable from a new world.
    """

    SEEDS = ("night1", "night2", "night3", "night4")

    @classmethod
    def setUpClass(cls):
        cls.worlds = {s: _world(s, size="pocket", years=80) for s in cls.SEEDS}

    @staticmethod
    def _necromancers(world):
        return [f for f in world.figures.values()
                if "necromancer" in f.flags and f.alive(world.year)]

    @staticmethod
    def _towers(world):
        return [s for s in world.sites if s.kind == "tower" and not s.is_ruin]

    def test_every_necromancer_has_a_tower(self):
        """It fled into the wilderness, so the wilderness must have somewhere."""
        checked = 0
        for seed, world in self.worlds.items():
            necros = self._necromancers(world)
            for fig in necros:
                site = world.site(fig.site_id) if fig.site_id else None
                self.assertIsNotNone(
                    site, "%s: %s lives nowhere" % (seed, fig.display_name))
                self.assertEqual(
                    site.kind, "tower",
                    "%s: %s lives in a %s" % (seed, fig.display_name, site.kind))
                checked += 1
        self.assertGreater(checked, 4, "hardly any necromancers arose")

    def test_no_two_necromancers_hold_the_same_tower(self):
        """`build_tower` puts one owner on the map, so two owners lose one."""
        for seed, world in self.worlds.items():
            necros = self._necromancers(world)
            if not necros:
                continue
            owners = [s.owner_hf for s in self._towers(world)
                      if s.owner_hf is not None]
            self.assertEqual(len(owners), len(set(owners)),
                             "%s: a tower changed hands and kept both" % seed)
            self.assertEqual(
                len(set(owners)), len(necros),
                "%s: %d necromancers between %d towers"
                % (seed, len(necros), len(set(owners))))

    def test_the_figure_and_the_site_agree(self):
        """Disagreeing quietly is what made this invisible for so long."""
        checked = 0
        for seed, world in self.worlds.items():
            for site in self._towers(world):
                if site.owner_hf is None:
                    continue
                fig = world.figures.get(site.owner_hf)
                self.assertIsNotNone(fig, "%s: %s is held by nobody real"
                                     % (seed, site.name))
                self.assertEqual(fig.site_id, site.id,
                                 "%s: %s holds %s and lives elsewhere"
                                 % (seed, fig.display_name, site.name))
                checked += 1
        self.assertGreater(checked, 4, "no tower in any world had an owner")

    def test_the_tower_stands_where_the_map_says(self):
        """A site the world tile does not know about is one you cannot reach.

        A tower raised by the histories has to be stamped onto its world tile
        the way the scattered ones are, or it is a name in the legends with
        nowhere on the map to travel to.
        """
        checked = 0
        for seed, world in self.worlds.items():
            for site in self._towers(world):
                tile = world.tile(site.wx, site.wy)
                self.assertEqual(tile.site_id, site.id,
                                 "%s: %s is not on its own tile"
                                 % (seed, site.name))
                self.assertEqual(tile.feature, "tower")
                self.assertFalse(tile.is_ocean, "%s: a tower at sea" % seed)
                checked += 1
        self.assertGreater(checked, 4,
                           "worlds still have barely any towers in them")

    def test_the_legends_name_who_holds_it(self):
        """So you can find out before you climb five floors to find out."""
        named = 0
        for seed, world in self.worlds.items():
            for site in self._towers(world):
                if site.owner_hf is None:
                    continue
                fig = world.figures[site.owner_hf]
                text = "\n".join(f.text for f in legends.site_lines(world, site.id))
                self.assertIn("Held by %s." % fig.display_name, text,
                              "%s: %s says nothing about who is in it"
                              % (seed, site.name))
                named += 1
        self.assertGreater(named, 4, "no tower in any world had an owner")

    def test_the_necromancer_is_home_when_you_arrive(self):
        """The half that was missing everywhere else too."""
        checked = 0
        for seed, world in self.worlds.items():
            for site in self._towers(world):
                if site.owner_hf is None:
                    continue
                _lm, pop = generate_local(world, site.wx, site.wy,
                                          RNG("tower%d" % site.id), site=site)
                mine = [p for p in pop if p.get("hf_id") == site.owner_hf]
                self.assertEqual(len(mine), 1,
                                 "%s: %s is not in %s"
                                 % (seed, world.figures[site.owner_hf].name,
                                    site.name))
                self.assertEqual(mine[0]["def_id"], "necromancer")
                self.assertTrue(
                    any(p.get("profession") == "undead" for p in pop),
                    "%s: %s has no dead in it" % (seed, site.name))
                checked += 1
        self.assertGreater(checked, 4, "no owned tower was built")

    def test_a_tower_whose_necromancer_is_dead_holds_only_its_dead(self):
        """You killed him. The legends recorded it. He does not come back."""
        world = self.worlds["night1"]
        site = next(s for s in self._towers(world) if s.owner_hf is not None)
        fig = world.figures[site.owner_hf]
        before = fig.died
        fig.died = world.year - 30
        try:
            _lm, pop = generate_local(world, site.wx, site.wy, RNG("dead"),
                                      site=site)
        finally:
            fig.died = before
        self.assertFalse([p for p in pop if p.get("def_id") == "necromancer"],
                         "a necromancer the world has buried was standing there")
        self.assertTrue([p for p in pop if p.get("profession") == "undead"],
                        "his dead left with him")

    def test_an_unclaimed_tower_still_has_its_necromancer(self):
        """Nameless, but a tower with nobody in it is not a tower."""
        world = self.worlds["night1"]
        site = next(s for s in self._towers(world) if s.owner_hf is not None)
        before = site.owner_hf
        site.owner_hf = None
        try:
            _lm, pop = generate_local(world, site.wx, site.wy, RNG("free"),
                                      site=site)
        finally:
            site.owner_hf = before
        nec = [p for p in pop if p.get("def_id") == "necromancer"]
        self.assertEqual(len(nec), 1, "an unclaimed tower came out empty")
        self.assertIsNone(nec[0].get("hf_id"))

    def test_the_tower_survives_a_save(self):
        """Who holds what is world state, and worlds get written down."""
        world = self.worlds["night2"]
        towers = [s for s in self._towers(world) if s.owner_hf is not None]
        self.assertTrue(towers)
        again = World.from_dict(json.loads(json.dumps(world.to_dict())))
        for site in towers:
            back = again.site(site.id)
            self.assertIsNotNone(back)
            self.assertEqual(back.owner_hf, site.owner_hf)
            self.assertEqual(again.figures[site.owner_hf].site_id, site.id)
            self.assertEqual(again.tile(site.wx, site.wy).site_id, site.id)
