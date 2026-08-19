"""Tests for the simulation: bodies, combat, items, world and save/load."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from ascii_warriors.engine.rng import RNG
from ascii_warriors.game import combat, crafting
from ascii_warriors.game.attributes import ALL_ATTRS, Attributes, roll_attributes
from ascii_warriors.game.body import Body
from ascii_warriors.game.entity import Creature, make_creature
from ascii_warriors.game.inventory import Inventory
from ascii_warriors.game.item import Item, corpse_of, make_item, starting_kit
from ascii_warriors.game.log import MessageLog
from ascii_warriors.game.needs import Needs
from ascii_warriors.game.personality import Personality, roll_personality
from ascii_warriors.game.skills import SkillSet, exp_for_level, level_from_exp


class TestAttributes(unittest.TestCase):
    def test_defaults_and_clamping(self):
        a = Attributes()
        for attr in ALL_ATTRS:
            self.assertEqual(a.get(attr), 1000)
        a.set("strength", 99999)
        self.assertEqual(a.get("strength"), 5000)
        a.set("strength", -50)
        self.assertEqual(a.get("strength"), 0)

    def test_factor_monotonic(self):
        a = Attributes()
        a.set("strength", 200)
        low = a.factor("strength")
        a.set("strength", 1000)
        mid = a.factor("strength")
        a.set("strength", 4000)
        high = a.factor("strength")
        self.assertLess(low, mid)
        self.assertLess(mid, high)
        self.assertAlmostEqual(mid, 1.0, places=3)

    def test_modifiers(self):
        a = Attributes({"agility": 1000})
        a.set_modifier("agility", -300)
        self.assertEqual(a.get("agility"), 700)
        self.assertEqual(a.base("agility"), 1000)
        a.clear_modifiers()
        self.assertEqual(a.get("agility"), 1000)

    def test_roll_and_round_trip(self):
        a = roll_attributes(RNG(1), {"strength": 1500})
        self.assertGreater(a.get("strength"), 500)
        clone = Attributes.from_dict(json.loads(json.dumps(a.to_dict())))
        for attr in ALL_ATTRS:
            self.assertEqual(clone.get(attr), a.get(attr))


class TestSkills(unittest.TestCase):
    def test_level_curve(self):
        self.assertEqual(exp_for_level(0), 0)
        for lv in range(1, 21):
            self.assertGreater(exp_for_level(lv), exp_for_level(lv - 1))
            self.assertEqual(level_from_exp(exp_for_level(lv)), lv)

    def test_training(self):
        s = SkillSet()
        self.assertEqual(s.level("sword"), 0)
        gained = None
        for _ in range(50):
            gained = s.add_exp("sword", 100) or gained
        self.assertGreater(s.level("sword"), 0)
        self.assertIsNotNone(gained)
        self.assertIsNone(s.add_exp("no_such_skill", 500))

    def test_progress_and_rust(self):
        s = SkillSet({"axe": 3})
        self.assertEqual(s.level("axe"), 3)
        self.assertTrue(0.0 <= s.progress("axe") <= 1.0)
        s.rust("axe", 10 ** 9)
        self.assertEqual(s.level("axe"), 0)

    def test_round_trip(self):
        s = SkillSet({"sword": 4, "dodging": 2})
        clone = SkillSet.from_dict(json.loads(json.dumps(s.to_dict())))
        self.assertEqual(clone.level("sword"), 4)
        self.assertEqual(clone.level("dodging"), 2)


class TestPersonality(unittest.TestCase):
    def test_ranges(self):
        p = roll_personality(RNG(1), "goblin")
        for value in p.facets.values():
            self.assertTrue(0 <= value <= 100)
        for value in p.values.values():
            self.assertTrue(-50 <= value <= 50)
        self.assertTrue(p.describe())
        self.assertTrue(0.1 <= p.bravery_factor() <= 2.0)

    def test_racial_bias(self):
        rng = RNG(7)
        goblins = [roll_personality(rng, "goblin").facet("cruelty") for _ in range(60)]
        elves = [roll_personality(rng, "elf").facet("cruelty") for _ in range(60)]
        self.assertGreater(sum(goblins) / 60.0, sum(elves) / 60.0)

    def test_round_trip(self):
        p = roll_personality(RNG(2), "dwarf")
        clone = Personality.from_dict(json.loads(json.dumps(p.to_dict())))
        self.assertEqual(clone.facets, p.facets)


class TestBody(unittest.TestCase):
    def test_construction(self):
        b = Body("humanoid", 70000)
        self.assertTrue(b.can_stand())
        self.assertTrue(b.can_see())
        self.assertTrue(b.can_breathe())
        self.assertEqual(b.can_grasp(), 2)
        self.assertFalse(b.dead)
        self.assertAlmostEqual(b.blood_fraction(), 1.0)

    def test_damage_progresses_through_tissues(self):
        b = Body("humanoid", 70000)
        rng = RNG(1)
        clauses = b.apply_damage("upper_body", "edge", 60000, 20000, 4000, rng)
        self.assertTrue(clauses)
        part = b.part("upper_body")
        self.assertLess(part.tissues["skin"], 1.0)
        self.assertGreater(part.damage_fraction(), 0.0)

    def test_severing_head_kills(self):
        b = Body("humanoid", 70000)
        b.sever("head")
        self.assertTrue(b.dead)
        self.assertIn("head", b.death_cause)

    def test_severing_takes_children(self):
        b = Body("humanoid", 70000)
        b.sever("left_arm_upper")
        self.assertTrue(b.part("left_arm_lower").gone)
        self.assertTrue(b.part("left_arm_end").gone)
        self.assertEqual(b.can_grasp(), 1)

    def test_blood_loss_kills(self):
        b = Body("humanoid", 70000)
        b.apply_blood_loss(b.max_blood * 0.9)
        self.assertTrue(b.dead)
        self.assertEqual(b.death_cause, "bled to death")

    def test_healing_over_time(self):
        b = Body("humanoid", 70000)
        rng = RNG(3)
        b.apply_damage("left_leg_upper", "edge", 40000, 2000, 3000, rng)
        hurt = b.part("left_leg_upper").damage_fraction()
        b.rest_heal(20000, 1.5)
        self.assertLess(b.part("left_leg_upper").damage_fraction(), hurt)

    def test_round_trip(self):
        b = Body("humanoid", 70000)
        b.apply_damage("head", "blunt", 30000, 100, 500, RNG(4))
        clone = Body.from_dict(json.loads(json.dumps(b.to_dict())))
        self.assertEqual(clone.part("head").damage_fraction(),
                         b.part("head").damage_fraction())
        self.assertEqual(clone.dead, b.dead)

    def test_status_output(self):
        b = Body("humanoid", 70000)
        self.assertEqual(b.wound_summary(), "unhurt")
        self.assertTrue(b.status_lines())


class TestItems(unittest.TestCase):
    def test_naming_and_weight(self):
        sword = Item("long_sword", "steel", quality=5)
        name = sword.name()
        self.assertIn("steel", name)
        self.assertIn("long sword", name)
        self.assertTrue(name.startswith("#"))
        self.assertGreater(sword.weight, 0.5)
        self.assertEqual(Item("axe", "iron").name(article=True), "an iron axe")
        self.assertEqual(Item("mace", "steel").name(article=True), "a steel mace")

    def test_stacking(self):
        a = Item("coin", "silver", count=10)
        b = Item("coin", "silver", count=5)
        self.assertTrue(a.stack_with(b))
        self.assertEqual(a.count, 15)
        self.assertFalse(a.stack_with(Item("coin", "gold", count=1)))
        split = a.split(4)
        self.assertEqual(split.count, 4)
        self.assertEqual(a.count, 11)

    def test_predicates(self):
        self.assertTrue(Item("sword", "iron").is_weapon)
        self.assertTrue(Item("mail_shirt", "iron").is_armor)
        self.assertTrue(Item("shield", "oak").is_shield)
        self.assertTrue(Item("meat", "meat").is_edible)
        self.assertTrue(Item("wine", "alcohol").is_drink)
        self.assertTrue(Item("arrow", "iron").is_ammo)
        self.assertTrue(Item("torch", "oak").is_light)

    def test_material_affects_damage_class(self):
        self.assertEqual(Item("sword", "steel").damage_class(), "edge")
        self.assertEqual(Item("sword", "gold").damage_class(), "blunt")

    def test_make_and_loot(self):
        rng = RNG(6)
        it = make_item(rng, "sword", tier=3)
        self.assertEqual(it.def_id, "sword")
        from ascii_warriors.game.item import random_loot

        loot = random_loot(rng, 3)
        self.assertTrue(loot)

    def test_round_trip(self):
        it = Item("battle_axe", "steel", quality=4, wear=1, count=1)
        clone = Item.from_dict(json.loads(json.dumps(it.to_dict())))
        self.assertEqual(clone.name(), it.name())
        self.assertEqual(clone.id, it.id)


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.creature = make_creature(RNG(1), "dwarf", faction="player")
        self.inv = self.creature.inventory
        self.inv.items.clear()
        self.inv.equipped.clear()

    def test_equip_and_unequip(self):
        sword = self.inv.add(Item("sword", "iron"))
        ok, _msg = self.inv.equip(sword)
        self.assertTrue(ok)
        self.assertIs(self.inv.weapon(), sword)
        self.assertEqual(self.inv.slot_of(sword), "weapon")
        self.assertIs(self.inv.unequip("weapon"), sword)
        self.assertIsNone(self.inv.weapon())

    def test_armor_layers(self):
        mail = self.inv.add(Item("mail_shirt", "iron"))
        tunic = self.inv.add(Item("tunic", "pig_tail_cloth"))
        self.inv.equip(mail)
        self.inv.equip(tunic)
        covering = self.inv.armor_on("torso")
        self.assertIn(mail, covering)
        self.assertIn(tunic, covering)
        self.assertEqual(self.inv.armor_on("head"), [])

    def test_two_handed_needs_both_hands(self):
        maul = self.inv.add(Item("maul", "iron"))
        shield = self.inv.add(Item("shield", "oak"))
        self.inv.equip(shield, "offhand")
        ok, _msg = self.inv.equip(maul, "weapon")
        self.assertTrue(ok)
        self.assertIsNone(self.inv.offhand())

    def test_coins(self):
        self.inv.add(Item("coin", "silver", count=50))
        self.assertEqual(self.inv.coins(), 50)
        self.assertTrue(self.inv.spend_coins(20))
        self.assertEqual(self.inv.coins(), 30)
        self.assertFalse(self.inv.spend_coins(1000))

    def test_auto_equip(self):
        self.inv.add(Item("sword", "iron"))
        self.inv.add(Item("mail_shirt", "iron"))
        self.inv.add(Item("shield", "oak"))
        self.inv.auto_equip()
        self.assertIsNotNone(self.inv.weapon())
        self.assertIsNotNone(self.inv.shield())

    def test_round_trip(self):
        sword = self.inv.add(Item("sword", "iron"))
        self.inv.equip(sword)
        clone = Inventory.from_dict(json.loads(json.dumps(self.inv.to_dict())))
        self.assertEqual(len(clone.items), len(self.inv.items))
        self.assertIsNotNone(clone.weapon())


class TestCombat(unittest.TestCase):
    def _duel(self, a_id, b_id, seed, a_level=0, b_level=0, kit=None, max_rounds=400):
        rng = RNG(seed)
        log = MessageLog()
        a = make_creature(rng, a_id, faction="player", level=a_level)
        a.is_player = True
        if kit:
            for it in starting_kit(rng, a_id, kit):
                a.inventory.add(it)
            a.inventory.auto_equip()
        b = make_creature(rng, b_id, faction="hostile", level=b_level)
        rounds = 0
        while not a.body.dead and not b.body.dead and rounds < max_rounds:
            combat.melee_attack(a, b, rng=rng, log=log)
            if not b.body.dead:
                combat.melee_attack(b, a, rng=rng, log=log)
            a.body.tick(rng, 1, 1.0, 1.0)
            b.body.tick(rng, 1, 1.0, 1.0)
            rounds += 1
        return a, b, rounds, log

    def test_fights_terminate_with_a_winner(self):
        for seed in range(8):
            a, b, rounds, _log = self._duel("human", "goblin", "d%d" % seed,
                                            1, 1, "warrior")
            self.assertLess(rounds, 400)
            self.assertTrue(a.body.dead or b.body.dead)

    def test_armed_and_armoured_usually_beats_a_goblin(self):
        wins = 0
        for seed in range(20):
            a, b, _r, _l = self._duel("human", "goblin", "w%d" % seed, 2, 1,
                                      "warrior")
            if b.body.dead and not a.body.dead:
                wins += 1
        self.assertGreaterEqual(wins, 13)

    def test_dragons_are_lethal(self):
        deaths = 0
        for seed in range(6):
            a, _b, _r, _l = self._duel("human", "dragon", "dr%d" % seed, 3, 0,
                                       "warrior")
            if a.body.dead:
                deaths += 1
        self.assertGreaterEqual(deaths, 5)

    def test_bronze_colossus_shrugs_off_iron(self):
        _a, b, _r, _l = self._duel("dwarf", "bronze_colossus", "bc", 6, 0,
                                   "warrior", max_rounds=60)
        self.assertFalse(b.body.dead)

    def test_armour_blunts_attacks(self):
        rng = RNG(11)
        naked = make_creature(rng, "human")
        armoured = make_creature(rng, "human")
        armoured.inventory.add(Item("breastplate", "steel"))
        armoured.inventory.auto_equip()
        bare, _outer = combat.armor_protection(naked, "upper_body", "edge")
        plated, _outer2 = combat.armor_protection(armoured, "upper_body", "edge")
        self.assertGreater(plated, bare)

    def test_messages_are_produced(self):
        rng = RNG(12)
        a = make_creature(rng, "human", faction="player")
        a.is_player = True
        a.inventory.add(Item("sword", "steel"))
        a.inventory.auto_equip()
        b = make_creature(rng, "goblin", faction="hostile")
        seen = False
        for _ in range(40):
            result = combat.melee_attack(a, b, rng=rng)
            self.assertTrue(result.messages)
            if result.hit:
                seen = True
            if b.body.dead:
                break
        self.assertTrue(seen)

    def test_ranged_attack_consumes_ammo(self):
        rng = RNG(13)
        a = make_creature(rng, "elf", faction="player")
        a.is_player = True
        bow = a.inventory.add(Item("bow", "oak"))
        ammo = a.inventory.add(Item("arrow", "iron", count=5))
        a.inventory.equip(bow)
        b = make_creature(rng, "goblin", faction="hostile")
        b.x, b.y = 5, 0
        combat.ranged_attack(a, b, bow, ammo, rng=rng)
        self.assertEqual(ammo.count, 4)

    def test_wrestling_works(self):
        rng = RNG(14)
        a = make_creature(rng, "human", faction="player")
        b = make_creature(rng, "kobold", faction="hostile")
        result = combat.wrestle(a, b, "throw", rng=rng)
        self.assertTrue(result.messages)


class TestNeedsAndCrafting(unittest.TestCase):
    def test_needs_progress_and_warn(self):
        creature = make_creature(RNG(1), "human", faction="player")

        class FakeGame:
            pass

        needs = creature.needs
        msgs = needs.tick(20000, creature, FakeGame())
        self.assertTrue(any("hungry" in m for m in msgs))
        self.assertEqual(needs.hunger_word(), "hungry")
        needs.eat(Item("bread", "bread"))
        self.assertLess(needs.hunger, 20000)

    # -- how long a feeling lasts ------------------------------------------ #

    class _Nowhere:
        """Enough of a game for `Needs.tick` to run against."""

    def _game(self):
        return self._Nowhere()

    def test_stress_fades_at_the_rate_the_constant_says(self):
        """`STRESS_DECAY` is ticks per point, and it was ignored.

        The fade was `stress -= max(1, int(drift))`, and the floor of one was
        applied per *call*, not per tick. A fortress steps ten ticks at a
        time, so every dwarf shed a full point of stress every step: a
        hundred and forty-four thousand ticks' worth of fading per day
        against the nine hundred ticks a point the constant asks for, ninety
        times too fast. Nothing could stay upset long enough to do anything
        about it -- measured over two hundred days of a fortress that lost ten
        of its twelve dwarves, not one tantrum, not one brawl, and every
        survivor sitting at a stress of zero.
        """
        n = Needs()
        n.stress = 100
        game = self._game()
        creature = make_creature(RNG(1), "dwarf", faction="player")
        for _ in range(90):                       # ninety ten-tick steps
            n.tick(10, creature, game)
        self.assertEqual(n.stress, 99, "900 ticks should shed exactly one")
        for _ in range(90 * 9):
            n.tick(10, creature, game)
        self.assertEqual(n.stress, 90, "nine more points in nine more days")

    def test_a_fortress_step_does_not_shed_a_whole_point(self):
        """The defect, stated at the size the fortress actually steps."""
        n = Needs()
        n.stress = 50
        creature = make_creature(RNG(2), "dwarf", faction="player")
        n.tick(10, creature, self._game())
        self.assertEqual(n.stress, 50, "one ten-tick step shed a whole point")

    def test_sleeping_settles_at_the_rate_the_constant_says(self):
        """`SLEEP_SETTLES` was integer-divided into nothing.

        A fortress sleeps in forty-tick instalments and this was
        `ticks // 400`, so sleeping has never once settled anybody.
        """
        n = Needs()
        n.stress = 100
        for _ in range(10):                       # ten forty-tick instalments
            n.sleep(40)
        self.assertEqual(n.stress, 99, "400 ticks of sleep should settle one")
        for _ in range(10):
            n.sleep(40)
        self.assertEqual(n.stress, 98)

    def test_a_feeling_still_fades_to_nothing_eventually(self):
        """The fade is slower now, not gone: it has to reach zero."""
        n = Needs()
        n.stress = 20
        creature = make_creature(RNG(3), "dwarf", faction="player")
        for _ in range(40):
            n.tick(900, creature, self._game())
        self.assertEqual(n.stress, 0)

    def test_the_carry_survives_a_save(self):
        """A part-faded point is state, and a save that drops it is a save
        that quietly re-rounds every dwarf's mood."""
        n = Needs()
        n.stress = 10
        creature = make_creature(RNG(4), "dwarf", faction="player")
        n.tick(400, creature, self._game())         # part of a point
        n.sleep(100)                              # part of another
        self.assertGreater(n.drift, 0.0)
        self.assertGreater(n.rested, 0)
        clone = Needs.from_dict(json.loads(json.dumps(n.to_dict())))
        self.assertAlmostEqual(clone.drift, n.drift)
        self.assertEqual(clone.rested, n.rested)

    def test_needs_round_trip(self):
        n = Needs()
        n.hunger = 500
        n.add_thought("test", 5)
        clone = Needs.from_dict(json.loads(json.dumps(n.to_dict())))
        self.assertEqual(clone.hunger, 500)
        self.assertEqual(clone.stress, n.stress)

    def test_butchering_yields_food(self):
        rng = RNG(2)
        hunter = make_creature(rng, "human", faction="player")
        deer = make_creature(rng, "deer")
        corpse = hunter.inventory.add(corpse_of(deer))

        class FakeGame:
            def __init__(self):
                self.rng = RNG(3)
                self.local = None

        out = crafting.butcher_corpse(hunter, corpse, FakeGame())
        self.assertTrue(out)
        self.assertTrue(any(i.def_id == "meat" for i in out))
        self.assertEqual(hunter.inventory.by_def("corpse"), [])


