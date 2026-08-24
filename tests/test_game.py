"""Tests for the simulation: bodies, combat, items, world and save/load."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from ascii_warriors.engine.rng import RNG
from ascii_warriors.data import bodies, items as items_data, materials
from ascii_warriors.game import combat, crafting
from ascii_warriors.game.attributes import ALL_ATTRS, Attributes, roll_attributes
from ascii_warriors.game import body as body_mod
from ascii_warriors.game.body import Body
from ascii_warriors.game.entity import Creature, make_creature
from ascii_warriors.game.inventory import Inventory
from ascii_warriors.game import item as item_mod
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


class TestWhatCannotBeKilled(unittest.TestCase):
    """A quarter of the bestiary could not be killed at all.

    `Body._check_state` ends a life three ways: blood loss, suffocation, or a
    vital or thinking part destroyed. Ten of the eighty-one creatures in the
    table have no blood -- the four undead, three of the things that live in
    the caverns §117 filled, the demon, the bronze colossus and the forgotten
    beast -- so the first rule never fired for them, the faint that precedes
    it never fired either, and the third almost never happens.

    Measured before this class was written: a starting warrior beats a wolf
    forty times in forty in seven exchanges and loses to a zombie thirty-eight
    times in forty, having cut the skin, fat and muscle off its torso, neck,
    both arms and both legs -- sixty-six wounds across eighteen parts, nothing
    destroyed, and the model with nothing to say about any of it.
    """

    @staticmethod
    def _duel(beast, weapon="sword", material="iron", n=16, cap=200,
              hit_back=True):
        """Fight one creature *n* times and count how it goes."""
        import tempfile as _tf

        from ascii_warriors.game.item import make_item
        from ascii_warriors.game.state import Game
        from ascii_warriors.world.worldgen import generate_world

        old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = _tf.mkdtemp()
        try:
            world = generate_world(RNG("duelworld").sub("w"), size="pocket",
                                   history_years=5)
            won = 0
            for i in range(n):
                r = RNG("duel-%s-%s-%d" % (beast, weapon, i))
                game = Game.new_game(
                    world, {"race": "human", "profession": "warrior"}, r)
                p = game.player
                for it in list(p.inventory.items):
                    if it.is_weapon:
                        p.inventory.items.remove(it)
                w = make_item(r, weapon, material=material, tier=3)
                p.inventory.add(w)
                p.inventory.equip(w, "weapon")
                foe = make_creature(r, beast, faction="hostile")
                for _turn in range(cap):
                    if p.body.dead or foe.body.dead:
                        break
                    combat.melee_attack(p, foe, rng=r)
                    if hit_back and not foe.body.dead:
                        combat.melee_attack(foe, p, rng=r)
                    for c in (p, foe):
                        c.body.tick(r, 10, c.attributes.factor("toughness"),
                                    c.attributes.factor("recuperation"))
                if foe.body.dead:
                    won += 1
            return won
        finally:
            if old is None:
                os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
            else:
                os.environ["ASCII_WARRIORS_SAVE_DIR"] = old

    # -- the measure itself -------------------------------------------------- #

    def test_a_whole_body_is_all_there(self):
        c = make_creature(RNG("whole"), "human", equip=False)
        self.assertEqual(c.body.structure_fraction(), 1.0)

    def test_taking_a_body_apart_shows_in_the_measure(self):
        c = make_creature(RNG("apart"), "human", equip=False)
        before = c.body.structure_fraction()
        torso = c.body.parts["upper_body"]
        for tid in list(torso.tissues):
            torso.tissues[tid] = 0.0
        opened = c.body.structure_fraction()
        self.assertLess(opened, before)

    def test_an_arm_on_the_floor_is_not_part_of_you(self):
        c = make_creature(RNG("arm"), "human", equip=False)
        before = c.body.structure_fraction()
        c.body.sever("left_arm_upper")
        self.assertLess(c.body.structure_fraction(), before)

    def test_a_broken_bone_is_worth_less_than_a_whole_one(self):
        from ascii_warriors.game.body import BROKEN_WORTH

        self.assertLess(BROKEN_WORTH, 1.0)
        c = make_creature(RNG("break"), "human", equip=False)
        before = c.body.structure_fraction()
        c.body.parts["upper_body"].broken = True
        self.assertLess(c.body.structure_fraction(), before)

    # -- and what it does ---------------------------------------------------- #

    def test_a_bloodless_body_stops_when_it_is_taken_apart(self):
        from ascii_warriors.game.body import STRUCTURE_DEATH

        c = make_creature(RNG("zed"), "zombie", equip=False)
        self.assertTrue(c.body.bloodless)
        for part in c.body.parts.values():
            for tid in list(part.tissues):
                part.tissues[tid] = STRUCTURE_DEATH - 0.2
        c.body._check_state()
        self.assertTrue(c.body.dead)
        self.assertEqual(c.body.death_cause, "hacked apart")

    def test_a_living_body_is_not_judged_on_it(self):
        """A man with no muscle left is a man who has bled to death, and the
        blood rule is what should say so."""
        from ascii_warriors.game.body import STRUCTURE_DEATH

        c = make_creature(RNG("live"), "human", equip=False)
        self.assertFalse(c.body.bloodless)
        for part in c.body.parts.values():
            for tid in list(part.tissues):
                part.tissues[tid] = STRUCTURE_DEATH - 0.2
        c.body._check_state()
        self.assertFalse(c.body.dead)

    def test_a_warrior_can_kill_a_zombie(self):
        """2 of 40 before; the wolf in the same test wins 40 of 40."""
        self.assertGreaterEqual(self._duel("zombie"), 11)

    def test_and_still_beats_a_wolf_in_the_same_breath(self):
        """The rule is gated on having no blood, so nothing alive changed."""
        self.assertGreaterEqual(self._duel("wolf"), 14)

    def test_every_bloodless_thing_but_one_can_be_killed(self):
        """Unopposed, with a good axe. The exception is named on purpose: a
        bronze colossus takes zero wounds from two thousand blows of an
        adamantine axe, because its natural armour subtracts a flat 30,000
        kilopascals and nothing in the game swings that hard. That is a
        different axis -- weapon force against natural armour -- and it is
        left measured rather than half-fixed."""
        from ascii_warriors.data import creatures as creature_data

        bloodless = sorted(d.id for d in creature_data.CREATURES.values()
                           if not d.blood)
        self.assertIn("bronze_colossus", bloodless)
        self.assertGreaterEqual(len(bloodless), 8)
        for beast in ("zombie", "ghoul", "mummy", "forgotten_beast", "demon"):
            self.assertIn(beast, bloodless)
            self.assertGreaterEqual(
                self._duel(beast, weapon="battle_axe", material="steel",
                           n=6, cap=400, hit_back=False), 5,
                "%s cannot be killed even unopposed" % beast)

    # -- and a skeleton is bones ---------------------------------------------- #

    def test_a_skeleton_has_no_flesh_on_it(self):
        """Saying so with the material map -- skin made of bone, fat made of
        bone -- gave it four layers of the toughest tissue in the game."""
        c = make_creature(RNG("bones"), "skeleton", equip=False)
        torso = c.body.parts["upper_body"]
        self.assertEqual(sorted(torso.tissues), ["bone"])
        for tid in ("skin", "fat", "muscle"):
            self.assertIn(tid, c.body.missing)

    def test_what_a_body_is_missing_survives_a_save(self):
        from ascii_warriors.game.body import Body

        c = make_creature(RNG("bonesave"), "skeleton", equip=False)
        back = Body.from_dict(json.loads(json.dumps(c.body.to_dict())))
        self.assertEqual(back.missing, c.body.missing)
        self.assertEqual(sorted(back.parts["upper_body"].tissues), ["bone"])

    def test_a_skeleton_comes_apart_under_an_axe(self):
        """It is one layer of solid bone, so what it takes is a weapon that
        chops: swords and hammers still glance off it."""
        self.assertGreaterEqual(
            self._duel("skeleton", weapon="battle_axe", material="steel",
                       n=12, cap=300), 7)


class TestTheMetalInYourSword(unittest.TestCase):
    """A weapon's material reached the calculation through its mass.

    The README calls this "real material science", and every material in the
    table carries shear and impact yields in kilopascals -- and a weapon's own
    material was used for exactly one thing: `effective_kind` asked whether it
    could hold an edge at all. Its yield never entered the sum. What decided a
    blow was momentum, and momentum is mostly mass.

    So a copper sword killed a goblin faster than a steel one, because copper
    is denser; and adamantine -- which shears at five million against steel's
    four hundred and thirty thousand, and is the point of the deepest mine in
    the game -- was the *worst* weapon material there is, taking twice as many
    blows as anything else, because it weighs a fortieth of what steel does.
    """

    #: The swordsman these measurements are taken with.
    #:
    #: Held fixed on purpose. Every number in this class is a claim about a
    #: *metal*, and until v3.88 the character swinging it happened to have
    #: `sword 0` -- `new_game` was given a profession and ignored it. When
    #: that was fixed the same tests measured a different swordsman, iron went
    #: from 400 blows to 81 and the ratio to steel fell from 10.8 to 2.7. The
    #: ordering never moved; the threshold did. Pinning the skill keeps these
    #: about the blade.
    BLOWS_SKILL = 4

    @staticmethod
    def _blows(weapon, material, beast, n=9, cap=400, armour_mat=""):
        """Median blows to put something down, unopposed."""
        import tempfile as _tf

        from ascii_warriors.game.state import Game
        from ascii_warriors.world.worldgen import generate_world

        old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = _tf.mkdtemp()
        try:
            world = generate_world(RNG("metalworld").sub("w"), size="pocket",
                                   history_years=5)
            hits = []
            for i in range(n):
                r = RNG("metal-%s-%s-%s-%d" % (weapon, material, beast, i))
                game = Game.new_game(
                    world, {"race": "human", "profession": "warrior"}, r)
                p = game.player
                for it in list(p.inventory.items):
                    if it.is_weapon:
                        p.inventory.items.remove(it)
                w = Item(weapon, material, quality=2)
                p.inventory.add(w)
                p.inventory.equip(w, "weapon")
                for sid in ("sword", "axe", "hammer", "spear", "dagger",
                            "fighter"):
                    p.skills.set_level(sid, TestTheMetalInYourSword.BLOWS_SKILL)
                foe = make_creature(r, beast, faction="hostile", equip=False)
                if armour_mat:
                    for piece in ("breastplate", "helm", "greaves"):
                        foe.inventory.add(Item(piece, armour_mat, quality=2))
                    foe.inventory.auto_equip()
                t = 0
                while t < cap and not foe.body.dead:
                    combat.melee_attack(p, foe, rng=r)
                    foe.body.tick(r, 10, 1.0, 1.0)
                    t += 1
                hits.append(t)
            hits.sort()
            return hits[len(hits) // 2]
        finally:
            if old is None:
                os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
            else:
                os.environ["ASCII_WARRIORS_SAVE_DIR"] = old

    # -- the measure --------------------------------------------------------- #

    def test_iron_is_the_anchor_and_the_rest_is_read_off_the_table(self):
        from ascii_warriors.data import materials as mat_data
        from ascii_warriors.game.body import (
            KEEN_CEILING, KEEN_FLOOR, keenness,
        )

        self.assertEqual(keenness(mat_data.get("iron"), True), 1.0)
        self.assertEqual(keenness(None, True), 1.0)
        order = ["copper", "bronze", "iron", "steel", "adamantine"]
        keen = [keenness(mat_data.get(m), True) for m in order]
        self.assertEqual(keen, sorted(keen), "the table is not in order")
        self.assertLess(keen[0], 1.0, "copper is not softer than iron")
        self.assertGreater(keen[3], 1.0, "steel is no better than iron")
        # Under the ceiling, which is the point of where the ceiling is: at
        # 3.0 the hardest thing in the game came out worse than steel.
        self.assertGreater(keen[4], 5.0, "adamantine is barely better")
        self.assertLessEqual(keen[4], KEEN_CEILING)
        self.assertGreaterEqual(keenness(mat_data.get("obsidian"), True),
                                KEEN_FLOOR)

    # -- and what it does ----------------------------------------------------- #

    def test_the_metal_decides_whether_you_can_cut_bone(self):
        """A skeleton is one layer of solid bone. Iron barely marks it.

        The ratio, not the cap. This asserted `iron == 300` -- the number the
        loop gives up at -- which is a saturating proxy: it says "iron never
        got there in three hundred blows" and stops meaning anything the
        moment iron gets there in two hundred and ninety-nine.

        Measured over twenty-five samples at `BLOWS_SKILL`, cap 400: copper
        400, iron 81, steel 30, adamantine 17. With the `sword 0` swordsman
        this class used to get by accident it was copper 400, iron 400, steel
        37, adamantine 22 -- the same ordering, a wider gap. Two and a half
        times, not three, because skill closes on the metal a little.
        """
        iron = self._blows("sword", "iron", "skeleton", cap=300)
        steel = self._blows("sword", "steel", "skeleton", cap=300)
        adam = self._blows("sword", "adamantine", "skeleton", cap=300)
        self.assertGreater(iron, steel * 2,
                           "an iron sword cuts bone nearly as well as steel")
        self.assertLess(steel, 100, "a steel sword still cannot cut bone")
        self.assertLess(adam, steel, "adamantine is no better than steel")

    def test_armour_asks_what_hit_it(self):
        """Plate stopped a copper knife and an adamantine one identically."""
        from ascii_warriors.data import materials as mat_data

        foe = make_creature(RNG("plated"), "human", equip=False)
        for piece in ("breastplate", "helm"):
            foe.inventory.add(Item(piece, "steel", quality=2))
        foe.inventory.auto_equip()
        soft, _o = combat.armor_protection(
            foe, "upper_body", "edge", edge=mat_data.get("copper"))
        plain, _o = combat.armor_protection(
            foe, "upper_body", "edge", edge=mat_data.get("iron"))
        keen, _o = combat.armor_protection(
            foe, "upper_body", "edge", edge=mat_data.get("adamantine"))
        self.assertGreater(soft, plain, "copper defeats as much as iron")
        self.assertLess(keen, plain, "adamantine defeats no more than iron")
        self.assertLess(keen * 3, plain, "the metal barely counts")

    def test_the_colossus_falls_to_the_one_thing_that_should_fell_it(self):
        """§125.4 left it taking zero wounds from two thousand blows."""
        steel = self._blows("sword", "steel", "bronze_colossus", n=5, cap=400)
        adam = self._blows("sword", "adamantine", "bronze_colossus",
                           n=5, cap=400)
        self.assertEqual(steel, 400, "steel now fells a bronze colossus")
        self.assertLess(adam, 400, "adamantine still cannot scratch it")

    def test_the_metal_buys_nothing_against_flesh(self):
        """The gate on hardness is what keeps this from being a rebalance:
        with it off, a steel sword kills a goblin in three blows against
        iron's seven, purely for being steel."""
        iron = self._blows("sword", "iron", "goblin", n=13)
        steel = self._blows("sword", "steel", "goblin", n=13)
        self.assertGreaterEqual(
            steel * 1.5, iron,
            "steel is %d blows against iron's %d: the metal is deciding a "
            "fight it has no business in" % (steel, iron))

    def test_a_wolf_is_not_charged_for_having_bone_teeth(self):
        """`attack_material` answers "bone" for a natural attack so
        `effective_kind` can ask whether it holds an edge. Handing that to
        the armour made every claw and bite in the world face a plate 1.6
        times thicker than it used to."""
        from ascii_warriors.data import materials as mat_data

        def coat(seed):
            c = make_creature(RNG(seed), "human", equip=False)
            c.inventory.add(Item("leather_armor", "leather", quality=2))
            c.inventory.auto_equip()
            return c

        bare, _o = combat.armor_protection(coat("a"), "upper_body", "blunt",
                                           edge=None)
        as_bone, _o = combat.armor_protection(coat("a"), "upper_body", "blunt",
                                              edge=mat_data.get("bone"))
        self.assertGreater(as_bone, bare, "bone is not softer than iron")

        # And what a bite actually meets is the first of those.
        wolf = make_creature(RNG("wolf2"), "wolf", faction="hostile")
        attack = max((n.attack for n in wolf.defn.attacks),
                     key=lambda a: a.penetration)
        momentum = combat.compute_momentum(wolf, None, attack)
        kind = combat.effective_kind(None, attack)
        for i in range(40):
            foe = coat("b%d" % i)
            expected, _o = combat.armor_protection(
                foe, "upper_body", kind, attack.contact, momentum, edge=None)
            result = combat.melee_attack(
                wolf, foe, attack_def=attack, target_part="upper_body",
                rng=RNG("bite%d" % i))
            if not result.hit:
                continue
            self.assertAlmostEqual(max(0.0, momentum - expected),
                                   result.damage, places=3)
            return
        self.fail("the wolf never landed a bite in forty tries")

    def test_an_ordinary_fight_did_not_move(self):
        """Everything in the world carries iron, which is the anchor: a wolf
        has to cost what a wolf cost."""
        self.assertLessEqual(self._blows("sword", "iron", "wolf"), 8)
        self.assertLessEqual(self._blows("sword", "iron", "goblin"), 8)


