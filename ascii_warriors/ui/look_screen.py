"""The look/examine cursor."""

from __future__ import annotations

from typing import Optional, Tuple

from ..engine import colors, keys
from ..engine.screen import Frag, Screen, frag_slice
from ..engine.widgets import key_hint
from ..world import tiles as tile_data
from .app import Scene
from .sidebar import LOG_HEIGHT, SIDEBAR_WIDTH


class LookScene(Scene):
    """Move a cursor around the map and describe what it is over."""

    def __init__(self, app, *, targeting: bool = False, prompt: str = "") -> None:
        super().__init__(app)
        self.targeting = targeting
        self.prompt = prompt or ("Choose a target" if targeting else "Look around")
        self.cx = 0
        self.cy = 0
        self.cz = 0
        self.result: Optional[Tuple[int, int, int]] = None

    def on_enter(self) -> None:
        game = self.game
        if game is None:
            self.done = True
            return
        p = game.player
        self.cx, self.cy, self.cz = p.x, p.y, p.z
        targets = [
            c for c in game.visible_creatures() if c.is_hostile_to(p)
        ] or game.visible_creatures()
        if targets:
            self.cx, self.cy, self.cz = targets[0].x, targets[0].y, targets[0].z

    def draw(self, scr: Screen) -> None:
        """Draw the map underneath and a description panel."""
        game = self.game
        if game is None:
            return
        from .play_screen import PlayScene

        play = PlayScene(self.app)
        mx, my, mw, mh = play._layout(scr)
        play.cam_x = max(0, min(max(0, game.local.width - mw), self.cx - mw // 2))
        play.cam_y = max(0, min(max(0, game.local.height - mh), self.cy - mh // 2))
        saved_z = game.player.z
        play.draw_map(scr, mx, my, mw, mh)

        sx = mx + self.cx - play.cam_x
        sy = my + self.cy - play.cam_y
        if mx <= sx < mx + mw and my <= sy < my + mh:
            ch, fg, _bg = scr.get(sx, sy)
            scr.put(sx, sy, ch, colors.UI["bg"], colors.UI["accent"])

        panel_x = scr.width - SIDEBAR_WIDTH + 1
        panel_w = SIDEBAR_WIDTH - 2
        if scr.width < 84:
            panel_x, panel_w = 2, scr.width - 4
        scr.fill(panel_x - 1, 1, panel_w + 1, scr.height - LOG_HEIGHT - 1, " ",
                 colors.UI["fg"], colors.UI["bg"])
        scr.vline(panel_x - 1, 1, scr.height - LOG_HEIGHT - 2, "|",
                  colors.UI["frame"])
        scr.text(panel_x, 1, self.prompt, colors.UI["title"])
        dist = max(abs(self.cx - game.player.x), abs(self.cy - game.player.y))
        scr.text(panel_x, 2, "(%d, %d) z%+d  %d away" % (
            self.cx, self.cy, self.cz, dist), colors.UI["dim"])
        row = 4
        for frag in game.describe_tile(self.cx, self.cy, self.cz):
            if row >= scr.height - LOG_HEIGHT - 1:
                break
            used = scr.wrapped(panel_x, row, panel_w, [frag])
            row += max(1, used)

        key_hint(scr, 0, scr.height - 1, [
            (keys.ENTER, "select" if self.targeting else "close"),
            ("hjkl", "move"), ("<>", "level"), (keys.TAB, "next"),
            (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Move the cursor or accept the target."""
        game = self.game
        if game is None:
            self.done = True
            return
        d = keys.direction_of(key)
        if d is not None:
            step = 5 if keys.is_run_key(key) else 1
            self.cx = max(0, min(game.local.width - 1, self.cx + d[0] * step))
            self.cy = max(0, min(game.local.height - 1, self.cy + d[1] * step))
            return
        if key == "<":
            self.cz = min(game.local.zmax, self.cz + 1)
            return
        if key == ">":
            self.cz = max(game.local.zmin, self.cz - 1)
            return
        if key == keys.TAB:
            targets = game.visible_creatures()
            if targets:
                cur = None
                for i, c in enumerate(targets):
                    if (c.x, c.y) == (self.cx, self.cy):
                        cur = i
                        break
                nxt = targets[((cur + 1) if cur is not None else 0) % len(targets)]
                self.cx, self.cy, self.cz = nxt.x, nxt.y, nxt.z
            return
        if key in (keys.ENTER, keys.SPACE):
            self.result = (self.cx, self.cy, self.cz)
            self.done = True
            return
        if key == keys.ESC:
            self.result = None
            self.done = True
