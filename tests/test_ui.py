"""Tests that drive the real UI through a headless terminal."""

from __future__ import annotations

import os
import tempfile
import unittest

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
        scene.cx, scene.cy = site.wx, site.wy
        text = self.render(scene)
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
