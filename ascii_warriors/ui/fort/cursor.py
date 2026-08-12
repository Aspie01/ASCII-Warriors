"""A shared cursor mode for painting things onto the map.

Designating, building and zoning are all the same interaction: move a cursor,
press Enter once to anchor a corner, press it again to apply. This is that
interaction, with the specifics left to whoever subclasses it.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import key_hint
from ..app import Scene
from . import render
from .fort_screen import scroll_delta
from .sidebar import LOG_HEIGHT, SIDEBAR_WIDTH, draw_log, draw_sidebar, draw_status_line

Cell = Tuple[int, int, int]


class CursorScene(Scene):
    """A map cursor with an optional rectangular drag."""

    #: What the status line calls this mode.
    mode_name = "Cursor"
    #: Whether Enter starts a rectangle rather than acting immediately.
    rectangular = True

    def __init__(self, app, parent) -> None:
        super().__init__(app)
        self.parent = parent
        self.fort = parent.fort
        mw, mh = 60, 30
        self.cx = parent.cam_x + mw // 2
        self.cy = parent.cam_y + mh // 2
        self.anchor: Optional[Tuple[int, int]] = None

    # -- subclass hooks ---------------------------------------------------- #

    def hints(self) -> List[Tuple[str, str]]:
        """Key hints for the bottom of the screen."""
        return [(keys.ENTER, "apply"), (keys.ESC, "done")]

    def header(self) -> List[Frag]:
        """A line describing what is about to happen."""
        return []

    def apply(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Do the thing to a rectangle of the map."""

    def ghost(self):
        """An optional ``(glyph, x, y, w, h)`` preview at the cursor."""
        return None

    def extra_key(self, key: str) -> bool:
        """Handle a key the base class does not. True if it was consumed."""
        return False

    # -- drawing ----------------------------------------------------------- #

    @property
    def cursor(self) -> Cell:
        """Where the cursor is."""
        return (self.cx, self.cy, self.fort.z)

    def _layout(self, scr: Screen) -> Tuple[int, int, int, int]:
        sidebar = SIDEBAR_WIDTH if scr.width >= 88 else 0
        map_w = scr.width - sidebar - (2 if sidebar else 0)
        map_h = scr.height - LOG_HEIGHT - 1
        return (0, 1, max(10, map_w), max(5, map_h))

    def draw(self, scr: Screen) -> None:
        """Render the map with the cursor and any pending rectangle."""
        fort = self.fort
        mx, my, mw, mh = self._layout(scr)
        self._follow(mw, mh)
        region = None
        if self.anchor is not None:
            region = (self.anchor[0], self.anchor[1], self.cx, self.cy)
        draw_status_line(scr, 0, 0, scr.width, fort, self.mode_name)
        render.draw_map(scr, fort, mx, my, mw, mh, self.parent.cam_x,
                        self.parent.cam_y, cursor=self.cursor, region=region,
                        ghost=self.ghost())
        if scr.width >= 88:
            draw_sidebar(scr, scr.width - SIDEBAR_WIDTH + 1, 1,
                         SIDEBAR_WIDTH - 1, scr.height - LOG_HEIGHT - 1, fort)
        draw_log(scr, 0, scr.height - LOG_HEIGHT, scr.width, LOG_HEIGHT, fort)
        head = self.header()
        if head:
            scr.fill(0, my + mh, scr.width, 1, " ", colors.UI["fg"],
                     colors.UI["bg"])
            scr.text(1, my + mh, head)
        key_hint(scr, 1, scr.height - 1, self.hints())

    def _follow(self, mw: int, mh: int) -> None:
        """Scroll the parent's camera to keep the cursor on screen."""
        p = self.parent
        margin = 3
        if self.cx < p.cam_x + margin:
            p.cam_x = self.cx - margin
        if self.cx >= p.cam_x + mw - margin:
            p.cam_x = self.cx - mw + margin + 1
        if self.cy < p.cam_y + margin:
            p.cam_y = self.cy - margin
        if self.cy >= p.cam_y + mh - margin:
            p.cam_y = self.cy - mh + margin + 1
        p.cam_x, p.cam_y = render.clamp_camera(self.fort, p.cam_x, p.cam_y,
                                               mw, mh)

    # -- input ------------------------------------------------------------- #

    def handle(self, key: str) -> None:
        """Move the cursor, anchor, apply, or hand the key to the subclass."""
        fort = self.fort
        delta = scroll_delta(key)
        if delta is not None:
            self.cx = max(0, min(fort.local.width - 1, self.cx + delta[0]))
            self.cy = max(0, min(fort.local.height - 1, self.cy + delta[1]))
            return
        if key in (">", ")"):
            fort.z = max(fort.local.zmin, fort.z - 1)
            return
        if key in ("<", "("):
            fort.z = min(fort.local.zmax, fort.z + 1)
            return
        if key == keys.ENTER:
            self._enter()
            return
        if key == keys.ESC:
            if self.anchor is not None:
                self.anchor = None
            else:
                self.done = True
            return
        if self.extra_key(key):
            return

    def _enter(self) -> None:
        """Anchor a corner, or apply the rectangle."""
        if not self.rectangular:
            self.apply(self.cx, self.cy, self.cx, self.cy)
            return
        if self.anchor is None:
            self.anchor = (self.cx, self.cy)
            return
        x0, y0 = self.anchor
        self.anchor = None
        self.apply(x0, y0, self.cx, self.cy)
