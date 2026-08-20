"""Tests for medicine, trade, companions, weather and light sources."""

from __future__ import annotations

import collections
import json
import os
import tempfile
import unittest

from ascii_warriors.data.calendar import TICKS_PER_HOUR
from ascii_warriors.engine.rng import RNG
from ascii_warriors.game import actions, companions, medical, trade
from ascii_warriors.game.entity import make_creature
from ascii_warriors.game.item import Item, starting_kit
from ascii_warriors.game.state import Game
from ascii_warriors.game.weather import KINDS, Weather, starting_weather
from ascii_warriors.engine.scheduler import ACTION_COST
from ascii_warriors.world.worldgen import generate_world


class GameFixture(unittest.TestCase):
    """A small started game in a temporary save directory."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        rng = RNG("systems")
        self.world = generate_world(rng.sub("w"), size="pocket", history_years=25)
        self.game = Game.new_game(
            self.world, {"race": "human", "profession": "warrior"}, rng)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def speakers(self):
        return [
            c for c in self.game.creatures.values()
            if c.defn.has("CAN_SPEAK") and not c.is_player
        ]


class TestMedical(unittest.TestCase):
    def _wounded(self, seed="med"):
        rng = RNG(seed)
        c = make_creature(rng, "human", faction="player")
        c.is_player = True
        c.body.apply_damage("left_leg_upper", "edge", 90000, 20000, 5000, rng)
        return c, rng

    def test_treatable_finds_bleeding(self):
        c, _rng = self._wounded()
        hurt = medical.treatable(c)
        self.assertTrue(hurt)
        self.assertTrue(any("bandage" in opts for _part, opts in hurt))

    def test_bandage_stops_bleeding_and_is_consumed(self):
        c, rng = self._wounded()
        c.skills.set_level("wound_dressing", 12)
        c.inventory.add(Item("bandage", "pig_tail_cloth", count=2))
        part = next(p for p, o in medical.treatable(c) if "bandage" in o)
        before = medical.part_bleeding(part)
        self.assertGreater(before, 0)
        msgs = medical.treat(c, c, part.id, "bandage", rng=rng)
        self.assertTrue(msgs)
        self.assertLess(medical.part_bleeding(part), before)
        self.assertEqual(c.inventory.count_of("bandage"), 1)

    def test_bandage_requires_supplies(self):
        c, rng = self._wounded()
        ok, why = medical.can_treat(c, "bandage")
        self.assertFalse(ok)
        self.assertIn("bandage", why)
        msgs = medical.treat(c, c, "left_leg_upper", "bandage", rng=rng)
        self.assertTrue(msgs)

    def test_splint_sets_a_broken_bone(self):
        rng = RNG("splint")
        c = make_creature(rng, "human", faction="player")
        c.skills.set_level("bone_setting", 14)
        part = c.body.part("left_arm_lower")
        part.broken = True
        c.inventory.add(Item("splint", "oak"))
        medical.treat(c, c, part.id, "splint", rng=rng)
        self.assertFalse(part.broken)
        self.assertEqual(c.inventory.count_of("splint"), 0)

    def test_diagnose_reports_bleeding_and_trains(self):
        c, _rng = self._wounded()
        c.skills.set_level("diagnose", 5)
        before = c.skills.exp("diagnose")
        lines = medical.diagnose(c, c)
        self.assertTrue(lines)
        self.assertTrue(any("bleed" in f.text.lower() for f in lines))
        self.assertGreater(c.skills.exp("diagnose"), before)

    def test_diagnose_on_healthy_creature(self):
        rng = RNG("healthy")
        c = make_creature(rng, "human", faction="player")
        lines = medical.diagnose(c, c)
        self.assertTrue(any("good health" in f.text for f in lines))

    def test_auto_treat_picks_the_worst_problem(self):
        c, rng = self._wounded()
        c.inventory.add(Item("bandage", "pig_tail_cloth", count=3))
        c.skills.set_level("wound_dressing", 10)
        before = c.body.bleeding_rate()
        medical.auto_treat(c, rng=rng)
        self.assertLess(c.body.bleeding_rate(), before)

    def test_bandaging_saves_a_life(self):
        """A creature that would bleed out survives once bandaged."""
        rng = RNG("save")
        doomed = make_creature(rng, "human")
        doomed.body.apply_damage("upper_body", "edge", 120000, 20000, 6000, rng)
        patched = make_creature(rng, "human")
        patched.body = doomed.body.__class__.from_dict(
            json.loads(json.dumps(doomed.body.to_dict())))
        patched.skills.set_level("wound_dressing", 18)
        patched.inventory.add(Item("bandage", "pig_tail_cloth", count=6))
        for part, options in medical.treatable(patched):
            if "bandage" in options:
                medical.treat(patched, patched, part.id, "bandage", rng=rng)
        for _ in range(400):
            doomed.body.tick(rng, 1, 1.0, 1.0)
            patched.body.tick(rng, 1, 1.0, 1.0)
        self.assertTrue(doomed.body.dead)
        self.assertFalse(patched.body.dead)


class TestWeather(unittest.TestCase):
    def test_kinds_are_well_formed(self):
        for kind in KINDS.values():
            self.assertTrue(kind.description)
            self.assertTrue(0.0 < kind.light <= 1.0)
            self.assertTrue(0.0 < kind.sight <= 1.0)

    def test_transitions_stay_valid(self):
        rng = RNG("weather")
        w = Weather("clear", 0)
        for biome in ("desert", "taiga", "jungle", "mountain", "grassland"):
            for temp in (-5.0, 40.0, 95.0):
                for _ in range(40):
                    w.tick(10 ** 6, rng, biome, temp, "Winter")
                    self.assertIn(w.kind, KINDS)

    def test_no_snow_in_the_desert_heat(self):
        rng = RNG("hot")
        w = Weather("clear", 0)
        for _ in range(300):
            w.tick(10 ** 6, rng, "desert", 95.0, "Summer")
            self.assertNotIn(w.kind, ("snow", "blizzard"))

    def test_no_rain_when_freezing(self):
        rng = RNG("cold")
        w = Weather("cloudy", 0)
        for _ in range(300):
            w.tick(10 ** 6, rng, "tundra", 5.0, "Winter")
            self.assertNotIn(w.kind, ("rain", "storm"))

    def test_modifiers_and_round_trip(self):
        w = starting_weather(RNG("s"), "taiga", 15.0, "Winter")
        self.assertTrue(0.0 < w.light_modifier() <= 1.0)
        self.assertTrue(0.0 < w.sight_modifier() <= 1.0)
        self.assertTrue(w.describe())
        clone = Weather.from_dict(json.loads(json.dumps(w.to_dict())))
        self.assertEqual(clone.kind, w.kind)
        self.assertEqual(clone.ticks_left, w.ticks_left)


class TestLightSources(GameFixture):
    def test_starting_torch_has_fuel_but_is_not_lit(self):
        torches = [i for i in self.game.player.inventory.items if i.is_light]
        self.assertTrue(torches)
        self.assertGreater(torches[0].charges, 0)
        self.assertFalse(torches[0].flags.get("lit"))

    def test_lighting_and_dousing(self):
        game = self.game
        torch = next(i for i in game.player.inventory.items if i.is_light)
        self.assertEqual(actions.light_source(game, torch), actions.NORMAL)
        self.assertTrue(torch.flags.get("lit"))
        self.assertGreater(game.player_light(), 0)
        actions.light_source(game, torch)
        self.assertFalse(torch.flags.get("lit"))
        self.assertEqual(game.player_light(), 0)

    def test_only_lit_torches_burn_down(self):
        game = self.game
        torch = next(i for i in game.player.inventory.items if i.is_light)
        charges = torch.charges
        game._tick_world(500)
        self.assertEqual(torch.charges, charges)
        actions.light_source(game, torch)
        game._tick_world(500)
        self.assertLess(torch.charges, charges)

    def test_a_lit_torch_lights_the_dark(self):
        game = self.game
        # Somewhere underground, where there is no daylight at all.
        dark = (game.player.x, game.player.y, game.local.zmin)
        before = game.light_at(*dark)
        torch = next(i for i in game.player.inventory.items if i.is_light)
        actions.light_source(game, torch)
        self.assertGreater(game.light_at(*dark), before)

    def test_a_spent_torch_burns_out_and_is_gone(self):
        game = self.game
        torch = next(i for i in game.player.inventory.items if i.is_light)
        torch.count = 1
        torch.charges = 10
        actions.light_source(game, torch)
        game._tick_world(50)
        self.assertNotIn(torch, game.player.inventory.items)


class TestTrade(GameFixture):
    def _merchant(self):
        rng = self.game.rng
        npc = make_creature(rng, "merchant", faction="town")
        from ascii_warriors.game.ai import AIState

        npc.ai = AIState("idle", role="merchant")
        trade.stock_merchant(npc, rng)
        return npc

    def test_traders_are_recognised(self):
        npc = self._merchant()
        self.assertTrue(trade.is_trader(npc))
        self.assertEqual(trade.trader_kind(npc), "merchant")
        hostile = make_creature(self.game.rng, "goblin", faction="hostile")
        self.assertFalse(trade.is_trader(hostile))

    def test_stock_is_generated_once(self):
        npc = self._merchant()
        count = len(npc.inventory.items)
        self.assertGreater(count, 3)
        trade.stock_merchant(npc, self.game.rng)
        self.assertEqual(len(npc.inventory.items), count)
        self.assertGreater(npc.inventory.coins(), 0)

    def test_merchants_charge_more_than_they_pay(self):
        npc = self._merchant()
        item = next(i for i in trade.for_sale(npc) if trade.wants(npc, i))
        buy = trade.price_to_buy(item, npc, self.game.player)
        sell = trade.price_to_sell(item, npc, self.game.player)
        self.assertGreater(buy, sell)
        self.assertGreaterEqual(sell, 0)

    def test_skills_improve_your_prices(self):
        npc = self._merchant()
        item = trade.for_sale(npc)[0]
        player = self.game.player
        plain = trade.price_to_buy(item, npc, player)
        player.skills.set_level("appraisal", 15)
        player.skills.set_level("negotiation", 15)
        skilled = trade.price_to_buy(item, npc, player)
        self.assertLess(skilled, plain)

    def test_buying_moves_goods_and_coin(self):
        game = self.game
        npc = self._merchant()
        game.player.inventory.add(Item("coin", "silver", count=5000))
        item = next(i for i in trade.for_sale(npc) if i.count == 1)
        purse = game.player.inventory.coins()
        ok, msg = trade.buy(game, npc, item)
        self.assertTrue(ok, msg)
        self.assertIn(item, game.player.inventory.items)
        self.assertNotIn(item, npc.inventory.items)
        self.assertLess(game.player.inventory.coins(), purse)

    def test_cannot_buy_what_you_cannot_afford(self):
        game = self.game
        npc = self._merchant()
        for coin in list(game.player.inventory.by_def("coin")):
            game.player.inventory.items.remove(coin)
        item = trade.for_sale(npc)[0]
        ok, msg = trade.buy(game, npc, item)
        self.assertFalse(ok)
        self.assertIn("afford", msg)

    def test_selling_moves_goods_and_coin(self):
        game = self.game
        npc = self._merchant()
        junk = game.player.inventory.add(Item("dagger", "copper"))
        purse = game.player.inventory.coins()
        ok, msg = trade.sell(game, npc, junk)
        self.assertTrue(ok, msg)
        self.assertGreater(game.player.inventory.coins(), purse)
        self.assertIn(junk, npc.inventory.items)

    def test_merchants_refuse_what_they_do_not_want(self):
        game = self.game
        npc = self._merchant()
        from ascii_warriors.game.ai import AIState

        npc.ai = AIState("idle", role="tavern_keeper")
        sword = game.player.inventory.add(Item("sword", "iron"))
        self.assertFalse(trade.wants(npc, sword))
        ok, _msg = trade.sell(game, npc, sword)
        self.assertFalse(ok)

    def test_stacks_can_be_split_or_sold_whole(self):
        game = self.game
        npc = self._merchant()
        arrows = game.player.inventory.add(Item("arrow", "iron", count=10))
        trade.sell(game, npc, arrows, 4)
        self.assertEqual(game.player.inventory.count_of("arrow"), 6)

    def test_renting_a_room_costs_coin_and_restores_you(self):
        game = self.game
        npc = self._merchant()
        game.player.inventory.add(Item("coin", "silver", count=500))
        game.player.needs.drowsy = 20000
        purse = game.player.inventory.coins()
        ok, msg = trade.rent_room(game, npc)
        self.assertTrue(ok, msg)
        self.assertLess(game.player.inventory.coins(), purse)
        self.assertLess(game.player.needs.drowsy, 20000)


class TestCompanions(GameFixture):
    def _candidate(self):
        rng = self.game.rng
        npc = make_creature(rng, "human", faction="town")
        from ascii_warriors.game.ai import AIState

        npc.ai = AIState("idle", role="patron")
        npc.personality.set_facet("bravery", 80)
        npc.x, npc.y, npc.z = (
            self.game.player.x, self.game.player.y, self.game.player.z)
        self.game.add_creature(npc)
        return npc

    def test_recruiting_costs_coin_and_changes_faction(self):
        game = self.game
        npc = self._candidate()
        game.player.inventory.add(Item("coin", "silver", count=5000))
        purse = game.player.inventory.coins()
        ok, msg = companions.recruit(game, npc)
        self.assertTrue(ok, msg)
        self.assertEqual(npc.faction, "player")
        self.assertIn(npc.id, game.companion_ids)
        self.assertLess(game.player.inventory.coins(), purse)
        self.assertEqual(npc.ai.leader_id, game.player.id)

    def test_cannot_recruit_without_coin(self):
        game = self.game
        npc = self._candidate()
        for coin in list(game.player.inventory.by_def("coin")):
            game.player.inventory.items.remove(coin)
        ok, msg = companions.recruit(game, npc)
        self.assertFalse(ok)
        self.assertIn("coins", msg)

    def test_party_limit_is_enforced(self):
        game = self.game
        game.player.inventory.add(Item("coin", "silver", count=100000))
        limit = companions.party_limit(game.player)
        hired = 0
        for _ in range(limit + 4):
            npc = self._candidate()
            ok, _msg = companions.recruit(game, npc)
            if ok:
                hired += 1
        self.assertEqual(hired, limit)
        self.assertEqual(len(companions.companions_of(game)), limit)

    def test_companions_fight_your_enemies(self):
        game = self.game
        npc = self._candidate()
        game.player.inventory.add(Item("coin", "silver", count=5000))
        companions.recruit(game, npc)
        goblin = make_creature(game.rng, "goblin", faction="hostile")
        self.assertTrue(npc.is_hostile_to(goblin))
        self.assertTrue(goblin.is_hostile_to(npc))

    def test_companions_travel_with_you(self):
        game = self.game
        npc = self._candidate()
        game.player.inventory.add(Item("coin", "silver", count=5000))
        companions.recruit(game, npc)
        from ascii_warriors.engine.geometry import DIRS8

        moved = False
        for dx, dy in DIRS8:
            if game.travel_step(dx, dy):
                moved = True
                break
        self.assertTrue(moved, "the adventurer should never start landlocked")
        self.assertIn(npc.id, game.creatures)
        follower = game.creatures[npc.id]
        self.assertEqual((follower.wx, follower.wy),
                         (game.player.wx, game.player.wy))
        self.assertLessEqual(game.player.distance_to(follower), 6)

    def test_dismissing_removes_them_from_the_party(self):
        game = self.game
        npc = self._candidate()
        game.player.inventory.add(Item("coin", "silver", count=5000))
        companions.recruit(game, npc)
        ok, _msg = companions.dismiss(game, npc)
        self.assertTrue(ok)
        self.assertNotIn(npc.id, game.companion_ids)
        self.assertNotEqual(npc.faction, "player")

    def test_a_dead_companion_leaves_the_party(self):
        game = self.game
        npc = self._candidate()
        game.player.inventory.add(Item("coin", "silver", count=5000))
        companions.recruit(game, npc)
        npc.body.dead = True
        npc.body.death_cause = "test"
        game.kill_creature(npc)
        self.assertNotIn(npc.id, game.companion_ids)

    def test_party_survives_save_and_load(self):
        from ascii_warriors.game import save as save_mod

        game = self.game
        npc = self._candidate()
        game.player.inventory.add(Item("coin", "silver", count=5000))
        companions.recruit(game, npc)
        name = npc.display_name()
        path = save_mod.save_game(game, game.player.name)
        loaded = save_mod.load_game(path)
        self.assertEqual(loaded.companion_ids, game.companion_ids)
        party = companions.companions_of(loaded)
        self.assertEqual(len(party), 1)
        self.assertEqual(party[0].display_name(), name)


class TestConversationExtras(GameFixture):
    def test_new_topics_are_offered_and_answered(self):
        from ascii_warriors.game import conversation

        game = self.game
        speakers = self.speakers()
        if not speakers:
            self.skipTest("no speakers at this start location")
        npc = speakers[0]
        topics = dict(conversation.topics_for(game.player, npc, game))
        for topic in topics:
            frags = conversation.say(game.player, npc, topic, game)
            self.assertTrue(frags, topic)
            for f in frags:
                self.assertNotIn("{", f.text)

    def test_trade_topic_stocks_the_merchant(self):
        from ascii_warriors.game import conversation
        from ascii_warriors.game.ai import AIState

        game = self.game
        npc = make_creature(game.rng, "merchant", faction="town")
        npc.ai = AIState("idle", role="merchant")
        game.add_creature(npc)
        conversation.say(game.player, npc, "trade", game)
        self.assertTrue(trade.for_sale(npc))


class TestRenown(GameFixture):
    """An adventurer the world has heard of."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import renown
        from ascii_warriors.world import history

        self.renown = renown
        self.history = history

    def _beast(self):
        """A megabeast from world history, standing next to the player."""
        game = self.game
        fig = self.history._spawn_megabeast(game.world, game.rng,
                                            game.time.year)
        foe = make_creature(game.rng, fig.creature_id, faction="hostile")
        foe.hf_id = fig.id
        p = game.player
        foe.x, foe.y, foe.z = p.x + 1, p.y, p.z
        game.creatures[foe.id] = foe
        game.update_fov()
        return fig, foe

    def test_the_player_is_a_historical_figure_from_the_start(self):
        """The first deed needs somebody to attribute it to."""
        game = self.game
        fig = self.renown.figure(game)
        self.assertIsNotNone(fig)
        self.assertEqual(game.player.hf_id, fig.id)
        self.assertEqual(fig.name, game.player.name)
        self.assertIs(self.renown.figure(game), fig, "made two of them")

    def test_a_notable_kill_goes_into_the_legends(self):
        """With the player's name on it."""
        game = self.game
        fig, foe = self._beast()
        before = len(game.world.events)
        foe.body.death_cause = "slain"
        game.kill_creature(foe)
        told = [e for e in game.world.events[before:] if e.kind == "beast_slain"]
        self.assertTrue(told)
        self.assertIn(game.player.name, told[0].text)
        hero = game.world.figures[game.player.hf_id]
        self.assertIn(fig.id, hero.kills)
        self.assertEqual(game.world.figures[fig.id].death_cause,
                         "slain by %s" % game.player.name)

    def test_stepping_on_a_rat_is_not_a_legend(self):
        """A legends screen listing every rat is one nobody reads."""
        game = self.game
        rat = make_creature(game.rng, "rat", faction="wild")
        p = game.player
        rat.x, rat.y, rat.z = p.x + 1, p.y, p.z
        game.creatures[rat.id] = rat
        game.update_fov()
        before = len(game.world.events)
        rat.body.death_cause = "slain"
        game.kill_creature(rat)
        self.assertEqual(len(game.world.events), before)

    def test_what_happens_out_of_sight_is_not_your_story(self):
        """Somebody else's kill must not become yours."""
        game = self.game
        fig, foe = self._beast()
        foe.x, foe.y, foe.z = 0, 0, foe.z
        game.update_fov()
        before = len(game.world.events)
        foe.body.death_cause = "slain"
        game.kill_creature(foe)
        self.assertEqual(len(game.world.events), before)

    def test_renown_earns_a_title(self):
        """And the title is what people call you."""
        game = self.game
        self.assertEqual(self.renown.title(game), "wanderer")
        self.renown.add(game, 200)
        self.assertEqual(self.renown.title(game), "legend")

    def test_a_name_is_paid_better(self):
        """Quest rewards scale with what the world has heard."""
        from ascii_warriors.game import quests

        game = self.game
        speakers = self.speakers()
        if not speakers:
            self.skipTest("nobody here to hand out work")
        giver = speakers[0]
        game.rng = RNG("quest-reward")
        plain = quests.generate_quest(RNG("q"), game, giver)
        if plain is None:
            self.skipTest("no quest available at this start")
        self.renown.add(game, 240)
        rich = quests.generate_quest(RNG("q"), game, giver)
        self.assertIsNotNone(rich)
        self.assertGreater(rich.reward, plain.reward)

    def test_retiring_leaves_you_in_the_world_alive(self):
        """The opposite of dying."""
        game = self.game
        event = self.renown.retire(game)
        hero = game.world.figures[game.player.hf_id]
        self.assertIsNone(hero.died, "retiring killed the adventurer")
        self.assertIn("retired", hero.flags)
        self.assertTrue(game.game_over)
        self.assertIn(game.player.name, event.text)

    def test_a_finished_task_is_remembered(self):
        """Quests are deeds too."""
        from ascii_warriors.game.quests import Quest

        game = self.game
        quest = Quest("bounty", "Hunt three wolves", "Wolves, three of them.")
        quest.site_name = "Testhold"
        game.quests.accept(quest)
        before = self.renown.renown(game)
        game.quests.complete(quest, game)
        self.assertGreater(self.renown.renown(game), before)
        self.assertTrue(any(quest.title in e.text for e in game.world.events))

    def test_the_famous_are_greeted_by_name(self):
        """Renown has to be visible in play, not only on the sheet."""
        from ascii_warriors.game import conversation

        game = self.game
        speakers = self.speakers()
        if not speakers:
            self.skipTest("nobody here to greet anybody")
        npc = speakers[0]
        plain = conversation.greeting(npc, game)
        self.renown.add(game, 200)
        famous = conversation.greeting(npc, game)
        self.assertNotEqual(plain, famous)
        self.assertIn(game.player.name, famous)

    def test_renown_survives_a_save(self):
        """It lives on the figure, which is what the world keeps."""
        from ascii_warriors.game.state import Game

        game = self.game
        self.renown.add(game, 60)
        clone = Game.from_dict(json.loads(json.dumps(game.to_dict())))
        self.assertEqual(self.renown.renown(clone), 60)
        self.assertEqual(self.renown.title(clone), self.renown.title(game))


class TestWeatherInGame(GameFixture):
    def test_weather_is_set_and_affects_light(self):
        game = self.game
        self.assertIn(game.weather.kind, KINDS)
        game.weather = Weather("fog", 10 ** 6)
        foggy = game.light_at(game.player.x, game.player.y, game.player.z)
        game.weather = Weather("clear", 10 ** 6)
        clear = game.light_at(game.player.x, game.player.y, game.player.z)
        if game.local.is_outside(game.player.x, game.player.y, game.player.z):
            self.assertLessEqual(foggy, clear)

    def test_weather_survives_save_and_load(self):
        from ascii_warriors.game import save as save_mod

        game = self.game
        game.weather = Weather("storm", 5000)
        path = save_mod.save_game(game, game.player.name)
        loaded = save_mod.load_game(path)
        self.assertEqual(loaded.weather.kind, "storm")

    def test_weather_changes_over_a_long_time(self):
        game = self.game
        seen = set()
        for _ in range(200):
            game._tick_world(TICKS_PER_HOUR * 4)
            seen.add(game.weather.kind)
        self.assertGreater(len(seen), 1)


class TestLocalCacheEviction(GameFixture):
    def test_cache_drops_the_least_recently_visited(self):
        game = self.game
        from ascii_warriors.engine.geometry import DIRS8

        for _ in range(60):
            game.travel_step(*game.rng.choice(list(DIRS8)))
            if game.game_over:
                break
        self.assertGreater(len(game._cache_order), 1)
        self.assertLessEqual(len(game._local_cache), 24)
        self.assertLessEqual(len(game._cache_order), 24)
        self.assertEqual(set(game._cache_order), set(game._local_cache))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestNightAdventure(GameFixture):
    """The night layer, in the half of the game that walks around in it."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import night as night_mod

        self.night = night_mod

    def _spawn(self, def_id, faction="hostile", offset=3):
        """A creature standing near the player."""
        from ascii_warriors.game.entity import make_creature

        game = self.game
        p = game.player
        c = make_creature(game.rng, def_id, faction=faction)
        for radius in range(1, 8):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    cell = (p.x + dx, p.y + dy, p.z)
                    if cell == (p.x, p.y, p.z):
                        continue
                    if game.is_passable(cell[0], cell[1], cell[2], c) \
                            and game.creature_at(*cell) is None:
                        c.x, c.y, c.z = cell
                        c.wx, c.wy = p.wx, p.wy
                        game.add_creature(c)
                        return c
        self.fail("nowhere to put a %s" % def_id)

    def _corpse_beside(self, creature):
        """A body on a free cell next to a creature."""
        from ascii_warriors.game.item import corpse_of
        from ascii_warriors.game.entity import make_creature

        game = self.game
        dead = make_creature(game.rng, "human", faction="wild")
        item = corpse_of(dead)
        item.flags["name"] = "Somebody"
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell = (creature.x + dx, creature.y + dy, creature.z)
                if cell == (creature.x, creature.y, creature.z):
                    continue
                if game.is_passable(cell[0], cell[1], cell[2], dead) \
                        and game.creature_at(*cell) is None:
                    game.drop_item(item, *cell)
                    return item, cell
        self.fail("nowhere to put a corpse")

    def test_a_necromancer_raises_on_its_turn(self):
        """Through the real AI, not by calling the raiser by hand."""
        from ascii_warriors.game import ai

        boss = self._spawn("necromancer")
        boss.profession = "necromancer"
        self._corpse_beside(boss)
        before = len(self.game.creatures)
        ai.take_turn(boss, self.game)
        self.assertEqual(boss.ai.mode, "raise")
        self.assertEqual(len(self.game.creatures), before + 1)

    def test_a_necromancer_with_no_corpses_gets_on_with_its_life(self):
        """It does not stall in raise mode with nothing to raise."""
        from ascii_warriors.game import ai

        boss = self._spawn("necromancer")
        boss.profession = "necromancer"
        self.game.items_on_ground.clear()
        ai.take_turn(boss, self.game)
        self.assertNotEqual(boss.ai.mode, "raise")

    def test_the_moon_turns_whoever_it_has_a_claim_on(self):
        """Not only the player: the innkeeper is the one who turns."""
        from ascii_warriors.data.calendar import TICKS_PER_DAY

        game = self.game
        victim = self._spawn("human", faction="town")
        self.night.afflict(victim, "werebeast")
        for day in range(60):
            game.time.ticks = day * TICKS_PER_DAY + int(TICKS_PER_DAY * 0.95)
            if self.night.moon_is_full(game.time) and game.time.is_night():
                break
        game._moon()
        self.assertTrue(victim.changed)
        self.assertEqual(victim.def_id, "werewolf")
        self.assertEqual(victim.faction, "hostile")
        game.time.ticks += int(TICKS_PER_DAY * 0.45)
        game._moon()
        self.assertFalse(victim.changed)
        self.assertEqual(victim.faction, "town")

    def test_a_cursed_player_keeps_its_own_side(self):
        """A game that takes the character away is not a game."""
        from ascii_warriors.data.calendar import TICKS_PER_DAY

        game = self.game
        p = game.player
        self.night.afflict(p, "werebeast")
        was = p.faction
        for day in range(60):
            game.time.ticks = day * TICKS_PER_DAY + int(TICKS_PER_DAY * 0.95)
            if self.night.moon_is_full(game.time) and game.time.is_night():
                break
        game._moon()
        self.assertTrue(p.changed)
        self.assertEqual(p.faction, was)
        self.assertIs(game.player, p)

    def test_the_character_sheet_names_the_affliction(self):
        """You should be able to find out what is happening to you."""
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.ui.character_screen import CharacterScene

        self.night.afflict(self.game.player, "werebeast")

        class _App:
            def __init__(self, game):
                self.game = game
                self.screen = None
                self.term = None

        scene = CharacterScene(_App(self.game))
        lines = [getattr(f, "text", str(f)) for f in scene._lines()]
        self.assertIn("Affliction", lines)
        self.assertTrue(any("Werebeast" in ln for ln in lines))
        # And the whole sheet still renders.
        scr = Screen(100, 34)
        scene.draw(scr)
        self.assertEqual(len(scr.to_text()), 34)

    def test_a_curse_survives_a_save(self):
        """Through the real save file."""
        from ascii_warriors.game import save as save_mod

        self.night.afflict(self.game.player, "vampire")
        path = save_mod.save_game(self.game, "night-test")
        back = save_mod.load_game(path)
        self.assertEqual(self.night.cursed_with(back.player), "vampire")
        path.unlink()


class TestStealth(GameFixture):
    """Moving unseen, and what happens the moment you are not."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import stealth as stealth_mod

        self.stealth = stealth_mod

    def _pair(self, sneak=0, ambusher=0, observer=0, dist=1):
        """A sneaker and a watcher, *dist* tiles apart, in a real game."""
        from ascii_warriors.game.entity import make_creature

        game = self.game
        a = make_creature(game.rng, "human", faction="wild", equip=False)
        b = make_creature(game.rng, "bandit", faction="hostile", equip=False)
        a.skills.set_level("sneak", sneak)
        a.skills.set_level("ambusher", ambusher)
        b.skills.set_level("observer", observer)
        a.x, a.y, a.z = 0, 0, 0
        b.x, b.y, b.z = dist, 0, 0
        return a, b

    # -- the roll ----------------------------------------------------------- #

    def test_standing_in_the_open_is_never_hidden(self):
        """And costs no roll at all."""
        a, b = self._pair(sneak=0, dist=9)
        self.assertFalse(self.stealth.is_sneaking(a))
        self.assertEqual(self.stealth.hide_chance(self.game, a, b), 0.0)
        self.assertTrue(self.stealth.noticed_by(self.game, a, b))

    def test_the_player_is_only_hidden_when_it_says_so(self):
        """A character that hides unasked is one the status bar lies about."""
        p = self.game.player
        p.skills.set_level("sneak", 20)
        p.skills.set_level("ambusher", 20)
        self.assertFalse(self.stealth.natural_sneak(p))
        self.assertFalse(self.stealth.hidden(p))
        self.stealth.set_sneaking(p, True)
        self.assertTrue(self.stealth.hidden(p))

    def test_sneaking_is_a_skill_not_a_posture(self):
        """Somebody who has never sneaked does not get even odds."""
        a, b = self._pair(sneak=0, dist=1)
        self.stealth.set_sneaking(a, True)
        self.assertLess(self.stealth.hide_chance(self.game, a, b), 0.2)
        c, d = self._pair(sneak=12, ambusher=6, dist=6)
        self.stealth.set_sneaking(c, True)
        self.assertGreater(self.stealth.hide_chance(self.game, c, d), 0.8)

    def test_an_observer_is_worth_a_sneak(self):
        """The watcher's skill is on the other side of the same scale."""
        a, b = self._pair(sneak=8, observer=0, dist=4)
        self.stealth.set_sneaking(a, True)
        blind = self.stealth.hide_chance(self.game, a, b)
        b.skills.set_level("observer", 8)
        sharp = self.stealth.hide_chance(self.game, a, b)
        self.assertLess(sharp, blind)

    def test_distance_and_noise_move_the_odds(self):
        """Far and still beats near and moving."""
        a, b = self._pair(sneak=8, dist=1)
        self.stealth.set_sneaking(a, True)
        self.stealth.note_action(a, "still")
        near_still = self.stealth.hide_chance(self.game, a, b)
        self.stealth.note_action(a, "move")
        near_moving = self.stealth.hide_chance(self.game, a, b)
        self.assertLess(near_moving, near_still)
        b.x = 8
        self.stealth.note_action(a, "still")
        self.assertGreater(self.stealth.hide_chance(self.game, a, b), near_still)

    def test_a_sleeping_watcher_is_not_watching(self):
        """Which is what makes a sleeping camp a thing to creep through."""
        a, b = self._pair(sneak=2, dist=2)
        self.stealth.set_sneaking(a, True)
        awake = self.stealth.hide_chance(self.game, a, b)
        b.body.unconscious = 500
        self.assertGreater(self.stealth.hide_chance(self.game, a, b), awake)

    def test_nothing_is_ever_certain(self):
        """A legendary sneak can be unlucky and a blind guard can turn round."""
        a, b = self._pair(sneak=20, ambusher=20, dist=20)
        self.stealth.set_sneaking(a, True)
        self.assertLessEqual(self.stealth.hide_chance(self.game, a, b),
                             self.stealth.MAX_CHANCE)
        c, d = self._pair(sneak=0, observer=20, dist=1)
        self.stealth.set_sneaking(c, True)
        self.assertGreaterEqual(self.stealth.hide_chance(self.game, c, d),
                                self.stealth.MIN_CHANCE)

    def test_a_lit_torch_gives_you_away(self):
        """The thing that lets you see the corridor is the thing they see."""
        from ascii_warriors.game.item import make_item

        a, b = self._pair(sneak=10, dist=5)
        self.stealth.set_sneaking(a, True)
        dark = self.stealth.hide_chance(self.game, a, b)
        torch = make_item(self.game.rng, "torch")
        torch.flags["lit"] = True
        torch.charges = max(1, torch.charges)
        a.inventory.add(torch)
        self.assertTrue(self.stealth._carrying_light(a))
        self.assertLess(self.stealth.hide_chance(self.game, a, b), dark)

    # -- who does it at all --------------------------------------------------- #

    def test_some_creatures_sneak_without_being_told(self):
        """Which is what makes the skills the data files hand out mean something."""
        from ascii_warriors.game.entity import make_creature

        thief = make_creature(self.game.rng, "kobold", faction="hostile")
        thief.skills.set_level("sneak", 8)
        self.assertTrue(self.stealth.natural_sneak(thief))
        self.assertTrue(self.stealth.hidden(thief))
        ox = make_creature(self.game.rng, "cow", faction="wild")
        self.assertFalse(self.stealth.natural_sneak(ox))
        self.assertFalse(self.stealth.hidden(ox))

    def test_the_ai_does_not_chase_what_it_has_not_noticed(self):
        """Line of sight is not the same as having seen something."""
        from ascii_warriors.game import ai
        from ascii_warriors.game.entity import make_creature

        game = self.game
        p = game.player
        p.skills.set_level("sneak", 20)
        p.skills.set_level("ambusher", 20)
        foe = make_creature(game.rng, "bandit", faction="hostile", equip=False)
        foe.x, foe.y, foe.z = p.x + 1, p.y, p.z
        game.add_creature(foe)
        self.assertIn(p, ai.hostile_targets(foe, game))
        self.stealth.set_sneaking(p, True)
        seen = sum(1 for _ in range(60)
                   if p in ai.hostile_targets(foe, game))
        self.assertLess(seen, 30, "a legendary sneak is always spotted")

    def test_fighting_is_not_sneaking(self):
        """You cannot stab somebody quietly enough to stay hidden from them."""
        a, _b = self._pair(sneak=10)
        self.stealth.set_sneaking(a, True)
        self.stealth.note_action(a, "fight")
        self.assertFalse(self.stealth.is_sneaking(a))

    # -- ambush --------------------------------------------------------------- #

    def test_an_ambush_lands_where_it_is_aimed(self):
        """A dagger in the dark is a different weapon from a dagger in a fight."""
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item

        game = self.game
        hits = necks = 0
        for _ in range(60):
            a = make_creature(game.rng, "human", faction="wild", equip=False)
            a.skills.set_level("dagger", 6)
            a.skills.set_level("sneak", 15)
            a.inventory.add(make_item(game.rng, "dagger"))
            a.inventory.auto_equip()
            b = make_creature(game.rng, "bandit", faction="hostile")
            a.x, a.y, a.z = 0, 0, 0
            b.x, b.y, b.z = 1, 0, 0
            self.stealth.set_sneaking(a, True)
            r = combat.melee_attack(a, b, rng=game.rng, log=None, world=game)
            if r.ambush and r.hit:
                hits += 1
                if r.part in ("neck", "throat", "head"):
                    necks += 1
        self.assertGreater(hits, 30, "ambushes never landed")
        self.assertGreater(necks, hits * 0.6, "ambushes did not aim")

    def test_an_ambush_hits_harder_than_a_fair_blow(self):
        """The whole reason to bother sneaking up on anything."""
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item

        game = self.game

        def strike(sneaking):
            total = landed = 0
            for _ in range(60):
                a = make_creature(game.rng, "human", faction="wild",
                                  equip=False)
                a.skills.set_level("dagger", 6)
                a.skills.set_level("sneak", 15)
                a.inventory.add(make_item(game.rng, "dagger"))
                a.inventory.auto_equip()
                b = make_creature(game.rng, "bandit", faction="hostile")
                a.x, a.y, a.z = 0, 0, 0
                b.x, b.y, b.z = 1, 0, 0
                self.stealth.set_sneaking(a, sneaking)
                r = combat.melee_attack(a, b, rng=game.rng, log=None,
                                        world=game if sneaking else None)
                if r.hit:
                    landed += 1
                    total += r.damage
            return landed, total / max(1, landed)

        fair_hits, fair_dmg = strike(False)
        amb_hits, amb_dmg = strike(True)
        self.assertGreater(amb_hits, fair_hits)
        self.assertGreater(amb_dmg, fair_dmg * 1.5)

    def test_an_ambush_gives_you_away(self):
        """One devastating blow, then an ordinary fight."""
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        game = self.game
        a = make_creature(game.rng, "human", faction="wild", equip=False)
        a.skills.set_level("sneak", 15)
        b = make_creature(game.rng, "bandit", faction="hostile")
        a.x, a.y, a.z = 0, 0, 0
        b.x, b.y, b.z = 1, 0, 0
        self.stealth.set_sneaking(a, True)
        combat.melee_attack(a, b, rng=game.rng, log=None, world=game)
        self.assertFalse(self.stealth.is_sneaking(a))

    def test_a_fair_fight_is_never_an_ambush(self):
        """No world, no ambush: the two fortress loops must stay fair."""
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        game = self.game
        a = make_creature(game.rng, "human", faction="wild", equip=False)
        a.skills.set_level("sneak", 20)
        b = make_creature(game.rng, "bandit", faction="hostile")
        a.x, a.y, a.z = 0, 0, 0
        b.x, b.y, b.z = 1, 0, 0
        self.stealth.set_sneaking(a, True)
        r = combat.melee_attack(a, b, rng=game.rng, log=None)
        self.assertFalse(r.ambush)

    # -- the player ----------------------------------------------------------- #

    def test_a_blocked_arrow_still_works(self):
        """The ambush guard belongs to melee and must not leak into ranged."""
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item

        game = self.game
        a = make_creature(game.rng, "human", faction="wild", equip=False)
        a.skills.set_level("bow", 8)
        bow = make_item(game.rng, "bow")
        arrows = make_item(game.rng, "arrow", count=40)
        a.inventory.add(bow)
        a.inventory.add(arrows)
        a.inventory.auto_equip()
        blocked = 0
        for _ in range(60):
            b = make_creature(game.rng, "bandit", faction="hostile")
            b.skills.set_level("shield_use", 12)
            b.inventory.add(make_item(game.rng, "shield"))
            b.inventory.auto_equip()
            a.x, a.y, a.z = 0, 0, 0
            b.x, b.y, b.z = 5, 0, 0
            r = combat.ranged_attack(a, b, bow, arrows, rng=game.rng, log=None)
            if r.blocked:
                blocked += 1
        self.assertGreater(blocked, 0, "no arrow was ever blocked")

    def test_the_sneak_key_is_free_and_reversible(self):
        """Being careful is a posture, not an action."""
        from ascii_warriors.game import actions

        game = self.game
        self.assertEqual(actions.toggle_sneak(game), actions.FREE)
        self.assertTrue(self.stealth.is_sneaking(game.player))
        actions.toggle_sneak(game)
        self.assertFalse(self.stealth.is_sneaking(game.player))

    def test_moving_makes_noise(self):
        """Through the real move, not by setting the flag."""
        game = self.game
        p = game.player
        self.stealth.set_sneaking(p, True)
        self.assertEqual(p.noise, "still")
        game.move_creature(p, p.x, p.y, p.z)
        self.assertEqual(p.noise, "move")

    def test_the_look_panel_says_whether_it_has_seen_you(self):
        """The only thing that makes a hidden roll playable."""
        from ascii_warriors.game.entity import make_creature

        game = self.game
        p = game.player
        foe = make_creature(game.rng, "bandit", faction="hostile", equip=False)
        foe.x, foe.y, foe.z = p.x + 1, p.y, p.z
        game.add_creature(foe)
        plain = " ".join(f.text for f in
                         game.describe_tile(foe.x, foe.y, foe.z))
        self.assertNotIn("see you", plain)
        self.stealth.set_sneaking(p, True)
        p.skills.set_level("sneak", 20)
        p.skills.set_level("ambusher", 20)
        hidden = " ".join(f.text for f in
                          game.describe_tile(foe.x, foe.y, foe.z))
        self.assertIn("no idea you are there", hidden)

    def test_sneaking_survives_a_save(self):
        """Through the real save file."""
        from ascii_warriors.game import save as save_mod

        self.stealth.set_sneaking(self.game.player, True)
        path = save_mod.save_game(self.game, "stealth-test")
        back = save_mod.load_game(path)
        self.assertTrue(self.stealth.is_sneaking(back.player))
        path.unlink()


class TestBooks(GameFixture):
    """The written word: what is in a book, and what reading one does."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import books as books_mod

        self.books = books_mod

    def _book(self, kind="history", depth=3):
        """A bound book of a given kind, in the player's hands."""
        from ascii_warriors.game.item import make_item

        item = make_item(self.game.rng, "book")
        book = self.books.bind(self.game.world, self.game.rng, item,
                               kind=kind, depth=depth)
        self.game.player.inventory.add(item)
        return item, book

    def _slab(self):
        """A slab, in the player's hands."""
        from ascii_warriors.game.item import make_item

        item = make_item(self.game.rng, "book")
        book = self.books.make_slab(self.game.rng)
        self.books.attach(item, book)
        self.game.player.inventory.add(item)
        return item, book

    # -- what is in one ------------------------------------------------------ #

    def test_a_book_is_about_something_that_happened(self):
        """A book about nothing is a prop."""
        _item, book = self._book("history")
        self.assertTrue(book.title)
        self.assertTrue(book.subject)
        self.assertIsNotNone(book.civ_id)
        self.assertTrue(book.event_ids, "bound to no real history")
        for eid in book.event_ids:
            self.assertTrue(any(e.id == eid for e in self.game.world.events))

    def test_every_kind_of_book_binds_to_the_world(self):
        """Or falls back to a general treatise rather than to nonsense."""
        for kind, _pattern, _skill in self.books.SUBJECTS:
            _item, book = self._book(kind, depth=2)
            self.assertTrue(book.subject, "%s has no subject" % kind)
            self.assertNotIn("%s", book.subject)
            self.assertTrue(book.title)

    def test_the_title_takes_the_name_of_the_item(self):
        """So a shelf of books reads as a shelf of books."""
        item, book = self._book()
        self.assertIn(book.title, item.name())

    def test_a_deeper_book_is_worth_more(self):
        """Which is what makes a library a target."""
        thin, _ = self._book(depth=1)
        thick, _ = self._book(depth=5)
        self.assertGreater(self.books.value_of(thick),
                           self.books.value_of(thin))

    def test_a_plain_item_is_not_a_book(self):
        """`of` has to say no cheaply, because everything asks it."""
        from ascii_warriors.game.item import make_item

        self.assertIsNone(self.books.of(make_item(self.game.rng, "dagger")))

    # -- reading ------------------------------------------------------------- #

    def test_reading_opens_the_world_s_own_history(self):
        """The world keeps a history nobody can otherwise read without walking."""
        item, book = self._book("history")
        lines = self.books.read(self.game, self.game.player, book)
        self.assertTrue(any("learn of" in ln for ln in lines))
        known = self.game.world.known_events
        for eid in book.event_ids:
            self.assertIn(eid, known)

    def test_reading_the_same_book_twice_teaches_nothing(self):
        """Which is what makes a library worth more than one very good book."""
        _item, book = self._book()
        self.books.read(self.game, self.game.player, book)
        again = self.books.read(self.game, self.game.player, book)
        self.assertEqual(len(again), 1)
        self.assertIn("read this before", again[0])

    def test_a_book_can_teach_its_skill_but_only_so_far(self):
        """At some point somebody has to swing a sword at you."""
        p = self.game.player
        _item, book = self._book("swordsmanship", depth=5)
        self.assertEqual(book.skill, "sword")
        before = p.skills.level("sword")
        self.books.read(self.game, p, book)
        self.assertGreaterEqual(p.skills.level("sword"), before)
        p.skills.set_level("sword", self.books.BOOK_SKILL_CAP + 2)
        _item2, book2 = self._book("swordsmanship", depth=5)
        lines = self.books.read(self.game, p, book2)
        self.assertTrue(any("more of this than the author" in ln
                            for ln in lines))

    def test_a_slow_reader_takes_longer(self):
        """A deep book with a poor reader is most of a day."""
        p = self.game.player
        _item, book = self._book(depth=5)
        p.skills.set_level("reading", 0)
        slow = self.books.read_turns(p, book)
        p.skills.set_level("reading", 12)
        self.assertLess(self.books.read_turns(p, book), slow)

    def test_reading_costs_turns_and_refuses_company(self):
        """A book is not a thing you finish while somebody walks towards you."""
        from ascii_warriors.game import actions
        from ascii_warriors.game.entity import make_creature

        game = self.game
        item, _book = self._book(depth=4)
        cost = actions.read_book(game, item)
        self.assertGreater(cost, actions.FREE)

        item2, _b2 = self._book(depth=4)
        foe = make_creature(game.rng, "bandit", faction="hostile", equip=False)
        foe.x, foe.y, foe.z = game.player.x, game.player.y, game.player.z
        game.add_creature(foe)
        game.update_fov()
        self.assertEqual(actions.read_book(game, item2), actions.FREE)
        self.assertTrue(any("company" in m.text for m in game.log.recent(3)))

    def test_reading_something_with_nothing_written_on_it(self):
        """The action has to survive being pointed at a dagger."""
        from ascii_warriors.game import actions
        from ascii_warriors.game.item import make_item

        knife = make_item(self.game.rng, "dagger")
        self.assertEqual(actions.read_book(self.game, knife), actions.FREE)

    # -- secrets -------------------------------------------------------------- #

    def test_a_slab_makes_you_a_necromancer(self):
        """v3.5's machinery takes any creature; this is the key to it."""
        from ascii_warriors.game import night

        p = self.game.player
        self.assertFalse(night.is_necromancer(p))
        _item, slab = self._slab()
        lines = self.books.read(self.game, p, slab)
        self.assertTrue(any("raise the dead" in ln for ln in lines))
        self.assertTrue(self.books.knows_secret(p, "necromancy"))
        self.assertTrue(night.is_necromancer(p))

    def test_a_secret_is_only_learned_once(self):
        """Reading the same stone twice teaches nothing."""
        p = self.game.player
        _item, slab = self._slab()
        self.books.read(self.game, p, slab)
        _item2, slab2 = self._slab()
        lines = self.books.read(self.game, p, slab2)
        self.assertTrue(any("already know" in ln for ln in lines))
        self.assertEqual(p.secrets.count("necromancy"), 1)

    def test_a_necromancer_player_raises_the_dead(self):
        """The whole payoff, and it needed no special case in `night`."""
        from ascii_warriors.game import actions, night
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import corpse_of

        game = self.game
        p = game.player
        _item, slab = self._slab()
        self.books.read(game, p, slab)

        dead = make_creature(game.rng, "human", faction="wild")
        body = corpse_of(dead)
        body.flags["name"] = "Alric"
        placed = False
        for dx in (1, -1, 0):
            for dy in (0, 1, -1):
                cell = (p.x + dx, p.y + dy, p.z)
                if cell == (p.x, p.y, p.z):
                    continue
                if game.is_passable(*cell, dead) \
                        and game.creature_at(*cell) is None:
                    game.drop_item(body, *cell)
                    placed = True
                    break
            if placed:
                break
        self.assertTrue(placed, "nowhere to put a body")
        before = len(game.creatures)
        cost = actions.raise_dead(game)
        self.assertGreater(cost, actions.FREE)
        self.assertEqual(len(game.creatures), before + 1)
        mine = [c for c in game.creatures.values() if c.raised_by == p.id]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].faction, p.faction)
        self.assertFalse(mine[0].is_hostile_to(p))

    def test_without_the_secret_there_is_no_raising(self):
        """And the action says so rather than doing nothing."""
        from ascii_warriors.game import actions

        self.assertEqual(actions.raise_dead(self.game), actions.FREE)
        self.assertTrue(any("do not know how" in m.text
                            for m in self.game.log.recent(3)))

    def test_raising_with_nothing_to_raise(self):
        """The other way the action can be pointed at nothing."""
        from ascii_warriors.game import actions

        game = self.game
        _item, slab = self._slab()
        self.books.read(game, game.player, slab)
        game.items_on_ground.clear()
        self.assertEqual(actions.raise_dead(game), actions.FREE)

    # -- in the world ---------------------------------------------------------- #

    def test_books_ride_in_on_the_people_who_own_them(self):
        """Sitegen returns people, not floors."""
        carried = [
            self.books.of(i)
            for c in self.game.creatures.values()
            for i in c.inventory.items
            if self.books.of(i) is not None
        ]
        # The starting site may or may not have a lord with a library, so this
        # asserts the machinery rather than the dice.
        self.assertIn("necromancer", self.game.BOOKISH)
        self.assertIn("tomb_lord", self.game.BOOKISH)
        for book in carried:
            self.assertTrue(book.title)

    def test_a_slab_bearer_carries_a_slab(self):
        """Not a book: the one thing the profession is for."""
        from ascii_warriors.engine.rng import RNG

        game = self.game
        rng = RNG("bookish")
        for profession in ("necromancer", "tomb_lord"):
            found = False
            for _ in range(20):
                from ascii_warriors.game.entity import make_creature

                c = make_creature(rng, "human", faction="hostile")
                c.profession = profession
                game._give_books(c, rng)
                slabs = [self.books.of(i) for i in c.inventory.items
                         if self.books.of(i) is not None]
                if slabs:
                    self.assertTrue(slabs[0].is_slab)
                    found = True
                    break
            self.assertTrue(found, "%s never carried anything" % profession)

    # -- persistence ------------------------------------------------------------ #

    def test_a_book_keeps_what_is_written_in_it(self):
        """Through the real save file, including who has read it."""
        from ascii_warriors.game import save as save_mod

        item, book = self._book("biography", depth=4)
        self.books.read(self.game, self.game.player, book)
        path = save_mod.save_game(self.game, "books-test")
        back = save_mod.load_game(path)
        found = None
        for it in back.player.inventory.items:
            b = self.books.of(it)
            if b is not None and b.title == book.title:
                found = b
                break
        self.assertIsNotNone(found, "the book did not come back")
        self.assertEqual(found.depth, 4)
        self.assertEqual(found.subject, book.subject)
        self.assertEqual(found.event_ids, book.event_ids)
        self.assertIn(back.player.id, found.read_by)
        path.unlink()

    def test_a_secret_survives_a_save(self):
        """You do not forget how at the save screen."""
        from ascii_warriors.game import night, save as save_mod

        _item, slab = self._slab()
        self.books.read(self.game, self.game.player, slab)
        path = save_mod.save_game(self.game, "secret-test")
        back = save_mod.load_game(path)
        self.assertTrue(night.is_necromancer(back.player))
        path.unlink()


class TestArtForms(GameFixture):
    """Forms are cultural property with an owner, a date and a subject."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.world import artforms

        self.artforms = artforms

    def test_worldgen_gives_every_civilization_forms(self):
        for civ in self.world.civs:
            mine = self.artforms.of_civ(self.world, civ.id)
            self.assertTrue(mine, "%s invented nothing" % civ.name)

    def test_every_kind_of_form_exists(self):
        kinds = {f.kind for f in self.artforms.forms(self.world)}
        self.assertEqual(kinds, set(self.artforms.KINDS))

    def test_a_form_is_owned_by_a_real_civilization(self):
        ids = {c.id for c in self.world.civs}
        for f in self.artforms.forms(self.world):
            self.assertIn(f.civ_id, ids)

    def test_a_musical_form_asks_for_a_real_instrument(self):
        from ascii_warriors.data import items as item_data

        for f in self.artforms.forms(self.world):
            if f.kind != "music":
                continue
            self.assertTrue(item_data.get(f.instrument).has("INSTRUMENT"))

    def test_nobody_wrote_the_song_before_the_battle(self):
        for f in self.artforms.forms(self.world):
            ev = self.artforms._event(self.world, f.event_id)
            if ev is not None:
                self.assertLessEqual(ev.year, f.year, f.name)

    def test_some_forms_are_about_something_that_happened(self):
        forms = self.artforms.forms(self.world)
        bound = [f for f in forms if f.event_id is not None]
        self.assertTrue(bound, "no form is about anything")
        self.assertLess(len(bound), len(forms), "every form is documentary")

    def test_a_form_describes_itself_completely(self):
        form = self.artforms.forms(self.world)[0]
        lines = self.artforms.describe(self.world, form)
        text = " ".join(lines)
        self.assertIn(form.name, text)
        self.assertIn(form.structure, text)

    def test_forms_survive_a_world_round_trip(self):
        from ascii_warriors.world.worldgen import World

        back = World.from_dict(self.world.to_dict())
        self.assertEqual(len(back.forms), len(self.artforms.forms(self.world)))
        a = self.artforms.forms(self.world)[0]
        b = self.artforms.by_id(back, a.id)
        self.assertEqual((b.name, b.kind, b.civ_id, b.year, b.instrument),
                         (a.name, a.kind, a.civ_id, a.year, a.instrument))

    def test_an_older_world_without_forms_still_loads(self):
        from ascii_warriors.world.worldgen import World

        raw = self.world.to_dict()
        del raw["forms"]
        raw["counters"] = raw["counters"][:4]
        back = World.from_dict(raw)
        self.assertEqual(back.forms, [])
        self.assertGreaterEqual(back._next_form, 1)

    def test_populate_is_idempotent(self):
        before = len(self.artforms.forms(self.world))
        self.artforms.populate(self.world, RNG("again"))
        self.assertEqual(len(self.artforms.forms(self.world)), before)


class TestPerformance(GameFixture):
    """The roll, the room, and what the room takes away from it."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import performance
        from ascii_warriors.world import artforms

        self.perf = performance
        self.artforms = artforms
        self.form = self._form("poetry")

    def _form(self, kind):
        for f in self.artforms.forms(self.world):
            if f.kind == kind:
                return f
        raise AssertionError("no %s form generated" % kind)

    def _listener(self):
        others = self.speakers()
        self.assertTrue(others, "nobody to perform to")
        return others[0]

    # -- the curve --------------------------------------------------------- #

    def test_an_untrained_performer_is_never_good(self):
        p = self.game.player
        p.skills.set_level("poetry", 0)
        self.perf.learn(p, self.form)
        rng = RNG("untrained")
        worst = max(self.perf.band(self.world, rng, p, self.form)
                    for _ in range(400))
        self.assertLessEqual(worst, 2)

    def test_a_legendary_performer_is_never_bad(self):
        p = self.game.player
        p.skills.set_level("poetry", 18)
        self.perf.learn(p, self.form)
        rng = RNG("legend")
        best = min(self.perf.band(self.world, rng, p, self.form)
                   for _ in range(400))
        self.assertGreaterEqual(best, 4)

    def test_skill_moves_the_curve_upwards(self):
        p = self.game.player
        self.perf.learn(p, self.form)
        means = []
        for level in (0, 6, 12, 18):
            p.skills.set_level("poetry", level)
            rng = RNG("curve%d" % level)
            means.append(sum(self.perf.band(self.world, rng, p, self.form)
                             for _ in range(200)) / 200.0)
        self.assertEqual(means, sorted(means))

    def test_knowing_the_form_is_worth_something(self):
        p = self.game.player
        p.skills.set_level("poetry", 8)
        p.forms = []
        blind = self.perf.score(self.world, p, self.form)
        self.perf.learn(p, self.form)
        self.assertGreater(self.perf.score(self.world, p, self.form), blind)

    # -- instruments ------------------------------------------------------- #

    def test_music_without_an_instrument_is_penalised(self):
        from ascii_warriors.game.item import make_item

        song = self._form("music")
        p = self.game.player
        p.skills.set_level("music", 8)
        self.perf.learn(p, song)
        empty = self.perf.score(self.world, p, song)
        p.inventory.add(make_item(self.game.rng, song.instrument))
        self.assertGreater(self.perf.score(self.world, p, song), empty)

    def test_the_wrong_instrument_beats_none_and_loses_to_the_right_one(self):
        from ascii_warriors.game.item import make_item

        song = self._form("music")
        wrong = [i for i in self.artforms.INSTRUMENTS if i != song.instrument][0]
        p = self.game.player
        self.perf.learn(p, song)
        none_ = self.perf.instrument_for(p, song)[1]
        bad = self.perf.instrument_for(p, song, [make_item(self.game.rng, wrong)])[1]
        good = self.perf.instrument_for(
            p, song, [make_item(self.game.rng, song.instrument)])[1]
        self.assertLess(none_, bad)
        self.assertLess(bad, good)

    def test_an_instrument_in_the_room_counts_as_much_as_one_in_hand(self):
        from ascii_warriors.game.item import make_item

        song = self._form("music")
        p = self.game.player
        lying = [make_item(self.game.rng, song.instrument)]
        item, bonus = self.perf.instrument_for(p, song, lying)
        self.assertIs(item, lying[0])
        self.assertEqual(bonus, self.perf.INSTRUMENT_BONUS)

    def test_poetry_never_wants_an_instrument(self):
        self.assertEqual(self.perf.instrument_for(self.game.player, self.form),
                         (None, 0))

    # -- what it does to the room ------------------------------------------ #

    def test_a_good_performance_relieves_the_audience(self):
        listener = self._listener()
        listener.needs.stress = 60
        p = self.game.player
        p.skills.set_level("poetry", 18)
        self.perf.learn(p, self.form)
        self.perf.perform(self.game, RNG("good"), p, self.form, [listener])
        self.assertLess(listener.needs.stress, 60)

    def test_a_bad_performance_costs_the_audience(self):
        listener = self._listener()
        listener.needs.stress = 0
        p = self.game.player
        p.skills.set_level("poetry", 0)
        p.forms = []
        rng = RNG("bad")
        for _ in range(6):
            self.perf.perform(self.game, rng, p, self.form, [listener])
        self.assertGreater(listener.needs.stress, 0)

    def test_relief_stops_at_the_floor(self):
        self.assertEqual(self.perf.felt(self.perf.RELIEF_FLOOR, 6), 0)
        self.assertEqual(self.perf.felt(self.perf.RELIEF_FLOOR - 50, 6), 0)
        self.assertLess(self.perf.felt(0, 6), 0)

    def test_annoyance_stops_at_the_ceiling(self):
        self.assertEqual(self.perf.felt(self.perf.ANNOYANCE_CEILING, 0), 0)
        self.assertEqual(self.perf.felt(self.perf.ANNOYANCE_CEILING + 50, 0), 0)
        self.assertGreater(self.perf.felt(0, 0), 0)

    def test_no_performance_can_push_past_the_window(self):
        """The bug that made the tavern the only system that mattered."""
        listener = self._listener()
        listener.needs.stress = 0
        p = self.game.player
        p.skills.set_level("poetry", 18)
        self.perf.learn(p, self.form)
        rng = RNG("many")
        for _ in range(200):
            self.perf.perform(self.game, rng, p, self.form, [listener],
                              mood=1.35)
        self.assertGreaterEqual(listener.needs.stress,
                                self.perf.RELIEF_FLOOR - 1)

    def test_the_performer_is_bounded_too(self):
        listener = self._listener()
        p = self.game.player
        p.skills.set_level("poetry", 18)
        p.needs.stress = 0
        self.perf.learn(p, self.form)
        rng = RNG("self")
        for _ in range(200):
            self.perf.perform(self.game, rng, p, self.form, [listener])
        self.assertGreaterEqual(p.needs.stress, self.perf.RELIEF_FLOOR - 1)

    def test_performing_trains_the_form_s_own_skill(self):
        p = self.game.player
        before = p.skills.exp("poetry")
        self.perf.perform(self.game, RNG("train"), p, self.form,
                          [self._listener()])
        self.assertGreater(p.skills.exp("poetry"), before)

    def test_the_dead_are_not_an_audience(self):
        listener = self._listener()
        listener.alive = False
        result = self.perf.perform(self.game, RNG("dead"), self.game.player,
                                   self.form, [listener])
        self.assertEqual(result.audience, [])

    def test_you_are_never_your_own_audience(self):
        p = self.game.player
        result = self.perf.perform(self.game, RNG("solo"), p, self.form, [p])
        self.assertEqual(result.audience, [])

    # -- forms travelling -------------------------------------------------- #

    def test_a_good_performance_can_teach_the_form(self):
        listener = self._listener()
        listener.forms = []
        p = self.game.player
        p.skills.set_level("poetry", 18)
        self.perf.learn(p, self.form)
        rng = RNG("teach")
        for _ in range(40):
            self.perf.perform(self.game, rng, p, self.form, [listener])
            if self.perf.knows(listener, self.form):
                break
        self.assertTrue(self.perf.knows(listener, self.form))

    def test_a_bad_performance_teaches_nobody(self):
        listener = self._listener()
        listener.forms = []
        p = self.game.player
        p.skills.set_level("poetry", 0)
        p.forms = []
        rng = RNG("nope")
        for _ in range(60):
            self.perf.perform(self.game, rng, p, self.form, [listener])
        self.assertFalse(self.perf.knows(listener, self.form))

    def test_learning_a_form_twice_is_not_learning_it(self):
        listener = self._listener()
        listener.forms = []
        self.assertTrue(self.perf.learn(listener, self.form))
        self.assertFalse(self.perf.learn(listener, self.form))
        self.assertEqual(listener.forms.count(self.form.id), 1)

    def test_hearing_a_song_opens_the_history_it_is_about(self):
        bound = [f for f in self.artforms.forms(self.world)
                 if f.event_id is not None]
        if not bound:
            self.skipTest("no form in this world is about an event")
        form = bound[0]
        self.world.known_events = set()
        lines = self.perf.reveal(self.game, form)
        self.assertTrue(lines)
        self.assertEqual(self.perf.reveal(self.game, form), [])

    def test_a_new_adventurer_knows_their_own_people_s_songs(self):
        self.assertTrue(self.game.player.forms)

    def test_forms_survive_a_save(self):
        from ascii_warriors.game import save as save_mod

        self.perf.learn(self.game.player, self.form)
        known = sorted(self.game.player.forms)
        path = save_mod.save_game(self.game, "forms-test")
        back = save_mod.load_game(path)
        self.assertEqual(sorted(back.player.forms), known)
        path.unlink()


class TestTracks(GameFixture):
    """Footprints, and the skill that has never read one."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import tracks

        self.tracks = tracks
        self.soft = self._soft_cell()

    def _soft_cell(self):
        """A nearby cell whose ground takes a print."""
        p = self.game.player
        for r in range(1, 12):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    cell = (p.x + dx, p.y + dy, p.z)
                    if self.tracks.takes_print(self.game, cell):
                        return cell
        return None

    def _walker(self):
        others = [c for c in self.game.creatures.values() if not c.is_player]
        if not others:
            self.skipTest("nothing to walk about")
        return others[0]

    def _walk(self, creature, cell, frm=None):
        """Walk a creature onto a cell through the real funnel."""
        x, y, z = cell
        if frm is not None:
            creature.x, creature.y, creature.z = frm
        self.game.move_creature(creature, x, y, z)
        return self.tracks.readable(self.game, cell)

    # -- leaving them ------------------------------------------------------ #

    def test_walking_on_soft_ground_leaves_a_track(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        beast = self._walker()
        track = self._walk(beast, self.soft)
        self.assertIsNotNone(track)
        self.assertEqual(track.def_id, beast.def_id)

    def test_rock_takes_no_print(self):
        p = self.game.player
        hard = None
        for r in range(1, 14):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    cell = (p.x + dx, p.y + dy, p.z)
                    if (self.game.local.in_bounds(*cell)
                            and not self.tracks.takes_print(self.game, cell)):
                        hard = cell
                        break
                if hard:
                    break
            if hard:
                break
        if hard is None:
            self.skipTest("everything here is soft")
        self._walk(self._walker(), hard)
        self.assertIsNone(self.tracks.readable(self.game, hard))

    def test_the_track_remembers_which_way_it_went(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        x, y, z = self.soft
        track = self._walk(self._walker(), self.soft, frm=(x - 1, y, z))
        self.assertEqual(track.heading, "east")

    def test_every_step_has_a_heading(self):
        from ascii_warriors.game.tracks import Track

        seen = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                seen.add(Track(dx=dx, dy=dy).heading)
        self.assertEqual(len(seen), 9)
        self.assertEqual(Track(dx=1, dy=0).heading, "east")
        self.assertEqual(Track(dx=0, dy=-1).heading, "north")

    def test_a_herd_reads_as_a_herd(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        beast = self._walker()
        for _ in range(4):
            track = self._walk(beast, self.soft)
        self.assertGreater(track.count, 1)

    def test_a_different_animal_overwrites_the_count(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        others = [c for c in self.game.creatures.values() if not c.is_player]
        kinds = {}
        for c in others:
            kinds.setdefault(c.def_id, c)
        if len(kinds) < 2:
            self.skipTest("only one kind of creature here")
        a, b = list(kinds.values())[:2]
        self._walk(a, self.soft)
        self._walk(a, self.soft)
        track = self._walk(b, self.soft)
        self.assertEqual(track.count, 1)
        self.assertEqual(track.def_id, b.def_id)

    def test_the_player_leaves_their_own_trail(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        track = self._walk(self.game.player, self.soft)
        self.assertTrue(track.player)

    # -- reading them ------------------------------------------------------ #

    def test_the_untrained_only_know_something_passed(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        track = self._walk(self._walker(), self.soft)
        self.game.player.skills.set_level("tracker", 0)
        lines = self.tracks.read(self.game, self.game.player, self.soft, track)
        self.assertEqual(len(lines), 1)
        self.assertNotIn(track.name, " ".join(lines))

    def test_the_skill_hands_over_one_fact_at_a_time(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        track = self._walk(self._walker(), self.soft)
        track.count = 4
        counts = []
        for level in (0, 2, 5, 8, 11, 15):
            self.game.player.skills.set_level("tracker", level)
            counts.append(len(self.tracks.read(
                self.game, self.game.player, self.soft, track)))
        self.assertEqual(counts, sorted(counts))
        self.assertGreater(counts[-1], counts[0])

    def test_a_hunter_names_the_animal(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        beast = self._walker()
        track = self._walk(beast, self.soft)
        self.game.player.skills.set_level("tracker",
                                          self.tracks.SPECIES_AT)
        text = " ".join(self.tracks.read(
            self.game, self.game.player, self.soft, track))
        self.assertIn(beast.short_name(), text)

    def test_blood_is_reported_to_anybody_who_can_name_the_animal(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        track = self._walk(self._walker(), self.soft)
        track.blood = True
        self.game.player.skills.set_level("tracker", self.tracks.SPECIES_AT)
        text = " ".join(self.tracks.read(
            self.game, self.game.player, self.soft, track))
        self.assertIn("blood", text)

    # -- ageing and weather ------------------------------------------------ #

    def test_a_track_fades_with_time(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        self._walk(self._walker(), self.soft)
        self.game.scheduler.ticks += self.tracks.BLOOD_FADE * 2
        self.assertIsNone(self.tracks.readable(self.game, self.soft))

    def test_snow_holds_a_print_longer_than_sand(self):
        self.assertGreater(self.tracks.FADE["snow"], self.tracks.FADE["sand"])

    def test_rain_takes_the_trail(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        self._walk(self._walker(), self.soft)
        self.assertTrue(self.tracks.layer(self.game))
        self.tracks.wipe(self.game)
        self.assertFalse(self.tracks.layer(self.game))

    def test_the_layer_is_capped(self):
        from ascii_warriors.game.tracks import Track

        marks = self.tracks.layer(self.game)
        for i in range(self.tracks.MAX_TRACKS + 50):
            t = Track("rat", "rat", 1000, 1, 0, i)
            marks[(i % 60, i // 60, 0)] = t
        self.tracks.prune(self.game)
        self.assertLessEqual(len(marks), self.tracks.MAX_TRACKS)

    def test_pruning_drops_the_oldest_first(self):
        from ascii_warriors.game.tracks import Track

        marks = self.tracks.layer(self.game)
        marks.clear()
        for i in range(self.tracks.MAX_TRACKS + 40):
            marks[(i, 0, 0)] = Track("rat", "rat", 1000, 1, 0, i)
        self.tracks.prune(self.game)
        self.assertNotIn((0, 0, 0), marks)
        self.assertIn((self.tracks.MAX_TRACKS + 39, 0, 0), marks)

    # -- the player's side -------------------------------------------------- #

    def test_searching_reads_the_ground(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        from ascii_warriors.game import actions

        self._walk(self._walker(), self.soft)
        self.game.player.skills.set_level("tracker", 6)
        self.assertTrue(actions.read_tracks(self.game))

    def test_your_own_footprints_are_not_a_discovery(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        self._walk(self.game.player, self.soft)
        self.assertEqual(self.tracks.nearby(self.game), [])
        self.assertTrue(self.tracks.nearby(self.game, include_own=True))

    def test_the_look_panel_reports_a_trail(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        self._walk(self._walker(), self.soft)
        self.game.player.skills.set_level("tracker", 8)
        text = " ".join(f.text for f in self.game.describe_tile(*self.soft))
        self.assertIn("tracks", text.lower())

    def test_tracks_survive_a_save(self):
        if self.soft is None:
            self.skipTest("no soft ground nearby")
        from ascii_warriors.game import save as save_mod

        beast = self._walker()
        before = self._walk(beast, self.soft)
        path = save_mod.save_game(self.game, "tracks-test")
        back = save_mod.load_game(path)
        after = self.tracks.readable(back, self.soft)
        self.assertIsNotNone(after)
        self.assertEqual((after.def_id, after.dx, after.dy, after.tick),
                         (before.def_id, before.dx, before.dy, before.tick))
        path.unlink()

    def test_a_save_without_tracks_still_loads(self):
        from ascii_warriors.game.state import Game

        raw = self.game.to_dict()
        del raw["tracks"]
        back = Game.from_dict(raw)
        self.assertEqual(self.tracks.layer(back), {})


class TestStanding(GameFixture):
    """Six ethics per people, finally read by something other than a screen."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import standing

        self.standing = standing

    def _folk(self):
        out = [c for c in self.game.creatures.values()
               if not c.is_player and c.defn.intelligent]
        if not out:
            self.skipTest("nobody intelligent on this map")
        return out

    def _gather(self, n=4):
        """Put some townsfolk where the player can be seen by them."""
        p = self.game.player
        folk = self._folk()[:n]
        for i, c in enumerate(folk):
            c.x, c.y, c.z = p.x + 1 + (i % 2), p.y + (i // 2), p.z
        self.game.update_fov()
        return folk

    def _civ_with(self, key, value):
        for civ in self.world.civs:
            if civ.ethics.get(key) == value:
                return civ
        return None

    # -- the book ---------------------------------------------------------- #

    def test_everybody_starts_indifferent(self):
        for civ in self.world.civs:
            self.assertEqual(self.standing.of(self.game, civ.id), 0)
            self.assertEqual(self.standing.attitude(self.game, civ.id),
                             "unknown")

    def test_standing_is_clamped(self):
        civ = self.world.civs[0]
        book = self.standing.book(self.game)
        book.add(civ.id, 10000)
        self.assertEqual(book.get(civ.id), self.standing.CEILING)
        book.add(civ.id, -100000)
        self.assertEqual(book.get(civ.id), self.standing.FLOOR)

    def test_every_level_has_a_name(self):
        seen = {self.standing.level_name(v)
                for v in range(self.standing.FLOOR, self.standing.CEILING + 1)}
        self.assertEqual(len(seen), len(self.standing.LEVELS))

    # -- ethics decide the cost -------------------------------------------- #

    def test_a_people_who_mind_killing_mind_a_killing(self):
        civ = self._civ_with("killing", "unthinkable")
        if civ is None:
            self.skipTest("no people here minds killing")
        self.assertLess(self.standing.value_of(self.game, civ.id, "murder"),
                        -20)

    def test_a_people_who_do_not_mind_killing_do_not_mind(self):
        civ = self._civ_with("killing", "acceptable")
        if civ is None:
            self.skipTest("everybody here minds killing")
        self.assertEqual(self.standing.value_of(self.game, civ.id, "murder"), 0)

    def test_the_same_murder_costs_different_peoples_differently(self):
        strict = self._civ_with("killing", "unthinkable")
        loose = self._civ_with("killing", "acceptable")
        if strict is None or loose is None:
            self.skipTest("this world agrees about killing")
        self.assertLess(self.standing.value_of(self.game, strict.id, "murder"),
                        self.standing.value_of(self.game, loose.id, "murder"))

    def test_a_people_who_require_theft_think_better_of_a_thief(self):
        civ = self._civ_with("theft", "required")
        if civ is None:
            self.skipTest("nobody here requires theft")
        self.assertGreater(self.standing.value_of(self.game, civ.id, "theft"), 0)

    def test_good_deeds_are_not_weighted_by_ethics(self):
        for civ in self.world.civs:
            self.assertEqual(self.standing.value_of(self.game, civ.id, "quest"),
                             self.standing.DEEDS["quest"][0])

    # -- being seen -------------------------------------------------------- #

    def test_a_murder_in_front_of_people_is_noticed(self):
        folk = self._gather()
        victim = folk[0]
        victim.faction = "town"
        changes = self.standing.on_kill(self.game, victim)
        if not changes:
            self.skipTest("nobody here minds")
        self.assertTrue(any(v < 0 for v in changes.values()))

    def test_a_murder_nobody_saw_costs_nothing(self):
        """v3.6's stealth now hides what you did, not only where you are."""
        folk = self._folk()
        victim = folk[0]
        victim.faction = "town"
        for c in self.game.creatures.values():
            if not c.is_player:
                c.x, c.y, c.z = c.x + 400, c.y + 400, c.z
        self.game.update_fov()
        self.assertEqual(self.standing.on_kill(self.game, victim), {})

    def test_killing_something_hostile_is_not_murder(self):
        folk = self._gather()
        victim = folk[0]
        victim.faction = "hostile"
        self.assertEqual(self.standing.on_kill(self.game, victim), {})

    def test_killing_an_animal_is_nobody_s_business(self):
        beasts = [c for c in self.game.creatures.values()
                  if not c.is_player and not c.defn.intelligent]
        if not beasts:
            self.skipTest("no animals here")
        self.assertEqual(self.standing.on_kill(self.game, beasts[0]), {})

    # -- consequences ------------------------------------------------------ #

    def test_a_people_who_hate_you_turn_on_you(self):
        folk = self._gather()
        cid = self.standing.civ_of(self.game, folk[0])
        if cid is None:
            self.skipTest("these people belong to nobody")
        self.standing.book(self.game).add(cid, self.standing.FLOOR)
        self.standing.enforce(self.game)
        theirs = [c for c in folk
                  if self.standing.civ_of(self.game, c) == cid]
        self.assertTrue(theirs)
        self.assertTrue(all(c.is_hostile_to(self.game.player) for c in theirs))

    def test_a_people_who_like_you_do_not(self):
        folk = self._gather()
        cid = self.standing.civ_of(self.game, folk[0])
        if cid is None:
            self.skipTest("these people belong to nobody")
        self.standing.book(self.game).add(cid, 50)
        self.standing.enforce(self.game)
        theirs = [c for c in folk
                  if self.standing.civ_of(self.game, c) == cid
                  and c.faction not in ("hostile", "wild_hostile")]
        self.assertTrue(all(self.game.player.id not in c.hostile_to
                            for c in theirs))

    def test_standing_moves_prices(self):
        from ascii_warriors.game import trade
        from ascii_warriors.game.item import make_item

        folk = self._gather()
        merchant = folk[0]
        cid = self.standing.civ_of(self.game, merchant)
        if cid is None:
            self.skipTest("this merchant belongs to nobody")
        item = make_item(self.game.rng, "sword")
        neutral = trade.price_to_buy(item, merchant, self.game.player, self.game)
        self.standing.book(self.game).add(cid, self.standing.CEILING)
        liked = trade.price_to_buy(item, merchant, self.game.player, self.game)
        self.assertLess(liked, neutral)

    def test_a_price_without_a_game_is_unchanged(self):
        """Two of the four callers quote a price with no world to hand."""
        from ascii_warriors.game import trade
        from ascii_warriors.game.item import make_item

        merchant = self._folk()[0]
        item = make_item(self.game.rng, "sword")
        self.assertEqual(
            trade.price_to_buy(item, merchant, self.game.player),
            trade.price_to_buy(item, merchant, self.game.player, None))

    def test_a_hated_people_greet_you_accordingly(self):
        from ascii_warriors.game import conversation

        npc = self._folk()[0]
        cid = self.standing.civ_of(self.game, npc)
        if cid is None:
            self.skipTest("this person belongs to nobody")
        self.standing.book(self.game).add(cid, self.standing.FLOOR)
        self.assertIn("Get out", conversation.greeting(npc, self.game))

    # -- peoples disliking each other -------------------------------------- #

    def test_ethical_distance_is_zero_between_a_people_and_itself(self):
        civ = self.world.civs[0]
        self.assertEqual(self.standing.ethical_distance(civ, civ), 0.0)

    def test_peoples_who_disagree_are_further_apart(self):
        by_race = {c.race: c for c in self.world.civs}
        if "elf" not in by_race or "goblin" not in by_race:
            near = [c for c in self.world.civs if c.race in ("dwarf", "human")]
            if len(near) < 2:
                self.skipTest("not enough peoples to compare")
            self.assertLess(
                self.standing.ethical_distance(near[0], near[1]), 0.5)
            return
        far = self.standing.ethical_distance(by_race["elf"], by_race["goblin"])
        self.assertGreater(far, 0.3)

    def test_ethical_distance_stays_in_range(self):
        for a in self.world.civs:
            for b in self.world.civs:
                d = self.standing.ethical_distance(a, b)
                self.assertGreaterEqual(d, 0.0)
                self.assertLessEqual(d, 1.0)

    # -- persistence -------------------------------------------------------- #

    def test_standing_survives_a_save(self):
        from ascii_warriors.game import save as save_mod

        civ = self.world.civs[0]
        self.standing.book(self.game).add(civ.id, -37)
        path = save_mod.save_game(self.game, "standing-test")
        back = save_mod.load_game(path)
        self.assertEqual(self.standing.of(back, civ.id), -37)
        path.unlink()

    def test_a_save_without_standing_still_loads(self):
        from ascii_warriors.game.state import Game

        raw = self.game.to_dict()
        del raw["standing"]
        back = Game.from_dict(raw)
        self.assertEqual(self.standing.book(back).by_civ, {})


class TestVenom(GameFixture):
    """POISON_BITE, finally read by something."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import venom

        self.venom = venom
        self.spider = self._spawn("giant_cave_spider")

    def _spawn(self, def_id):
        from ascii_warriors.game.entity import make_creature

        c = make_creature(self.game.rng, def_id, faction="hostile")
        p = self.game.player
        c.x, c.y, c.z = p.x + 1, p.y, p.z
        self.game.add_creature(c)
        return c

    # -- who carries what -------------------------------------------------- #

    def test_a_venomous_creature_carries_venom(self):
        self.assertEqual(self.venom.carries(self.spider), "spider")

    def test_something_harmless_carries_none(self):
        self.assertIsNone(self.venom.carries(self.game.player))

    def test_every_venomous_creature_maps_to_a_real_venom(self):
        from ascii_warriors.data import creatures as creature_data

        found = 0
        for cid, defn in creature_data.CREATURES.items():
            if not defn.has("POISON_BITE"):
                continue
            found += 1
            kind = self.venom.BY_CREATURE.get(cid, "rot")
            self.assertIn(kind, self.venom.KINDS, cid)
        self.assertGreater(found, 0, "nothing in the data is venomous")

    # -- getting it -------------------------------------------------------- #

    def test_a_bite_envenoms(self):
        from ascii_warriors.game import combat

        p = self.game.player
        for _ in range(80):
            combat.melee_attack(self.spider, p, rng=self.game.rng, log=None)
            if p.venom:
                break
        self.assertTrue(p.venom, "eighty spider bites and no venom")

    def test_venom_does_not_bite_itself(self):
        other = self._spawn("giant_cave_spider")
        self.assertIsNone(self.venom.on_bite(self.spider, other))

    def test_a_second_dose_extends_rather_than_stacks(self):
        p = self.game.player
        first = self.venom.inject(p, "spider")
        self.assertIsNotNone(first)
        was = first.left
        for _ in range(20):
            self.venom.inject(p, "spider")
        self.assertEqual(len(p.venom), 1)
        self.assertGreater(p.venom[0].left, was)
        self.assertLessEqual(p.venom[0].left,
                             int(first.total * self.venom.MAX_EXTEND))

    def test_toughness_and_discipline_shorten_it(self):
        p = self.game.player
        p.skills.set_level("discipline", 0)
        soft = self.venom.resistance(p)
        p.skills.set_level("discipline", 15)
        self.assertGreater(self.venom.resistance(p), soft)
        self.assertLessEqual(self.venom.resistance(p), self.venom.MAX_RESIST)

    def test_resistance_shortens_the_dose(self):
        p = self.game.player
        p.skills.set_level("discipline", 0)
        p.venom = []
        weak = self.venom.inject(p, "scorpion").left
        p.venom = []
        p.skills.set_level("discipline", 18)
        self.assertLess(self.venom.inject(p, "scorpion").left, weak)

    # -- living with it ----------------------------------------------------- #

    def test_venom_waits_before_it_starts(self):
        p = self.game.player
        dose = self.venom.inject(p, "spider")
        self.assertFalse(dose.active)
        self.assertGreater(dose.onset, 0)

    def test_it_announces_itself_when_it_starts(self):
        p = self.game.player
        dose = self.venom.inject(p, "spider")
        msgs = self.venom.tick(p, dose.onset + 1, self.game.rng)
        self.assertTrue(any("heavy" in m for m in msgs), msgs)
        self.assertTrue(dose.active)

    def test_venom_slows_you(self):
        p = self.game.player
        clean = p.effective_speed()
        dose = self.venom.inject(p, "spider")
        dose.onset = 0
        self.assertLess(p.effective_speed(), clean)

    def test_venom_hurts(self):
        p = self.game.player
        dose = self.venom.inject(p, "scorpion")
        dose.onset = 0
        before = p.body.pain
        self.venom.tick(p, 400, self.game.rng)
        self.assertGreater(p.body.pain, before)

    def test_venom_ends(self):
        p = self.game.player
        dose = self.venom.inject(p, "scorpion")
        dose.onset = 0
        msgs = self.venom.tick(p, dose.left + 10, self.game.rng)
        self.assertFalse(p.venom)
        self.assertTrue(any("fades" in m or "passes" in m or "clean" in m
                            for m in msgs), msgs)

    def test_nothing_runs_for_ever(self):
        p = self.game.player
        self.venom.inject(p, "rot")
        for _ in range(400):
            self.venom.tick(p, 100, self.game.rng)
        self.assertFalse(p.venom)

    def test_the_afflicted_list_reads(self):
        p = self.game.player
        dose = self.venom.inject(p, "spider")
        self.assertEqual(self.venom.afflicted(p), [])
        dose.onset = 0
        self.assertEqual(self.venom.afflicted(p), ["spider venom"])

    # -- treating it -------------------------------------------------------- #

    def test_an_untrained_healer_cannot_treat_venom(self):
        p = self.game.player
        self.venom.inject(p, "spider")
        p.skills.set_level("diagnose", 0)
        ok, _said = self.venom.treat(p, p)
        self.assertFalse(ok)

    def test_treating_halves_what_is_left(self):
        p = self.game.player
        dose = self.venom.inject(p, "spider")
        was = dose.left
        p.skills.set_level("diagnose", 6)
        ok, _said = self.venom.treat(p, p)
        self.assertTrue(ok)
        self.assertLess(dose.left, was)
        self.assertTrue(dose.treated)

    def test_treating_a_clean_patient_does_nothing(self):
        p = self.game.player
        p.skills.set_level("diagnose", 6)
        ok, _said = self.venom.treat(p, p)
        self.assertFalse(ok)

    def test_venom_survives_a_save(self):
        from ascii_warriors.game import save as save_mod

        p = self.game.player
        dose = self.venom.inject(p, "scorpion")
        path = save_mod.save_game(self.game, "venom-test")
        back = save_mod.load_game(path)
        self.assertEqual(len(back.player.venom), 1)
        self.assertEqual((back.player.venom[0].kind, back.player.venom[0].left),
                         (dose.kind, dose.left))
        path.unlink()


class TestWebs(GameFixture):
    """WEBBER and the `web` tile, joined up at last."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import webs

        self.webs = webs
        self.spider = self._spawn("giant_cave_spider")
        self.here = (self.game.player.x, self.game.player.y,
                     self.game.player.z)

    def _spawn(self, def_id):
        from ascii_warriors.game.entity import make_creature

        c = make_creature(self.game.rng, def_id, faction="hostile")
        p = self.game.player
        c.x, c.y, c.z = p.x + 1, p.y, p.z
        self.game.add_creature(c)
        return c

    def test_a_spinner_spins(self):
        self.assertTrue(self.webs.spins(self.spider))
        self.assertFalse(self.webs.spins(self.game.player))

    def test_a_web_can_be_laid(self):
        self.assertTrue(self.webs.spin(self.game, self.spider, self.here))
        self.assertTrue(self.webs.is_web(self.game, self.here))

    def test_a_web_cannot_be_laid_twice(self):
        self.webs.spin(self.game, self.spider, self.here)
        self.assertFalse(self.webs.spin(self.game, self.spider, self.here))

    def test_a_web_catches_you(self):
        self.webs.spin(self.game, self.spider, self.here)
        self.assertTrue(self.webs.caught(self.game, self.game.player))

    def test_a_spinner_walks_its_own_web(self):
        self.webs.spin(self.game, self.spider, self.here)
        self.spider.x, self.spider.y, self.spider.z = self.here
        self.assertFalse(self.webs.caught(self.game, self.spider))

    def test_struggling_always_tears_something(self):
        self.webs.spin(self.game, self.spider, self.here)
        before = self.webs.strength_at(self.game, self.here)
        self.webs.struggle(self.game, self.game.player, self.game.rng)
        self.assertLess(self.webs.strength_at(self.game, self.here), before)

    def test_nobody_is_stuck_for_ever(self):
        """Even the weakest creature tears MIN_TEAR away every try."""
        self.webs.spin(self.game, self.spider, self.here)
        p = self.game.player
        for _ in range(self.webs.STRENGTH // self.webs.MIN_TEAR + 2):
            free, _said = self.webs.struggle(self.game, p, self.game.rng)
            if free:
                break
        self.assertFalse(self.webs.caught(self.game, p))

    def test_tearing_free_clears_the_tile(self):
        self.webs.spin(self.game, self.spider, self.here)
        p = self.game.player
        for _ in range(20):
            free, _said = self.webs.struggle(self.game, p, self.game.rng)
            if free:
                break
        self.assertFalse(self.webs.is_web(self.game, self.here))

    def test_a_stuck_player_struggles_instead_of_walking(self):
        from ascii_warriors.game import actions

        self.webs.spin(self.game, self.spider, self.here)
        p = self.game.player
        was = (p.x, p.y, p.z)
        actions.move_or_attack(self.game, 0, 1)
        self.assertEqual((p.x, p.y, p.z), was)

    def test_a_spinner_throws_one_eventually(self):
        cells = []
        for _ in range(400):
            self.game.scheduler.ticks += self.webs.COOLDOWN
            cell = self.webs.maybe_spin(self.game, self.spider,
                                        self.game.player, self.game.rng)
            if cell is not None:
                cells.append(cell)
        self.assertTrue(cells, "a spider never spun in four hundred tries")

    def test_a_spinner_will_not_reach_across_the_map(self):
        self.spider.x += 60
        self.game.scheduler.ticks += self.webs.COOLDOWN * 2
        self.assertIsNone(self.webs.maybe_spin(
            self.game, self.spider, self.game.player, self.game.rng))

    def test_webs_survive_a_save(self):
        from ascii_warriors.game import save as save_mod

        self.webs.spin(self.game, self.spider, self.here)
        self.webs.strands(self.game)[self.here] = 42
        path = save_mod.save_game(self.game, "web-test")
        back = save_mod.load_game(path)
        self.assertEqual(self.webs.strength_at(back, self.here), 42)
        path.unlink()


class TestMounts(GameFixture):
    """The last dead skill in the table, and the flags that go with it."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import mounts

        self.mounts = mounts
        self.horse = self._spawn("horse")

    def _spawn(self, def_id, faction="wild"):
        """Put one animal beside the player, and nothing else.

        The tile east of the player was assumed empty and is not always: what
        else the map generator put there is a property of the seed, and a
        wandering troll standing on it is what `ride_or_dismount` then found
        when it looked for an animal to get on. Cleared and placed rather than
        hoped for.
        """
        from ascii_warriors.game.entity import make_creature

        p = self.game.player
        near = [(p.x + dx, p.y + dy, p.z)
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if not (dx == 0 and dy == 0)]
        for other in list(self.game.creatures.values()):
            if other is not p and (other.x, other.y, other.z) in near:
                self.game.creatures.pop(other.id, None)
                self.game.scheduler.remove(other.id)
        c = make_creature(self.game.rng, def_id, faction=faction)
        spot = next((cell for cell in near
                     if self.game.local.walkable(*cell)), near[0])
        c.x, c.y, c.z = spot
        self.game.add_creature(c)
        return c

    def _tamed(self):
        self.horse.tame = True
        self.horse.faction = "player"
        return self.horse

    # -- the flags --------------------------------------------------------- #

    def test_a_horse_is_a_mount(self):
        self.assertTrue(self.mounts.is_mount(self.horse))
        self.assertTrue(self.mounts.is_trainable(self.horse))

    def test_a_person_is_not_tameable(self):
        self.assertFalse(self.mounts.is_trainable(self.game.player))

    def test_every_mount_in_the_data_is_trainable(self):
        from ascii_warriors.data import creatures as creature_data

        found = 0
        for _cid, defn in creature_data.CREATURES.items():
            if not defn.has("MOUNT"):
                continue
            found += 1
            self.assertTrue(defn.has("TRAINABLE"),
                            "%s can be ridden but never tamed" % defn.name)
        self.assertGreater(found, 0, "nothing in the data is rideable")

    # -- taming ------------------------------------------------------------ #

    def test_a_wild_animal_is_harder_to_tame(self):
        p = self.game.player
        p.skills.set_level("rider", 8)
        self.horse.faction = "wild"
        wild = self.mounts.tame_chance(p, self.horse)
        self.horse.faction = "town"
        self.assertGreater(self.mounts.tame_chance(p, self.horse), wild)

    def test_skill_makes_taming_likelier(self):
        p = self.game.player
        p.skills.set_level("rider", 0)
        poor = self.mounts.tame_chance(p, self.horse)
        p.skills.set_level("rider", 15)
        self.assertGreater(self.mounts.tame_chance(p, self.horse), poor)

    def test_taming_works_eventually(self):
        p = self.game.player
        p.skills.set_level("rider", 12)
        for _ in range(40):
            ok, _said = self.mounts.tame(self.game, self.horse, self.game.rng)
            if ok:
                break
        self.assertTrue(self.horse.tame)
        self.assertEqual(self.horse.faction, "player")

    def test_a_refusal_makes_the_next_try_harder(self):
        p = self.game.player
        p.skills.set_level("rider", 0)
        for _ in range(4):
            self.mounts.tame(self.game, self.horse, self.game.rng)
        self.assertGreater(self.horse.tame_tries, 0)

    def test_you_cannot_tame_what_is_already_yours(self):
        self._tamed()
        ok, _said = self.mounts.tame(self.game, self.horse, self.game.rng)
        self.assertFalse(ok)

    # -- riding ------------------------------------------------------------ #

    def test_you_cannot_ride_an_untamed_animal(self):
        ok, why = self.mounts.can_ride(self.game, self.horse)
        self.assertFalse(ok)
        self.assertIn("Tame", why)

    def test_you_cannot_ride_something_that_is_not_a_mount(self):
        dog = self._spawn("dog")
        dog.tame = True
        ok, _why = self.mounts.can_ride(self.game, dog)
        self.assertFalse(ok)

    def test_riding_takes_the_mount_off_the_map(self):
        horse = self._tamed()
        ok, _said = self.mounts.ride(self.game, horse)
        self.assertTrue(ok)
        self.assertNotIn(horse.id, self.game.creatures)
        self.assertIs(self.game.player.mount, horse)

    def test_dismounting_puts_it_back(self):
        horse = self._tamed()
        self.mounts.ride(self.game, horse)
        ok, _said = self.mounts.dismount(self.game)
        self.assertTrue(ok)
        self.assertIn(horse.id, self.game.creatures)
        self.assertIsNone(self.game.player.mount)

    def test_you_cannot_ride_two_things(self):
        horse = self._tamed()
        self.mounts.ride(self.game, horse)
        other = self._spawn("horse")
        other.tame = True
        ok, _why = self.mounts.can_ride(self.game, other)
        self.assertFalse(ok)

    def test_a_mount_is_faster_than_your_legs(self):
        p = self.game.player
        on_foot = p.effective_speed()
        self.mounts.ride(self.game, self._tamed())
        self.assertGreater(p.effective_speed(), on_foot)

    def test_a_mount_carries_for_you(self):
        p = self.game.player
        self.mounts.ride(self.game, self._tamed())
        self.assertGreater(self.mounts.carry_bonus(self.game), 1.0)

    def test_a_mount_makes_the_world_smaller(self):
        self.assertEqual(self.mounts.travel_factor(self.game), 1.0)
        self.mounts.ride(self.game, self._tamed())
        self.assertLess(self.mounts.travel_factor(self.game), 1.0)

    # -- staying on -------------------------------------------------------- #

    def test_skill_keeps_you_on(self):
        p = self.game.player
        p.skills.set_level("rider", 0)
        poor = self.mounts.seat_chance(p)
        p.skills.set_level("rider", 18)
        best = self.mounts.seat_chance(p)
        self.assertGreater(best, poor)
        self.assertLessEqual(best, self.mounts.SEAT_MAX)

    def test_a_scratch_does_not_unseat_anybody(self):
        self.mounts.ride(self.game, self._tamed())
        self.assertIsNone(self.mounts.on_hit(
            self.game, self.mounts.UNSEAT_THRESHOLD - 1, self.game.rng))
        self.assertTrue(self.mounts.mounted(self.game))

    def test_a_solid_hit_eventually_unseats_the_untrained(self):
        p = self.game.player
        p.skills.set_level("rider", 0)
        self.mounts.ride(self.game, self._tamed())
        for _ in range(40):
            said = self.mounts.on_hit(self.game, 60000, self.game.rng)
            if said:
                break
        self.assertFalse(self.mounts.mounted(self.game))
        self.assertIn(self.horse.id, self.game.creatures)

    def test_falling_off_is_never_asked_of_somebody_on_foot(self):
        self.assertIsNone(self.mounts.on_hit(self.game, 999999, self.game.rng))

    def test_the_status_line_says_so(self):
        self.assertEqual(self.mounts.status(self.game), "")
        self.mounts.ride(self.game, self._tamed())
        self.assertIn("riding", self.mounts.status(self.game))

    # -- the player's side and persistence --------------------------------- #

    def test_the_ride_key_mounts_and_dismounts(self):
        from ascii_warriors.game import actions

        self._tamed()
        actions.ride_or_dismount(self.game)
        self.assertTrue(self.mounts.mounted(self.game))
        actions.ride_or_dismount(self.game)
        self.assertFalse(self.mounts.mounted(self.game))

    def test_taming_by_key_finds_the_animal_beside_you(self):
        from ascii_warriors.game import actions

        self.game.player.skills.set_level("rider", 14)
        for _ in range(40):
            actions.tame_animal(self.game)
            if self.horse.tame:
                break
        self.assertTrue(self.horse.tame)

    def test_a_mount_survives_a_save(self):
        from ascii_warriors.game import save as save_mod

        horse = self._tamed()
        self.mounts.ride(self.game, horse)
        path = save_mod.save_game(self.game, "mount-test")
        back = save_mod.load_game(path)
        self.assertIsNotNone(back.player.mount)
        self.assertEqual(back.player.mount.def_id, "horse")
        self.assertTrue(back.player.mount.tame)
        path.unlink()

    def test_a_tamed_animal_survives_a_save(self):
        from ascii_warriors.game import save as save_mod

        self._tamed()
        self.horse.tame_tries = 3
        path = save_mod.save_game(self.game, "tame-test")
        back = save_mod.load_game(path)
        theirs = [c for c in back.creatures.values()
                  if c.def_id == "horse"]
        self.assertTrue(theirs)
        self.assertTrue(theirs[0].tame)
        self.assertEqual(theirs[0].tame_tries, 3)
        path.unlink()


class TestWhoTheDragonsAre(GameFixture):
    """A megabeast is somebody, not something you meet on the way to the shops.

    v3.52 gave a named megabeast a lair, pointed the quest at it, and made
    killing it write a date into the histories. Then a survey of the
    wilderness found the point of all that quietly undone: eight named
    megabeasts in the whole world against fifteen nameless ones inside
    forty-four tiles of the player's doorstep, five of them bronze colossi.

    `spawn_wildlife` asked `spawnable` for anything up to tier five with no
    flags excluded. The fortress has excluded megabeasts since it had wildlife
    at all -- "wildlife, not enemies" -- and adventure mode had never been
    told.
    """

    def _wild(self, tiles=12):
        """Walk some wilderness and return everything met on the way."""
        met = []
        world = self.world
        px, py = self.game.player.wx, self.game.player.wy
        walked = 0
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if walked >= tiles:
                    break
                wx, wy = px + dx, py + dy
                if not (0 <= wx < world.width and 0 <= wy < world.height):
                    continue
                if world.tile(wx, wy).is_ocean:
                    continue
                if any((s.wx, s.wy) == (wx, wy) for s in world.sites):
                    continue
                self.game.enter_world_tile(wx, wy)
                walked += 1
                met.extend(c for c in self.game.creatures.values()
                           if not c.is_player)
        self.assertGreater(walked, 4, "hardly any wilderness to walk")
        return met

    def test_the_wilderness_hands_out_no_megabeasts(self):
        """The rule, in the half of the game that did not have it."""
        loose = [c.def_id for c in self._wild()
                 if c.hf_id is None
                 and (c.defn.has("MEGABEAST") or c.defn.has("SEMIMEGABEAST"))]
        self.assertEqual(loose, [], "nameless megabeasts in the wild")

    def test_the_wilderness_is_still_worth_walking_through(self):
        """The other half: a rule that empties the world is not a fix.

        Measured across thirty-five tiles, thirty-eight species survive the
        exclusion -- wolves, trolls, night trolls, werewolves and all -- and
        only one tile in thirty-five comes out empty.
        """
        met = self._wild()
        self.assertGreater(len(met), 20, "the wild came out empty")
        self.assertGreater(len({c.def_id for c in met}), 6,
                           "the wild came out monotonous")

    def test_both_halves_of_the_game_agree_about_megabeasts(self):
        """Named in each, so they cannot drift apart in silence again.

        The fortress had the rule written into the middle of a call and
        adventure mode had no rule at all, which is a disagreement nothing
        could see. Both are constants now, and this fails if either forgets.
        """
        from ascii_warriors.fortress import animals

        for flag in ("MEGABEAST", "SEMIMEGABEAST"):
            self.assertIn(flag, Game.WILD_NEVER, "adventure mode forgot %s" % flag)
            self.assertIn(flag, animals.WILD_NEVER,
                          "the fortress forgot %s" % flag)

    def test_a_named_beast_is_still_in_its_lair(self):
        """Excluding them from the wild must not exclude them from the game."""
        from ascii_warriors.world.localmap import generate_local

        beasts = [f for f in self.world.figures.values()
                  if "monster" in f.flags and f.alive(self.world.year)]
        if not beasts:
            self.skipTest("this small world has no living megabeast")
        fig = beasts[0]
        site = next((s for s in self.world.sites if s.id == fig.site_id), None)
        self.assertIsNotNone(site)
        _lm, pop = generate_local(self.world, site.wx, site.wy,
                                  RNG("lair"), site=site)
        self.assertTrue(any(spec.get("hf_id") == fig.id for spec in pop),
                        "the named beast went out with the wildlife")


class TestRecoveringTheArtifact(unittest.TestCase):
    """The last quest kind nobody could finish.

    The histories forge artifacts, name them, and remember which site each one
    ended up at. `_quest_retrieve` sends you after one by name -- "It lies at
    Blood Grave, a tomb" -- and `quests.on_pickup` matches on
    `Item.artifact_id`. That field was read, copied and saved, and written
    nowhere: `sitegen` had never heard of artifacts, so the tomb was empty and
    the quest could be accepted, walked to, and never completed.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _quest(self, seed):
        """A game, and the first retrieve quest anybody offers in it."""
        from ascii_warriors.game import quests
        from ascii_warriors.world.worldgen import generate_world

        rng = RNG(seed)
        world = generate_world(rng.sub("w"), size="small", history_years=150)
        game = Game.new_game(
            world, {"race": "human", "profession": "warrior"}, rng)
        for giver in [c for c in game.creatures.values()
                      if c.defn.has("CAN_SPEAK") and not c.is_player][:80]:
            q = quests.generate_quest(game.rng, game, giver)
            if q is not None and q.kind == "retrieve_artifact":
                game.quests.accept(q)
                return game, q
        return game, None

    def _bring_to_ground(self, game, artifact_id):
        """Get the thing onto the floor, however it is being kept.

        Loose on some worlds and in a monster's claws on others, and which is
        a property of the seed: excluding megabeasts from the wilderness moved
        the world's dice and turned one into the other under two tests that
        had assumed the floor. Killing the holder is what a player does about
        it, and it drops what it was carrying.
        """
        loose, held = self._find(game, artifact_id)
        if loose:
            return loose[0][0]
        self.assertTrue(held, "the artifact is nowhere on this map")
        holder = held[0][0]
        holder.body.dead = True
        holder.body.death_cause = "slain"
        game.kill_creature(holder)
        loose, _held = self._find(game, artifact_id)
        self.assertTrue(loose, "it did not drop what it was carrying")
        return loose[0][0]

    def _find(self, game, artifact_id):
        """Wherever the thing has got to on this map."""
        loose = [(cell, it) for cell, items in game.items_on_ground.items()
                 for it in items
                 if getattr(it, "artifact_id", None) == artifact_id]
        held = [(c, it) for c in game.creatures.values()
                for it in c.inventory.items
                if getattr(it, "artifact_id", None) == artifact_id]
        return loose, held

    def test_the_artifact_is_at_the_site_the_quest_names(self):
        """On three worlds, because one is a coincidence."""
        checked = 0
        for seed in ("art1", "art2", "art3"):
            game, q = self._quest(seed)
            if q is None:
                continue
            game.enter_world_tile(q.wx, q.wy)
            loose, held = self._find(game, q.artifact_id)
            self.assertTrue(loose or held,
                            "%s: the artifact is not where it is said to be"
                            % seed)
            checked += 1
        self.assertGreater(checked, 1, "hardly any retrieve quests offered")

    def test_it_is_the_artifact_the_histories_describe(self):
        """Right item, right material, and its own name on it."""
        game, q = self._quest("art1")
        self.assertIsNotNone(q)
        game.enter_world_tile(q.wx, q.wy)
        loose, held = self._find(game, q.artifact_id)
        it = (loose[0][1] if loose else held[0][1])
        art = next(a for a in game.world.artifacts if a.id == q.artifact_id)
        self.assertEqual(it.def_id, art.item_def)
        self.assertEqual(it.material, art.material)
        self.assertIn(art.name, it.name())

    def test_picking_it_up_finishes_the_quest(self):
        """`on_pickup` has always been wired. It never had anything to fire on."""
        from ascii_warriors.game import actions

        game, q = self._quest("art1")
        self.assertIsNotNone(q)
        game.enter_world_tile(q.wx, q.wy)
        cell = self._bring_to_ground(game, q.artifact_id)
        game.player.x, game.player.y, game.player.z = cell
        actions.pick_up_all(game)
        self.assertTrue(any(getattr(i, "artifact_id", None) == q.artifact_id
                            for i in game.player.inventory.items))
        self.assertGreaterEqual(q.progress, q.goal, "the pickup did not count")
        if q.state != "done":
            self.assertTrue(game.quests.turn_in(game, q.giver_hf))
        self.assertEqual(q.state, "done")

    def test_it_is_not_lying_there_again_when_you_come_back(self):
        """The map cache holds twenty-four tiles and then evicts.

        Without a guard, the crown you are wearing is back on the floor of the
        tomb you took it from, as often as you care to walk back.
        """
        from ascii_warriors.game import actions

        game, q = self._quest("art1")
        self.assertIsNotNone(q)
        game.enter_world_tile(q.wx, q.wy)
        cell = self._bring_to_ground(game, q.artifact_id)
        game.player.x, game.player.y, game.player.z = cell
        actions.pick_up_all(game)
        # Away first, then forget, then back. `enter_world_tile` stashes the
        # map it is leaving into the cache before it loads the next one, so
        # clearing the cache and re-entering the tile you are standing on just
        # reads back what you were told to forget -- which is why the first
        # version of this passed with the guard deleted.
        away = (q.wx + 1, q.wy) if q.wx + 1 < game.world.width else (q.wx - 1, q.wy)
        game.enter_world_tile(*away)
        game._local_cache.clear()
        game._cache_order.clear()
        game.enter_world_tile(q.wx, q.wy)
        again, _held2 = self._find(game, q.artifact_id)
        self.assertEqual(again, [], "a second one was left on the floor")
        self.assertEqual(
            sum(1 for i in game.player.inventory.items
                if getattr(i, "artifact_id", None) == q.artifact_id), 1)

    def test_a_site_with_no_artifact_gets_none(self):
        """The placer must not invent them."""
        from ascii_warriors.game import artifacts as artifact_mod
        from ascii_warriors.world.worldgen import generate_world

        rng = RNG("bare")
        world = generate_world(rng.sub("w"), size="small", history_years=150)
        placed = {a.site_id for a in world.artifacts}
        spare = next((s for s in world.sites if s.id not in placed), None)
        self.assertIsNotNone(spare, "every site in the world holds an artifact")
        self.assertEqual(artifact_mod.at_site(world, spare.id), [])


class TestSlayingTheBeast(unittest.TestCase):
    """A quest that could not be finished, end to end.

    "Every quest points at something that exists" is the README's promise, and
    every target did exist. None of them was there. The chain from a name in
    the histories to a body on the floor had a gap in the middle of it, and
    this walks the whole thing: take the quest, go where it sends you, kill
    what it names, and be paid.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _quest(self, seed):
        """A game, and the first slay-the-beast quest anybody offers in it."""
        from ascii_warriors.game import quests
        from ascii_warriors.world.worldgen import generate_world

        rng = RNG(seed)
        world = generate_world(rng.sub("w"), size="small", history_years=150)
        game = Game.new_game(
            world, {"race": "human", "profession": "warrior"}, rng)
        givers = [c for c in game.creatures.values()
                  if c.defn.has("CAN_SPEAK") and not c.is_player]
        for giver in givers[:80]:
            q = quests.generate_quest(game.rng, game, giver)
            if q is not None and q.kind == "slay_beast":
                game.quests.accept(q)
                return game, q
        return game, None

    def test_the_quest_sends_you_to_the_beasts_own_lair(self):
        """Not `rng.choice(lairs)`, which is what it used to be.

        Across several worlds, because a cave picked at random is sometimes
        the right cave: on one world the old rule passed this by luck.
        """
        checked = 0
        for seed in ("slay1", "slay2", "slay3", "slay4"):
            game, q = self._quest(seed)
            if q is None:
                continue
            fig = game.world.figures.get(q.target_hf)
            self.assertIsNotNone(fig)
            self.assertIsNotNone(fig.site_id,
                                 "%s: the beast lairs nowhere" % seed)
            self.assertEqual(q.site_id, fig.site_id,
                             "%s: sent where the beast does not live" % seed)
            checked += 1
        self.assertGreater(checked, 1, "hardly any slay quests were offered")

    def test_the_beast_is_there_when_you_arrive(self):
        """The half that was missing, on three worlds rather than one."""
        for seed in ("slay1", "slay2", "slay3"):
            game, q = self._quest(seed)
            if q is None:
                continue
            game.enter_world_tile(q.wx, q.wy)
            quarry = [c for c in game.creatures.values()
                      if c.hf_id == q.target_hf and not c.body.dead]
            self.assertEqual(len(quarry), 1,
                             "%s: the beast is not at its lair" % seed)
            fig = game.world.figures.get(q.target_hf)
            self.assertEqual(quarry[0].def_id, fig.creature_id,
                             "%s: wrong species waiting" % seed)

    def test_killing_it_finishes_the_quest_and_the_figure(self):
        """And the world remembers, which is what the legends are for."""
        game, q = self._quest("slay1")
        self.assertIsNotNone(q)
        game.enter_world_tile(q.wx, q.wy)
        beast = next(c for c in game.creatures.values()
                     if c.hf_id == q.target_hf)
        beast.body.dead = True
        beast.body.death_cause = "slain"
        game.kill_creature(beast)
        self.assertGreaterEqual(q.progress, q.goal, "the kill did not count")
        if q.state != "done":
            # A quest with a giver is reported back rather than closing itself.
            self.assertTrue(game.quests.turn_in(game, q.giver_hf))
        self.assertEqual(q.state, "done")
        fig = game.world.figures.get(q.target_hf)
        self.assertIsNotNone(fig.died, "the histories never heard about it")
        self.assertIn("slain", fig.death_cause)

    def test_the_lair_survives_a_save(self):
        """Where a beast lives is world state, and worlds get written down."""
        from ascii_warriors.world.worldgen import World, generate_world

        world = generate_world(RNG("saved").sub("w"), size="small",
                               history_years=150)
        beasts = [f for f in world.figures.values()
                  if "monster" in f.flags and f.alive(world.year)]
        self.assertTrue(beasts)
        again = World.from_dict(json.loads(json.dumps(world.to_dict())))
        for fig in beasts:
            self.assertEqual(again.figures[fig.id].site_id, fig.site_id)


class TestPlayingTheAdventure(GameFixture):
    """The clock an adventurer lives on, and the driver that measures it.

    The fortress has been audited by simulating a year and looking at the
    wreckage since v3.46, and five defects came out of it. Adventure mode had
    no equivalent: `smoke` proves the screens fit together and `fuzz` presses
    keys at random, and neither of them plays. `tools/play` does, and these
    pin the things it depends on being true.
    """

    def _turns(self, n, cost=None):
        """Take *n* ordinary turns the way the play screen does.

        With the map cleared of anything hostile first. A test about the clock
        that shares a hamlet with a troll measures how long the player lasts,
        because `player_acts` does nothing once the game is over -- which is
        how this came to read 81 ticks out of 200 the moment an unrelated
        change moved the world's dice.
        """
        for other in list(self.game.creatures.values()):
            if other is not self.game.player and other.faction == "hostile":
                self.game.creatures.pop(other.id, None)
                self.game.scheduler.remove(other.id)
        for _ in range(n):
            self.assertFalse(self.game.game_over, "the run ended early")
            self.game.player_acts(cost or actions.wait(self.game))

    def test_an_action_moves_the_world_clock(self):
        """`player_acts` is the whole of it.

        Calling an action function and then `advance()` looks like taking a
        turn and is not: nothing has charged the player its energy, so the
        scheduler hands the turn straight back and the world barely moves.
        Two hundred turns driven that way advanced the clock by two ticks
        instead of two hundred, and an adventurer on that clock would need
        four million turns to get thirsty. It was a probe that did this rather
        than the game, and the probe looked exactly like a discovery.
        """
        p = self.game.player
        before = p.needs.thirst
        self._turns(200)
        self.assertGreaterEqual(p.needs.thirst - before, 150,
                                "two hundred turns barely moved the clock")

    def test_needs_reach_the_thresholds_that_matter(self):
        """Thirst has to be able to become urgent, or nothing below it runs."""
        from ascii_warriors.game import feeding

        p = self.game.player
        p.needs.thirst = feeding.THIRSTY_AT - 60
        self._turns(120)
        self.assertGreater(p.needs.thirst, feeding.THIRSTY_AT)

    def test_you_can_drink_from_the_water_you_are_standing_in(self):
        """The fortress's thirst bug, asked of the other mode."""
        p = self.game.player
        self.game.local.set_tile(p.x + 1, p.y, p.z, "shallow_water")
        p.needs.thirst = 30000
        self.assertTrue(actions.water_source_near(self.game))
        self.assertGreater(actions.drink(self.game), 0)
        self.assertEqual(p.needs.thirst, 0)

    def test_drinking_from_a_river_needs_a_river(self):
        """And the other half, or the guard above passes anywhere."""
        p = self.game.player
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                self.game.local.set_tile(p.x + dx, p.y + dy, p.z, "grass")
        for item in list(p.inventory.items):
            if item.is_drink:
                p.inventory.items.remove(item)
        p.needs.thirst = 30000
        self.assertFalse(actions.water_source_near(self.game))
        actions.drink(self.game)
        self.assertEqual(p.needs.thirst, 30000, "it drank from dry grass")

    def test_a_waterskin_is_what_carries_the_water(self):
        """`refill_waterskins` invents water, so what it invents is the point.

        Both directions, because only one of them can fail. The explicit
        "no skins, no water" guard in the function is unreachable: with no
        skin the capacity is zero and the `have >= capacity` line returns
        zero anyway, so deleting the check changes nothing. What is worth
        pinning is that a skin holds four and a second skin holds four more.
        """
        p = self.game.player
        for item in list(p.inventory.by_def("waterskin")):
            p.inventory.items.remove(item)
        for item in list(p.inventory.by_def("water_drink")):
            p.inventory.items.remove(item)
        self.assertEqual(actions.refill_waterskins(self.game), 0)
        self.assertEqual(p.inventory.count_of("water_drink"), 0)
        p.inventory.add(Item("waterskin", "leather"))
        self.assertEqual(actions.refill_waterskins(self.game), 4)
        self.assertEqual(p.inventory.count_of("water_drink"), 4)
        self.assertEqual(actions.refill_waterskins(self.game), 0,
                         "a full skin filled again")

    def test_the_world_an_adventurer_walks_into_is_populated(self):
        """A map with nothing on it makes every other measurement meaningless."""
        others = [c for c in self.game.creatures.values() if not c.is_player]
        self.assertGreater(len(others), 4, "the world is empty")

    def test_the_play_driver_looks_after_the_character(self):
        """The tool is only worth having if it plays rather than presses keys.

        Driven at a character that is already parched, so `_look_after` has
        to fire: a short run on a quiet map never reaches a threshold, which
        is why the first version of this passed with the whole needs branch
        deleted.
        """
        from tools import play

        why = collections.Counter()
        p = self.game.player
        self.game.local.set_tile(p.x + 1, p.y, p.z, "shallow_water")
        p.needs.thirst = play.THIRSTY + 5000
        cost = play._look_after(self.game, why)
        self.assertIsNotNone(cost, "it ignored a parched character")
        self.assertEqual(p.needs.thirst, 0)
        # Either counter is the same act: standing at water it fills the skin
        # as well, which is what it is for, and drinking from the source is
        # what sets the thirst to nothing.
        self.assertEqual(why["drank"] + why["filled the skin"], 1)

    def test_it_tears_up_a_shirt_when_the_bandages_are_gone(self):
        """The last thing between an adventurer and bleeding to death.

        Measured over twenty-four runs before this: bleeding was the *only*
        cause of death, twenty-one of twenty-one, and the driver counted
        "bleeding, and nothing to bind it with" while wearing four bandages'
        worth of clothing.
        """
        from ascii_warriors.game import body as body_mod
        from tools import play

        why = collections.Counter()
        p = self.game.player
        for it in list(p.inventory.by_def("bandage")):
            p.inventory.items.remove(it)
        self.assertTrue([i for i in p.inventory.items
                         if i.category == "clothing"], "nothing to tear up")
        part = p.body.part("upper_body")
        part.wounds.append(body_mod.Wound(part.id, "skin", 0.5, "cut", 8, 5))
        p.body.blood = p.body.max_blood * (play.PATCH_UP_AT - 0.05)
        cost = play._staunch(self.game, why)
        self.assertIsNotNone(cost, "it bled with a shirt on its back")
        self.assertEqual(why["tore up a shirt"], 1)
        self.assertEqual(why["bleeding, and nothing to bind it with"], 0)
        self.assertGreater(p.inventory.count_of("bandage"), 0)

    def test_it_says_so_when_there_is_nothing_left_to_tear(self):
        """The other half of the branch, or the counter above proves nothing."""
        from ascii_warriors.game import body as body_mod
        from tools import play

        why = collections.Counter()
        p = self.game.player
        for it in list(p.inventory.items):
            if it.def_id == "bandage" or it.category == "clothing":
                p.inventory.items.remove(it)
        part = p.body.part("upper_body")
        part.wounds.append(body_mod.Wound(part.id, "skin", 0.5, "cut", 8, 5))
        p.body.blood = p.body.max_blood * (play.PATCH_UP_AT - 0.05)
        self.assertIsNone(play._staunch(self.game, why))
        self.assertEqual(why["bleeding, and nothing to bind it with"], 1)

    def test_it_fills_the_skin_at_the_water_rather_than_at_the_next_desert(self):
        """It drank when parched and never otherwise, so it walked past three
        rivers with a half-full skin and died of thirst twice in ten runs."""
        from tools import play

        why = collections.Counter()
        p = self.game.player
        self.game.local.set_tile(p.x + 1, p.y, p.z, "shallow_water")
        p.needs.thirst = 0
        for it in list(p.inventory.items):
            if it.def_id == "water_drink":
                p.inventory.items.remove(it)
        self.assertTrue(p.inventory.by_def("waterskin"))
        self.assertIsNotNone(play._look_after(self.game, why))
        self.assertEqual(why["filled the skin"], 1)
        self.assertGreater(p.inventory.count_of("water_drink"), 0)

    def test_it_takes_the_bandage_off_what_it_killed(self):
        """Everybody in the world carries one since v3.63 and it falls to the
        floor when they do; the driver walked over all of it and spent 95
        turns in one run with nothing to bind a wound with."""
        from ascii_warriors.game.item import Item
        from tools import play

        why = collections.Counter()
        game, p = self.game, self.game.player
        for c in list(game.creatures.values()):
            if not c.is_player:
                game.remove_creature(c)
        for it in list(p.inventory.items):
            if it.def_id == "bandage":
                p.inventory.items.remove(it)
        game.drop_item(Item("bandage", "pig_tail_cloth"), p.x, p.y, p.z)
        self.assertIsNotNone(play._loot(game, why))
        self.assertEqual(why["took what it needed"], 1)
        self.assertTrue(p.inventory.by_def("bandage"))

    def test_it_follows_the_route_rather_than_the_bearing(self):
        """Walking greedily at the goal left it hemmed in by a coastline for
        3999 turns out of 4000, three runs in ten."""
        from tools import play

        why = collections.Counter()
        game, p = self.game, self.game.player
        for c in list(game.creatures.values()):
            if not c.is_player:
                game.remove_creature(c)
        town = next((s for s in self.world.sites if s.is_settlement
                     and (s.wx, s.wy) != (p.wx, p.wy)
                     and game.route_overland(s.wx, s.wy)), None)
        self.assertIsNotNone(town, "nowhere to walk to")
        wanted = game.route_overland(town.wx, town.wy)[1]
        self.assertIsNotNone(play._travel_toward(game, town.wx, town.wy, why))
        self.assertEqual((p.wx, p.wy), wanted)
        self.assertEqual(why["travelled"], 1)

    def test_the_play_driver_runs_and_reports(self):
        """And it has to come back with numbers, not just print them."""
        from tools import play

        out = play.play("harness", 120, size="pocket", history=10,
                        report=lambda *a: None)
        self.assertEqual(out["seed"], "harness")
        self.assertGreater(out["peak"]["thirst"], 0,
                           "the driver never moved the clock")
        self.assertLessEqual(out["turns"], 120)

    def test_an_action_that_did_not_happen_does_not_claim_the_turn(self):
        """It spent 3971 of 4000 turns pressing "drink" with nothing to
        drink and reported the run as fine."""
        from tools import play

        why = collections.Counter()
        p = self.game.player
        for it in list(p.inventory.items):
            if it.is_drink:
                p.inventory.items.remove(it)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                self.game.local.set_tile(p.x + dx, p.y + dy, p.z, "floor")
        p.needs.thirst = play.THIRSTY + 5000
        p.needs.drowsy = 0
        cost = play._look_after(self.game, why)
        self.assertIsNone(cost, "a failed drink was billed as a turn")
        self.assertEqual(why["nothing to drink"], 1)

    def test_the_driver_can_hit_an_animal(self):
        """`_adjacent_foe` asked `faction == "hostile"` since v3.51, and a
        wolf's faction is "wild": a wolf could chew through an adventurer who
        never swung back."""
        from ascii_warriors.game.entity import make_creature
        from tools import play

        p = self.game.player
        wolf = make_creature(self.game.rng, "wolf", faction="wild")
        wolf.x, wolf.y, wolf.z = p.x + 1, p.y, p.z
        self.game.add_creature(wolf)
        self.assertTrue(wolf.is_hostile_to(p))
        self.assertEqual(play._adjacent_foe(self.game), (1, 0))

    def test_the_driver_gets_out_of_the_water(self):
        """It stood in a river trading blows with a goblin and drowned."""
        from tools import play

        why = collections.Counter()
        game, p = self.game, self.game.player
        game.local.set_tile(p.x, p.y, p.z, "deep_water")
        game.local.set_tile(p.x + 1, p.y, p.z, "floor")
        cost = play._get_out_of_the_water(game, why)
        self.assertIsNotNone(cost, "it stayed under")
        self.assertEqual(why["struck out for the bank"], 1)
        # And it is the first thing `_look_after` asks, above thirst: an
        # adventurer with its head under water has a more pressing problem.
        why.clear()
        game.local.set_tile(p.x, p.y, p.z, "deep_water")   # back in the river
        game.local.set_tile(p.x + 1, p.y, p.z, "floor")
        p.needs.thirst = play.THIRSTY + 5000
        self.assertIsNotNone(play._look_after(game, why))
        self.assertEqual(why["struck out for the bank"], 1)

    def test_the_driver_takes_work_and_says_what_it_did(self):
        """The whole point of the errand: it walks into a town, finds
        somebody who wants something done, and takes it on."""
        from tools import play

        out = play.play("errandharness", 400, size="pocket", history=20,
                        report=lambda *a: None)
        self.assertIn("quests_taken", out)
        self.assertIn("world_tiles", out)
        self.assertEqual(out["nowhere"], [],
                         "it was given work with no destination")


class TestTheWild(GameFixture):
    """BENIGN, AMBUSHER and VERMIN, finally read by something."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import wild

        self.wild = wild
        for c in list(self.game.creatures.values()):
            if not c.is_player:
                self.game.remove_creature(c)
        self.game.update_fov()

    def _spawn(self, def_id, dist=5, faction="wild"):
        """Put a creature *dist* away with a clear line of sight, if possible."""
        from ascii_warriors.engine.geometry import DIRS8
        from ascii_warriors.game import ai
        from ascii_warriors.game.ai import AIState
        from ascii_warriors.game.entity import make_creature

        p = self.game.player
        c = make_creature(self.game.rng, def_id, faction=faction)
        c.ai = AIState("idle")
        self.game.add_creature(c)
        for dx, dy in DIRS8:
            cell = (p.x + dx * dist, p.y + dy * dist, p.z)
            if not self.game.is_passable(*cell):
                continue
            c.x, c.y, c.z = cell
            self.game.update_fov()
            if ai.can_see(c, p, self.game):
                return c
        c.x, c.y, c.z = p.x, p.y, p.z
        self.game.update_fov()
        return None if dist else c

    # -- the flags --------------------------------------------------------- #

    def test_the_flags_pick_out_the_right_animals(self):
        from ascii_warriors.data import creatures as creature_data

        for flag, checker in (("BENIGN", self.wild.is_skittish),
                              ("AMBUSHER", self.wild.is_ambusher),
                              ("VERMIN", self.wild.is_vermin)):
            owners = [i for i, d in creature_data.CREATURES.items()
                      if d.has(flag)]
            self.assertTrue(owners, "%s is on nothing" % flag)
        deer = self._spawn("deer", 0)
        self.assertTrue(self.wild.is_skittish(deer))
        self.assertFalse(self.wild.is_ambusher(deer))

    def test_a_person_is_never_skittish(self):
        self.assertFalse(self.wild.is_skittish(self.game.player))

    # -- running away ------------------------------------------------------ #

    def test_a_deer_runs_from_you(self):
        from ascii_warriors.game import ai

        deer = self._spawn("deer", 5)
        if deer is None:
            self.skipTest("no clear ground to put a deer on")
        self.assertEqual(ai.pick_mode(deer, self.game), "flee")

    def test_a_deer_actually_gets_further_away(self):
        from ascii_warriors.game import ai

        deer = self._spawn("deer", 4)
        if deer is None:
            self.skipTest("no clear ground to put a deer on")
        was = deer.distance_to(self.game.player)
        for _ in range(12):
            ai.take_turn(deer, self.game)
        self.assertGreater(deer.distance_to(self.game.player), was)

    def test_a_tame_animal_does_not_run(self):
        deer = self._spawn("deer", 4)
        if deer is None:
            self.skipTest("no clear ground to put a deer on")
        deer.tame = True
        self.assertIsNone(self.wild.frightener(self.game, deer))
        self.assertEqual(self.wild.flight_distance(
            self.game, deer, self.game.player), 0)

    def test_sneaking_gets_you_closer_than_walking(self):
        """The reason v3.6 and v3.9 exist, finally paid off."""
        from ascii_warriors.game import stealth

        deer = self._spawn("deer", 6)
        if deer is None:
            self.skipTest("no clear ground to put a deer on")
        p = self.game.player
        p.skills.set_level("sneak", 18)
        stealth.set_sneaking(p, True)
        sneaking = self.wild.flight_distance(self.game, deer, p)
        stealth.set_sneaking(p, False)
        p.skills.set_level("sneak", 0)
        walking = self.wild.flight_distance(self.game, deer, p)
        self.assertLess(sneaking, walking)

    def test_flight_lasts_more_than_one_step(self):
        deer = self._spawn("deer", 4)
        if deer is None:
            self.skipTest("no clear ground to put a deer on")
        self.wild.start_flight(deer, self.game.player)
        kept = sum(1 for _ in range(self.wild.FLIGHT_TURNS)
                   if self.wild.still_fleeing(deer))
        self.assertGreater(kept, 1)
        self.assertFalse(self.wild.still_fleeing(deer))

    def test_a_deer_does_not_bolt_from_another_deer(self):
        a = self._spawn("deer", 0)
        b = self._spawn("deer", 2)
        if a is None or b is None:
            self.skipTest("no clear ground for two deer")
        self.assertFalse(self.wild._alarming(a, b))

    # -- lying in wait ----------------------------------------------------- #

    def test_an_ambusher_waits_when_it_has_not_been_seen(self):
        from ascii_warriors.game import ai

        self.game.player.skills.set_level("observer", 0)
        tiger = self._spawn("tiger", 7)
        if tiger is None:
            self.skipTest("no clear sightline for a tiger")
        modes = [ai.pick_mode(tiger, self.game) for _ in range(30)]
        self.assertIn("lurk", modes)

    def test_an_ambusher_springs_once_you_are_close(self):
        from ascii_warriors.game import ai

        self.game.player.skills.set_level("observer", 0)
        tiger = self._spawn("tiger", 2)
        if tiger is None:
            self.skipTest("no clear sightline for a tiger")
        modes = [ai.pick_mode(tiger, self.game) for _ in range(10)]
        self.assertNotIn("lurk", modes)

    def test_a_watchful_eye_stops_the_ambush(self):
        from ascii_warriors.game import ai

        p = self.game.player
        tiger = self._spawn("tiger", 7)
        if tiger is None:
            self.skipTest("no clear sightline for a tiger")
        p.skills.set_level("observer", 0)
        blind = [ai.pick_mode(tiger, self.game) for _ in range(30)].count("lurk")
        tiger.ambush_wait = 0
        p.skills.set_level("observer", 15)
        sharp = [ai.pick_mode(tiger, self.game) for _ in range(30)].count("lurk")
        self.assertGreater(blind, sharp)

    def test_an_ambusher_does_not_wait_for_ever(self):
        tiger = self._spawn("tiger", 7)
        if tiger is None:
            self.skipTest("no clear sightline for a tiger")
        tiger.ambush_wait = self.wild.GIVE_UP_HIDDEN
        self.assertFalse(self.wild.waiting(self.game, tiger, self.game.player))

    def test_one_unlucky_roll_does_not_end_the_ambush(self):
        """It did: a single notice set the counter straight to its ceiling."""
        tiger = self._spawn("tiger", 7)
        if tiger is None:
            self.skipTest("no clear sightline for a tiger")
        self.game.player.skills.set_level("observer", 0)
        seen = [self.wild.waiting(self.game, tiger, self.game.player)
                for _ in range(self.wild.GIVE_UP_HIDDEN - 1)]
        self.assertIn(True, seen)
        self.assertLess(tiger.ambush_wait, self.wild.GIVE_UP_HIDDEN + 1)

    def test_an_ambusher_hides_without_being_told_to(self):
        from ascii_warriors.game import stealth

        tiger = self._spawn("tiger", 0)
        self.assertTrue(stealth.natural_sneak(tiger))
        self.assertEqual(tiger.skills.level("ambusher"), 0,
                         "this test is about the flag, not the skill")

    def test_the_flag_is_worth_something_in_the_roll(self):
        from ascii_warriors.game import stealth

        tiger = self._spawn("tiger", 5)
        if tiger is None:
            self.skipTest("no clear sightline for a tiger")
        p = self.game.player
        p.skills.set_level("observer", 0)
        seen = sum(1 for _ in range(300)
                   if stealth.noticed_by(self.game, tiger, p))
        self.assertLess(seen, 250, "an ambush predator is never hidden at all")

    # -- vermin ------------------------------------------------------------- #

    def test_vermin_run_from_anything_bigger(self):
        rat = self._spawn("rat", 2)
        if rat is None:
            self.skipTest("no clear ground for a rat")
        self.assertTrue(self.wild.is_skittish(rat))
        self.assertIsNotNone(self.wild.frightener(self.game, rat))

    def test_vermin_steal_food_off_the_ground(self):
        from ascii_warriors.game.item import Item

        rat = self._spawn("rat", 2)
        if rat is None:
            self.skipTest("no clear ground for a rat")
        self.game.drop_item(Item("meat", "meat"), rat.x, rat.y, rat.z)
        took = None
        for _ in range(30):
            took = self.wild.steal(self.game, rat, self.game.rng)
            if took is not None:
                break
        self.assertIsNotNone(took)
        self.assertEqual(self.game.items_at(rat.x, rat.y, rat.z), [])

    def test_something_that_is_not_vermin_steals_nothing(self):
        from ascii_warriors.game.item import Item

        deer = self._spawn("deer", 2)
        if deer is None:
            self.skipTest("no clear ground for a deer")
        self.game.drop_item(Item("meat", "meat"), deer.x, deer.y, deer.z)
        self.assertIsNone(self.wild.steal(self.game, deer, self.game.rng))

    # -- the faction that never was ----------------------------------------- #

    def test_wild_hostile_is_actually_hostile(self):
        """It fell through to False, so the one faction with `hostile` in its
        name was the one that never attacked anybody."""
        rabbit = self._spawn("rabbit", 2, faction="wild_hostile")
        if rabbit is None:
            self.skipTest("no clear ground for a rabbit")
        self.assertTrue(rabbit.is_hostile_to(self.game.player))
        self.assertTrue(self.game.player.is_hostile_to(rabbit))


class TestTraps(GameFixture):
    """The TRAP and ICE tile flags, and what a sealed tomb is for."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import traps

        self.traps = traps
        self.traps.layer(self.game).clear()

    def _here(self, dx=1, dy=0):
        """A walkable cell beside the player, made if there is not one.

        Six hand-picked offsets and a skip if none of them was open, which is
        a thing the dice decide -- so the trap tests could be switched off by
        a change to worldgen anywhere. It digs one out now.
        """
        p = self.game.player
        for ox, oy in ((dx, dy), (-dx, dy), (dx, -dy), (0, 1), (1, 1), (-1, -1)):
            cell = (p.x + ox, p.y + oy, p.z)
            if self.game.local.walkable(*cell):
                return cell
        cell = (max(1, min(self.game.local.width - 2, p.x + 1)), p.y, p.z)
        self.game.local.set_tile(cell[0], cell[1], cell[2], "floor")
        return cell

    def _trap(self, kind="pit"):
        cell = self._here()
        self.assertIsNotNone(cell)
        trap = self.traps.place(self.game, cell, kind)
        self.assertIsNotNone(trap)
        return cell, trap

    # -- placing them ------------------------------------------------------ #

    def test_every_kind_has_a_strike_the_combat_model_knows(self):
        from ascii_warriors.game import combat

        for kind, defn in self.traps.KINDS.items():
            if not defn.get("damage", (0, 0))[1]:
                continue
            self.assertIn(kind, combat.TRAP_STRIKES, kind)

    def test_a_trap_cannot_be_put_in_a_wall(self):
        p = self.game.player
        solid = None
        for r in range(1, 20):
            for dx in range(-r, r + 1):
                cell = (p.x + dx, p.y + r, p.z)
                if (self.game.local.in_bounds(*cell)
                        and not self.game.local.walkable(*cell)):
                    solid = cell
                    break
            if solid:
                break
        if solid is None:
            self.skipTest("nothing solid nearby")
        self.assertIsNone(self.traps.place(self.game, solid, "pit"))

    def test_two_traps_do_not_share_a_cell(self):
        cell, _t = self._trap()
        self.assertIsNone(self.traps.place(self.game, cell, "dart"))

    def test_tombs_get_more_traps_than_ruins(self):
        self.assertGreater(self.traps.PER_SITE["tomb"][0],
                           self.traps.PER_SITE["ruin"][0])

    # -- finding them ------------------------------------------------------ #

    def test_a_trap_starts_hidden(self):
        _cell, trap = self._trap()
        self.assertFalse(trap.found)

    def test_looking_finds_them_better_than_walking_past(self):
        _cell, trap = self._trap()
        p = self.game.player
        p.skills.set_level("observer", 8)
        self.assertGreater(
            self.traps.spot_chance(p, trap, searching=True),
            self.traps.spot_chance(p, trap, searching=False))

    def test_the_spot_curve_is_a_curve_and_not_a_cliff(self):
        """It was: observer 0 found a pit 1% of the time and observer 5, 95%."""
        _cell, trap = self._trap()
        p = self.game.player
        seen = []
        for level in (0, 5, 10, 16):
            p.skills.set_level("observer", level)
            seen.append(self.traps.spot_chance(p, trap, searching=True))
        self.assertEqual(seen, sorted(seen))
        # No single rank may be worth more than half the whole range.
        steps = [b - a for a, b in zip(seen, seen[1:])]
        self.assertLess(max(steps), 0.5)
        self.assertGreater(seen[-1] - seen[0], 0.3)

    def test_a_hidden_trap_is_harder_than_an_obvious_one(self):
        p = self.game.player
        p.skills.set_level("observer", 6)
        pit = self.traps.Trap("pit")
        alarm = self.traps.Trap("alarm")
        self.assertGreater(self.traps.spot_chance(p, pit, searching=True),
                           self.traps.spot_chance(p, alarm, searching=True))

    def test_searching_eventually_finds_one(self):
        cell, trap = self._trap()
        p = self.game.player
        p.x, p.y, p.z = cell[0], cell[1], cell[2]
        p.skills.set_level("observer", 10)
        for _ in range(40):
            if self.traps.look_around(self.game, searching=True):
                break
        self.assertTrue(trap.found)

    def test_finding_one_draws_it(self):
        cell, trap = self._trap()
        self.traps.reveal(self.game, cell, trap)
        self.assertEqual(self.game.local.tile(*cell), self.traps.TRAP_TILE)

    # -- disarming them ---------------------------------------------------- #

    def test_you_cannot_disarm_what_you_have_not_found(self):
        cell, _trap = self._trap()
        ok, _said = self.traps.disarm(self.game, cell)
        self.assertFalse(ok)

    def test_a_mechanic_takes_one_apart(self):
        cell, trap = self._trap()
        self.traps.reveal(self.game, cell, trap)
        self.game.player.skills.set_level("mechanics", 14)
        for _ in range(30):
            ok, _said = self.traps.disarm(self.game, cell)
            if ok or trap.sprung:
                break
        self.assertFalse(trap.armed)

    def test_a_disarmed_trap_does_nothing(self):
        cell, trap = self._trap()
        trap.armed = False
        self.assertIsNone(
            self.traps.step_on(self.game, self.game.player, cell))

    # -- setting them off --------------------------------------------------- #

    def test_stepping_on_one_springs_it(self):
        cell, trap = self._trap()
        p = self.game.player
        p.x, p.y, p.z = cell
        self.assertIsNotNone(self.traps.step_on(self.game, p, cell))
        self.assertTrue(trap.sprung)
        self.assertFalse(trap.armed)

    def test_a_sprung_trap_does_not_spring_twice(self):
        cell, _trap = self._trap()
        p = self.game.player
        p.x, p.y, p.z = cell
        self.traps.step_on(self.game, p, cell)
        self.assertIsNone(self.traps.step_on(self.game, p, cell))

    def test_a_dart_envenoms(self):
        cell, _trap = self._trap("dart")
        p = self.game.player
        p.x, p.y, p.z = cell
        p.inventory.remove_all()          # no armour to stop it
        self.traps.spring(self.game, cell, p)
        self.assertTrue(p.venom)

    def test_a_dart_that_cannot_get_through_does_not_envenom(self):
        """Armour mattering for the wound and not the venom is armour
        mattering for half the trap.

        Whether a given dart gets through is a die roll, and this used to skip
        the run when it did -- so any change to the game's dice anywhere could
        turn the test off, and one did. It throws darts until it has seen the
        case it is about.
        """
        cell, trap = self._trap("dart")
        p = self.game.player
        p.x, p.y, p.z = cell
        stopped = 0
        for _ in range(40):
            trap.sprung, trap.armed = False, True
            p.venom = []
            before = sum(len(part.wounds) for part in p.body.parts.values())
            self.traps.spring(self.game, cell, p)
            after = sum(len(part.wounds) for part in p.body.parts.values())
            if after > before:
                continue           # it got through; the venom belongs
            stopped += 1
            self.assertFalse(p.venom,
                             "a dart that drew no blood still envenomed")
        self.assertGreater(stopped, 0,
                           "forty darts and armour stopped none of them")

    def test_a_snare_lays_a_web(self):
        from ascii_warriors.game import webs

        cell, _trap = self._trap("snare")
        p = self.game.player
        p.x, p.y, p.z = cell
        self.traps.spring(self.game, cell, p)
        self.assertTrue(webs.is_web(self.game, cell))

    def test_an_alarm_wakes_the_neighbours(self):
        from ascii_warriors.game.ai import AIState
        from ascii_warriors.game.entity import make_creature

        cell, _trap = self._trap("alarm")
        p = self.game.player
        p.x, p.y, p.z = cell
        other = make_creature(self.game.rng, "human", faction="hostile")
        other.x, other.y, other.z = cell[0] + 2, cell[1], cell[2]
        other.ai = AIState("idle")
        other.ai.alertness = 0
        self.game.add_creature(other)
        self.traps.spring(self.game, cell, p)
        self.assertGreater(other.ai.alertness, 0)

    # -- ice ---------------------------------------------------------------- #

    def test_ice_is_recognised_by_its_flag(self):
        cell = self._here()
        if cell is None:
            self.skipTest("no walkable ground beside the player")
        self.assertFalse(self.traps.is_ice(self.game, cell))
        self.game.local.set_tile(cell[0], cell[1], cell[2], "ice")
        self.assertTrue(self.traps.is_ice(self.game, cell))

    def test_climbing_keeps_your_feet(self):
        p = self.game.player
        p.skills.set_level("climbing", 0)
        poor = self.traps.footing(p)
        p.skills.set_level("climbing", 15)
        self.assertGreater(self.traps.footing(p), poor)

    def test_you_can_slip_on_ice(self):
        cell = self._here()
        if cell is None:
            self.skipTest("no walkable ground beside the player")
        self.game.local.set_tile(cell[0], cell[1], cell[2], "ice")
        p = self.game.player
        p.skills.set_level("climbing", 0)
        slipped = any(self.traps.cross(self.game, p, cell) for _ in range(60))
        self.assertTrue(slipped)

    def test_ordinary_ground_never_trips_anybody(self):
        cell = self._here()
        if cell is None:
            self.skipTest("no walkable ground beside the player")
        self.assertFalse(any(self.traps.cross(self.game, self.game.player, cell)
                             for _ in range(40)))

    # -- persistence --------------------------------------------------------- #

    def test_traps_survive_a_save(self):
        from ascii_warriors.game import save as save_mod

        cell, trap = self._trap("collapse")
        self.traps.reveal(self.game, cell, trap)
        path = save_mod.save_game(self.game, "trap-test")
        back = save_mod.load_game(path)
        again = self.traps.at(back, cell)
        self.assertIsNotNone(again)
        self.assertEqual((again.kind, again.found, again.armed),
                         ("collapse", True, True))
        path.unlink()

    def test_a_save_without_traps_still_loads(self):
        from ascii_warriors.game.state import Game

        raw = self.game.to_dict()
        del raw["traps"]
        back = Game.from_dict(raw)
        self.assertEqual(self.traps.layer(back), {})


class TestPersonality(GameFixture):
    """Thirty facets and twenty values, finally read by something."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import personality

        self.pers = personality

    def _people(self, n=200, race="dwarf"):
        from ascii_warriors.game.entity import make_creature

        return [make_creature(RNG("p%d" % i), race) for i in range(n)]

    # -- the numbers -------------------------------------------------------- #

    def test_every_accessor_stays_in_a_sane_band(self):
        for c in self._people(120):
            self.assertGreater(self.pers.sensitivity(c.personality), 0.2)
            self.assertLess(self.pers.sensitivity(c.personality), 2.0)
            self.assertGreater(self.pers.resilience(c.personality), 0.3)
            self.assertLess(self.pers.diligence(c.personality), 1.6)
            self.assertGreaterEqual(self.pers.grudge(c.personality), 0.0)

    def test_personalities_actually_differ(self):
        vals = [self.pers.sensitivity(c.personality) for c in self._people()]
        self.assertGreater(max(vals) - min(vals), 0.25,
                           "every dwarf feels things identically")

    def test_an_anxious_creature_feels_more_than_a_confident_one(self):
        a, b = self._people(2)
        for f, v in (("anxiety", 95), ("swayed_by_emotions", 95),
                     ("confidence", 5), ("tolerance", 5)):
            a.personality.set_facet(f, v)
        for f, v in (("anxiety", 5), ("swayed_by_emotions", 5),
                     ("confidence", 95), ("tolerance", 95)):
            b.personality.set_facet(f, v)
        self.assertGreater(self.pers.sensitivity(a.personality),
                           self.pers.sensitivity(b.personality))

    # -- the funnel --------------------------------------------------------- #

    def test_needs_know_whose_they_are(self):
        c = self._people(1)[0]
        self.assertIs(c.needs.owner, c)

    def test_the_same_event_lands_differently_on_different_people(self):
        """Fifty-six places make somebody feel something. One of them knows
        about personalities, and that is the point."""
        got = set()
        for c in self._people():
            c.needs.stress = 0
            c.needs.add_thought("a funeral", 20)
            got.add(c.needs.stress)
        self.assertGreater(len(got), 3)
        self.assertGreater(max(got), min(got))

    def test_a_thought_still_moves_stress_the_right_way(self):
        c = self._people(1)[0]
        c.needs.stress = 0
        c.needs.add_thought("something bad", 20)
        self.assertGreater(c.needs.stress, 0)
        c.needs.stress = 0
        c.needs.add_thought("something good", -20)
        self.assertLess(c.needs.stress, 0)

    def test_needs_without_an_owner_are_unscaled(self):
        from ascii_warriors.game.needs import Needs

        n = Needs()
        self.assertEqual(n.feeling(), 1.0)
        self.assertEqual(n.recovery(), 1.0)
        n.add_thought("plain", 10)
        self.assertEqual(n.stress, 10)

    def test_feelings_still_fade(self):
        c = self._people(1)[0]
        c.needs.stress = 100
        for _ in range(60):
            c.needs.tick(1000, c, self.game)
        self.assertLess(c.needs.stress, 100)

    def test_the_stress_clamp_still_holds(self):
        c = self._people(1)[0]
        for _ in range(200):
            c.needs.add_thought("relentless", 40)
        self.assertLessEqual(c.needs.stress, 200)
        for _ in range(400):
            c.needs.add_thought("relentless joy", -40)
        self.assertGreaterEqual(c.needs.stress, -150)

    # -- values ------------------------------------------------------------- #

    def test_holding_a_value_decides_whether_you_care(self):
        felt = [c.value_thought("artwork", -20, "a statue")
                for c in self._people()]
        self.assertTrue(any(f != 0 for f in felt), "nobody cares about anything")
        self.assertTrue(any(f == 0 for f in felt),
                        "everybody cares about everything")

    def test_a_value_you_hold_dearly_is_worth_more(self):
        a, b = self._people(2)
        a.personality.values["craftsmanship"] = 50
        b.personality.values["craftsmanship"] = 0
        self.assertLess(a.value_thought("craftsmanship", -20, "a masterwork"),
                        b.value_thought("craftsmanship", -20, "a masterwork") + 1)

    def test_despising_a_value_reverses_the_feeling(self):
        c = self._people(1)[0]
        c.personality.values["law"] = -50
        self.assertGreater(c.value_thought("law", -20, "the law upheld"), 0)

    def test_races_hold_their_own_values(self):
        dwarves = self._people(60, "dwarf")
        mean = sum(self.pers.values_held(c.personality, "craftsmanship")
                   for c in dwarves) / 60.0
        self.assertGreater(mean, 0.1, "dwarves are indifferent to craft")

    # -- work --------------------------------------------------------------- #

    def test_diligence_moves_the_work_rate(self):
        from ascii_warriors.fortress.jobs import Job, work_rate

        a, b = self._people(2)
        from ascii_warriors.fortress import dwarf as dwarf_mod

        for c in (a, b):
            dwarf_mod.attach(c, "miner")
        for f in ("perseverance", "activity_level", "discipline"):
            a.personality.set_facet(f, 95)
            b.personality.set_facet(f, 5)
        job = Job(1, "dig", 0, 0, 0, skill="mining")
        self.assertGreater(work_rate(a, job), work_rate(b, job))

    # -- grudges ------------------------------------------------------------- #

    def test_a_vengeful_creature_holds_a_grudge(self):
        a, b = self._people(2)
        for f, v in (("vengefulness", 95), ("hate_propensity", 95),
                     ("tolerance", 5), ("altruism", 5)):
            a.personality.set_facet(f, v)
        for f, v in (("vengefulness", 5), ("hate_propensity", 5),
                     ("tolerance", 95), ("altruism", 95)):
            b.personality.set_facet(f, v)
        self.assertGreater(self.pers.grudge(a.personality),
                           self.pers.grudge(b.personality))

    def test_personality_survives_a_save(self):
        from ascii_warriors.game import save as save_mod

        p = self.game.player
        p.personality.set_facet("anxiety", 91)
        before = self.pers.sensitivity(p.personality)
        path = save_mod.save_game(self.game, "pers-test")
        back = save_mod.load_game(path)
        self.assertEqual(back.player.personality.facet("anxiety"), 91)
        self.assertAlmostEqual(self.pers.sensitivity(back.player.personality),
                               before, places=5)
        self.assertIs(back.player.needs.owner, back.player)
        path.unlink()


class TestKin(GameFixture):
    """`relationships` and `"marriage"`, declared for ever and never used."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.world import history

        self.history = history

    def _figures_with(self, kind, n=1):
        out = [f for f in self.world.figures.values()
               if any(k == kind for k in f.relationships.values())]
        if len(out) < n:
            self.skipTest("this world has no %s" % kind)
        return out

    # -- the graph ---------------------------------------------------------- #

    def test_worldgen_makes_families(self):
        related = [f for f in self.world.figures.values() if f.relationships]
        self.assertTrue(related, "nobody in this world is anybody's anything")

    def test_marriages_are_recorded_as_events(self):
        weddings = [e for e in self.world.events if e.kind == "marriage"]
        spouses = self._figures_with("spouse")
        self.assertTrue(spouses)
        self.assertTrue(weddings, "people married and the world forgot")

    def test_every_relationship_is_reciprocal(self):
        for f in self.world.figures.values():
            for other_id, kind in f.relationships.items():
                other = self.world.figures.get(other_id)
                self.assertIsNotNone(other, "relation to a figure that is gone")
                back = other.relationships.get(f.id)
                self.assertEqual(back, self.history.OPPOSITE.get(kind, kind),
                                 "%s -> %s" % (kind, back))

    def test_nobody_is_related_to_themselves(self):
        for f in self.world.figures.values():
            self.assertNotIn(f.id, f.relationships)

    def test_every_relationship_kind_has_an_opposite_and_a_name(self):
        for kind in self.history.OPPOSITE:
            self.assertIn(kind, self.history.RELATION_NAMES, kind)
        for f in self.world.figures.values():
            for kind in f.relationships.values():
                self.assertIn(kind, self.history.OPPOSITE, kind)

    def test_relate_writes_both_ways(self):
        a, b = list(self.world.figures.values())[:2]
        a.relationships.clear()
        b.relationships.clear()
        self.history.relate(a, b, "parent")
        self.assertEqual(a.relationships[b.id], "parent")
        self.assertEqual(b.relationships[a.id], "child")

    def test_relating_somebody_to_themselves_does_nothing(self):
        a = list(self.world.figures.values())[0]
        before = dict(a.relationships)
        self.history.relate(a, a, "spouse")
        self.assertEqual(a.relationships, before)

    # -- bounds -------------------------------------------------------------- #

    def test_no_couple_has_an_absurd_number_of_children(self):
        """One couple accumulated fifteen before this was bounded."""
        for f in self.world.figures.values():
            kids = sum(1 for k in f.relationships.values() if k == "child")
            self.assertLessEqual(kids, self.history.MAX_CHILDREN)

    def test_children_take_the_family_name(self):
        parents = self._figures_with("child")
        shared = 0
        for parent in parents:
            for kid_id, kind in parent.relationships.items():
                if kind != "child":
                    continue
                kid = self.world.figures[kid_id]
                if (len(parent.name.split()) > 1
                        and parent.name.split()[1:] == kid.name.split()[1:]):
                    shared += 1
        if not shared:
            self.skipTest("this race has no surnames")
        self.assertGreater(shared, 0)

    def test_kin_are_blood_and_marriage_only(self):
        """`kin_of` counts blood and marriage, and a killer is neither.

        Built rather than hunted. This used to skip itself when the generated
        history happened to contain no slaying, so it measured nothing on the
        worlds that did not oblige -- and it went quiet the moment an unrelated
        change moved the dice, which is how it was noticed.
        """
        pair = [f for f in self.world.figures.values() if f.relationships][:2]
        self.assertEqual(len(pair), 2, "nobody in this world knows anybody")
        victim, killer = pair
        victim.relationships[killer.id] = "slain_by"
        killer.relationships[victim.id] = "slew"
        self.assertNotIn(killer, self.history.kin_of(self.world, victim),
                         "a killer counts as family")
        slain = [f for f in self.world.figures.values()
                 if any(k == "slain_by" for k in f.relationships.values())]
        self.assertTrue(slain)
        for f in slain:
            for k in self.history.kin_of(self.world, f):
                self.assertIn(f.relationships[k.id],
                              ("spouse", "parent", "child", "sibling"))

    # -- reading it ---------------------------------------------------------- #

    def test_the_legends_page_shows_relations(self):
        from ascii_warriors.world import legends

        related = [f for f in self.world.figures.values() if f.relationships]
        if not related:
            self.skipTest("no relations in this world")
        fig = related[0]
        text = " ".join(f.text for f in legends.figure_lines(self.world, fig.id))
        self.assertIn("Relations", text)

    def test_relations_survive_a_world_round_trip(self):
        from ascii_warriors.world.worldgen import World

        related = [f for f in self.world.figures.values() if f.relationships]
        if not related:
            self.skipTest("no relations in this world")
        fig = related[0]
        back = World.from_dict(self.world.to_dict())
        self.assertEqual(back.figures[fig.id].relationships, fig.relationships)

    # -- kin remember --------------------------------------------------------- #

    def test_killing_somebody_turns_their_kin_on_you(self):
        from ascii_warriors.game import standing

        related = [f for f in self.world.figures.values()
                   if self.history.kin_of(self.world, f)]
        if not related:
            self.skipTest("nobody here has family")
        victim_fig = related[0]
        relative = self.history.kin_of(self.world, victim_fig)[0]

        folk = [c for c in self.game.creatures.values()
                if not c.is_player and c.defn.intelligent]
        if len(folk) < 2:
            self.skipTest("not enough people on this map")
        victim, avenger = folk[0], folk[1]
        victim.hf_id = victim_fig.id
        victim.faction = "town"
        avenger.hf_id = relative.id
        p = self.game.player
        for i, c in enumerate((victim, avenger)):
            c.x, c.y, c.z = p.x + 1 + i, p.y, p.z
        self.game.update_fov()

        standing.on_kill(self.game, victim)
        self.assertIn(p.id, avenger.hostile_to)

    def test_killing_a_nobody_leaves_no_avengers(self):
        from ascii_warriors.game import standing

        folk = [c for c in self.game.creatures.values()
                if not c.is_player and c.defn.intelligent]
        if not folk:
            self.skipTest("nobody on this map")
        victim = folk[0]
        victim.hf_id = None
        victim.faction = "town"
        p = self.game.player
        victim.x, victim.y, victim.z = p.x + 1, p.y, p.z
        self.game.update_fov()
        before = {c.id: set(c.hostile_to) for c in folk}
        standing.on_kill(self.game, victim)
        for c in folk[1:]:
            self.assertEqual(c.hostile_to, before[c.id])


class TestFire(GameFixture):
    """FLAMMABLE, on tiles and materials and items, finally read."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.world import fire

        self.fire = fire
        self.game.fire = fire.Fire()

    def _forest(self, size=6):
        """Plant a block of trees near the player and return the cells."""
        lm = self.game.local
        p = self.game.player
        cells = []
        for dy in range(-size // 2, size // 2):
            for dx in range(-size // 2, size // 2):
                c = (p.x + dx, p.y + dy, p.z)
                if lm.in_bounds(*c) and lm.walkable(*c):
                    lm.set_tile(c[0], c[1], c[2], "tree")
                    cells.append(c)
        if not cells:
            self.skipTest("nowhere to plant a forest")
        return cells

    # -- what burns ---------------------------------------------------------- #

    def test_a_tree_is_fuel_and_stone_is_not(self):
        lm = self.game.local
        p = self.game.player
        cell = (p.x, p.y, p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "tree")
        self.assertGreater(self.fire.fuel_at(lm, cell), 0)
        lm.set_tile(cell[0], cell[1], cell[2], "rock_wall")
        self.assertEqual(self.fire.fuel_at(lm, cell), 0)

    def test_a_tree_burns_longer_than_a_shrub(self):
        self.assertGreater(self.fire.TILE_FUEL["tree"],
                           self.fire.TILE_FUEL["shrub"])

    def test_wood_burns_by_its_material(self):
        from ascii_warriors.game.item import Item

        self.assertTrue(self.fire.is_flammable_item(Item("bed", "oak")))
        self.assertFalse(self.fire.is_flammable_item(Item("sword", "iron")))

    def test_items_add_to_the_fire(self):
        from ascii_warriors.game.item import Item

        pile = [Item("log", "oak"), Item("sword", "iron")]
        self.assertEqual(self.fire.item_fuel(pile), self.fire.ITEM_FUEL)

    # -- lighting it ---------------------------------------------------------- #

    def test_nothing_catches_on_bare_stone(self):
        lm = self.game.local
        p = self.game.player
        cell = (p.x, p.y, p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "rock_wall")
        self.assertFalse(self.game.fire.ignite(lm, cell))

    def test_a_tree_catches(self):
        cells = self._forest()
        self.assertTrue(self.game.fire.ignite(self.game.local, cells[0]))
        self.assertGreater(self.game.fire.burning(*cells[0]), 0)

    def test_a_cell_cannot_catch_twice(self):
        cells = self._forest()
        self.game.fire.ignite(self.game.local, cells[0])
        self.assertFalse(self.game.fire.ignite(self.game.local, cells[0]))

    # -- burning --------------------------------------------------------------- #

    def test_fire_burns_down_and_goes_out(self):
        cells = self._forest()
        self.game.fire.ignite(self.game.local, cells[0])
        for _ in range(2000):
            self.game.fire.step(self.game.local, self.game.rng)
            if not self.game.fire.anything_burning:
                break
        self.assertFalse(self.game.fire.anything_burning)

    def test_what_burned_becomes_ash(self):
        cells = self._forest()
        self.game.fire.ignite(self.game.local, cells[0])
        for _ in range(2000):
            self.game.fire.step(self.game.local, self.game.rng)
            if not self.game.fire.anything_burning:
                break
        burnt = [c for c in cells if self.game.local.tile(*c) == "ash"]
        self.assertTrue(burnt)

    def test_fire_spreads_through_a_forest(self):
        cells = self._forest(8)
        self.game.fire.ignite(self.game.local, cells[len(cells) // 2])
        burnt = 0
        for _ in range(3000):
            burnt += len(self.game.fire.step(self.game.local, self.game.rng))
            if not self.game.fire.anything_burning:
                break
        self.assertGreater(burnt, 1, "a fire in a forest burned one tree")

    def test_fire_does_not_cross_bare_ground(self):
        """Two trees, six tiles of rock between them, and it stays put.

        The layout is built rather than found. It used to skip when the
        player's start had no six clear tiles running east, which is a thing
        the dice decide -- so any worldgen change anywhere could quietly turn
        this test off, and one did.

        It also only asked whether the far tree survived, which a fire that
        crossed three tiles of rock and then went out passes. It asks about
        the ground between them now.
        """
        lm = self.game.local
        p = self.game.player
        y = min(max(p.y, 0), lm.height - 1)
        x = min(max(p.x, 0), lm.width - 7)
        here, far = (x, y, p.z), (x + 6, y, p.z)
        for dx in range(7):
            lm.set_tile(x + dx, y, p.z, "floor")
        for c in (here, far):
            lm.set_tile(c[0], c[1], c[2], "tree")
        self.game.fire.ignite(lm, here)
        for _ in range(2000):
            self.game.fire.step(lm, self.game.rng)
            if not self.game.fire.anything_burning:
                break
        self.assertEqual([lm.tile(x + dx, y, p.z) for dx in range(1, 6)],
                         ["floor"] * 5, "the bare ground caught")
        self.assertEqual(lm.tile(*far), "tree", "fire jumped six tiles of rock")

    def test_the_burning_cap_holds(self):
        cells = self._forest(20)
        for c in cells[:400]:
            self.game.fire.ignite(self.game.local, c)
        self.assertLessEqual(len(self.game.fire.fuel), self.fire.MAX_BURNING)

    def test_an_unlit_map_costs_nothing_to_step(self):
        self.assertEqual(
            self.game.fire.step(self.game.local, self.game.rng), [])

    # -- what it does ---------------------------------------------------------- #

    def test_fire_is_light(self):
        cells = self._forest()
        self.game.fire.ignite(self.game.local, cells[0])
        self.assertGreater(self.game.fire.light_at(*cells[0]), 0.5)
        far = (cells[0][0] + 20, cells[0][1], cells[0][2])
        self.assertEqual(self.game.fire.light_at(*far), 0.0)

    def test_the_map_reports_the_light(self):
        cells = self._forest()
        self.game.fire.ignite(self.game.local, cells[0])
        self.assertGreater(self.game.light_at(*cells[0]), 0.5)

    def test_standing_in_a_fire_hurts(self):
        p = self.game.player
        before = p.body.health_fraction()
        for _ in range(12):
            self.fire.burn(p, self.game.rng)
        self.assertLess(p.body.health_fraction(), before)

    def test_the_fire_strike_is_in_the_shared_table(self):
        from ascii_warriors.game import combat

        self.assertIn("fire", combat.TRAP_STRIKES)

    def test_a_torch_is_needed_to_start_one(self):
        from ascii_warriors.game import actions

        self._forest()
        p = self.game.player
        for it in list(p.inventory.items):
            if it.is_light:
                it.flags["lit"] = False
        self.assertEqual(actions.set_fire(self.game), actions.FREE)
        self.assertFalse(self.game.fire.anything_burning)

    def test_a_lit_torch_starts_one(self):
        from ascii_warriors.data import items as item_data
        from ascii_warriors.game import actions
        from ascii_warriors.game.item import Item

        self._forest()
        p = self.game.player
        torch = Item("torch", "oak")
        torch.flags["lit"] = True
        torch.charges = 5000
        p.inventory.add(torch)
        self.assertTrue(self.fire.carrying_flame(p))
        actions.set_fire(self.game)
        self.assertTrue(self.game.fire.anything_burning)

    # -- persistence ------------------------------------------------------------ #

    def test_fire_survives_a_save(self):
        from ascii_warriors.game import save as save_mod

        cells = self._forest()
        self.game.fire.ignite(self.game.local, cells[0])
        left = self.game.fire.burning(*cells[0])
        path = save_mod.save_game(self.game, "fire-test")
        back = save_mod.load_game(path)
        self.assertEqual(back.fire.burning(*cells[0]), left)
        path.unlink()

    def test_a_save_without_fire_still_loads(self):
        from ascii_warriors.game.state import Game

        raw = self.game.to_dict()
        del raw["fire"]
        back = Game.from_dict(raw)
        self.assertFalse(back.fire.anything_burning)


class TestTemperature(GameFixture):
    """The world map's temperature, and the material table's melting points,
    finally reading each other."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.world import heat

        self.heat = heat

    # -- the scale ----------------------------------------------------------- #

    def test_freezing_comes_out_of_the_material_table(self):
        from ascii_warriors.data.materials import MATERIALS

        self.assertEqual(self.heat.FREEZING,
                         MATERIALS["ice"].melting_point - self.heat.URIST_OFFSET)
        self.assertEqual(self.heat.FREEZING, 32.0)

    def test_the_conversion_goes_both_ways(self):
        self.assertAlmostEqual(self.heat.urists(self.heat.degrees(11500)), 11500)

    def test_metal_melts_far_out_of_reach_of_weather(self):
        self.assertGreater(self.heat.melts_at("iron"), 2000)
        self.assertEqual(self.heat.melts_at("water"), 32.0)
        self.assertIsNone(self.heat.melts_at("no_such_material"))

    # -- what the air does --------------------------------------------------- #

    def test_winter_is_colder_than_summer(self):
        w = self.heat.ambient(50, season="Winter")
        s = self.heat.ambient(50, season="Summer")
        self.assertGreater(s - w, 30)

    def test_the_night_is_colder_than_the_afternoon(self):
        self.assertLess(self.heat.ambient(50, hour=4),
                        self.heat.ambient(50, hour=15))

    def test_a_blizzard_is_colder_than_a_clear_sky(self):
        self.assertLess(self.heat.ambient(40, weather="blizzard"),
                        self.heat.ambient(40, weather="clear"))

    def test_weather_does_not_reach_you_indoors(self):
        out = self.heat.ambient(40, weather="blizzard", outside=True)
        inn = self.heat.ambient(40, weather="blizzard", outside=False)
        self.assertGreater(inn, out)

    def test_the_biome_bias_is_read(self):
        from ascii_warriors.data import biomes

        glacier = biomes.get("glacier")
        self.assertLess(glacier.temperature_bias, 0)
        self.assertLess(self.heat.ambient(40, biome=glacier),
                        self.heat.ambient(40, biome=None))

    def test_the_biome_bias_is_a_nudge_not_a_second_climate(self):
        # Believing the whole bias double-counts the climate worldgen already
        # used to pick the biome, and puts a glacier at ninety below.
        from ascii_warriors.data import biomes

        g = biomes.get("glacier")
        shift = self.heat.ambient(40, biome=g) - self.heat.ambient(40)
        self.assertLess(abs(shift), abs(g.temperature_bias))

    def test_deep_rock_does_not_care_what_month_it_is(self):
        deep = [self.heat.ambient(40, season=s, depth=self.heat.CAVE_DEPTH * 2,
                                  outside=False)
                for s in ("Summer", "Winter")]
        self.assertAlmostEqual(deep[0], deep[1], places=6)
        self.assertAlmostEqual(deep[0], self.heat.CAVE_TEMP, places=6)

    def test_depth_moves_you_toward_the_rock(self):
        cold = 0.0
        near = max(1, self.heat.CAVE_DEPTH // 4)
        far = max(near + 1, self.heat.CAVE_DEPTH - 1)
        shallow = self.heat.ambient(cold, depth=near, outside=False)
        deeper = self.heat.ambient(cold, depth=far, outside=False)
        self.assertLess(shallow, deeper)
        self.assertLess(deeper, self.heat.CAVE_TEMP)
        self.assertEqual(self.heat.ambient(cold, depth=self.heat.CAVE_DEPTH,
                                           outside=False), self.heat.CAVE_TEMP)

    # -- what is nearby ------------------------------------------------------ #

    def test_a_fire_warms_the_ground_around_it(self):
        lm = self.game.local
        p = self.game.player
        cell = (p.x, p.y, p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "tree")
        self.game.fire.ignite(lm, cell)
        near = self.heat.source_heat((p.x + 1, p.y, p.z), fire=self.game.fire)
        far = self.heat.source_heat((p.x + 5, p.y, p.z), fire=self.game.fire)
        self.assertGreater(near, far)
        self.assertGreater(far, 0.0)
        self.assertEqual(
            self.heat.source_heat((p.x + 40, p.y, p.z), fire=self.game.fire), 0.0)

    def test_no_fire_is_no_heat(self):
        p = self.game.player
        self.assertEqual(
            self.heat.source_heat((p.x, p.y, p.z), fire=self.game.fire), 0.0)

    def test_magma_is_hotter_than_a_camp_fire(self):
        self.assertGreater(self.heat.MAGMA_HEAT, self.heat.FIRE_HEAT)

    # -- what you are wearing ------------------------------------------------ #

    def test_clothes_insulate_and_nakedness_does_not(self):
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item
        from ascii_warriors.engine.rng import RNG

        bare = make_creature(RNG("t"), "dwarf", equip=False)
        self.assertLess(self.heat.insulation(bare), 0.1)
        dressed = make_creature(RNG("t"), "dwarf", equip=False)
        for i in ("tunic", "trousers", "cloak", "hood", "shoes"):
            dressed.inventory.equip(make_item(RNG("i"), i, material="wool_cloth"))
        self.assertGreater(self.heat.insulation(dressed), 0.5)

    def test_wool_is_a_better_coat_than_iron(self):
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item
        from ascii_warriors.engine.rng import RNG

        def clad(ids, mat):
            c = make_creature(RNG("t"), "dwarf", equip=False)
            for i in ids:
                c.inventory.equip(make_item(RNG("i"), i, material=mat))
            return self.heat.insulation(c)

        self.assertGreater(clad(("tunic", "trousers", "cloak"), "wool_cloth"),
                           clad(("mail_shirt", "greaves", "helm"), "iron"))

    def test_coverage_comes_out_of_the_body_table(self):
        self.assertGreater(self.heat.COVERAGE["torso"], self.heat.COVERAGE["hand"])
        self.assertAlmostEqual(sum(self.heat.COVERAGE.values()), 1.0, places=6)

    # -- what it does to you ------------------------------------------------- #

    def test_the_comfortable_band_costs_nothing(self):
        self.assertEqual(self.heat.strain(65.0, 0.0), 0.0)

    def test_cold_and_heat_pull_opposite_ways(self):
        self.assertLess(self.heat.strain(0.0), 0.0)
        self.assertGreater(self.heat.strain(120.0), 0.0)

    def test_clothes_help_in_the_cold_and_hurt_in_the_heat(self):
        self.assertGreater(self.heat.strain(20.0, 0.8), self.heat.strain(20.0, 0.0))
        self.assertGreater(self.heat.strain(100.0, 0.8), self.heat.strain(100.0, 0.0))

    def test_exposure_builds_over_time_rather_than_tripping(self):
        p = self.game.player
        p.exposure = 0.0
        self.heat.tick(p, -20.0, 60, self.game.rng)
        first = p.exposure
        self.assertLess(first, 0.0)
        self.assertGreater(first, -1.0)
        self.heat.tick(p, -20.0, 600, self.game.rng)
        self.assertLess(p.exposure, first)

    def test_coming_in_out_of_the_cold_is_faster_than_going_into_it(self):
        self.assertLess(self.heat.RECOVER_TICKS, self.heat.ADJUST_TICKS)
        p = self.game.player
        p.exposure = -0.8
        self.heat.tick(p, 65.0, 300, self.game.rng)
        self.assertGreater(p.exposure, -0.8)

    def test_exposure_never_passes_the_strain_it_is_chasing(self):
        p = self.game.player
        p.exposure = 0.0
        for _ in range(200):
            self.heat.tick(p, 36.0, 600, self.game.rng)
        self.assertGreaterEqual(p.exposure, self.heat.strain(36.0,
                                                             self.heat.insulation(p)))
        self.assertLessEqual(p.exposure, 0.0)

    def test_a_fire_imp_does_not_care(self):
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.engine.rng import RNG

        drake = make_creature(RNG("t"), "dragon")
        self.assertTrue(drake.defn.has("FIREIMMUNE"))
        self.assertTrue(self.heat.unaffected(drake))
        self.heat.tick(drake, 400.0, 6000, self.game.rng)
        self.assertEqual(drake.exposure, 0.0)

    def test_the_dead_do_not_shiver(self):
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.engine.rng import RNG

        z = make_creature(RNG("t"), "zombie")
        self.assertTrue(z.defn.has("UNDEAD"))
        self.heat.tick(z, -80.0, 6000, self.game.rng)
        self.assertEqual(z.exposure, 0.0)

    def test_but_the_living_do(self):
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.engine.rng import RNG

        c = make_creature(RNG("t"), "human", equip=False)
        self.assertFalse(self.heat.unaffected(c))
        self.heat.tick(c, -80.0, 600, self.game.rng)
        self.assertLess(c.exposure, 0.0)

    def test_severe_cold_takes_fingers(self):
        from ascii_warriors.engine.rng import RNG

        p = self.game.player
        p.exposure = -1.0
        rng = RNG("frost")
        before = sum(len(part.wounds) for part in p.body.parts.values())
        for _ in range(60):
            self.heat.tick(p, -60.0, 600, rng)
        after = sum(len(part.wounds) for part in p.body.parts.values())
        self.assertGreater(after, before)
        bitten = [part.id for part in p.body.parts.values() if part.wounds]
        self.assertTrue(any("digit" in b for b in bitten), bitten)

    def test_frostbite_goes_through_the_one_trap_table(self):
        from ascii_warriors.game import combat

        self.assertIn("frostbite", combat.TRAP_STRIKES)
        self.assertIn("fire", combat.TRAP_STRIKES)

    def test_a_trap_can_be_aimed(self):
        from ascii_warriors.game import combat
        from ascii_warriors.engine.rng import RNG

        hits = set()
        for i in range(30):
            r = combat.trap_strike(self.game.player, "frostbite",
                                   rng=RNG("aim%d" % i), prefer="DIGIT")
            if r.part:
                hits.add(r.part)
        self.assertTrue(hits)
        self.assertTrue(all("digit" in h for h in hits), hits)

    def test_heat_costs_you_water(self):
        p = self.game.player
        p.exposure = 0.9
        p.needs.thirst = 0
        self.heat.tick(p, 130.0, 600, self.game.rng)
        self.assertGreater(p.needs.thirst, 0)

    def test_the_weather_slows_you_when_it_is_bad_enough(self):
        p = self.game.player
        p.exposure = 0.0
        self.assertEqual(self.heat.speed_factor(p), 1.0)
        p.exposure = -0.95
        self.assertLess(self.heat.speed_factor(p), 1.0)
        self.assertGreaterEqual(self.heat.speed_factor(p), self.heat.SLOW_FLOOR)

    def test_exposure_has_a_word_for_itself(self):
        p = self.game.player
        p.exposure = 0.0
        self.assertEqual(self.heat.describe(p), "")
        p.exposure = -0.9
        self.assertIn("freezing", self.heat.describe(p))
        p.exposure = 0.9
        self.assertNotIn("freezing", self.heat.describe(p))

    # -- frost --------------------------------------------------------------- #

    def _pool(self):
        """A cell of open-air water on the adventure map."""
        lm = self.game.local
        p = self.game.player
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                c = (p.x + dx, p.y + dy, lm.surface_z(p.x + dx, p.y + dy))
                if lm.in_bounds(*c) and lm.is_outside(*c):
                    lm.set_tile(c[0], c[1], c[2], "shallow_water")
                    return c
        self.skipTest("nowhere to put a pool")

    def test_terrain_water_freezes_and_thaws_back(self):
        lm = self.game.local
        cell = self._pool()
        was = lm.tile(*cell)
        self.assertTrue(self.game.frost.freeze(lm, cell))
        self.assertEqual(lm.tile(*cell), "ice")
        self.assertTrue(self.game.frost.is_frozen(*cell))
        self.assertTrue(self.game.frost.thaw(lm, cell))
        self.assertEqual(lm.tile(*cell), was)
        self.assertFalse(self.game.frost.is_frozen(*cell))

    def test_rock_does_not_freeze(self):
        lm = self.game.local
        p = self.game.player
        cell = (p.x, p.y, p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "rock_wall")
        self.assertFalse(self.game.frost.freeze(lm, cell))

    def test_deep_water_is_left_alone(self):
        lm = self.game.local
        cell = self._pool()
        lm.set_tile(cell[0], cell[1], cell[2], "deep_water")
        self.assertIsNone(self.heat.liquid_freezes_at(lm, cell))
        self.assertFalse(self.game.frost.freeze(lm, cell))

    def test_ice_is_something_you_slip_on(self):
        # v3.14 has read the ICE flag since it shipped; nothing had ever put
        # an ice tile anywhere a player would walk.
        from ascii_warriors.world import tiles

        self.assertTrue(tiles.get(self.heat.ICE_TILE).has("ICE"))

    def test_freezing_swallows_the_fluid_layer_and_gives_it_back(self):
        from ascii_warriors.world.fluids import Water

        lm = self.game.local
        cell = self._pool()
        water = Water()
        water.set(cell, 3)
        self.assertTrue(self.game.frost.freeze(lm, cell, water))
        self.assertEqual(water.at(*cell), 0)
        self.assertEqual(lm.tile(*cell), "ice")
        self.assertTrue(self.game.frost.thaw(lm, cell, water))
        self.assertEqual(water.at(*cell), 3)

    def test_only_the_surface_of_deep_fluid_freezes(self):
        from ascii_warriors.world.fluids import Water

        lm = self.game.local
        cell = self._pool()
        water = Water()
        water.set(cell, 4)
        water.set((cell[0], cell[1], cell[2] + 1), 2)
        self.assertFalse(self.game.frost.freeze(lm, cell, water))

    def test_the_cold_only_looks_on_a_cadence(self):
        lm = self.game.local
        self._pool()
        first = self.game.frost.step(lm, self.game.rng, lambda c: -40.0, 0)
        again = self.game.frost.step(lm, self.game.rng, lambda c: -40.0, 1)
        self.assertGreater(first[0], 0)
        self.assertEqual(again, (0, 0))

    def test_a_warm_day_freezes_nothing(self):
        lm = self.game.local
        self._pool()
        froze, _thawed = self.game.frost.step(
            lm, self.game.rng, lambda c: 70.0, 0)
        self.assertEqual(froze, 0)

    def test_frost_survives_a_save(self):
        from ascii_warriors.game.state import Game

        lm = self.game.local
        cell = self._pool()
        self.game.frost.freeze(lm, cell)
        back = Game.from_dict(self.game.to_dict())
        self.assertTrue(back.frost.is_frozen(*cell))

    def test_exposure_survives_a_save(self):
        from ascii_warriors.game.state import Game

        self.game.player.exposure = -0.42
        back = Game.from_dict(self.game.to_dict())
        self.assertAlmostEqual(back.player.exposure, -0.42, places=3)

    # -- both modes ask the same question ------------------------------------ #

    def test_the_game_reads_a_temperature_at_a_cell(self):
        p = self.game.player
        t = self.game.temperature_at(p.x, p.y, p.z)
        self.assertIsInstance(t, float)
        self.assertGreater(t, -150.0)
        self.assertLess(t, 250.0)

    def test_standing_by_a_fire_is_warmer_than_not(self):
        lm = self.game.local
        p = self.game.player
        cold = self.game.temperature_at(p.x, p.y, p.z)
        cell = (p.x + 1, p.y, p.z)
        if not lm.in_bounds(*cell):
            self.skipTest("no room beside the player")
        lm.set_tile(cell[0], cell[1], cell[2], "tree")
        self.game.fire.ignite(lm, cell)
        self.assertGreater(self.game.temperature_at(p.x, p.y, p.z), cold)

    def test_a_deep_cell_is_steadier_than_the_surface(self):
        """Cave temperature down there, and it stays there all year.

        This used to ask for a cell twenty levels below the surface of a map
        that is eleven levels deep, so it skipped every single time it was
        ever run -- the one permanent skip in the suite, and invisible because
        a skip is silent. `heat.CAVE_DEPTH` is six, which the map does have
        room for, and "steadier" is now measured rather than assumed: half a
        year passes, the surface notices and the cave does not.
        """
        from ascii_warriors.data.calendar import TICKS_PER_YEAR

        lm = self.game.local
        column = next(
            ((x, y) for y in range(lm.height) for x in range(lm.width)
             if lm.surface_z(x, y) - self.heat.CAVE_DEPTH >= lm.zmin), None)
        self.assertIsNotNone(column, "no column has a cave's depth under it")
        x, y = column
        surf = lm.surface_z(x, y)
        deep = surf - self.heat.CAVE_DEPTH
        was_surf = self.game.temperature_at(x, y, surf)
        self.assertAlmostEqual(self.game.temperature_at(x, y, deep),
                               self.heat.CAVE_TEMP, places=4)
        self.game.time.ticks += TICKS_PER_YEAR // 2
        self.assertAlmostEqual(self.game.temperature_at(x, y, deep),
                               self.heat.CAVE_TEMP, places=4,
                               msg="the cave felt the season")
        self.assertNotAlmostEqual(self.game.temperature_at(x, y, surf),
                                  was_surf, places=2,
                                  msg="the surface did not")


class TestMapLayersStayOnTheirMap(GameFixture):
    """Fires, frost, traps and webs belong to a map, not to the player."""

    def _neighbour(self):
        p = self.game.player
        for nx, ny in self.game.world.neighbours(p.wx, p.wy):
            if not self.game.world.tile(nx, ny).is_ocean:
                return (nx, ny)
        self.skipTest("landlocked nowhere to go")

    def _light_something(self):
        from ascii_warriors.world import fire as fire_mod

        lm = self.game.local
        lit = 0
        for y in range(lm.height):
            for x in range(lm.width):
                cell = (x, y, lm.surface_z(x, y))
                if fire_mod.fuel_at(lm, cell) > 0 and self.game.fire.ignite(lm, cell):
                    lit += 1
            if lit >= 3:
                return lit
        if not lit:
            self.skipTest("nothing flammable on this map")
        return lit

    def test_a_fire_does_not_follow_you_to_another_map(self):
        here = (self.game.player.wx, self.game.player.wy)
        there = self._neighbour()
        self.game.enter_world_tile(*there)
        self.game.enter_world_tile(*here)
        self._light_something()
        self.assertTrue(self.game.fire.anything_burning)
        self.game.enter_world_tile(*there)
        self.assertFalse(self.game.fire.anything_burning)

    def test_but_it_is_still_burning_when_you_come_back(self):
        here = (self.game.player.wx, self.game.player.wy)
        there = self._neighbour()
        self.game.enter_world_tile(*there)
        self.game.enter_world_tile(*here)
        lit = self._light_something()
        self.game.enter_world_tile(*there)
        self.game.enter_world_tile(*here)
        self.assertEqual(len(self.game.fire.fuel), lit)

    def test_a_fresh_map_starts_clean(self):
        self.game._restore_layers({})
        self.assertFalse(self.game.fire.anything_burning)
        self.assertFalse(self.game.frost.any_ice)
        self.assertEqual(self.game.traps, {})
        self.assertEqual(self.game.webs, {})


class TestSwingTime(unittest.TestCase):
    """`prepare` and `recover`, on every attack since the table was written,
    finally costing somebody time."""

    def _who(self, race="dwarf"):
        from ascii_warriors.game.entity import make_creature

        return make_creature(RNG("swing"), race, equip=False)

    def _armed(self, wid, race="dwarf", material="iron", skill=0):
        from ascii_warriors.game.item import make_item

        c = self._who(race)
        it = make_item(RNG("i"), wid, material=material)
        c.inventory.equip(it)
        if skill:
            c.skills.set_level(it.defn.weapon.skill, skill)
        return c, it

    def _blows(self, c, it):
        from ascii_warriors.data.items import PUNCH
        from ascii_warriors.game import combat

        attacks = it.defn.weapon.attacks if it is not None else (PUNCH,)
        costs = [combat.attack_cost(c, it, a) for a in attacks]
        return ACTION_COST * len(costs) / float(sum(costs))

    # -- the dead fields ----------------------------------------------------- #

    def test_swing_time_is_prepare_plus_recover(self):
        from ascii_warriors.data.items import ITEMS
        from ascii_warriors.game import combat

        a = ITEMS["maul"].weapon.attacks[0]
        self.assertEqual(combat.swing_time(a), a.prepare + a.recover)
        self.assertGreater(a.prepare, 0)

    def test_chopping_is_slower_than_thrusting(self):
        from ascii_warriors.data.items import ITEMS
        from ascii_warriors.game import combat

        hack = next(a for a in ITEMS["battle_axe"].weapon.attacks
                    if a.name == "hack")
        stab = next(a for a in ITEMS["spear"].weapon.attacks if a.name == "stab")
        self.assertGreater(combat.swing_time(hack), combat.swing_time(stab))

    def test_an_axe_lands_fewer_blows_than_a_sword(self):
        sword, si = self._armed("sword")
        axe, ai = self._armed("battle_axe")
        self.assertGreater(self._blows(sword, si), self._blows(axe, ai))

    def test_a_bare_fist_is_the_quickest_thing_there_is(self):
        c = self._who()
        fastest = self._blows(c, None)
        for wid in ("dagger", "sword", "spear", "maul"):
            armed, it = self._armed(wid)
            self.assertGreater(fastest, self._blows(armed, it), wid)

    # -- weight -------------------------------------------------------------- #

    def test_a_weapon_you_can_barely_lift_is_slow(self):
        from ascii_warriors.game import combat

        small, it = self._armed("maul", race="kobold")
        big, it2 = self._armed("maul", race="human")
        self.assertGreater(combat.heft(small, it), 1.0)
        self.assertLess(self._blows(small, it), self._blows(big, it2))

    def test_the_same_maul_is_quicker_in_stronger_hands(self):
        dwarf, di = self._armed("maul", race="dwarf")
        human, hi = self._armed("maul", race="human")
        self.assertGreater(self._blows(human, hi), self._blows(dwarf, di))

    def test_a_light_weapon_costs_nothing_extra_to_anybody(self):
        from ascii_warriors.game import combat

        for race in ("dwarf", "human", "kobold"):
            c, it = self._armed("dagger", race=race)
            self.assertLessEqual(combat.heft(c, it), 1.0, race)

    def test_bare_hands_have_no_heft(self):
        from ascii_warriors.game import combat

        self.assertEqual(combat.heft(self._who(), None), 0.0)

    # -- skill --------------------------------------------------------------- #

    def test_skill_buys_you_time(self):
        raw, ri = self._armed("maul", skill=0)
        able, ai = self._armed("maul", skill=15)
        self.assertGreater(self._blows(able, ai), self._blows(raw, ri))

    def test_but_never_without_limit(self):
        from ascii_warriors.game import combat

        c, it = self._armed("maul", skill=20)
        a = it.defn.weapon.attacks[0]
        self.assertGreaterEqual(combat.attack_cost(c, it, a),
                                int(ACTION_COST * combat.FASTEST))

    def test_the_band_holds_at_both_ends(self):
        from ascii_warriors.data.items import PUNCH
        from ascii_warriors.game import combat

        floor = int(ACTION_COST * combat.FASTEST)
        ceiling = int(ACTION_COST * combat.SLOWEST)
        self.assertEqual(combat.attack_cost(self._who(), None, PUNCH), floor)
        small, it = self._armed("maul", race="kobold")
        self.assertLessEqual(
            combat.attack_cost(small, it, it.defn.weapon.attacks[0]), ceiling)

    # -- it reaches the scheduler -------------------------------------------- #

    def test_a_strike_reports_what_it_cost(self):
        from ascii_warriors.game import combat

        a, it = self._armed("maul")
        d = self._who("human")
        r = combat.melee_attack(a, d, rng=RNG("hit"))
        self.assertGreater(r.cost, ACTION_COST)

    def test_and_a_quick_one_reports_less(self):
        from ascii_warriors.game import combat

        a = self._who()
        d = self._who("human")
        r = combat.melee_attack(a, d, rng=RNG("hit"))
        self.assertLess(r.cost, ACTION_COST)

    def test_the_fortress_banks_time_instead_of_spending_it(self):
        """A fortress steps everyone once a step, so a slow weapon has to
        wait rather than cost."""
        from ascii_warriors.game import combat

        a, it = self._armed("maul")
        cost = combat.attack_cost(a, it, it.defn.weapon.attacks[0])
        swings = 0
        for _ in range(20):
            d = self._who("human")      # a fresh target, so nobody dies early
            if combat.timed_strike(a, d, rng=RNG("bank")) is not None:
                swings += 1
        self.assertEqual(swings, 20 * ACTION_COST // cost)
        self.assertLess(swings, 20)

    def test_a_quick_fighter_never_waits(self):
        from ascii_warriors.game import combat

        a = self._who()          # bare hands: cheaper than a standard action
        d = self._who("human")
        for _ in range(6):
            self.assertIsNotNone(combat.timed_strike(a, d, rng=RNG("q")))

    def test_the_bank_survives_a_save(self):
        from ascii_warriors.game.entity import Creature

        c = self._who()
        c.swing_bank = 37.0
        self.assertAlmostEqual(
            Creature.from_dict(c.to_dict()).swing_bank, 37.0, places=2)

    # -- what the player is told --------------------------------------------- #

    def test_a_weapon_says_how_quick_it_is(self):
        from ascii_warriors.game.item import speed_word

        c, maul = self._armed("maul")
        text = " ".join(maul.full_description(c))
        self.assertIn("Speed: slow", text)
        self.assertIn("blows per turn", text)
        self.assertIn("heavy for you", text)
        self.assertEqual(speed_word(4.0), "fast")

    def test_and_a_quick_one_says_so(self):
        c, pike = self._armed("pike")
        self.assertIn("Speed: fast", " ".join(pike.full_description(c)))

    def test_a_description_still_works_with_nobody_holding_it(self):
        from ascii_warriors.game.item import make_item

        text = " ".join(make_item(RNG("i"), "maul", material="iron")
                        .full_description())
        self.assertIn("Speed: slow", text)
        self.assertNotIn("blows per turn", text)


class TestWear(GameFixture):
    """`wear_tick` was called from one place and its answer thrown away."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import wear

        self.wear = wear

    def _item(self, wid, material="iron"):
        from ascii_warriors.game.item import make_item

        return make_item(RNG("i"), wid, material=material)

    # -- the scale ----------------------------------------------------------- #

    def test_wear_stops_at_the_end_of_the_scale(self):
        it = self._item("sword")
        rng = RNG("w")
        for _ in range(5000):
            it.wear_tick(rng)
        self.assertEqual(it.wear, it.MAX_WEAR)

    def test_and_so_the_factor_never_goes_negative(self):
        # 1 - 0.15 * wear is negative from 7 up, and momentum multiplies by it.
        it = self._item("sword")
        rng = RNG("w")
        for _ in range(5000):
            it.wear_tick(rng)
        self.assertGreater(it.wear_factor(), 0.0)

    def test_a_ruined_item_keeps_saying_it_is_finished(self):
        it = self._item("tunic", material="wool_cloth")
        it.wear = it.MAX_WEAR
        rng = RNG("w")
        self.assertTrue(any(it.wear_tick(rng) for _ in range(2000)))

    def test_an_artifact_never_wears(self):
        it = self._item("sword")
        it.artifact_id = 1
        rng = RNG("w")
        for _ in range(3000):
            self.assertFalse(it.wear_tick(rng))
        self.assertEqual(it.wear, 0)

    def test_metal_outlasts_cloth(self):
        # Over many items, not one: at 0.4% against 1.2% a single pair is
        # mostly noise, and a test that only passes on a lucky seed is not
        # measuring anything.
        rng = RNG("w")
        metal = [self._item("sword", "iron") for _ in range(40)]
        cloth = [self._item("tunic", "wool_cloth") for _ in range(40)]
        for _ in range(120):
            for it in metal:
                it.wear_tick(rng)
            for it in cloth:
                it.wear_tick(rng)
        self.assertLess(sum(i.wear for i in metal), sum(i.wear for i in cloth))

    # -- destruction --------------------------------------------------------- #

    def test_destroy_takes_an_item_off_the_body_and_out_of_the_pack(self):
        p = self.game.player
        it = self._item("tunic", "wool_cloth")
        p.inventory.equip(it)
        self.assertIn(it, p.inventory.items)
        self.wear.destroy(p, it, log=self.game.log)
        self.assertNotIn(it, p.inventory.items)
        self.assertNotIn(it, list(p.inventory.equipped.values()))

    def test_and_off_the_floor_too(self):
        p = self.game.player
        it = self._item("tunic", "wool_cloth")
        cell = (p.x, p.y, p.z)
        self.game.items_on_ground.setdefault(cell, []).append(it)
        self.wear.destroy(p, it, world=self.game)
        self.assertNotIn(it, self.game.items_at(*cell))

    def test_losing_your_clothes_is_worth_a_thought(self):
        p = self.game.player
        p.needs.thoughts.clear()
        it = self._item("tunic", "wool_cloth")
        p.inventory.equip(it)
        self.wear.destroy(p, it)
        self.assertTrue(any("rags" in t[0] for t in p.needs.thoughts))

    def test_losing_a_sword_is_not(self):
        p = self.game.player
        p.needs.thoughts.clear()
        it = self._item("sword")
        p.inventory.equip(it)
        self.wear.destroy(p, it)
        self.assertFalse(any("rags" in t[0] for t in p.needs.thoughts))

    # -- what wears ---------------------------------------------------------- #

    def test_a_weapon_wears_from_landing_blows(self):
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        # 0.4% a landed blow, so one weapon over a few hundred swings is a
        # coin-flip; ten of them is not.
        rng = RNG("fight")
        total = 0
        for _ in range(10):
            a = make_creature(rng, "dwarf", equip=False)
            it = self._item("sword")
            a.inventory.equip(it)
            a.skills.set_level("swordsmanship", 12)
            for _ in range(300):
                d = make_creature(rng, "human", equip=False)
                combat.melee_attack(a, d, rng=rng)
                if it not in a.inventory.items:
                    break
            total += it.wear
        self.assertGreater(total, 0)

    def test_armour_wears_from_stopping_them(self):
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        rng = RNG("fight2")
        worn = 0
        for _ in range(40):
            a = make_creature(rng, "dwarf", equip=False)
            d = make_creature(rng, "human", equip=False)
            plate = self._item("breastplate")
            d.inventory.equip(plate)
            for _ in range(60):
                combat.melee_attack(a, d, rng=rng)
                if d.body.dead:
                    break
            worn += plate.wear
        self.assertGreater(worn, 0)

    def test_clothing_wears_from_being_worn(self):
        p = self.game.player
        shirt = self._item("tunic", "wool_cloth")
        p.inventory.equip(shirt)
        rng = RNG("time")
        for _ in range(400):
            self.wear.wearing(p, rng)
            if shirt not in p.inventory.items:
                return
        self.assertGreater(shirt.wear, 0)

    def test_armour_is_not_worn_out_by_the_clock(self):
        """It wears from being hit, which is a different clock."""
        p = self.game.player
        plate = self._item("breastplate")
        p.inventory.equip(plate)
        rng = RNG("time")
        for _ in range(600):
            self.wear.wearing(p, rng)
        self.assertEqual(plate.wear, 0)

    def test_the_check_runs_on_a_cadence(self):
        p = self.game.player
        p.next_wear_check = 0
        self.assertTrue(self.wear.due(p, 0))
        self.wear.mark(p, 0)
        self.assertFalse(self.wear.due(p, self.wear.CLOTH_TICKS - 1))
        self.assertTrue(self.wear.due(p, self.wear.CLOTH_TICKS))

    def test_the_cadence_survives_a_save(self):
        from ascii_warriors.game.state import Game

        self.game.player.next_wear_check = 4242
        back = Game.from_dict(self.game.to_dict())
        self.assertEqual(back.player.next_wear_check, 4242)

    def test_dressed_knows_the_difference(self):
        from ascii_warriors.game.entity import make_creature

        c = make_creature(RNG("n"), "dwarf", equip=False)
        self.assertFalse(self.wear.dressed(c))
        c.inventory.equip(self._item("tunic", "wool_cloth"))
        self.assertTrue(self.wear.dressed(c))

    # -- the whetstone ------------------------------------------------------- #

    def test_a_whetstone_puts_an_edge_back(self):
        from ascii_warriors.game.item import Item

        p = self.game.player
        blade = self._item("sword")
        blade.wear = 2
        p.inventory.equip(blade)
        p.inventory.add(Item("whetstone", "granite"))
        for _ in range(12):
            self.wear.sharpen(p, blade, RNG("s%d" % blade.wear))
            if blade.wear < 2:
                break
        self.assertLess(blade.wear, 2)

    def test_but_not_without_one(self):
        p = self.game.player
        blade = self._item("sword")
        blade.wear = 2
        p.inventory.equip(blade)
        self.assertIn("no whetstone", self.wear.sharpen(p, blade, RNG("s")))
        self.assertEqual(blade.wear, 2)

    def test_and_not_on_a_maul(self):
        from ascii_warriors.game.item import Item

        p = self.game.player
        maul = self._item("maul")
        maul.wear = 2
        p.inventory.add(Item("whetstone", "granite"))
        self.assertIn("no edge", self.wear.sharpen(p, maul, RNG("s")))
        self.assertEqual(maul.wear, 2)
        self.assertFalse(self.wear.can_sharpen(maul))
        self.assertTrue(self.wear.can_sharpen(self._item("sword")) is False)

    def test_nor_on_something_already_sharp(self):
        from ascii_warriors.game.item import Item

        p = self.game.player
        blade = self._item("sword")
        p.inventory.add(Item("whetstone", "granite"))
        self.assertIn("already", self.wear.sharpen(p, blade, RNG("s")))

    def test_the_action_reaches_the_player(self):
        from ascii_warriors.game import actions
        from ascii_warriors.game.item import Item

        p = self.game.player
        blade = self._item("sword")
        blade.wear = 3
        p.inventory.equip(blade)
        p.inventory.add(Item("whetstone", "granite"))
        for _ in range(12):
            actions.sharpen(self.game)
            if blade.wear < 3:
                return
        self.fail("sharpening never took")

    # -- flint and steel ----------------------------------------------------- #

    def test_flint_and_steel_lights_what_a_torch_would(self):
        from ascii_warriors.game import actions
        from ascii_warriors.game.item import Item
        from ascii_warriors.world import fire as fire_mod

        p = self.game.player
        lm = self.game.local
        cell = (p.x, p.y, p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "tree")
        for it in list(p.inventory.items):
            if it.is_light:
                p.inventory.items.remove(it)
                p.inventory.unequip_item(it)
        self.assertFalse(fire_mod.carrying_flame(p))
        actions.set_fire(self.game)
        self.assertFalse(self.game.fire.anything_burning)
        p.inventory.add(Item("flint_and_steel", "iron"))
        actions.set_fire(self.game)
        self.assertTrue(self.game.fire.anything_burning)


class TestSkillsYouWereSold(GameFixture):
    """Skills in the table, handed out at character creation, never read."""

    # -- what a blow is done with -------------------------------------------- #

    def test_a_punch_a_kick_and_a_bite_are_three_different_things(self):
        from ascii_warriors.data.items import BITE, KICK, PUNCH
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        c = make_creature(RNG("c"), "human", equip=False)
        self.assertEqual(combat.skill_for_attack(c, None, PUNCH), "striker")
        self.assertEqual(combat.skill_for_attack(c, None, KICK), "kicker")
        self.assertEqual(combat.skill_for_attack(c, None, BITE), "biter")

    def test_a_weapon_still_decides_when_there_is_one(self):
        from ascii_warriors.data.items import PUNCH
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item

        c = make_creature(RNG("c"), "human", equip=False)
        sword = make_item(RNG("i"), "sword", material="iron")
        self.assertEqual(combat.skill_for_attack(c, sword, PUNCH), "sword")

    def test_grappling_is_still_wrestling(self):
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        c = make_creature(RNG("c"), "human", equip=False)
        self.assertEqual(combat.skill_for_attack(c, None, None), "wrestling")

    def test_a_dragon_finally_bites_with_its_biting(self):
        from ascii_warriors.data.creatures import CREATURES
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        drake = make_creature(RNG("d"), "dragon", equip=False)
        bite = next(na.attack for na in CREATURES["dragon"].attacks
                    if na.attack.name == "bite")
        self.assertGreater(drake.skills.level("biter"), 8)
        self.assertEqual(combat.skill_for_attack(drake, None, bite), "biter")

    def test_skill_makes_an_unarmed_blow_harder(self):
        from ascii_warriors.data.items import PUNCH
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        raw = make_creature(RNG("c"), "human", equip=False)
        able = make_creature(RNG("c"), "human", equip=False)
        able.skills.set_level("striker", 10)
        self.assertGreater(combat.compute_momentum(able, None, PUNCH),
                           combat.compute_momentum(raw, None, PUNCH))

    def test_and_wrestling_no_longer_does(self):
        """It governs grappling; punching has its own skill now."""
        from ascii_warriors.data.items import PUNCH
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        raw = make_creature(RNG("c"), "human", equip=False)
        grappler = make_creature(RNG("c"), "human", equip=False)
        grappler.skills.set_level("wrestling", 10)
        self.assertEqual(combat.compute_momentum(grappler, None, PUNCH),
                         combat.compute_momentum(raw, None, PUNCH))

    def test_the_species_authored_as_body_fighters_kept_their_teeth(self):
        """Eight creatures had `wrestling` because that is what was read."""
        from ascii_warriors.data.creatures import CREATURES

        for cid in ("troll", "ogre", "cyclops", "bronze_colossus",
                    "night_troll", "zombie", "demon", "gorilla"):
            skills = CREATURES[cid].skills
            self.assertIn("wrestling", skills, cid)
            for specific in ("striker", "kicker", "biter"):
                self.assertIn(specific, skills, "%s lost its %s" % (cid, specific))

    def test_a_wrestler_is_better_at_it_than_a_peasant(self):
        from ascii_warriors.data.items import PUNCH
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.ui.charcreate import PROFESSIONS

        peasant = make_creature(RNG("c"), "human", equip=False)
        wrestler = make_creature(RNG("c"), "human", equip=False)
        for k, v in PROFESSIONS["wrestler"][1].items():
            wrestler.skills.set_level(k, v)
        self.assertGreater(combat.compute_momentum(wrestler, None, PUNCH),
                           combat.compute_momentum(peasant, None, PUNCH))

    # -- lying --------------------------------------------------------------- #

    def _talker(self, profession="thief"):
        from ascii_warriors.ui.charcreate import PROFESSIONS

        p = self.game.player
        for k, v in PROFESSIONS[profession][1].items():
            p.skills.set_level(k, v)
        p.kills = []
        return p

    def _listener(self, seed="l"):
        from ascii_warriors.game.entity import make_creature

        return make_creature(RNG(seed), "human", equip=False)

    def _brag(self, speaker, listener):
        from ascii_warriors.game import conversation as conv

        return " ".join(f.text for f in
                        conv.say(speaker, listener, "brag", self.game))

    def test_someone_with_nothing_and_no_gift_for_it_says_so(self):
        p = self.game.player
        p.kills = []
        for sid, _lv in list(p.skills.known()):
            p.skills.set_level(sid, 0)
        self.assertIn("nothing worth the telling",
                      self._brag(p, self._listener()))

    def test_but_a_liar_tries_anyway(self):
        p = self._talker("thief")
        self.assertGreater(p.skills.level("lying"), 0)
        self.assertIn("story about yourself", self._brag(p, self._listener()))

    def test_the_lie_lands_sometimes_and_not_others(self):
        from ascii_warriors.game import conversation as conv

        p = self._talker("thief")
        seen = set()
        for i in range(120):
            text = self._brag(p, self._listener("l%d" % i))
            seen.add("quite a life" in text or "many like you" in text
                     or "welcome at my table" in text)
        self.assertEqual(seen, {True, False})
        self.assertGreater(conv.lie_chance(p, self._listener()), 0.0)

    def test_a_better_liar_is_believed_more_often(self):
        from ascii_warriors.game import conversation as conv

        p = self._talker("thief")
        listener = self._listener()
        p.skills.set_level("lying", 2)
        poor = conv.lie_chance(p, listener)
        p.skills.set_level("lying", 12)
        self.assertGreater(conv.lie_chance(p, listener), poor)

    def test_an_observant_listener_is_harder_to_fool(self):
        from ascii_warriors.game import conversation as conv

        p = self._talker("thief")
        dull = self._listener("a")
        sharp = self._listener("b")
        dull.skills.set_level("observer", 0)
        sharp.skills.set_level("observer", 8)
        self.assertGreater(conv.lie_chance(p, dull), conv.lie_chance(p, sharp))

    def test_real_deeds_are_not_a_lie(self):
        p = self.game.player
        p.kills = ["a hydra"]
        self.assertIn("notable kills", self._brag(p, self._listener()))

    def test_nor_is_a_reputation(self):
        p = self.game.player
        p.kills = []
        p.skills.set_level("sword", 9)
        text = self._brag(p, self._listener())
        self.assertIn("reputation as a swordsman", text)

    # -- writing ------------------------------------------------------------- #

    def _scholar(self):
        from ascii_warriors.ui.charcreate import PROFESSIONS

        p = self.game.player
        for k, v in PROFESSIONS["scholar"][1].items():
            p.skills.set_level(k, v)
        return p

    def test_a_scholar_can_write_and_an_illiterate_cannot(self):
        from ascii_warriors.game import books

        p = self._scholar()
        self.assertTrue(books.can_write(p))
        p.skills.set_level("writing", 0)
        self.assertFalse(books.can_write(p))

    def test_a_blank_book_is_writable_and_a_full_one_is_not(self):
        from ascii_warriors.game import books
        from ascii_warriors.game.item import Item

        blank = Item("book", "leather")
        self.assertTrue(books.writable(blank))
        books.bind(self.game.world, self.game.rng, blank)
        self.assertFalse(books.writable(blank))

    def test_you_can_only_write_what_you_know(self):
        from ascii_warriors.game import books

        p = self._scholar()
        kinds = {k for k, _p in books.subjects_for(p)}
        self.assertIn("history", kinds)
        self.assertNotIn("swordsmanship", kinds)
        p.skills.set_level("sword", 8)
        self.assertIn("swordsmanship", {k for k, _p in books.subjects_for(p)})

    def test_a_better_writer_writes_a_deeper_book(self):
        from ascii_warriors.game import books

        p = self._scholar()
        p.skills.set_level("writing", 1)
        poor = books.write_depth(p, "history")
        p.skills.set_level("writing", 14)
        self.assertGreater(books.write_depth(p, "history"), poor)
        self.assertLessEqual(books.write_depth(p, "history"), books.MAX_DEPTH)

    def test_writing_a_book_fills_it_and_signs_it(self):
        from ascii_warriors.game import books
        from ascii_warriors.game.item import Item

        p = self._scholar()
        blank = Item("book", "leather")
        book, said = books.write(self.game.world, self.game.rng, p, blank,
                                 "history")
        self.assertIsNotNone(book)
        self.assertEqual(books.of(blank), book)
        self.assertEqual(book.author, p.display_name())
        self.assertIn(book.title, said)
        self.assertFalse(books.writable(blank))

    def test_you_do_not_learn_from_your_own_book(self):
        from ascii_warriors.game import books
        from ascii_warriors.game.item import Item

        p = self._scholar()
        blank = Item("book", "leather")
        book, _said = books.write(self.game.world, self.game.rng, p, blank,
                                  "history")
        self.assertTrue(books.already_read(p, book))

    def test_the_action_takes_real_time(self):
        from ascii_warriors.game import actions, books
        from ascii_warriors.game.item import Item

        p = self._scholar()
        p.inventory.add(Item("book", "leather"))
        cost = actions.write_book(self.game)
        self.assertGreater(cost, 100)
        self.assertTrue(any(books.of(i) is not None for i in p.inventory.items))

    def test_and_refuses_without_a_blank_book(self):
        from ascii_warriors.game import actions, books

        p = self._scholar()
        for i in list(p.inventory.items):
            if books.writable(i):
                p.inventory.items.remove(i)
        self.assertEqual(actions.write_book(self.game), 0)

    def test_there_is_something_to_write_in(self):
        from ascii_warriors.game.crafting import RECIPES

        self.assertIn("book", {r.output for r in RECIPES.values()})


class TestNerve(GameFixture):
    """`allies_near` was complete, correct and called by nothing."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import morale

        self.morale = morale
        for c in list(self.game.creatures.values()):
            if not c.is_player:
                self.game.creatures.pop(c.id, None)

    def _beast(self, cid="wolf", seed="w", n=0):
        from ascii_warriors.game.entity import make_creature

        p = self.game.player
        c = make_creature(RNG(seed), cid, faction="wild")
        c.x, c.y, c.z = p.x + 1 + (n % 3), p.y + (n // 3), p.z
        self.game.creatures[c.id] = c
        return c

    # -- company ------------------------------------------------------------- #

    def test_allies_near_is_finally_called(self):
        one = self._beast(seed="a", n=0)
        self.assertEqual(self.morale.company(one, self.game), [])
        two = self._beast(seed="b", n=1)
        self.assertIn(two, self.morale.company(one, self.game))

    def test_the_other_side_is_not_company(self):
        wolf = self._beast(seed="a")
        self.assertNotIn(self.game.player, self.morale.company(wolf, self.game))

    def test_numbers_steady_a_creature(self):
        subject = self._beast(seed="fixed", n=0)
        alone = self.morale.nerve(subject, self.game)
        for i in range(1, 4):
            self._beast(seed="f%d" % i, n=i)
        self.assertGreater(self.morale.nerve(subject, self.game), alone)

    def test_but_only_up_to_a_point(self):
        subject = self._beast(seed="fixed", n=0)
        for i in range(1, self.morale.MAX_COMPANY + 1):
            self._beast(seed="g%d" % i, n=i)
        capped = self.morale.nerve(subject, self.game)
        for i in range(20, 26):
            self._beast(seed="h%d" % i, n=i % 3)
        self.assertAlmostEqual(self.morale.nerve(subject, self.game), capped,
                               places=6)

    def test_a_pack_animal_takes_being_alone_hard(self):
        from ascii_warriors.data.creatures import CREATURES

        self.assertTrue(CREATURES["wolf"].has("PACK"))
        lone = self._beast(cid="wolf", seed="fixed", n=0)
        alone = self.morale.nerve(lone, self.game)
        self._beast(cid="wolf", seed="mate", n=1)
        together = self.morale.nerve(lone, self.game)
        self.assertGreater(together - alone,
                           self.morale.ALLY_NERVE)   # more than one ally's worth

    # -- shock --------------------------------------------------------------- #

    def test_watching_an_ally_fall_shakes_you(self):
        watcher = self._beast(seed="a", n=0)
        victim = self._beast(seed="b", n=1)
        self.assertEqual(watcher.shaken, 0.0)
        self.morale.saw_death(self.game, victim)
        self.assertGreater(watcher.shaken, 0.0)

    def test_but_not_from_across_the_map(self):
        watcher = self._beast(seed="a", n=0)
        victim = self._beast(seed="b", n=1)
        victim.x += self.morale.COMPANY_RANGE + 5
        self.morale.saw_death(self.game, victim)
        self.assertEqual(watcher.shaken, 0.0)

    def test_nor_when_it_was_on_the_other_side(self):
        watcher = self._beast(seed="a", n=0)
        self.morale.saw_death(self.game, self.game.player)
        self.assertEqual(watcher.shaken, 0.0)

    def test_a_pack_takes_it_harder(self):
        wolf = self._beast(cid="wolf", seed="a", n=0)
        boar = self._beast(cid="human", seed="b", n=0)
        victim = self._beast(seed="v", n=1)
        wolf.faction = boar.faction = victim.faction = "wild"
        self.morale.saw_death(self.game, victim)
        self.assertGreater(wolf.shaken, boar.shaken)

    def test_the_shock_wears_off(self):
        c = self._beast(seed="a")
        self.morale.shake(c, 0.6)
        self.morale.steady(c, self.morale.SHOCK_DECAY_TICKS // 2)
        self.assertLess(c.shaken, 0.6)
        self.morale.steady(c, self.morale.SHOCK_DECAY_TICKS * 5)
        self.assertEqual(c.shaken, 0.0)

    def test_and_it_cannot_pile_up_for_ever(self):
        c = self._beast(seed="a")
        for _ in range(50):
            self.morale.shake(c, 0.5)
        self.assertLessEqual(c.shaken, self.morale.MAX_SHOCK)

    def test_a_death_reaches_the_shock_through_the_game(self):
        watcher = self._beast(seed="a", n=0)
        victim = self._beast(seed="b", n=1)
        victim.body.dead = True
        victim.body.death_cause = "slain"
        self.game.kill_creature(victim)
        self.assertGreater(watcher.shaken, 0.0)

    # -- breaking ------------------------------------------------------------ #

    def test_the_last_one_standing_breaks(self):
        pack = [self._beast(cid="wolf", seed="p%d" % i, n=i) for i in range(4)]
        self.assertFalse(self.morale.broke(pack[0], self.game))
        for victim in pack[1:]:
            self.morale.saw_death(self.game, victim)
            self.game.creatures.pop(victim.id, None)
        self.assertTrue(self.morale.broke(pack[0], self.game))

    def test_and_the_ai_sends_it_running(self):
        from ascii_warriors.game import ai

        pack = [self._beast(cid="wolf", seed="q%d" % i, n=i) for i in range(4)]
        for c in pack:
            c.hostile_to.add("player")
            c.ai = ai.AIState("hunt")
        for victim in pack[1:]:
            self.morale.saw_death(self.game, victim)
            self.game.creatures.pop(victim.id, None)
        self.assertEqual(ai.pick_mode(pack[0], self.game), "flee")

    def test_the_fearless_never_break(self):
        from ascii_warriors.data.creatures import CREATURES

        self.assertTrue(CREATURES["goblin"].has("NO_FEAR"))
        gob = self._beast(cid="goblin", seed="g")
        self.morale.shake(gob, self.morale.MAX_SHOCK)
        gob.body.apply_damage("upper_body", "edge", 40000, 100, 2000, RNG("h"))
        self.assertTrue(self.morale.fearless(gob))
        self.assertFalse(self.morale.broke(gob, self.game))
        self.assertEqual(self.morale.nerve(gob, self.game), 1.0)

    def test_nor_do_the_dead_or_the_enormous(self):
        for cid in ("zombie", "dragon"):
            c = self._beast(cid=cid, seed=cid)
            self.assertTrue(self.morale.fearless(c), cid)

    def test_the_old_call_still_works_without_a_world(self):
        """`opportunity_to_flee` is the name the AI has always used."""
        from ascii_warriors.game import combat

        c = self._beast(cid="wolf", seed="a")
        self.assertFalse(combat.opportunity_to_flee(c))
        self.assertIsInstance(combat.opportunity_to_flee(c, self.game), bool)

    def test_nerve_has_a_word_for_itself(self):
        c = self._beast(cid="wolf", seed="fixed", n=0)
        for i in range(1, 5):
            self._beast(cid="wolf", seed="s%d" % i, n=i)
        self.assertEqual(self.morale.describe(c, self.game), "")
        self.morale.shake(c, self.morale.MAX_SHOCK)
        self.assertIn(self.morale.describe(c, self.game),
                      ("wavering", "breaking"))

    def test_being_shaken_survives_a_save(self):
        from ascii_warriors.game.state import Game

        self.game.player.shaken = 0.55
        back = Game.from_dict(self.game.to_dict())
        self.assertAlmostEqual(back.player.shaken, 0.55, places=3)


class TestFoodChain(GameFixture):
    """`diet` classified eighty species and nothing read it; nothing wild had
    ever eaten or drunk anything."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import feeding

        self.feeding = feeding
        for c in list(self.game.creatures.values()):
            if not c.is_player:
                self.game.creatures.pop(c.id, None)

    def _beast(self, cid, seed="b", n=0):
        from ascii_warriors.game.entity import make_creature

        p = self.game.player
        c = make_creature(RNG(seed), cid, faction="wild")
        c.x, c.y, c.z = p.x + 1 + (n % 3), p.y + (n // 3), p.z
        self.game.creatures[c.id] = c
        return c

    # -- diet ---------------------------------------------------------------- #

    def test_diet_is_finally_read(self):
        wolf = self._beast("wolf")
        deer = self._beast("deer", n=1)
        self.assertEqual(wolf.defn.diet, "carnivore")
        self.assertEqual(deer.defn.diet, "herbivore")
        self.assertTrue(self.feeding.eats_meat(wolf))
        self.assertFalse(self.feeding.eats_plants(wolf))
        self.assertTrue(self.feeding.eats_plants(deer))
        self.assertFalse(self.feeding.eats_meat(deer))

    def test_a_wolf_eats_a_deer_though_a_deer_is_bigger(self):
        wolf = self._beast("wolf")
        deer = self._beast("deer", n=1)
        self.assertGreater(deer.defn.size, wolf.defn.size)
        self.assertTrue(self.feeding.is_prey(wolf, deer))

    def test_but_not_a_bear(self):
        wolf = self._beast("wolf")
        bear = self._beast("grizzly_bear", n=1)
        self.assertFalse(self.feeding.is_prey(wolf, bear))

    def test_and_a_deer_eats_nobody(self):
        deer = self._beast("deer")
        rabbit = self._beast("rabbit", n=1)
        self.assertFalse(self.feeding.is_prey(deer, rabbit))

    def test_numbers_extend_what_a_pack_will_take_on(self):
        # A wolf is 40 litres and reaches three times that alone; an elk is
        # 300, which is beyond it until there are others with it.
        wolf = self._beast("wolf")
        elk = self._beast("elk", n=1)
        self.assertFalse(self.feeding.is_prey(wolf, elk))
        self.assertTrue(self.feeding.is_prey(wolf, elk, pack=3))

    def test_people_are_not_prey(self):
        wolf = self._beast("wolf")
        self.assertFalse(self.feeding.is_prey(wolf, self.game.player))
        villager = self._beast("human", n=1)
        self.assertFalse(self.feeding.is_prey(wolf, villager))

    def test_a_hungry_hunter_looks_for_something(self):
        wolf = self._beast("wolf")
        deer = self._beast("deer", n=1)
        wolf.needs.hunger = 0
        self.assertIsNone(self.feeding.prey_for(wolf, self.game))
        wolf.needs.hunger = self.feeding.HUNGRY_AT + 1
        self.assertIs(self.feeding.prey_for(wolf, self.game), deer)

    def test_and_the_ai_goes_after_it(self):
        from ascii_warriors.game import ai

        wolf = self._beast("wolf")
        self._beast("deer", n=1)
        wolf.needs.hunger = self.feeding.HUNGRY_AT + 1
        wolf.needs.thirst = 0
        self.assertEqual(ai.pick_mode(wolf, self.game), "hunt")

    def test_prey_runs_from_a_predator_now(self):
        from ascii_warriors.game import wild

        # People alarm everything and always did, so put the deer somewhere
        # there is nobody but the wolf: what is being tested is the wolf.
        for c in list(self.game.creatures.values()):
            if c is not self.game.player:
                self.game.creatures.pop(c.id, None)
        self.game.creatures.pop(self.game.player.id, None)
        deer = self._beast("deer")
        wolf = self._beast("wolf", n=1)
        # v3.13 asked only about AMBUSHER and SAVAGE.
        self.assertTrue(self.feeding.hunted_by(deer, wolf))
        self.assertIs(wild.frightener(self.game, deer), wolf)

    # -- feeding ------------------------------------------------------------- #

    def test_a_grazer_standing_on_grass_eats(self):
        deer = self._beast("deer")
        lm = self.game.local
        lm.set_tile(deer.x, deer.y, deer.z, "grass")
        deer.needs.hunger = self.feeding.HUNGRY_AT + 1000
        before = deer.needs.hunger
        self.assertEqual(self.feeding.feed_here(deer, self.game), "graze")
        self.assertLess(deer.needs.hunger, before)

    def test_and_a_carnivore_does_not(self):
        wolf = self._beast("wolf")
        lm = self.game.local
        lm.set_tile(wolf.x, wolf.y, wolf.z, "grass")
        wolf.needs.hunger = self.feeding.HUNGRY_AT + 1000
        wolf.needs.thirst = 0
        self.assertEqual(self.feeding.feed_here(wolf, self.game), "")

    def test_a_carnivore_eats_carrion(self):
        from ascii_warriors.game.item import corpse_of

        wolf = self._beast("wolf")
        victim = self._beast("rabbit", n=1)
        self.game.drop_item(corpse_of(victim), wolf.x, wolf.y, wolf.z)
        wolf.needs.hunger = self.feeding.HUNGRY_AT + 1000
        wolf.needs.thirst = 0
        before = wolf.needs.hunger
        self.assertEqual(self.feeding.feed_here(wolf, self.game), "meat")
        self.assertLess(wolf.needs.hunger, before)

    def test_eating_is_where_the_water_is(self):
        """Most maps draw no water at all."""
        deer = self._beast("deer")
        lm = self.game.local
        lm.set_tile(deer.x, deer.y, deer.z, "grass")
        deer.needs.hunger = self.feeding.HUNGRY_AT + 1000
        deer.needs.thirst = self.feeding.THIRSTY_AT + 1000
        before = deer.needs.thirst
        self.feeding.feed_here(deer, self.game)
        self.assertLess(deer.needs.thirst, before)

    def test_a_kill_is_a_meal(self):
        wolf = self._beast("wolf")
        deer = self._beast("deer", n=1)
        wolf.needs.hunger = self.feeding.HUNGRY_AT + 5000
        before = wolf.needs.hunger
        self.feeding.ate(wolf, deer)
        self.assertLess(wolf.needs.hunger, before)

    def test_hunger_beats_fear_in_the_end(self):
        """A rabbit in sight of a fox fled until it died standing on grass."""
        from ascii_warriors.game import ai

        rabbit = self._beast("rabbit")
        self._beast("fox", n=1)
        lm = self.game.local
        lm.set_tile(rabbit.x, rabbit.y, rabbit.z, "grass")
        rabbit.needs.thirst = self.feeding.THIRSTY_AT + 100
        self.assertEqual(ai.pick_mode(rabbit, self.game), "flee")
        rabbit.needs.thirst = self.feeding.DESPERATE_THIRST + 100
        self.assertEqual(ai.pick_mode(rabbit, self.game), "forage")

    def test_a_wild_animal_is_not_on_a_persons_clock(self):
        deer = self._beast("deer")
        self.assertLess(self.feeding.need_ticks(deer, 1000), 1000)
        self.assertEqual(self.feeding.need_ticks(self.game.player, 1000), 1000)

    def test_but_a_tame_one_is_somebody_elses_problem(self):
        deer = self._beast("deer")
        deer.tame = True
        self.assertEqual(self.feeding.need_ticks(deer, 1000), 1000)

    def test_the_undead_need_nothing(self):
        z = self._beast("zombie")
        self.assertTrue(self.feeding.needs_nothing(z))
        self.assertEqual(self.feeding.wants(z), "")
        self.assertEqual(self.feeding.feed_here(z, self.game), "")

    def test_foraging_reaches_food_that_is_not_underfoot(self):
        from ascii_warriors.game import ai

        # The player alarms everything; this is about food, not fear.
        self.game.creatures.pop(self.game.player.id, None)
        deer = self._beast("deer")
        lm = self.game.local
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                cell = (deer.x + dx, deer.y + dy, deer.z)
                if lm.in_bounds(*cell) and lm.walkable(*cell):
                    lm.set_tile(cell[0], cell[1], cell[2], "dirt")
        spot = (deer.x + 4, deer.y, deer.z)
        if not lm.in_bounds(*spot) or not lm.walkable(*spot):
            self.skipTest("no room to put the grass")
        lm.set_tile(spot[0], spot[1], spot[2], "grass")
        deer.needs.hunger = self.feeding.HUNGRY_AT + 1000
        deer.needs.thirst = 0
        # Not necessarily *this* patch -- the map is full of grass and the
        # nearest one wins. What matters is that it finds one and walks to it.
        found = self.feeding.target_cell(deer, self.game)
        self.assertIsNotNone(found)
        self.assertEqual(self.feeding.feed_here(deer, self.game), "")
        before = deer.needs.hunger
        for _ in range(30):
            ai.take_turn(deer, self.game)
            if deer.needs.hunger < before:
                return
        self.fail("it never reached the grass")


class TestLivingOffTheLand(GameFixture):
    """Whole chains missing one link: nobody could fish, and only dwarves
    could pick anything."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import foraging

        self.foraging = foraging
        self.p = self.game.player

    def _here(self):
        return (self.p.x, self.p.y, self.p.z)

    # -- gathering ----------------------------------------------------------- #

    def test_a_shrub_is_worth_picking(self):
        cell = self._here()
        self.game.local.set_tile(cell[0], cell[1], cell[2], "shrub")
        self.assertEqual(self.foraging.gatherable(self.game, cell), "shrub")

    def test_and_bare_rock_is_not(self):
        cell = self._here()
        self.game.local.set_tile(cell[0], cell[1], cell[2], "rock_wall")
        self.assertEqual(self.foraging.gatherable(self.game, cell), "")

    def test_picking_a_shrub_gives_you_something_and_leaves_grass(self):
        cell = self._here()
        self.game.local.set_tile(cell[0], cell[1], cell[2], "shrub")
        items, said = self.foraging.gather(self.game, self.p, RNG("g"))
        self.assertTrue(items, said)
        what, count = items[0]
        self.assertGreater(count, 0)
        self.assertTrue(self.p.inventory.by_def(what))
        self.assertEqual(self.game.local.tile(*cell), "grass")

    def test_a_better_herbalist_gets_more(self):
        lm = self.game.local
        cell = self._here()
        best = {}
        for level in (0, 12):
            self.p.skills.set_level("herbalism", level)
            total = 0
            for i in range(8):
                lm.set_tile(cell[0], cell[1], cell[2], "shrub")
                items, _ = self.foraging.gather(self.game, self.p, RNG("g%d" % i))
                total += sum(n for _what, n in items)
            best[level] = total
        self.assertGreater(best[12], best[0])

    def test_gathering_trains_the_skill_the_fortress_has_always_used(self):
        cell = self._here()
        self.game.local.set_tile(cell[0], cell[1], cell[2], "shrub")
        before = self.p.skills.experience("herbalism") \
            if hasattr(self.p.skills, "experience") else None
        self.foraging.gather(self.game, self.p, RNG("g"))
        self.assertGreaterEqual(self.p.skills.level("herbalism"), 0)
        if before is not None:
            self.assertGreater(self.p.skills.experience("herbalism"), before)

    def test_nothing_growing_means_nothing_picked(self):
        lm = self.game.local
        p = self.p
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                cell = (p.x + dx, p.y + dy, p.z)
                if lm.in_bounds(*cell):
                    lm.set_tile(cell[0], cell[1], cell[2], "dirt")
        items, said = self.foraging.gather(self.game, p, RNG("g"))
        self.assertEqual(items, [])
        self.assertIn("nothing growing", said)

    def test_the_action_costs_time(self):
        from ascii_warriors.game import actions

        cell = self._here()
        self.game.local.set_tile(cell[0], cell[1], cell[2], "shrub")
        self.assertGreater(actions.gather_here(self.game), 0)

    # -- fishing ------------------------------------------------------------- #

    def test_you_need_the_rod_the_item_table_has_always_had(self):
        from ascii_warriors.data.items import ITEMS

        self.assertIn("fishing_rod", ITEMS)
        self.assertFalse(self.foraging.has_rod(self.p))
        items, said = self.foraging.fish(self.game, self.p, RNG("f"))
        self.assertEqual(items, [])
        self.assertIn("no fishing rod", said)

    def test_and_water_to_put_it_in(self):
        from ascii_warriors.game.item import Item

        self.p.inventory.add(Item("fishing_rod", "oak"))
        lm = self.game.local
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                cell = (self.p.x + dx, self.p.y + dy, self.p.z)
                if lm.in_bounds(*cell):
                    lm.set_tile(cell[0], cell[1], cell[2], "dirt")
        items, said = self.foraging.fish(self.game, self.p, RNG("f"))
        self.assertEqual(items, [])
        self.assertIn("no water", said)

    def test_with_both_you_catch_fish(self):
        from ascii_warriors.game.item import Item

        self.p.inventory.add(Item("fishing_rod", "oak"))
        self.p.skills.set_level("fishing", 8)
        lm = self.game.local
        lm.set_tile(self.p.x + 1, self.p.y, self.p.z, "water")
        caught = 0
        for i in range(20):
            items, _said = self.foraging.fish(self.game, self.p, RNG("f%d" % i))
            caught += sum(n for _what, n in items)
        self.assertGreater(caught, 0)
        self.assertTrue(any(i.def_id == "fish_food" for i in self.p.inventory.items))

    def test_a_better_angler_catches_more_often(self):
        self.p.skills.set_level("fishing", 0)
        poor = self.foraging.fish_chance(self.p)
        self.p.skills.set_level("fishing", 14)
        self.assertGreater(self.foraging.fish_chance(self.p), poor)
        self.assertLessEqual(self.foraging.fish_chance(self.p),
                             self.foraging.FISH_MAX)

    def test_fishing_takes_most_of_an_afternoon(self):
        from ascii_warriors.game import actions
        from ascii_warriors.game.item import Item

        self.p.inventory.add(Item("fishing_rod", "oak"))
        self.game.local.set_tile(self.p.x + 1, self.p.y, self.p.z, "water")
        self.assertGreater(actions.fish_here(self.game),
                           self.foraging.GATHER_TURNS)

    def test_and_not_with_something_watching(self):
        from ascii_warriors.game import actions
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import Item

        self.p.inventory.add(Item("fishing_rod", "oak"))
        self.game.local.set_tile(self.p.x + 1, self.p.y, self.p.z, "water")
        foe = make_creature(RNG("g"), "goblin", faction="hostile")
        foe.x, foe.y, foe.z = self.p.x + 2, self.p.y, self.p.z
        self.game.creatures[foe.id] = foe
        self.game.update_fov() if hasattr(self.game, "update_fov") else None
        if not self.game.hostiles_in_sight():
            self.skipTest("the goblin is not actually in sight")
        self.assertEqual(actions.fish_here(self.game), 0)

    def test_the_whole_chain_the_fish_was_missing_from(self):
        from ascii_warriors.data.creatures import CREATURES
        from ascii_warriors.data.items import ITEMS
        from ascii_warriors.game.crafting import RECIPES
        from ascii_warriors.game.skills import SKILLS

        self.assertIn("fishing", SKILLS)
        self.assertIn("fish_food", ITEMS)
        self.assertIn("carp", CREATURES)
        self.assertIn("cook_fish", RECIPES)


class TestAftermath(GameFixture):
    """What a fight leaves on the floor."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.game import tracks

        self.tracks = tracks
        self.p = self.game.player

    def _butcher(self, seed="a"):
        """Somebody who can take a limb off in one swing."""
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item

        c = make_creature(RNG(seed), "human", equip=False)
        c.inventory.equip(make_item(RNG("i"), "great_axe", material="steel"))
        c.skills.set_level("axe", 14)
        c.attributes.set("strength", 2400)
        return c

    # -- severed limbs ------------------------------------------------------- #

    def test_a_limb_that_comes_off_lands_on_the_floor(self):
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        found = 0
        for i in range(40):
            a = self._butcher("a%d" % i)
            d = make_creature(RNG("d%d" % i), "goblin", equip=False)
            d.x, d.y, d.z = self.p.x, self.p.y, self.p.z
            for _ in range(20):
                combat.melee_attack(a, d, rng=RNG("f%d" % i), ground=self.game)
                if d.body.dead:
                    break
            found = sum(1 for pile in self.game.items_on_ground.values()
                        for it in pile if it.def_id == "severed_part")
            if found:
                break
        self.assertGreater(found, 0, "nothing was ever cut off")

    def test_and_it_says_whose_it_was(self):
        from ascii_warriors.game.item import severed_part
        from ascii_warriors.game.entity import make_creature

        gob = make_creature(RNG("g"), "goblin", equip=False)
        item = severed_part(gob, "left hand")
        self.assertIn("goblin", item.name())
        self.assertIn("left hand", item.name())
        self.assertEqual(item.flags.get("creature"), "goblin")

    def test_the_same_limb_is_not_dropped_twice(self):
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        d = make_creature(RNG("d"), "goblin", equip=False)
        d.x, d.y, d.z = self.p.x, self.p.y, self.p.z
        # A blow big enough to take the arm off outright, then ask twice.
        # A hand needs more than a hand's worth of momentum; the forearm goes.
        part = d.body.parts["left_arm_lower"]
        d.body.apply_damage("left_arm_lower", "edge", 900000, 60, 9000, RNG("x"))
        self.assertTrue(part.severed, "that blow did not take the arm off")
        first = combat.severed_items(d, RNG("s"))
        second = combat.severed_items(d, RNG("s"))
        self.assertTrue(first)
        self.assertEqual(second, [])

    def test_the_fortress_gets_them_too(self):
        """`timed_strike` is the fortress's melee path; the limb has to land
        there as well, without turning on the ambush rules it deliberately
        leaves off."""
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        d = make_creature(RNG("d"), "goblin", equip=False)
        d.x, d.y, d.z = self.p.x, self.p.y, self.p.z
        d.body.apply_damage("left_arm_lower", "edge", 900000, 60, 9000, RNG("x"))
        self.assertTrue(d.body.parts["left_arm_lower"].severed)
        a = self._butcher()
        a.swing_bank = 10000        # do not wait on the swing clock
        combat.timed_strike(a, d, rng=RNG("t"), ground=self.game)
        dropped = [it for pile in self.game.items_on_ground.values()
                   for it in pile if it.def_id == "severed_part"]
        self.assertTrue(dropped)

    # -- blood --------------------------------------------------------------- #

    def _bleed(self):
        self.p.body.apply_damage("upper_body", "edge", 60000, 30, 4000,
                                 RNG("cut"))
        if self.p.body.bleeding_rate() <= 0:
            self.skipTest("that wound did not bleed")

    def test_blood_falls_on_ground_that_takes_no_print(self):
        """`BLOOD_FADE` has said so since v3.9 and the help screen promises it."""
        lm = self.game.local
        cell = (self.p.x, self.p.y, self.p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "stone_floor")
        self.assertFalse(self.tracks.takes_print(self.game, cell))
        self._bleed()
        track = self.tracks.leave(self.game, self.p, (cell[0] - 1, cell[1], cell[2]))
        self.assertIsNotNone(track)
        self.assertTrue(track.blood)
        self.assertFalse(track.printed)

    def test_but_an_unhurt_walker_leaves_nothing_on_stone(self):
        lm = self.game.local
        cell = (self.p.x, self.p.y, self.p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "stone_floor")
        for part in self.p.body.parts.values():
            part.wounds.clear()
        self.assertIsNone(
            self.tracks.leave(self.game, self.p, (cell[0] - 1, cell[1], cell[2])))

    def test_blood_on_stone_does_not_pretend_to_be_a_footprint(self):
        lm = self.game.local
        cell = (self.p.x, self.p.y, self.p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "stone_floor")
        self._bleed()
        track = self.tracks.leave(self.game, self.p, (cell[0] - 1, cell[1], cell[2]))
        self.p.skills.set_level("tracker", 12)
        lines = " ".join(self.tracks.read(self.game, self.p, cell, track))
        self.assertIn("lood", lines)
        self.assertNotIn("head", lines)      # no heading off bare stone
        self.assertNotIn("tracks", lines)

    def test_a_print_still_reads_as_a_print(self):
        lm = self.game.local
        cell = (self.p.x, self.p.y, self.p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "mud")
        track = self.tracks.leave(self.game, self.p, (cell[0] - 1, cell[1], cell[2]))
        self.assertTrue(track.printed)
        self.p.skills.set_level("tracker", 12)
        lines = " ".join(self.tracks.read(self.game, self.p, cell, track))
        self.assertIn("head", lines)

    def test_blood_outlasts_a_footprint(self):
        bloody = self.tracks.Track("wolf", "wolf", 40000, 1, 0, 0)
        bloody.blood = True
        plain = self.tracks.Track("wolf", "wolf", 40000, 1, 0, 0)
        cell = (self.p.x, self.p.y, self.p.z)
        self.game.local.set_tile(cell[0], cell[1], cell[2], "grass")
        self.assertGreater(self.tracks.fade_ticks(self.game, cell, bloody),
                           self.tracks.fade_ticks(self.game, cell, plain))

    def test_the_mark_survives_a_save(self):
        from ascii_warriors.game.state import Game

        lm = self.game.local
        cell = (self.p.x, self.p.y, self.p.z)
        lm.set_tile(cell[0], cell[1], cell[2], "stone_floor")
        self._bleed()
        self.tracks.leave(self.game, self.p, (cell[0] - 1, cell[1], cell[2]))
        back = Game.from_dict(self.game.to_dict())
        mark = self.tracks.layer(back).get(cell)
        self.assertIsNotNone(mark)
        self.assertTrue(mark.blood)
        self.assertFalse(mark.printed)


class TestGravity(GameFixture):
    """`has_floor` was asked in one place and nothing ever fell."""

    def setUp(self):
        super().setUp()
        from ascii_warriors.world import gravity

        self.gravity = gravity
        self.p = self.game.player

    def _shaft(self, cell, depth):
        """Open a hole under a cell with a floor at the bottom.

        Returns where something dropped in comes to rest: the lowest *open*
        cell, standing on the floor tile below it, not the floor tile itself.
        """
        lm = self.game.local
        x, y, z = cell
        if z - depth - 1 < lm.zmin:
            self.skipTest("the map is not deep enough for that drop")
        for dz in range(0, depth + 1):
            lm.set_tile(x, y, z - dz, "air")
        lm.set_tile(x, y, z - depth - 1, "stone_floor")
        return (x, y, z - depth)

    # -- the shape of a fall -------------------------------------------------- #

    def test_a_step_down_is_free(self):
        self.assertEqual(self.gravity.fall_force(1), 0.0)

    def test_and_further_is_not(self):
        self.assertGreater(self.gravity.fall_force(4),
                           self.gravity.fall_force(2))

    def test_but_it_stops_getting_worse_eventually(self):
        self.assertEqual(self.gravity.fall_force(40),
                         self.gravity.fall_force(400))
        self.assertEqual(self.gravity.fall_force(400), self.gravity.MAX_FALL)

    def test_a_fall_is_in_the_one_trap_table(self):
        from ascii_warriors.game import combat

        self.assertIn("fall", combat.TRAP_STRIKES)

    def test_and_not_borrowing_the_pit_traps_numbers(self):
        """A trap's numbers let a breastplate eat a six-storey drop."""
        from ascii_warriors.game import combat

        self.assertGreater(combat.TRAP_STRIKES["fall"][1],
                           combat.TRAP_STRIKES["pit"][1])

    # -- where things land ---------------------------------------------------- #

    def test_landing_finds_the_first_solid_thing(self):
        here = (self.p.x, self.p.y, self.p.z)
        bottom = self._shaft(here, 4)
        self.assertEqual(self.gravity.landing(self.game.local, here), bottom)
        self.assertEqual(self.gravity.drop_distance(self.game.local, here), 4)

    def test_solid_ground_is_no_drop_at_all(self):
        here = (self.p.x, self.p.y, self.p.z)
        self.assertTrue(self.gravity.supported(self.game.local, here))
        self.assertEqual(self.gravity.drop_distance(self.game.local, here), 0)

    # -- falling -------------------------------------------------------------- #

    def test_a_long_fall_hurts(self):
        here = (self.p.x, self.p.y, self.p.z)
        self._shaft(here, 5)
        before = self.p.body.health_fraction()
        fell = self.gravity.settle(self.game, self.p, RNG("f"), log=self.game.log)
        self.assertEqual(fell, 5)
        self.assertLess(self.p.body.health_fraction(), before)

    def test_and_puts_you_at_the_bottom(self):
        here = (self.p.x, self.p.y, self.p.z)
        bottom = self._shaft(here, 5)
        self.gravity.settle(self.game, self.p, RNG("f"))
        self.assertEqual((self.p.x, self.p.y, self.p.z), bottom)

    def test_a_short_one_does_not(self):
        here = (self.p.x, self.p.y, self.p.z)
        self._shaft(here, 1)
        before = self.p.body.health_fraction()
        self.gravity.settle(self.game, self.p, RNG("f"))
        self.assertEqual(self.p.body.health_fraction(), before)

    def test_water_breaks_a_fall(self):
        from ascii_warriors.game.entity import make_creature

        deep = shallow = 0.0
        for i in range(30):
            for water, bucket in ((0, "dry"), (7, "wet")):
                c = make_creature(RNG("c%d" % i), "human", equip=False)
                self.gravity.hurt(c, 8, RNG("f%d" % i), water=water)
                if water:
                    deep += c.body.health_fraction()
                else:
                    shallow += c.body.health_fraction()
        self.assertGreater(deep, shallow)

    def test_everyone_falls_not_only_the_player(self):
        from ascii_warriors.game.entity import make_creature

        c = make_creature(RNG("c"), "human", equip=False)
        c.x, c.y, c.z = self.p.x + 2, self.p.y, self.p.z
        self.game.creatures[c.id] = c
        bottom = self._shaft((c.x, c.y, c.z), 4)
        self.gravity.settle(self.game, c, RNG("f"))
        self.assertEqual((c.x, c.y, c.z), bottom)

    def test_moving_into_thin_air_is_a_fall(self):
        """`move_creature` is the funnel; walking off a cliff used to slide
        you down for free."""
        here = (self.p.x, self.p.y, self.p.z)
        bottom = self._shaft(here, 5)
        before = self.p.body.health_fraction()
        self.game.move_creature(self.p, here[0], here[1], here[2])
        self.assertEqual(self.p.z, bottom[2])
        self.assertLess(self.p.body.health_fraction(), before)

    # -- items ---------------------------------------------------------------- #

    def test_items_in_mid_air_come_down(self):
        from ascii_warriors.game.item import Item

        cell = (self.p.x + 3, self.p.y, self.p.z)
        bottom = self._shaft(cell, 3)
        self.game.items_on_ground[cell] = [Item("sword", "iron")]
        self.assertEqual(self.gravity.settle_items(self.game, cell), 1)
        self.assertFalse(self.game.items_at(*cell))
        self.assertTrue(self.game.items_at(*bottom))

    def test_but_items_on_a_floor_stay_put(self):
        from ascii_warriors.game.item import Item

        cell = (self.p.x, self.p.y, self.p.z)
        self.game.items_on_ground[cell] = [Item("sword", "iron")]
        self.assertEqual(self.gravity.settle_items(self.game, cell), 0)

    # -- the tile nobody ever placed ------------------------------------------ #

    def test_a_chasm_is_a_hole(self):
        from ascii_warriors.world import tiles

        self.assertTrue(tiles.get("chasm").has("CHASM"))
        self.assertFalse(tiles.get("chasm").walk)
        cell = (self.p.x, self.p.y, self.p.z)
        self.game.local.set_tile(cell[0], cell[1], cell[2], "chasm")
        self.assertTrue(self.gravity.is_chasm(self.game.local, cell))

    def test_finding_everyone_standing_on_nothing(self):
        here = (self.p.x, self.p.y, self.p.z)
        self.assertEqual(self.gravity.unsupported_creatures(self.game), [])
        self._shaft(here, 3)
        self.assertIn(self.p, self.gravity.unsupported_creatures(self.game))


class TestContactArea(unittest.TestCase):
    """Contact area -- on every attack in the game since the weapon table was
    written, and until now read by nothing at all."""

    def _who(self, race="human", fighter=0):
        c = make_creature(RNG("contact"), race, equip=False)
        c.skills.set_level("fighter", fighter)
        for s in ("sword", "axe", "spear", "hammer", "mace", "misc_weapon",
                  "dagger", "pick", "striker", "kicker", "biter"):
            c.skills.set_level(s, 7)
        return c

    def _armed(self, wid, material="steel", fighter=0):
        c = self._who(fighter=fighter)
        it = Item(wid, material)
        c.inventory.add(it)
        c.inventory.auto_equip()
        return c, it

    def _wearing(self, *gear):
        c = make_creature(RNG("target"), "human", equip=False)
        for iid, material in gear:
            c.inventory.add(Item(iid, material))
        c.inventory.auto_equip()
        return c

    def _attack(self, wid, name):
        from ascii_warriors.data.items import ITEMS

        return next(a for a in ITEMS[wid].weapon.attacks if a.name == name)

    def _through(self, wid, name, target):
        """Momentum left after armour, for one named attack of one weapon."""
        from ascii_warriors.game import combat

        who, it = self._armed(wid)
        a = self._attack(wid, name)
        kind = combat.effective_kind(it, a)
        absorbed, _outer = combat.armor_protection(
            target, "upper_body", kind, a.contact)
        return combat.compute_momentum(who, it, a) - absorbed

    # -- the curve ---------------------------------------------------------- #

    def test_spread_rises_with_contact_area_and_stays_bounded(self):
        from ascii_warriors.game import contact

        seen = [contact.spread(c) for c in
                (1, 5, 10, 20, 40, 60, 120, 400, 20000, 90000)]
        self.assertEqual(seen, sorted(seen))
        self.assertGreaterEqual(min(seen), contact.MIN_SPREAD)
        self.assertLessEqual(max(seen), contact.MAX_SPREAD)
        # A point and a chopping edge are genuinely different weapons.
        self.assertGreater(contact.spread(90000) / contact.spread(5), 2.5)

    def test_the_middle_of_the_natural_attacks_is_left_alone(self):
        """The bestiary was balanced before contact area was read. A kick is
        the reference, so a kick behaves exactly as it always did."""
        from ascii_warriors.data.items import KICK
        from ascii_warriors.game import contact

        self.assertAlmostEqual(contact.spread(KICK.contact), 1.0, places=2)
        self.assertAlmostEqual(contact.bite(KICK.contact), 1.0, places=2)

    def test_a_broad_edge_never_pays_twice_for_its_width(self):
        """`bite` is capped at 1.0 on purpose. Charging an edge for its width
        in the layer above *and* in the depth below cost the great axe a third
        of its reach and gave it nothing back, which was measurably wrong."""
        from ascii_warriors.game import contact

        for c in (400, 20000, 90000):
            self.assertGreater(contact.spread(c), 1.0)
            self.assertEqual(contact.bite(c), 1.0)
        self.assertLess(contact.bite(5), contact.spread(5))

    # -- the weapon triangle ------------------------------------------------ #

    def test_a_point_gets_through_mail_that_turns_an_edge(self):
        mailed = self._wearing(("mail_shirt", "iron"))
        stab = self._through("sword", "stab", mailed)
        slash = self._through("sword", "slash", mailed)
        self.assertGreater(stab, 0.0)
        self.assertLessEqual(slash, 0.0)

    def test_a_hammer_gets_through_mail_that_turns_an_axe(self):
        mailed = self._wearing(("mail_shirt", "iron"))
        self.assertGreater(self._through("maul", "bash", mailed), 0.0)
        self.assertLessEqual(self._through("axe", "hack", mailed), 0.0)

    def test_a_picks_point_goes_where_its_own_flat_cannot(self):
        """The cleanest statement the model makes: one weapon, one weight, one
        strength, the same momentum in both hands -- and mail stops the flat
        of it dead while the spike goes through."""
        from ascii_warriors.game import combat

        who, it = self._armed("pick")
        stab = self._attack("pick", "stab")
        bash = self._attack("pick", "bash")
        self.assertAlmostEqual(combat.compute_momentum(who, it, stab),
                               combat.compute_momentum(who, it, bash), places=5)
        mailed = self._wearing(("mail_shirt", "iron"))
        self.assertGreater(self._through("pick", "stab", mailed), 0.0)
        self.assertLess(self._through("pick", "bash", mailed), 0.0)

    def test_mail_takes_three_times_as_much_from_a_broad_blow(self):
        """Contact alone, with the damage kind held still."""
        from ascii_warriors.game import combat

        mailed = self._wearing(("mail_shirt", "iron"))
        for kind in ("edge", "blunt"):
            fine, _f = combat.armor_protection(mailed, "upper_body", kind, 5)
            broad, _b = combat.armor_protection(mailed, "upper_body", kind, 60000)
            self.assertGreater(broad, fine * 3.0)

    def test_bare_skin_does_not_care_how_wide_the_blow_was(self):
        """Contact area is read by armour. A man with none on is hit exactly
        as hard as he was before any of this."""
        from ascii_warriors.game import combat

        bare = self._wearing()
        for wid, name in (("sword", "stab"), ("sword", "slash"),
                          ("great_axe", "hack"), ("dagger", "stab")):
            who, it = self._armed(wid)
            a = self._attack(wid, name)
            absorbed, _o = combat.armor_protection(
                bare, "upper_body", combat.effective_kind(it, a), a.contact)
            self.assertEqual(absorbed, 0.0)

    def test_a_hide_spreads_a_slash_and_not_a_point(self):
        """Natural armour is armour: it spreads by contact area too."""
        from ascii_warriors.game import combat

        beast = make_creature(RNG("hide"), "elephant", equip=False)
        if beast.defn.natural_armor <= 0:
            beast = make_creature(RNG("hide"), "dragon", equip=False)
        self.assertGreater(beast.defn.natural_armor, 0)
        part = next(p for p in beast.body.parts.values()
                    if p.defn.category == "torso")
        fine, _a = combat.armor_protection(beast, part.id, "edge", 5)
        broad, _b = combat.armor_protection(beast, part.id, "edge", 60000)
        self.assertGreater(broad, fine * 2.0)

    # -- what the wound looks like ------------------------------------------ #

    def _chew(self, contact_area, force=48000.0, kind="edge"):
        """Drive one blow into a fresh torso and report depth and damage."""
        c = make_creature(RNG("chew"), "human", equip=False)
        clauses = c.body.apply_damage(
            "upper_body", kind, force, contact_area, 4000, RNG("blow"))
        part = c.body.part("upper_body")
        worst = min(part.tissues.values()) if part.tissues else 1.0
        touched = sum(1 for f in part.tissues.values() if f < 1.0)
        return len(clauses), touched, 1.0 - worst

    def test_an_edge_chews_a_wider_wound_than_a_point(self):
        _dc, _dt, point = self._chew(5)
        _ec, _et, edge = self._chew(60000)
        self.assertGreater(edge, point * 1.5)

    def test_a_point_reaches_layers_an_edge_stops_short_of(self):
        """A torso is skin, fat, muscle, bone. At the force that puts a point
        into the muscle, the edge is still in the fat; at the force that puts
        a point on the bone, the edge has taken the skin and the fat off and
        stopped."""
        for force in (32000.0, 70000.0):
            _pc, point_deep, _pd = self._chew(5, force)
            _ec, edge_deep, _ed = self._chew(60000, force)
            self.assertGreater(point_deep, edge_deep, "at force %.0f" % force)

    def test_the_edge_takes_the_layers_it_does_reach_apart(self):
        """The other half of the same trade. The edge stops sooner because it
        spent everything on width, and the width is what shows."""
        c = make_creature(RNG("chew"), "human", equip=False)
        c.body.apply_damage("upper_body", "edge", 70000.0, 60000, 4000,
                            RNG("blow"))
        edge = c.body.part("upper_body").tissues
        d = make_creature(RNG("chew"), "human", equip=False)
        d.body.apply_damage("upper_body", "edge", 70000.0, 5, 4000, RNG("blow"))
        point = d.body.part("upper_body").tissues
        self.assertEqual(edge["skin"], 0.0)
        self.assertEqual(edge["fat"], 0.0)
        self.assertGreater(point["skin"], 0.0)
        self.assertLess(edge["muscle"], point["muscle"])
        self.assertEqual(edge["bone"], 1.0)
        self.assertLess(point["bone"], 1.0)

    def test_a_narrow_wound_is_likelier_to_find_an_organ(self):
        from ascii_warriors.game import contact

        chances = [contact.organ_chance(c) for c in (5, 20, 60, 400, 60000)]
        self.assertEqual(chances, sorted(chances, reverse=True))
        self.assertGreater(chances[0], chances[-1] * 2.0)
        self.assertGreaterEqual(min(chances), contact.MIN_ORGAN)
        self.assertLessEqual(max(chances), contact.MAX_ORGAN)

    def test_an_axe_takes_an_arm_off_and_a_spear_does_not(self):
        from ascii_warriors.game import combat

        def blows_to_lose(wid, name, gear=()):
            taken = []
            for i in range(12):
                target = self._wearing(*gear)
                who, it = self._armed(wid)
                a = self._attack(wid, name)
                rng = RNG(4000 + i)
                for blow in range(1, 31):
                    combat.melee_attack(who, target, weapon=it, attack_def=a,
                                        target_part="left_arm_lower", rng=rng)
                    part = target.body.part("left_arm_lower")
                    if part.gone or part.destroyed:
                        taken.append(blow)
                        break
            return len(taken), (sum(taken) / len(taken) if taken else 0.0)

        axes, axe_blows = blows_to_lose("great_axe", "hack")
        spears, spear_blows = blows_to_lose("spear", "stab")
        self.assertGreaterEqual(axes, 10)
        self.assertLess(axe_blows, 12.0)
        # How much faster, not how many trials got there inside thirty blows.
        # The count saturated -- both reached twelve of twelve once a steel
        # point could grind through the bone in the arm at all -- while the
        # thing the contact model actually claims got *sharper*: an axe takes
        # the arm off in four blows and a spear needs fourteen.
        self.assertGreaterEqual(spears, 1, "a spear never gets through at all")
        self.assertGreater(spear_blows, axe_blows * 2.0,
                           "a spear takes an arm off as fast as an axe")

    # -- the choice ---------------------------------------------------------- #

    def _choices(self, wid, target, fighter, rolls=400):
        from ascii_warriors.game import combat

        who, it = self._armed(wid, fighter=fighter)
        rng = RNG("choose")
        counts = {}
        for _ in range(rolls):
            a = combat.choose_attack(who, it, rng, target)
            counts[a.name] = counts.get(a.name, 0) + 1
        return counts

    def test_a_trained_fighter_thrusts_at_the_man_in_mail(self):
        mailed = self._wearing(("mail_shirt", "iron"))
        counts = self._choices("sword", mailed, fighter=9)
        self.assertGreater(counts.get("stab", 0), counts.get("slash", 0) * 4)

    def test_an_untrained_fighter_swings_whatever_is_in_his_hand(self):
        mailed = self._wearing(("mail_shirt", "iron"))
        counts = self._choices("sword", mailed, fighter=0)
        self.assertGreater(counts.get("slash", 0), 0.3 * sum(counts.values()))

    def test_judgement_grows_with_skill(self):
        mailed = self._wearing(("mail_shirt", "iron"))
        share = []
        for level in (0, 3, 9):
            counts = self._choices("sword", mailed, fighter=level)
            share.append(counts.get("stab", 0) / float(sum(counts.values())))
        self.assertEqual(share, sorted(share))
        self.assertGreater(share[-1] - share[0], 0.3)

    def test_against_a_bare_target_both_attacks_stay_in_use(self):
        """Nothing to judge means nothing to force: a swordsman facing a man
        in a shirt still cuts as often as he thrusts."""
        bare = self._wearing()
        counts = self._choices("sword", bare, fighter=9)
        for name in ("stab", "slash"):
            self.assertGreater(counts.get(name, 0), 0.25 * sum(counts.values()))

    def test_with_nobody_in_front_of_him_the_choice_is_a_coin_toss(self):
        from ascii_warriors.game import combat

        who, it = self._armed("sword", fighter=15)
        rng = RNG("nobody")
        counts = {}
        for _ in range(400):
            a = combat.choose_attack(who, it, rng)
            counts[a.name] = counts.get(a.name, 0) + 1
        self.assertGreater(min(counts.values()), 120)

    def test_teeth_and_claws_are_judged_too(self):
        """`fighter` is on most of the bestiary and it buys the same judgement
        it buys a swordsman."""
        from ascii_warriors.game import combat

        beast = make_creature(RNG("beast"), "dragon", equip=False)
        # Asserted rather than skipped: a dragon that lost its claws would
        # make this test measure nothing, and it should say so.
        self.assertGreaterEqual(len(beast.defn.attacks), 2)
        self.assertGreater(beast.skills.level("fighter"), 0)
        mailed = self._wearing(("mail_shirt", "iron"), ("helm", "iron"))
        rng = RNG("teeth")
        counts = {}
        for _ in range(400):
            a = combat.choose_attack(beast, None, rng, mailed)
            counts[a.name] = counts.get(a.name, 0) + 1
        best = max(counts, key=lambda k: counts[k])
        flat = sum(counts.values()) / float(len(counts))
        self.assertGreater(counts[best], flat * 1.2)

    # -- the rest of the game ------------------------------------------------ #

    def test_a_fall_is_spread_by_armour_and_a_dart_is_not(self):
        """Both comments were written into the trap table long before
        anything read `contact`. They are true now."""
        from ascii_warriors.game import combat

        plated = self._wearing(("breastplate", "steel"))
        fall = combat.TRAP_STRIKES["fall"]
        dart = combat.TRAP_STRIKES["dart"]
        spread_fall, _f = combat.armor_protection(
            plated, "upper_body", fall[0], fall[2])
        spread_dart, _d = combat.armor_protection(
            plated, "upper_body", dart[0], dart[2])
        self.assertGreater(spread_fall, spread_dart * 1.5)

    def test_a_trap_with_no_contact_area_does_not_crash(self):
        from ascii_warriors.game import combat, contact

        self.assertEqual(contact.spread(0), contact.MIN_SPREAD)
        victim = self._wearing()
        result = combat.trap_strike(victim, "alarm", rng=RNG("alarm"))
        self.assertFalse(result.hit)

    def test_the_item_screen_says_which_attack_gets_through(self):
        lines = " ".join(Item("sword", "steel").full_description(None))
        self.assertIn("cleaving", lines)
        self.assertIn("Armour spreads its slash", lines)
        self.assertIn("the stab is what gets through", lines)

    def test_a_single_edged_weapon_is_described_as_one(self):
        lines = " ".join(Item("great_axe", "steel").full_description(None))
        self.assertIn("armour has a great deal to spread", lines)
        point = " ".join(Item("dagger", "steel").full_description(None))
        self.assertIn("armour has little to spread", point)

    def test_a_whole_fight_still_ends(self):
        """The model changed under every blow in the game; fights must still
        finish, and finish in a sane number of them."""
        from ascii_warriors.game import combat

        lengths = []
        for seed in range(6):
            who, it = self._armed("sword", fighter=6)
            foe = self._wearing(("mail_shirt", "iron"), ("helm", "iron"))
            rng = RNG(600 + seed)
            for blow in range(1, 201):
                combat.melee_attack(who, foe, weapon=it, rng=rng)
                if foe.body.dead:
                    lengths.append(blow)
                    break
                foe.body.tick(rng, 1, 1.0, 1.0)
        self.assertEqual(len(lengths), 6)
        self.assertLess(sum(lengths) / len(lengths), 90.0)


class TestWhatArmourIsWorth(unittest.TestCase):
    """Armour that stops a cut absolutely and a hammer not at all, and the
    skill that had been levelling up for nothing since it was written."""

    PLATE = (("breastplate", "steel"), ("mail_shirt", "iron"), ("helm", "iron"),
             ("greaves", "steel"), ("gauntlets", "steel"))
    MAIL = (("mail_shirt", "iron"), ("helm", "iron"))
    LEATHER = (("leather_armor", "leather"),)

    def _wearing(self, gear=(), skill=0):
        c = make_creature(RNG("worn"), "human", equip=False)
        c.skills.set_level("armor_use", skill)
        for iid, material in gear:
            c.inventory.add(Item(iid, material))
        c.inventory.auto_equip()
        return c

    def _swinger(self):
        a = make_creature(RNG("swing"), "human", equip=False)
        for s in ("fighter", "sword", "axe", "spear", "hammer", "mace",
                  "misc_weapon", "dagger", "pick"):
            a.skills.set_level(s, 7)
        return a

    def _attack(self, wid, name):
        from ascii_warriors.data.items import ITEMS

        return next(a for a in ITEMS[wid].weapon.attacks if a.name == name)

    def _through(self, wid, name, target):
        """What one named attack delivers to *target*'s chest."""
        from ascii_warriors.game import combat

        who = self._swinger()
        it = Item(wid, "steel")
        who.inventory.add(it)
        who.inventory.auto_equip()
        a = self._attack(wid, name)
        kind = combat.effective_kind(it, a)
        momentum = combat.compute_momentum(who, it, a)
        absorbed, _o = combat.armor_protection(
            target, "upper_body", kind, a.contact, momentum)
        return momentum - absorbed

    # -- the defect --------------------------------------------------------- #

    def test_a_hammer_gets_through_the_plate_that_stops_every_edge(self):
        """The hammerman's whole pitch at character creation, and it used to
        be exactly inverted: steel's impact yield is three and a half times its
        shear yield, so plate was three and a half times *better* against a
        mace than against an axe."""
        knight = self._wearing(self.PLATE)
        for wid, name in (("warhammer", "bash"), ("mace", "bash"),
                          ("maul", "bash"), ("morningstar", "bash")):
            self.assertGreater(self._through(wid, name, knight), 0.0,
                               "%s should get through plate" % wid)
        for wid, name in (("axe", "hack"), ("sword", "slash"),
                          ("great_axe", "hack"), ("dagger", "stab")):
            self.assertLess(self._through(wid, name, knight), 0.0,
                            "%s should not cut plate" % wid)

    def test_an_edge_is_left_exactly_as_it_was(self):
        """The cap is on blunt only. v3.27's calibration of every edged weapon
        against every kind of armour must come through untouched."""
        from ascii_warriors.game import combat

        for gear in ((), self.LEATHER, self.MAIL, self.PLATE):
            target = self._wearing(gear)
            for contact_area in (5, 60, 25000, 90000):
                capped, _a = combat.armor_protection(
                    target, "upper_body", "edge", contact_area, 50000.0)
                uncapped, _b = combat.armor_protection(
                    target, "upper_body", "edge", contact_area)
                self.assertEqual(capped, uncapped)

    def test_plate_spreads_a_hammer_better_than_mail_does(self):
        """Rigidity, which is geometry. Without it the cap binds on both and a
        breastplate is worth exactly a mail shirt against a mace, which is not
        what a breastplate is."""
        plated = self._through("warhammer", "bash", self._wearing(self.PLATE))
        mailed = self._through("warhammer", "bash", self._wearing(self.MAIL))
        bare = self._through("warhammer", "bash", self._wearing())
        self.assertGreater(bare, mailed)
        self.assertGreater(mailed, plated)
        self.assertGreater(plated, 0.0)

    def test_cloth_and_leather_never_reach_the_cap(self):
        """The cap is a ceiling on absorption, not a floor. A wool tunic's own
        thinness is far below it, so the `min` never fires and a hammer goes
        through a shirt exactly as it always did."""
        from ascii_warriors.game import armour, combat

        for gear in ((("tunic", "wool_cloth"),), self.LEATHER):
            target = self._wearing(gear)
            capped, _a = combat.armor_protection(
                target, "upper_body", "blunt", 20, 50000.0)
            uncapped, _b = combat.armor_protection(
                target, "upper_body", "blunt", 20)
            self.assertEqual(capped, uncapped)
            self.assertFalse(armour.caps_blunt(
                uncapped, 20, armour.rigidity(2, 2)))

    def test_a_blunt_share_always_arrives(self):
        from ascii_warriors.game import armour

        for contact_area in (2, 10, 40, 400, 20000):
            for skill in (0, 10, 20):
                share = armour.transmit_share(contact_area, skill, 3.0)
                self.assertGreater(share, 0.0)
                self.assertLess(share, 1.0)
        # A concentrated blow transmits more than a spread one.
        self.assertGreater(armour.transmit_share(10, 0, 1.0),
                           armour.transmit_share(20000, 0, 1.0))

    # -- the skill ---------------------------------------------------------- #

    def test_armour_skill_takes_a_hammer_off_the_ribs(self):
        green = self._through("warhammer", "bash", self._wearing(self.PLATE, 0))
        veteran = self._through(
            "warhammer", "bash", self._wearing(self.PLATE, 20))
        self.assertGreater(green, veteran * 1.25)
        self.assertGreater(veteran, 0.0)

    def test_armour_skill_takes_weight_off_the_shoulders(self):
        green = self._wearing(self.PLATE, 0)
        veteran = self._wearing(self.PLATE, 20)
        self.assertLess(veteran.encumbrance(), green.encumbrance())
        self.assertGreater(green.encumbrance() - veteran.encumbrance(), 0.1)

    def test_the_relief_is_on_what_is_worn_and_not_what_is_carried(self):
        """A breastplate in a sack is dead weight to anybody."""
        carried = make_creature(RNG("worn"), "human", equip=False)
        carried.skills.set_level("armor_use", 20)
        carried.inventory.add(Item("breastplate", "steel"))
        before = carried.encumbrance()
        carried.inventory.auto_equip()
        self.assertLess(carried.encumbrance(), before)

    def test_a_veteran_dodges_better_in_the_same_steel(self):
        from ascii_warriors.game import combat

        green = combat.defense_power(self._wearing(self.PLATE, 0))
        veteran = combat.defense_power(self._wearing(self.PLATE, 20))
        self.assertGreater(veteran, green)

    def test_every_level_of_the_skill_is_worth_something(self):
        """A skill whose last five levels buy nothing lies to whoever trains
        it. Both curves reach their limit at 20 and not before."""
        from ascii_warriors.game import armour
        from ascii_warriors.game.skills import MAX_LEVEL

        self.assertGreater(armour.weight_relief(MAX_LEVEL),
                           armour.weight_relief(MAX_LEVEL - 4))
        rigid = armour.rigidity(5, 4)
        self.assertLess(armour.transmit_share(40, MAX_LEVEL, rigid),
                        armour.transmit_share(40, MAX_LEVEL - 4, rigid))

    def test_a_knight_who_knows_his_armour_lasts_longer(self):
        """All of it together, in blows."""
        from ascii_warriors.game import combat

        def blows(skill):
            taken = []
            for seed in range(10):
                who = self._swinger()
                w = Item("warhammer", "steel")
                who.inventory.add(w)
                who.inventory.auto_equip()
                foe = self._wearing(self.PLATE, skill)
                rng = RNG(8000 + seed)
                for n in range(1, 121):
                    combat.melee_attack(who, foe, weapon=w, rng=rng)
                    if foe.body.dead or foe.body.unconscious > 0:
                        taken.append(n)
                        break
                    foe.body.tick(rng, 1, 1.0, 1.0)
            return sum(taken) / len(taken) if taken else 0.0

        green, veteran = blows(0), blows(20)
        self.assertGreater(green, 0.0)
        self.assertGreater(veteran, green * 1.15)

    # -- the choice it changes ------------------------------------------------ #

    def test_a_spearman_facing_plate_clubs_him_with_the_shaft(self):
        """Nobody wrote this. The armour model and the contact model compose:
        a spear's stab is stopped dead by a breastplate and its bash is not,
        and v3.27's judgement reads the difference off the same numbers."""
        from ascii_warriors.game import combat

        who = self._swinger()
        who.skills.set_level("fighter", 9)
        w = Item("spear", "steel")
        who.inventory.add(w)
        who.inventory.auto_equip()
        knight = self._wearing(self.PLATE)
        rng = RNG("shaft")
        counts = {}
        for _ in range(400):
            name = combat.choose_attack(who, w, rng, knight).name
            counts[name] = counts.get(name, 0) + 1
        self.assertGreater(counts.get("bash", 0), counts.get("stab", 0) * 4)

    def test_against_a_bare_man_the_spear_is_a_spear_again(self):
        from ascii_warriors.game import combat

        who = self._swinger()
        who.skills.set_level("fighter", 9)
        w = Item("spear", "steel")
        who.inventory.add(w)
        who.inventory.auto_equip()
        rng = RNG("bare")
        counts = {}
        for _ in range(400):
            name = combat.choose_attack(who, w, rng, self._wearing()).name
            counts[name] = counts.get(name, 0) + 1
        self.assertGreater(counts.get("stab", 0), 0.3 * sum(counts.values()))

    # -- the traps ------------------------------------------------------------ #

    def test_the_traps_that_cut_you_are_spelled_the_way_the_model_reads(self):
        """`TRAP_STRIKES` was written with "edged" and "piercing"; the model
        has only ever known "edge" and "blunt". Three traps fell through to the
        blunt branch, which does not bleed and does not sever, so a weapon trap
        that "slashes" you had never once cut anybody."""
        from ascii_warriors.game import combat

        for spec in combat.TRAP_STRIKES.values():
            self.assertIn(spec[0], ("edge", "blunt"))
        for trap in ("weapon_trap", "spike_trap", "dart"):
            self.assertEqual(combat.TRAP_STRIKES[trap][0], "edge")

    def test_a_dart_draws_blood(self):
        from ascii_warriors.game import combat

        bleeding = 0
        for i in range(40):
            victim = self._wearing()
            combat.trap_strike(victim, "dart", "iron", rng=RNG(9000 + i))
            if any(w.bleeding > 0 for p in victim.body.parts.values()
                   for w in p.wounds):
                bleeding += 1
        self.assertGreater(bleeding, 30)

    def test_mail_turns_a_dart_and_a_spike_goes_through_it(self):
        """Both are points now, so the material test decides, and it decides
        differently for nine thousand of momentum and twenty-four."""
        from ascii_warriors.game import combat

        mailed = self._wearing(self.MAIL)
        for trap, expect_through in (("dart", False), ("spike_trap", True)):
            kind, momentum, contact_area, _pen, _verb = \
                combat.TRAP_STRIKES[trap]
            absorbed, _o = combat.armor_protection(
                mailed, "upper_body", kind, contact_area, momentum)
            self.assertEqual(momentum - absorbed > 0, expect_through, trap)

    def test_a_fall_still_lands_the_way_v3_26_calibrated_it(self):
        """Armour halves a drop. The blunt cap must not have quietly undone a
        milestone that was measured against unarmoured bone."""
        from ascii_warriors.game import combat

        def broke(gear):
            hurt = 0
            for i in range(60):
                victim = self._wearing(gear)
                combat.trap_strike(victim, "fall", rng=RNG(300 + i))
                if any(p.broken for p in victim.body.parts.values()):
                    hurt += 1
            return hurt

        bare, plated = broke(()), broke(self.PLATE)
        self.assertGreater(bare, 40)
        self.assertLess(plated, bare * 0.6)

    # -- what the player is told ---------------------------------------------- #

    def test_the_item_screen_says_what_a_breastplate_is_for(self):
        lines = " ".join(Item("breastplate", "steel").full_description(None))
        self.assertIn("Turns a cut of up to", lines)
        self.assertIn("of a blunt blow through", lines)

    def test_the_item_screen_does_not_promise_a_shirt_spreads_a_hammer(self):
        lines = " ".join(Item("tunic", "wool_cloth").full_description(None))
        self.assertIn("Too thin to spread a blunt blow", lines)
        self.assertNotIn("of a blunt blow through", lines)

    def test_the_skill_has_a_description_now(self):
        from ascii_warriors.game import skills

        self.assertTrue(skills.SKILLS["armor_use"].description.strip())


class TestSwimming(GameFixture):
    """`TileDef.swim`, on the water tiles since the tile table was written and
    read by nothing, so that a river was a wall."""

    def _pool(self, tile_id="water", w=5):
        """Carve a pool of *tile_id* with a dry bank, and stand the player on it."""
        lm = self.game.local
        p = self.game.player
        z = p.z
        x0, y0 = p.x + 2, p.y
        for dx in range(w):
            for dy in range(-1, 2):
                lm.set_tile(x0 + dx, y0 + dy, z, tile_id)
        for dy in range(-1, 2):
            lm.set_tile(x0 - 1, y0 + dy, z, "grass")
        p.x, p.y, p.z = x0 - 1, y0, z
        self.game.drowning.clear()
        return (x0, y0, z)

    def _strip(self, creature=None):
        """Nothing carried, so the load term is not what is being measured."""
        c = creature or self.game.player
        for item in list(c.inventory.items):
            c.inventory.remove(item, item.count)
        return c

    # -- the flag ----------------------------------------------------------- #

    def test_the_water_tiles_say_they_can_be_swum(self):
        from ascii_warriors.world import tiles as tile_data

        self.assertFalse(tile_data.get("shallow_water").swim)
        for tid in ("water", "deep_water"):
            t = tile_data.get(tid)
            self.assertTrue(t.swim)
            self.assertFalse(t.walk, "%s is meant to need swimming" % tid)

    def test_a_river_is_no_longer_a_wall(self):
        x, y, z = self._pool()
        self._strip()
        self.assertTrue(self.game.is_passable(x, y, z, self.game.player))

    def test_you_cannot_walk_on_water_you_can_only_swim_it(self):
        """The tile is still not walkable. Everything that has no business in
        deep water -- pathing, gravity, a cart -- must keep seeing that."""
        x, y, z = self._pool()
        self.assertFalse(self.game.local.walkable(x, y, z))

    def test_walking_in_is_slower_and_costlier_than_walking(self):
        from ascii_warriors.game import actions
        from ascii_warriors.engine.scheduler import ACTION_COST

        self._pool()
        self._strip()
        before = self.game.player.needs.fatigue
        cost = actions.move_or_attack(self.game, 1, 0)
        self.assertGreater(cost, ACTION_COST)
        self.assertGreater(self.game.player.needs.fatigue, before + 2)

    # -- the depth ---------------------------------------------------------- #

    def test_the_three_water_tiles_are_three_different_places(self):
        from ascii_warriors.game import swimming

        shallow = swimming.depth_of("shallow_water")
        mid = swimming.depth_of("water")
        deep = swimming.depth_of("deep_water")
        self.assertLess(shallow, mid)
        self.assertLess(mid, deep)
        self.assertFalse(swimming.is_swimming(shallow))
        self.assertTrue(swimming.is_swimming(mid))
        who = self._strip()
        self.assertGreater(swimming.stroke_chance(who, mid),
                           swimming.stroke_chance(who, deep))

    def test_a_flooded_room_is_not_a_lake(self):
        """Water to the ceiling is what the fortress drowns people in, and it
        has to stay far worse than a river."""
        from ascii_warriors.game import swimming
        from ascii_warriors.world import fluids

        who = self._strip()
        who.skills.set_level("swimming", 10)
        lake = swimming.stroke_chance(who, swimming.depth_of("deep_water"))
        room = swimming.stroke_chance(who, fluids.MAX_DEPTH)
        self.assertGreater(lake, room * 3.0)

    # -- drowning ----------------------------------------------------------- #

    def test_treading_water_spends_breath_and_reaching_the_bank_returns_it(self):
        from ascii_warriors.game import swimming

        x, y, z = self._pool()
        p = self._strip()
        p.x, p.y, p.z = x, y, z
        self.game._swim(10)
        held = self.game.drowning.get(p.id, 0.0)
        self.assertGreater(held, 0.0)
        self.game._swim(10)
        self.assertGreater(self.game.drowning.get(p.id, 0.0), held)
        p.x = x - 1
        self.game._swim(10)
        self.assertNotIn(p.id, self.game.drowning)

    def test_a_tick_at_a_time_still_drowns_you(self):
        """Breath is a float on purpose. Rounding each slice and calling a
        zero "head above water" threw the whole count away every time the
        world advanced by a tick, which on a busy map is most of the time."""
        from ascii_warriors.game import swimming

        x, y, z = self._pool()
        p = self._strip()
        p.x, p.y, p.z = x, y, z
        for _ in range(swimming.DROWN_TICKS * 3):
            self.game._swim(1)
            if self.game.game_over:
                break
        self.assertTrue(self.game.game_over)
        self.assertEqual(self.game.death_message, "drowned")

    def test_shallow_water_never_drowns_anybody(self):
        x, y, z = self._pool("shallow_water")
        p = self._strip()
        p.x, p.y, p.z = x, y, z
        for _ in range(200):
            self.game._swim(5)
        self.assertFalse(self.game.game_over)
        self.assertNotIn(p.id, self.game.drowning)

    def test_a_fish_does_not_drown(self):
        from ascii_warriors.game.entity import make_creature

        x, y, z = self._pool()
        carp = make_creature(RNG("carp"), "carp")
        carp.x, carp.y, carp.z = x, y, z
        self.game.add_creature(carp)
        for _ in range(200):
            self.game._swim(5)
        self.assertFalse(carp.body.dead)
        self.assertNotIn(carp.id, self.game.drowning)

    # -- what you are carrying ------------------------------------------------ #

    def test_you_cannot_swim_in_a_steel_breastplate(self):
        from ascii_warriors.game import swimming

        p = self._strip()
        bare = swimming.stroke_chance(p, swimming.depth_of("water"))
        self.assertGreater(bare, 0.0)
        for iid, material in (("breastplate", "steel"), ("mail_shirt", "iron"),
                              ("greaves", "steel"), ("helm", "iron")):
            p.inventory.add(Item(iid, material))
        p.inventory.auto_equip()
        self.assertEqual(swimming.stroke_chance(p, swimming.depth_of("water")), 0.0)

    def test_no_amount_of_skill_saves_a_man_in_plate(self):
        from ascii_warriors.game import swimming
        from ascii_warriors.game.skills import MAX_LEVEL

        p = self._strip()
        for iid, material in (("breastplate", "steel"), ("mail_shirt", "iron"),
                              ("greaves", "steel"), ("helm", "iron")):
            p.inventory.add(Item(iid, material))
        p.inventory.auto_equip()
        p.skills.set_level("swimming", MAX_LEVEL)
        p.skills.set_level("armor_use", MAX_LEVEL)
        self.assertEqual(swimming.stroke_chance(p, swimming.depth_of("water")), 0.0)

    def test_taking_the_armour_off_is_what_saves_him(self):
        from ascii_warriors.game import swimming

        p = self._strip()
        for iid, material in (("breastplate", "steel"), ("mail_shirt", "iron")):
            p.inventory.add(Item(iid, material))
        p.inventory.auto_equip()
        self.assertEqual(swimming.stroke_chance(p, 5), 0.0)
        self._strip()
        self.assertGreater(swimming.stroke_chance(p, 5), 0.0)

    def test_armour_skill_helps_you_swim_in_mail(self):
        """Not because swimming knows about armour, but because v3.28 made
        `armor_use` decide what a kit weighs and this reads the weight."""
        from ascii_warriors.game import swimming
        from ascii_warriors.game.skills import MAX_LEVEL

        def chance(armour_skill):
            c = make_creature(RNG("mailed"), "human", equip=False)
            c.skills.set_level("armor_use", armour_skill)
            for iid, material in (("mail_shirt", "iron"), ("helm", "iron")):
                c.inventory.add(Item(iid, material))
            c.inventory.auto_equip()
            return swimming.stroke_chance(c, 5)

        self.assertGreater(chance(MAX_LEVEL), chance(0))

    # -- the skill ------------------------------------------------------------ #

    def test_the_skill_is_worth_training_all_the_way(self):
        from ascii_warriors.game import swimming
        from ascii_warriors.game.skills import MAX_LEVEL

        p = self._strip()
        seen = []
        for level in (0, 5, 10, 15, MAX_LEVEL):
            p.skills.set_level("swimming", level)
            seen.append(swimming.stroke_chance(p, 5))
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(seen[-1], seen[-2], "the last levels buy nothing")
        self.assertGreater(seen[-1], seen[0] * 2.0)

    def test_the_skill_has_a_description_now(self):
        from ascii_warriors.game import skills

        self.assertTrue(skills.SKILLS["swimming"].description.strip())

    def test_swimming_trains_by_swimming(self):
        from ascii_warriors.game import swimming

        p = self._strip()
        p.skills.set_level("swimming", 3)
        before = p.skills.exp_of("swimming") if hasattr(
            p.skills, "exp_of") else None
        gained = 0
        rng = RNG("train")
        for _ in range(200):
            if swimming.stays_up(p, 5, rng):
                gained += 1
        self.assertGreater(gained, 0)
        self.assertGreater(p.skills.level("swimming"), 0)

    # -- what lives in it ------------------------------------------------------ #

    def test_a_river_tile_offers_the_things_that_live_in_rivers(self):
        """`biomes.classify` cannot return "river" -- no world tile has ever
        been one -- and carp and pike list nowhere else, so neither had ever
        existed. The tile knows it has a river running through it."""
        from ascii_warriors.data import biomes as biome_data
        from ascii_warriors.data import creatures as creature_data

        reachable = set()
        for elev in [i / 10.0 for i in range(11)]:
            for rain in [i / 5.0 for i in range(6)]:
                for temp in range(-40, 60, 10):
                    for drain in [i / 5.0 for i in range(6)]:
                        reachable.add(biome_data.classify(
                            elev, rain, temp, drain, is_water=False))
        self.assertNotIn("river", reachable)
        river_only = [
            c.id for c in creature_data.spawnable("river")
            if not (set(creature_data.get(c.id).biomes) - {"river", "lake"})
        ]
        self.assertIn("carp", river_only)
        self.assertIn("pike", river_only)

    def test_a_fish_is_put_in_the_water_and_can_move_in_it(self):
        from ascii_warriors.game.entity import make_creature

        x, y, z = self._pool(w=6)
        spot = self.game.local.random_water(RNG("where"))
        self.assertIsNotNone(spot, "a pool was carved and nothing found it")
        carp = make_creature(RNG("carp"), "carp")
        carp.x, carp.y, carp.z = spot
        self.assertTrue(self.game.is_passable(*spot, carp))
        moves = [
            (spot[0] + dx, spot[1] + dy, spot[2])
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if self.game.is_passable(spot[0] + dx, spot[1] + dy, spot[2], carp)
        ]
        self.assertTrue(moves, "the fish cannot go anywhere")

    def test_a_fish_still_cannot_leave_the_water(self):
        from ascii_warriors.game.entity import make_creature

        x, y, z = self._pool()
        carp = make_creature(RNG("carp"), "carp")
        self.assertFalse(self.game.is_passable(x - 1, y, z, carp))

    # -- the two modes agree --------------------------------------------------- #

    def test_both_modes_ask_the_same_rule(self):
        """The fortress has drowned people since v2.5 with its own formula and
        adventure mode had never heard of drowning. One rule now."""
        import inspect

        from ascii_warriors.fortress import sim

        source = inspect.getsource(sim._flow)
        self.assertIn("stays_up", source)
        self.assertNotIn("0.25 + skill", source)

    # -- what walks into it ---------------------------------------------------- #

    def _cow_at(self, cell, mode="wander"):
        from ascii_warriors.game.ai import AIState
        from ascii_warriors.game.entity import make_creature

        cow = make_creature(RNG("cow"), "cow")
        cow.x, cow.y, cow.z = cell
        cow.ai = AIState(mode)
        cow.ai.home = cell
        self.game.add_creature(cow)
        return cow

    def test_a_wandering_animal_will_not_walk_into_a_lake(self):
        """Water being enterable at all meant every animal on the map could
        walk into one and hold its breath until it stopped. That is not
        wildlife behaviour, it is a bug with legs."""
        from ascii_warriors.game import ai, swimming

        x, y, z = self._pool()
        entered = 0
        for _ in range(40):
            cow = self._cow_at((x - 1, y, z))
            if ai._move_to(cow, self.game, (x, y, z)) and swimming.is_swimming(
                    swimming.depth_of(self.game.local.tile(*(cow.x, cow.y, cow.z)))):
                entered += 1
            self.game.creatures.pop(cow.id, None)
        self.assertEqual(entered, 0)

    def test_a_fleeing_animal_takes_to_the_water(self):
        """Which is what water is for."""
        from ascii_warriors.game import ai, swimming

        x, y, z = self._pool()
        cow = self._cow_at((x - 1, y, z), mode="flee")
        self.assertTrue(ai._move_to(cow, self.game, (x, y, z)))
        self.assertTrue(swimming.is_swimming(
            swimming.depth_of(self.game.local.tile(cow.x, cow.y, cow.z))))

    def test_something_already_swimming_can_still_reach_the_bank(self):
        """Refusing water it is standing in would strand it there to drown."""
        from ascii_warriors.game import ai

        x, y, z = self._pool()
        cow = self._cow_at((x + 1, y, z))
        self.assertTrue(ai._move_to(cow, self.game, (x - 1, y, z))
                        or ai._move_to(cow, self.game, (x, y, z)))

    def test_the_swim_state_survives_a_save(self):
        x, y, z = self._pool()
        p = self._strip()
        p.x, p.y, p.z = x, y, z
        self.game._swim(6)
        held = self.game.drowning.get(p.id, 0.0)
        self.assertGreater(held, 0.0)
        from ascii_warriors.game.state import Game

        restored = Game.from_dict(self.game.to_dict())
        self.assertAlmostEqual(restored.drowning.get(p.id, 0.0), held, places=3)


class TestAptitude(unittest.TestCase):
    """`SkillDef.attrs` -- the attributes each skill declares it is governed
    by, written with the table and read by nothing, leaving ten of the
    nineteen attributes rolled for every creature and connected to nothing."""

    def _who(self, race="dwarf", **attrs):
        c = make_creature(RNG("apt"), race, equip=False)
        for attr, value in attrs.items():
            c.attributes.set(attr, value)
        return c

    def _gifted(self, sid, value, level=0):
        from ascii_warriors.game import skills

        c = make_creature(RNG("apt"), "dwarf", equip=False)
        for attr in skills.SKILLS[sid].attrs:
            c.attributes.set(attr, value)
        c.skills.set_level(sid, level)
        return c

    # -- every attribute reaches something now -------------------------------- #

    def test_the_attributes_nothing_read_are_all_governed_by_a_skill(self):
        """Three attributes -- toughness, recuperation and disease resistance
        -- govern no skill and never did; they are read directly, by wounds
        and by venom. Every one of the ten that had no reader at all has to
        reach one through the table."""
        from ascii_warriors.game import skills
        from ascii_warriors.game.attributes import ALL_ATTRS

        direct_only = {"toughness", "recuperation", "disease_resistance"}
        for attr in ALL_ATTRS:
            if attr in direct_only:
                continue
            self.assertTrue(skills.governed_by(attr),
                            "%s governs nothing and nothing reads it" % attr)

    def test_every_attribute_now_reaches_an_outcome(self):
        """Ten of nineteen were read by no line of code anywhere. The ones
        with no direct reader must reach one through a skill somebody asks
        `ability` for."""
        import os
        import re

        from ascii_warriors.game import skills
        from ascii_warriors.game.attributes import ALL_ATTRS

        text = []
        for dirpath, _dirs, names in os.walk("ascii_warriors"):
            if "__pycache__" in dirpath:
                continue
            for name in names:
                if name.endswith(".py"):
                    with open(os.path.join(dirpath, name)) as fh:
                        text.append(fh.read())
        source = "\n".join(text)

        asked = set(re.findall(
            r'ability\([^,]+,\s*["\']([a-z_]+)["\']', source))
        # The three dynamic call sites, each covering a whole category.
        for sd in skills.SKILLS.values():
            if sd.category in ("craft", "medical"):
                asked.add(sd.id)
        asked.update(("music", "poetry", "dancing"))
        reached = set()
        for sid in asked:
            sd = skills.SKILLS.get(sid)
            if sd:
                reached.update(sd.attrs)

        for attr in ALL_ATTRS:
            direct = re.search(r'factor\(\s*["\']%s["\']' % attr, source)
            self.assertTrue(direct or attr in reached,
                            "%s is read by nothing at all" % attr)

    # -- the curve ------------------------------------------------------------ #

    def test_talent_helps_and_does_not_decide(self):
        from ascii_warriors.game import skills

        poor = skills.aptitude(self._gifted("crafting", 300), "crafting")
        average = skills.aptitude(self._gifted("crafting", 1000), "crafting")
        gifted = skills.aptitude(self._gifted("crafting", 2200), "crafting")
        self.assertLess(poor, average)
        self.assertLess(average, gifted)
        self.assertAlmostEqual(average, 1.0, places=2)
        self.assertGreaterEqual(poor, skills.MIN_APTITUDE)
        self.assertLessEqual(gifted, skills.MAX_APTITUDE)

    def test_talent_is_worth_under_half_a_level_of_training(self):
        """What `MIN_APTITUDE` and `MAX_APTITUDE` are actually deciding. A
        wider band was tried first and a prodigy beat a man four levels above
        him, which is not what practice is for."""
        from ascii_warriors.game import skills

        self.assertLess(skills.TALENT_WORTH, 0.5)
        checked = 0
        for level in range(2, skills.MAX_LEVEL):
            gap = int(level * skills.TALENT_WORTH) + 1
            if level + gap > skills.MAX_LEVEL:
                continue
            checked += 1
            gifted = self._gifted("crafting", 5000, level=level)
            dull = self._gifted("crafting", 0, level=level + gap)
            self.assertGreater(
                skills.ability(dull, "crafting"),
                skills.ability(gifted, "crafting"),
                "the best possible %d beat the worst possible %d"
                % (level, level + gap))
        self.assertGreater(checked, 8, "the sweep checked almost nothing")

    def test_the_most_gifted_apprentice_loses_to_a_dull_veteran(self):
        from ascii_warriors.game import skills

        gifted_novice = self._gifted("crafting", 5000, level=8)
        dull_veteran = self._gifted("crafting", 0, level=12)
        self.assertGreater(skills.ability(dull_veteran, "crafting"),
                           skills.ability(gifted_novice, "crafting"))

    def test_an_untrained_skill_is_still_untrained(self):
        """Aptitude multiplies; it does not grant. Being clever is not knowing
        how."""
        from ascii_warriors.game import skills

        prodigy = self._gifted("crafting", 5000, level=0)
        self.assertEqual(skills.ability(prodigy, "crafting"), 0.0)

    def test_aptitude_is_not_experience(self):
        """It must never be stored. A gifted crafter's *level* is what they
        trained, and a save that wrote aptitude into it would compound every
        time it was loaded."""
        from ascii_warriors.game import skills

        c = self._gifted("crafting", 2400, level=7)
        self.assertEqual(c.skills.level("crafting"), 7)
        self.assertGreater(skills.ability(c, "crafting"), 7)
        restored = type(c.skills)()
        for sid, lv in c.skills.known():
            restored.set_level(sid, lv)
        self.assertEqual(restored.level("crafting"), 7)

    def test_a_creature_with_no_attributes_is_simply_average(self):
        from ascii_warriors.game import skills

        class Bare:
            skills = None
            attributes = None

        self.assertEqual(skills.aptitude(Bare(), "crafting"), 1.0)
        self.assertEqual(skills.aptitude(self._who(), "no_such_skill"), 1.0)

    # -- where it reaches ------------------------------------------------------ #

    def test_a_gifted_crafter_makes_better_things(self):
        """The headline. Quality was skill plus a die minus difficulty, and a
        dull smith and a brilliant one turned out identical work."""
        from ascii_warriors.game import crafting

        def masterworks(gift):
            made = []
            for seed in range(60):
                maker = self._gifted("crafting", gift, level=9)
                made.append(crafting.ability(maker, "crafting")
                            if hasattr(crafting, "ability") else 0)
            return made

        from ascii_warriors.game import skills

        dull = skills.ability(self._gifted("crafting", 400, 9), "crafting")
        bright = skills.ability(self._gifted("crafting", 2400, 9), "crafting")
        self.assertGreater(bright, dull * 1.2)

    def test_the_fortress_and_the_adventurer_roll_the_same_talent(self):
        """Two quality rolls in two modes; both had skill and no attributes."""
        import inspect

        from ascii_warriors.fortress import fortress as fort_mod
        from ascii_warriors.game import crafting

        self.assertIn("ability(", inspect.getsource(crafting.craft))
        self.assertIn("ability(", inspect.getsource(fort_mod.Fortress._quality_for))

    def test_disease_resistance_finally_resists_something(self):
        """Rolled for every creature in the world, printed on the character
        sheet, and read by nothing. A syndrome is the one thing it could
        possibly have meant."""
        from ascii_warriors.game import venom

        frail = self._who(disease_resistance=200, toughness=1000)
        hardy = self._who(disease_resistance=3000, toughness=1000)
        self.assertGreater(venom.resistance(hardy), venom.resistance(frail))

    def test_a_musician_needs_musicality(self):
        """The last attribute in the game that reached nothing else."""
        from ascii_warriors.game import skills

        tin_ear = self._who(musicality=300, kinesthetic_sense=1000)
        tuneful = self._who(musicality=2600, kinesthetic_sense=1000)
        for c in (tin_ear, tuneful):
            c.skills.set_level("music", 8)
        self.assertGreater(skills.ability(tuneful, "music"),
                           skills.ability(tin_ear, "music"))

    def test_a_haggler_uses_the_four_attributes_the_table_named(self):
        """`_haggle_factor` multiplied both skills by `social_awareness` and
        ignored the analytical head and the memory for prices that appraisal
        actually declares."""
        import inspect

        from ascii_warriors.game import trade

        source = inspect.getsource(trade._haggle_factor)
        self.assertIn("ability(", source)
        self.assertNotIn('factor("social_awareness")', source)

    def test_combat_is_deliberately_left_alone(self):
        """Its attribute model is hand-written and has been calibrated against
        measurements in every milestone from v3.19 to v3.28. Running aptitude
        over the top of it would count agility twice and invalidate all of
        it."""
        import inspect

        from ascii_warriors.game import combat

        for fn in (combat.attack_power, combat.defense_power,
                   combat.compute_momentum):
            self.assertNotIn("ability(", inspect.getsource(fn))

    # -- what the player is told ------------------------------------------------ #

    def test_the_sheet_says_what_an_attribute_is_for(self):
        from ascii_warriors.ui.character_screen import _helps_with

        c = self._who()
        self.assertEqual(_helps_with(c, "creativity"), "")
        c.skills.set_level("crafting", 6)
        c.skills.set_level("lying", 3)
        line = _helps_with(c, "creativity")
        self.assertIn("Craftsdwarf", line)
        self.assertIn("Liar", line)

    def test_the_sheet_names_the_best_of_them_first(self):
        from ascii_warriors.ui.character_screen import _helps_with

        c = self._who()
        c.skills.set_level("crafting", 2)
        c.skills.set_level("lying", 9)
        self.assertLess(_helps_with(c, "creativity").index("Liar"),
                        _helps_with(c, "creativity").index("Craftsdwarf"))

    def test_a_knack_is_only_mentioned_when_there_is_one(self):
        from ascii_warriors.game import skills

        self.assertEqual(skills.aptitude_word(1.0), "")
        self.assertTrue(skills.aptitude_word(skills.MIN_APTITUDE))
        self.assertTrue(skills.aptitude_word(skills.MAX_APTITUDE))


class TestFlight(GameFixture):
    """`FLIER`, on ten creature definitions since the bestiary was written and
    read by no line of code in the project. A raven walked."""

    def _bird(self, cid="raven", at=None):
        from ascii_warriors.game.entity import make_creature

        c = make_creature(RNG(cid), cid)
        x, y, z = at or (self.game.player.x + 3, self.game.player.y, self.game.player.z)
        c.x, c.y, c.z = x, y, z
        self.game.add_creature(c)
        return c

    def _shaft(self, cell, depth=4):
        """A hole you actually fall down: the cell and the ones beneath it."""
        lm = self.game.local
        x, y, z = cell
        for dz in range(0, depth + 1):
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    if lm.in_bounds(x + dx, y + dy, z - dz):
                        lm.set_tile(x + dx, y + dy, z - dz, "chasm")

    def _pool(self, cell, tile_id="deep_water", w=4):
        lm = self.game.local
        x, y, z = cell
        for dx in range(w):
            lm.set_tile(x + dx, y, z, tile_id)

    # -- who flies ------------------------------------------------------------ #

    def test_the_bestiary_has_fliers_and_they_have_wings(self):
        from ascii_warriors.data import bodies as body_data
        from ascii_warriors.data import creatures as creature_data
        from ascii_warriors.game import flight
        from ascii_warriors.game.entity import make_creature

        fliers = [cid for cid, d in creature_data.CREATURES.items()
                  if d.has("FLIER")]
        self.assertGreaterEqual(len(fliers), 8)
        winged = 0
        for cid in fliers:
            c = make_creature(RNG(cid), cid)
            self.assertTrue(flight.is_flier(c), cid)
            self.assertTrue(flight.can_fly(c), cid)
            if flight.has_wings(c):
                winged += 1
        self.assertGreaterEqual(winged, len(fliers) - 1,
                                "wings are the point; only the demon may lack them")

    def test_nothing_without_the_flag_gets_off_the_ground(self):
        from ascii_warriors.game import flight
        from ascii_warriors.game.entity import make_creature

        for cid in ("cow", "human", "dwarf", "goblin", "carp"):
            self.assertFalse(flight.can_fly(make_creature(RNG(cid), cid)), cid)

    # -- gravity -------------------------------------------------------------- #

    def test_a_bird_does_not_fall_down_a_hole(self):
        from ascii_warriors.world import gravity

        cell = (self.game.player.x + 5, self.game.player.y + 5, self.game.player.z)
        self._shaft(cell)
        bird = self._bird(at=cell)
        self.assertEqual(gravity.settle(self.game, bird, self.game.rng), 0)
        self.assertEqual(bird.z, cell[2])

    def test_a_cow_in_the_same_hole_certainly_does(self):
        """The control. If this stops falling, the test above proves nothing."""
        from ascii_warriors.world import gravity

        cell = (self.game.player.x + 5, self.game.player.y + 5, self.game.player.z)
        self._shaft(cell)
        cow = self._bird("cow", at=cell)
        self.assertGreater(gravity.settle(self.game, cow, self.game.rng), 0)
        self.assertLess(cow.z, cell[2])

    def test_a_flier_is_never_counted_as_standing_on_nothing(self):
        from ascii_warriors.world import gravity

        cell = (self.game.player.x + 5, self.game.player.y + 5, self.game.player.z)
        self._shaft(cell)
        bird = self._bird(at=cell)
        self.assertNotIn(bird, gravity.unsupported_creatures(self.game))

    # -- what it can cross ----------------------------------------------------- #

    def test_air_is_a_road_to_a_flier_and_a_wall_to_everything_else(self):
        cell = (self.game.player.x + 5, self.game.player.y + 5, self.game.player.z)
        self._shaft(cell)
        bird = self._bird(at=(cell[0] - 2, cell[1], cell[2]))
        cow = self._bird("cow", at=(cell[0] - 2, cell[1] + 1, cell[2]))
        self.assertTrue(self.game.is_passable(*cell, bird))
        self.assertFalse(self.game.is_passable(*cell, cow))

    def test_rock_is_still_rock(self):
        """Flight is a set of exemptions, and this is not one of them."""
        lm = self.game.local
        cell = (self.game.player.x + 6, self.game.player.y + 6, self.game.player.z)
        lm.set_tile(*cell, "rock_wall")
        bird = self._bird(at=(cell[0] - 2, cell[1], cell[2]))
        self.assertFalse(self.game.is_passable(*cell, bird))

    def test_fire_is_deliberately_still_fire(self):
        lm = self.game.local
        cell = (self.game.player.x + 6, self.game.player.y + 8, self.game.player.z)
        lm.set_tile(*cell, "fire")
        bird = self._bird(at=(cell[0] - 2, cell[1], cell[2]))
        self.assertFalse(self.game.is_passable(*cell, bird))

    def test_magma_is_deliberately_still_magma(self):
        """A creature occupies a whole cell here, so "over the lava" is not a
        place there is any way to be."""
        lm = self.game.local
        cell = (self.game.player.x + 6, self.game.player.y + 7, self.game.player.z)
        lm.set_tile(*cell, "lava")
        bird = self._bird(at=(cell[0] - 2, cell[1], cell[2]))
        self.assertFalse(self.game.is_passable(*cell, bird))

    def test_a_bird_crosses_a_lake_without_swimming_it(self):
        from ascii_warriors.game import swimming

        cell = (self.game.player.x + 4, self.game.player.y + 4, self.game.player.z)
        self._pool(cell)
        bird = self._bird(at=cell)
        self.assertEqual(
            swimming.stroke_chance(bird, swimming.depth_of("deep_water")), 1.0)
        for _ in range(80):
            self.game._swim(5)
        self.assertFalse(bird.body.dead)
        self.assertNotIn(bird.id, self.game.drowning)

    def test_a_flooded_room_drowns_a_flier_like_everybody_else(self):
        """Water to the ceiling has no air in it. This is the one place wings
        buy nothing, and it is what keeps the fortress's sealed-room drowning
        honest now that demons and rocs can turn up in one."""
        from ascii_warriors.game import swimming
        from ascii_warriors.world import fluids

        bird = self._bird()
        self.assertLess(swimming.stroke_chance(bird, fluids.MAX_DEPTH), 0.2)

    def test_a_wandering_flier_is_not_kept_out_of_the_water(self):
        from ascii_warriors.game import swimming

        bird = self._bird()
        self.assertFalse(swimming.avoids(
            bird, 0, swimming.depth_of("deep_water")))

    # -- wings ----------------------------------------------------------------- #

    def test_taking_the_wings_off_brings_it_down(self):
        """The reason wings are modelled rather than flagged: the combat model
        has been able to sever a body part since long before this, and a wing
        is a body part."""
        from ascii_warriors.game import flight
        from ascii_warriors.world import gravity

        cell = (self.game.player.x + 5, self.game.player.y + 5, self.game.player.z)
        self._shaft(cell)
        bird = self._bird(at=cell)
        self.assertTrue(flight.can_fly(bird))
        for wing in flight.wings(bird):
            bird.body.sever(wing.id)
        self.assertFalse(flight.can_fly(bird))
        self.assertGreater(gravity.settle(self.game, bird, self.game.rng), 0)
        self.assertLess(bird.z, cell[2])

    def test_a_grounded_flier_says_why(self):
        from ascii_warriors.game import flight

        bird = self._bird()
        self.assertIsNone(flight.grounded_reason(bird))
        for wing in flight.wings(bird):
            bird.body.sever(wing.id)
        reason = flight.grounded_reason(bird)
        self.assertTrue(reason)
        self.assertIn("wing", reason)

    def test_the_demon_flies_without_wings_and_cannot_be_clipped(self):
        """Whatever is carrying it is not a pair of wings."""
        from ascii_warriors.game import flight
        from ascii_warriors.game.entity import make_creature

        demon = make_creature(RNG("d"), "demon")
        self.assertFalse(flight.has_wings(demon))
        self.assertTrue(flight.can_fly(demon))

    def test_a_senseless_bird_falls(self):
        from ascii_warriors.game import flight

        bird = self._bird()
        bird.body.unconscious = 50
        self.assertFalse(flight.can_fly(bird))
        bird.body.unconscious = 0
        bird.body.stunned = 20
        self.assertFalse(flight.can_fly(bird))

    def test_a_dead_bird_is_not_flying(self):
        from ascii_warriors.game import flight
        from ascii_warriors.world import gravity

        cell = (self.game.player.x + 5, self.game.player.y + 5, self.game.player.z)
        self._shaft(cell)
        bird = self._bird(at=cell)
        bird.body.dead = True
        self.assertFalse(flight.can_fly(bird))
        self.assertGreater(gravity.settle(self.game, bird, self.game.rng), 0)

    # -- the skill nothing could train ----------------------------------------- #

    def test_every_skill_can_be_reached(self):
        """`discipline` was granted by no profession, no creature and no
        labour, and awarded experience by nothing anywhere: every creature in
        the game had it at zero for ever, and `venom.resistance` reads it."""
        import os
        import re

        from ascii_warriors.data import creatures as creature_data
        from ascii_warriors.game import skills
        from ascii_warriors.ui import charcreate

        text = []
        for dirpath, _dirs, names in os.walk("ascii_warriors"):
            if "__pycache__" in dirpath:
                continue
            for name in names:
                if name.endswith(".py"):
                    with open(os.path.join(dirpath, name)) as fh:
                        text.append(fh.read())
        source = "\n".join(text)

        granted = set()
        for _desc, table in charcreate.PROFESSIONS.values():
            granted |= set(table)
        for defn in creature_data.CREATURES.values():
            granted |= set(defn.skills or {})
        trained = set(re.findall(r'add_exp\(\s*["\']([a-z_]+)["\']', source))
        # The families whose skill id is chosen at run time.
        dynamic = {sd.id for sd in skills.SKILLS.values()
                   if sd.category in ("craft", "medical", "weapon")}
        dynamic |= {"music", "poetry", "dancing", "striker", "biter", "kicker",
                    "wrestling", "rider"}
        for sid in skills.SKILLS:
            self.assertTrue(sid in granted or sid in trained or sid in dynamic,
                            "nothing grants or trains %s" % sid)

    def test_enduring_a_syndrome_teaches_discipline(self):
        from ascii_warriors.game import venom

        victim = self._bird("cow")
        venom.inject(victim, "rot", self.game.rng)
        before = victim.skills.exp("discipline")
        for _ in range(40):
            venom.tick(victim, 30, self.game.rng)
        self.assertGreater(victim.skills.exp("discipline"), before)

    def test_holding_together_after_a_death_teaches_discipline(self):
        from ascii_warriors.game import morale

        witness = self._bird("cow")
        witness.shaken = 1.0
        before = witness.skills.exp("discipline")
        for _ in range(30):
            morale.steady(witness, 10)
        self.assertGreater(witness.skills.exp("discipline"), before)

    def test_discipline_now_actually_shortens_a_syndrome(self):
        """It was read all along; there was simply never any of it."""
        from ascii_warriors.game import venom

        green = self._bird("cow")
        hard = self._bird("cow")
        hard.skills.set_level("discipline", 12)
        self.assertGreater(venom.resistance(hard), venom.resistance(green))

    def test_a_bird_cannot_carry_off_a_granite_block(self):
        from ascii_warriors.game import flight

        bird = self._bird("roc")
        self.assertTrue(flight.can_fly(bird))
        for _ in range(400):
            bird.inventory.add(Item("boulder", "granite"))
        self.assertGreater(bird.encumbrance(), flight.FLIGHT_LOAD)
        self.assertFalse(flight.can_fly(bird))
        self.assertEqual(flight.grounded_reason(bird), "too heavily laden")


class TestWhatAnAdventureSaveKeeps(GameFixture):
    """The other half of v3.34's round-trip guarantee.

    Adventure mode turned out to be clean, which is worth having a test say
    rather than having found once and forgotten -- most of the state the last
    dozen milestones added lives here.
    """

    #: Recomputed by whatever the creature does next, deliberately not saved.
    TRANSIENT = {"noise", "rng", "log", "local", "world", "owner", "defn",
                 "game", "fort", "scheduler", "path", "visible", "creatures",
                 "items_on_ground", "travel_target"}

    def _diff(self, before, after, label):
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
            if name.startswith("_") or name in self.TRANSIENT:
                continue
            was, now = getattr(before, name, "?"), getattr(after, name, "?")
            if callable(was):
                continue
            if summarise(was) != summarise(now):
                out.append("%s.%s: %r -> %r"
                           % (label, name, summarise(was), summarise(now)))
        return out

    def test_an_adventure_comes_back_the_way_it_went_in(self):
        from ascii_warriors.game.state import Game

        game = self.game
        player = game.player
        for _ in range(30):
            game.player_acts(100)
        # The state the recent milestones added, all set at once.
        game.drowning[player.id] = 7.5
        player.shaken = 0.8
        player.swing_bank = 33.0
        player.exposure = -0.4
        player.skills.set_level("discipline", 4)
        player.add_exp("swimming", 200)
        # An ordinary map has no ruins on it, so leaving this empty would let
        # the diff below pass on a field that was never written to the save at
        # all: nought and nought are the same shape.
        game.ruins = [{"kind": "smith", "x": 4, "y": 5, "z": player.z,
                       "material_name": "granite", "built": True}]

        back = Game.from_dict(game.to_dict())
        lost = self._diff(game, back, "game")
        lost += self._diff(player, back.player, "player")
        lost += self._diff(player.body, back.player.body, "player.body")
        lost += self._diff(player.needs, back.player.needs, "player.needs")
        lost += self._diff(player.skills, back.player.skills, "player.skills")
        self.assertEqual(lost, [], "a save lost state:\n  " + "\n  ".join(lost))

    def test_the_things_the_last_milestones_added_all_survive(self):
        """Named one at a time, because a shape-only diff would pass on a
        field that came back the right type and the wrong value."""
        from ascii_warriors.game.state import Game

        game = self.game
        p = game.player
        game.drowning[p.id] = 7.5
        p.shaken = 0.8
        p.swing_bank = 33.0
        p.skills.set_level("discipline", 4)
        p.skills.set_level("swimming", 6)
        ruin = {"kind": "smith", "x": 4, "y": 5, "z": p.z,
                "material_name": "granite", "built": True}
        game.ruins = [ruin]

        back = Game.from_dict(game.to_dict())
        bp = back.player
        self.assertAlmostEqual(back.drowning.get(p.id, 0.0), 7.5, places=3)
        self.assertAlmostEqual(getattr(bp, "shaken", 0.0), 0.8, places=3)
        self.assertAlmostEqual(getattr(bp, "swing_bank", 0.0), 33.0, places=3)
        self.assertEqual(bp.skills.level("discipline"), 4)
        self.assertEqual(bp.skills.level("swimming"), 6)
        self.assertEqual(back.ruins, [ruin])


class TestSpentAmmunition(GameFixture):
    """Every shot fired in the history of this project annihilated its own
    arrow. Throwing a dagger left the dagger on the ground; firing did
    `ammo.count -= 1` and that was the end of it."""

    def _archer(self, material="iron", count=30):
        p = self.game.player
        for item in list(p.inventory.items):
            p.inventory.remove(item, item.count)
        bow = Item("bow", "oak")
        p.inventory.add(bow)
        p.inventory.add(Item("arrow", material, count=count))
        p.inventory.auto_equip()
        return p, bow

    def _target(self, gear=()):
        from ascii_warriors.game.entity import make_creature

        p = self.game.player
        foe = make_creature(RNG("mark"), "goblin", faction="hostile")
        foe.x, foe.y, foe.z = p.x + 4, p.y, p.z
        for iid, material in gear:
            foe.inventory.add(Item(iid, material))
        foe.inventory.auto_equip()
        self.game.add_creature(foe)
        return foe

    def _arrows_at(self, cell):
        return sum(i.count for i in self.game.items_at(*cell)
                   if i.def_id == "arrow")

    def _volley(self, shots=60, material="iron", gear=()):
        from ascii_warriors.game import combat

        p, bow = self._archer(material, count=shots)
        landed = 0
        fired = 0
        for i in range(shots):
            ammo = p.inventory.ammo()
            if ammo is None or ammo.count <= 0:
                break
            foe = self._target(gear)
            cell = (foe.x, foe.y, foe.z)
            combat.ranged_attack(p, foe, bow, ammo, rng=RNG(700 + i),
                                 ground=self.game)
            fired += 1
            landed += self._arrows_at(cell)
            for item in list(self.game.items_at(*cell)):
                self.game.take_item(item, *cell)
            self.game.creatures.pop(foe.id, None)
        return fired, landed

    # -- the defect ----------------------------------------------------------- #

    def test_a_fired_arrow_exists_afterwards(self):
        fired, landed = self._volley(shots=40)
        self.assertEqual(fired, 40)
        self.assertGreater(landed, 0, "every arrow fired vanished")

    def test_not_every_arrow_survives_being_fired(self):
        """Otherwise an archer never runs out and the quiver is decorative."""
        fired, landed = self._volley(shots=60)
        self.assertLess(landed, fired)

    def test_the_quiver_still_empties(self):
        from ascii_warriors.game import combat

        p, bow = self._archer(count=8)
        for i in range(8):
            ammo = p.inventory.ammo()
            self.assertIsNotNone(ammo, "the quiver refilled itself")
            foe = self._target()
            combat.ranged_attack(p, foe, bow, ammo, rng=RNG(30 + i),
                                 ground=self.game)
            self.game.creatures.pop(foe.id, None)
        self.assertIsNone(p.inventory.ammo())

    def test_what_lands_is_one_arrow_and_not_the_quiver(self):
        """`spend` has to split the stack. Dropping the stack itself would put
        thirty arrows on the floor and leave the archer with none."""
        from ascii_warriors.game import combat

        p, bow = self._archer(count=30)
        foe = self._target()
        cell = (foe.x, foe.y, foe.z)
        combat.ranged_attack(p, foe, bow, p.inventory.ammo(), rng=RNG(3),
                             ground=self.game)
        on_floor = [i for i in self.game.items_at(*cell) if i.def_id == "arrow"]
        for item in on_floor:
            self.assertEqual(item.count, 1)
        left = p.inventory.ammo()
        self.assertIsNotNone(left)
        self.assertEqual(left.count, 29, "the quiver lost more than one arrow")
        # Nought or one on the floor: the round either survived or it broke,
        # and a broken one is gone rather than lying about in pieces.
        self.assertLessEqual(len(on_floor), 1)

    # -- what it is made of ---------------------------------------------------- #

    def test_a_steel_arrow_survives_where_an_obsidian_one_shatters(self):
        from ascii_warriors.game import ammo as ammo_mod

        self.assertGreater(ammo_mod.toughness(Item("arrow", "steel")),
                           ammo_mod.toughness(Item("arrow", "iron")))
        self.assertGreater(ammo_mod.toughness(Item("arrow", "iron")),
                           ammo_mod.toughness(Item("arrow", "obsidian")))
        tough, _l = self._volley(shots=60, material="steel")
        _f, tough_back = self._volley(shots=60, material="steel")
        _f2, brittle_back = self._volley(shots=60, material="obsidian")
        self.assertGreater(tough_back, brittle_back)

    def test_toughness_is_bounded_at_both_ends(self):
        from ascii_warriors.game import ammo as ammo_mod
        from ascii_warriors.data import materials as mat_data

        for mid in mat_data.MATERIALS:
            value = ammo_mod.toughness(Item("arrow", mid))
            self.assertGreaterEqual(value, ammo_mod.MIN_TOUGHNESS, mid)
            self.assertLessEqual(value, ammo_mod.MAX_TOUGHNESS, mid)

    # -- every way a shot can end ---------------------------------------------- #

    def test_a_missed_shot_lands_too(self):
        """Missing is the cheap case: the arrow is in the grass, not a rib."""
        from ascii_warriors.game import ammo as ammo_mod

        self.assertGreater(ammo_mod.MISS_SURVIVES, ammo_mod.HIT_SURVIVES)
        fired, landed = self._volley(shots=60, gear=(("mail_shirt", "iron"),))
        self.assertGreater(landed, 0)

    def test_firing_with_no_world_to_drop_into_does_not_crash(self):
        """Combat is called from two modes and from tests that have neither,
        which is the same reason v3.25 gave the melee path a `ground`."""
        from ascii_warriors.game import combat

        p, bow = self._archer(count=4)
        foe = self._target()
        result = combat.ranged_attack(p, foe, bow, p.inventory.ammo(),
                                      rng=RNG(11))
        self.assertIsNotNone(result)
        self.assertEqual(p.inventory.ammo().count, 3)

    def test_an_archer_can_shoot_dry_and_pick_them_back_up(self):
        """The whole point: forty tiles from anywhere, this is the difference
        between a bow and a stick."""
        from ascii_warriors.game import combat

        p, bow = self._archer(count=12)
        foe = self._target()
        cell = (foe.x, foe.y, foe.z)
        for i in range(12):
            ammo = p.inventory.ammo()
            if ammo is None:
                break
            combat.ranged_attack(p, foe, bow, ammo, rng=RNG(60 + i),
                                 ground=self.game)
            if foe.body.dead:
                self.game.creatures.pop(foe.id, None)
                foe = self._target()
                cell = (foe.x, foe.y, foe.z)
        self.assertIsNone(p.inventory.ammo(), "the quiver never emptied")
        recovered = 0
        for item in list(self.game.items_at(*cell)):
            if item.def_id == "arrow":
                recovered += item.count
                self.game.take_item(item, *cell)
                p.inventory.add(item)
        self.assertGreater(recovered, 0, "nothing to pick up")
        p.inventory.auto_equip()
        self.assertIsNotNone(p.inventory.ammo(), "could not rearm")

    def test_a_thrown_dagger_still_lands(self):
        """This half always worked. It is what made the other half obvious."""
        from ascii_warriors.game import actions

        p = self.game.player
        knife = Item("dagger", "iron")
        p.inventory.add(knife)
        actions.throw(self.game, knife, p.x + 3, p.y)
        found = False
        for dx in range(0, 5):
            if any(i.def_id == "dagger"
                   for i in self.game.items_at(p.x + dx, p.y, p.z)):
                found = True
        self.assertTrue(found, "the dagger vanished")


class TestThingsThatSaidSoAndDidNot(GameFixture):
    """Constants and tuples that described behaviour nothing implemented.

    Found by sweeping for module-level names that appear exactly once -- at
    their own definition -- and for parameters a function never reads. Most
    hits were legitimate (palettes, uniform dispatch signatures); these are
    the ones where the code was making a claim it did not keep.
    """

    def test_a_mount_lets_you_see_further(self):
        """Every other mounts constant was wired up. `SIGHT_BONUS` was
        declared, documented, and read by nothing."""
        from ascii_warriors.game import mounts
        from ascii_warriors.game.entity import make_creature

        g = self.game
        g.update_fov()
        on_foot = len(g.visible)

        horse = make_creature(RNG("horse"), "horse", faction="player")
        horse.x, horse.y, horse.z = g.player.x + 1, g.player.y, g.player.z
        g.add_creature(horse)
        horse.tame = True
        ok, _why = mounts.ride(g, horse)
        self.assertTrue(ok, "the test could not get on the horse")
        self.assertTrue(mounts.mounted(g))
        g.update_fov()
        self.assertGreater(len(g.visible), on_foot,
                           "riding shows you no more than walking does")

    def test_standing_in_a_fire_burns_you(self):
        """Fire is blunt to the tissue model, so it described itself as a
        bruise and `WOUND_KINDS` listed a "burn" nothing could produce."""
        from ascii_warriors.game import combat
        from ascii_warriors.game.body import WOUND_KINDS
        from ascii_warriors.game.entity import make_creature

        victim = make_creature(RNG("burnt"), "human")
        # One RNG, advanced. A fresh RNG("f") each pass replays one identical
        # roll forty times and tests nothing.
        rng = RNG("f")
        for _ in range(40):
            combat.trap_strike(victim, "fire", "", rng=rng)
            if any(w.kind == "burn" for p in victim.body.parts.values()
                   for w in p.wounds):
                break
        kinds = {w.kind for p in victim.body.parts.values() for w in p.wounds}
        self.assertIn("burn", kinds, "a fire leaves bruises")
        self.assertNotIn("bruise", kinds)
        self.assertIn("burn", WOUND_KINDS)

    def test_frostbite_is_not_a_bruise_either(self):
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature

        victim = make_creature(RNG("cold"), "human")
        rng = RNG("c")
        for _ in range(40):
            combat.trap_strike(victim, "frostbite", "", rng=rng)
            if any(w.kind == "frostbite" for p in victim.body.parts.values()
                   for w in p.wounds):
                break
        kinds = {w.kind for p in victim.body.parts.values() for w in p.wounds}
        self.assertIn("frostbite", kinds)

    def test_a_burn_names_every_layer_it_goes_through(self):
        """A blow that reaches skin, fat and muscle wounds all three, and the
        override has to survive the loop. The first version of it collided
        with the loop's own `wound` local, so from the second layer on it read
        back the `Wound` object the previous pass had just built."""
        from ascii_warriors.game import combat
        from ascii_warriors.game.body import Body

        body = Body("humanoid", 70000)
        clauses = body.apply_damage("upper_body", "blunt", 90000, 2, 300,
                                    RNG("deep"), wound="burn")
        self.assertTrue(clauses, "the blow did nothing")
        kinds = [w.kind for p in body.parts.values() for w in p.wounds]
        self.assertGreater(len(kinds), 1, "only one tissue layer was reached")
        self.assertEqual(set(kinds), {"burn"})

    def test_an_ordinary_blow_is_unchanged(self):
        """The clause table was rewritten; it must say what it said before."""
        from ascii_warriors.game.body import _tissue_clause

        self.assertEqual(_tissue_clause("skin", "cut", 0.1, 0.9),
                         "cutting the skin")
        self.assertEqual(_tissue_clause("skin", "cut", 0.5, 0.5),
                         "tearing the skin")
        self.assertEqual(_tissue_clause("skin", "cut", 0.9, 0.1),
                         "tearing the skin")
        self.assertEqual(_tissue_clause("skin", "cut", 1.0, 0.0),
                         "tearing apart the skin")
        self.assertEqual(_tissue_clause("bone", "fracture", 0.1, 0.9),
                         "chipping the bone")
        self.assertEqual(_tissue_clause("bone", "fracture", 0.5, 0.5),
                         "fracturing the bone")
        self.assertEqual(_tissue_clause("bone", "fracture", 1.0, 0.0),
                         "shattering the bone")
        self.assertEqual(_tissue_clause("fat", "bruise", 0.1, 0.9),
                         "bruising the fat")
        self.assertEqual(_tissue_clause("fat", "bruise", 0.9, 0.1),
                         "denting the fat")

    def test_every_wound_kind_can_actually_happen(self):
        """It listed a "puncture" and a "tear" that nothing produced."""
        import os

        from ascii_warriors.game.body import WOUND_KINDS

        src = ""
        for d, _dirs, files in os.walk("ascii_warriors"):
            if "__pycache__" in d:
                continue
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(d, f)) as fh:
                        src += fh.read()
        for kind in WOUND_KINDS:
            self.assertGreater(
                src.count('"%s"' % kind), 1,
                "%r is declared a wound kind and nothing makes one" % kind)

    def test_every_quest_kind_can_be_generated(self):
        """"deliver" was listed and had no builder at all."""
        from ascii_warriors.game import quests

        from ascii_warriors.world.history import Artifact

        world = self.game.world
        if not [a for a in world.artifacts if a.site_id is not None]:
            # `_quest_retrieve` needs something to retrieve, and whether a
            # 25-year pocket world forges one is luck. Give it one rather than
            # let the seed decide whether this test tests anything.
            art = Artifact(world.next_id("artifact"), "Testhammer", "",
                           "warhammer", "steel")
            art.site_id = world.sites[0].id
            world.artifacts.append(art)

        made = set()
        givers = [c for c in self.game.creatures.values() if not c.is_player]
        self.assertTrue(givers)
        for i in range(600):
            q = quests.generate_quest(RNG("q%d" % i), self.game,
                                      givers[i % len(givers)])
            if q is not None:
                made.add(q.kind)
        self.assertEqual(set(quests.QUEST_KINDS) - made, set(),
                         "a declared quest kind cannot be generated")
        self.assertEqual(made - set(quests.QUEST_KINDS), set())

    def test_every_conversation_topic_is_answered(self):
        """"ask_family" was listed, never offered and never handled."""
        import re

        from ascii_warriors.game import conversation

        with open("ascii_warriors/game/conversation.py") as fh:
            src = fh.read()
        handled = set(re.findall(r'topic == "([a-z_]+)"', src))
        for topic in conversation.TOPICS:
            self.assertIn(topic, handled,
                          "%r is a declared topic nobody answers" % topic)

    def test_every_event_kind_is_one_the_world_records(self):
        """It was missing the three a fortress ending or a reclaim writes and
        the one the living world writes when a ruin is moved back into."""
        import os
        import re

        from ascii_warriors.world.history import EVENT_KINDS

        # Counted as string literals, the way the wound-kind check is. Matching
        # the argument out of the call needs a regex, and a
        # `HistoricalEvent(world.next_id("event"), year, "site_founded", ...)`
        # defeats any regex that stops at the first bracket -- which is how an
        # earlier version of this test concluded the fortress records nothing.
        src = ""
        for d, _dirs, files in os.walk("ascii_warriors"):
            if "__pycache__" in d:
                continue
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(d, f)) as fh:
                        src += fh.read()
        # The four a fortress writes, and the one the living world writes when
        # somebody moves back into a ruin. All five were missing.
        for kind in ("site_founded", "site_abandoned", "site_destroyed",
                     "site_reclaimed", "founded_site", "resettled"):
            self.assertIn(kind, EVENT_KINDS,
                          "%s is recorded and not declared" % kind)
        for kind in EVENT_KINDS:
            self.assertGreater(
                src.count('"%s"' % kind), 1,
                "%r is a declared event kind nothing records" % kind)

    def test_the_hospital_asks_for_bandages_before_it_needs_them(self):
        """`BANDAGE_PER_DWARF` said the hospital keeps a stock and nothing
        read it, so the only warning came with somebody already bleeding."""
        from tests.test_fortress import embark
        from ascii_warriors.fortress import hospital, sim

        fort = embark("bandages")
        for item in list(fort.all_items()):
            if item.def_id == "bandage":
                fort.take_item(item)
        self.assertEqual(fort.stock_count("bandage"), 0)
        sim.step(fort)
        said = " ".join(getattr(m, "text", str(m)) for m in fort.log.recent(80))
        self.assertIn("bandage", said.lower())
        self.assertGreater(hospital.BANDAGE_PER_DWARF, 0)


class TestTheSlabInTheTower(unittest.TestCase):
    """The secret of raising the dead, and whether anywhere holds it.

    The help screen says it plainly: "a slab in a necromancer's tower -- is the
    secret of raising the dead. Read it and press Z." Every piece of that was
    written and every piece was tested -- `make_slab`, `_give_books`, `read`,
    `is_necromancer`, the raising itself -- and all of it was tested against
    creatures the tests built themselves. Nobody asked whether a world contains
    one. Two worlds in three had no tower standing at all, and the only other
    slab-bearer is a tomb lord who carries one three times in five, so the
    night half of the game was reachable by luck or not at all.

    These walk it: find the tower on the world map, go in, climb to the top,
    take the slab off the necromancer standing there, and read it.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _game(self, seed="night1"):
        rng = RNG(seed)
        world = generate_world(rng.sub("w"), size="pocket", history_years=80)
        return Game.new_game(
            world, {"race": "human", "profession": "warrior"}, rng)

    @staticmethod
    def _towers(world):
        return [s for s in world.sites
                if s.kind == "tower" and not s.is_ruin
                and s.owner_hf is not None]

    @staticmethod
    def _slabs(creature):
        from ascii_warriors.game import books

        return [it for it in creature.inventory.items
                if books.of(it) is not None
                and getattr(books.of(it), "secret", "") == "necromancy"]

    def test_a_world_has_towers_with_necromancers_in_them(self):
        """The measurement that opened this: it used to be none or one."""
        found = 0
        for seed in ("night1", "night2", "night3"):
            game = self._game(seed)
            towers = self._towers(game.world)
            self.assertTrue(towers, "%s: no tower anybody holds" % seed)
            found += len(towers)
        self.assertGreater(found, 5,
                           "towers are still as rare as they were")

    def test_the_named_necromancer_is_the_one_standing_there(self):
        """Not "a necromancer": the one the legends screen sent you after."""
        game = self._game()
        towers = self._towers(game.world)
        self.assertGreater(len(towers), 2, "hardly any tower has an owner")
        for site in towers[:3]:
            fig = game.world.figures[site.owner_hf]
            game.enter_world_tile(site.wx, site.wy)
            here = [c for c in game.creatures.values()
                    if c.hf_id == site.owner_hf and not c.body.dead]
            self.assertEqual(len(here), 1,
                             "%s is not in %s" % (fig.name, site.name))
            nec = here[0]
            self.assertEqual(nec.def_id, "necromancer")
            self.assertEqual(nec.name, fig.name)
            self.assertEqual(nec.faction, "hostile")
            self.assertTrue(
                [c for c in game.creatures.values()
                 if c.profession == "undead"],
                "%s has no dead in it" % site.name)

    def test_he_carries_the_secret_the_help_promises(self):
        """The slab is the reason to climb the tower."""
        carried = 0
        for seed in ("night1", "night2"):
            game = self._game(seed)
            for site in self._towers(game.world)[:3]:
                game.enter_world_tile(site.wx, site.wy)
                nec = next((c for c in game.creatures.values()
                            if c.hf_id == site.owner_hf), None)
                self.assertIsNotNone(nec)
                self.assertTrue(self._slabs(nec),
                                "%s carries no slab" % site.name)
                carried += 1
        self.assertGreater(carried, 2, "hardly any tower was entered")

    def test_you_can_climb_to_him_from_where_you_come_in(self):
        """A necromancer on a floor with no stair is a necromancer nobody meets."""
        from ascii_warriors.engine.pathfind import bfs_reachable

        game = self._game()
        site = self._towers(game.world)[0]
        game.enter_world_tile(site.wx, site.wy)
        nec = next(c for c in game.creatures.values()
                   if c.hf_id == site.owner_hf)
        start = (game.player.x, game.player.y, game.player.z)
        reach = bfs_reachable(start, game.local.path_neighbours,
                              max_nodes=200000)
        self.assertIn((nec.x, nec.y, nec.z), reach,
                      "%s stands where you cannot get to him" % nec.name)
        self.assertGreater(nec.z, game.player.z,
                           "he is meant to be upstairs")

    def test_taking_the_slab_and_reading_it_makes_you_a_necromancer(self):
        """The whole promise, end to end, out of a world nobody arranged."""
        from ascii_warriors.game import books, night

        game = self._game()
        site = self._towers(game.world)[0]
        game.enter_world_tile(site.wx, site.wy)
        nec = next(c for c in game.creatures.values()
                   if c.hf_id == site.owner_hf)
        self.assertFalse(night.is_necromancer(game.player))
        slab = self._slabs(nec)[0]
        nec.inventory.remove(slab)
        game.player.inventory.add(slab)
        lines = books.read(game, game.player, books.of(slab))
        self.assertTrue(lines)
        self.assertTrue(night.is_necromancer(game.player),
                        "the slab in the tower taught nothing")


class TestTheLedger(unittest.TestCase):
    """The world's record of where a named thing is, after you have moved it.

    The histories know which site every artifact lies in and whose hands it is
    in there, and `_quest_retrieve` reads exactly that: *"It lies at Blood
    Grave, a tomb."* v3.53 put the thing on the floor for you to pick up, and
    nothing told the histories you had. `site_id` and `holder_hf` went on
    naming the tomb and the dead king, so the generator would offer it again
    -- a quest to fetch what is already in your pack, which no pickup can ever
    complete because the pickup already happened. Measured on seed `ledger`:
    twelve offers in a hundred and twenty, state active, progress zero of one,
    and nothing at the site to change that.

    These walk the object and the record together: take it, be offered it,
    put it down, sell it, and die holding it.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        rng = RNG("ledger")
        self.world = generate_world(rng.sub("w"), size="small",
                                    history_years=150)
        self.game = Game.new_game(
            self.world, {"race": "human", "profession": "warrior"}, rng)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _loose_artifact(self):
        """An artifact on the floor under the player, and its record."""
        game = self.game
        art = next(a for a in self.world.artifacts if a.site_id is not None)
        site = self.world.site(art.site_id)
        game.enter_world_tile(site.wx, site.wy)
        item = None
        for c in list(game.creatures.values()):
            for i in list(c.inventory.items):
                if getattr(i, "artifact_id", None) == art.id:
                    c.inventory.remove(i)
                    item = i
        for pile in list(game.items_on_ground.values()):
            for i in list(pile):
                if getattr(i, "artifact_id", None) == art.id:
                    pile.remove(i)
                    item = i
        self.assertIsNotNone(item, "the artifact was not at its own site")
        p = game.player
        game.drop_item(item, p.x, p.y, p.z)
        return art, site, item

    def _offers(self, art, tag, tries=120):
        """How often the quest generator sends somebody after this one."""
        from ascii_warriors.game import quests

        n = 0
        for i in range(tries):
            q = quests._quest_retrieve(RNG("%s%d" % (tag, i)), self.game, None)
            if q is not None and q.artifact_id == art.id:
                n += 1
        return n

    def test_taking_an_artifact_moves_the_record(self):
        """Through the action a player actually presses."""
        from ascii_warriors.game import actions, renown

        art, _site, item = self._loose_artifact()
        actions.pick_up(self.game, item)
        fig = renown.figure(self.game)
        self.assertEqual(art.holder_hf, fig.id, "the histories missed it")
        self.assertIsNone(art.site_id,
                          "an artifact on a wandering adventurer is at no site")
        self.assertFalse(art.lost)

    def test_nobody_sends_you_after_what_you_are_carrying(self):
        """The defect, stated as the thing you would notice."""
        from ascii_warriors.game import actions

        art, _site, item = self._loose_artifact()
        before = self._offers(art, "before")
        self.assertGreater(before, 0, "nobody offered this one even at rest")
        actions.pick_up(self.game, item)
        self.assertEqual(self._offers(art, "after"), 0,
                         "sent after something in your own pack")

    def test_an_old_save_is_not_sent_after_its_own_pack(self):
        """Belt and braces, for the record the ledger never got to fix.

        A game saved before any of this carries `site_id` pointing at the
        tomb while the crown sits in the pack, and nothing on load repairs it.
        The generator refuses to offer an artifact the player is carrying
        whatever the record says.
        """
        from ascii_warriors.game import actions

        art, site, item = self._loose_artifact()
        actions.pick_up(self.game, item)
        art.site_id = site.id      # the state an old save loads with
        art.holder_hf = None
        self.assertEqual(self._offers(art, "stale"), 0,
                         "an old save is still sent after its own pack")

    def test_putting_it_down_makes_it_findable_again(self):
        """The record follows the object both ways, or it is not a record."""
        from ascii_warriors.game import actions

        art, site, item = self._loose_artifact()
        actions.pick_up(self.game, item)
        actions.drop(self.game, item)
        self.assertIsNone(art.holder_hf)
        self.assertEqual(art.site_id, site.id)
        self.assertFalse(art.lost)
        self.assertGreater(self._offers(art, "again"), 0,
                           "an artifact lying in a tomb nobody can be sent to")

    def test_the_legends_say_who_has_it(self):
        """You are a figure in this world's history from the first turn."""
        from ascii_warriors.game import actions
        from ascii_warriors.world import legends

        art, _site, item = self._loose_artifact()
        actions.pick_up(self.game, item)
        page = "\n".join(f.text for f in legends.artifact_lines(self.world,
                                                                art.id))
        self.assertIn("Held by %s." % self.game.player.name, page)

    def test_killing_the_holder_leaves_it_where_the_body_is(self):
        """It is on the floor, and the histories stop naming a dead man."""
        game = self.game
        found = None
        for a in self.world.artifacts:
            if a.site_id is None or a.holder_hf is None:
                continue
            s = self.world.site(a.site_id)
            game.enter_world_tile(s.wx, s.wy)
            holder = next((c for c in game.creatures.values()
                           if c.hf_id == a.holder_hf and not c.body.dead), None)
            if holder is not None and any(
                    getattr(i, "artifact_id", None) == a.id
                    for i in holder.inventory.items):
                found = (a, s, holder)
                break
        self.assertIsNotNone(found, "no artifact was in anybody's hands")
        art, site, holder = found
        holder.body.dead = True
        holder.body.death_cause = "slain"
        game.kill_creature(holder)
        self.assertIsNone(art.holder_hf, "a corpse is still holding it")
        self.assertEqual(art.site_id, site.id)
        floor = [i for pile in game.items_on_ground.values() for i in pile
                 if getattr(i, "artifact_id", None) == art.id]
        self.assertEqual(len(floor), 1, "it did not fall where he did")

    def test_selling_one_hands_the_record_over_too(self):
        """A crown sold in a town is a crown the histories place in that town."""
        from ascii_warriors.game import actions, trade

        art, site, item = self._loose_artifact()
        actions.pick_up(self.game, item)
        merchant = next((c for c in self.game.creatures.values()
                         if not c.is_player and c.hf_id is not None), None)
        self.assertIsNotNone(merchant, "nobody here to sell to")
        merchant.inventory.add(Item("coin", "silver", count=99999))
        ok, _msg = trade.sell(self.game, merchant, item)
        if not ok:
            self.skipTest("this merchant deals in other things")
        self.assertEqual(art.holder_hf, merchant.hf_id)
        self.assertEqual(art.site_id, site.id)

    def test_the_record_survives_a_save(self):
        """Where a named thing is, is world state."""
        from ascii_warriors.game import actions, renown
        from ascii_warriors.world.worldgen import World

        art, _site, item = self._loose_artifact()
        actions.pick_up(self.game, item)
        fig = renown.figure(self.game)
        again = World.from_dict(json.loads(json.dumps(self.world.to_dict())))
        back = next(a for a in again.artifacts if a.id == art.id)
        self.assertEqual(back.holder_hf, fig.id)
        self.assertIsNone(back.site_id)

    def test_nobody_says_a_dead_ruler_rules_here(self):
        """The seat refills within the season; until then it is empty."""
        from ascii_warriors.game import conversation

        game = self.game
        site = next(s for s in self.world.sites
                    if s.ruler_hf and not s.is_ruin)
        game.enter_world_tile(site.wx, site.wy)
        ruler = self.world.figures[site.ruler_hf]
        speaker = next((c for c in game.creatures.values()
                        if not c.is_player and c.defn.has("CAN_SPEAK")), None)
        self.assertIsNotNone(speaker, "nobody here to ask")
        said = "\n".join(f.text for f in conversation.say(
            game.player, speaker, "ask_site", game))
        self.assertIn("%s rules here." % ruler.display_name, said)
        ruler.died = self.world.year
        said = "\n".join(f.text for f in conversation.say(
            game.player, speaker, "ask_site", game))
        self.assertNotIn("rules here", said,
                         "a townsman named a corpse as the ruler")


class TestTheEmptyDeep(unittest.TestCase):
    """Six levels of cavern under every tile, and nothing alive in any of them.

    A local map is eleven z-levels and six of them are underground: caverns
    cut by cellular automata, ore and gem veins, and the README telling you to
    light a torch before you go down there. Measured over sixteen tiles around
    an adventurer's start: **three hundred and fifty-eight creatures of
    thirty-four kinds above the surface, ninety thousand walkable cells below
    it, and zero creatures in them.**

    `creature_data.spawnable` has taken an `underground` flag since it was
    written and eleven species carry `SUBTERRANEAN`. The one caller in the
    game passed a local variable set to `False` on the line above it and never
    changed -- so `spawnable(underground=True)` had never been called by
    anything. Four species live nowhere else in the table and so had never
    once existed: the cave spider, the giant cave spider, the giant cave
    swallow and the gremlin. `venom` carries an entry for the bite of one of
    them.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        rng = RNG("deep")
        self.world = generate_world(rng.sub("w"), size="small",
                                    history_years=120)
        self.game = Game.new_game(
            self.world, {"race": "human", "profession": "warrior"}, rng)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _walk(self, tiles=9):
        """Enter a few wild tiles and return what was found where.

        Wild rather than any: guards keep the wildlife budget down in an
        inhabited place, and a third of very little is nothing. Chosen by
        distance from the player over the whole map rather than by scanning a
        box around them, because how much open country a start has is a thing
        the dice decide.
        """
        game = self.game
        px, py = game.player.wx, game.player.wy
        wild = [
            (max(abs(x - px), abs(y - py)), x, y)
            for y in range(self.world.height)
            for x in range(self.world.width)
            if not self.world.tile(x, y).is_ocean
            and self.world.site_at(x, y) is None
        ]
        wild.sort()
        below, above, walked = [], [], 0
        for _d, x, y in wild[:tiles]:
            game.enter_world_tile(x, y)
            lm = game.local
            walked += 1
            for c in game.creatures.values():
                if c.is_player:
                    continue
                if c.z < lm.surface_z(c.x, c.y):
                    below.append(c)
                else:
                    above.append(c)
        return below, above, walked

    def test_the_caves_have_something_living_in_them(self):
        """The measurement that opened this, as a guard."""
        below, above, walked = self._walk()
        self.assertGreater(walked, 4, "hardly any wilderness to walk")
        self.assertTrue(above, "nothing above ground either -- bad fixture")
        # At least one per tile walked. Not "more than none": placing the
        # group and then walking every member of it up to `surface_z` leaves
        # a single straggler underground, which a floor of zero calls a pass.
        self.assertGreaterEqual(len(below), walked,
                                "the caves are still all but empty")

    def test_what_is_down_there_belongs_down_there(self):
        """Not a deer that fell in a hole."""
        below, above, _walked = self._walk()
        self.assertTrue(below)
        for c in below:
            self.assertTrue(
                c.defn.has("SUBTERRANEAN"),
                "%s is underground and has no business there" % c.def_id)
        # And the other direction: a cave dweller standing in a meadow means
        # the group was placed in the dark and then walked up into the sun.
        strays = [c for c in above if c.defn.has("SUBTERRANEAN")
                  and not set(c.defn.biomes) - {"cave"}]
        self.assertLessEqual(
            len(strays), len(below) // 4,
            "%d cave dwellers are standing about above ground" % len(strays))

    def test_the_species_that_live_only_underground_exist(self):
        """Four of them list no surface biome at all."""
        from ascii_warriors.data import creatures as creature_data

        only_below = {c.id for c in creature_data.CREATURES.values()
                      if "SUBTERRANEAN" in c.flags and c.frequency > 0
                      and not (set(c.biomes) - {"cave"})}
        self.assertTrue(only_below, "nothing in the table lives only below")
        below, _above, _walked = self._walk()
        found = {c.def_id for c in below} & only_below
        self.assertTrue(found,
                        "none of %s has ever existed" % sorted(only_below))

    def test_the_deep_is_not_paid_for_with_a_slower_turn(self):
        """The cave share comes out of the surface budget, not on top of it."""
        below, above, walked = self._walk()
        self.assertGreater(walked, 4)
        from ascii_warriors.game.state import WILDLIFE_MAX

        per_tile = (len(below) + len(above)) / float(walked)
        self.assertLess(per_tile, WILDLIFE_MAX * 4,
                        "a map got far more wildlife than the budget allows")
        self.assertGreater(len(below), 0)

    def test_they_are_still_down_there_after_a_while(self):
        """A cave dweller that walks into the sun is a cave dweller nowhere."""
        game = self.game
        px, py = game.player.wx, game.player.wy
        wild = [
            (max(abs(x - px), abs(y - py)), x, y)
            for y in range(self.world.height)
            for x in range(self.world.width)
            if not self.world.tile(x, y).is_ocean
            and self.world.site_at(x, y) is None
        ]
        wild.sort()
        # Stand on a tile that has somebody down there, rather than on
        # whichever tile a walk happened to end on -- which is a thing the
        # dice decide, and a skip is the one way a test can be wrong and say
        # nothing about it.
        here = []
        for _d, x, y in wild[:40]:
            game.enter_world_tile(x, y)
            lm = game.local
            here = [c for c in game.creatures.values()
                    if not c.is_player and c.z < lm.surface_z(c.x, c.y)]
            if here:
                break
        self.assertTrue(here, "no tile in forty had anything living below it")
        for _ in range(300):
            game.player_acts(ACTION_COST)
            game.advance()
        still = [c for c in here
                 if not c.body.dead and c.z < lm.surface_z(c.x, c.y)]
        self.assertGreater(len(still), len(here) // 2,
                           "most of the caves emptied out into the daylight")


class TestJewelleryInTheWild(unittest.TestCase):
    """The other half of v3.58: an adventurer finding what a fortress sets.

    The five pieces are one set of item definitions shared by both modes, and
    before the jeweller existed neither half could produce them -- so a ring
    was a row in a table with a value beside it and nothing else.
    """

    def test_the_treasure_table_has_something_to_find(self):
        from ascii_warriors.game.item import _LOOT_TABLE, random_loot

        self.assertIn("treasure", _LOOT_TABLE)
        found = set()
        for i in range(200):
            for item in random_loot(RNG("loot%d" % i), 4, ("treasure",)):
                found.add(item.def_id)
        for piece in ("ring", "earring", "bracelet", "amulet"):
            self.assertIn(piece, found,
                          "%s turns up in no hoard anywhere" % piece)

    def test_what_is_found_is_worth_something(self):
        from ascii_warriors.game.item import Item

        for piece in ("ring", "earring", "bracelet", "amulet", "crown"):
            self.assertGreater(Item(piece, "gold").value,
                               Item("rough_gem", "ruby").value,
                               "%s is worth less than the stone" % piece)


class TestTheWorldOutlivesTheCharacter(unittest.TestCase):
    """Retire an adventurer, and the next one walks into a world with them in it.

    Three places promised this and none of them could deliver: every world was
    generated fresh from a seed at the start of a game and lived only inside
    that game's save file, so there was no way to enter a world anybody had
    played in. `residents.RETIRED_WORTH` -- "an adventurer somebody retired
    here outranks anybody the world invented" -- had never once been added to
    a score in a game a player could reach.

    The whole loop is run once here, and the tests read the result.
    """

    @classmethod
    def setUpClass(cls):
        from ascii_warriors.game import artifacts as artifact_mod
        from ascii_warriors.game import renown as renown_mod
        from ascii_warriors.game import save as save_mod

        cls._tmp = tempfile.mkdtemp()
        cls._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = cls._tmp

        rng = RNG("outlives")
        world = generate_world(rng.sub("w"), size="pocket", history_years=60)
        # Somebody of the town's own race, so the town has a slot they fit.
        cls.site = next(s for s in world.sites
                        if s.is_settlement and getattr(s, "race", ""))
        first = Game.new_game(
            world, {"race": cls.site.race, "profession": "warrior"}, rng)
        first.player.name = "Kadol Testfist"
        first.enter_world_tile(cls.site.wx, cls.site.wy)
        # ...carrying something the world has a name for.
        cls.art_id = world.artifacts[0].id
        keepsake = artifact_mod.make(world.artifacts[0], rng)
        first.player.inventory.add(keepsake)
        first.player_took(keepsake)
        renown_mod.retire(first)
        cls.hero_id = first.player.hf_id
        cls.save_path = save_mod.save_game(first, first.player.name)
        cls.metas = save_mod.list_worlds()

        # ...and the next character, in the world off the disk.
        cls.world = save_mod.load_world(cls.metas[0]["path"])
        rng2 = RNG(save_mod.continue_seed(cls.world))
        cls.second = Game.new_game(
            cls.world, {"race": "human", "profession": "hunter"}, rng2)
        cls.second.enter_world_tile(cls.site.wx, cls.site.wy)

    @classmethod
    def tearDownClass(cls):
        if cls._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = cls._old

    # -- the world is a file ------------------------------------------------ #

    def test_saving_a_character_writes_the_world_to_a_file_of_its_own(self):
        from ascii_warriors.game import save as save_mod

        self.assertEqual(len(self.metas), 1)
        self.assertTrue(save_mod.world_path_for(self.metas[0]["uid"]).exists())

    def test_the_world_file_holds_the_adventurer_who_retired(self):
        fig = self.world.figures.get(self.hero_id)
        self.assertIsNotNone(fig)
        self.assertIn("retired", fig.flags)
        self.assertIsNone(fig.died)
        self.assertEqual(fig.site_id, self.site.id)

    def test_the_world_list_says_who_is_waiting_in_it(self):
        from ascii_warriors.game import save as save_mod

        self.assertIn("Kadol Testfist", self.metas[0].get("retired") or [])
        self.assertIn("Kadol Testfist", save_mod.describe_world(self.metas[0]))

    # -- and the next character finds them ---------------------------------- #

    def test_the_next_adventurer_meets_the_one_you_retired(self):
        """The whole point: they are standing in the town, by name."""
        here = [c for c in self.second.creatures.values()
                if c.hf_id == self.hero_id]
        self.assertEqual(len(here), 1)
        self.assertEqual(here[0].name, "Kadol Testfist")

    def test_a_retired_adventurer_outranks_anybody_the_world_invented(self):
        """What `RETIRED_WORTH` is for, guarded for the first time."""
        from ascii_warriors.world import residents as res_mod

        ranked = res_mod.residents(self.world, self.site)
        self.assertGreater(len(ranked), 1)
        self.assertEqual(ranked[0].id, self.hero_id)
        hero = self.world.figures[self.hero_id]
        others = max(res_mod.notability(self.world, f) for f in ranked[1:])
        self.assertGreater(res_mod.notability(self.world, hero), others)

    def test_what_you_retired_holding_is_in_their_hands_when_you_return(self):
        """Retirement is not a death and not a sale, so the crown stays with
        them -- but it has to be somewhere, or the next character meets the
        person and never sees it."""
        art = next(a for a in self.world.artifacts if a.id == self.art_id)
        self.assertEqual(art.holder_hf, self.hero_id)
        self.assertEqual(art.site_id, self.site.id)
        self.assertFalse(art.lost)
        them = next(c for c in self.second.creatures.values()
                    if c.hf_id == self.hero_id)
        held = [getattr(i, "artifact_id", None) for i in them.inventory.items]
        self.assertIn(self.art_id, held)

    def test_the_next_adventurer_can_hear_about_them(self):
        from ascii_warriors.game import conversation as conv

        said = conv.rumor_lines(self.second, hf_id=self.hero_id, n=3)
        self.assertTrue(said)
        self.assertTrue(any("Kadol Testfist" in ln for ln in said))

    def test_a_fortress_can_embark_in_a_world_somebody_retired_in(self):
        """The other half of the promise: "or a fortress in the same world"."""
        from ascii_warriors.fortress.fortress import Fortress

        spot = next((x, y) for y in range(self.world.height)
                    for x in range(self.world.width)
                    if self.world.tile(x, y).site_id is None
                    and not self.world.tile(x, y).is_ocean)
        fort = Fortress.embark(self.world, spot[0], spot[1], RNG("emb"))
        fig = fort.world.figures.get(self.hero_id)
        self.assertIsNotNone(fig)
        self.assertIn("retired", fig.flags)

    # -- what the world says about them ------------------------------------- #

    def test_the_legends_page_is_written_in_the_world_s_voice(self):
        from ascii_warriors.world import legends as legends_mod

        text = "\n".join(
            f.text for f in legends_mod.figure_lines(self.world, self.hero_id))
        self.assertIn("An adventurer who settled here.", text)
        self.assertNotIn("player", text)

    def test_settling_with_nothing_to_show_still_reads_like_a_sentence(self):
        hero = self.world.figures[self.hero_id]
        said = [e.text for e in self.world.events if self.hero_id in e.figures
                and e.kind == "hero_rose"]
        self.assertTrue(said)
        self.assertFalse(hero.kills)
        self.assertNotIn("0 notable", said[-1])
        self.assertIn(self.site.name, said[-1])


class TestWorldFiles(unittest.TestCase):
    """The bookkeeping under it: one file per world, and never the wrong one."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        self.rng = RNG("worldfiles")
        self.world = generate_world(self.rng.sub("w"), size="pocket",
                                    history_years=10)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def test_a_world_keeps_one_file_however_many_characters_play_in_it(self):
        from ascii_warriors.game import save as save_mod

        first = Game.new_game(
            self.world, {"race": "human", "profession": "warrior"}, self.rng)
        first.player.name = "One"
        save_mod.save_game(first, first.player.name)
        uid = self.world.uid
        second = Game.new_game(
            self.world, {"race": "human", "profession": "hunter"}, self.rng)
        second.player.name = "Two"
        save_mod.save_game(second, second.player.name)
        self.assertEqual(self.world.uid, uid)
        self.assertEqual(len(save_mod.list_worlds()), 1)

    def test_two_worlds_of_the_same_name_do_not_share_a_file(self):
        from ascii_warriors.game import save as save_mod

        other = generate_world(RNG("other").sub("w"), size="pocket",
                               history_years=10)
        other.name = self.world.name
        save_mod.save_world(self.world)
        save_mod.save_world(other)
        self.assertNotEqual(self.world.uid, other.uid)
        self.assertEqual(len(save_mod.list_worlds()), 2)

    def test_opening_a_save_adopts_a_world_that_has_no_file(self):
        """Every save carries a world; a save made before world files is
        the only copy of its own."""
        from ascii_warriors.game import save as save_mod

        game = Game.new_game(
            self.world, {"race": "human", "profession": "warrior"}, self.rng)
        path = save_mod.save_game(game, "Orphan")
        save_mod.delete_save(save_mod.world_path_for(self.world.uid))
        self.assertEqual(save_mod.list_worlds(), [])
        save_mod.load_game(path)
        self.assertEqual(len(save_mod.list_worlds()), 1)

    def test_opening_an_old_save_does_not_roll_the_world_back(self):
        """The world file is the world as the last character *left* it."""
        from ascii_warriors.game import save as save_mod
        from ascii_warriors.world import history as history_mod

        game = Game.new_game(
            self.world, {"race": "human", "profession": "warrior"}, self.rng)
        old_path = save_mod.save_game(game, "Early")
        history_mod.record(self.world, self.world.year, "hero_rose",
                           "Somebody else did something.", [], [])
        save_mod.save_world(self.world)
        moved_on = len(self.world.events)
        save_mod.load_game(old_path)
        self.assertEqual(len(save_mod.list_worlds()), 1)
        back = save_mod.load_world(save_mod.world_path_for(self.world.uid))
        self.assertEqual(len(back.events), moved_on)

    def test_a_fortress_that_falls_is_in_the_world_file(self):
        from ascii_warriors.fortress import sim as sim_mod
        from ascii_warriors.fortress.fortress import Fortress
        from ascii_warriors.game import save as save_mod

        spot = next((x, y) for y in range(self.world.height)
                    for x in range(self.world.width)
                    if self.world.tile(x, y).site_id is None
                    and not self.world.tile(x, y).is_ocean)
        fort = Fortress.embark(self.world, spot[0], spot[1], RNG("fell"))
        fort.lost = True
        fort.loss_reason = "abandoned"
        sim_mod.record_fall(fort, abandoned=True)
        save_mod.save_world(fort.world)
        back = save_mod.load_world(save_mod.list_worlds()[0]["path"])
        self.assertIsNotNone(back.preserved_map(spot[0], spot[1]))
        self.assertIn(fort.name, save_mod.list_worlds()[0].get("built") or [])

    def test_a_world_survives_its_own_file(self):
        from ascii_warriors.game import save as save_mod

        path = save_mod.save_world(self.world)
        back = save_mod.load_world(path)
        self.assertEqual(back.to_dict(), self.world.to_dict())

    def test_a_header_is_read_without_the_world_behind_it(self):
        """The title screen lists three kinds of file and a world is a
        megabyte of JSON, so a listing reads the front of each and stops."""
        import gzip
        import json

        from ascii_warriors.game import save as save_mod

        path = save_mod.save_world(self.world)
        with gzip.open(str(path), "rt", encoding="utf-8") as fh:
            head = fh.read(save_mod.HEADER_CHARS)
            self.assertTrue(fh.read(1), "the file is shorter than one header")
        self.assertIsNotNone(save_mod._header_of(head))
        with gzip.open(str(path), "rt", encoding="utf-8") as fh:
            whole = json.load(fh)
        meta = save_mod.read_meta(path)
        self.assertEqual(meta["name"], whole["meta"]["name"])
        self.assertEqual(meta["retired"], whole["meta"]["retired"])
        self.assertEqual(meta["saved_at"], whole["saved_at"])

    def test_a_listing_does_not_read_the_whole_world(self):
        """Proved by taking the tail away: a listing never reaches it."""
        from ascii_warriors.game import save as save_mod

        path = save_mod.save_world(self.world)
        data = path.read_bytes()
        path.write_bytes(data[:len(data) // 2])
        meta = save_mod.read_meta(path)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["name"], self.world.name)

    def test_a_header_that_is_not_at_the_front_is_still_read(self):
        import gzip
        import json

        from ascii_warriors.game import save as save_mod

        path = save_mod.save_dir() / ("odd" + save_mod.WORLD_SUFFIX)
        with gzip.open(str(path), "wt", encoding="utf-8") as fh:
            json.dump({"world": {"junk": "x" * (save_mod.HEADER_CHARS + 64)},
                       "version": 1, "saved_at": 7,
                       "meta": {"name": "Late"}}, fh)
        self.assertEqual(save_mod.read_meta(path)["name"], "Late")


class TestTheArcherShoots(unittest.TestCase):
    """The whole ranged path had never run for anybody but the player.

    `ai.py` shoots when the wielded weapon is ranged and there is ammunition
    readied. No creature in any world had ever had either, so
    `combat.ranged_attack`, `ammo.spend` and `ammo.land` -- the arrows that
    stick in the grass and the two in three that shatter -- were reachable
    only by the player's own bow.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        rng = RNG("archery")
        world = generate_world(rng.sub("w"), size="pocket", history_years=15)
        self.game = Game.new_game(
            world, {"race": "human", "profession": "warrior"}, rng)
        self.rng = rng

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _lane(self, length=8):
        """A clear line between the player and somebody at the far end."""
        from ascii_warriors.game.entity import make_creature

        game, p = self.game, self.game.player
        for dx in range(0, length + 1):
            game.local.set_tile(p.x + dx, p.y, p.z, "floor")
        archer = make_creature(self.rng, "elf_archer", faction="hostile",
                               level=3)
        archer.x, archer.y, archer.z = p.x + length - 2, p.y, p.z
        game.add_creature(archer)
        return archer

    def test_an_archer_across_the_room_shoots_at_you(self):
        game = self.game
        archer = self._lane()
        started = archer.inventory.ammo().count
        self.assertGreater(started, 0)
        for _ in range(40):
            if archer.body.dead or game.game_over:
                break
            game.player_acts(100)
        left = archer.inventory.ammo().count if archer.inventory.ammo() else 0
        self.assertLess(left, started, "the archer never loosed one")

    def test_the_arrows_it_spent_are_on_the_floor_afterwards(self):
        game = self.game
        archer = self._lane()
        for _ in range(40):
            if archer.body.dead or game.game_over:
                break
            game.player_acts(100)
        onground = [it for pile in game.items_on_ground.values() for it in pile
                    if it.defn.has("AMMO")]
        self.assertTrue(onground, "nothing it shot ever landed")


class TestTheTavernHasAFloor(unittest.TestCase):
    """The tile is declared, two features test for it, and nothing laid one.

    `tiles.py` has had a `tavern` floor with its own glyph since it was
    written. `_tavern_music` will not run unless the player is standing on
    one and `_applaud` pays a crowd more when they are indoors on one, and
    `sitegen._furnish` dropped tables and chairs into a tavern without ever
    laying its floor -- so no tavern in any world had one, and neither
    feature had ever happened.

    With a floor there is somewhere to put the house instruments, which is
    the other half: `performance.instrument_for` scores a bonus for the right
    instrument in the room and its own docstring says a game with no
    instruments in it performs identically to one with every instrument in
    it. Adventure mode was the second kind.
    """

    @classmethod
    def setUpClass(cls):
        from ascii_warriors.game import furnishings

        cls._tmp = tempfile.mkdtemp()
        cls._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = cls._tmp
        rng = RNG("tavern")
        cls.world = generate_world(rng.sub("w"), size="small", history_years=80)
        cls.game = Game.new_game(
            cls.world, {"race": "human", "profession": "bard"}, rng)
        cls.rng = rng
        cls.site = None
        for s in cls.world.sites:
            if not s.is_settlement:
                continue
            cls.game.enter_world_tile(s.wx, s.wy)
            if furnishings._tavern_cells(cls.game.local):
                cls.site = s
                break
        cls.cells = furnishings._tavern_cells(cls.game.local)

    @classmethod
    def tearDownClass(cls):
        if cls._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = cls._old

    def _room(self):
        return [it for pile in self.game.items_on_ground.values() for it in pile]

    def test_a_town_has_a_tavern_you_can_stand_in(self):
        self.assertIsNotNone(self.site, "no settlement in the world has one")
        self.assertGreaterEqual(len(self.cells), 4)
        for cell in self.cells:
            self.assertEqual(self.game.local.tile(*cell), "tavern")

    def test_the_tile_is_the_one_the_rest_of_the_game_asks_about(self):
        from ascii_warriors.world import sitegen, tiles as tile_data

        self.assertEqual(sitegen.ROOM_FLOORS["tavern"], "tavern")
        self.assertIn("tavern", tile_data.TILES)
        self.assertTrue(tile_data.get("tavern").walk)

    def test_the_house_keeps_something_to_play(self):
        held = {it.defn.id for it in self._room() if it.defn.has("INSTRUMENT")}
        self.assertTrue(held, "a tavern with nothing in it to play")

    def test_what_is_in_the_room_is_worth_something_to_the_song(self):
        from ascii_warriors.game import performance

        folk = [c for c in self.game.creatures.values() if not c.is_player]
        pairs = [(c, f) for c in folk
                 for f in performance.repertoire(self.world, c)
                 if f.kind == "music"]
        if not pairs:
            for c in folk[:4]:
                performance.teach_civ(self.world, self.rng, c, None, n=2)
            pairs = [(c, f) for c in folk
                     for f in performance.repertoire(self.world, c)
                     if f.kind == "music"]
        self.assertTrue(pairs)
        who, form = pairs[0]
        bare = performance.score(self.world, who, form, available=[])
        room = performance.score(self.world, who, form, available=self._room())
        self.assertGreaterEqual(room - bare,
                                -performance.NO_INSTRUMENT)

    def test_somebody_plays_while_you_are_standing_in_it(self):
        from ascii_warriors.game import performance

        game = self.game
        p = game.player
        p.x, p.y, p.z = self.cells[0]
        folk = [c for c in game.creatures.values()
                if not c.is_player and not c.is_hostile_to(p)]
        self.assertTrue(folk)
        folk[0].x, folk[0].y, folk[0].z = self.cells[min(1, len(self.cells) - 1)]
        for c in folk[:4]:
            performance.teach_civ(self.world, self.rng, c, None, n=2)
        game.update_fov()
        game._tavern_wait = 1
        before = len(game.log.recent(600))
        game._tavern_music(10)
        said = game.log.recent(600)[before:]
        text = " ".join(
            getattr(x, "text", str(x)) for ln in said
            for x in (ln if isinstance(ln, list) else [ln]))
        self.assertTrue(text.strip(), "nobody in the tavern did anything")


class TestTheErrand(unittest.TestCase):
    """The loop the README spends most of its words on, walked end to end.

    `tools/play` looked after a body -- drink, eat, sleep, hit what is next
    to it -- and nothing else, for a dozen versions. Travel, a town, somebody
    to talk to, work to take, a place the work points at, the thing waiting
    there and the walk back to be paid had never been driven by anything, and
    six defects were sitting in it.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        self.rng = RNG("errand")
        self.world = generate_world(self.rng.sub("w"), size="pocket",
                                    history_years=30)
        self.game = Game.new_game(
            self.world, {"race": "human", "profession": "warrior"}, self.rng)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _in_a_town(self):
        """Stand the player in a settlement and return it."""
        town = next(s for s in self.world.sites if s.is_settlement)
        self.game.enter_world_tile(town.wx, town.wy)
        return town

    def _employer(self):
        return next(c for c in self.game.creatures.values()
                    if c.ai and c.ai.role in ("lord", "tavern_keeper", "guard",
                                              "priest", "merchant"))

    # -- every job names a place -------------------------------------------- #

    def test_every_kind_of_work_says_where_to_go(self):
        """A bounty pinned the square you were standing on and named no
        destination at all -- 21 of 21 measured."""
        from ascii_warriors.game import quests as quest_mod

        self._in_a_town()
        giver = self._employer()
        kinds = set()
        for _ in range(40):
            self.game.quests = quest_mod.QuestLog()
            q = quest_mod.generate_quest(self.game.rng, self.game, giver)
            if q is None:
                continue
            kinds.add(q.kind)
            self.assertTrue(q.site_name, "%s sends you nowhere" % q.kind)
            self.assertNotEqual(
                (q.wx, q.wy), (self.game.player.wx, self.game.player.wy),
                "%s pins the square you are standing on" % q.kind)
        self.assertGreaterEqual(len(kinds), 3)

    def test_a_job_remembers_where_it_was_taken(self):
        from ascii_warriors.game import quests as quest_mod

        town = self._in_a_town()
        giver = self._employer()
        q = None
        for _ in range(30):
            self.game.quests = quest_mod.QuestLog()
            q = quest_mod.generate_quest(self.game.rng, self.game, giver)
            if q is not None:
                break
        self.assertIsNotNone(q)
        self.assertEqual((q.giver_wx, q.giver_wy), (town.wx, town.wy))
        self.assertEqual(q.giver_site_name, town.name)
        text = "\n".join(q.detail_lines())
        self.assertIn(town.name, text)
        back = quest_mod.Quest.from_dict(
            json.loads(json.dumps(q.to_dict())))
        self.assertEqual((back.giver_wx, back.giver_wy), (q.giver_wx, q.giver_wy))
        self.assertEqual(back.giver_site_name, q.giver_site_name)

    # -- and the thing is there when you get there --------------------------- #

    def _bounty(self):
        from ascii_warriors.game import quests as quest_mod

        self._in_a_town()
        giver = self._employer()
        for _ in range(60):
            q = quest_mod._quest_bounty(self.game.rng, self.game, giver)
            if q is not None:
                return q
        self.fail("no bounty could be built at all")

    def test_what_a_bounty_sends_you_after_is_where_it_sends_you(self):
        """Measured before this: present on seven arrivals in forty-two."""
        from ascii_warriors.game import quests as quest_mod

        q = self._bounty()
        self.game.quests = quest_mod.QuestLog()
        self.game.quests.accept(q)
        self.game.enter_world_tile(q.wx, q.wy)
        here = [c for c in self.game.creatures.values()
                if c.def_id == q.target_def and not c.body.dead]
        self.assertTrue(here, "sent to hunt %s where there are none"
                        % q.target_def)

    def test_there_are_enough_of_them_to_finish_the_job(self):
        """A group is one to three and a bounty asks for three to seven, so
        one roll leaves you standing in an empty field with two kills."""
        from ascii_warriors.game import quests as quest_mod

        checked = 0
        for _ in range(6):
            q = self._bounty()
            self.game.quests = quest_mod.QuestLog()
            self.game.quests.accept(q)
            self.game.enter_world_tile(q.wx, q.wy)
            here = [c for c in self.game.creatures.values()
                    if c.def_id == q.target_def and not c.body.dead]
            self.assertGreaterEqual(
                len(here), q.goal,
                "sent for %d %s and found %d" % (q.goal, q.target_def,
                                                 len(here)))
            checked += 1
            self._in_a_town()
        self.assertEqual(checked, 6)

    def test_they_are_there_on_a_map_you_have_already_walked_across(self):
        """The map cache restores the wildlife that was there before you were
        sent after anything."""
        from ascii_warriors.game import quests as quest_mod

        q = self._bounty()
        self.game.enter_world_tile(q.wx, q.wy)      # cache it, with no job
        self._in_a_town()
        self.game.quests = quest_mod.QuestLog()
        self.game.quests.accept(q)
        self.game.enter_world_tile(q.wx, q.wy)      # and come back with one
        here = [c for c in self.game.creatures.values()
                if c.def_id == q.target_def and not c.body.dead]
        self.assertGreaterEqual(len(here), q.goal)

    def test_a_bounty_never_sends_you_to_a_field_for_a_cave_dweller(self):
        from ascii_warriors.data import creatures as creature_data

        self._in_a_town()
        giver = self._employer()
        from ascii_warriors.game import quests as quest_mod

        for _ in range(60):
            q = quest_mod._quest_bounty(self.game.rng, self.game, giver)
            if q is None:
                continue
            self.assertFalse(
                creature_data.get(q.target_def).has("SUBTERRANEAN"),
                "sent above ground after %s" % q.target_def)

    # -- and the body you take it with --------------------------------------- #

    def test_an_adventurer_sets_out_able_to_bind_a_wound(self):
        """Bleeding is what kills an adventurer, and the kit had rope and
        torches in it and nothing to bind anything with."""
        from ascii_warriors.game import medical

        p = self.game.player
        self.assertTrue(p.inventory.by_def("bandage"))
        ok, why = medical.can_treat(p, "bandage")
        self.assertTrue(ok, why)
        ok, why = medical.can_treat(p, "splint")
        self.assertTrue(ok, why)

    def test_what_you_are_carrying_counts_as_something_to_drink(self):
        """The fallback reached exactly one item id, so an adventurer with
        four skins of ale was told there was nothing to drink."""
        from ascii_warriors.game import actions

        game = self.game
        p = game.player
        for it in list(p.inventory.items):
            if it.def_id == "water_drink":
                p.inventory.items.remove(it)
        # Somewhere with no water in reach.
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                game.local.set_tile(p.x + dx, p.y + dy, p.z, "floor")
        self.assertFalse(actions.water_source_near(game))
        self.assertTrue([i for i in p.inventory.items if i.is_drink])
        p.needs.thirst = 20000
        self.assertGreater(actions.drink(game), 0, "it refused the ale")
        self.assertLess(p.needs.thirst, 20000)


class TestTheWayAcrossTheWorld(unittest.TestCase):
    """`route_overland`: one place that knows how to cross a coastline.

    The travel screen has drawn a route with A* since it was written and kept
    it to itself, so the driver that plays the game walked greedily at its
    destination and tried four neighbours when a step failed. Three runs in
    ten spent every one of four thousand turns hemmed in by a bay.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        rng = RNG("overland")
        self.world = generate_world(rng.sub("w"), size="small",
                                    history_years=20)
        self.game = Game.new_game(
            self.world, {"race": "human", "profession": "warrior"}, rng)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _reachable_towns(self):
        return [s for s in self.world.sites if s.is_settlement
                and self.game.route_overland(s.wx, s.wy)]

    def test_it_finds_a_way_to_the_places_there_is_a_way_to(self):
        p = self.game.player
        towns = self._reachable_towns()[:8]
        self.assertTrue(towns)
        for town in towns:
            route = self.game.route_overland(town.wx, town.wy)
            self.assertEqual(route[0], (p.wx, p.wy))
            self.assertEqual(route[-1], (town.wx, town.wy))

    def test_and_says_so_when_there_is_not(self):
        """Some towns are across open water. Measured on one small world: ten
        of forty-five settlements and sixteen of sixty-one sites."""
        far = [s for s in self.world.sites
               if not self.game.route_overland(s.wx, s.wy)]
        for site in far:
            self.assertEqual(self.game.route_overland(site.wx, site.wy), [])

    def test_the_route_never_crosses_open_water(self):
        town = max(self._reachable_towns(),
                   key=lambda s: max(abs(s.wx - self.game.player.wx),
                                     abs(s.wy - self.game.player.wy)))
        route = self.game.route_overland(town.wx, town.wy)
        self.assertTrue(route)
        for wx, wy in route:
            self.assertFalse(self.world.tile(wx, wy).is_ocean,
                             "the route swims through (%d, %d)" % (wx, wy))

    def test_every_step_of_it_is_one_the_game_will_take(self):
        town = self._reachable_towns()[0]
        route = self.game.route_overland(town.wx, town.wy)
        self.assertTrue(route)
        for a, b in zip(route, route[1:]):
            self.assertLessEqual(max(abs(b[0] - a[0]), abs(b[1] - a[1])), 1)
        # And it walks: the driver's whole errand rests on this.
        p = self.game.player
        for _ in range(len(route) - 1):
            nxt = self.game.route_overland(town.wx, town.wy)[1]
            self.assertTrue(self.game.travel_step(nxt[0] - p.wx, nxt[1] - p.wy))
        self.assertEqual((p.wx, p.wy), (town.wx, town.wy))

    def test_there_is_no_route_into_the_sea(self):
        ocean = next(((x, y) for y in range(self.world.height)
                      for x in range(self.world.width)
                      if self.world.tile(x, y).is_ocean), None)
        self.assertIsNotNone(ocean, "a world with no sea in it")
        self.assertEqual(self.game.route_overland(*ocean), [])

    def test_nobody_is_sent_somewhere_they_cannot_walk_to(self):
        """Every builder was free to name a town across the water."""
        from ascii_warriors.game import quests as quest_mod

        town = self._reachable_towns()[0]
        self.game.enter_world_tile(town.wx, town.wy)
        giver = next(c for c in self.game.creatures.values()
                     if c.ai and c.ai.role in ("lord", "tavern_keeper",
                                               "guard", "priest", "merchant"))
        offered = 0
        for _ in range(30):
            self.game.quests = quest_mod.QuestLog()
            q = quest_mod.generate_quest(self.game.rng, self.game, giver)
            if q is None:
                continue
            offered += 1
            self.assertTrue(
                self.game.route_overland(q.wx, q.wy),
                "%s sends you to (%d, %d), which you cannot walk to"
                % (q.kind, q.wx, q.wy))
        self.assertGreater(offered, 10)
