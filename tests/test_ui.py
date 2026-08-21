"""Tests that drive the real UI through a headless terminal."""

from __future__ import annotations

import os
import tempfile
import unittest

from ascii_warriors.engine import keys
from ascii_warriors.engine.rng import RNG
from ascii_warriors.engine.terminal import HeadlessTerminal, QuitSignal
from ascii_warriors.game.state import Game
from ascii_warriors.ui.app import App
from ascii_warriors.world.worldgen import generate_world


class UITestBase(unittest.TestCase):
    """Builds a small game and an app wired to a headless terminal."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp
        rng = RNG("ui")
        world = generate_world(rng.sub("w"), size="pocket", history_years=25)
        self.game = Game.new_game(
            world, {"race": "dwarf", "profession": "warrior"}, rng)
        self.term = HeadlessTerminal(100, 34)
        self.app = App(self.term)
        self.app.game = self.game

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def render(self, scene) -> str:
        """Push a scene, draw it and return the plain-text frame."""
        self.app.push(scene)
        self.app.draw()
        return self.term.last_text()


class TestScreensRender(UITestBase):
    def test_play_screen(self):
        from ascii_warriors.ui.play_screen import PlayScene

        text = self.render(PlayScene(self.app))
        self.assertIn(self.game.player.name, text)
        self.assertIn("Body", text)
        self.assertIn("Wielding", text)
        self.assertIn("@", text)

    def test_character_screen_all_tabs(self):
        from ascii_warriors.ui.character_screen import CharacterScene

        for tab in range(5):
            scene = CharacterScene(self.app, tab=tab)
            text = self.render(scene)
            self.assertIn("Character", text)
            self.app.pop()

    def test_inventory_screen(self):
        from ascii_warriors.ui.inventory_screen import InventoryScene

        scene = InventoryScene(self.app)
        text = self.render(scene)
        self.assertIn("Inventory", text)
        self.assertIn("kg", text)
        scene.handle("TAB")
        self.app.draw()
        self.assertIn("Weapon", self.term.last_text())

    def test_legends_screen_all_tabs(self):
        from ascii_warriors.ui.legends_screen import LegendsScene

        scene = LegendsScene(self.app)
        text = self.render(scene)
        self.assertIn("Legends", text)
        for _ in range(5):
            scene.handle("TAB")
            self.app.draw()
            self.assertIn("Legends", self.term.last_text())

    def test_legends_detail_pages(self):
        from ascii_warriors.ui.legends_screen import LegendsScene

        scene = LegendsScene(self.app)
        self.render(scene)
        scene.handle("TAB")
        scene.handle("ENTER")
        self.app.draw()
        self.assertIsNotNone(scene.detail)

    def test_help_screen(self):
        from ascii_warriors.ui.help_screen import HelpScene

        scene = HelpScene(self.app)
        text = self.render(scene)
        self.assertIn("Help", text)
        for _ in range(4):
            scene.handle("TAB")
            self.app.draw()
            self.assertTrue(self.term.last_text().strip())

    def test_travel_screen(self):
        from ascii_warriors.ui.travel_screen import TravelScene

        scene = TravelScene(self.app, view_only=True)
        text = self.render(scene)
        self.assertIn("World map", text)
        self.assertIn("@", text)

    def test_travel_screen_says_who_holds_a_place(self):
        """The screen you decide from, not just the legends screen.

        A necromancer's tower and a bandit's camp are both "a tower,
        population 4" until this line, and who is standing in it is the whole
        of the decision to go there.
        """
        from ascii_warriors.ui.travel_screen import TravelScene

        world = self.game.world
        site = next(s for s in world.sites if not s.is_ruin)
        holder = next(f for f in world.figures.values() if f.alive(world.year))
        site.owner_hf = holder.id
        scene = TravelScene(self.app, view_only=True)
        # Pushed first, because `Scene.on_enter` puts the cursor back on the
        # player: setting it before `render` and hoping was a test that passed
        # only while the player happened to be standing on the site it had
        # just handed a lord to.
        self.app.push(scene)
        scene.cx, scene.cy = site.wx, site.wy
        self.app.draw()
        text = self.term.last_text()
        self.assertIn("held by", text)
        self.assertIn(holder.name, text)

    def test_look_screen(self):
        from ascii_warriors.ui.look_screen import LookScene

        scene = LookScene(self.app)
        text = self.render(scene)
        self.assertTrue(text.strip())
        scene.handle("j")
        scene.handle("l")
        self.app.draw()
        self.assertTrue(self.term.last_text().strip())

    def test_main_menu(self):
        from ascii_warriors.ui.menus import MainMenu

        text = self.render(MainMenu(self.app))
        self.assertIn("New adventure", text)
        self.assertIn("Quit", text)

    def test_death_screen(self):
        from ascii_warriors.ui.menus import DeathScene

        self.game.end_game("eaten by a dragon")
        text = self.render(DeathScene(self.app))
        self.assertIn("Here lies", text)
        self.assertIn("dragon", text)

    def test_conversation_screen(self):
        from ascii_warriors.ui.dialogs import ConversationScene

        npcs = [
            c for c in self.game.creatures.values()
            if c.defn.has("CAN_SPEAK") and not c.is_player
        ]
        if not npcs:
            self.skipTest("no speakers at this start location")
        scene = ConversationScene(self.app, npcs[0])
        text = self.render(scene)
        self.assertIn("says", text)

    def test_pause_menu_overlays_the_map(self):
        from ascii_warriors.ui.menus import GameMenu
        from ascii_warriors.ui.play_screen import PlayScene

        self.app.push(PlayScene(self.app))
        self.app.push(GameMenu(self.app))
        self.app.draw()
        text = self.term.last_text()
        self.assertIn("Paused", text)
        self.assertIn(self.game.player.name, text)

    def test_small_terminal_still_renders(self):
        from ascii_warriors.ui.play_screen import PlayScene

        term = HeadlessTerminal(72, 22)
        app = App(term)
        app.game = self.game
        app.push(PlayScene(app))
        app.draw()
        self.assertTrue(term.last_text().strip())


class TestKeyHandling(UITestBase):
    def test_movement_keys_advance_the_game(self):
        from ascii_warriors.ui.play_screen import PlayScene

        scene = PlayScene(self.app)
        self.app.push(scene)
        before = self.game.turn
        for key in "jklhyubn":
            scene.handle(key)
        self.assertGreater(self.game.turn, before)

    def test_wait_and_search(self):
        from ascii_warriors.ui.play_screen import PlayScene

        scene = PlayScene(self.app)
        self.app.push(scene)
        scene.handle(".")
        scene.handle("s")
        self.assertGreater(self.game.turn, 0)

    def test_unknown_keys_are_ignored(self):
        from ascii_warriors.ui.play_screen import PlayScene

        scene = PlayScene(self.app)
        self.app.push(scene)
        for key in ("%", "F9", "~", "C-x"):
            scene.handle(key)
        self.assertFalse(self.game.game_over)


class TestFullRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def test_smoke_script_completes(self):
        from tools.smoke import DEFAULT_SCRIPT

        term = HeadlessTerminal(100, 34, list(DEFAULT_SCRIPT))
        app = App(term, seed="uitest", world_size="pocket", history_years=15)
        term.open()
        try:
            app.run()
        except QuitSignal:
            pass
        finally:
            term.close()
        self.assertTrue(term.frames)
        self.assertIsNotNone(app.game)
        self.assertGreater(term.key_count, 50)

    def test_main_headless_entry_point(self):
        from ascii_warriors.main import main

        code = main([
            "--headless", "ENTER,ESC", "--size", "pocket", "--history", "10",
            "--seed", "entry",
        ])
        self.assertEqual(code, 0)

    def test_dump_world(self):
        from ascii_warriors.main import main

        path = os.path.join(self._tmp, "world.txt")
        code = main(["--dump-world", path, "--size", "pocket", "--history", "10",
                     "--seed", "dump"])
        self.assertEqual(code, 0)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Civilizations", text)
        self.assertNotIn("{noun", text)


class TestTheDoorBackIntoAWorld(UITestBase):
    """The screens that make a world outlive the character who played there."""

    def _saved_world(self):
        from ascii_warriors.game import save as save_mod

        return save_mod.save_world(self.game.world)

    def test_the_world_list_is_empty_until_there_is_a_world(self):
        from ascii_warriors.ui.worldgen_screen import WorldGenScene

        scene = WorldGenScene(self.app)
        self.app.push(scene)
        entry = next(i for i in scene.menu.items if i.value == "old")
        self.assertFalse(entry.enabled)

    def test_a_saved_world_can_be_played_again(self):
        from ascii_warriors.ui.worldgen_screen import WorldGenScene

        self._saved_world()
        scene = WorldGenScene(self.app)
        self.app.push(scene)
        entry = next(i for i in scene.menu.items if i.value == "old")
        self.assertTrue(entry.enabled)

    def test_the_world_list_names_the_world_and_who_is_in_it(self):
        from ascii_warriors.game import renown as renown_mod
        from ascii_warriors.ui.worldgen_screen import WorldMenu

        self.game.player.name = "Sigun Farwalker"
        renown_mod.retire(self.game)
        self._saved_world()
        text = self.render(WorldMenu(self.app))
        self.assertIn(self.game.world.name[:20], text)
        # Both halves of the screen say it: the list line, and the panel under
        # it that says what the last character left behind here.
        self.assertIn("Sigun Farwalker settled here", text)
        self.assertIn("Sigun Farwalker settled here and is still alive", text)

    def test_the_column_headings_line_up_with_their_columns(self):
        """A menu row is pushed right by its "a) " hotkey; the heading above
        it has to be too, or every heading names the column to its left."""
        from ascii_warriors.ui.worldgen_screen import WorldMenu

        self._saved_world()
        lines = self.render(WorldMenu(self.app)).splitlines()
        name = self.game.world.name[:28]
        head = next(ln for ln in lines if "WHO IS THERE" in ln)
        row = next(ln for ln in lines if name in ln)
        self.assertEqual(head.index("WORLD"), row.index(name))

    def test_choosing_a_world_rolls_a_character_in_it(self):
        from ascii_warriors.ui.charcreate import CharCreateScene
        from ascii_warriors.ui.worldgen_screen import WorldMenu

        self._saved_world()
        scene = WorldMenu(self.app)
        self.app.push(scene)
        scene.handle(keys.ENTER)
        top = self.app.current
        self.assertIsInstance(top, CharCreateScene)
        self.assertEqual(top.world.name, self.game.world.name)
        self.assertIsNot(top.world, self.game.world)

    def test_choosing_a_world_to_embark_in_goes_to_the_embark_screen(self):
        from ascii_warriors.ui.fort.embark import EmbarkScene
        from ascii_warriors.ui.worldgen_screen import WorldMenu

        self._saved_world()
        scene = WorldMenu(self.app, mode="fortress")
        self.app.push(scene)
        scene.handle(keys.ENTER)
        self.assertIsInstance(self.app.current, EmbarkScene)

    def test_legends_can_be_read_without_a_game(self):
        from ascii_warriors.ui.legends_screen import LegendsScene
        from ascii_warriors.ui.worldgen_screen import WorldMenu

        self._saved_world()
        scene = WorldMenu(self.app, mode="legends")
        self.app.push(scene)
        scene.handle(keys.ENTER)
        top = self.app.current
        self.assertIsInstance(top, LegendsScene)
        self.app.game = None
        self.app.draw()
        self.assertIn(self.game.world.name[:20], self.term.last_text())

    def test_the_end_of_a_fortress_puts_it_on_the_map_whichever_key_you_press(self):
        """The epitaph says the place stands on the world map now."""
        from ascii_warriors.fortress.fortress import Fortress
        from ascii_warriors.game import save as save_mod
        from ascii_warriors.ui.fort.fort_screen import FortEndScene

        world = self.game.world
        spot = next((x, y) for y in range(world.height)
                    for x in range(world.width)
                    if world.tile(x, y).site_id is None
                    and not world.tile(x, y).is_ocean)
        fort = Fortress.embark(world, spot[0], spot[1], RNG("endscene"))
        fort.lost = True
        fort.loss_reason = "abandoned"
        self.app.push(FortEndScene(self.app, fort))
        self.assertTrue(fort.recorded)
        back = save_mod.load_world(save_mod.list_worlds()[0]["path"])
        self.assertIsNotNone(back.preserved_map(spot[0], spot[1]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestARowThatMeansNothing(unittest.TestCase):
    """A `MenuItem` given no value stands for its own text, which is what
    most menus want -- and passing `None` got that too, so a row that meant
    *nothing* came back as the string it was drawn with.

    Found by fuzz seed 23: the inventory screen highlighted an empty armour
    slot and called `full_description` on the string "Head (empty)".
    """

    def test_a_row_with_no_value_stands_for_its_own_text(self):
        from ascii_warriors.engine.widgets import MenuItem

        self.assertEqual(MenuItem("Onwards").value, "Onwards")

    def test_a_row_given_nothing_means_nothing(self):
        from ascii_warriors.engine.widgets import MenuItem

        self.assertIsNone(MenuItem("Head  (empty)", None).value)

    def test_a_row_that_is_switched_off_is_not_a_selection(self):
        from ascii_warriors.engine.widgets import ListMenu, MenuItem

        menu = ListMenu([
            MenuItem("(no saved games)", None, enabled=False),
            MenuItem("A real one", "real"),
        ])
        menu.index = 0
        self.assertIsNone(menu.selected)
        self.assertIsNone(menu.selected_value)
        menu.index = 1
        self.assertEqual(menu.selected_value, "real")

    def test_the_inventory_screen_survives_an_empty_slot(self):
        import os
        import tempfile

        from ascii_warriors.engine.terminal import HeadlessTerminal
        from ascii_warriors.game.state import Game
        from ascii_warriors.ui.app import App
        from ascii_warriors.ui.inventory_screen import InventoryScene
        from ascii_warriors.world.worldgen import generate_world

        old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = tempfile.mkdtemp()
        try:
            rng = RNG("emptyslot")
            world = generate_world(rng.sub("w"), size="pocket",
                                   history_years=5)
            game = Game.new_game(
                world, {"race": "human", "profession": "warrior"}, rng)
            app = App(HeadlessTerminal(100, 34))
            app.game = game
            scene = InventoryScene(app)
            app.push(scene)
            scene.tabs.index = 1          # the equipped tab
            scene.refresh()
            for index in range(len(scene.menu.items)):
                scene.menu.index = index
                app.draw()                # used to raise on an empty slot
            self.assertTrue(app.term.frames)
        finally:
            if old is None:
                os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
            else:
                os.environ["ASCII_WARRIORS_SAVE_DIR"] = old


class TestTheLogIsNotCutInHalf(UITestBase):
    """A message pane that throws away the end of every long line.

    Both log panes drew `frag_slice(msg.display(), 0, w)` -- the first *w*
    columns, and the rest on the floor. A blow reads "<who> <verb> <whom> in
    the <part> with a <weapon>, <what it did to the tissue>", so the half that
    says how bad it is is the half past column eighty. Measured over one
    fortress fight, twenty-five of fifty-seven lines ran past eighty columns.

    `wrap_frags` -- a colour-preserving word wrap -- has been in `screen.py`
    the whole time, and neither pane called it.
    """

    LONG = ("Thugdush Skullsplitter bashes Nomal Anvilhammer in the right "
            "upper leg with a lead mace, tearing apart the skin, tearing "
            "apart the fat, bruising the muscle!")

    WIDTH = 72

    def _draw(self, text, log_owner=None):
        """Draw one message into an empty pane and return the rows used.

        The log starts with five lines of "you arrive at Helmsong" in it, and
        a test that counts rows without clearing them counts those instead --
        which is a count that cannot come out wrong.
        """
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.game.log import MessageLog
        from ascii_warriors.ui.sidebar import draw_log

        owner = log_owner if log_owner is not None else self.game
        owner.log = MessageLog()
        owner.log.combat(text)
        scr = Screen(self.WIDTH, 12)
        draw_log(scr, 0, 0, self.WIDTH, 8, owner)
        rows = [row.rstrip() for row in scr.to_text()]
        used = [r for r in rows if r.strip() and set(r.strip()) != {"-"}]
        return rows, used

    def test_the_tail_of_a_blow_survives(self):
        _rows, used = self._draw(self.LONG)
        shown = " ".join(r.strip() for r in used)
        self.assertIn("Thugdush Skullsplitter", shown)
        self.assertIn("bruising the muscle!", shown,
                      "the end of the sentence was cut off: %r" % shown)
        self.assertEqual(shown, self.LONG, shown)

    def test_it_wraps_rather_than_running_off_the_edge(self):
        rows, used = self._draw(self.LONG)
        for row in rows:
            self.assertLessEqual(len(row), self.WIDTH, row)
        self.assertGreater(len(used), 1,
                           "a %d-column line fitted on one %d-column row"
                           % (len(self.LONG), self.WIDTH))

    def test_a_short_line_still_takes_one_row(self):
        """Wrapping is not padding."""
        _rows, used = self._draw("Nomal Anvilhammer is stunned!")
        self.assertEqual(len(used), 1, used)

    def test_the_fortress_pane_wraps_too(self):
        """Two panes, one defect, and they are separate functions."""
        from ascii_warriors.engine.screen import Screen
        from ascii_warriors.game.log import MessageLog
        from ascii_warriors.ui.fort.sidebar import draw_log as fort_log
        from tests.test_fortress import embark

        fort = embark("logwrap")
        fort.log = MessageLog()
        fort.log.combat(self.LONG)
        scr = Screen(self.WIDTH, 12)
        fort_log(scr, 0, 0, self.WIDTH, 8, fort)
        rows = [row.rstrip() for row in scr.to_text()]
        used = [r for r in rows if r.strip() and set(r.strip()) != {"-"}]
        self.assertEqual(" ".join(r.strip() for r in used), self.LONG,
                         used)


class TestTheManualIsAPromise(unittest.TestCase):
    """Every number the help screen gives a player, against the code.

    The manual is where a fortress player gets the figures they plan with, and
    nothing had ever checked one of them. Thirteen claims audited; three were
    wrong:

    * "A dwarf drinks about one unit a day" -- measured over four fortresses
      and twelve days each, 1.54, 1.67, 1.58 and 1.54. Half again what it said,
      on the resource the same page calls "the difference between a fortress
      and a graveyard".
    * "You can wade through two" -- `SWIM_DEPTH` is 4, so you wade through
      three.
    * "Mounted you carry half again as much" -- `CARRY_SHARE` is 1.6.

    The embark stock knew the truth all along: a hundred and fifty units of
    ale is a fortnight for seven at 1.58 a day and three weeks at the rate the
    sentence claimed.

    These tests pin the wording to the constant, so moving one without the
    other fails here rather than in somebody's fortress.
    """

    def _text(self):
        from ascii_warriors.ui import help_screen

        return " ".join(
            " ".join(getattr(help_screen, name).split())
            for name in ("FORTRESS_TEXT", "COMBAT_TEXT", "WORLD_TEXT",
                         "SURVIVAL_TEXT"))

    def _says(self, phrase):
        self.assertIn(phrase, self._text(),
                      "the manual no longer says %r" % phrase)

    # -- water ------------------------------------------------------------- #

    def test_the_depth_you_can_wade_through(self):
        from ascii_warriors.world.fluids import MAX_DEPTH, SWIM_DEPTH

        self.assertEqual(SWIM_DEPTH, 4)
        self.assertEqual(MAX_DEPTH, 7)
        self._says("Water has depth, from one to seven")
        self._says("You can wade through three")
        self._says("at four your feet leave the bottom")

    def test_swimming_starts_where_the_manual_says_it_does(self):
        """The sentence and the function, asked the same question."""
        from ascii_warriors.game import swimming

        self.assertFalse(swimming.is_swimming(3), "three is wading")
        self.assertTrue(swimming.is_swimming(4), "four is swimming")

    # -- food and drink ----------------------------------------------------- #

    def test_a_dwarf_eats_about_one_a_day_and_drinks_more(self):
        """Measured, not read off a constant.

        `fortress.dwarf.THIRST_URGENT` is 9000 against a 14400-tick day, so
        1.60 a day; the barrels say 1.58. It is measured here rather than
        divided out because the first attempt divided out the *wrong*
        constant -- `needs.THIRST_THIRSTY`, which is when an adventurer is
        told they are thirsty and has no bearing on a dwarf at all. Doubling
        it changes the fortress rate by nothing, which is what the re-break
        pass caught.
        """
        from ascii_warriors.data.calendar import TICKS_PER_DAY
        from ascii_warriors.fortress import sim
        from ascii_warriors.fortress.fortress import Fortress
        from ascii_warriors.ui.fort.embark import suggest_site
        from ascii_warriors.world.worldgen import generate_world

        rng = RNG("manual")
        world = generate_world(rng.sub("w"), size="small", history_years=25)
        wx, wy = suggest_site(world)
        fort = Fortress.embark(world, wx, wy, rng.sub("f"))
        days = 8
        food0, drink0 = fort.food_stock(), fort.stock_count("dwarven_ale")
        for _ in range(days):
            fort_steps = TICKS_PER_DAY // sim.STEP_TICKS
            sim.run(fort, fort_steps)
        n = max(1, len(fort.dwarves()))
        food = (food0 - fort.food_stock()) / float(days) / n
        drink = (drink0 - fort.stock_count("dwarven_ale")) / float(days) / n
        self.assertTrue(0.8 <= food <= 1.25,
                        "manual says a dwarf eats about one a day; %.2f" % food)
        self.assertTrue(1.25 <= drink <= 1.9,
                        "manual says about one and a half a day; %.2f" % drink)
        self._says("eats about one unit a day and drinks about one and a half")

    def test_the_embark_really_is_a_fortnight_of_drink(self):
        """The claim the wrong rate made nonsense of."""
        from ascii_warriors.fortress.fortress import Fortress
        from ascii_warriors.ui.fort.embark import suggest_site
        from ascii_warriors.world.worldgen import generate_world

        rng = RNG("manual2")
        world = generate_world(rng.sub("w"), size="small", history_years=25)
        wx, wy = suggest_site(world)
        fort = Fortress.embark(world, wx, wy, rng.sub("f"))
        n = len(fort.dwarves())
        ale = fort.stock_count("dwarven_ale")
        days = ale / float(n) / 1.58
        self.assertTrue(12 <= days <= 16,
                        "%d units of ale is %.1f days for %d dwarves"
                        % (ale, days, n))
        self._says("a hundred and fifty units of ale is fourteen days")
        self.assertEqual(ale, 150)

    # -- the rest of the numbers -------------------------------------------- #

    def test_seven_dwarves_and_the_livestock(self):
        import collections

        from ascii_warriors.fortress.fortress import Fortress
        from ascii_warriors.ui.fort.embark import suggest_site
        from ascii_warriors.world.worldgen import generate_world

        rng = RNG("manual3")
        world = generate_world(rng.sub("w"), size="small", history_years=25)
        wx, wy = suggest_site(world)
        fort = Fortress.embark(world, wx, wy, rng.sub("f"))
        self.assertEqual(len(fort.dwarves()), 7)
        self._says("Seven dwarves arrive with a wagon")
        herd = collections.Counter(
            c.short_name() for c in fort.creatures.values()
            if c.faction == "fortress" and c.def_id != "dwarf")
        self.assertEqual(herd["dog"], 2)
        self.assertEqual(herd["cat"], 1)
        self.assertEqual(herd["cow"], 2)
        self.assertEqual(herd["sheep"], 2)
        self._says("You arrive with two dogs, a cat, two cows and two sheep")

    def test_a_mount_carries_what_the_manual_says(self):
        from ascii_warriors.game import mounts

        self.assertEqual(mounts.CARRY_SHARE, 1.6)
        self._says("carry a little over half again as much")

    def test_one_level_is_a_step(self):
        from ascii_warriors.world import gravity

        self.assertEqual(gravity.SAFE_DROP, 1)
        self._says("One level is a step")

    def test_a_sheriff_needs_eighteen_dwarves(self):
        from ascii_warriors.fortress import nobles

        sheriff = nobles.POSITIONS.get("sheriff")
        self.assertIsNotNone(sheriff, "there is no sheriff")
        self.assertEqual(sheriff.at_population, 18)
        self._says("a sheriff needs eighteen dwarves")

    def test_thirty_facets_and_twenty_values(self):
        from ascii_warriors.game.personality import FACETS, VALUES

        self.assertEqual(len(FACETS), 30)
        self.assertEqual(len(VALUES), 20)
        self._says("thirty personality facets and twenty values")

    def test_an_alarm_carries_forty_tiles(self):
        from ascii_warriors.game import traps

        self.assertEqual(traps.ALARM_RANGE, 40)
        self._says("within forty tiles")


class TestTheManualOnWeapons(unittest.TestCase):
    """The second pass over the manual's numbers, on the combat page.

    §137 pinned thirteen claims and left "fifty-odd numeric sentences still
    unpinned -- the ones about combat timing, temperature, skill ladders and
    world generation." Ten more were put to the code here. Seven were already
    true; three were not, and all three were about weapons:

    * "A dagger swings half again as often as an axe" -- it swings *twice* as
      often. Half again is the ratio against a sword.
    * `AttackResult.cost`: "A maul is worth nearly two sword-blows of somebody
      else's time" -- it is worth one and a third.
    * "Against plate the five best weapons in the game are all blunt" -- the
      best of them is an edge-only halberd, and a great axe gets literally
      nothing through a breastplate.
    """

    def _fighter(self, skill=0):
        """A stated fighter. Cost depends on skill, so it has to be said."""
        from ascii_warriors.game.entity import make_creature

        f = make_creature(RNG("mw"), "human", faction="player")
        for sid in ("fighter", "sword", "axe", "mace", "hammer", "spear",
                    "dagger", "whip", "pike", "misc_weapon"):
            f.skills.set_level(sid, skill)
        return f

    def _cost(self, fighter, weapon, attack):
        """The cost of one named attack, not of a coin toss between them."""
        from ascii_warriors.game import combat

        return combat.attack_cost(fighter, weapon, attack)

    def _text(self):
        from ascii_warriors.ui import help_screen

        return " ".join(
            " ".join(getattr(help_screen, name).split())
            for name in ("FORTRESS_TEXT", "COMBAT_TEXT", "WORLD_TEXT",
                         "SURVIVAL_TEXT"))

    # -- how often a weapon swings ------------------------------------------ #

    def test_the_attack_sets_the_speed_not_the_weapon(self):
        """The rule four separate comments got wrong.

        `swing_time` is `prepare + recover` on the *attack*, against a
        `BASELINE_SWING` of 6. Untrained that is 66 for a stab or a lash, 100
        for a slash, 133 for a hack or a bash -- and a dagger and a sword
        carry the same two attacks at the same two prices.
        """
        from ascii_warriors.data import items as idata
        from ascii_warriors.game.item import make_item

        f = self._fighter(skill=0)
        by_attack = {}
        for wid, defn in sorted(idata.ITEMS.items()):
            if getattr(defn, "category", "") != "weapon":
                continue
            w = make_item(RNG("i"), wid, material="iron")
            if w.is_ranged:
                continue
            for a in w.attacks():
                by_attack.setdefault(a.name, set()).add(self._cost(f, w, a))
        for name, costs in by_attack.items():
            self.assertEqual(len(costs), 1,
                             "%s costs different amounts on different "
                             "weapons: %s" % (name, sorted(costs)))
        flat = {k: v.pop() for k, v in by_attack.items()}
        self.assertEqual(flat.get("stab"), 66, flat)
        self.assertEqual(flat.get("slash"), 100, flat)
        self.assertEqual(flat.get("hack"), 133, flat)
        self.assertEqual(flat.get("bash"), 133, flat)
        self._says("A stab or a lash takes two thirds of a standard action")

    def test_a_dagger_is_no_quicker_than_a_sword(self):
        """The belief that was in three comments and the manual."""
        from ascii_warriors.game.item import make_item

        f = self._fighter(skill=0)
        dagger = make_item(RNG("i"), "dagger", material="iron")
        sword = make_item(RNG("i"), "sword", material="iron")
        self.assertEqual(
            {a.name: self._cost(f, dagger, a) for a in dagger.attacks()},
            {a.name: self._cost(f, sword, a) for a in sword.attacks()},
            "a dagger and a sword no longer cost the same")
        self._says("A dagger is therefore no quicker than a sword")

    def test_weight_never_charges_a_human_and_does_charge_a_kobold(self):
        """The comments all reached for weight; weight is not what does it.

        `heft` is the weapon against `carry_capacity() * EASY_SWING`, and a
        strength-1008 human swings every melee weapon in the table freely --
        so `HEFT_PENALTY` never fires for the player at all. It is not dead:
        a kobold is charged for the same weapons. Pinned because §138 says so
        and because the first re-break of `HEFT_PENALTY` could not fail.
        """
        from ascii_warriors.data import items as idata
        from ascii_warriors.game import combat
        from ascii_warriors.game.entity import make_creature
        from ascii_warriors.game.item import make_item

        human = make_creature(RNG("mw"), "human", faction="player")
        kobold = make_creature(RNG("mk"), "kobold", faction="hostile")
        charged_human, charged_kobold = [], []
        for wid, defn in sorted(idata.ITEMS.items()):
            if getattr(defn, "category", "") != "weapon":
                continue
            w = make_item(RNG("i"), wid, material="iron")
            if w.is_ranged:
                continue
            if combat.heft(human, w) > 1.0:
                charged_human.append(wid)
            if combat.heft(kobold, w) > 1.0:
                charged_kobold.append(wid)
        self.assertEqual(charged_human, [],
                         "a human is now charged for %s" % charged_human)
        self.assertTrue(charged_kobold,
                        "nothing charges a kobold either; the rule is dead")

    def test_the_old_wrong_belief_is_gone_from_the_code(self):
        """It was written down three times in two files."""
        import inspect

        from ascii_warriors.game import combat

        src = inspect.getsource(combat)
        self.assertNotIn("a dagger swings half again as often as a sword", src)
        self.assertNotIn("A dagger is most of two blows to a sword's one", src)
        self.assertNotIn("nearly two sword-blows of somebody", src)

    def test_a_maul_against_both_of_a_sword_s_attacks(self):
        """"Nearly two sword-blows" was true of one attack and not the other.

        A maul bashes for 133. A sword slashes for 100 and stabs for 66, so
        the maul is a third again of the one and twice the other -- which is
        why the flat comparison had to go.
        """
        from ascii_warriors.game.item import make_item

        f = self._fighter(skill=0)
        maul = make_item(RNG("i"), "maul", material="iron")
        sword = make_item(RNG("i"), "sword", material="iron")
        bash = self._cost(f, maul, maul.attacks()[0])
        by_name = {a.name: self._cost(f, sword, a) for a in sword.attacks()}
        self.assertAlmostEqual(bash / float(by_name["slash"]), 1.33, delta=0.05)
        self.assertAlmostEqual(bash / float(by_name["stab"]), 2.0, delta=0.06)
        # This one lives in the code rather than the manual: it is the comment
        # on `AttackResult.cost` that used to say "nearly two sword-blows".
        import inspect

        from ascii_warriors.game import combat

        self.assertIn("a third again of a slash and twice a stab",
                      inspect.getsource(combat))

    # -- what gets through plate -------------------------------------------- #

    def test_what_actually_gets_through_a_breastplate(self):
        """Aimed at the armoured part, which is the whole of the claim.

        Counting every wound on a creature wearing four pieces gave the great
        axe first place -- because it was taking legs off, not defeating the
        plate. Aim at the upper body and the great axe scores zero.
        """
        from ascii_warriors.game import combat
        from ascii_warriors.game.item import make_item
        from ascii_warriors.game.entity import make_creature

        f = self._fighter()

        def through(wid, n=260):
            w = make_item(RNG("i"), wid, material="iron")
            total = 0.0
            for i in range(n):
                rng = RNG("t%s%d" % (wid, i))
                d = make_creature(rng, "human", faction="hostile")
                plate = make_item(rng, "breastplate", material="iron")
                d.inventory.add(plate)
                d.inventory.equip(plate)
                combat.melee_attack(f, d, weapon=w, rng=rng,
                                    target_part="upper_body")
                total += sum(wd.severity for p in d.body.parts.values()
                             for wd in p.wounds if p.id == "upper_body")
            return total / n

        axe = through("great_axe")
        self.assertEqual(axe, 0.0,
                         "a breastplate no longer stops a great axe: %.3f" % axe)
        halberd = through("halberd")
        sword = through("sword")
        self.assertGreater(halberd, sword,
                           "a point no longer beats an edge through plate")
        self.assertGreater(halberd, axe)
        self._says("A great axe scores exactly nothing")
        self._says("the halberd, the morningstar, the warhammer, the maul and "
                   "the spear")

    def test_the_halberd_is_edge_only(self):
        """Which is why "all blunt" was wrong rather than merely imprecise."""
        from ascii_warriors.game.item import make_item

        w = make_item(RNG("i"), "halberd", material="iron")
        self.assertEqual(sorted({a.kind for a in w.attacks()}), ["edge"])

    # -- the ones that were already true ------------------------------------ #

    def test_a_mace_is_two_bars_and_a_great_axe_is_five(self):
        from ascii_warriors.fortress import production

        rec = production.RECIPES
        self.assertIn(("BAR", 2), rec["iron_mace"].inputs)
        self.assertIn(("BAR", 5), rec["iron_greataxe"].inputs)
        self._says("a mace is two bars, a great axe is five")

    def test_you_start_with_three_bandages(self):
        from ascii_warriors.game.item import starting_kit

        kit = starting_kit(RNG("kit"), "human", "warrior")
        n = sum(getattr(i, "count", 1) for i in kit if i.def_id == "bandage")
        self.assertEqual(n, 3)
        self._says("You start with three bandages")

    def test_fifty_of_the_eighty_one_are_quicker_than_a_man(self):
        """Written into the manual by §133; still true."""
        from ascii_warriors.data import creatures as cd

        self.assertEqual(len(cd.CREATURES), 81)
        self.assertEqual(sum(1 for d in cd.CREATURES.values() if d.speed > 100),
                         50)
        self._says("Fifty of the eighty-one kinds of creature in the world are "
                   "quicker than a man on foot")

    def test_a_conviction_is_four_days_per_point_of_severity(self):
        from ascii_warriors.data.calendar import TICKS_PER_DAY
        from ascii_warriors.fortress import justice

        self.assertEqual(justice.JAIL_TICKS, TICKS_PER_DAY * 4)
        self.assertEqual(justice.CRIMES["murder"][1], 4)
        self._says("four days off the roster per point of severity")

    def test_treating_a_bite_halves_what_is_left(self):
        import inspect

        from ascii_warriors.game import venom

        self.assertIn("0.5 if dose.treated", inspect.getsource(venom))
        self._says("halve what is left of it")

    def _says(self, phrase):
        self.assertIn(phrase, self._text(),
                      "the manual no longer says %r" % phrase)
