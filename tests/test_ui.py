"""Tests that drive the real UI through a headless terminal."""

from __future__ import annotations

import collections
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

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


class TestARunYouCanReplay(unittest.TestCase):
    """`tools/fuzz.py` promised a replay it was not delivering.

    Its docstring says "Every run is seeded, so a failure can be replayed
    exactly". It was not: the run was a function of the seed *and* of the
    player's save folder, which the run itself wrote a world into. Measured on
    the same seed and the same source, adventure mode, 1500 keys:

        save folder empty                 -> 459 keys, four runs of four
        save folder held at 144 files     -> 447 keys, four runs of four
        save folder as the ritual left it -> 447 and 835, alternating

    One saved fortress is enough to do it -- 459 becomes 835 -- because a
    fortress on disk puts another entry on the title screen, and the fuzzer
    navigates that screen by counting keystrokes. So a `fuzz --mode fortress`
    run changed what the next `fuzz --mode adventure` run measured, and a
    failure could not be reproduced from the seed it was reported with.

    `tools.scratch_saves` is the one funnel every driver goes through now.
    """

    def setUp(self):
        self._old_save = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        self._old_xdg = os.environ.get("XDG_DATA_HOME")
        self._old_appdata = os.environ.get("APPDATA")
        # A "player's folder" of our own, and no override pointing away from
        # it: this is the state a driver runs in on somebody's machine.
        self._home = tempfile.mkdtemp()
        os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        os.environ["XDG_DATA_HOME"] = self._home
        os.environ["APPDATA"] = self._home

    def tearDown(self):
        for name, old in (("ASCII_WARRIORS_SAVE_DIR", self._old_save),
                          ("XDG_DATA_HOME", self._old_xdg),
                          ("APPDATA", self._old_appdata)):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old

    def _players_folder(self):
        """Where saves would land if a driver did not redirect them."""
        from ascii_warriors.game import save as save_mod

        old = os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        try:
            return save_mod.save_dir()
        finally:
            if old is not None:
                os.environ["ASCII_WARRIORS_SAVE_DIR"] = old

    def _files_in(self, path):
        return sorted(p.name for p in path.iterdir()) if path.exists() else []

    # -- the funnel ---------------------------------------------------------- #

    def test_it_redirects_the_save_directory(self):
        from ascii_warriors.game import save as save_mod
        import tools

        where = tools.scratch_saves()
        self.assertEqual(str(save_mod.save_dir()), where)
        self.assertNotEqual(save_mod.save_dir(), self._players_folder())

    def test_it_keeps_a_directory_somebody_already_chose(self):
        """Replaying a failure against a saved world has to stay possible."""
        import tools

        mine = tempfile.mkdtemp()
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = mine
        self.assertEqual(tools.scratch_saves(), mine)

    # -- and every driver goes through it ------------------------------------ #

    def _run_driver_untouched(self, run, argv):
        """Run a driver with no override set; return what it left behind."""
        folder = self._players_folder()
        before = self._files_in(folder)
        os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = run(argv)
        finally:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        return code, before, self._files_in(folder)

    def test_the_fuzzer_does_not_write_to_the_players_folder(self):
        from tools import fuzz

        code, before, after = self._run_driver_untouched(
            fuzz.run, ["--mode", "fortress", "--seed", "q", "--keys", "40",
                       "--size", "pocket", "--history", "5"])
        self.assertEqual(code, 0)
        self.assertEqual(before, after,
                         "the fuzzer saved into the player's own folder")

    def test_the_smoke_driver_does_not_write_to_the_players_folder(self):
        from tools import smoke

        code, before, after = self._run_driver_untouched(
            smoke.run, ["--mode", "fortress", "--quiet", "--size", "pocket",
                        "--history", "5"])
        self.assertEqual(code, 0)
        self.assertEqual(before, after,
                         "the smoke driver saved into the player's own folder")

    # -- the promise itself -------------------------------------------------- #

    def _stub_fortress_save(self, folder):
        """The smallest file `list_fortresses` will agree to list."""
        import gzip
        import json

        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "Stubhold.awf"
        payload = {"version": 1, "saved_at": 1,
                   "meta": {"name": "Stubhold", "world": "w", "dwarves": 7}}
        with gzip.open(str(path), "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_the_fortress_driver_redirects_before_it_plays(self):
        """`tools/fort.py` had no guard on this at all.

        Its own tests set a save directory in `setUp`, so removing the
        redirect from the driver left every one of them green -- which is how
        `fuzz` and `smoke` came to be missing it in the first place.
        """
        from tools import fort as driver

        self._assert_redirects_before_playing(driver, ["--seed", "t",
                                                       "--quiet"])

    def test_the_adventure_driver_redirects_before_it_plays(self):
        from tools import play as driver

        self._assert_redirects_before_playing(driver, ["--seed", "t"])

    def _assert_redirects_before_playing(self, driver, argv):
        """Stop the driver the moment it starts playing and see where it saves.

        Checked at that instant rather than by running the driver, because a
        seven-day fortress is a minute and a half and this needs to be a test
        somebody will keep running. What matters is the ordering: by the time
        there is a game to save, the saves already point somewhere else.
        """
        class Stop(Exception):
            pass

        seen = []
        real = driver.play

        def spy(*args, **kwargs):
            seen.append(os.environ.get("ASCII_WARRIORS_SAVE_DIR"))
            raise Stop

        players = self._players_folder()
        os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        driver.play = spy
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(Stop):
                    driver.main(argv)
        finally:
            driver.play = real
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)

        self.assertEqual(len(seen), 1)
        where = seen[0]
        self.assertIsNotNone(where, "it started playing with the player\'s "
                                    "own folder still selected")
        self.assertNotEqual(Path(where), players)

    def test_the_run_never_resolves_the_players_folder(self):
        """The promise, stated as the thing that has to be true for it.

        A run replays from its seed exactly when nothing outside the seed can
        reach it, and the only way the folder reached it was `save_dir()`. So
        this watches every call the run makes and asserts the player's folder
        is never among the answers.

        Asserted this way rather than by running the same seed twice and
        diffing the screens, because that comparison is not sensitive enough
        to be a guard: measured with the funnel removed, a saved fortress in
        the folder left the frames identical at 120, 300 and 600 keys and only
        told them apart over the full 1500-key run -- 459 keys against 835.
        A guard that needs a minute and a half to notice is one that gets
        turned off.
        """
        from ascii_warriors.game import save as save_mod
        from tools import fuzz

        players = self._players_folder()
        self._stub_fortress_save(players)
        seen = []
        real = save_mod.save_dir

        def spy():
            got = real()
            seen.append(got)
            return got

        os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        save_mod.save_dir = spy
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                fuzz.run(["--mode", "adventure", "--seed", "11",
                          "--keys", "120", "--size", "pocket",
                          "--history", "5"])
        finally:
            save_mod.save_dir = real
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)

        self.assertTrue(seen, "the run never touched the save layer at all")
        self.assertNotIn(players, seen,
                         "the run read the player\'s own save folder")