class TestTheHammerThatCouldNotBreakABone(unittest.TestCase):
    """Hard tissue crushed harder than it sheared, and only hard tissue.

    Everything soft gives to a blow sooner than to an edge -- skin shears at
    20,000 and crushes at 10,000, fat at 15,000 and 10,000, muscle at 30,000
    and 20,000. Bone was written the other way round: shear 115,000, **impact
    200,000**, nearly twice as hard to crush as to cut, and the whole bone
    family followed it.

    A skeleton is the only creature in the game made of hard tissue alone --
    twenty-two of its forty parts are bone and nothing else -- so it was where
    the inversion had nowhere to hide, and it turned the weapon triangle
    upside down:

        battle axe     72 blows to kill      warhammer    >1500, still up
        sword         115 blows              mace         >1500, still up
        spear         209 blows

    A warhammer landed **262 of 400 blows and left no wound at all**, while
    the same hammer put 147 bruises on a goblin.
    """

    class _Ground:
        def drop_item(self, item, x, y, z):
            pass

    def _blows_to_kill(self, weapon, foe_id, cap=600):
        """How many swings of *weapon* it takes to put *foe_id* down."""
        rng = RNG("blows-%s-%s" % (weapon, foe_id))
        hero = make_creature(rng, "human", faction="player", level=1)
        held = make_item(rng, weapon, material="iron")
        hero.inventory.add(held)
        hero.inventory.equip(held)
        foe = make_creature(rng, foe_id, faction="hostile", level=1)
        ground = self._Ground()
        for i in range(cap):
            combat.timed_strike(hero, foe, rng=rng, log=None, ground=ground)
            foe.body.tick(rng, 10, 1.0, 1.0)
            if foe.body.dead:
                return i + 1
        return None

    def test_no_tissue_crushes_harder_than_it_shears(self):
        """The rule, over the whole table.

        Stated once here rather than trusted six times in the data. `nail` and
        `scale` carried the same inversion and no creature is made of either
        alone, so nothing had exposed them -- but scale is a layer a blow has
        to get through, and it was stopping a hammer better than a sword.
        """
        wrong = []
        for tissue_id, tissue in sorted(bodies.TISSUES.items()):
            mat = materials.get(tissue.material)
            if mat.impact_yield > mat.shear_yield:
                wrong.append("%s (%s): crushes at %d, shears at %d"
                             % (tissue_id, tissue.material,
                                mat.impact_yield, mat.shear_yield))
        self.assertEqual(wrong, [], "; ".join(wrong))

    def test_a_hammer_can_break_a_skeleton(self):
        blows = self._blows_to_kill("warhammer", "skeleton")
        self.assertIsNotNone(
            blows, "six hundred hammer blows and the skeleton is still up")

    def test_the_weapon_triangle_is_not_upside_down(self):
        """Blunt must not be the worst thing to bring to a pile of bones.

        Not "blunt must win" -- an axe hacking a skeleton apart is a fine
        answer too. Only that the one class of weapon made for shattering
        bone is not beaten by the one made for cutting flesh.
        """
        hammer = self._blows_to_kill("warhammer", "skeleton")
        sword = self._blows_to_kill("sword", "skeleton")
        self.assertIsNotNone(hammer, "the hammer never killed it")
        if sword is None:
            # A sword that cannot cut a skeleton at all is the triangle the
            # right way up, not a case to skip past. Said out loud, because a
            # bare `return` here would let the hammer regress unnoticed the
            # moment the sword stopped working.
            return
        self.assertLessEqual(
            hammer, sword * 2,
            "a warhammer needs %d blows on a skeleton and a sword %d"
            % (hammer, sword))

    def test_flesh_and_blood_costs_what_it_cost(self):
        """S126 anchored these and the shear numbers are untouched.

        Blows spend themselves on skin, fat and muscle long before they reach
        bone, so a change to how bone crushes should not reach a wolf at all.
        Measured over the change: a wolf still dies in a median of 5 rounds
        and a goblin in 6, at the same win rates.
        """
        # Twice what each actually costs, measured: 8 blows for a wolf, 4 for
        # a goblin, 4 for a kobold. Loose enough that ordinary drift will not
        # trip it, tight enough to notice a real change -- the first version
        # allowed forty and did not blink at flesh made ten times tougher.
        for foe_id, ceiling in (("wolf", 16), ("goblin", 10), ("kobold", 10)):
            blows = self._blows_to_kill("sword", foe_id)
            self.assertIsNotNone(blows, "a sword no longer kills a %s" % foe_id)
            self.assertLessEqual(
                blows, ceiling,
                "a %s now takes %d sword blows" % (foe_id, blows))


