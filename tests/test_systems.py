"""Tests for medicine, trade, companions, weather and light sources."""

from __future__ import annotations

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
