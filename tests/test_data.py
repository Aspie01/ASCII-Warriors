"""Tests for the static data tables."""

from __future__ import annotations

import unittest

from ascii_warriors.data import (
    biomes, bodies, calendar, creatures, descriptors, items, materials, names,
)
from ascii_warriors.engine.rng import RNG


class TestMaterials(unittest.TestCase):
    def test_required_materials_present(self):
        required = (
            "copper bronze iron steel silver gold platinum adamantine "
            "granite gabbro basalt obsidian marble limestone sandstone slate "
            "oak willow pine leather bone shell chitin ivory horn tooth "
            "pig_tail_cloth silk_cloth wool_cloth diamond ruby sapphire "
            "emerald amethyst topaz glass ice water blood skin fat muscle "
            "nerve nail hair cartilage brain lung heart gut soap charcoal ash"
        ).split()
        for mid in required:
            self.assertTrue(materials.exists(mid), mid)

    def test_weight_calculation(self):
        iron = materials.get("iron")
        # A litre of iron weighs about 7.85 kg.
        self.assertAlmostEqual(iron.weight_of(1000), 7.85, places=2)

    def test_steel_beats_iron_beats_copper(self):
        steel = materials.get("steel")
        iron = materials.get("iron")
        copper = materials.get("copper")
        self.assertGreater(steel.shear_yield, iron.shear_yield)
        self.assertGreater(iron.shear_yield, copper.shear_yield)

    def test_flags_and_queries(self):
        self.assertTrue(materials.get("iron").is_metal)
        self.assertFalse(materials.get("oak").is_metal)
        self.assertTrue(materials.get("steel").can_hold_edge)
        self.assertFalse(materials.get("gold").can_hold_edge)
        self.assertTrue(materials.by_flag("METAL"))
        self.assertTrue(materials.by_category("stone"))
        self.assertEqual(materials.get("no_such_material").id, "iron")

    def test_stone_layers_resolve(self):
        for layer, mats in materials.STONE_LAYERS.items():
            for mid in mats:
                self.assertTrue(materials.exists(mid), "%s/%s" % (layer, mid))


class TestBodies(unittest.TestCase):
    def test_plans_are_valid(self):
        self.assertEqual(bodies.validate(), [])

    def test_required_plans(self):
        for plan in ("humanoid", "quadruped", "bird", "serpent", "insect",
                     "fish", "blob", "dragon", "giant_humanoid"):
            self.assertIn(plan, bodies.BODY_PLANS)

    def test_humanoid_completeness(self):
        ids = {p.id for p in bodies.BODY_PLANS["humanoid"]}
        for pid in ("head", "brain", "skull", "left_eye", "right_eye", "neck",
                    "throat", "upper_body", "lower_body", "heart", "left_lung",
                    "right_lung", "liver", "guts", "spine", "ribs",
                    "left_arm_upper", "left_arm_end", "right_leg_end"):
            self.assertIn(pid, ids)

    def test_tissue_materials_exist(self):
        for tissue in bodies.TISSUES.values():
            self.assertTrue(materials.exists(tissue.material), tissue.id)

    def test_fallbacks(self):
        self.assertEqual(bodies.build_plan("nonsense"),
                         bodies.BODY_PLANS["humanoid"])
        self.assertEqual(bodies.tissue("nonsense").id, "muscle")


class TestItems(unittest.TestCase):
    def test_data_valid(self):
        self.assertEqual(items.validate(), [])

    def test_required_items(self):
        required = (
            "dagger short_sword sword long_sword two_handed_sword axe "
            "battle_axe great_axe mace morningstar warhammer maul spear pike "
            "halberd scimitar whip flail pick crossbow bow sling bolt arrow "
            "stone_ammo cap helm mail_shirt breastplate greaves gauntlets "
            "high_boots shield buckler cloak robe tunic trousers shoes hood "
            "backpack waterskin rope torch lantern lockpick whetstone bandage "
            "meat plump_helmet bread cheese dwarven_ale wine rum coin gem "
            "book instrument corpse"
        ).split()
        for iid in required:
            self.assertTrue(items.exists(iid), iid)

    def test_weapons_have_attacks_and_skills(self):
        from ascii_warriors.game.skills import SKILLS

        for item in items.ITEMS.values():
            if item.weapon is None:
                continue
            self.assertTrue(item.weapon.attacks, item.id)
            self.assertIn(item.weapon.skill, SKILLS, item.id)

    def test_armor_coverage_uses_known_categories(self):
        known = {"head", "neck", "torso", "arm", "hand", "leg", "foot", "organ"}
        for item in items.armor_pieces():
            for part in item.armor.coverage:
                self.assertIn(part, known, item.id)

    def test_queries(self):
        self.assertTrue(items.by_category("weapon"))
        self.assertTrue(items.weapons_for_skill("sword"))
        self.assertTrue(items.melee_weapons())
        self.assertTrue(items.ranged_weapons())
        self.assertEqual(items.get("nonsense").id, "boulder")


