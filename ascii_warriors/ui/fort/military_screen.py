"""Raising, arming and ordering the militia."""

from __future__ import annotations

from typing import List

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import ListMenu, MenuItem, choose, header, key_hint
from ...fortress import military as military_mod
from ...fortress.military import ORDER_NAMES, SQUAD_SIZE, UNIFORMS
from ..app import Scene


class MilitaryScene(Scene):
    """Squads, who is in them, and what they are told to do."""

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort
        self.menu = ListMenu(self._items(), per_page=18, auto_hotkeys=False)

    # -- contents ---------------------------------------------------------- #

    def _items(self) -> List[MenuItem]:
        """Squads and their members, then everyone available to enlist."""
        fort = self.fort
        military = fort.military
        items: List[MenuItem] = []
        enlisted = set(military.soldiers())

        for squad in military.squads:
            ready, total = military_mod.readiness(squad, fort)
            items.append(MenuItem([
                Frag("%-22s " % squad.name[:22], colors.UI["title"]),
                Frag("%-12s " % squad.defn.name, colors.UI["accent"]),
                Frag("%d/%d armed  " % (ready, total),
                     colors.UI["good"] if ready == total and total
                     else colors.UI["warn"]),
                Frag(squad.order_name, colors.UI["dim"]),
            ], ("squad", squad.id)))
            for dwarf_id in squad.members:
                d = fort.creatures.get(dwarf_id)
                if d is None:
                    continue
                items.append(MenuItem(self._soldier_row(squad, d),
                                      ("member", dwarf_id)))
            if not squad.members:
                items.append(MenuItem(
                    [Frag("    (nobody)", colors.UI["dim"])],
                    ("empty", squad.id)))

        civilians = [d for d in fort.dwarves() if d.id not in enlisted]
        items.append(header("Available (%d)" % len(civilians)))
        civilians.sort(key=lambda d: -military_mod.combat_level(d))
        for d in civilians:
            items.append(MenuItem([
                Frag("  %-24s " % d.name[:24], colors.UI["fg"]),
                Frag("%-22s " % d.profession[:22], colors.UI["dim"]),
                Frag("combat %d" % military_mod.combat_level(d),
                     colors.UI["accent"]),
            ], ("civilian", d.id)))
        return items

    def _soldier_row(self, squad, d) -> List[Frag]:
        """One soldier's line under its squad."""
        missing = military_mod.wanted_items(squad, d)
        weapon = d.inventory.weapon()
        return [
            Frag("  %-24s " % d.name[:24], colors.UI["fg"]),
            Frag("%-22s " % (weapon.name()[:22] if weapon else "unarmed"),
                 colors.UI["fg"] if weapon else colors.UI["danger"]),
            Frag("%-10s " % ("ready" if not missing
                             else "needs %d" % len(missing)),
                 colors.UI["good"] if not missing else colors.UI["warn"]),
            Frag("combat %d" % military_mod.combat_level(d),
                 colors.UI["accent"]),
        ]

    # -- drawing ----------------------------------------------------------- #

    def draw(self, scr: Screen) -> None:
        """The militia roster."""
        fort = self.fort
        scr.clear(colors.UI["bg"])
        scr.frame(0, 0, scr.width, scr.height,
                  title="The militia of %s" % fort.name)
        alarm = fort.military.alarm
        scr.text_right(scr.width - 2, 0,
                       " ALARM " if alarm else " all clear ",
                       colors.UI["danger"] if alarm else colors.UI["good"])
        self.menu.per_page = max(4, scr.height - 5)
        self.menu.draw(scr, 2, 2, scr.width - 4, scr.height - 5)
        key_hint(scr, 2, scr.height - 2, [
            ("n", "new squad"), (keys.ENTER, "enlist / discharge"),
            ("u", "uniform"), ("o", "orders"), ("r", "rename"),
            ("a", "alarm"), ("x", "disband"), (keys.ESC, "back"),
        ])

    # -- input ------------------------------------------------------------- #

    def handle(self, key: str) -> None:
        """Raise squads, move dwarves in and out, and give orders."""
        fort = self.fort
        military = fort.military
        if key == keys.ESC:
            self.done = True
            return
        if key == "n":
            self._new_squad()
            return
        if key == "a":
            if military.alarm:
                military.all_clear(fort.log)
            else:
                military.sound_alarm(fort.log)
            return

        value = self.menu.selected_value
        if key == keys.ENTER and value:
            self._toggle(value)
            return
        squad = self._squad_for(value)
        if squad is not None:
            if key == "u":
                self._set_uniform(squad)
                return
            if key == "o":
                self._set_order(squad)
                return
            if key == "r":
                self._rename(squad)
                return
            if key == "x":
                if self.app.confirm("Disband %s?" % squad.name):
                    military.disband(squad)
                    self._refresh()
                return
        if self.menu.handle(key) == "cancel":
            self.done = True

    def _squad_for(self, value):
        """The squad the highlighted row belongs to."""
        if not value:
            return None
        kind, ident = value
        if kind in ("squad", "empty"):
            return self.fort.military.squad(ident)
        if kind == "member":
            return self.fort.military.squad_of(ident)
        return None

    def _toggle(self, value) -> None:
        """Enlist a civilian, or discharge a soldier."""
        fort = self.fort
        military = fort.military
        kind, ident = value
        if kind == "member":
            military.discharge(ident)
            d = fort.creatures.get(ident)
            if d is not None:
                d.fort.squad = False
                fort.log.system("%s returns to civilian work." % d.name)
            self._refresh()
            return
        if kind != "civilian":
            return
        if not military.squads:
            self._new_squad()
        if not military.squads:
            return
        squad = self._pick_squad("Enlist into which squad?")
        if squad is None:
            return
        d = fort.creatures.get(ident)
        if d is None:
            return
        if not military.enlist(squad, ident):
            self.app.message("Militia", "%s is full (%d dwarves)."
                             % (squad.name, SQUAD_SIZE))
            return
        d.fort.squad = True
        d.fort.labors.enable("military")
        fort.log.system("%s joins %s." % (d.name, squad.name))
        self._refresh()

    def _pick_squad(self, title: str):
        """Choose one of the existing squads."""
        squads = self.fort.military.squads
        if len(squads) == 1:
            return squads[0]
        items = [MenuItem("%s (%d/%d)" % (s.name, len(s.members), SQUAD_SIZE),
                          s.id) for s in squads]
        chosen = choose(self.app.screen, self.app.term, title, items)
        return self.fort.military.squad(chosen) if chosen else None

    def _new_squad(self) -> None:
        """Raise a squad."""
        from ...data import names as name_data

        uniform = choose(
            self.app.screen, self.app.term, "What sort of squad?",
            [MenuItem([Frag("%-14s " % u.name, colors.UI["fg"]),
                       Frag(", ".join(u.weapons[:2]), colors.UI["dim"])],
                      u.id, desc=u.description)
             for u in UNIFORMS.values()])
        if uniform is None:
            return
        name = name_data.group_name(self.fort.rng, "military")
        squad = self.fort.military.add_squad(name, uniform)
        self.fort.log.good("%s has been raised." % squad.name)
        self._refresh()

    def _set_uniform(self, squad) -> None:
        """Change what a squad wears."""
        chosen = choose(
            self.app.screen, self.app.term, "Uniform for %s" % squad.name,
            [MenuItem(u.name, u.id, desc=u.description)
             for u in UNIFORMS.values()])
        if chosen:
            squad.uniform = chosen
            self.fort.log.system("%s will carry %s." % (
                squad.name, UNIFORMS[chosen].name.lower() + " gear"))
            self._refresh()

    def _set_order(self, squad) -> None:
        """Tell a squad what to do."""
        items = [
            MenuItem("Train at the barracks", "train"),
            MenuItem("Defend the fortress", "defend"),
            MenuItem("Station here", "station",
                     desc="Stand at the middle of the current view"),
        ]
        hostiles = self.fort.hostiles()
        if hostiles:
            items.append(MenuItem("Kill the nearest intruder", "kill"))
        chosen = choose(self.app.screen, self.app.term,
                        "Orders for %s" % squad.name, items)
        if chosen is None:
            return
        squad.order = chosen
        if chosen == "station":
            squad.station = self._view_centre()
        if chosen == "kill" and hostiles:
            squad.target = hostiles[0].id
        self.fort.log.system("%s: %s." % (squad.name, ORDER_NAMES[chosen]))
        self._refresh()

    def _view_centre(self):
        """The cell in the middle of whatever the player is looking at."""
        fort = self.fort
        for scene in reversed(self.app.scenes):
            cam_x = getattr(scene, "cam_x", None)
            if cam_x is None:
                continue
            return (cam_x + 30, getattr(scene, "cam_y", 0) + 13, fort.z)
        return (fort.local.width // 2, fort.local.height // 2, fort.z)

    def _rename(self, squad) -> None:
        """Give a squad a name of your own."""
        from ...engine.widgets import prompt_string

        name = prompt_string(self.app.screen, self.app.term,
                             "Name for %s" % squad.name, squad.name)
        if name:
            squad.name = name.strip()
            self._refresh()

    def _refresh(self) -> None:
        """Rebuild the list, holding the cursor still."""
        index = self.menu.index
        self.menu.set_items(self._items())
        self.menu.index = min(index, max(0, len(self.menu.visible_items()) - 1))
