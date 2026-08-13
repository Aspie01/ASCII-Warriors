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
