"""The main play view: map, sidebar and message log."""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..engine import colors, keys
from ..engine.colors import Color
from ..engine.screen import Frag, Screen
from ..engine.widgets import MenuItem, choose, key_hint, message_box
from ..game import actions, crafting
from ..world import tiles as tile_data
from .app import Scene
from .sidebar import LOG_HEIGHT, SIDEBAR_WIDTH, draw_log, draw_sidebar, draw_status_line

#: How much dimmer each z-level below the player renders.
DEPTH_FADE = 0.45
#: How much dimmer remembered but unseen terrain renders.
MEMORY_FADE = 0.34


class PlayScene(Scene):
    """The screen you spend the game in."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.cam_x = 0
        self.cam_y = 0
        self.pending: Optional[str] = None

    def on_enter(self) -> None:
        if self.game is not None and self.game.game_over:
            from .menus import DeathScene

            self.app.replace(DeathScene(self.app))

    # -- layout ------------------------------------------------------------ #

    def _layout(self, scr: Screen) -> Tuple[int, int, int, int]:
        """Compute the map viewport rectangle."""
        sidebar = SIDEBAR_WIDTH if scr.width >= 84 else 0
        map_w = scr.width - sidebar - (2 if sidebar else 0)
        map_h = scr.height - LOG_HEIGHT - 1
        return (0, 1, max(10, map_w), max(5, map_h))

    def _center_camera(self, vw: int, vh: int) -> None:
        """Keep the player near the middle of the viewport."""
        game = self.game
        lm = game.local
        p = game.player
        self.cam_x = p.x - vw // 2
        self.cam_y = p.y - vh // 2
        self.cam_x = max(0, min(max(0, lm.width - vw), self.cam_x))
        self.cam_y = max(0, min(max(0, lm.height - vh), self.cam_y))

    # -- drawing ----------------------------------------------------------- #

    def draw(self, scr: Screen) -> None:
        """Render the whole play view."""
        game = self.game
        if game is None:
            return
        mx, my, mw, mh = self._layout(scr)
        self._center_camera(mw, mh)
        draw_status_line(scr, 0, 0, scr.width, game)
        self.draw_map(scr, mx, my, mw, mh)
        if scr.width >= 84:
            draw_sidebar(scr, scr.width - SIDEBAR_WIDTH + 1, 1,
                         SIDEBAR_WIDTH - 1, scr.height - LOG_HEIGHT - 1, game)
        draw_log(scr, 0, scr.height - LOG_HEIGHT, scr.width, LOG_HEIGHT, game)

    def draw_map(self, scr: Screen, ox: int, oy: int, w: int, h: int) -> None:
        """Draw the local map, with depth fading for levels below."""
        game = self.game
        lm = game.local
        p = game.player
        z = p.z

        for sy in range(h):
            wy = self.cam_y + sy
            if wy < 0 or wy >= lm.height:
                continue
            for sx in range(w):
                wx = self.cam_x + sx
                if wx < 0 or wx >= lm.width:
                    continue
                glyph, fg, bg = self._cell(lm, game, wx, wy, z)
                scr.put(ox + sx, oy + sy, glyph, fg, bg)

        # Creatures and items on top.
        for pile_key, pile in game.items_on_ground.items():
            ix, iy, iz = pile_key
            if iz != z or not pile:
                continue
            if (ix, iy, iz) not in game.seen:
                continue
            sx, sy = ix - self.cam_x, iy - self.cam_y
            if not (0 <= sx < w and 0 <= sy < h):
                continue
            item = pile[-1]
            visible = (ix, iy, iz) in game.visible
            colour = item.color if visible else colors.darken(item.color,
                                                              MEMORY_FADE)
            scr.put(ox + sx, oy + sy, item.glyph, colour)

        for c in game.creatures.values():
            if c.z != z or c.body.dead:
                continue
            if (c.x, c.y, c.z) not in game.visible and not c.is_player:
                continue
            sx, sy = c.x - self.cam_x, c.y - self.cam_y
            if not (0 <= sx < w and 0 <= sy < h):
                continue
            glyph, colour = c.glyph_and_color()
            _ch, _fg, bg = scr.get(ox + sx, oy + sy)
            scr.put(ox + sx, oy + sy, glyph, colour, bg)

    def _cell(self, lm, game, x: int, y: int, z: int) -> Tuple[str, Color, Color]:
        """Work out what one map cell should look like."""
        key = (x, y, z)
        seen = key in game.seen
        visible = key in game.visible
        if not seen:
            return (" ", colors.UI["bg"], colors.UI["bg"])

        tid = lm.tile(x, y, z)
        t = tile_data.get(tid)
        glyph, fg = t.glyph, t.color
        bg = t.bg if t.bg is not None else colors.UI["bg"]

        # Looking down through open space, DF style.
        if t.has("OPEN"):
            depth = 0
            zz = z - 1
            while zz >= lm.zmin and depth < 4:
                below = tile_data.get(lm.tile(x, y, zz))
                if not below.has("OPEN"):
                    fade = DEPTH_FADE ** (depth + 1)
                    return (
                        below.glyph,
                        colors.darken(below.color, max(0.18, fade)),
                        colors.darken(
                            below.bg if below.bg is not None else colors.UI["bg"],
                            max(0.15, fade),
                        ),
                    )
                depth += 1
                zz -= 1
            return (" ", colors.UI["bg"], colors.UI["bg"])

        if visible:
            intensity = game.visible.get(key, 1.0)
            light = game.light_at(x, y, z)
            factor = max(0.35, min(1.0, 0.45 + 0.55 * intensity * (0.4 + 0.6 * light)))
            return (glyph, colors.darken(fg, factor), colors.darken(bg, factor))
        return (
            glyph,
            colors.desaturate(colors.darken(fg, MEMORY_FADE), 0.5),
            colors.darken(bg, MEMORY_FADE * 0.7),
        )

    # -- input ------------------------------------------------------------- #

    def handle(self, key: str) -> None:
        """Dispatch one key press to an action."""
        game = self.game
        if game is None:
            return
        if game.game_over:
            from .menus import DeathScene

            self.app.replace(DeathScene(self.app))
            return

        cost = 0
        direction = keys.direction_of(key)

        if key == keys.ESC:
            from .menus import GameMenu

            self.app.push(GameMenu(self.app))
            return

        if direction is not None and not keys.is_run_key(key):
            dx, dy = direction
            if (dx, dy) == (0, 0):
                cost = actions.wait(game)
            else:
                cost = actions.move_or_attack(game, dx, dy)
        elif keys.is_run_key(key):
            cost = self._run(keys.direction_of(key))
        elif key == "<":
            cost = actions.move_z(game, 1)
        elif key == ">":
            cost = actions.move_z(game, -1)
        elif key == ".":
            cost = actions.wait(game)
        elif key == "g":
            cost = actions.pick_up(game, self._choose_ground_item("Pick up what?"))
        elif key == ",":
            cost = actions.pick_up_all(game)
        elif key == "d":
            item = self._choose_inventory("Drop what?")
            cost = actions.drop(game, item) if item else 0
        elif key == "i":
            from .inventory_screen import InventoryScene

            self.app.push(InventoryScene(self.app))
        elif key in ("w", "W"):
            item = self._choose_inventory(
                "Wield what?" if key == "w" else "Wear what?",
                pred=(lambda i: i.is_weapon) if key == "w" else
                (lambda i: i.is_armor),
            )
            cost = actions.equip(game, item) if item else 0
        elif key == "r":
            cost = self._remove()
        elif key == "e":
            item = self._choose_inventory("Eat what?", pred=lambda i: i.is_edible)
            cost = actions.eat(game, item) if item else 0
        elif key == "q":
            item = self._choose_inventory("Drink what?", pred=lambda i: i.is_drink,
                                          allow_none=True)
            cost = actions.drink(game, item)
        elif key == "x":
            from .look_screen import LookScene

            self.app.push(LookScene(self.app))
        elif key == "t":
            cost = self._talk()
        elif key == "T":
            from .travel_screen import TravelScene

            if actions.travel_start(game) == 0 and game.can_travel():
                self.app.push(TravelScene(self.app))
        elif key == "M":
            from .travel_screen import TravelScene

            self.app.push(TravelScene(self.app, view_only=True))
        elif key == "a":
            cost = self._attack()
        elif key == "f":
            cost = self._fire()
        elif key == "F":
            cost = self._throw()
        elif key == "s":
            cost = actions.search(game)
        elif key == "S":
            cost = actions.sleep(game)
        elif key == "R":
            cost = actions.rest(game, 600)
        elif key == "o":
            cost = self._open_close()
        elif key == "c":
            cost = self._craft()
        elif key == "b":
            item = self._choose_inventory("Butcher what?", pred=lambda i: i.is_corpse,
                                          include_ground=True)
            cost = actions.butcher(game, item) if item else 0
        elif key == "B":
            cost = actions.build_fire(game)
        elif key == "C":
            from .character_screen import CharacterScene

            self.app.push(CharacterScene(self.app))
        elif key == "z":
            from .character_screen import CharacterScene

            self.app.push(CharacterScene(self.app, tab=1))
        elif key == "L":
            from .legends_screen import LegendsScene

            self.app.push(LegendsScene(self.app))
        elif key == "Q":
            from .character_screen import CharacterScene

            self.app.push(CharacterScene(self.app, tab=3))
        elif key == "?":
            from .help_screen import HelpScene

            self.app.push(HelpScene(self.app))
        elif key == "C-s":
            from ..game import save as save_mod

            try:
                path = save_mod.save_game(game, game.player.name)
                game.log.system("Saved to %s." % path.name)
            except Exception as exc:  # pragma: no cover - disk failure
                game.log.bad("Save failed: %s" % exc)

        if cost:
            game.player_acts(cost)
            if game.game_over:
                from .menus import DeathScene

                self.app.replace(DeathScene(self.app))

    # -- action helpers ---------------------------------------------------- #

    def _run(self, direction) -> int:
        """Walk in one direction until something interesting happens."""
        game = self.game
        if direction is None:
            return 0
        dx, dy = direction
        steps = 0
        while steps < 25:
            if game.visible_creatures():
                hostiles = [
                    c for c in game.visible_creatures()
                    if c.is_hostile_to(game.player)
                ]
                if hostiles:
                    break
            cost = actions.move_or_attack(game, dx, dy)
            if not cost:
                break
            game.player_acts(cost)
            steps += 1
            if game.game_over:
                break
            if game.items_at(game.player.x, game.player.y, game.player.z):
                break
        return 0

    def _choose_ground_item(self, title: str):
        """Pick one item from the pile underfoot."""
        game = self.game
        p = game.player
        pile = game.items_at(p.x, p.y, p.z)
        if len(pile) <= 1:
            return pile[0] if pile else None
        items = [MenuItem(i.colored_name(), i) for i in pile]
        return choose(self.app.screen, self.app.term, title, items)

    def _choose_inventory(
        self, title: str, pred=None, *, allow_none: bool = False,
        include_ground: bool = False,
    ):
        """Pick an item from the pack, optionally including the ground."""
        game = self.game
        p = game.player
        pool = list(p.inventory.items)
        if include_ground:
            pool += game.items_at(p.x, p.y, p.z)
        if pred is not None:
            pool = [i for i in pool if pred(i)]
        if not pool:
            if allow_none:
                return None
            game.log.info("You have nothing suitable.")
            return None
        items = []
        for i in pool:
            slot = p.inventory.slot_of(i)
            label = i.colored_name()
            if slot:
                label = list(label) + [Frag(" (worn)", colors.UI["dim"])]
            items.append(MenuItem(label, i))
        return choose(self.app.screen, self.app.term, title, items)

    def _remove(self) -> int:
        """Take off a worn or wielded item."""
        game = self.game
        equipped = game.player.inventory.equipped
        if not equipped:
            game.log.info("You are not wearing anything.")
            return 0
        from ..game.inventory import SLOT_NAMES

        items = [
            MenuItem("%-14s %s" % (SLOT_NAMES.get(slot, slot), it.name()), slot)
            for slot, it in equipped.items()
        ]
        slot = choose(self.app.screen, self.app.term, "Remove what?", items)
        return actions.unequip(game, slot) if slot else 0

    def _direction_prompt(self, prompt: str):
        """Ask the player for a direction."""
        from ..engine.widgets import prompt_direction

        return prompt_direction(self.app.screen, self.app.term, prompt)

    def _attack(self) -> int:
        """Attack in a chosen direction, optionally aiming."""
        game = self.game
        d = self._direction_prompt("Attack in which direction?")
        if d is None:
            return 0
        target = game.creature_at(game.player.x + d[0], game.player.y + d[1],
                                  game.player.z)
        part = None
        if target is not None:
            parts = target.body.external_parts()
            items = [MenuItem("Anywhere", None)] + [
                MenuItem(p.name, p.id) for p in parts[:24]
            ]
            part = choose(self.app.screen, self.app.term, "Aim where?", items)
        return actions.attack_dir(game, d[0], d[1], part=part)

    def _target_prompt(self, prompt: str):
        """Pick a target cell with the look cursor."""
        from .look_screen import LookScene

        scene = LookScene(self.app, targeting=True, prompt=prompt)
        self.app.push(scene)
        return scene

    def _fire(self) -> int:
        """Shoot at the nearest visible hostile."""
        game = self.game
        weapon = game.player.inventory.weapon()
        if weapon is None or not weapon.is_ranged:
            game.log.warn("You have no ranged weapon readied.")
            return 0
        targets = [
            c for c in game.visible_creatures() if c.is_hostile_to(game.player)
            or game.player.is_hostile_to(c)
        ]
        if not targets:
            targets = game.visible_creatures()
        if not targets:
            game.log.info("There is nothing to shoot at.")
            return 0
        items = [
            MenuItem("%s (%d away)" % (c.display_name(), game.player.distance_to(c)), c)
            for c in targets[:12]
        ]
        target = choose(self.app.screen, self.app.term, "Shoot at what?", items)
        if target is None:
            return 0
        return actions.fire(game, target.x, target.y)

    def _throw(self) -> int:
        """Throw an item at a visible creature."""
        game = self.game
        item = self._choose_inventory("Throw what?")
        if item is None:
            return 0
        targets = game.visible_creatures()
        if not targets:
            game.log.info("There is nothing to throw at.")
            return 0
        items = [
            MenuItem("%s (%d away)" % (c.display_name(), game.player.distance_to(c)), c)
            for c in targets[:12]
        ]
        target = choose(self.app.screen, self.app.term, "Throw at what?", items)
        if target is None:
            return 0
        return actions.throw(game, item, target.x, target.y)

    def _open_close(self) -> int:
        """Open or shut an adjacent door."""
        d = self._direction_prompt("Open or close in which direction?")
        if d is None:
            return 0
        return actions.open_close(self.game, d[0], d[1])

    def _talk(self) -> int:
        """Start a conversation with an adjacent or nearby person."""
        game = self.game
        p = game.player
        nearby = [
            c for c in game.visible_creatures()
            if p.distance_to(c) <= 2 and c.defn.has("CAN_SPEAK")
        ]
        if not nearby:
            game.log.info("There is no one nearby to talk to.")
            return 0
        target = nearby[0]
        if len(nearby) > 1:
            items = [MenuItem(c.display_name(), c) for c in nearby]
            target = choose(self.app.screen, self.app.term, "Talk to whom?", items)
        if target is None:
            return 0
        if actions.talk(game, target) == 0:
            return 0
        from .dialogs import ConversationScene

        self.app.push(ConversationScene(self.app, target))
        return 0

    def _craft(self) -> int:
        """Choose something to make."""
        game = self.game
        recipes = crafting.available(game.player, game)
        if not recipes:
            game.log.info("You cannot make anything here.")
            return 0
        items = [
            MenuItem("%-26s %s" % (r.name, r.skill), r,
                     desc="needs " + ", ".join(r.needs) if r.needs else "")
            for r in recipes
        ]
        recipe = choose(self.app.screen, self.app.term, "Make what?", items)
        if recipe is None:
            return 0
        return actions.craft_recipe(game, recipe)
