"""Painting designations: the orders you give the map rather than the dwarves."""

from __future__ import annotations

from typing import List, Tuple

from ...engine import colors, keys
from ...engine.screen import Frag
from ...fortress.designations import KINDS
from .cursor import CursorScene

#: The key each designation hangs off, in the order the prompt lists them.
#: Every kind in `KINDS` needs one. `engrave` went without for a long time,
#: which meant the whole of `fortress/art.py` -- the engravings, their
#: quality, the history they carve, the rooms they are worth something to --
#: could not be asked for from the keyboard at all. `TestDesignations` now
#: holds this list against `KINDS` so it cannot happen again.
BINDINGS: Tuple[Tuple[str, str], ...] = (
    ("d", "dig"),
    ("h", "channel"),
    ("i", "stairs"),
    ("r", "ramp"),
    ("s", "smooth"),
    ("e", "engrave"),
    ("t", "chop"),
    ("g", "gather"),
    ("a", "sand"),
    ("n", "remove"),
)


class DesignateScene(CursorScene):
    """Paint dig, channel, stairs and the rest onto the map."""

    mode_name = "Designate"

    def __init__(self, app, parent) -> None:
        super().__init__(app, parent)
        self.kind = "dig"
        self.erasing = False

    def header(self) -> List[Frag]:
        """What is selected, and how to change it."""
        out: List[Frag] = []
        if self.erasing:
            out.append(Frag("ERASE  ", colors.UI["danger"]))
        for key, kind in BINDINGS:
            defn = KINDS[kind]
            chosen = kind == self.kind and not self.erasing
            colour = defn.color if chosen else colors.UI["dim"]
            out.append(Frag("%s:%s " % (key, defn.name), colour))
        out.append(Frag(" x:erase", colors.UI["dim"]))
        return out

    def hints(self) -> List[Tuple[str, str]]:
        """Bottom-line hints."""
        verb = "erase" if self.erasing else KINDS[self.kind].name.lower()
        return [
            (keys.ENTER, "corner, then %s" % verb),
            ("< >", "level"),
            (keys.ESC, "done"),
        ]

    def extra_key(self, key: str) -> bool:
        """Pick a designation kind."""
        if key == "x":
            self.erasing = not self.erasing
            return True
        for binding, kind in BINDINGS:
            if key == binding:
                self.kind = kind
                self.erasing = False
                return True
        return False

    def apply(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Paint or erase a rectangle."""
        fort = self.fort
        if self.erasing:
            n = fort.designations.clear_rect(x0, y0, x1, y1, fort.z)
            if n:
                fort.log.system("Cleared %d designations." % n)
            return
        n = fort.designations.paint_rect(fort.local, x0, y0, x1, y1, fort.z,
                                         self.kind)
        total = (abs(x1 - x0) + 1) * (abs(y1 - y0) + 1)
        name = KINDS[self.kind].name.lower()
        if n == 0:
            fort.log.warn("Nothing there will take a %s designation." % name)
        else:
            fort.log.system("Designated %d of %d tiles: %s." % (n, total, name))
        for cell in list(fort.unreachable):
            if cell[2] == fort.z:
                del fort.unreachable[cell]
