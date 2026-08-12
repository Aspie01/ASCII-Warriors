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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