#: What `tools.play.play` hands back after a run that went well. The invariant
#: tests replace the run itself: what is under test is which of these numbers
#: the driver refuses to print OK over.
def _a_game():
    """A small real game, for driver tests that need a map to walk on."""
    from ascii_warriors.engine.rng import RNG
    from ascii_warriors.game.state import Game
    from ascii_warriors.world.worldgen import generate_world

    rng = RNG("driver")
    world = generate_world(rng.sub("w"), size="pocket", history_years=20)
    return Game.new_game(world, {"race": "dwarf", "profession": "warrior"}, rng)


def _a_creature(game, def_id="wolf"):
    """One hostile on the map, placed by the caller."""
    from ascii_warriors.game.entity import make_creature

    beast = make_creature(game.rng, def_id, faction="hostile", level=1)
    beast.wx, beast.wy = game.player.wx, game.player.wy
    game.creatures[beast.id] = beast
    return beast


_PLAY_RUN = {
    "turns": 230, "ticks": 109921, "dead": True, "cause": "bled to death",
    "peak": {"thirst": 22126, "hunger": 27447, "drowsy": 29075},
    "water_nearby": False, "dry_land_beside": False, "nowhere": [],
    "world_tiles": 4, "actions": {}, "ready_but_unpaid": 0,
    "quests_taken": 1, "quests_done": 0, "furthest": 40, "work": {},
    "gave_up": 0,
}


def _run_play(out, argv=("--seed", "t")):
    """Run `tools.play.main` over a canned result and return (code, output)."""
    from tools import play as driver

    real = driver.play
    driver.play = lambda *a, **k: out
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = driver.main(list(argv))
    finally:
        driver.play = real
    return code, buf.getvalue()