class TestSomethingToBindItWith(unittest.TestCase):
    """Bleeding, clotting, and the one recipe that answers them.

    Eight adventurers played by `tools/play`, eight deaths, and every one of
    them bled out. Seven counted "bleeding, and nothing to bind it with"
    sixteen, nineteen, fifty-two times after the third and last bandage in the
    kit was spent.
    """

    def _cut(self, points, *, bloodless=False):
        """A body with one wound of *points* and nothing else wrong.

        With *bloodless* it cannot die of the wound, which is the only way to
        watch a bad one close: twenty points empties a human in forty-nine
        ticks and a corpse stops clotting.
        """
        b = Body("humanoid", 70000)
        b.bloodless = bloodless
        part = b.part("upper_body")
        part.wounds.append(body_mod.Wound(part.id, "skin", 0.5, "cut",
                                          points, 5))
        return b

    def test_clotting_does_not_care_how_the_clock_is_sliced(self):
        """The same wound, the same hour, however the hour arrives.

        It was `rng.chance(0.0018 * ticks)` per call to `Body.tick`, clamped
        at 0.9 -- so one long call could only ever close one point, and the
        same twenty-point wound over the same four thousand ticks came out at
        13.2 points open when time arrived one tick at a time and 19.1 when it
        arrived in one lump. Sleeping through the night healed less than
        walking through it.
        """
        rng = RNG("slices")
        left = []
        for slice_ticks in (1, 10, 200, 4000):
            b = self._cut(20, bloodless=True)
            done = 0
            while done < 4000:
                b.tick(rng, slice_ticks, 1.0, 1.0)
                done += slice_ticks
            left.append(sum(w.bleeding for p in b.parts.values()
                            for w in p.wounds))
        self.assertEqual(len(set(left)), 1,
                         "same wound, same hour, different answers: %s" % left)

    def test_a_scratch_closes_and_a_maiming_does_not(self):
        """The two ends of the model have to say different things.

        Otherwise there is no reason for a bandage to exist -- or no way to
        survive a fight without one. Ten minutes of game time, in ticks rather
        than in multiples of `CLOT_TICKS`: a test that measures itself against
        the constant it is guarding cannot fail when the constant moves.
        """
        rng = RNG("ends")
        ten_minutes = 100
        small = self._cut(3, bloodless=True)
        small.tick(rng, ten_minutes, 1.0, 1.0)
        self.assertEqual(small.bleeding_rate(), 0.0,
                         "a three-point cut was still open ten minutes later")
        big = self._cut(28, bloodless=True)
        big.tick(rng, ten_minutes, 1.0, 1.0)
        self.assertGreater(big.bleeding_rate(), 0.0,
                           "a torn-open thigh closed itself in ten minutes")

    def test_bleeding_has_a_ceiling(self):
        """No number of holes empties you faster than a heart can pump.

        A troll fight left an adventurer carrying two hundred and sixty-three
        points of bleeding, which is 1.05 litres a tick out of a body that
        holds 4.9 and dies at 0.98. It was dead in the next six seconds of
        game time.
        """
        b = self._cut(300)
        cap = b.max_blood * body_mod.BLEED_CAP
        self.assertLessEqual(b.bleeding_rate(), cap + 1e-9)
        # And the cap is not so low that one bad wound is free.
        one = self._cut(20)
        self.assertAlmostEqual(one.bleeding_rate(),
                               20 * body_mod.BLEED_PER_POINT)
        self.assertGreater(b.bleeding_rate(), one.bleeding_rate())

    def test_a_capped_body_still_bleeds_to_death(self):
        """A ceiling is not a reprieve. Four minutes, from whole to dead."""
        rng = RNG("cap")
        b = self._cut(300)
        for _ in range(60):
            b.tick(rng, 1, 1.0, 1.0)
            if b.blood_fraction() <= body_mod.BLOOD_DEATH:
                break
        self.assertLessEqual(b.blood_fraction(), body_mod.BLOOD_DEATH,
                             "three hundred points of bleeding is survivable")

    def test_the_help_does_not_promise_what_the_recipe_refuses(self):
        """`make_bandage` said "Any garment will do". It takes cloth ones.

        Garment materials are rolled. Over four hundred warrior kits 19% of
        the clothes come out leather, and **58% of adventurers set out with at
        least one garment the help told them they could tear and the recipe
        would not take**. Bleeding is what kills adventurers -- 75% of
        twenty-four measured lives -- and they spent 10.9 turns of each fatal
        life with nothing left to bind with.

        The rule is deliberate: `test_a_recipe_still_means_what_it_says` has
        pinned "it tore strips off a leather tunic" as a failure since the
        recipe was written, and leather does not tear into dressings. So the
        words were wrong, not the rule. This ties the two together: refuse
        leather and say so, or accept it, but not one and the other.
        """
        recipe = crafting.RECIPES["make_bandage"]
        rng = RNG("promise")
        leather = make_item(rng, "cloak", material="leather")
        self.assertEqual(leather.category, "clothing")
        takes_leather = crafting._satisfies(leather, recipe.inputs[0][0])
        said = recipe.description.lower()
        if takes_leather:
            self.assertNotIn(
                "leather does not", said,
                "the recipe takes leather and the help says it does not")
        else:
            self.assertIn(
                "cloth", said,
                "the recipe takes only cloth and the help does not say so")
            self.assertIn(
                "leather", said,
                "the recipe refuses leather garments and never mentions it, "
                "so a bleeding adventurer wearing one is told to tear it up")

    def test_armour_is_not_a_garment(self):
        """A breastplate is not a shirt off your back, whatever it is made of.

        The class names a *category* as well as a material, and armour is
        `armor` rather than `clothing`. Loosen the material without noticing
        that and "tear a bandage" quietly becomes "shred your armour", and
        the first anybody knows is a soldier fighting naked.
        """
        rng = RNG("armour")
        need = crafting.RECIPES["make_bandage"].inputs[0][0]
        for def_id in ("leather_armor", "mail_shirt", "helm", "high_boots"):
            for material in ("leather", "wool_cloth"):
                piece = make_item(rng, def_id, material=material)
                self.assertFalse(
                    crafting._satisfies(piece, need),
                    "a %s %s can be torn up for bandages"
                    % (material, def_id))

    def test_every_recipe_input_names_something_that_exists(self):
        """An input naming nothing is a recipe nobody can ever make.

        `_satisfies` answers False for a class it has never heard of, so a
        typo, or a class removed from `CLASSES` while a recipe still asks for
        it, is a silent failure -- the recipe simply never appears and nothing
        says why. `CLOTH` was removed from `CLASSES` in this milestone, which
        is exactly the move that would cause it.
        """
        for rid, recipe in sorted(crafting.RECIPES.items()):
            for need, _count in recipe.inputs:
                self.assertTrue(
                    need in items_data.ITEMS or need in crafting.CLASSES,
                    "recipe %r wants %r, which is neither an item nor a class"
                    % (rid, need))
            self.assertIn(recipe.output, items_data.ITEMS,
                          "recipe %r makes %r, which is not an item"
                          % (rid, recipe.output))

    def test_no_class_is_declared_and_unused(self):
        """The other direction, and the reason `CLOTH` is gone."""
        asked = {need for recipe in crafting.RECIPES.values()
                 for need, _count in recipe.inputs}
        unused = sorted(k for k in crafting.CLASSES if k not in asked)
        self.assertEqual(unused, [],
                         "%s declared in CLASSES and named by no recipe"
                         % unused)

    def test_the_person_bleeding_can_make_a_bandage(self):
        """`make_bandage` asked for a cloak and nobody had one.

        The starting kit is armour: a mail shirt, a helm and boots, over
        nothing at all, while `_dress` puts a tunic, trousers and shoes on
        every other creature in the world. So the one recipe in the game that
        answers the thing that kills adventurers could not be made by the
        adventurer.
        """
        rng = RNG("tear")
        kit = starting_kit(rng, "human", "warrior")
        cloth = [i for i in kit if i.category == "clothing"]
        self.assertTrue(cloth, "the adventurer owns no clothes")
        c = make_creature(rng, "human", faction="player", level=1)
        for it in list(c.inventory.items):
            c.inventory.items.remove(it)
        c.inventory.add(make_item(rng, "tunic"))
        recipe = crafting.RECIPES["make_bandage"]
        self.assertIn(recipe, crafting.available(c, _NoWorld()))
        made, why = crafting.craft(c, recipe, _NoWorld())
        self.assertTrue(made, why)
        self.assertGreaterEqual(c.inventory.count_of("bandage"),
                                recipe.out_count)
        self.assertEqual(c.inventory.count_of("tunic"), 0)

    def test_a_recipe_still_means_what_it_says(self):
        """A class input is not a licence to eat the whole pack.

        Cloth, and clothing: a mail shirt is armour and a leather jerkin is
        not cloth, and neither of them is a bandage however badly you need
        one.
        """
        rng = RNG("strict")
        recipe = crafting.RECIPES["make_bandage"]
        c = make_creature(rng, "human", faction="player", level=1)
        for it in list(c.inventory.items):
            c.inventory.items.remove(it)
        c.inventory.add(make_item(rng, "mail_shirt"))
        # A cloth rope, which is cloth and is not clothing: you want it for
        # the climb down and it is not a dressing.
        c.inventory.add(make_item(rng, "rope", material="pig_tail_cloth"))
        self.assertNotIn(recipe, crafting.available(c, _NoWorld()))
        made, _why = crafting.craft(c, recipe, _NoWorld())
        self.assertFalse(made, "it tore up the mail shirt or the rope")
        leather = make_item(rng, "tunic", material="leather")
        self.assertEqual(leather.category, "clothing")
        c.inventory.add(leather)
        self.assertNotIn(recipe, crafting.available(c, _NoWorld()))
        made, _why = crafting.craft(c, recipe, _NoWorld())
        self.assertFalse(made, "it tore strips off a leather tunic")


