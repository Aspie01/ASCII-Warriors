"""Who is hurt, how badly, and whether anybody can do anything about it."""

from __future__ import annotations

from typing import List

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import ListMenu, MenuItem, header, key_hint, popup
from ...fortress import hospital
from ..app import Scene


class HealthScene(Scene):
    """The hospital ward, as a list."""

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort
        self.menu = ListMenu(self._items(), per_page=18, auto_hotkeys=False)

    def _items(self) -> List[MenuItem]:
        """Patients first, then the doctors, then the supply position."""
        fort = self.fort
        items: List[MenuItem] = []
        hurt = hospital.patients(fort)
        items.append(header("Wounded (%d)" % len(hurt)))
        if not hurt:
            items.append(MenuItem(
                [Frag("  Nobody is hurt.", colors.UI["good"])], None))
        for d in hurt:
            critical = hospital.is_critical(d)
            care = hospital.needs_care(d)
            wanted = ", ".join(sorted({t for _p, t in care})) or "rest"
            items.append(MenuItem([
                Frag("  %-22s " % d.name[:22],
                     colors.UI["danger"] if critical else colors.UI["fg"]),
                Frag("blood %3d%%  " % int(d.body.blood_fraction() * 100),
                     colors.UI["danger"] if d.body.blood_fraction() < 0.6
                     else colors.UI["warn"]),
                Frag("%-28s " % d.body.wound_summary()[:28], colors.UI["dim"]),
                Frag(wanted, colors.UI["accent"]),
            ], d.id))

        docs = hospital.doctors(fort)
        items.append(header("Doctors (%d)" % len(docs)))
        if not docs:
            items.append(MenuItem(
                [Frag("  Nobody has the medicine labor enabled.",
                      colors.UI["danger"])], None))
        for d in docs:
            items.append(MenuItem([
                Frag("  %-22s " % d.name[:22], colors.UI["fg"]),
                Frag("dressing %d  suturing %d  bone-setting %d" % (
                    d.skills.level("wound_dressing"),
                    d.skills.level("suturing"),
                    d.skills.level("bone_setting")), colors.UI["dim"]),
            ], d.id))

        beds = hospital.hospital_beds(fort)
        items.append(header("The ward"))
        items.append(MenuItem([
            Frag("  %d hospital beds, " % len(beds),
                 colors.UI["fg"] if beds else colors.UI["warn"]),
            Frag("%d bandages, " % fort.stock_count("bandage"),
                 colors.UI["fg"] if fort.stock_count("bandage")
                 else colors.UI["danger"]),
            Frag("%d splints" % fort.stock_count("splint"), colors.UI["fg"]),
        ], None))
        return items

    def draw(self, scr: Screen) -> None:
        """The ward list."""
        scr.clear(colors.UI["bg"])
        scr.frame(0, 0, scr.width, scr.height,
                  title="Health in %s" % self.fort.name)
        self.menu.per_page = max(4, scr.height - 5)
        self.menu.draw(scr, 2, 2, scr.width - 4, scr.height - 5)
        key_hint(scr, 2, scr.height - 2, [
            (keys.ENTER, "look closer"), (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Inspect a patient, or leave."""
        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result != "select":
            return
        cid = self.menu.selected_value
        creature = self.fort.creatures.get(cid) if cid else None
        if creature is None:
            return
        lines: List = list(creature.body.status_lines())
        care = hospital.needs_care(creature)
        if care:
            lines.append("")
            lines.append(Frag("Wants", colors.UI["accent"]))
            for part_id, treatment in care[:6]:
                part = creature.body.part(part_id)
                lines.append("  %s: %s" % (
                    part.name if part else part_id, treatment))
        popup(self.app.screen, self.app.term, lines,
              title=creature.display_name(),
              width=min(self.app.screen.width - 4, 64))
