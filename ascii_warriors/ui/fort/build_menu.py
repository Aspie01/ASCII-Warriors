"""Putting things up: workshops, furniture, walls and stockpiles."""

from __future__ import annotations

from typing import List, Optional, Tuple

from ...engine import colors, keys
from ...engine.screen import Frag
from ...engine.widgets import MenuItem, choose, header
from ...fortress import buildings as building_mod
from ...fortress.buildings import BUILD_CATEGORIES, KINDS, Building, Stockpile
from ...fortress.buildings import STOCKPILE_TYPES
from .cursor import CursorScene


def pick_building(app, fort) -> Optional[str]:
    """Choose what to build."""
    items: List[MenuItem] = []
    for category in BUILD_CATEGORIES:
        items.append(header(category))
        for k in KINDS.values():
            if k.category != category:
                continue
            need = ("%d %s" % (k.material_count, "/".join(k.materials).lower())
                    if k.material_count else "no materials")
            label = [
                Frag("%-24s " % k.name, k.color),
                Frag("%-16s " % need, colors.UI["dim"]),
            ]
            if k.width > 1 or k.height > 1:
                label.append(Frag("%dx%d" % (k.width, k.height),
                                  colors.UI["dim"]))
            items.append(MenuItem(label, k.id, desc=k.description))
    return choose(app.screen, app.term, "Build what?", items, per_page=20,
                  width=min(app.screen.width - 4, 72))


class BuildScene(CursorScene):
    """Place a chosen building on the map."""

    mode_name = "Build"
    rectangular = False

    def __init__(self, app, parent, kind: str = "") -> None:
        super().__init__(app, parent)
        self.kind = kind or (pick_building(app, parent.fort) or "")
        if not self.kind:
            self.done = True

    @property
    def defn(self):
        """The chosen building's definition."""
        return KINDS.get(self.kind)

    def ghost(self):
        """Show the footprint under the cursor."""
        d = self.defn
        if d is None:
            return None
        return (d.glyph, self.cx, self.cy, d.width, d.height)

    def header(self) -> List[Frag]:
        """Name the building and whether it fits."""
        d = self.defn
        if d is None:
            return []
        ok, why = building_mod.can_place(self.fort.local, self.kind, self.cx,
                                         self.cy, self.fort.z,
                                         self.fort.buildings,
                                         self.fort.magma)
        out = [Frag(d.name + "  ", d.color)]
        if ok:
            out.append(Frag("place with Enter", colors.UI["good"]))
        else:
            out.append(Frag(why, colors.UI["danger"]))
        return out

    def hints(self) -> List[Tuple[str, str]]:
        """Bottom-line hints."""
        return [(keys.ENTER, "place"), ("b", "change"), ("< >", "level"),
                (keys.ESC, "done")]

    def extra_key(self, key: str) -> bool:
        """Swap to a different building."""
        if key == "b":
            chosen = pick_building(self.app, self.fort)
            if chosen:
                self.kind = chosen
            return True
        return False

    def apply(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Plan the building here."""
        fort = self.fort
        ok, why = building_mod.can_place(fort.local, self.kind, x0, y0, fort.z,
                                         fort.buildings, fort.magma)
        if not ok:
            fort.log.warn(why)
            return
        b = Building(self.kind, x0, y0, fort.z)
        fort.buildings.append(b)
        fort.log.system("A %s is planned here." % b.defn.name.lower())
        fort.clear_warning("material-" + self.kind)


class StockpileScene(CursorScene):
    """Drag out a stockpile."""

    mode_name = "Stockpile"

    def __init__(self, app, parent) -> None:
        super().__init__(app, parent)
        self.kind = "all"
        self.removing = False

    #: Letters, not digits: the number row already scrolls the cursor.
    LETTERS = "qwertyuiop"

    def header(self) -> List[Frag]:
        """The pile types, with the chosen one lit."""
        out: List[Frag] = []
        if self.removing:
            out.append(Frag("REMOVE  ", colors.UI["danger"]))
        for i, kind in enumerate(sorted(STOCKPILE_TYPES)):
            chosen = kind == self.kind and not self.removing
            colour = (building_mod.STOCKPILE_COLORS.get(kind, colors.UI["fg"])
                      if chosen else colors.UI["dim"])
            out.append(Frag("%s:%s " % (self.LETTERS[i], kind), colour))
        out.append(Frag(" x:remove", colors.UI["dim"]))
        return out

    def hints(self) -> List[Tuple[str, str]]:
        """Bottom-line hints."""
        return [(keys.ENTER, "corner, then corner"),
                ("%s-%s" % (self.LETTERS[0], self.LETTERS[
                    len(STOCKPILE_TYPES) - 1]), "kind"),
                (keys.ESC, "done")]

    def extra_key(self, key: str) -> bool:
        """Toggle removal mode."""
        if key == "x":
            self.removing = not self.removing
            return True
        return False

    def handle(self, key: str) -> None:
        """Letters choose a stockpile type; everything else is the cursor."""
        kinds = sorted(STOCKPILE_TYPES)
        if key in self.LETTERS[:len(kinds)]:
            self.kind = kinds[self.LETTERS.index(key)]
            self.removing = False
            return
        super().handle(key)

    def apply(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Create or delete a stockpile rectangle."""
        fort = self.fort
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))
        if self.removing:
            gone = [s for s in fort.stockpiles
                    if s.z == fort.z and lo_x <= s.x <= hi_x
                    and lo_y <= s.y <= hi_y]
            for s in gone:
                fort.stockpiles.remove(s)
            fort.log.system("Removed %d stockpiles." % len(gone))
            return
        pile = Stockpile(self.kind, lo_x, lo_y, fort.z,
                         hi_x - lo_x + 1, hi_y - lo_y + 1)
        fort.stockpiles.append(pile)
        fort.log.system("Stockpile (%s), %d by %d." % (
            self.kind, pile.w, pile.h))


class BurrowScene(CursorScene):
    """Mark the room civilians run to when the alarm sounds."""

    mode_name = "Safe burrow"

    def header(self) -> List[Frag]:
        """Explain what this is for."""
        current = self.fort.military.burrow
        out = [Frag("Mark the room your civilians shelter in. ",
                    colors.UI["fg"])]
        if current is not None:
            out.append(Frag("(one is already set: Enter twice to replace it)",
                            colors.UI["dim"]))
        return out

    def hints(self) -> List[Tuple[str, str]]:
        """Bottom-line hints."""
        return [(keys.ENTER, "corner, then corner"), ("x", "clear"),
                (keys.ESC, "done")]

    def extra_key(self, key: str) -> bool:
        """Clear the burrow entirely."""
        if key == "x":
            self.fort.military.burrow = None
            self.fort.log.system("The safe burrow is cleared.")
            return True
        return False

    def apply(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Set the burrow rectangle."""
        fort = self.fort
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))
        fort.military.burrow = (lo_x, lo_y, fort.z,
                                hi_x - lo_x + 1, hi_y - lo_y + 1)
        fort.log.system("Safe burrow set, %d by %d." % (
            hi_x - lo_x + 1, hi_y - lo_y + 1))