class TestCreatures(unittest.TestCase):
    def test_data_valid(self):
        self.assertEqual(creatures.validate(), [])

    def test_playable_races_exist_and_speak(self):
        for race in creatures.PLAYABLE_RACES:
            defn = creatures.get(race)
            self.assertTrue(defn.intelligent, race)
            self.assertIsNotNone(defn.civ, race)

    def test_roster_size_and_variety(self):
        self.assertGreaterEqual(len(creatures.CREATURES), 60)
        self.assertTrue(creatures.megabeasts())
        self.assertTrue(creatures.night_creatures())
        self.assertGreaterEqual(len(creatures.civilized_races()), 5)

    def test_spawnable_filters(self):
        forest = creatures.spawnable("temperate_forest", max_tier=3)
        self.assertTrue(forest)
        self.assertTrue(all(c.tier <= 3 for c in forest))
        underground = creatures.spawnable("", underground=True)
        self.assertTrue(underground)
        self.assertTrue(all("SUBTERRANEAN" in c.flags for c in underground))
        peaceful = creatures.spawnable("grassland", flags_none=("EVIL", "SAVAGE"))
        self.assertTrue(all("EVIL" not in c.flags for c in peaceful))

    def test_forgotten_beast_generation(self):
        rng = RNG(5)
        for _ in range(20):
            fb = creatures.random_forgotten_beast(rng, "Test Beast")
            self.assertIn(fb.body_plan, bodies.BODY_PLANS)
            self.assertTrue(fb.attacks)
            self.assertTrue(fb.description)
            part_ids = {p.id for p in bodies.BODY_PLANS[fb.body_plan]}
            for na in fb.attacks:
                if na.part:
                    self.assertIn(na.part, part_ids, fb.body_plan)


class TestBiomes(unittest.TestCase):
    def test_required_biomes(self):
        required = (
            "ocean deep_ocean lake river glacier tundra taiga temperate_forest "
            "temperate_broadleaf tropical_forest jungle savanna shrubland "
            "grassland desert badlands mountain hills marsh swamp beach volcano"
        ).split()
        for bid in required:
            self.assertTrue(biomes.exists(bid), bid)

    def test_classification(self):
        self.assertEqual(biomes.classify(0.95, 0.5, 50, 0.5), "mountain")
        self.assertEqual(biomes.classify(0.1, 0.5, 50, 0.5, is_water=True),
                         "deep_ocean")
        self.assertEqual(biomes.classify(0.5, 0.05, 80, 0.5), "desert")
        self.assertEqual(biomes.classify(0.5, 0.85, 80, 0.5), "jungle")
        self.assertEqual(biomes.classify(0.5, 0.5, 0, 0.5), "tundra")

    def test_classification_always_known(self):
        for e in (0.0, 0.3, 0.6, 0.9):
            for r in (0.0, 0.3, 0.6, 1.0):
                for t in (-10, 10, 40, 80, 110):
                    for d in (0.0, 0.5, 1.0):
                        bid = biomes.classify(e, r, t, d)
                        self.assertTrue(biomes.exists(bid), bid)

    def test_labels(self):
        self.assertEqual(biomes.savagery_name(90), "Savage")
        self.assertEqual(biomes.alignment_name(90), "Evil")
        self.assertEqual(biomes.alignment_name(10), "Good")
        self.assertIn("Forest", biomes.region_adjective("temperate_forest", 50, 50))


class TestCalendar(unittest.TestCase):
    def test_month_and_season_mapping(self):
        self.assertEqual(len(calendar.MONTHS), 12)
        for m in range(1, 13):
            self.assertIn(calendar.season_of_month(m), calendar.SEASONS)
        self.assertEqual(calendar.season_of_month(1), "Spring")
        self.assertEqual(calendar.season_of_month(12), "Winter")

    def test_components_round_trip(self):
        t = calendar.GameTime.at(125, 7, 14, 13, 30)
        self.assertEqual((t.year, t.month, t.day, t.hour, t.minute),
                         (125, 7, 14, 13, 30))
        self.assertEqual(t.month_name, "Limestone")

    def test_year_boundary(self):
        t = calendar.GameTime.at(125, 12, 28, 23, 50)
        t.advance(calendar.TICKS_PER_MINUTE * 10)
        self.assertEqual((t.year, t.month, t.day, t.hour), (126, 1, 1, 0))

    def test_light_and_night(self):
        for hour in range(24):
            t = calendar.GameTime.at(125, 1, 1, hour)
            self.assertTrue(0.0 <= t.light_level() <= 1.0)
        self.assertTrue(calendar.GameTime.at(125, 1, 1, 2).is_night())
        self.assertFalse(calendar.GameTime.at(125, 1, 1, 12).is_night())
        self.assertGreater(calendar.GameTime.at(125, 1, 1, 12).light_level(),
                           calendar.GameTime.at(125, 1, 1, 3).light_level())

    def test_ordinal(self):
        cases = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 11: "11th", 12: "12th",
                 13: "13th", 21: "21st", 101: "101st", 112: "112th"}
        for n, want in cases.items():
            self.assertEqual(calendar.ordinal(n), want)

    def test_serialisation(self):
        t = calendar.GameTime.at(200, 3, 5, 9, 10)
        self.assertEqual(calendar.GameTime.from_dict(t.to_dict()), t)

    def test_duration_words(self):
        self.assertEqual(calendar.duration_str(1), "a moment")
        self.assertIn("hour", calendar.duration_str(calendar.TICKS_PER_HOUR * 3))
        self.assertIn("day", calendar.duration_str(calendar.TICKS_PER_DAY * 2))


