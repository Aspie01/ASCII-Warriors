"""Choosing the world you are about to play in: generate one, or reopen one."""

from __future__ import annotations


from ..engine import colors, keys
from ..engine.rng import RNG
from ..engine.screen import Screen
from ..engine.widgets import (
    HOTKEY_INDENT, ListMenu, MenuItem, key_hint, prompt_string,
)
from ..world.worldgen import WORLD_SIZES, generate_world
from .app import Scene

SIZE_ORDER = ["pocket", "small", "medium", "large", "huge"]
HISTORY_OPTIONS = [20, 50, 100, 150, 250, 500]


class WorldGenScene(Scene):
    """Choose world parameters, then generate."""

    def __init__(self, app, mode: str = "adventure") -> None:
        super().__init__(app)
        #: ``"adventure"`` rolls a character next; ``"fortress"`` picks a site.
        self.mode = mode
        self.size = app.world_size if app.world_size in WORLD_SIZES else "medium"
        self.history = app.history_years
        self.seed_text = app.seed or ""
        self.status = ""
        self.progress = 0.0
        self.world = None
        self.generating = False

    def on_enter(self) -> None:
        from ..game import save as save_mod

        items = [
            MenuItem("World size", "size", hotkey="s"),
            MenuItem("Years of history", "history", hotkey="h"),
            MenuItem("Seed", "seed", hotkey="e"),
            MenuItem("Generate world", "go", hotkey="g"),
            MenuItem("Play in a world you already have", "old", hotkey="o",
                     enabled=bool(save_mod.list_worlds())),
            MenuItem("Back", "back", hotkey="q"),
        ]
        self.menu = ListMenu(items, per_page=8, auto_hotkeys=False)

    def draw(self, scr: Screen) -> None:
        """Draw the parameter form or the generation progress."""
        scr.frame(2, 1, scr.width - 4, scr.height - 3, title="Choose a world")
        if self.generating:
            self._draw_progress(scr)
            return
        y = 4
        scr.text(6, y, "The world is made once, and then it is the world.",
                 colors.UI["dim"])
        y += 2
        dim = WORLD_SIZES[self.size]
        rows = [
            ("World size", "%s (%dx%d)" % (self.size, dim, dim)),
            ("Years of history", str(self.history)),
            ("Seed", self.seed_text or "(random)"),
        ]
        for i, (label, value) in enumerate(rows):
            scr.text(6, y + i, "%-20s" % label, colors.UI["accent"])
            scr.text(28, y + i, value, colors.UI["fg"])
        y += len(rows) + 2
        self.menu.draw(scr, 6, y, 40, len(self.menu.items), show_desc=False)
        y += len(self.menu.items) + 2
        scr.text(6, y, "Bigger worlds and longer histories take longer to make",
                 colors.UI["dim"])
        scr.text(6, y + 1, "but give you more places to go and more to hear about.",
                 colors.UI["dim"])
        key_hint(scr, 4, scr.height - 3, [
            (keys.ENTER, "choose"), (keys.LEFT, "less"), (keys.RIGHT, "more"),
            (keys.ESC, "back"),
        ])

    def _draw_progress(self, scr: Screen) -> None:
        """Draw the generation progress bar."""
        cy = scr.height // 2
        scr.text_center(cy - 2, "Creating a world...", colors.UI["title"])
        scr.text_center(cy, self.status, colors.UI["fg"])
        bar_w = min(50, scr.width - 12)
        bx = (scr.width - bar_w) // 2
        filled = int(bar_w * self.progress)
        scr.put(bx - 1, cy + 2, "[", colors.UI["frame"])
        scr.put(bx + bar_w, cy + 2, "]", colors.UI["frame"])
        scr.fill(bx, cy + 2, filled, 1, "=", colors.UI["accent"])
        scr.fill(bx + filled, cy + 2, bar_w - filled, 1, "-", colors.UI["frame"])
        scr.text_center(cy + 4, "%d%%" % int(self.progress * 100), colors.UI["dim"])

    def handle(self, key: str) -> None:
        """Adjust parameters or start generating."""
        if self.generating:
            return
        if key in (keys.LEFT, keys.RIGHT, "h", "l"):
            delta = -1 if key in (keys.LEFT, "h") else 1
            choice = self.menu.selected_value
            if choice == "size":
                i = (SIZE_ORDER.index(self.size) + delta) % len(SIZE_ORDER)
                self.size = SIZE_ORDER[i]
            elif choice == "history":
                i = HISTORY_OPTIONS.index(self.history) \
                    if self.history in HISTORY_OPTIONS else 2
                self.history = HISTORY_OPTIONS[
                    (i + delta) % len(HISTORY_OPTIONS)
                ]
            return
        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result != "select":
            return
        choice = self.menu.selected_value
        if choice == "back":
            self.done = True
        elif choice == "seed":
            text = prompt_string(self.app.screen, self.app.term,
                                 "Seed:", self.seed_text, 40)
            if text is not None:
                self.seed_text = text
        elif choice == "size":
            i = (SIZE_ORDER.index(self.size) + 1) % len(SIZE_ORDER)
            self.size = SIZE_ORDER[i]
        elif choice == "history":
            i = HISTORY_OPTIONS.index(self.history) \
                if self.history in HISTORY_OPTIONS else 2
            self.history = HISTORY_OPTIONS[(i + 1) % len(HISTORY_OPTIONS)]
        elif choice == "old":
            self.app.push(WorldMenu(self.app, mode=self.mode))
        elif choice == "go":
            self._generate()

    def _generate(self) -> None:
        """Run world generation, repainting the progress bar as it goes."""
        self.generating = True
        seed_text = self.seed_text.strip()
        if not seed_text:
            import time

            seed_text = "%x" % (int(time.time() * 1000) & 0xFFFFFFFF)
            self.seed_text = seed_text
        rng = RNG(seed_text)

        def progress(label: str, frac: float) -> None:
            self.status = label
            self.progress = frac
            self.app.draw()

        world = generate_world(
            rng, size=self.size, history_years=self.history, progress=progress,
        )
        from ..game import save as save_mod

        # Written now rather than at the first save, because a world exists as
        # soon as it is made: quit before the first turn and it is still there
        # to come back to.
        try:
            save_mod.save_world(world)
        except OSError:  # pragma: no cover - disk failure
            pass
        self.app.rng = rng
        enter_world(self.app, world, rng, self.mode)


