"""The application shell: a stack of scenes over one terminal."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..engine import colors, keys
from ..engine.rng import RNG
from ..engine.screen import Screen
from ..engine.terminal import QuitSignal, Terminal

MIN_WIDTH = 72
MIN_HEIGHT = 22


class Scene:
    """One screen of the game."""

    #: Overlay scenes are drawn on top of the scene beneath them.
    overlay = False

    def __init__(self, app: "App") -> None:
        self.app = app
        self.done = False

    @property
    def game(self):
        """The active game, if there is one."""
        return self.app.game

    def on_enter(self) -> None:
        """Called when this scene becomes the top of the stack."""

    def on_exit(self) -> None:
        """Called when this scene is popped."""

    def draw(self, scr: Screen) -> None:
        """Render the scene."""
        raise NotImplementedError

    def handle(self, key: str) -> None:
        """React to one key press."""

    def tick(self) -> None:
        """Optional per-frame update for animated scenes."""


class App:
    """Owns the terminal, the screen buffer and the scene stack."""

    def __init__(
        self,
        term: Terminal,
        *,
        seed: Optional[str] = None,
        debug: bool = False,
        world_size: str = "medium",
        history_years: int = 120,
    ) -> None:
        self.term = term
        w, h = term.size
        self.screen = Screen(max(MIN_WIDTH, w), max(MIN_HEIGHT, h))
        self.screen.ascii_only = not term.unicode_glyphs
        self.game = None
        self.seed = seed
        self.debug = debug
        self.world_size = world_size
        self.history_years = history_years
        self.scenes: List[Scene] = []
        self.quit = False
        self.exit_code = 0
        self.rng = RNG(seed or "ascii-warriors")

    # -- scene stack ------------------------------------------------------- #

    def push(self, scene: Scene) -> None:
        """Put a scene on top of the stack."""
        self.scenes.append(scene)
        scene.on_enter()

    def pop(self) -> Optional[Scene]:
        """Remove the top scene."""
        if not self.scenes:
            return None
        scene = self.scenes.pop()
        scene.on_exit()
        if self.scenes:
            self.scenes[-1].on_enter()
        return scene

    def replace(self, scene: Scene) -> None:
        """Swap the top scene for another."""
        if self.scenes:
            old = self.scenes.pop()
            old.on_exit()
        self.push(scene)

    def reset_to(self, scene: Scene) -> None:
        """Clear the stack and start again with one scene."""
        while self.scenes:
            self.scenes.pop().on_exit()
        self.push(scene)

    @property
    def current(self) -> Optional[Scene]:
        """The scene currently receiving input."""
        return self.scenes[-1] if self.scenes else None

    # -- main loop --------------------------------------------------------- #

    def _resize(self) -> None:
        w, h = self.term.size
        w = max(MIN_WIDTH, w)
        h = max(MIN_HEIGHT, h)
        if (w, h) != (self.screen.width, self.screen.height):
            self.screen.resize(w, h)
            self.screen.ascii_only = not self.term.unicode_glyphs
            self.term.full_redraw()

    def draw(self) -> None:
        """Render the visible scenes and flush them to the terminal."""
        if not self.scenes:
            return
        # Find the deepest scene that paints a full background, then draw
        # everything above it so modal overlays keep their context.
        start = len(self.scenes) - 1
        while start > 0 and self.scenes[start].overlay:
            start -= 1
        self.screen.clear(colors.UI["bg"])
        for scene in self.scenes[start:]:
            scene.draw(self.screen)
        self.term.render(self.screen)

    def run(self) -> int:
        """Run until the player quits; returns a process exit code."""
        from .menus import MainMenu

        if not self.scenes:
            self.push(MainMenu(self))
        try:
            while not self.quit and self.scenes:
                if self.term.poll_resize():
                    self._resize()
                self.draw()
                scene = self.current
                if scene is None:
                    break
                key = self.term.read_key()
                if key is None:
                    continue
                if key == "C-l":
                    self.term.full_redraw()
                    continue
                scene.handle(key)
                scene.tick()
                while self.scenes and self.scenes[-1].done:
                    self.pop()
        except QuitSignal:
            # The headless driver ran out of scripted input; that is a clean exit.
            pass
        except KeyboardInterrupt:
            self.exit_code = 130
        return self.exit_code

    # -- helpers used by scenes -------------------------------------------- #

    def message(self, title: str, text: str) -> None:
        """Show a modal message."""
        from ..engine.widgets import message_box

        message_box(self.screen, self.term, title, text)

    def confirm(self, question: str) -> bool:
        """Ask a yes/no question."""
        from ..engine.widgets import confirm

        return confirm(self.screen, self.term, question)

    def quit_game(self) -> None:
        """Stop the main loop."""
        self.quit = True
