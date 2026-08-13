"""The fortress view: the screen fortress mode is played on.

Time runs by itself here. The player watches, pauses, paints designations and
queues orders; the dwarves do the rest, or fail to.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import MenuItem, choose, key_hint, popup
from ...fortress import sim
from ...fortress.designations import KINDS as DESIGNATION_KINDS
from ..app import Scene
from . import render
from .sidebar import LOG_HEIGHT, SIDEBAR_WIDTH, draw_log, draw_sidebar, draw_status_line

Cell = Tuple[int, int, int]

#: Simulation steps run per frame at each speed setting.
SPEEDS: Tuple[int, ...] = (1, 3, 10, 40)

#: Fortress mode moves a camera, not a character, so the vi keys stay free for
#: commands and scrolling lives on the arrows and the numpad, as it does in
#: Dwarf Fortress itself.
SCROLL_KEYS = {
    keys.LEFT: (-1, 0), keys.RIGHT: (1, 0),
    keys.UP: (0, -1), keys.DOWN: (0, 1),
    "4": (-1, 0), "6": (1, 0), "8": (0, -1), "2": (0, 1),
    "7": (-1, -1), "9": (1, -1), "1": (-1, 1), "3": (1, 1),
}

#: Keys that scroll a screenful at a time.
FAST_SCROLL = {
    keys.PGUP: (0, -12), keys.PGDN: (0, 12),
    keys.HOME: (-20, 0), keys.END: (20, 0),
}


def scroll_delta(key: str) -> Optional[Tuple[int, int]]:
    """How far a key scrolls the view, or ``None`` if it is not a scroll key."""
    if key in SCROLL_KEYS:
        return SCROLL_KEYS[key]
    return FAST_SCROLL.get(key)


class FortScene(Scene):
    """The main fortress screen."""

    realtime = True
    frame_time = 0.06

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort
        self.cam_x = 0
        self.cam_y = 0
        self.cursor: Optional[Cell] = None
        self.follow = True
        self._centre_on_dwarves()

    # -- camera ------------------------------------------------------------ #

    def _centre_on_dwarves(self) -> None:
        """Point the camera at wherever most of the fortress is."""
        dwarves = self.fort.dwarves()
        if not dwarves:
            return
        self.cam_x = sum(d.x for d in dwarves) // len(dwarves) - 30
        self.cam_y = sum(d.y for d in dwarves) // len(dwarves) - 14
        self.fort.z = dwarves[0].z

    def _layout(self, scr: Screen) -> Tuple[int, int, int, int]:
        sidebar = SIDEBAR_WIDTH if scr.width >= 88 else 0
        map_w = scr.width - sidebar - (2 if sidebar else 0)
        map_h = scr.height - LOG_HEIGHT - 1
        return (0, 1, max(10, map_w), max(5, map_h))

    def scroll(self, dx: int, dy: int, scr_w: int = 0, scr_h: int = 0) -> None:
        """Move the view."""
        self.cam_x += dx
        self.cam_y += dy
        self.follow = False

    # -- drawing ----------------------------------------------------------- #

    def draw(self, scr: Screen) -> None:
        """Render the fortress and its furniture."""
        fort = self.fort
        mx, my, mw, mh = self._layout(scr)
        self.cam_x, self.cam_y = render.clamp_camera(
            fort, self.cam_x, self.cam_y, mw, mh)
        draw_status_line(scr, 0, 0, scr.width, fort)
        render.draw_map(scr, fort, mx, my, mw, mh, self.cam_x, self.cam_y,
                        cursor=self.cursor)
        if scr.width >= 88:
            draw_sidebar(scr, scr.width - SIDEBAR_WIDTH + 1, 1,
                         SIDEBAR_WIDTH - 1, scr.height - LOG_HEIGHT - 1, fort)
        draw_log(scr, 0, scr.height - LOG_HEIGHT, scr.width, LOG_HEIGHT, fort)

    # -- simulation -------------------------------------------------------- #

    def tick(self) -> None:
        """Advance the fortress if time is running."""
        fort = self.fort
        if fort.paused or fort.lost:
            return
        for _ in range(SPEEDS[min(fort.speed - 1, len(SPEEDS) - 1)]):
            sim.step(fort)
            if fort.lost:
                fort.paused = True
                self.app.push(FortEndScene(self.app, fort))
                return

    # -- input ------------------------------------------------------------- #

    def handle(self, key: str) -> None:
        """Dispatch one key press."""
        fort = self.fort
        delta = scroll_delta(key)
        if delta is not None:
            self.scroll(*delta)
            return

        if key in (keys.SPACE, "."):
            fort.paused = not fort.paused
        elif key in ("+", "="):
            fort.speed = min(len(SPEEDS), fort.speed + 1)
        elif key == "-":
            fort.speed = max(1, fort.speed - 1)
        elif key in (">", ")"):
            fort.z = max(fort.local.zmin, fort.z - 1)
        elif key in ("<", "("):
            fort.z = min(fort.local.zmax, fort.z + 1)
        elif key == "d":
            from .designate import DesignateScene

            self.app.push(DesignateScene(self.app, self))
        elif key == "b":
            from .build_menu import BuildScene

            self.app.push(BuildScene(self.app, self))
        elif key == "p":
            from .build_menu import StockpileScene

            self.app.push(StockpileScene(self.app, self))
        elif key == "u":
            from .units import UnitsScene

            self.app.push(UnitsScene(self.app, fort))
        elif key == "h":
            from .health import HealthScene

            self.app.push(HealthScene(self.app, fort))
        elif key == "m":
            from .military_screen import MilitaryScene

            self.app.push(MilitaryScene(self.app, fort))
        elif key == "L":
            from .levers import LeverScene

            self.app.push(LeverScene(self.app, fort))
        elif key == "c":
            from .justice_screen import JusticeScene

            self.app.push(JusticeScene(self.app, fort))
        elif key == "w":
            from .build_menu import BurrowScene

            self.app.push(BurrowScene(self.app, self))
        elif key == "n":
            from .build_menu import PastureScene

            self.app.push(PastureScene(self.app, self))
        elif key == "j":
            self._job_summary()
        elif key == "z":
            from .stocks import StocksScene

            self.app.push(StocksScene(self.app, fort))
        elif key == "o":
            from .orders import pick_workshop

            pick_workshop(self.app, fort)
        elif key == "t":
            from .trade_screen import open_trade

            open_trade(self.app, fort)
        elif key == "k":
            self._look()
        elif key == "?":
            self._help()
        elif key == keys.ESC:
            self._menu()

    # -- panels ------------------------------------------------------------ #

    def _job_summary(self) -> None:
        """What the fortress is working on, in one list."""
        fort = self.fort
        rows = fort.jobs.summary()
        if not rows:
            self.app.message("Jobs", "Nothing is outstanding.")
            return
        from ...fortress.jobs import JOB_LABELS

        lines = ["%-24s %4d" % (JOB_LABELS.get(k, (k.title(), None))[0], n)
                 for k, n in rows]
        popup(self.app.screen, self.app.term, lines, title="Jobs outstanding")

    def _look(self) -> None:
        """Describe whatever is under the cursor."""
        fort = self.fort
        mx, my, mw, mh = self._layout(self.app.screen)
        cx = self.cam_x + mw // 2
        cy = self.cam_y + mh // 2
        cell = (cx, cy, fort.z)
        from ...world import tiles as tile_data

        name = tile_data.get(fort.local.tile(*cell)).name
        vein = fort.local.veins.get(cell)
        if vein:
            # "an ore vein" tells you nothing; "a native gold vein" is a plan.
            from ...data import materials as mat_data

            name = "%s %s" % (mat_data.get(vein).adjective, name)
        lines: List = [Frag(name, colors.UI["title"])]
        art = fort.engravings.get(cell)
        if art is not None:
            lines.append(Frag(art.describe(), colors.UI["accent2"]))
        if fort.magma.at(*cell):
            lines.append(Frag("magma, %d deep" % fort.magma.at(*cell),
                              colors.Color(240, 120, 50)))
        elif fort.water.at(*cell):
            lines.append(Frag("water, %d deep" % fort.water.at(*cell),
                              colors.Color(120, 175, 225)))
        b = fort.building_at(*cell)
        if b is not None:
            lines.append("%s (%s)" % (
                b.name, "built" if b.built else "planned"))
        pile = fort.stockpile_at(*cell)
        if pile is not None:
            lines.append("%s stockpile" % pile.kind)
        des = fort.designations.get(*cell)
        if des:
            lines.append("designated: %s" % DESIGNATION_KINDS[des].name)
        for item in fort.items_at(*cell):
            lines.append(item.name())
        c = fort.creature_at(*cell)
        if c is not None:
            lines.append(Frag(c.display_name(), colors.UI["accent"]))
        popup(self.app.screen, self.app.term, lines,
              title="At %d, %d, %+d" % cell)

    def _help(self) -> None:
        """The key list."""
        popup(self.app.screen, self.app.term, HELP_LINES,
              title="Fortress mode", width=64)

    def _menu(self) -> None:
        """Pause and open the game menu."""
        self.fort.paused = True
        items = [
            MenuItem("Resume", "resume"),
            MenuItem("Save fortress", "save"),
            MenuItem("Help", "help"),
            MenuItem("Abandon the fortress", "abandon"),
            MenuItem("Save and quit to menu", "quit"),
        ]
        choice = choose(self.app.screen, self.app.term, "Fortress", items)
        if choice == "save":
            self._save()
        elif choice == "help":
            self._help()
        elif choice == "abandon":
            if self.app.confirm("Abandon %s? Losing is fun." % self.fort.name):
                self.fort.lost = True
                self.fort.loss_reason = "abandoned"
                sim.record_fall(self.fort, abandoned=True)
                self.app.push(FortEndScene(self.app, self.fort))
        elif choice == "quit":
            self._save()
            from ..menus import MainMenu

            self.app.reset_to(MainMenu(self.app))

    def _save(self) -> None:
        """Write the fortress to disk."""
        from ...game import save

        try:
            path = save.save_fortress(self.fort)
        except OSError as exc:
            self.app.message("Save failed", str(exc))
            return
        self.fort.log.system("Saved to %s." % path.name)


HELP_LINES: Tuple[str, ...] = (
    "Space    pause and unpause time",
    "+ -      faster, slower",
    "< >      up and down a level",
    "arrows   scroll the view (PgUp/PgDn/Home/End to scroll fast)",
    "",
    "d        designate: dig, channel, stairs, chop, smooth",
    "b        build a workshop, furniture, wall or trap",
    "p        place a stockpile",
    "o        queue work orders at a workshop",
    "",
    "m        the militia: raise squads, arm them, order them about",
    "h        health: who is hurt and who can treat them",
    "c        crime: the sheriff's book, trials and pardons",
    "L        levers: link them to gates and pull them",
    "w        mark the safe burrow civilians retreat into",
    "n        paint a pasture for the livestock",
    "u        units: who is here and what they are doing",
    "z        stocks: everything the fortress owns",
    "j        jobs outstanding",
    "k        look at the middle of the view",
    "t        trade with the caravan, when one is here",
    "",
    "Esc      menu, save, abandon",
    "",
    "Your dwarves will not dig without a mining designation, will",
    "not eat what they cannot reach, and will not brew without a",
    "still. Everything else they work out themselves.",
)


class FortEndScene(Scene):
    """The screen you get when it is over."""

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort

    def draw(self, scr: Screen) -> None:
        """The epitaph."""
        fort = self.fort
        scr.clear(colors.UI["bg"])
        y = max(2, scr.height // 2 - 8)
        scr.text_center(y, fort.name, colors.UI["title"])
        y += 2
        scr.text_center(y, "founded %d, fell %d" % (fort.year_founded,
                                                    fort.time.year),
                        colors.UI["dim"])
        y += 2
        scr.text_center(y, fort.loss_reason or "abandoned",
                        colors.UI["danger"])
        y += 2
        stats = [
            "Dwarves who lived here: %d" % len(fort.creatures),
            "Wealth at the end: %d" % sim.appraise(fort),
            "Migrant waves: %d" % fort.migrant_waves,
            "Sieges survived: %d" % max(0, fort.siege_count - 1),
            "Artifacts made: %d" % len(fort.artifacts),
        ]
        for line in stats:
            scr.text_center(y, line, colors.UI["fg"])
            y += 1
        y += 1
        for art in fort.artifacts[:6]:
            scr.text_center(y, "%s, a %s" % (art["name"], art["item"]),
                            colors.MAGIC)
            y += 1
        y += 2
        scr.text_center(y, "Losing is fun.", colors.UI["accent"])
        y += 2
        scr.text_center(
            y, "%s stands on the world map now, exactly as you left it."
            % fort.name, colors.UI["dim"])
        key_hint(scr, 2, scr.height - 2, [
            ("a", "walk into it as an adventurer"),
            (keys.ENTER, "back to the menu"),
        ])

    def handle(self, key: str) -> None:
        """Return to the menu, or take up the story from the other side."""
        if key == "a":
            self._become_adventurer()
            return
        from ..menus import MainMenu

        self.app.reset_to(MainMenu(self.app))

    def _become_adventurer(self) -> None:
        """Roll a character in this world, who can go and find the ruins."""
        from ...fortress import sim as sim_mod
        from ..charcreate import CharCreateScene

        fort = self.fort
        if not fort.recorded:
            sim_mod.record_fall(fort, abandoned=fort.loss_reason == "abandoned")
        self.app.reset_to(CharCreateScene(self.app, fort.world, fort.rng))