#: What each mode does with a world, for the world list's own wording.
MODE_VERBS = {
    "adventure": ("set out in", "set out"),
    "fortress": ("embark in", "embark"),
    "legends": ("read about", "read"),
}


def enter_world(app, world, rng, mode: str) -> None:
    """Hand a chosen world to whichever mode asked for it.

    The one place a world becomes a game, so a world that came off disk goes
    the same way as one that was made a moment ago.
    """
    if mode == "legends":
        from .legends_screen import LegendsScene

        app.replace(LegendsScene(app, world))
        return
    if mode == "fortress":
        from .fort.embark import EmbarkScene

        app.replace(EmbarkScene(app, world, rng))
        return
    from .charcreate import CharCreateScene

    app.replace(CharCreateScene(app, world, rng))


class WorldMenu(Scene):
    """The worlds on disk, and who was left in them.

    A world outlives the characters who play in it. This is the door back in:
    pick one and the next adventurer is rolled there, or the next fortress
    embarks there, in the world as the last character left it.
    """

    def __init__(self, app, mode: str = "adventure") -> None:
        super().__init__(app)
        self.mode = mode
        self.worlds = []
        self.menu = ListMenu([], per_page=12)
        self.error = ""

    def on_enter(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Re-read the save directory."""
        from ..game import save as save_mod

        self.worlds = save_mod.list_worlds()
        items = [
            MenuItem(save_mod.describe_world(m), m, hotkey=None)
            for m in self.worlds
        ]
        if not items:
            items = [MenuItem("(no worlds yet)", None, enabled=False)]
        self.menu.set_items(items)

    def draw(self, scr: Screen) -> None:
        """Draw the world list and what is waiting in the selected one."""
        what, verb = MODE_VERBS.get(self.mode, MODE_VERBS["adventure"])
        scr.frame(2, 1, scr.width - 4, scr.height - 3,
                  title="Choose a world to %s" % what)
        scr.text(4 + HOTKEY_INDENT, 3, "%-28s %-6s %-7s %-7s %s" % (
            "WORLD", "YEAR", "SITES", "LIVING", "WHO IS THERE"),
            colors.UI["accent"])
        rows = min(12, max(3, scr.height - 16))
        self.menu.draw(scr, 4, 5, scr.width - 8, rows, show_desc=False)
        self._draw_detail(scr, 5 + rows + 1)
        if self.error:
            scr.text(4, scr.height - 5, self.error, colors.UI["danger"])
        key_hint(scr, 4, scr.height - 3, [
            (keys.ENTER, verb), ("d", "delete"), (keys.ESC, "back"),
        ])

    def _draw_detail(self, scr: Screen, y: int) -> None:
        """What the last character left in the world under the cursor."""
        meta = self.menu.selected_value
        if not meta:
            return
        scr.text(4, y, "%s, year %s -- %s sites, %s living" % (
            meta.get("name", "?"), meta.get("year", "?"),
            meta.get("sites", "?"), meta.get("figures", "?")),
            colors.UI["accent2"])
        y += 1
        for name in (meta.get("retired") or [])[:4]:
            if y >= scr.height - 6:
                return
            scr.text(6, y, "%s settled here and is still alive." % name,
                     colors.UI["fg"])
            y += 1
        for name in (meta.get("built") or [])[:4]:
            if y >= scr.height - 6:
                return
            scr.text(6, y, "%s stands where you left it." % name,
                     colors.UI["fg"])
            y += 1
        if not (meta.get("retired") or meta.get("built")):
            scr.text(6, y, "Nobody has left anything here yet.",
                     colors.UI["dim"])

    def handle(self, key: str) -> None:
        """Open a world, delete one, or go back."""
        from ..game import save as save_mod

        if key == "d" and self.menu.selected_value:
            meta = self.menu.selected_value
            if self.app.confirm(
                    "Delete the world of %s? Everything in it goes with it."
                    % meta.get("name", "?")):
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
            world = save_mod.load_world(meta["path"])
        except Exception as exc:  # pragma: no cover - corrupt world file
            self.error = "Could not open that world: %s" % exc
            return
        rng = RNG(save_mod.continue_seed(world))
        if self.mode != "legends":
            self.app.rng = rng
        enter_world(self.app, world, rng, self.mode)
