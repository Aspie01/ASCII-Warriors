"""Buying from and selling to a merchant."""

from __future__ import annotations

from typing import List

from ..engine import colors, keys
from ..engine.screen import Frag, Screen
from ..engine.widgets import ListMenu, MenuItem, Tabs, key_hint
from ..game import trade
from .app import Scene


class ShopScene(Scene):
    """A two-tab trading screen: their goods, and yours."""

    def __init__(self, app, merchant) -> None:
        super().__init__(app)
        self.merchant = merchant
        self.tabs = Tabs(["Buy", "Sell"])
        self.menu = ListMenu([], per_page=18)
        self.message = ""

    def on_enter(self) -> None:
        game = self.game
        if game is None or self.merchant is None:
            self.done = True
            return
        trade.stock_merchant(self.merchant, game.rng)
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the item list for the active tab."""
        game = self.game
        player = game.player
        items: List[MenuItem] = []
        if self.tabs.index == 0:
            for it in trade.for_sale(self.merchant):
                price = trade.price_to_buy(it, self.merchant, player)
                afford = player.inventory.coins() >= price
                label = list(it.colored_name())
                if not afford:
                    label = [Frag(f.text, colors.UI["dim"]) for f in label]
                items.append(MenuItem(
                    label, it, desc="%d" % price, enabled=afford))
            if not items:
                items = [MenuItem("(nothing for sale)", None, enabled=False)]
        else:
            for it in trade.sellable(player, self.merchant):
                price = trade.price_to_sell(it, self.merchant, player)
                items.append(MenuItem(
                    it.colored_name(), it, desc="%d" % price, enabled=price > 0))
            if not items:
                items = [MenuItem("(they want nothing you carry)", None,
                                  enabled=False)]
        self.menu.set_items(items)

    def draw(self, scr: Screen) -> None:
        """Draw the shop, the item detail and both purses."""
        game = self.game
        if game is None:
            return
        player = game.player
        title = self.merchant.display_name()
        if self.merchant.profession:
            title += " the %s" % self.merchant.profession
        scr.frame(0, 0, scr.width, scr.height - 1, title=title)
        self.tabs.draw(scr, 2, 1, 30)
        scr.text_right(scr.width - 2, 1, "you %d   them %d" % (
            player.inventory.coins(), self.merchant.inventory.coins()),
            colors.UI["accent"])

        list_w = max(30, scr.width // 2 - 2)
        scr.text(2, 2, "%-*s %6s" % (list_w - 8, "ITEM", "PRICE"),
                 colors.UI["dim"])
        self.menu.draw(scr, 2, 3, list_w, scr.height - 7)

        detail_x = list_w + 4
        detail_w = scr.width - detail_x - 2
        item = self.menu.selected_value
        if item is not None and detail_w > 12:
            scr.vline(detail_x - 2, 3, scr.height - 7, "|", colors.UI["frame"])
            row = 3
            for i, line in enumerate(item.full_description()):
                if row >= scr.height - 5:
                    break
                colour = colors.UI["title"] if i == 0 else colors.UI["fg"]
                row += scr.wrapped(detail_x, row, detail_w, line, colour)

        if self.message:
            scr.text(2, scr.height - 3, self.message[: scr.width - 4],
                     colors.UI["good"] if "buy" in self.message
                     or "sell" in self.message else colors.UI["warn"])
        key_hint(scr, 2, scr.height - 2, [
            (keys.ENTER, "trade one"), ("a", "trade all"),
            (keys.TAB, "buy/sell"), (keys.ESC, "leave"),
        ])

    def handle(self, key: str) -> None:
        """Buy, sell or leave."""
        game = self.game
        if game is None:
            self.done = True
            return
        if self.tabs.handle(key):
            self.message = ""
            self.refresh()
            return

        item = self.menu.selected_value
        if key == "a" and item is not None:
            self._trade(item, item.count)
            return
        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result == "select" and item is not None:
            self._trade(item, 1)

    def _trade(self, item, count: int) -> None:
        """Move one item (or a whole stack) across the counter."""
        game = self.game
        if self.tabs.index == 0:
            ok, message = trade.buy(game, self.merchant, item, count)
        else:
            ok, message = trade.sell(game, self.merchant, item, count)
        self.message = message
        if ok:
            game.log.info(message)
        self.refresh()