class TestDescriptors(unittest.TestCase):
    def test_skill_ladder(self):
        for lv in range(21):
            self.assertTrue(descriptors.skill_level_name(lv))
        self.assertEqual(descriptors.skill_level_name(0), "Dabbling")
        self.assertEqual(descriptors.skill_level_name(15), "Legendary")
        self.assertEqual(descriptors.skill_level_name(20), "Legendary+5")
        self.assertEqual(descriptors.skill_level_name(99), "Legendary+5")

    def test_quality(self):
        self.assertEqual(descriptors.quality_wrap(0, "sword"), "sword")
        self.assertEqual(descriptors.quality_wrap(3, "sword"), "*sword*")
        self.assertEqual(descriptors.quality_wrap(6, "sword"), "@sword@")
        self.assertEqual(descriptors.quality_name(5), "masterwork")

    def test_attribute_descriptions_cover_every_attribute(self):
        from ascii_warriors.game.attributes import ALL_ATTRS

        for attr in ALL_ATTRS:
            self.assertEqual(descriptors.attribute_desc(attr, 1000), "")
            self.assertTrue(descriptors.attribute_desc(attr, 5000), attr)
            self.assertTrue(descriptors.attribute_desc(attr, 0), attr)

    def test_text_helpers(self):
        self.assertEqual(descriptors.list_join(["a"]), "a")
        self.assertEqual(descriptors.list_join(["a", "b"]), "a and b")
        self.assertEqual(descriptors.list_join(["a", "b", "c"]), "a, b and c")
        self.assertEqual(descriptors.indefinite_article("iron sword"), "an")
        self.assertEqual(descriptors.indefinite_article("steel sword"), "a")
        self.assertEqual(descriptors.pluralize("axe", 2), "axes")
        self.assertEqual(descriptors.pluralize("axe", 1), "axe")
        self.assertEqual(descriptors.number_word(3), "three")

    def test_state_words(self):
        self.assertTrue(descriptors.wound_severity(0.0))
        self.assertTrue(descriptors.wound_severity(1.0))
        self.assertTrue(descriptors.stress_desc(0))
        self.assertTrue(descriptors.stress_desc(200))
        self.assertTrue(descriptors.age_desc(5, "human"))
        self.assertTrue(descriptors.size_desc(70000))


class TestNames(unittest.TestCase):
    def test_personal_names(self):
        rng = RNG("names")
        for race in creatures.PLAYABLE_RACES:
            for female in (False, True):
                name = names.name_for_race(race, rng, female)
                self.assertTrue(name)
                self.assertEqual(name, name.strip())

    def test_generated_names_have_no_unexpanded_tokens(self):
        rng = RNG("tokens")
        makers = [
            lambda: names.site_name(rng, "dwarf", "fortress")[1],
            lambda: names.site_name(rng, "human", "town")[1],
            lambda: names.civ_name(rng, "goblin")[1],
            lambda: names.artifact_name(rng, "dwarf")[1],
            lambda: names.region_name(rng, "temperate_forest"),
            lambda: names.beast_name(rng),
            lambda: names.group_name(rng, "bandit"),
        ]
        for maker in makers:
            for _ in range(60):
                value = maker()
                self.assertNotIn("{", value)
                self.assertTrue(value.strip())

    def test_native_and_translated_differ(self):
        rng = RNG("pairs")
        native, translated = names.site_name(rng, "dwarf", "fortress")
        self.assertTrue(native)
        self.assertTrue(translated)
        self.assertNotEqual(native, translated)

    def test_titles(self):
        rng = RNG("titles")
        self.assertTrue(names.title_for(rng, "leader", True))
        self.assertTrue(names.title_for(rng, "hero"))
        self.assertTrue(names.title_for(rng, "monster"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