class TestCreature(unittest.TestCase):
    def test_creation(self):
        c = make_creature(RNG(1), "dwarf", faction="player", level=2)
        self.assertTrue(c.name)
        self.assertTrue(c.full_title())
        self.assertTrue(c.describe())
        self.assertGreater(c.effective_speed(), 0)
        self.assertGreater(c.carry_capacity(), 0)
        self.assertGreater(c.sight_radius(1.0), 0)

    def test_hostility(self):
        rng = RNG(2)
        player = make_creature(rng, "human", faction="player")
        goblin = make_creature(rng, "goblin", faction="hostile")
        cow = make_creature(rng, "cow", faction="wild")
        self.assertTrue(player.is_hostile_to(goblin))
        self.assertTrue(goblin.is_hostile_to(player))
        self.assertFalse(player.is_hostile_to(cow))
        self.assertFalse(cow.is_hostile_to(player))

    def test_wounds_slow_you_down(self):
        c = make_creature(RNG(3), "human")
        fast = c.effective_speed()
        c.body.sever("left_leg_upper")
        c.body.sever("right_leg_upper")
        self.assertLess(c.effective_speed(), fast)

    def test_round_trip(self):
        rng = RNG(4)
        c = make_creature(rng, "dwarf", faction="player", level=2)
        for it in starting_kit(rng, "dwarf", "warrior"):
            c.inventory.add(it)
        c.inventory.auto_equip()
        clone = Creature.from_dict(json.loads(json.dumps(c.to_dict())))
        self.assertEqual(clone.name, c.name)
        self.assertEqual(clone.id, c.id)
        self.assertEqual(len(clone.inventory.items), len(c.inventory.items))
        self.assertEqual(clone.skills.level("axe"), c.skills.level("axe"))

    def test_unique_creature_round_trip(self):
        from ascii_warriors.data import creatures as creature_data

        rng = RNG(5)
        c = make_creature(rng, "forgotten_beast")
        c.unique_def = creature_data.random_forgotten_beast(rng, "Test Horror")
        clone = Creature.from_dict(json.loads(json.dumps(c.to_dict())))
        self.assertEqual(clone.defn.name, "Test Horror")


