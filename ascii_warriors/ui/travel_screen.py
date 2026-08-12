"""The world map and overland travel."""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..data import biomes as biome_data
from ..engine import colors, geometry, keys
from ..engine.colors import Color
from ..engine.pathfind import astar
from ..engine.screen import Frag, Screen, frag_slice
from ..engine.widgets import key_hint
from .app import Scene

RIVER_COLOR = colors.Color(96, 156, 210)


class TravelScene(Scene):
    """Browse the world map and walk between world tiles."""

    def __init__(self, app, *, view_only: bool = False) -> None:
        super().__init__(app)
        self.view_only = view_only
        self.cx = 0
        self.cy = 0
        self.route: List[Tuple[int, int]] = []
        self.message = ""

    def on_enter(self) -> None:
        game = self.game
        if game is None:
            self.done = True
            return
        self.cx, self.cy = game.player.wx, game.player.wy

    # -- drawing ----------------------------------------------------------- #

    def _tile_glyph(self, world, x: int, y: int) -> Tuple[str, Color]:
        """Glyph and colour for one world tile."""
        t = world.tile(x, y)
        site = world.site_at(x, y)
        if site is not None:
            return site.glyph()
        if t.river and not t.is_ocean:
            return ("~", RIVER_COLOR)
        b = biome_data.get(t.biome)
        return (b.glyph, b.map_color)

    def draw(self, scr: Screen) -> None:
        """Draw the world map, a legend and the cursor's tile details."""
        game = self.game
        if game is None:
            return
        world = game.world
        panel_w = 34
        map_w = max(20, scr.width - panel_w - 3)
        map_h = max(10, scr.height - 4)

        cam_x = max(0, min(max(0, world.width - map_w), self.cx - map_w // 2))
        cam_y = max(0, min(max(0, world.height - map_h), self.cy - map_h // 2))

        title = "World map" if self.view_only else "Travel"
        scr.frame(0, 0, map_w + 2, scr.height - 1, title="%s - %s" % (
            title, world.name))

        route_set = set(self.route)
        for sy in range(map_h):
            wy = cam_y + sy
            if wy >= world.height:
                break
            for sx in range(map_w):
                wx = cam_x + sx
                if wx >= world.width:
                    break
                glyph, colour = self._tile_glyph(world, wx, wy)
                t = world.tile(wx, wy)
                if not t.explored:
                    colour = colors.darken(colour, 0.55)
                if (wx, wy) in route_set:
                    colour = colors.UI["accent"]
                    glyph = "*" if glyph == "." else glyph
                scr.put(1 + sx, 1 + sy, glyph, colour)

        px, py = game.player.wx, game.player.wy
        if cam_x <= px < cam_x + map_w and cam_y <= py < cam_y + map_h:
            scr.put(1 + px - cam_x, 1 + py - cam_y, "@", colors.WHITE)
        if cam_x <= self.cx < cam_x + map_w and cam_y <= self.cy < cam_y + map_h:
            ch, _fg, _bg = scr.get(1 + self.cx - cam_x, 1 + self.cy - cam_y)
            scr.put(1 + self.cx - cam_x, 1 + self.cy - cam_y, ch,
                    colors.UI["bg"], colors.UI["accent"])

        self._draw_panel(scr, map_w + 3, 1, panel_w - 2)
        hints = [("hjkl", "move cursor"), (keys.ESC, "back")]
        if not self.view_only:
            hints = [("hjkl", "move"), (keys.ENTER, "travel here"),
                     ("HJKL", "fast"), (keys.ESC, "back")]
        key_hint(scr, 1, scr.height - 1, hints)

    def _draw_panel(self, scr: Screen, x: int, y: int, w: int) -> None:
        """Draw the details of the tile under the cursor."""
        game = self.game
        world = game.world
        t = world.tile(self.cx, self.cy)
        b = biome_data.get(t.biome)
        region = world.region_at(self.cx, self.cy)
        site = world.site_at(self.cx, self.cy)

        row = y
        scr.text(x, row, "(%d, %d)" % (self.cx, self.cy), colors.UI["dim"])
        row += 1
        scr.text(x, row, b.name, b.map_color)
        row += 1
        if region is not None:
            row += scr.wrapped(x, row, w, region.full_name, colors.UI["accent2"])
        row += 1
        if site is not None:
            row += scr.wrapped(x, row, w, site.full_name, colors.UI["title"])
            scr.text(x, row, "a %s" % site.kind_name, colors.UI["dim"])
            row += 1
            if site.is_ruin:
                scr.text(x, row, "in ruins", colors.UI["danger"])
            else:
                scr.text(x, row, "population %d" % site.population,
                         colors.UI["fg"])
            row += 1
            civ = world.civ(site.civ_id) if site.civ_id else None
            if civ is not None:
                row += scr.wrapped(x, row, w, civ.name, colors.UI["dim"])
            row += 1

        stats = [
            ("Elevation", "%d" % int(t.elevation * 100)),
            ("Rainfall", "%d" % int(t.rainfall * 100)),
            ("Temperature", "%d" % int(t.temperature)),
            ("Savagery", "%d" % t.savagery),
            ("Alignment", biome_data.alignment_name(t.evil)),
        ]
        for label, value in stats:
            if row >= scr.height - 6:
                break
            scr.text(x, row, "%-13s %s" % (label, value), colors.UI["dim"])
            row += 1
        if t.river:
            scr.text(x, row, "A river runs through here.", colors.UI["accent2"])
            row += 1

        row += 1
        dist = max(abs(self.cx - game.player.wx), abs(self.cy - game.player.wy))
        scr.text(x, row, "%d tiles away" % dist, colors.UI["dim"])
        row += 1
        if self.route:
            scr.text(x, row, "Route: %d tiles" % (len(self.route) - 1),
                     colors.UI["accent"])
            row += 1
        if self.message:
            row += 1
            scr.wrapped(x, row, w, self.message, colors.UI["warn"])

    # -- input ------------------------------------------------------------- #

    def handle(self, key: str) -> None:
        """Move the cursor, or travel."""
        game = self.game
        if game is None:
            self.done = True
            return
        world = game.world
        d = keys.direction_of(key)
        if d is not None:
            step = 5 if keys.is_run_key(key) else 1
            self.cx = max(0, min(world.width - 1, self.cx + d[0] * step))
            self.cy = max(0, min(world.height - 1, self.cy + d[1] * step))
            self.route = []
            self.message = ""
            return
        if key == keys.ESC:
            self.done = True
            return
        if key in (keys.ENTER, keys.SPACE) and not self.view_only:
            self._travel_to(self.cx, self.cy)

    def _travel_to(self, tx: int, ty: int) -> None:
        """Walk overland to a chosen tile, one step at a time."""
        game = self.game
        world = game.world
        if (tx, ty) == (game.player.wx, game.player.wy):
            self.done = True
            return
        if world.tile(tx, ty).is_ocean:
            self.message = "You cannot travel onto open water."
            return

        def neighbours(node):
            x, y = node
            for nx, ny in world.neighbours(x, y):
                if world.tile(nx, ny).is_ocean:
                    continue
                yield ((nx, ny), world.travel_cost(nx, ny))

        path = astar(
            (game.player.wx, game.player.wy), (tx, ty), neighbours,
            lambda a, b: geometry.chebyshev(a[0], a[1], b[0], b[1]),
            max_nodes=40000,
        )
        if not path:
            self.message = "You cannot find a way there."
            return
        self.route = path

        for step in path[1:]:
            dx = step[0] - game.player.wx
            dy = step[1] - game.player.wy
            if not game.travel_step(dx, dy):
                break
            self.cx, self.cy = game.player.wx, game.player.wy
            self.route = [
                p for p in self.route
                if (p[0], p[1]) != (game.player.wx, game.player.wy)
            ]
            self.app.draw()
            if game.game_over:
                break
            hostiles = [
                c for c in game.visible_creatures()
                if c.is_hostile_to(game.player)
            ]
            if hostiles:
                game.log.warn("You are ambushed!")
                break
        self.route = []
        self.done = True
