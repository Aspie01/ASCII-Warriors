"""Character creation."""

from __future__ import annotations

from typing import Dict, Tuple

from ..data import creatures as creature_data
from ..data import names as name_data
from ..engine import colors, keys
from ..engine.rng import RNG
from ..engine.screen import Screen
from ..engine.widgets import ListMenu, MenuItem, key_hint, prompt_string
from ..game.skills import SKILLS, level_name
from ..game.state import Game
from .app import Scene

# The table itself lives in `data/professions.py`, where the game can
# see it: `Game.new_game` applies it. See that module for why.
from ..data.professions import PROFESSION_ORDER, PROFESSIONS


class CharCreateScene(Scene):
    """Pick a race, a profession, a name and set out."""

    def __init__(self, app, world, rng: RNG) -> None:
        super().__init__(app)
        self.world = world
        self.rng = rng
        self.race = "dwarf"
        self.profession = "warrior"
        self.female = False
        self.name = ""
        self.preview = None
        self.stage = "race"

    def on_enter(self) -> None:
        self._build_menu()
        if not self.name:
            self._reroll_name()

    def _build_menu(self) -> None:
        items = [
            MenuItem("Race", "race", hotkey="r"),
            MenuItem("Profession", "prof", hotkey="p"),
            MenuItem("Sex", "sex", hotkey="s"),
            MenuItem("Name", "name", hotkey="n"),
            MenuItem("Reroll name", "reroll", hotkey="R"),
            MenuItem("Begin the adventure", "go", hotkey="g"),
            MenuItem("Back", "back", hotkey="q"),
        ]
        self.menu = ListMenu(items, per_page=10, auto_hotkeys=False)

    def _reroll_name(self) -> None:
        self.name = name_data.name_for_race(self.race, self.rng, self.female)

    def draw(self, scr: Screen) -> None:
        """Draw the character sheet preview alongside the choices."""
        scr.frame(2, 1, scr.width - 4, scr.height - 3, title="Create a character")
        left = 5
        right = max(left + 34, scr.width // 2 + 2)

        defn = creature_data.get(self.race)
        desc, skills = PROFESSIONS[self.profession]

        y = 3
        scr.text(left, y, "World: %s" % self.world.name, colors.UI["dim"])
        y += 2
        rows = [
            ("Race", "%s" % defn.name),
            ("Profession", self.profession),
            ("Sex", "female" if self.female else "male"),
            ("Name", self.name),
        ]
        for label, value in rows:
            scr.text(left, y, "%-12s" % label, colors.UI["accent"])
            scr.text(left + 13, y, value, colors.UI["fg"])
            y += 1
        y += 1
        self.menu.draw(scr, left, y, 34, len(self.menu.items), show_desc=False)

        # Right-hand preview.
        py = 3
        scr.text(right, py, defn.name.capitalize(), colors.UI["title"])
        py += 1
        py += scr.wrapped(right, py, scr.width - right - 4,
                          defn.description or "", colors.UI["dim"])
        py += 1
        scr.text(right, py, "Lifespan: %d-%d years" % defn.lifespan,
                 colors.UI["dim"])
        py += 2
        scr.text(right, py, "Profession: %s" % self.profession,
                 colors.UI["title"])
        py += 1
        py += scr.wrapped(right, py, scr.width - right - 4, desc, colors.UI["dim"])
        py += 1
        scr.text(right, py, "Starting skills", colors.UI["accent"])
        py += 1
        for sid, lv in sorted(skills.items(), key=lambda kv: -kv[1]):
            if py >= scr.height - 5:
                break
            sd = SKILLS.get(sid)
            if sd is None:
                continue
            scr.text(right + 2, py, "%-18s %s" % (sd.name, level_name(lv)),
                     colors.UI["fg"])
            py += 1

        key_hint(scr, 4, scr.height - 3, [
            (keys.LEFT, "prev"), (keys.RIGHT, "next"), (keys.ENTER, "choose"),
            (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Cycle options or start the game."""
        choice = self.menu.selected_value
        if key in (keys.LEFT, keys.RIGHT, "h", "l"):
            delta = -1 if key in (keys.LEFT, "h") else 1
            if choice == "race":
                races = list(creature_data.PLAYABLE_RACES)
                i = (races.index(self.race) + delta) % len(races)
                self.race = races[i]
                self._reroll_name()
            elif choice == "prof":
                i = (PROFESSION_ORDER.index(self.profession) + delta) \
                    % len(PROFESSION_ORDER)
                self.profession = PROFESSION_ORDER[i]
            elif choice == "sex":
                self.female = not self.female
                self._reroll_name()
            return

        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result != "select":
            return
        if choice == "back":
            self.done = True
        elif choice == "race":
            races = list(creature_data.PLAYABLE_RACES)
            self.race = races[(races.index(self.race) + 1) % len(races)]
            self._reroll_name()
        elif choice == "prof":
            i = (PROFESSION_ORDER.index(self.profession) + 1) % len(PROFESSION_ORDER)
            self.profession = PROFESSION_ORDER[i]
        elif choice == "sex":
            self.female = not self.female
            self._reroll_name()
        elif choice == "reroll":
            self._reroll_name()
        elif choice == "name":
            text = prompt_string(self.app.screen, self.app.term, "Name:",
                                 self.name, 32)
            if text:
                self.name = text
        elif choice == "go":
            self._start()

    def _start(self) -> None:
        """Build the game and hand over to the play screen."""
        _desc, skills = PROFESSIONS[self.profession]
        spec = {
            "race": self.race,
            "profession": self.profession,
            "female": self.female,
            "name": self.name,
            "skills": skills,
        }
        game = Game.new_game(self.world, spec, self.rng)
        self.app.game = game
        from .play_screen import PlayScene

        self.app.reset_to(PlayScene(self.app))
