"""The inventory and equipment screen."""

from __future__ import annotations

from typing import List

from ..engine import colors, keys
from ..engine.screen import Frag, Screen
from ..engine.widgets import ListMenu, MenuItem, Tabs, key_hint
from ..game import actions
from ..game.inventory import BODY_SLOTS, SLOT_NAMES
from .app import Scene

CATEGORY_ORDER = (
    "weapon", "armor", "clothing", "shield", "ammo", "food", "drink", "tool",
    "container", "gem", "coin", "book", "corpse", "remains", "misc", "furniture",
)


class InventoryScene(Scene):
    """Browse, equip, drop, eat and inspect what you carry."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.tabs = Tabs(["Carried", "Equipped"])
        self.menu = ListMenu([], per_page=20)

    def on_enter(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the item list for the active tab."""
        game = self.game
        if game is None:
            self.done = True
            return
        inv = game.player.inventory
        items: List[MenuItem] = []
        if self.tabs.index == 0:
            by_cat = {}
            for it in inv.items:
                by_cat.setdefault(it.category, []).append(it)
            for cat in CATEGORY_ORDER:
                pool = by_cat.get(cat)
                if not pool:
                    continue
                items.append(MenuItem(cat.capitalize(), None, enabled=False,
                                      group=cat))
                for it in pool:
                    label = list(it.colored_name())
                    slot = inv.slot_of(it)
                    if slot:
                        label.append(Frag(" (%s)" % SLOT_NAMES.get(slot, slot),
                                          colors.UI["accent"]))
                    items.append(MenuItem(
                        label, it, desc="%.1fkg" % it.weight))
            for cat, pool in by_cat.items():
                if cat in CATEGORY_ORDER:
                    continue
                items.append(MenuItem(cat.capitalize(), None, enabled=False,
                                      group=cat))
                for it in pool:
                    items.append(MenuItem(it.colored_name(), it,
                                          desc="%.1fkg" % it.weight))
        else:
            for slot in BODY_SLOTS:
                it = inv.equipped.get(slot)
                label = "%-14s " % SLOT_NAMES.get(slot, slot)
                if it is None:
                    items.append(MenuItem(
                        [Frag(label, colors.UI["dim"]),
                         Frag("(empty)", colors.UI["dim"])], None, enabled=False))
                else:
                    items.append(MenuItem(
                        [Frag(label, colors.UI["accent"])] + list(it.colored_name()),
                        it))
        if not items:
            items = [MenuItem("(carrying nothing)", None, enabled=False)]
        self.menu.set_items(items)

    def draw(self, scr: Screen) -> None:
        """Draw the item list and a detail panel."""
        game = self.game
        if game is None:
            return
        inv = game.player.inventory
        scr.frame(0, 0, scr.width, scr.height - 1, title="Inventory")
        self.tabs.draw(scr, 2, 1, 40)

        weight = inv.total_weight()
        cap = game.player.carry_capacity()
        colour = (colors.UI["danger"] if weight > cap else
                  colors.UI["warn"] if weight > cap * 0.75 else colors.UI["dim"])
        scr.text_right(scr.width - 2, 1, "%.1f / %.1f kg   %d coins" % (
            weight, cap, inv.coins()), colour)

        list_w = max(30, scr.width // 2 - 2)
        self.menu.draw(scr, 2, 3, list_w, scr.height - 6)

        detail_x = list_w + 4
        detail_w = scr.width - detail_x - 2
        item = self.menu.selected_value
        if item is not None and detail_w > 12:
            scr.vline(detail_x - 2, 3, scr.height - 6, "|", colors.UI["frame"])
            row = 3
            for line in item.full_description(self.game.player):
                if row >= scr.height - 4:
                    break
                colour = colors.UI["title"] if row == 3 else colors.UI["fg"]
                row += scr.wrapped(detail_x, row, detail_w, line, colour)

        key_hint(scr, 2, scr.height - 2, [
            (keys.ENTER, "use"), ("w", "wield/wear"), ("r", "remove"),
            ("R", "read"), ("d", "drop"), ("e", "eat"),
            (keys.TAB, "tab"), (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Act on the selected item."""
        game = self.game
        if game is None:
            self.done = True
            return
        if self.tabs.handle(key):
            self.refresh()
            return
        item = self.menu.selected_value

        if key in ("w", "W") and item is not None:
            actions.equip(game, item)
            self.refresh()
            return
        if key == "r" and item is not None:
            slot = game.player.inventory.slot_of(item)
            if slot:
                actions.unequip(game, slot)
                self.refresh()
            return
        if key == "d" and item is not None:
            actions.drop(game, item)
            self.refresh()
            return
        if key == "e" and item is not None and item.is_edible:
            actions.eat(game, item)
            self.refresh()
            return
        if key == "q" and item is not None and item.is_drink:
            actions.drink(game, item)
            self.refresh()
            return
        if key == "b" and item is not None and item.is_corpse:
            actions.butcher(game, item)
            self.refresh()
            return
        if key == "R" and item is not None and _is_book(item):
            cost = actions.read_book(game, item)
            if cost:
                game.player_acts(cost)
            self.done = True
            return

        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result == "select" and item is not None:
            if _is_book(item):
                cost = actions.read_book(game, item)
                if cost:
                    game.player_acts(cost)
                self.done = True
                return
            if item.is_edible:
                actions.eat(game, item)
            elif item.is_drink:
                actions.drink(game, item)
            elif item.is_weapon or item.is_armor:
                actions.equip(game, item)
            self.refresh()


def _is_book(item) -> bool:
    """Whether this is something with words on it."""
    from ..game import books

    return books.of(item) is not None