class _NoWorld:
    """Enough of a game for a recipe that needs no fire and no workshop."""

    local = None
    rng = RNG("craft")

    def current_site(self):
        return None


class TestWhoIsFighting(unittest.TestCase):
    """The log names the people in it.

    Found by playing: a hundred-day fortress run on two different seeds was
    wiped by a siege between day fifty-six and day eighty-four. The record of
    the thing that ended the fortress was fifty-seven lines long, and fifty of
    them said "the dwarf" or "the goblin". Three used a name, and two of those
    three were the death notices.

    Worldgen has named every intelligent creature it makes since there was a
    worldgen -- the seven who embark, and "Uzzgul Skullsplitter" and "Durzug
    the Black" who come for them -- and the sidebar has listed those names all
    along. The fight was the one place that would not say them.
    """

    def _pair(self, seed="who"):
        """An armed dwarf and a goblin, both named, neither the player."""
        rng = RNG(seed)
        a = make_creature(rng, "dwarf", faction="fortress", level=1)
        b = make_creature(rng, "goblin", faction="hostile", level=1)
        return rng, a, b

    def _lines(self, log):
        from ascii_warriors.engine.screen import frag_str

        return [frag_str(m.display()) for m in log.all()]

    # -- the rule ---------------------------------------------------------- #

    def test_the_game_knows_their_names(self):
        """The premise. Without this the rest is about nothing."""
        _rng, a, b = self._pair()
        for c in (a, b):
            self.assertTrue(c.defn.intelligent)
            self.assertTrue(c.name, "worldgen made an unnamed person")
            self.assertTrue(c.known_by_name())
            self.assertEqual(c.subject_name(), c.name)
            self.assertEqual(c.object_name(), c.name)

    def test_an_animal_is_still_an_animal(self):
        """A dog has a name in the save file and is a dog on the screen."""
        rng = RNG("beasts")
        for def_id in ("wolf", "dog", "rabbit"):
            beast = make_creature(rng, def_id, faction="wild")
            self.assertTrue(beast.name, "even animals are named internally")
            self.assertFalse(beast.known_by_name())
            self.assertEqual(beast.subject_name(), "The %s" % beast.short_name())
            self.assertEqual(beast.object_name(), "the %s" % beast.short_name())

    def test_the_article_is_not_lost(self):
        """"Goblin slips." was a real message.

        Five places built a subject by capitalising the species and forgetting
        the article. The funnel is the fix and this is the reason it has to be
        one: every one of them was written separately.
        """
        rng = RNG("article")
        beast = make_creature(rng, "wolf", faction="wild")
        self.assertTrue(beast.subject_name().startswith("The "))
        self.assertEqual(beast.subject_name()[0], "T")

    def test_the_player_is_you(self):
        _rng, a, b = self._pair()
        a.is_player = True
        self.assertEqual(a.subject_name(), "You")
        self.assertEqual(a.object_name(), "you")
        self.assertEqual(a.pronoun(), "you")
        self.assertNotEqual(b.subject_name(), "You")

    def test_a_title_stays_out_of_the_fight(self):
        """It belongs in the unit list, not on every blow."""
        _rng, _a, b = self._pair()
        b.title = "the Pitiless"
        self.assertIn("the Pitiless", b.display_name())
        self.assertNotIn("Pitiless", b.subject_name())
        self.assertNotIn("Pitiless", b.object_name())

    def test_capitalize_would_have_mangled_it(self):
        """Why `subject_name` capitalises and callers must not.

        `"Uzzgul Skullsplitter".capitalize()` is "Uzzgul skullsplitter", and
        five call sites were doing exactly that to the species name.
        """
        _rng, _a, b = self._pair()
        if " " in b.name:
            self.assertNotEqual(b.name.capitalize(), b.name)
        self.assertEqual(b.subject_name(), b.name)

    # -- the fight --------------------------------------------------------- #

    def test_a_blow_says_who_struck_and_who_was_struck(self):
        rng, a, b = self._pair()
        log = MessageLog()
        for _ in range(60):
            combat.melee_attack(a, b, rng=rng, log=log)
            if b.body.dead:
                break
        text = " ".join(self._lines(log))
        self.assertTrue(text.strip(), "the fight logged nothing")
        self.assertIn(a.name, text, "the attacker is not named")
        self.assertIn(b.name, text, "the defender is not named")
        self.assertNotIn("The dwarf", text)
        self.assertNotIn("the goblin", text)

    def test_a_wolf_is_still_the_wolf(self):
        """The other half: naming people did not name the wildlife."""
        rng = RNG("wolfhunt")
        wolf = make_creature(rng, "wolf", faction="wild")
        deer = make_creature(rng, "deer", faction="wild")
        log = MessageLog()
        for _ in range(40):
            combat.melee_attack(wolf, deer, rng=rng, log=log)
            if deer.body.dead:
                break
        text = " ".join(self._lines(log))
        self.assertIn("wolf", text)
        self.assertNotIn(wolf.name, text, "the wolf was introduced by name")
        self.assertTrue("The wolf" in text or "the wolf" in text,
                        "the wolf lost its article: %r" % text[:120])

    def test_nobody_is_named_twice_in_one_sentence(self):
        """The dodge line, which is the only one that mentions them twice.

        "Thugdush Skullsplitter bashes at Nomal Anvilhammer, but Nomal
        Anvilhammer dodges" is a sentence nobody wrote on purpose. `female`
        has been rolled for every creature since they could be made and no
        line of text had ever asked.
        """
        rng, a, b = self._pair("dodging")
        log = MessageLog()
        dodges = []
        for _ in range(200):
            combat.melee_attack(a, b, rng=rng, log=log)
            if b.body.dead:
                b.body.blood = b.body.max_blood
                b.body.dead = False
                for p in b.body.parts.values():
                    p.wounds = []
        for line in self._lines(log):
            if "dodges" in line:
                dodges.append(line)
        self.assertTrue(dodges, "nobody dodged in two hundred blows")
        for line in dodges:
            self.assertEqual(line.count(b.name), 1, line)
            self.assertIn(b.pronoun(), line.split(", but ")[-1], line)

    def test_the_pronoun_matches_the_creature(self):
        rng, a, _b = self._pair("pronouns")
        a.female = True
        self.assertEqual(a.pronoun(), "she")
        a.female = False
        self.assertEqual(a.pronoun(), "he")
        beast = make_creature(rng, "wolf", faction="wild")
        self.assertEqual(beast.pronoun(), "it")



