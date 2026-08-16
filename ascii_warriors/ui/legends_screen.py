"""The legends viewer."""

from __future__ import annotations

from typing import List, Optional

from ..engine import colors, keys
from ..engine.screen import Frag, Screen
from ..engine.widgets import (
    ListMenu, MenuItem, Tabs, key_hint, prompt_string, scroll_view,
)
from ..world import legends
from .app import Scene

TABS = ["Overview", "Figures", "Sites", "Civilizations", "Artifacts",
        "Art", "Gods", "Events"]


class LegendsScene(Scene):
    """Browse everything the world remembers."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.tabs = Tabs(TABS)
        self.menu = ListMenu([], per_page=20)
        self.offset = 0
        self.detail: Optional[List[Frag]] = None
        self.search_text = ""

    @property
    def world(self):
        """The world being browsed."""
        return self.app.game.world if self.app.game else None

    def on_enter(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the list for the active tab."""
        world = self.world
        if world is None:
            self.done = True
            return
        idx = self.tabs.index
        items: List[MenuItem] = []
        needle = self.search_text.lower()

        if idx == 1:
            figs = sorted(
                world.figures.values(),
                key=lambda f: (-len(f.flags), -f.stats.get("prowess", 0), f.name),
            )
            for f in figs:
                if needle and needle not in f.name.lower():
                    continue
                colour = (colors.UI["danger"] if "monster" in f.flags else
                          colors.MAGIC if "necromancer" in f.flags else
                          colors.UI["accent"] if "legendary" in f.flags else
                          colors.UI["fg"])
                items.append(MenuItem([Frag(f.summary(), colour)], ("figure", f.id)))
        elif idx == 2:
            for s in sorted(world.sites, key=lambda s: (-s.population, s.name)):
                if needle and needle not in s.name.lower():
                    continue
                colour = colors.UI["dim"] if s.is_ruin else colors.UI["fg"]
                items.append(MenuItem(
                    [Frag("%-30s %-16s pop %-6d %s" % (
                        s.name[:30], s.kind_name, s.population,
                        "(ruins)" if s.is_ruin else ""), colour)],
                    ("site", s.id)))
        elif idx == 3:
            for c in world.civs:
                if needle and needle not in c.name.lower():
                    continue
                items.append(MenuItem(
                    "%-34s %-8s %d sites" % (c.name[:34], c.race, len(c.sites)),
                    ("civ", c.id)))
        elif idx == 4:
            for a in world.artifacts:
                if needle and needle not in a.name.lower():
                    continue
                items.append(MenuItem(
                    [Frag("%-28s %s" % (a.name[:28], a.description[:40]),
                          colors.MAGIC)],
                    ("artifact", a.id)))
        elif idx == 5:
            from ..world import artforms

            for f in sorted(artforms.forms(world),
                            key=lambda f: (f.kind, f.name)):
                if needle and needle not in f.name.lower():
                    continue
                items.append(MenuItem(
                    [Frag(artforms.summary(world, f), colors.UI["accent2"])],
                    ("form", f.id)))
        elif idx == 6:
            from ..world import religion

            for g in sorted(getattr(world, "gods", []),
                            key=lambda g: (g.spheres[:1], g.name)):
                if needle and needle not in g.name.lower():
                    continue
                items.append(MenuItem(
                    [Frag(g.summary(), colors.UI["accent2"])],
                    ("deity", g.id)))
        elif idx == 7:
            for e in reversed(world.events[-500:]):
                if needle and needle not in e.text.lower():
                    continue
                items.append(MenuItem(e.describe(world), ("event", e.id)))

        if not items and idx > 0:
            items = [MenuItem("(nothing found)", None, enabled=False)]
        self.menu.set_items(items)
        self.detail = None
        self.offset = 0

    def draw(self, scr: Screen) -> None:
        """Draw the tab strip, list and detail pane."""
        world = self.world
        if world is None:
            return
        scr.frame(0, 0, scr.width, scr.height - 1,
                  title="Legends of %s" % world.name)
        self.tabs.draw(scr, 2, 1, scr.width - 4)
        if self.search_text:
            scr.text_right(scr.width - 2, 1, "filter: %s" % self.search_text,
                           colors.UI["accent"])

        if self.tabs.index == 0:
            lines = legends.world_summary(world)
            self.offset = scroll_view(scr, 2, 3, scr.width - 4, scr.height - 6,
                                      lines, self.offset)
        elif self.detail is not None:
            self.offset = scroll_view(scr, 2, 3, scr.width - 4, scr.height - 6,
                                      self.detail, self.offset)
        else:
            self.menu.draw(scr, 2, 3, scr.width - 4, scr.height - 6,
                           show_desc=False)

        hints = [(keys.TAB, "tab"), ("jk", "scroll"), (keys.ESC, "back")]
        if self.tabs.index > 0:
            hints.insert(1, (keys.ENTER, "open"))
            hints.insert(2, ("/", "search"))
        key_hint(scr, 2, scr.height - 2, hints)

    def handle(self, key: str) -> None:
        """Navigate tabs, entries and detail pages."""
        if self.tabs.handle(key):
            self.refresh()
            return
        if key == "/":
            text = prompt_string(self.app.screen, self.app.term, "Search:",
                                 self.search_text, 30)
            if text is not None:
                self.search_text = text
                self.refresh()
            return
        if self.tabs.index == 0 or self.detail is not None:
            if key in (keys.DOWN, "j"):
                self.offset += 1
            elif key in (keys.UP, "k"):
                self.offset = max(0, self.offset - 1)
            elif key == keys.PGDN:
                self.offset += 12
            elif key == keys.PGUP:
                self.offset = max(0, self.offset - 12)
            elif key in (keys.ESC, "q"):
                if self.detail is not None:
                    self.detail = None
                    self.offset = 0
                else:
                    self.done = True
            return

        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result == "select":
            self._open(self.menu.selected_value)

    def _open(self, value) -> None:
        """Show the detail page for a list entry."""
        if not value:
            return
        world = self.world
        kind, ident = value
        if kind == "figure":
            self.detail = legends.figure_lines(world, ident)
        elif kind == "site":
            self.detail = legends.site_lines(world, ident)
        elif kind == "civ":
            self.detail = legends.civ_lines(world, ident)
        elif kind == "artifact":
            self.detail = legends.artifact_lines(world, ident)
        elif kind == "form":
            from ..world import artforms

            form = artforms.by_id(world, ident)
            self.detail = artforms.describe(world, form) if form else None
        elif kind == "event":
            ev = next((e for e in world.events if e.id == ident), None)
            self.detail = legends.event_lines(world, ev) if ev else None
        elif kind == "deity":
            self.detail = legends.deity_lines(world, ident)
        self.offset = 0
