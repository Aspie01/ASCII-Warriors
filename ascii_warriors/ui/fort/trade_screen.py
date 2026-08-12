"""Trading with the dwarven caravan.

The caravan wants crafts, and pays badly for anything you actually need. Offer
goods on the left, take goods on the right, and press Enter when the balance
suits you.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import ListMenu, MenuItem, key_hint
from ...game.item import Item
from ...game.trade import BASE_BUY_RATE, BASE_SELL_RATE
from ..app import Scene


def open_trade(app, fort) -> None:
    """Open the trade screen, if there is anybody to trade with."""
    if fort.caravan is None:
        app.message("Trade", "There is no caravan here.\n\n"
                             "One comes every autumn, if you are worth "
                             "visiting.")
        return
    app.push(TradeScene(app, fort))


class TradeScene(Scene):
    """Offer goods, take goods."""

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort
        self.caravan = fort.caravan
        self.their_goods: List[Item] = [
            Item.from_dict(d) for d in self.caravan.get("goods", [])
        ]
        self.side = 0
        self.offered: Dict[int, int] = {}
        self.wanted: Dict[int, int] = {}
        self.mine = ListMenu(self._my_items(), per_page=14, auto_hotkeys=False)
        self.theirs = ListMenu(self._their_items(), per_page=14,
                               auto_hotkeys=False)

    # -- contents ---------------------------------------------------------- #

    def _sellable(self) -> List[Item]:
        """Everything of yours a caravan would take away."""
        out: List[Item] = []
        for pile in self.fort.items_on_ground.values():
            for item in pile:
                if item.is_corpse or item.def_id == "coin":
                    continue
                out.append(item)
        out.sort(key=lambda i: (-i.value, i.base_name()))
        return out

    def _my_items(self) -> List[MenuItem]:
        """Your side of the table."""
        rows = []
        for item in self._sellable():
            picked = self.offered.get(item.id, 0)
            rows.append(MenuItem([
                Frag("%-30s " % item.name()[:30],
                     colors.UI["fg"] if not picked else colors.UI["accent"]),
                Frag("%3d " % item.count, colors.UI["dim"]),
                Frag("%5d " % self.sell_price(item), colors.UI["good"]),
                Frag(("offering %d" % picked) if picked else "",
                     colors.UI["accent"]),
            ], item.id))
        if not rows:
            rows.append(MenuItem("Nothing worth selling.", None))
        return rows

    def _their_items(self) -> List[MenuItem]:
        """The caravan's side."""
        rows = []
        for item in self.their_goods:
            picked = self.wanted.get(item.id, 0)
            rows.append(MenuItem([
                Frag("%-30s " % item.name()[:30],
                     colors.UI["fg"] if not picked else colors.UI["accent"]),
                Frag("%3d " % item.count, colors.UI["dim"]),
                Frag("%5d " % self.buy_price(item), colors.UI["warn"]),
                Frag(("taking %d" % picked) if picked else "",
                     colors.UI["accent"]),
            ], item.id))
        if not rows:
            rows.append(MenuItem("Their wagons are empty.", None))
        return rows

    # -- prices ------------------------------------------------------------ #

    def sell_price(self, item: Item) -> int:
        """What they will give you for one unit."""
        return max(1, int(item.value / max(1, item.count) * BASE_SELL_RATE))

    def buy_price(self, item: Item) -> int:
        """What they want for one unit."""
        return max(1, int(item.value / max(1, item.count) * BASE_BUY_RATE))

    def balance(self) -> Tuple[int, int]:
        """``(what you are giving, what you are taking)`` in coins."""
        give = 0
        for item in self._sellable():
            n = self.offered.get(item.id, 0)
            if n:
                give += self.sell_price(item) * n
        take = 0
        for item in self.their_goods:
            n = self.wanted.get(item.id, 0)
            if n:
                take += self.buy_price(item) * n
        return (give, take)

    # -- drawing ----------------------------------------------------------- #

    def draw(self, scr: Screen) -> None:
        """Two columns and a running total."""
        scr.clear(colors.UI["bg"])
        scr.frame(0, 0, scr.width, scr.height, title="The dwarven caravan")
        half = (scr.width - 6) // 2
        left, right = 2, 4 + half
        scr.text(left, 1, "Yours", colors.UI["title"] if self.side == 0
                 else colors.UI["dim"])
        scr.text(right, 1, "Theirs", colors.UI["title"] if self.side == 1
                 else colors.UI["dim"])
        scr.vline(right - 2, 1, scr.height - 4, "|", colors.UI["frame"])
        body_h = scr.height - 6
        self.mine.per_page = max(3, body_h)
        self.theirs.per_page = max(3, body_h)
        self.mine.draw(scr, left, 2, half, body_h)
        self.theirs.draw(scr, right, 2, half, body_h)

        give, take = self.balance()
        row = scr.height - 3
        scr.text(left, row, "You offer %d" % give, colors.UI["good"])
        scr.text(right, row, "You take %d" % take, colors.UI["warn"])
        verdict = ("They will take that." if give >= take
                   else "They want %d more." % (take - give))
        colour = colors.UI["good"] if give >= take else colors.UI["danger"]
        scr.text_center(row + 1, verdict, colour)
        key_hint(scr, left, scr.height - 1, [
            (keys.TAB, "side"), (keys.SPACE, "add one"), ("a", "add all"),
            ("x", "clear"), (keys.ENTER, "trade"), (keys.ESC, "leave"),
        ])

    # -- input ------------------------------------------------------------- #

    @property
    def menu(self) -> ListMenu:
        """The column the cursor is in."""
        return self.mine if self.side == 0 else self.theirs

    def handle(self, key: str) -> None:
        """Move goods across the table."""
        if key == keys.ESC:
            self.done = True
            return
        if key in (keys.TAB, keys.LEFT, keys.RIGHT):
            self.side = 1 - self.side
            return
        if key == "x":
            self.offered.clear()
            self.wanted.clear()
            self._refresh()
            return
        if key == keys.ENTER:
            self._trade()
            return
        if key in (keys.SPACE, "a"):
            self._pick(all_of_it=key == "a")
            return
        self.menu.handle(key)

    def _pick(self, *, all_of_it: bool) -> None:
        """Add one, or all, of the highlighted stack to the deal."""
        item_id = self.menu.selected_value
        if item_id is None:
            return
        if self.side == 0:
            item = next((i for i in self._sellable() if i.id == item_id), None)
            store = self.offered
        else:
            item = next((i for i in self.their_goods if i.id == item_id), None)
            store = self.wanted
        if item is None:
            return
        current = store.get(item_id, 0)
        store[item_id] = item.count if all_of_it else min(item.count,
                                                          current + 1)
        if current >= item.count and not all_of_it:
            store[item_id] = 0
        self._refresh()

    def _refresh(self) -> None:
        """Redraw both columns, holding the cursors still."""
        mi, ti = self.mine.index, self.theirs.index
        self.mine.set_items(self._my_items())
        self.theirs.set_items(self._their_items())
        self.mine.index = min(mi, max(0, len(self.mine.visible_items()) - 1))
        self.theirs.index = min(ti, max(0, len(self.theirs.visible_items()) - 1))

    def _trade(self) -> None:
        """Close the deal, if they will take it."""
        fort = self.fort
        give, take = self.balance()
        if take > give:
            fort.log.warn("The trader shakes his head. Offer %d more."
                          % (take - give))
            return
        if not self.offered and not self.wanted:
            self.done = True
            return

        for item in list(self._sellable()):
            n = self.offered.get(item.id, 0)
            if not n:
                continue
            item.count -= n
            if item.count <= 0:
                fort.take_item(item)
        depot = self._depot()
        for item in self.their_goods:
            n = self.wanted.get(item.id, 0)
            if not n:
                continue
            fort.drop_item(Item(item.def_id, item.material, count=n,
                                quality=item.quality), *depot)
            item.count -= n

        self.their_goods = [i for i in self.their_goods if i.count > 0]
        self.caravan["goods"] = [i.to_dict() for i in self.their_goods]
        self.caravan["traded"] = True
        fort.log.good("Trade concluded: %d for %d." % (give, take))
        for d in fort.dwarves():
            d.needs.add_thought("traded with the caravan", -3)
        self.offered.clear()
        self.wanted.clear()
        self._refresh()

    def _depot(self):
        """Where bought goods land."""
        dwarves = self.fort.dwarves()
        if dwarves:
            d = dwarves[0]
            return (d.x, d.y, d.z)
        return (self.fort.local.width // 2, self.fort.local.height // 2,
                self.fort.z)