class TestTheWoundThatStoppedHurting(unittest.TestCase):
    """Pain that drained faster than the clock ran.

    `Body.tick` shed wound pain at `max(1, int(ticks * 0.02))`. That is a rate
    per *call*, not per unit of game time: at one tick `int(0.02)` is zero, the
    floor of one fires, and the wound sheds fifty times the pain the number
    names. Adventure mode hands out about one tick a turn and the fortress
    steps ten, so the same wound on the same body stopped hurting an adventurer
    almost at once and went on hurting a dwarf.

    §129 found this exact shape in clotting -- "the same wound over the same
    four thousand ticks came out at 13.2 points still open if time arrived one
    tick at a time and 19.1 if it arrived in one lump" -- and banked the time
    to fix it. Pain was the other half of the same loop and was not swept.
    """

    TOTAL = 100
    PAIN = 25
    WOUNDS = 4

    def _hurt(self, seed="pain"):
        c = make_creature(RNG(seed), "human")
        part = c.body.parts["left_leg_upper"]
        for _ in range(self.WOUNDS):
            part.wounds.append(body_mod.Wound(
                part="left_leg_upper", tissue="muscle", severity=9,
                kind="cut", bleeding=0, pain=self.PAIN))
        c.body.pain = self.PAIN * self.WOUNDS
        return c

    def _run(self, creature, total, step):
        rng = RNG("t")
        left = total
        while left > 0:
            n = min(step, left)
            creature.body.tick(rng, n, 1.0, 1.0)
            left -= n
        return sum(w.pain for p in creature.body.parts.values()
                   for w in p.wounds)

    def test_the_same_time_wears_off_the_same_pain(self):
        """However the hundred ticks arrive."""
        got = {}
        for step in (1, 10, 50, 100):
            got[step] = self._run(self._hurt(), self.TOTAL, step)
        self.assertEqual(len(set(got.values())), 1,
                         "the clock still depends on how it is read: %s" % got)

    def test_a_tick_at_a_time_does_not_erase_it(self):
        """The way adventure mode actually delivers time.

        One tick at a time used to take a hundred points of wound pain to
        nothing over a hundred ticks. It should take off two.
        """
        left = self._run(self._hurt(), self.TOTAL, 1)
        self.assertGreater(left, 0, "a hundred ticks erased every wound's pain")
        self.assertEqual(left, self.PAIN * self.WOUNDS
                         - int(self.TOTAL * body_mod.PAIN_FADE) * self.WOUNDS)

    def test_the_rate_it_names_is_the_rate_it_charges(self):
        for total in (50, 100, 500):
            left = self._run(self._hurt(), total, 1)
            worn = (self.PAIN * self.WOUNDS - left) / float(self.WOUNDS)
            self.assertAlmostEqual(worn, total * body_mod.PAIN_FADE, delta=1.0,
                                   msg="%d ticks wore off %g" % (total, worn))

    def test_an_open_wound_goes_on_hurting(self):
        """`Body.pain` cannot settle below the wounds still open.

        One wound, not four, and long enough for the bank to pay out. The
        body's own shock settles `PAIN_BODY_FADE` times faster than the cut
        under it, so with several wounds the floor falls faster than the
        shock does and nothing can be told apart; with one, the shock would
        sink straight through the floor if it were not held.
        """
        c = make_creature(RNG("onewound"), "human")
        part = c.body.parts["left_leg_upper"]
        part.wounds.append(body_mod.Wound(
            part="left_leg_upper", tissue="muscle", severity=9, kind="cut",
            bleeding=0, pain=self.PAIN))
        c.body.pain = self.PAIN
        self._run(c, 600, 1)
        floor = sum(w.pain for p in c.body.parts.values() for w in p.wounds)
        self.assertGreater(floor, 0, "the wound closed; nothing to hold up to")
        self.assertGreaterEqual(c.body.pain, floor,
                                "shock settled below an open wound")

    def test_a_fight_is_worse_at_the_end_than_in_the_middle(self):
        """The point of the whole thing.

        Traced before the fix: the goblin's pain peaked at 0.50 on round
        twenty and receded to 0.41 by round thirty-five while its wounds went
        from twelve to sixteen and its blood from 75% to 48% -- and because
        `effective_speed` reads pain, it got *faster* as it was cut apart.
        """
        rng = RNG("worse")
        a = make_creature(rng, "human", faction="player", level=1)
        for it in starting_kit(rng, "human", "warrior"):
            a.inventory.add(it)
        a.inventory.auto_equip()
        b = make_creature(rng, "goblin", faction="hostile", level=1)
        middle = end = None
        for n in range(1, 60):
            combat.melee_attack(a, b, rng=rng)
            if b.body.dead:
                break
            combat.melee_attack(b, a, rng=rng)
            b.body.tick(rng, 1, 1.0, 1.0)
            a.body.tick(rng, 1, 1.0, 1.0)
            if n == 15:
                middle = (b.body.pain_level(), b.effective_speed())
            end = (b.body.pain_level(), b.effective_speed())
        self.assertIsNotNone(middle, "the fight was over before it started")
        self.assertGreaterEqual(end[0], middle[0],
                                "it hurt less at the end: %s -> %s"
                                % (middle, end))
        self.assertLessEqual(end[1], middle[1],
                             "it sped up as it was cut apart: %s -> %s"
                             % (middle, end))

    def test_the_bank_is_not_saved_and_does_not_need_to_be(self):
        """The same call as `_clot_ticks`, which is not saved either."""
        c = self._hurt()
        c.body.tick(RNG("s"), 3, 1.0, 1.0)
        self.assertNotIn("pain_ticks", c.body.to_dict())
        again = body_mod.Body.from_dict(json.loads(json.dumps(c.body.to_dict())))
        self.assertEqual(again.pain, c.body.pain)
        self.assertEqual(
            sum(w.pain for p in again.parts.values() for w in p.wounds),
            sum(w.pain for p in c.body.parts.values() for w in p.wounds))


