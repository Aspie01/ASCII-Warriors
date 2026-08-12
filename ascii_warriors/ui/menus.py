"""Title screen, save browser and the in-game escape menu."""

from __future__ import annotations


from ..engine import colors, keys
from ..engine.screen import Screen
from ..engine.widgets import ListMenu, MenuItem, key_hint
from ..game import save as save_mod
from .app import Scene

TITLE_ART = [
    "  _   ___  ___ ___ ___   __      __             _              ",
    " /_\\ / __|/ __|_ _|_ _|  \\ \\    / /_ _ _ _ _ _ (_)___ _ _ ___  ",
    "/ _ \\\\__ \\ (__ | | | |    \\ \\/\\/ / _` | '_| '_|| / _ \\ '_(_-<  ",
    "/_/ \\_\\___/\\___|___|___|    \\_/\\_/\\__,_|_| |_|  |_\\___/_| /__/ ",
]

TAGLINE = "An ASCII adventure in the spirit of Dwarf Fortress"

QUOTES = [
    "Losing is fun.",
    "Strike the earth!",
    "The world does not wait for you.",
    "Every scar has a story, and the world remembers all of them.",
    "Urist McAdventurer has been struck down.",
    "Somewhere below, something very old is still awake.",
]


class MainMenu(Scene):
    """The title screen."""

    def on_enter(self) -> None:
        items = [
            MenuItem("New adventure", "new", hotkey="n",
                     desc="Generate a world and set out"),
            MenuItem("Continue", "load", hotkey="c",
                     desc="Load a saved adventure",
                     enabled=bool(save_mod.list_saves())),
            MenuItem("Legends", "legends", hotkey="l",
                     desc="Browse a saved world's history",
                     enabled=bool(save_mod.list_saves())),
            MenuItem("Help", "help", hotkey="?", desc="Controls and concepts"),
            MenuItem("Quit", "quit", hotkey="q", desc="Leave the mountainhome"),
        ]
        self.menu = ListMenu(items, per_page=8, auto_hotkeys=False)
        self.quote = self.app.rng.choice(QUOTES)

    def draw(self, scr: Screen) -> None:
        """Draw the title, art and menu."""
        scr.clear(colors.UI["bg"])
        top = max(1, scr.height // 2 - 10)
        for i, row in enumerate(TITLE_ART):
            scr.text_center(top + i, row, colors.UI["accent"])
        scr.text_center(top + len(TITLE_ART) + 1, TAGLINE, colors.UI["dim"])
        scr.text_center(top + len(TITLE_ART) + 2, '"%s"' % self.quote,
                        colors.UI["accent2"])

        mx = max(2, scr.width // 2 - 22)
        my = top + len(TITLE_ART) + 5
        scr.frame(mx - 2, my - 1, 46, len(self.menu.items) + 2)
        self.menu.draw(scr, mx, my, 42, len(self.menu.items), show_desc=False)

        for i, it in enumerate(self.menu.items):
            if it.desc:
                if i == self.menu.index:
                    scr.text_center(my + len(self.menu.items) + 2, it.desc,
                                    colors.UI["dim"])
        scr.text_center(scr.height - 2, "ASCII Warriors  -  MIT licensed",
                        colors.UI["dim"])

    def handle(self, key: str) -> None:
        """Run the chosen menu entry."""
        result = self.menu.handle(key)
        if result == "cancel":
            self.app.quit_game()
            return
        if result != "select":
            return
        choice = self.menu.selected_value
        if choice == "new":
            from .worldgen_screen import WorldGenScene

            self.app.push(WorldGenScene(self.app))
        elif choice == "load":
            self.app.push(SaveMenu(self.app, mode="load"))
        elif choice == "legends":
            self.app.push(SaveMenu(self.app, mode="legends"))
        elif choice == "help":
            from .help_screen import HelpScene

            self.app.push(HelpScene(self.app))
        elif choice == "quit":
            self.app.quit_game()


class SaveMenu(Scene):
    """Browse, load and delete saved games."""

    def __init__(self, app, mode: str = "load") -> None:
        super().__init__(app)
        self.mode = mode
        self.saves = []
        self.menu = ListMenu([], per_page=14)
        self.error = ""

    def on_enter(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Re-read the save directory."""
        self.saves = save_mod.list_saves()
        items = [
            MenuItem(save_mod.describe(m), m, hotkey=None) for m in self.saves
        ]
        if not items:
            items = [MenuItem("(no saved games)", None, enabled=False)]
        self.menu.set_items(items)

    def draw(self, scr: Screen) -> None:
        """Draw the save list."""
        title = "Load a saved adventure" if self.mode == "load" else \
            "Browse a world's legends"
        scr.frame(2, 1, scr.width - 4, scr.height - 3, title=title)
        scr.text(4, 3, "%-20s %-10s %-14s %-6s %s" % (
            "NAME", "RACE", "DATE", "STATE", "SAVED"), colors.UI["accent"])
        self.menu.draw(scr, 4, 5, scr.width - 8, scr.height - 10, show_desc=False)
        if self.error:
            scr.text(4, scr.height - 5, self.error, colors.UI["danger"])
        key_hint(scr, 4, scr.height - 3, [
            (keys.ENTER, "open"), ("d", "delete"), (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Load, delete or leave."""
        if key == "d" and self.menu.selected_value:
            meta = self.menu.selected_value
            if self.app.confirm("Delete the save for %s?" % meta.get("name", "?")):
                save_mod.delete_save(meta["path"])
                self.refresh()
            return
        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result != "select":
            return
        meta = self.menu.selected_value
        if not meta:
            return
        try:
            game = save_mod.load_game(meta["path"])
        except Exception as exc:  # pragma: no cover - corrupt save path
            self.error = "Could not load that save: %s" % exc
            return
        self.app.game = game
        if self.mode == "legends":
            from .legends_screen import LegendsScene

            self.app.replace(LegendsScene(self.app))
        else:
            from .play_screen import PlayScene

            self.app.reset_to(PlayScene(self.app))


class GameMenu(Scene):
    """The in-game escape menu."""

    overlay = True

    def on_enter(self) -> None:
        items = [
            MenuItem("Return to the game", "resume", hotkey="r"),
            MenuItem("Save", "save", hotkey="s"),
            MenuItem("Save and quit", "savequit", hotkey="Q"),
            MenuItem("Help", "help", hotkey="?"),
            MenuItem("Legends", "legends", hotkey="l"),
            MenuItem("Abandon this adventure", "abandon", hotkey="A"),
        ]
        self.menu = ListMenu(items, per_page=8, auto_hotkeys=False)

    def draw(self, scr: Screen) -> None:
        """Draw a small centred menu over the game."""
        scr.shade(0, 0, scr.width, scr.height, 0.45)
        w, h = 42, len(self.menu.items) + 4
        x, y = (scr.width - w) // 2, (scr.height - h) // 2
        scr.fill(x, y, w, h, " ", colors.UI["fg"], colors.UI["bg"])
        scr.frame(x, y, w, h, title="Paused")
        scr.box_shadow(x, y, w, h)
        self.menu.draw(scr, x + 2, y + 2, w - 4, h - 3, show_desc=False)

    def handle(self, key: str) -> None:
        """Act on the chosen entry."""
        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result != "select":
            return
        choice = self.menu.selected_value
        game = self.app.game
        if choice == "resume":
            self.done = True
        elif choice in ("save", "savequit"):
            if game is not None:
                try:
                    path = save_mod.save_game(game, game.player.name)
                    game.log.system("Saved to %s" % path.name)
                except Exception as exc:  # pragma: no cover - disk failure
                    self.app.message("Save failed", str(exc))
                    return
            if choice == "savequit":
                self.app.quit_game()
            else:
                self.done = True
        elif choice == "help":
            from .help_screen import HelpScene

            self.app.push(HelpScene(self.app))
        elif choice == "legends":
            from .legends_screen import LegendsScene

            self.app.push(LegendsScene(self.app))
        elif choice == "abandon":
            if self.app.confirm("Abandon this adventure? Unsaved progress is lost."):
                self.app.game = None
                self.app.reset_to(MainMenu(self.app))


class DeathScene(Scene):
    """The obituary shown when the player dies."""

    def on_enter(self) -> None:
        game = self.app.game
        if game is not None:
            save_mod.autosave(game)

    def draw(self, scr: Screen) -> None:
        """Draw the tombstone."""
        game = self.app.game
        scr.clear(colors.UI["bg"])
        y = max(2, scr.height // 2 - 9)
        scr.text_center(y, "Here lies", colors.UI["dim"])
        if game is None:
            return
        p = game.player
        scr.text_center(y + 2, p.full_title(), colors.UI["danger"])
        scr.text_center(y + 4, "%s" % game.death_message, colors.UI["warn"])
        scr.text_center(y + 6, "in the year %d, on the %s" % (
            game.time.year, game.time.date_str()), colors.UI["dim"])
        scr.text_center(y + 8, "%d foes fell to them" % len(p.kills),
                        colors.UI["fg"])
        best = p.skills.known()[:3]
        if best:
            from ..game.skills import SKILLS, level_name

            scr.text_center(y + 9, ", ".join(
                "%s %s" % (level_name(lv), SKILLS[sid].name) for sid, lv in best
            ), colors.UI["dim"])
        scr.text_center(y + 11, "Their name is now written in the legends of %s."
                        % game.world.name, colors.UI["accent2"])
        scr.text_center(scr.height - 3, "Press any key", colors.UI["dim"])

    def handle(self, key: str) -> None:
        """Return to the title screen."""
        self.app.game = None
        self.app.reset_to(MainMenu(self.app))
