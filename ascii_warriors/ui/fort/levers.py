"""Levers: what they are linked to, and pulling them."""

from __future__ import annotations

from typing import List

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import ListMenu, MenuItem, choose, header, key_hint
from ..app import Scene


class LeverScene(Scene):
    """Every lever, what it opens, and a button to throw it."""

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort
        self.menu = ListMenu(self._items(), per_page=18, auto_hotkeys=False)

    def _items(self) -> List[MenuItem]:
        """Levers, their links, and anything not yet linked."""
        fort = self.fort
        items: List[MenuItem] = []
        levers = fort.levers()
        items.append(header("Levers (%d)" % len(levers)))
        if not levers:
            items.append(MenuItem(
                [Frag("  Build one from a mechanism (b, Defence).",
                      colors.UI["dim"])], None))
        for lever in levers:
            state = "waiting to be pulled" if lever.pending else (
                "%d linked" % len(lever.links))
            items.append(MenuItem([
                Frag("  %-18s " % ("lever at %d,%d" % (lever.x, lever.y)),
                     colors.UI["fg"]),
                Frag("%-22s " % state,
                     colors.UI["warn"] if lever.pending else colors.UI["dim"]),
                Frag(lever.material_name or "", colors.UI["dim"]),
            ], ("lever", lever.id)))
            for gid in lever.links:
                gate = fort.building(gid)
                if gate is None:
                    continue
                items.append(MenuItem([
                    Frag("      -> %-20s " % gate.defn.name, colors.UI["dim"]),
                    Frag("shut" if gate.shut else "open",
                         colors.UI["danger"] if gate.shut else colors.UI["good"]),
                ], ("gate", gid)))

        loose = [g for g in fort.gates()
                 if not any(g.id in lv.links for lv in levers)]
        items.append(header("Unlinked (%d)" % len(loose)))
        for gate in loose:
            items.append(MenuItem([
                Frag("  %-20s " % gate.defn.name, colors.UI["fg"]),
                Frag("at %d,%d,%+d  " % (gate.x, gate.y, gate.z),
                     colors.UI["dim"]),
                Frag("shut" if gate.shut else "open",
                     colors.UI["danger"] if gate.shut else colors.UI["good"]),
            ], ("gate", gate.id)))
        return items

    def draw(self, scr: Screen) -> None:
        """The lever list."""
        scr.clear(colors.UI["bg"])
        scr.frame(0, 0, scr.width, scr.height,
                  title="Levers and gates of %s" % self.fort.name)
        self.menu.per_page = max(4, scr.height - 5)
        self.menu.draw(scr, 2, 2, scr.width - 4, scr.height - 5)
        key_hint(scr, 2, scr.height - 2, [
            (keys.ENTER, "pull"), ("l", "link to a gate"),
            (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Pull a lever, or link one to a gate."""
        fort = self.fort
        if key == keys.ESC:
            self.done = True
            return
        value = self.menu.selected_value
        if key == keys.ENTER and value and value[0] == "lever":
            lever = fort.building(value[1])
            if lever is not None:
                lever.pending = True
                fort.log.system("Somebody will pull the lever at %d,%d."
                                % (lever.x, lever.y))
                self._refresh()
            return
        if key == "l" and value and value[0] == "lever":
            self._link(fort.building(value[1]))
            return
        if self.menu.handle(key) == "cancel":
            self.done = True

    def _link(self, lever) -> None:
        """Attach a lever to something it can open."""
        fort = self.fort
        if lever is None:
            return
        gates = fort.gates()
        if not gates:
            self.app.message(
                "Levers", "There is nothing to link to.\n\n"
                          "Build a floodgate, a drawbridge, a door or a hatch "
                          "first.")
            return
        items = [
            MenuItem([
                Frag("%-20s " % g.defn.name, g.defn.color),
                Frag("at %d,%d,%+d  " % (g.x, g.y, g.z), colors.UI["dim"]),
                Frag("linked" if g.id in lever.links else "",
                     colors.UI["accent"]),
            ], g.id)
            for g in gates
        ]
        chosen = choose(self.app.screen, self.app.term,
                        "Link the lever to what?", items)
        if chosen is None:
            return
        gate = fort.building(chosen)
        if gate is None:
            return
        if fort.link(lever, gate):
            fort.log.system("The lever is linked to a %s."
                            % gate.defn.name.lower())
        else:
            fort.log.system("The lever is unlinked from a %s."
                            % gate.defn.name.lower())
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild the list, holding the cursor still."""
        index = self.menu.index
        self.menu.set_items(self._items())
        self.menu.index = min(index, max(0, len(self.menu.visible_items()) - 1))