class TestTheSkillNobodyCouldHave(unittest.TestCase):
    """`misc_weapon` -- "Misc. Object User" -- and the pikeman who mined.

    §138 left the skill table as an open question, so it got the
    declared-but-unreachable treatment. Two things fell out.

    `misc_weapon` was defined once in `skills.py` and referenced nowhere else
    in the game. Nothing could reach it: `slot_for` put an item in a hand only
    when `defn.category == "weapon"`, so there was no way to be holding
    anything else, and `skill_for_attack` answered `wrestling` -- the skill for
    having nothing in your hands at all -- when asked about one anyway.

    And the pick's skill was called **Pikeman**. Its own description says
    "Mining tools turned to war"; a pike is governed by `spear`, whose skill is
    called Spearman. A dwarf who fought with a pick was shown as a pikeman.
    """

    def _item(self, iid, mat=None):
        return make_item(RNG("i"), iid, material=mat) if mat \
            else make_item(RNG("i"), iid)

    def _man(self):
        return make_creature(RNG("m"), "human", faction="player")

    # -- the pick ---------------------------------------------------------- #

    def test_a_pick_is_not_a_pike(self):
        from ascii_warriors.game.skills import SKILLS

        self.assertEqual(SKILLS["pick"].name, "Pick User")
        self.assertNotIn("pike", SKILLS, "there is no pike skill to be named "
                                         "after")
        self.assertEqual(SKILLS["spear"].name, "Spearman")

    def test_a_pike_is_governed_by_the_spear(self):
        """Which is why the name was free to be wrong for so long."""
        self.assertEqual(
            combat.skill_for_attack(self._man(), self._item("pike", "iron")),
            "spear")

    # -- the skill nobody could have ---------------------------------------- #

    def test_you_can_pick_up_a_chair(self):
        man = self._man()
        chair = self._item("chair")
        man.inventory.add(chair)
        ok, msg = man.inventory.equip(chair)
        self.assertTrue(ok, msg)
        self.assertIs(man.inventory.weapon(), chair)

    def test_and_the_skill_for_it_is_the_one_in_the_table(self):
        from ascii_warriors.game.skills import SKILLS

        self.assertIn("misc_weapon", SKILLS)
        self.assertEqual(
            combat.skill_for_attack(self._man(), self._item("chair")),
            "misc_weapon")

    def test_swinging_it_teaches_you_to_swing_it(self):
        """A skill you cannot train is the same as one you cannot have."""
        man = self._man()
        chair = self._item("chair")
        man.inventory.add(chair)
        man.inventory.equip(chair)
        before = man.skills.exp("misc_weapon")
        for i in range(30):
            foe = make_creature(RNG("f%d" % i), "human", faction="hostile")
            combat.melee_attack(man, foe, weapon=chair, rng=RNG("s%d" % i))
        self.assertGreater(man.skills.exp("misc_weapon"), before)

    def test_a_statue_is_scenery(self):
        """The line is volume, and it was guessed wrong the first time.

        60000 was picked on the assumption that a statue was half a million.
        It is 30000, so the first version of this let you fight with one.
        """
        man = self._man()
        statue = self._item("statue")
        self.assertGreater(statue.defn.volume, item_mod.SWINGABLE_VOLUME)
        man.inventory.add(statue)
        ok, _msg = man.inventory.equip(statue)
        self.assertFalse(ok, "wielded a statue")

    def test_armour_still_goes_on_rather_than_in_the_hand(self):
        """Asked of the predicate as well as of the slot.

        `slot_for` filters armour out before it ever calls `can_be_swung`, so
        going only through `equip` cannot tell whether the predicate holds --
        which the re-break pass demonstrated by deleting the check and losing
        nothing.
        """
        for iid in ("mail_shirt", "helm", "high_boots", "shield"):
            man = self._man()
            piece = self._item(iid, "iron")
            self.assertFalse(piece.can_be_swung, "%s is not a club" % iid)
            man.inventory.add(piece)
            ok, msg = man.inventory.equip(piece)
            self.assertTrue(ok, msg)
            self.assertNotEqual(man.inventory.slot_of(piece), "weapon", iid)

    def test_nobody_arms_themselves_with_a_sandwich(self):
        """`auto_equip` picks a weapon, and food is not one."""
        man = self._man()
        for iid in ("meat", "bread", "chair"):
            man.inventory.add(self._item(iid))
        man.inventory.add(self._item("sword", "iron"))
        man.inventory.auto_equip()
        held = man.inventory.weapon()
        self.assertIsNotNone(held)
        self.assertEqual(held.def_id, "sword")

    # -- and it is worth doing ---------------------------------------------- #

    def test_a_chair_beats_a_fist_and_a_sandwich_does_not(self):
        """The point of picking anything up."""
        def blows(iid):
            man = self._man()
            w = None
            if iid is not None:
                w = self._item(iid)
                man.inventory.add(w)
                man.inventory.equip(w)
            total = 0.0
            for i in range(150):
                rng = RNG("b%s%d" % (iid, i))
                foe = make_creature(rng, "human", faction="hostile")
                combat.melee_attack(man, foe, weapon=w, rng=rng)
                total += sum(wd.severity for p in foe.body.parts.values()
                             for wd in p.wounds)
            return total / 150.0

        fists = blows(None)
        chair = blows("chair")
        meat = blows("meat")
        self.assertGreater(chair, fists * 2,
                           "a chair is no better than a fist")
        self.assertGreater(chair, meat * 3,
                           "a sandwich is as good as a chair")
        # Not asserted: that a sandwich is worse than a bare fist. It is, over
        # five hundred blows (0.16 against 0.26), and it is not over a hundred
        # and fifty (0.31 against 0.23). A wide, soft, low-penetration swing
        # against a narrow hard one is close enough that the ordering is noise
        # at any sample size this suite can afford.

    def test_furniture_swings_like_furniture(self):
        """Slow. A chair used to cost a punch, which made it faster than a
        sword and nearly as damaging."""
        man = self._man()
        chair = self._item("chair")
        sword = self._item("sword", "iron")
        chair_cost = combat.attack_cost(
            man, chair, combat.choose_attack(man, chair, RNG("a"), man))
        sword_costs = [combat.attack_cost(man, sword, a)
                       for a in sword.attacks()]
        self.assertGreater(chair_cost, max(sword_costs),
                           "furniture swings faster than a sword")

    def test_it_reads_as_a_sentence(self):
        """"swings Ustnok in the leg" is not one."""
        from ascii_warriors.engine.screen import frag_str

        man = self._man()
        chair = self._item("chair")
        man.inventory.add(chair)
        man.inventory.equip(chair)
        log = MessageLog()
        for i in range(20):
            foe = make_creature(RNG("l%d" % i), "goblin", faction="hostile")
            combat.melee_attack(man, foe, weapon=chair, rng=RNG("k%d" % i),
                                log=log)
        text = " ".join(frag_str(m.display()) for m in log.all())
        self.assertIn("clubs", text)
        self.assertNotIn("swings ", text)
        self.assertNotIn("punches", text)
        self.assertNotIn("kicks", text)