class TestTheKeysTheRunKeysAte(UITestBase):
    """Four things the game could do and the player could not reach.

    `PlayScene.handle` tests `keys.is_run_key(key)` near the top of its chain,
    and the diagonal run keys are `H J K L Y U B N`. Four branches further
    down tested `U`, `B`, `N` and `Y`, so they were dead code:

        U   disarm a trap you have found      printed in the help
        B   set fire to what is beside you    printed in the help
        N   gather the plants growing here    documented nowhere
        Y   fish, if you are standing by water   documented nowhere

    Pressing them ran the player diagonally instead. Two were advertised on
    the Controls page, which makes them the same shape as v3.93's alarm key --
    a control the player can read about and cannot use -- and the other two
    were a working action nobody could find.

    They are on `^`, `!`, `"` and `%` now: the glyphs of a trap, and of a
    shrub, and a mark for water, the same mnemonic `_` uses for an altar.
    """

    def _scene(self):
        from ascii_warriors.ui.play_screen import PlayScene

        scene = PlayScene(self.app)
        self.app.push(scene)
        return scene

    def _reaches(self, key, action_name):
        """True if pressing *key* gets as far as `actions.<action_name>`."""
        from ascii_warriors.game import actions

        scene = self._scene()
        called = []
        real = getattr(actions, action_name)

        def spy(*a, **kw):
            called.append(True)
            return real(*a, **kw)

        setattr(actions, action_name, spy)
        try:
            scene.handle(key)
        finally:
            setattr(actions, action_name, real)
        return bool(called)

    def test_the_four_actions_can_be_reached(self):
        for key, action in (("^", "disarm_trap"), ("!", "set_fire"),
                            ('"', "gather_here"), ("%", "fish_here")):
            self.assertTrue(
                self._reaches(key, action),
                "%r never reaches actions.%s" % (key, action))

    def test_no_advertised_action_sits_on_a_run_key(self):
        """The rule, rather than the four cases.

        Anything the Controls page offers as an *action* has to survive the
        run-key test that runs before it. Movement entries are exempt: they
        are the run keys, and are listed under their own heading.
        """
        from ascii_warriors.engine import keys as key_mod
        from ascii_warriors.ui import help_screen

        section = ""
        clashes = []
        for key, desc in help_screen.CONTROLS:
            if not key and desc:
                section = desc
                continue
            if section == "MOVEMENT" or not key or not desc:
                continue
            for part in key.replace("/", " ").replace(" or ", " ").split():
                if len(part) != 1:
                    continue
                if key_mod.is_run_key(part) or \
                        key_mod.direction_of(part) is not None:
                    clashes.append("%r (%s)" % (part, desc))
        self.assertEqual(clashes, [],
                         "the Controls page offers %s, and the run-key branch "
                         "in PlayScene.handle takes those keys first"
                         % "; ".join(clashes))

    def test_the_prose_names_keys_that_exist(self):
        """The Controls page is not the only place the manual binds keys.

        Rebinding the four keys and updating the Controls list left the
        fortress chapter still saying "Press N to pick what is growing",
        "Press Y to fish", "Press B with a lit torch in hand" and "press U to
        take it apart" -- four sentences naming keys that had just become dead
        again. The list-shaped guard above could not see them, because prose
        is not a list.

        The rule here is the weaker one that generalises: an instruction to
        press a key must name a key some screen actually handles.
        """
        import ast
        import inspect
        import re
        import textwrap

        from ascii_warriors.ui import help_screen, play_screen
        from ascii_warriors.ui.fort import fort_screen

        def handled(func):
            found = set()
            source = textwrap.dedent(inspect.getsource(func))
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Compare) \
                        and isinstance(node.left, ast.Name) \
                        and node.left.id == "key":
                    for cmp_to in node.comparators:
                        if isinstance(cmp_to, ast.Constant) \
                                and isinstance(cmp_to.value, str):
                            found.add(cmp_to.value)
                        elif isinstance(cmp_to, (ast.Tuple, ast.List, ast.Set)):
                            for element in cmp_to.elts:
                                if isinstance(element, ast.Constant) \
                                        and isinstance(element.value, str):
                                    found.add(element.value)
            return found

        # Only keys a screen tests *explicitly*. Folding in the Controls page
        # made this unable to fail: "press N to pick what is growing" passed
        # because `N` appears there as a diagonal run key, which is exactly
        # the confusion that produced the defect. A key being pressable is not
        # the same as a key doing the thing the sentence says.
        known = handled(play_screen.PlayScene.handle)
        known |= handled(fort_screen.FortScene.handle)

        # `press 'p'` is the manual's other way of writing it, so the quote is
        # skipped rather than read as the key.
        wrong = []
        for name in ("FORTRESS_TEXT", "COMBAT_TEXT", "WORLD_TEXT",
                     "SURVIVAL_TEXT"):
            text = getattr(help_screen, name)
            for match in re.finditer(r"[Pp]ress '?([!-~])'?", text):
                pressed = match.group(1)
                if pressed in ("'", '"'):
                    continue
                if pressed not in known:
                    wrong.append("%s: press %r" % (name, pressed))
        self.assertEqual(wrong, [],
                         "the manual tells the player to press keys no screen "
                         "handles: %s" % "; ".join(wrong))

    def test_every_action_the_screen_handles_is_written_down(self):
        """The other direction: a working key nobody can find out about.

        `X`, `V` and `_` were all handled and none of them appeared on the
        Controls page, so sharpening a blade, writing a book and praying at an
        altar were things you could only do by reading the source.
        """
        import ast
        import inspect
        import textwrap

        from ascii_warriors.ui import help_screen, play_screen

        source = textwrap.dedent(
            inspect.getsource(play_screen.PlayScene.handle))
        handled = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Compare) \
                    and isinstance(node.left, ast.Name) \
                    and node.left.id == "key":
                for cmp_to in node.comparators:
                    if isinstance(cmp_to, ast.Constant) \
                            and isinstance(cmp_to.value, str):
                        handled.add(cmp_to.value)
                    elif isinstance(cmp_to, (ast.Tuple, ast.List, ast.Set)):
                        for element in cmp_to.elts:
                            if isinstance(element, ast.Constant) \
                                    and isinstance(element.value, str):
                                handled.add(element.value)
        listed = set()
        for key, _desc in help_screen.CONTROLS:
            for part in key.replace("/", " ").replace(" or ", " ").split():
                if len(part) == 1:
                    listed.add(part)
        missing = sorted(k for k in handled - listed if len(k) == 1)
        self.assertEqual(missing, [],
                         "PlayScene handles %s and the Controls page never "
                         "mentions them" % missing)


