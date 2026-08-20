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
