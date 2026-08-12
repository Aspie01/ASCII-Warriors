"""Queueing work at a workshop."""

from __future__ import annotations

from typing import List

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import ListMenu, MenuItem, choose, header, key_hint
from ...fortress import production
from ..app import Scene


def pick_workshop(app, fort) -> None:
    """Choose a workshop and open its order queue."""
    shops = [b for b in fort.buildings if b.is_workshop and b.built]
    if not shops:
        app.message("Orders", "You have not built a workshop yet.\n\n"
                              "Press b to build one.")
        return
    items = [
        MenuItem([
            Frag("%-28s " % b.name, b.defn.color),
            Frag("at %d,%d " % (b.x, b.y), colors.UI["dim"]),
            Frag("%d queued" % len(b.orders),
                 colors.UI["accent"] if b.orders else colors.UI["dim"]),
        ], b.id)
        for b in shops
    ]
    chosen = choose(app.screen, app.term, "Which workshop?", items)
    if chosen is None:
        return
    shop = fort.building(chosen)
    if shop is not None:
        app.push(OrderScene(app, fort, shop))


class OrderScene(Scene):
    """The queue at one workshop."""

    def __init__(self, app, fort, shop) -> None:
        super().__init__(app)
        self.fort = fort
        self.shop = shop
        self.menu = ListMenu(self._items(), per_page=16, auto_hotkeys=False)

    def _items(self) -> List[MenuItem]:
        """The queue, then everything this workshop could make."""
        items: List[MenuItem] = []
        if self.shop.orders:
            items.append(header("Queued"))
            for i, order in enumerate(self.shop.orders):
                recipe = production.RECIPES.get(order.get("recipe", ""))
                name = recipe.name if recipe else order.get("recipe", "?")
                count = ("repeat" if order.get("repeat")
                         else "x%d" % int(order.get("count", 1)))
                items.append(MenuItem([
                    Frag("%-30s " % name, colors.UI["fg"]),
                    Frag(count, colors.UI["accent"]),
                ], ("queued", i)))
        items.append(header("Can make"))
        for recipe in production.recipes_for(self.shop.kind):
            need = ", ".join("%d %s" % (n, r.lower())
                             for r, n in recipe.inputs)
            items.append(MenuItem([
                Frag("%-30s " % recipe.name, colors.UI["fg"]),
                Frag("%-22s " % ("needs " + need), colors.UI["dim"]),
                Frag("x%d" % recipe.out_count, colors.UI["accent"]),
            ], ("recipe", recipe.id), desc=recipe.description))
        return items

    def draw(self, scr: Screen) -> None:
        """The order screen."""
        scr.clear(colors.UI["bg"])
        scr.frame(0, 0, scr.width, scr.height, title=self.shop.name)
        self.menu.per_page = max(4, scr.height - 5)
        self.menu.draw(scr, 2, 2, scr.width - 4, scr.height - 5)
        key_hint(scr, 2, scr.height - 2, [
            (keys.ENTER, "queue one"), ("5", "queue five"),
            ("r", "repeat forever"), ("x", "cancel order"), (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Queue and cancel orders."""
        if key == keys.ESC:
            self.done = True
            return
        value = self.menu.selected_value
        if key in (keys.ENTER, "5", "r") and value and value[0] == "recipe":
            count = 5 if key == "5" else 1
            self.shop.orders.append({
                "recipe": value[1], "count": count, "repeat": key == "r",
            })
            recipe = production.RECIPES[value[1]]
            self.fort.log.system("Ordered: %s%s." % (
                recipe.name, " (repeating)" if key == "r" else ""))
            self._refresh()
            return
        if key == "x" and value and value[0] == "queued":
            index = value[1]
            if 0 <= index < len(self.shop.orders):
                del self.shop.orders[index]
                self._refresh()
            return
        if self.menu.handle(key) == "cancel":
            self.done = True

    def _refresh(self) -> None:
        """Rebuild the list, holding the cursor still."""
        index = self.menu.index
        self.menu.set_items(self._items())
        self.menu.index = min(index, max(0, len(self.menu.visible_items()) - 1))