class TestThePatienceNobodySpends(unittest.TestCase):
    """`LOCAL_PATIENCE` and `TRAVEL_PATIENCE` were declared and never read.

    Their docstrings say what they are for -- "how far the driver will walk
    inside one map before giving up on a target and doing something else" --
    and nothing consulted either of them, so the driver had no bound at all.

    Seed `long` is what that cost. Three thousand turns, one job taken, none
    finished, and `PLAY OK` printed over it:

        working  698     walking at the target
        blocked 1073     walking into things while idle

    The target was a `goblin_snatcher` one z-level above the player and
    diagonally adjacent, with **no path to it at a hundred thousand nodes**.
    The driver aimed at it eight hundred and eighty-five times. Every ritual
    since the driver existed has been printing OK over runs like that.
    """

    def _play(self, seed, turns=1500):
        from tools import play as driver

        return driver.play(seed, turns=turns)

    def test_it_gives_up_on_what_it_cannot_reach(self):
        """Built rather than found.

        This asked seed `long` for the answer, because that seed had an
        unreachable bounty on it. v4.00 fixed the map defect behind that --
        the adventurer was standing in a lake it could not climb out of -- and
        the seed now finishes two of three jobs and gives up on nothing, so
        the guard went red for the best possible reason and was measuring the
        wrong thing either way. A guard for "the driver stops chasing what it
        cannot catch" must not depend on the game still having somewhere
        uncatchable in it.
        """
        from tools import play as driver

        game = _a_game()
        quarry = _a_creature(game)
        why = collections.Counter()
        # Somewhere solid, on a level of its own: nothing walks to this.
        quarry.x, quarry.y, quarry.z = 1, 1, game.local.zmin
        game.local.set_tile(quarry.x, quarry.y, quarry.z, "rock_wall")

        # Halfway to the bound it is still worth chasing: the patience is a
        # patience, not a single failed step.
        for _ in range(driver.LOCAL_PATIENCE // 2):
            driver._swing_at(game, quarry, why, "hunted")
        self.assertTrue(driver._worth_chasing(game, quarry),
                        "wrote it off after %d tries, well inside the bound"
                        % (driver.LOCAL_PATIENCE // 2))
        self.assertEqual(why["gave up on something it could not reach"], 0)

        for _ in range(driver.LOCAL_PATIENCE):
            driver._swing_at(game, quarry, why, "hunted")
        self.assertFalse(driver._worth_chasing(game, quarry),
                         "chased it %d times and never wrote it off"
                         % (driver.LOCAL_PATIENCE + driver.LOCAL_PATIENCE // 2))
        self.assertEqual(why["gave up on something it could not reach"], 1,
                         "the reason should be counted once, not every step")

    def test_reaching_it_clears_the_count(self):
        """A long approach that works is not a failure.

        Without this the patience is a lifetime budget rather than a run of
        failures, and a driver that chased two hundred things successfully
        would refuse to chase the two hundred and first.
        """
        from tools import play as driver

        game = _a_game()
        quarry = _a_creature(game)
        quarry.x, quarry.y, quarry.z = 1, 1, game.local.zmin
        game.local.set_tile(quarry.x, quarry.y, quarry.z, "rock_wall")
        why = collections.Counter()
        for _ in range(driver.LOCAL_PATIENCE // 2):
            driver._swing_at(game, quarry, why, "hunted")
        self.assertTrue(driver._worth_chasing(game, quarry))

        # Now it is standing next to the player, and gets hit.
        player = game.player
        quarry.x, quarry.y, quarry.z = player.x + 1, player.y, player.z
        driver._swing_at(game, quarry, why, "hunted")
        self.assertEqual(driver._patience(game)["tries"].get(quarry.id), None,
                         "getting there did not clear the count")

    def test_giving_up_is_not_the_same_as_giving_up_on_everything(self):
        """A run that finishes its work must not be writing targets off.

        The bound has to be loose enough that an honest chase never hits it.
        Seeds that die fighting have chased plenty and given up on nothing.
        """
        for seed in ("play", "t", "hero", "quest"):
            out = self._play(seed)
            self.assertEqual(out["gave_up"], 0,
                             "%s wrote off a target on an ordinary run" % seed)

    def test_the_bound_is_looser_than_a_walk_across_the_map(self):
        """Or the driver gives up on things it was about to reach.

        A local map is 80x60, so a corner-to-corner walk is about 140 steps
        with diagonals. The bound has to sit above that.
        """
        from tools import play as driver

        self.assertGreater(driver.LOCAL_PATIENCE, 140)

    def test_a_run_that_achieved_nothing_is_not_reported_as_fine(self):
        """The alarm, on the canned result rather than a fifty-second run."""
        code, text = _run_play(dict(_PLAY_RUN, turns=3000, dead=False,
                                    gave_up=4, quests_done=0, quests_taken=1),
                               argv=("--seed", "t", "--turns", "3000"))
        self.assertEqual(code, 1, text)
        self.assertIn("finished none of the", text)

    def test_dying_is_a_reason_to_have_finished_nothing(self):
        """A player who was killed is not a player who was stuck."""
        code, text = _run_play(dict(_PLAY_RUN, turns=3000, dead=True,
                                    gave_up=4, quests_done=0, quests_taken=1),
                               argv=("--seed", "t", "--turns", "3000"))
        self.assertEqual(code, 0, text)

    def test_a_short_run_is_not_asked(self):
        """Giving up once inside two hundred turns is not a pathology."""
        from tools import play as driver

        code, text = _run_play(dict(_PLAY_RUN,
                                    turns=driver.LOCAL_PATIENCE, dead=False,
                                    gave_up=1, quests_done=0, quests_taken=1),
                               argv=("--seed", "t", "--turns",
                                     str(driver.LOCAL_PATIENCE)))
        self.assertEqual(code, 0, text)

    def test_finishing_the_work_clears_it(self):
        """Writing off one target on the way to finishing the job is fine."""
        code, text = _run_play(dict(_PLAY_RUN, turns=3000, dead=False,
                                    gave_up=4, quests_done=1, quests_taken=1),
                               argv=("--seed", "t", "--turns", "3000"))
        self.assertEqual(code, 0, text)


class TestTheStubThatDriftedOnceMore(unittest.TestCase):
    """`_PLAY_RUN` is the adventure side of a shape that has now drifted three
    times.

    v3.92 swept the fortress stub, `_DRIVER_RUN`, after it drifted twice --
    v3.80 added `militia`, v3.91 added `beds_added`, and each time five
    reporting tests died on a `KeyError` and six more followed. Its write-up
    said plainly that `tools/play.py` had the same arrangement, no guard at
    all, and had not been swept.

    v3.97 added `gave_up` and eight tests in this file died on
    `KeyError: 'gave_up'`, which is the third time and the first one that was
    predicted in writing.

    This asks the driver rather than a hand-kept list. `tools/fort.py` has a
    `REPORT_KEYS` tuple to compare against, which is itself a thing that can
    drift; `main` here reads its keys by name, so the names can be read
    straight out of it with `ast` and there is nothing in between to go stale.
    """

    def _keys_main_reads(self):
        import ast
        import inspect
        import textwrap

        from tools import play as driver

        tree = ast.parse(textwrap.dedent(inspect.getsource(driver.main)))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) \
                    and isinstance(node.value, ast.Name) \
                    and node.value.id == "out" \
                    and isinstance(node.slice, ast.Constant):
                found.add(node.slice.value)
            if isinstance(node, ast.Call) \
                    and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "get" \
                    and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "out" and node.args \
                    and isinstance(node.args[0], ast.Constant):
                found.add(node.args[0].value)
        return found

    def test_the_stub_carries_every_key_the_driver_reads(self):
        wanted = self._keys_main_reads()
        self.assertTrue(wanted, "read no keys out of `main` at all")
        missing = sorted(k for k in wanted if k not in _PLAY_RUN)
        self.assertEqual(missing, [],
                         "the canned result is missing %s, so every reporting "
                         "test in this file dies on KeyError" % missing)

    def test_the_driver_produces_every_key_it_reads(self):
        """The other direction: `play` must supply what `main` asks for."""
        import inspect

        from tools import play as driver

        source = inspect.getsource(driver.play)
        for key in sorted(self._keys_main_reads()):
            self.assertIn('"%s"' % key, source,
                          "`main` reads %r and `play` never sets it" % key)

    def test_the_stub_does_not_say_anything_twice(self):
        """Python keeps the last of a repeated key without a word about it."""
        import ast
        import collections

        with open(__file__) as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "_PLAY_RUN"
                       for t in node.targets):
                continue
            keys = [k.value for k in node.value.keys
                    if isinstance(k, ast.Constant)]
            twice = [k for k, n in collections.Counter(keys).items() if n > 1]
            self.assertEqual(twice, [],
                             "%s written more than once; Python keeps the "
                             "last and drops the rest" % twice)
            return
        self.fail("could not find the _PLAY_RUN literal to check")


class TestAnAlarmYouCanTrust(unittest.TestCase):
    """Two driver invariants that were measuring a proxy.

    `tools/play.py` asked whether peak thirst had passed 100 and called
    anything less "the clock is not running". How many ticks a turn buys
    depends on what the turn was: the world map moves in strides of a hundred,
    a wolf fight moves it by one. Seed `play` is jumped on the road and dies
    in 36 local turns, so 36 ticks pass and thirst reaches 36 -- and that seed
    printed PLAY PROBLEM in every run of the ritual from v3.71 to v3.81.

    `tools/fort.py` asked whether the *map* held any water when somebody died
    of thirst, and a map holds water in the sea, in sealed caverns and inside
    the rock as aquifer. Seed alpha breaches a magma pipe on day one; the
    dwarves who then died of thirst were called a defect in the game because
    360 cells of water existed somewhere on it.

    Neither alarm was wrong to exist -- between them they found the errand bug
    and the fleeing bug. They were asking the wrong question.
    """

    # -- the clock ----------------------------------------------------------- #

    def test_a_short_violent_life_is_not_a_stopped_clock(self):
        """Seed `play`, which the old floor failed in every ritual."""
        code, text = _run_play(dict(_PLAY_RUN, turns=36, ticks=36,
                                    peak={"thirst": 36, "hunger": 36,
                                          "drowsy": 13}))
        self.assertEqual(code, 0, text)
        self.assertIn("PLAY OK", text)

    def test_a_stopped_clock_is_still_caught(self):
        """The alarm keeps its teeth: time passing with needs frozen."""
        code, text = _run_play(dict(_PLAY_RUN, ticks=50000,
                                    peak={"thirst": 3, "hunger": 0,
                                          "drowsy": 0}))
        self.assertEqual(code, 1, text)
        self.assertIn("the clock is running and needs are not", text)

    def test_a_clock_that_never_moved_is_caught(self):
        code, text = _run_play(dict(_PLAY_RUN, ticks=0, turns=200))
        self.assertEqual(code, 1, text)
        self.assertIn("the clock never moved", text)

    def test_it_does_not_ask_before_there_was_time_to_answer(self):
        """Just under the threshold, thirst at a plausible one-a-tick."""
        from tools import play as driver

        ticks = driver.CLOCK_ENOUGH
        code, text = _run_play(dict(_PLAY_RUN, ticks=ticks, turns=20,
                                    peak={"thirst": 1, "hunger": 1,
                                          "drowsy": 1}))
        self.assertEqual(code, 0, text)

    def test_the_floor_is_clear_by_the_time_it_is_asked(self):
        """The two constants have to leave room for an honest run.

        Thirst climbs about a point a tick before anybody drinks, so by
        `CLOCK_ENOUGH` an honest run has that many points of it. The floor
        must sit well under that or the alarm fires on good runs.
        """
        from tools import play as driver

        self.assertLess(driver.CLOCK_FLOOR, driver.CLOCK_ENOUGH // 2)


class TestTheGatesThatNeverOpened(unittest.TestCase):
    """Two checks gated on the adventurer surviving, which none of them do.

        if out["world_tiles"] < 2 and not out["dead"]: ...
        if not out["quests_taken"] and not out["dead"]: ...

    Twelve seeds measured, twelve dead -- every adventurer in the ritual
    bleeds to death, most inside 300 turns of a 16000-turn budget. So `not
    dead` was a gate that never opened and neither check had ever run.

    Gated on opportunity instead: an adventurer killed on turn 36 has not
    failed to travel, and one that lived 300 turns on a single world square
    has. The seeds that died inside 70 turns saw one or two squares; the ones
    that lived 189 or more saw between 5 and 34.
    """

    def test_a_short_life_that_went_nowhere_is_not_a_defect(self):
        code, text = _run_play(dict(_PLAY_RUN, turns=36, ticks=36,
                                    world_tiles=1,
                                    peak={"thirst": 36, "hunger": 36,
                                          "drowsy": 13}))
        self.assertEqual(code, 0, text)

    def test_a_long_life_that_went_nowhere_is(self):
        code, text = _run_play(dict(_PLAY_RUN, turns=300, world_tiles=1))
        self.assertEqual(code, 1, text)
        self.assertIn("never left the world square", text)

    def test_a_short_life_with_no_work_is_not_a_defect(self):
        """Seed `iota`: nobody offered it anything, and it died on turn 43."""
        code, text = _run_play(dict(_PLAY_RUN, turns=43, ticks=43,
                                    quests_taken=0, world_tiles=1,
                                    peak={"thirst": 43, "hunger": 43,
                                          "drowsy": 20}))
        self.assertEqual(code, 0, text)

    def test_a_long_life_with_no_work_is(self):
        code, text = _run_play(dict(_PLAY_RUN, turns=300, quests_taken=0))
        self.assertEqual(code, 1, text)
        self.assertIn("nobody in the world had any work", text)

    def test_the_gate_sits_in_the_gap_the_seeds_left(self):
        """The threshold has to separate the short lives from the long ones.

        Measured: dead by turn 70 means one or two world squares seen, and
        alive at 189 means five or more. A gate inside that gap asks the
        question only of runs that had a chance to answer it.
        """
        from tools import play as driver

        self.assertGreater(driver.TRAVEL_ENOUGH, 70)
        self.assertLess(driver.TRAVEL_ENOUGH, 189)


class TestYouCannotOutrunAWolf(unittest.TestCase):
    """The driver backed away from things it could not possibly outrun.

    `Game._pace_of` has told the player since v3.73 that "it is much faster
    than you", and named the number in its own docstring: fifty of the
    eighty-one creature kinds are quicker than a man, and a wolf is 160 to a
    starting warrior's 102. At 1.57 actions to your one, every step of a
    retreat is a free attack handed over. `_run_away` had never asked.

    Measured over forty seeds, the same seeds both ways: the flee actions drop
    from 482 to 88, because almost nothing in the wilderness is slower than a
    man. Survival barely moves -- paired, 20 seeds longer, 9 shorter, 11
    unchanged, a mean of 328.7 turns against 311.9 -- so the hypothesis this
    started from, that fleeing was what killed the adventurer, is refuted.
    What is left is narrower and still true: 394 of those steps could not gain
    any ground, and a driver should not spend turns on a move that cannot
    work.
    """

    def setUp(self):
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = tempfile.mkdtemp()

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _game_and_foe(self, foe_id, seed="outrun"):
        from ascii_warriors.game.entity import make_creature

        rng = RNG(seed)
        world = generate_world(rng.sub("w"), size="pocket", history_years=20)
        game = Game.new_game(
            world, {"race": "human", "profession": "warrior"}, rng)
        p = game.player
        foe = make_creature(rng, foe_id, faction="hostile")
        foe.x, foe.y, foe.z = p.x + 1, p.y, p.z
        game.add_creature(foe)
        return game, foe

    def test_a_wolf_cannot_be_outrun(self):
        from tools import play as driver

        game, foe = self._game_and_foe("wolf")
        self.assertGreater(foe.effective_speed(),
                           game.player.effective_speed(),
                           "the fixture picked something that is not faster")
        self.assertFalse(driver._can_outrun(game, [foe]))

    def test_something_slower_can_be(self):
        """A zombie is 70 to a warrior's 102, and shambling is what it does."""
        from tools import play as driver

        game, foe = self._game_and_foe("zombie", seed="slow")
        self.assertLess(foe.effective_speed(),
                        game.player.effective_speed(),
                        "the fixture picked something that is not slower")
        self.assertTrue(driver._can_outrun(game, [foe]))

    def test_thirty_one_of_eighty_one_are_slow_enough_to_leave(self):
        """The gate must not be a gate that never opens -- see §143.

        Fifty of the eighty-one creature kinds are quicker than a man, which
        is the whole point; but thirty-one are not, so backing away is still a
        move the driver can make.
        """
        from ascii_warriors.data import creatures as cdata

        speeds = [d.speed for d in cdata.CREATURES.values()
                  if getattr(d, "speed", None)]
        self.assertEqual(len(speeds), 81)
        self.assertGreaterEqual(sum(1 for s in speeds if s < 102), 20)

    def test_one_fast_foe_in_a_crowd_is_enough(self):
        """Backing away from four only works if all four are slower."""
        from tools import play as driver

        game, wolf = self._game_and_foe("wolf")

        class Slow:
            @staticmethod
            def effective_speed():
                return 1

        self.assertFalse(driver._can_outrun(game, [Slow, Slow, wolf]))
        self.assertTrue(driver._can_outrun(game, [Slow, Slow]))

    def test_the_driver_does_not_back_away_from_a_wolf(self):
        """End to end: `_run_away` declines, so the turn goes to fighting."""
        from tools import play as driver

        game, foe = self._game_and_foe("wolf")
        p = game.player
        # Bleeding badly enough that the old rule would certainly have run.
        p.body.blood = p.body.max_blood * 0.3
        self.assertLess(p.body.blood_fraction(), driver.RUN_AWAY_AT)
        why = collections.Counter()
        self.assertIsNone(driver._run_away(game, why))
        self.assertEqual(why["ran"], 0)

    def test_surrounded_beats_the_speed_gate(self):
        """Two on you is a step worth taking whatever their speed.

        The blanket version of this gate broke a measured result: stepping
        diagonally out of a cross of four puts two of them behind you, and
        that gain has nothing to do with outpacing anybody. The full suite
        caught it -- `TestKnowingWhenToRun` in `test_systems` -- which is what
        the full suite is for.
        """
        from ascii_warriors.game.entity import make_creature
        from tools import play as driver

        game, first = self._game_and_foe("wolf", seed="crowd")
        p = game.player
        p.body.blood = p.body.max_blood * 0.3
        second = make_creature(game.rng, "wolf", faction="hostile")
        second.x, second.y, second.z = p.x - 1, p.y, p.z
        game.add_creature(second)
        self.assertFalse(driver._can_outrun(game, [first, second]))
        why = collections.Counter()
        self.assertIsNotNone(driver._run_away(game, why),
                             "it stood between two wolves rather than move")
        self.assertEqual(why["ran"], 1)

    def test_it_still_backs_away_from_something_slower(self):
        from tools import play as driver

        game, foe = self._game_and_foe("wolf", seed="slowfoe")
        p = game.player
        p.body.blood = p.body.max_blood * 0.3
        # Same wolf, made slower than the player rather than faster.
        foe.effective_speed = lambda: 1
        why = collections.Counter()
        self.assertIsNotNone(driver._run_away(game, why),
                             "it would not leave something it can outpace")
        self.assertEqual(why["ran"], 1)


class TestRederivingWhatCannotChange(unittest.TestCase):
    """The adventurer walked the whole map every turn to ask where water was.

    `_water_cells` visits every tile of every level -- 33792 of them on a
    small world's local map, 64 by 48 over eleven levels -- and where the
    water is is a fact about the terrain. §144.3 and §145.4 both recorded it
    and left it:

        5.41 ms a call, 1318 calls over forty seeds, 7.66 seconds
        1261 of those calls were on maps with no water at all
        seed s28 did it 1059 times in a life of 1107 turns

    `dwarf.py` learned this in `TAVERN_UNREACHABLE_BACKOFF`: one dwarf finding
    out the tavern is cut off is enough information for the whole fortress.
    """

    def setUp(self):
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = tempfile.mkdtemp()
        rng = RNG("rederive")
        world = generate_world(rng.sub("w"), size="pocket", history_years=20)
        self.game = Game.new_game(
            world, {"race": "human", "profession": "warrior"}, rng)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _count_scans(self, fn):
        """How many tiles the scan actually looks at while `fn` runs."""
        from ascii_warriors.world import tiles as tile_data

        seen = collections.Counter()
        real = tile_data.get

        def counting(tid):
            seen["tiles"] += 1
            return real(tid)

        tile_data.get = counting
        try:
            fn()
        finally:
            tile_data.get = real
        return seen["tiles"]

    def test_the_map_is_walked_once_not_once_a_turn(self):
        from tools import play as driver

        first = self._count_scans(lambda: driver._water_cells(self.game))
        self.assertGreater(first, 1000,
                           "the first scan did not walk the map at all")
        again = self._count_scans(lambda: driver._water_cells(self.game))
        self.assertLess(again, first // 10,
                        "it walked the map again: %d tiles" % again)

    def test_the_answer_is_the_same_answer(self):
        """Cheaper is only worth having if it is still right.

        On a map with known water in it, and comparing a cache *hit* against a
        fresh scan: the first version compared the first call -- which is a
        miss, and so never runs the line that answers from the cache at all --
        on a map that happened to have no water, where two empty lists agree
        whatever the code does.
        """
        from tools import play as driver

        class Pond:
            width, height = 4, 2
            levels = {0: ["floor", "water", "floor", "well",
                          "floor", "floor", "shallow_water", "floor"]}

        self.game.local = Pond()
        first = list(driver._water_cells(self.game))
        self.assertEqual(len(first), 3,
                         "the fixture did not put water on the map")
        hit = list(driver._water_cells(self.game))
        self.game._play_water_cells = None
        fresh = list(driver._water_cells(self.game))
        self.assertEqual(hit, fresh)
        self.assertEqual(hit, first)

    def test_walking_to_another_world_square_asks_again(self):
        from tools import play as driver

        driver._water_cells(self.game)
        self.game.player.wx += 1
        again = self._count_scans(lambda: driver._water_cells(self.game))
        self.assertGreater(again, 1000,
                           "it answered a new square from the old map")

    def test_a_freshly_generated_map_asks_again(self):
        """Same square, new map object: the cache must not answer for it."""
        from tools import play as driver

        driver._water_cells(self.game)

        class Elsewhere:
            width = 4
            height = 4
            levels = {0: ["floor"] * 16}

        self.game.local = Elsewhere()
        again = self._count_scans(lambda: driver._water_cells(self.game))
        self.assertGreater(again, 0,
                           "a new map was answered from the old one's scan")

    def test_finding_a_drink_still_works(self):
        """End to end, through the function the driver actually calls."""
        from tools import play as driver

        why = collections.Counter()
        driver._find_water(self.game, why)
        first = dict(why)
        why.clear()
        driver._find_water(self.game, why)
        self.assertEqual(dict(why), first,
                         "the cached second call reached a different verdict")


class TestWhatKillsAWarriorWhoCanFight(unittest.TestCase):
    """§148.5 asked what is left once the warrior can use his sword.

    Re-measured over the same forty seeds, everything doubled and nothing was
    solved: 13147 turns became 27182, one kill per 454 swings became one per
    237. But 22 of the 24 kills are still undead -- zombies and ghouls -- and
    37 of 40 still bleed to death.

    The reason is not the fighting. It is that there is never a moment to
    recover:

        wanted to rest        2418
        something in sight    2299   (95%)
        actually rested        115   (4.8%)

    And "in sight" is not a distant onlooker. Of the 1174 sampled moments it
    wanted to rest, the nearest hostile was **one tile away in 1073 of them**.
    It is standing in melee, being bitten, for almost every turn it is hurt.
    `hostiles_in_sight` is right to refuse -- you cannot bind a wound with a
    wolf on you -- and its own docstring already measured that nothing hostile
    is ever visible from further than six tiles anyway. The rule is not too
    coarse. The adventurer is simply never out of contact.

    These tests pin the rule rather than change it, because nothing here is
    the driver doing the wrong thing.

    One small thing the re-break turned up: `_rest_up`'s own
    `hostiles_in_sight()` check is redundant. `actions.rest` refuses on the
    same condition and returns `FREE`, so the driver's copy can be deleted
    without changing any behaviour -- which is exactly what deleting it did.
    Left in place, because saying the condition out loud where the decision is
    made is worth a duplicated call, but the load-bearing one is in the
    engine and that is where the guard bites.
    """

    def setUp(self):
        self._old = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
        os.environ["ASCII_WARRIORS_SAVE_DIR"] = tempfile.mkdtemp()
        rng = RNG("whatkills")
        world = generate_world(rng.sub("w"), size="pocket", history_years=20)
        self.game = Game.new_game(
            world, {"race": "human", "profession": "warrior"}, rng)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ASCII_WARRIORS_SAVE_DIR", None)
        else:
            os.environ["ASCII_WARRIORS_SAVE_DIR"] = self._old

    def _wolf_at(self, dx, dy):
        from ascii_warriors.game.entity import make_creature

        p = self.game.player
        foe = make_creature(self.game.rng, "wolf", faction="hostile")
        foe.x, foe.y, foe.z = p.x + dx, p.y + dy, p.z
        foe.wx, foe.wy = p.wx, p.wy
        self.game.add_creature(foe)
        self.game.update_fov()
        return foe

    def test_it_does_not_lie_down_with_a_wolf_on_it(self):
        from tools import play as driver

        p = self.game.player
        p.body.blood = p.body.max_blood * 0.5
        # Fed and watered, so the wolf is the only thing that can refuse it.
        # Without this the test passed with the wolf check deleted, because
        # `_rest_up` was declining over thirst instead.
        p.needs.thirst = 0
        p.needs.hunger = 0
        self.assertIsNotNone(driver._rest_up(self.game, collections.Counter()),
                             "the fixture cannot rest even with nothing near")
        p.body.blood = p.body.max_blood * 0.5
        p.needs.thirst = 0
        p.needs.hunger = 0
        self._wolf_at(1, 0)
        why = collections.Counter()
        self.assertIsNone(driver._rest_up(self.game, why),
                          "it lay down to rest while being bitten")

    def test_it_rests_once_there_is_nothing_watching(self):
        from tools import play as driver

        p = self.game.player
        p.body.blood = p.body.max_blood * 0.5
        p.needs.thirst = 0
        p.needs.hunger = 0
        self.game.update_fov()
        why = collections.Counter()
        self.assertIsNotNone(driver._rest_up(self.game, why),
                             "it would not rest with the field empty")
        self.assertEqual(why["rested"], 1)

    # There was a third test here, duelling a trained warrior against a
    # novice to pin §148's gain. It is gone on purpose. Twelve duels at a win
    # rate around a quarter is a coin flip: the same comparison gave 6 wins
    # against 1 at twenty samples with one set of seeds, and 0 against 1 at
    # twelve with another. A guard whose verdict is a sample is worse than no
    # guard, and the gain is already pinned deterministically by
    # `TestAWarriorWhoCanUseASword` in `test_game.py`, which asserts the
    # skills themselves rather than what they win.
