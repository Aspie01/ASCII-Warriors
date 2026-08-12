"""World generation and character creation screens."""

from __future__ import annotations


from ..engine import colors, keys
from ..engine.rng import RNG
from ..engine.screen import Screen
from ..engine.widgets import ListMenu, MenuItem, key_hint, prompt_string
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
        items = [
            MenuItem("World size", "size", hotkey="s"),
            MenuItem("Years of history", "history", hotkey="h"),
            MenuItem("Seed", "seed", hotkey="e"),
            MenuItem("Generate world", "go", hotkey="g"),
            MenuItem("Back", "back", hotkey="q"),
        ]
        self.menu = ListMenu(items, per_page=8, auto_hotkeys=False)

    def draw(self, scr: Screen) -> None:
        """Draw the parameter form or the generation progress."""
        scr.frame(2, 1, scr.width - 4, scr.height - 3, title="Create a world")
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
        self.app.rng = rng
        if self.mode == "fortress":
            from .fort.embark import EmbarkScene

            self.app.replace(EmbarkScene(self.app, world, rng))
            return
        from .charcreate import CharCreateScene

        self.app.replace(CharCreateScene(self.app, world, rng))