class TestTheModesNobodyEnters(unittest.TestCase):
    """A table of AI modes that nothing read, and so nothing kept true.

    A sweep of the package found 740 module-level constants, 28 of them read
    by nothing. Most are the colour palette, which is a palette. `ai.MODES`
    was not: it listed "travel" and "talk", which no code path can produce,
    and omitted "spin" and "stuck", which `take_turn` assigns to a spider
    throwing a web and to anything caught in one. Both lists were thirteen
    long, which is how it went unnoticed.

    Measured in play as well as in the source -- three fortresses over seven
    days and four adventures -- the modes actually entered were idle 31207,
    wander 6794, follow 2000, flee 1200, guard 1199, hunt 800. The rest are
    rare rather than dead: `pick_mode` returns "sleep" for anything
    unconscious, "graze" and "forage" for a hungry herbivore, "lurk" for an
    ambusher, and none of those came up in the sample.

    This test derives the truth from the source so the list cannot drift
    again while nothing reads it.
    """

    @staticmethod
    def _modes_the_code_can_produce():
        """Every mode string `ai.py` can put on a creature."""
        import ast
        import inspect

        from ascii_warriors.game import ai as ai_mod

        tree = ast.parse(inspect.getsource(ai_mod))
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "pick_mode":
                for r in ast.walk(node):
                    if isinstance(r, ast.Return) \
                            and isinstance(r.value, ast.Constant) \
                            and isinstance(r.value.value, str):
                        out.add(r.value.value)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) \
                    and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Attribute) and tgt.attr == "mode" \
                            and isinstance(tgt.value, ast.Name) \
                            and tgt.value.id == "ai":
                        out.add(node.value.value)
        return out

    def test_the_table_lists_exactly_what_the_code_produces(self):
        from ascii_warriors.game import ai as ai_mod

        real = self._modes_the_code_can_produce()
        self.assertTrue(real, "the scan found no modes at all")
        declared = set(ai_mod.MODES)
        self.assertEqual(declared - real, set(),
                         "listed but no code path produces it")
        self.assertEqual(real - declared, set(),
                         "produced but missing from MODES")

    def test_the_web_modes_are_in_it(self):
        """The two that were missing, named so the fix cannot silently undo."""
        from ascii_warriors.game import ai as ai_mod

        self.assertIn("spin", ai_mod.MODES)
        self.assertIn("stuck", ai_mod.MODES)

    def test_no_duplicates(self):
        from ascii_warriors.game import ai as ai_mod

        self.assertEqual(len(ai_mod.MODES), len(set(ai_mod.MODES)))

    def test_the_treatment_list_cannot_drift_from_the_tables(self):
        """`TREATMENTS` was a third copy that nothing consulted."""
        from ascii_warriors.game import medical

        self.assertEqual(set(medical.TREATMENTS), set(medical.TREATMENT_NAMES))
        self.assertEqual(set(medical.TREATMENTS), set(medical.TREATMENT_SKILL))

    def test_a_tick_really_is_six_seconds(self):
        """The claim the architecture keeps repeating, made load-bearing.

        `SECONDS_PER_TICK` was declared and read by nothing, so the minute
        below it was a bare 10 that happened to agree.
        """
        from ascii_warriors.data import calendar

        self.assertEqual(calendar.SECONDS_PER_TICK * calendar.TICKS_PER_MINUTE,
                         60)
        self.assertEqual(calendar.TICKS_PER_DAY, 14400)


