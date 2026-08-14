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
        from ascii_warriors.game.entity import make_creature

        c = make_creature(self.game.rng, def_id, faction=faction)
        p = self.game.player
        c.x, c.y, c.z = p.x + 1, p.y, p.z
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
        """A walkable cell beside the player."""
        p = self.game.player
        for ox, oy in ((dx, dy), (-dx, dy), (dx, -dy), (0, 1), (1, 1), (-1, -1)):
            cell = (p.x + ox, p.y + oy, p.z)
            if self.game.local.walkable(*cell):
                return cell
        return None

    def _trap(self, kind="pit"):
        cell = self._here()
        if cell is None:
            self.skipTest("no walkable ground beside the player")
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
        mattering for half the trap."""
        cell, _trap = self._trap("dart")
        p = self.game.player
        p.venom = []
        landed = self.traps._hurt(self.game, p, "dart")
        if landed:
            self.skipTest("the dart got through this time")
        self.assertFalse(p.venom)

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