class TestMessageLog(unittest.TestCase):
    def test_collapse_and_limits(self):
        log = MessageLog(capacity=50)
        for _ in range(5):
            log.add("You slip on the ice.")
        self.assertEqual(len(log.messages), 1)
        self.assertIn("(x5)", log.messages[0].text)
        for i in range(200):
            log.add("message %d" % i)
        self.assertLessEqual(len(log.messages), 50)

    def test_round_trip(self):
        log = MessageLog()
        log.combat("You strike the goblin.")
        clone = MessageLog.from_dict(json.loads(json.dumps(log.to_dict())))
        self.assertEqual(clone.messages[0].text, log.messages[0].text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestWhatEverybodyIsCarrying(unittest.TestCase):
    """Everybody in the world had a weapon, maybe a coat, and nothing else.

    Measured before this class was written: 1440 people of 24 kinds carried
    24 distinct item ids between them out of 117, none of them food, water,
    clothing, light or rope -- while the player they met set out with all of
    it. `item.random_loot` declares seven categories of thing to carry and its
    one caller asked only ever for treasure, so six of them, about sixty item
    definitions, had never been drawn from by anything.
    """

    @staticmethod
    def _many(def_id, n=60, faction="town", seed=None):
        rng = RNG(seed or ("carry-" + def_id))
        return [make_creature(rng, def_id, faction=faction,
                              level=rng.randint(0, 4)) for _ in range(n)]

    # -- the archers -------------------------------------------------------- #

    def test_everybody_given_a_bow_draws_it_and_has_something_to_shoot(self):
        """0 of 248 did either. `best_weapon` skips ranged weapons on
        purpose, and both the arming code and `auto_equip` asked it whether
        there was a bow."""
        from ascii_warriors.data import items as item_data

        armed = 0
        for def_id in ("elf", "elf_archer", "kobold", "marksdwarf"):
            for c in self._many(def_id, n=40, faction="hostile"):
                ranged = [i for i in c.inventory.items if i.is_ranged]
                if not ranged:
                    continue
                armed += 1
                held = c.inventory.weapon()
                self.assertIsNotNone(held, "%s holds nothing" % def_id)
                self.assertTrue(held.is_ranged)
                ammo = c.inventory.ammo()
                self.assertIsNotNone(ammo, "%s has no ammunition" % def_id)
                self.assertEqual(ammo.def_id, item_data.ammo_for(held.defn))
        self.assertGreater(armed, 40)

    def test_an_elven_archer_carries_a_bow_and_a_marksdwarf_a_crossbow(self):
        for def_id, weapon, shot in (("elf_archer", "bow", "arrow"),
                                     ("marksdwarf", "crossbow", "bolt")):
            for c in self._many(def_id, n=12):
                self.assertEqual(c.inventory.weapon().def_id, weapon)
                self.assertEqual(c.inventory.ammo().def_id, shot)

    def test_one_place_says_what_a_ranged_weapon_eats(self):
        """`ammo_for` was written as the funnel and never called: three other
        places carried the same `!= "stone"` patch for a sling instead."""
        from ascii_warriors.data import items as item_data

        self.assertEqual(item_data.validate(), [])
        for wid in ("bow", "crossbow", "sling"):
            ammo = item_data.ammo_for(item_data.get(wid))
            self.assertIn(ammo, item_data.ITEMS)
            self.assertTrue(item_data.get(ammo).has("AMMO"))

    # -- what they fight with ----------------------------------------------- #

    def test_people_fight_with_what_the_table_says_they_trained_in(self):
        """An `elf_archer` has bow 7 and used to draw from a list keyed on
        its race, which handed it a spear two times in three."""
        from ascii_warriors.data import creatures as creature_data
        from ascii_warriors.game.entity import trained_weapons

        self.assertEqual(trained_weapons(creature_data.get("elf_archer")),
                         ["bow"])
        self.assertEqual(trained_weapons(creature_data.get("marksdwarf")),
                         ["crossbow"])
        for c in self._many("axedwarf", n=20):
            self.assertEqual(c.inventory.weapon().defn.weapon.skill, "axe")
        for c in self._many("hammerdwarf", n=20):
            self.assertEqual(c.inventory.weapon().defn.weapon.skill, "hammer")

    def test_nobody_carries_a_weapon_they_cannot_lift(self):
        """A gremlin is fifteen thousand and a battle axe wants twenty-seven
        and a half, so it carried one around and fought with its hands."""
        for def_id in ("gremlin", "kobold", "goblin", "dwarf", "giant"):
            for c in self._many(def_id, n=20, faction="hostile"):
                for it in c.inventory.items:
                    if not it.is_weapon or it.defn.weapon is None:
                        continue
                    self.assertGreaterEqual(
                        c.defn.size, it.defn.weapon.min_size,
                        "%s carries a %s it cannot hold" % (def_id, it.def_id))
                self.assertIsNotNone(c.inventory.weapon(),
                                     "%s stands there empty-handed" % def_id)

    def test_a_town_s_baker_is_not_issued_a_battle_axe(self):
        """`_fights` reads the table: a peasant has no fighting skill at all
        and used to draw a weapon off the same list as the guard."""
        heavy = 0
        for c in self._many("peasant", n=40) + self._many("merchant", n=40):
            held = c.inventory.weapon()
            if held is not None and held.defn.weapon is not None:
                self.assertEqual(held.defn.weapon.skill, "dagger")
                heavy += 1
        self.assertGreater(heavy, 10)

    # -- and what else is on them ------------------------------------------- #

    def test_everybody_civilised_is_wearing_something(self):
        for def_id in ("human", "dwarf", "elf", "goblin", "merchant",
                       "peasant", "guard", "necromancer", "vampire"):
            for c in self._many(def_id, n=10):
                worn = {i.def_id for i in c.inventory.items}
                self.assertTrue(
                    worn & {"tunic", "trousers", "shoes"},
                    "%s is standing there in nothing" % def_id)

    def test_and_nothing_in_the_table_is_cut_for_a_giant(self):
        """`CIVILIZED` is the line, the same one that decides who can have a
        name. A cyclops in shoes is a worse world than a cyclops without."""
        for def_id in ("giant", "cyclops", "ettin", "night_troll"):
            for c in self._many(def_id, n=10, faction="hostile"):
                worn = {i.def_id for i in c.inventory.items}
                self.assertFalse(worn & {"tunic", "trousers", "shoes"},
                                 "%s is wearing clothes" % def_id)

    def test_a_merchant_carries_goods_and_a_traveller_carries_water(self):
        goods = set()
        for c in self._many("merchant", n=40):
            goods.update(i.defn.category for i in c.inventory.items)
        self.assertTrue(goods & {"gem", "coin"},
                        "a merchant with nothing to sell")
        carried = set()
        for def_id in ("human", "guard", "merchant", "peasant", "bandit"):
            for c in self._many(def_id, n=40):
                carried.update(i.def_id for i in c.inventory.items)
        for wanted in ("waterskin", "torch", "rope", "bandage"):
            self.assertIn(wanted, carried, "nobody in the world has a %s"
                          % wanted)
        self.assertTrue(carried & {"meat", "bread", "cheese", "berries",
                                   "plump_helmet"}, "nobody carries food")
        self.assertTrue(carried & {"dwarven_ale", "wine", "rum", "beer",
                                   "mead"}, "nobody carries a drink")

    def test_asking_for_a_kind_of_loot_that_does_not_exist_is_an_error(self):
        from ascii_warriors.game.item import random_loot

        with self.assertRaises(KeyError):
            random_loot(RNG("nonsense"), 2, ("provisions",))

    def test_every_category_of_loot_is_drawn_by_somebody(self):
        """Six of the seven had one caller between them, asking for treasure."""
        from ascii_warriors.game.item import _LOOT_TABLE

        drawn = set()
        for def_id in ("merchant", "guard", "peasant", "bandit", "human"):
            for c in self._many(def_id, n=40):
                for it in c.inventory.items:
                    for kind, table in _LOOT_TABLE.items():
                        if it.def_id in table:
                            drawn.add(kind)
        self.assertEqual(sorted(drawn), sorted(_LOOT_TABLE))