class TestAWarriorWhoCanUseASword(unittest.TestCase):
    """`Game.new_game` took a profession, stored it, and ignored it.

    The skills each profession starts with lived in `ui/charcreate.py`, and
    `new_game` applied only whatever skills the caller passed alongside. The
    character-creation screen passed them. `tests/test_systems.py` reaches
    into the UI and applies them by hand, in three places. `tools/play.py`
    passed `{"race": "human", "profession": "warrior"}` and nothing else, and
    so spent its whole existence measuring a man with an iron sword, a mail
    shirt and no idea what to do with either:

        the character play() made: sword/iron, mail_shirt, helm
                                   fighter 0, sword 0
        duelled twenty times:      1 win of 20 against a wolf
                                   0 of 20 against a goblin

    The duel test two classes up says a starting warrior "beats a wolf forty
    times in forty in seven exchanges". Both were true. They were not the same
    warrior.

    Measured over forty seeds, the same seeds both ways:

        fighter 0   mean 328.7 turns, median 138.5, longest 4214, survived 0
        fighter 4   mean 679.5 turns, median 155.0, longest 16000, survived 1

    Thirty-eight of the forty lived longer, and one reached the sixteen
    thousand turns the driver asks for -- the first time anything has, and the
    reason §143.4, §144.4 and §147 could each report that three quarters of
    the run had never been exercised by anything.
    """

    def _new_game(self, spec, seed="prof"):
        import tempfile

        from ascii_warriors.game.state import Game
        from ascii_warriors.world.worldgen import generate_world

        old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = tempfile.mkdtemp()
        try:
            rng = RNG(seed)
            world = generate_world(rng.sub("w"), size="pocket",
                                   history_years=5)
            return Game.new_game(world, spec, rng)
        finally:
            if old is None:
                os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
            else:
                os.environ["ASCII_WARRIORS_SAVE_DIR"] = old

    def test_asking_for_a_warrior_gets_one(self):
        game = self._new_game({"race": "human", "profession": "warrior"})
        p = game.player
        self.assertGreaterEqual(p.skills.level("sword"), 4,
                                "a warrior who has never held a sword")
        self.assertGreaterEqual(p.skills.level("fighter"), 4)

    def test_every_profession_starts_with_what_it_says(self):
        from ascii_warriors.data import professions

        for name, (_desc, skills) in professions.PROFESSIONS.items():
            game = self._new_game({"race": "human", "profession": name},
                                  seed="prof-" + name)
            for skill, level in skills.items():
                self.assertGreaterEqual(
                    game.player.skills.level(skill), level,
                    "%s should start with %s %d" % (name, skill, level))

    def test_what_the_caller_asks_for_still_wins(self):
        """Character creation passes its own skills; they must not be lost."""
        game = self._new_game({"race": "human", "profession": "warrior",
                               "skills": {"sword": 9}})
        self.assertEqual(game.player.skills.level("sword"), 9)

    def test_a_profession_nobody_has_heard_of_is_not_a_crash(self):
        from ascii_warriors.data import professions

        self.assertEqual(professions.skills_for("chandler"), {})
        game = self._new_game({"race": "human", "profession": "chandler"})
        self.assertEqual(game.player.profession, "chandler")

    def test_there_is_only_one_copy_of_the_table(self):
        """The UI re-exports it rather than keeping a second one to drift."""
        from ascii_warriors.data import professions
        from ascii_warriors.ui import charcreate

        self.assertIs(charcreate.PROFESSIONS, professions.PROFESSIONS)

    def test_the_driver_gets_a_fighter(self):
        """End to end, through the call `tools/play.py` actually makes."""
        game = self._new_game({"race": "human", "profession": "warrior"},
                              seed="driver")
        self.assertGreater(game.player.skills.level("fighter"), 0,
                           "the adventure driver is measuring a novice again")
