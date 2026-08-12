"""Everything the fortress owns, counted."""

from __future__ import annotations

from typing import Dict, List, Tuple

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import ListMenu, MenuItem, header, key_hint
from ..app import Scene

#: The order stock categories are listed in.
CATEGORY_ORDER: Tuple[str, ...] = (
    "drink", "food", "misc", "furniture", "weapon", "armor", "clothing",
    "shield", "ammo", "tool", "gem", "coin", "container", "book", "remains",
    "corpse",
)


class StocksScene(Scene):
    """A counted inventory of the whole fortress."""

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort
        self.menu = ListMenu(self._items(), per_page=18, auto_hotkeys=False)

    def _tally(self) -> Dict[str, Dict[str, Tuple[int, int]]]:
        """``category -> name -> (count, value)`` over ground and inventories."""
        out: Dict[str, Dict[str, Tuple[int, int]]] = {}
        def add(item):
            cat = out.setdefault(item.category, {})
            name = item.base_name(item.count > 1)
            count, value = cat.get(name, (0, 0))
            cat[name] = (count + item.count, value + item.value)

        for pile in self.fort.items_on_ground.values():
            for item in pile:
                add(item)
        for c in self.fort.creatures.values():
            if getattr(c, "fort", None) is None:
                continue
            for item in c.inventory.items:
                add(item)
        return out

    def _items(self) -> List[MenuItem]:
        """One row per kind of thing."""
        tally = self._tally()
        items: List[MenuItem] = []
        order = list(CATEGORY_ORDER)
        order += sorted(k for k in tally if k not in CATEGORY_ORDER)
        total = 0
        for category in order:
            rows = tally.get(category)
            if not rows:
                continue
            items.append(header(category.title()))
            for name, (count, value) in sorted(rows.items()):
                total += value
                items.append(MenuItem([
                    Frag("%-34s " % name[:34], colors.UI["fg"]),
                    Frag("%6d " % count, colors.UI["accent"]),
                    Frag("%8d" % value, colors.UI["dim"]),
                ], name))
        if not items:
            items.append(MenuItem("The fortress owns nothing at all.", "none"))
        else:
            items.insert(0, header("Total value: %d" % total))
        return items

    def draw(self, scr: Screen) -> None:
        """The stock list."""
        scr.clear(colors.UI["bg"])
        scr.frame(0, 0, scr.width, scr.height,
                  title="Stocks of %s" % self.fort.name)
        scr.text(scr.width - 26, 1, "%6s %8s" % ("count", "value"),
                 colors.UI["dim"])
        self.menu.per_page = max(4, scr.height - 5)
        self.menu.draw(scr, 2, 2, scr.width - 4, scr.height - 5)
        key_hint(scr, 2, scr.height - 2, [(keys.ESC, "back")])

    def handle(self, key: str) -> None:
        """Scroll, or leave."""
        if self.menu.handle(key) in ("cancel", "select"):
            self.done = True
