"""Who is in the fortress, what they are doing, and what they will do."""

from __future__ import annotations

from typing import List

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import ListMenu, MenuItem, header, key_hint, popup
from ...fortress import dwarf as dwarf_mod
from ...fortress.labors import CATEGORIES, LABORS, profession_title
from ..app import Scene


def _child(dwarf) -> bool:
    """Too young to hold a pick."""
    from ...fortress import social

    return social.is_child(dwarf)


def _jailed(fort, dwarf) -> bool:
    """Whether this dwarf is off the roster because the sheriff says so."""
    from ...fortress import justice

    return justice.is_jailed(fort, dwarf)


#: How a bond is coloured in the detail panel.
BOND_COLORS = {
    "spouse": "accent2", "lover": "accent2", "child": "accent2",
    "close friend": "good", "friend": "good",
    "annoyed by": "warn", "enemy of": "danger",
}


def _relationships(fort, dwarf, lines: List) -> None:
    """Who this dwarf knows, closest first, into an existing line list."""
    from ...fortress import social

    bonds = [bd for bd in social.bonds_of(fort, dwarf)
             if bd.kind or abs(bd.value) >= 15]
    if not bonds:
        return
    lines.append("")
    lines.append(Frag("Relationships", colors.UI["accent"]))
    for bd in bonds[:8]:
        other = fort.creatures.get(bd.other(dwarf.id))
        if other is None:
            continue
        colour = colors.UI[BOND_COLORS.get(bd.label, "fg")]
        lines.append([
            Frag("  %-11s " % bd.label, colour),
            Frag(other.name, colors.UI["fg"]),
            Frag("" if other.alive else " (dead)", colors.UI["dim"]),
        ])


def _sentence(fort, dwarf) -> str:
    """What a dwarf is serving, and for how much longer."""
    from ...fortress import justice

    for crime in justice.serving(fort):
        if crime.culprit == dwarf.id:
            return "Serving %d days: %s" % (justice.days_left(fort, crime),
                                            crime.description)
    return ""


class UnitsScene(Scene):
    """The list of everybody in the fortress."""

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort
        self.menu = ListMenu(self._items(), per_page=18, auto_hotkeys=False)

    def _items(self) -> List[MenuItem]:
        """One row per dwarf, then anything else that is alive."""
        fort = self.fort
        items: List[MenuItem] = []
        dwarves = sorted(fort.dwarves(), key=lambda d: d.name)
        items.append(header("Dwarves (%d)" % len(dwarves)))
        for d in dwarves:
            items.append(MenuItem(self._row(d), d.id))
        from ...fortress import animals as animal_mod

        herd = sorted(animal_mod.livestock(fort), key=lambda c: c.short_name())
        if herd:
            items.append(header("Animals (%d)" % len(herd)))
            for c in herd:
                items.append(MenuItem(self._animal_row(c), c.id))
        others = [c for c in fort.creatures.values()
                  if getattr(c, "fort", None) is None and not c.body.dead
                  and not (animal_mod.is_animal(c) and not c.animal.wild)]
        if others:
            items.append(header("Others (%d)" % len(others)))
            for c in others:
                colour = (colors.UI["danger"] if c.faction == "hostile"
                          else colors.UI["dim"])
                items.append(MenuItem(
                    [Frag("%-24s " % c.display_name()[:24], colour),
                     Frag(c.faction, colors.UI["dim"])], c.id))
        dead = [c for c in fort.creatures.values() if c.body.dead]
        if dead:
            items.append(header("The dead (%d)" % len(dead)))
            for c in dead:
                items.append(MenuItem(
                    [Frag("%-24s " % c.name[:24], colors.UI["dim"]),
                     Frag(c.body.death_cause or "dead", colors.UI["dim"])],
                    c.id))
        return items

    def _animal_row(self, c) -> List[Frag]:
        """One animal's line: what it is, where it is, and its future."""
        from ...fortress import animals as animal_mod

        fort = self.fort
        what = "%s %s" % ("cow" if c.female else "bull",
                          c.short_name()) if c.defn.id == "cow" else (
            "%s %s" % ("female" if c.female else "male", c.short_name()))
        pasture = fort.pasture(c.animal.pasture)
        where = ("pasture %d" % pasture.id if pasture is not None
                 else "loose")
        if c.animal.owner is not None:
            owner = fort.creatures.get(c.animal.owner)
            where = "with %s" % owner.name.split()[0] if owner else "loose"
        if c.animal.slaughter:
            fate, colour = "for slaughter", colors.UI["danger"]
        elif animal_mod.ready_to_produce(fort, c):
            fate, colour = "ready to tend", colors.UI["good"]
        else:
            fate, colour = "", colors.UI["dim"]
        return [
            Frag("%-22s " % what[:22], colors.UI["fg"]),
            Frag("%-22s " % where[:22], colors.UI["dim"]),
            Frag("%-18s " % fate[:18], colour),
        ]

    def _row(self, d) -> List[Frag]:
        """One dwarf's line."""
        state = d.fort
        name = state.nickname or d.name
        title = self.fort.court.title_of(d.id)
        if title:
            name = "%s the %s" % (name, title)
        if d.changed:
            what, colour = "TRANSFORMED", colors.MAGIC
        elif state.mood:
            what, colour = "possessed", colors.MAGIC
        elif _child(d):
            what, colour = "playing", colors.UI["accent2"]
        elif self.fort.crimes and _jailed(self.fort, d):
            what, colour = "serving time", colors.UI["danger"]
        elif state.job is not None:
            what, colour = state.job.label, state.job.color
        elif d.body.unconscious > 0:
            what, colour = "unconscious", colors.UI["danger"]
        else:
            what, colour = "no job", colors.UI["dim"]
        stress = d.needs.stress
        mood_colour = (colors.UI["good"] if stress < 0 else
                       colors.UI["warn"] if stress < 90 else
                       colors.UI["danger"])
        wounded = d.body.wound_summary()
        return [
            Frag("%-22s " % name[:22], colors.UI["fg"]),
            Frag("%-22s " % profession_title(d)[:22], colors.UI["accent"]),
            Frag("%-18s " % what[:18], colour),
            Frag("%-12s " % d.needs.mood()[:12], mood_colour),
            Frag(wounded[:18] if wounded else "", colors.UI["danger"]),
        ]

    def draw(self, scr: Screen) -> None:
        """The list."""
        scr.clear(colors.UI["bg"])
        scr.frame(0, 0, scr.width, scr.height,
                  title="Units of %s" % self.fort.name)
        self.menu.per_page = max(4, scr.height - 5)
        self.menu.draw(scr, 2, 2, scr.width - 4, scr.height - 5)
        key_hint(scr, 2, scr.height - 2, [
            (keys.ENTER, "look closer"), ("l", "labors"), ("n", "nickname"),
            ("m", "militia"), ("s", "slaughter"), (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Inspect, rename, or change what a dwarf is willing to do."""
        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        creature = self._selected()
        if result == "select" and creature is not None:
            self._describe(creature)
            return
        if key == "s" and creature is not None \
                and getattr(creature, "animal", None) is not None:
            self._slaughter(creature)
            return
        if creature is None or getattr(creature, "fort", None) is None:
            return
        if key == "l":
            self.app.push(LaborScene(self.app, self.fort, creature))
        elif key == "n":
            self._nickname(creature)
        elif key == "m":
            from .military_screen import MilitaryScene

            self.app.push(MilitaryScene(self.app, self.fort))

    def _selected(self):
        """The creature under the cursor."""
        cid = self.menu.selected_value
        return self.fort.creatures.get(cid) if cid is not None else None

    def _slaughter(self, creature) -> None:
        """Mark an animal for the butcher, or change your mind."""
        state = creature.animal
        if state.wild:
            return
        state.slaughter = not state.slaughter
        self.fort.log.system(
            "The %s is marked for slaughter." % creature.short_name()
            if state.slaughter else
            "The %s is spared." % creature.short_name())
        self.menu.set_items(self._items())

    def _nickname(self, creature) -> None:
        """Give a dwarf a name of your own."""
        from ...engine.widgets import prompt_string

        name = prompt_string(self.app.screen, self.app.term,
                             "Nickname for %s" % creature.name)
        if name is not None:
            creature.fort.nickname = name.strip()
            self.menu.set_items(self._items())

    def _describe(self, creature) -> None:
        """A full account of one dwarf."""
        from ...fortress import rooms

        lines: List = list(creature.describe())
        state = getattr(creature, "fort", None)
        if state is not None:
            noble = self.fort.court.position_of(creature.id)
            room = rooms.room_of(self.fort, creature)
            squad = self.fort.military.squad_of(creature.id)
            if noble is not None or room is not None or squad is not None:
                lines.append("")
            if noble is not None:
                lines.append(Frag("The %s of %s" % (noble.defn.title,
                                                    self.fort.name),
                                  colors.UI["accent"]))
            if squad is not None:
                lines.append("Serves in %s as a %s"
                             % (squad.name, squad.defn.name.lower()))
            if room is not None:
                lines.append("Sleeps in %s" % room.name)
            else:
                lines.append(Frag("Has no bedroom", colors.UI["warn"]))
            _relationships(self.fort, creature, lines)
            lines.append("")
            lines.append(Frag("Thoughts", colors.UI["accent"]))
            thoughts = creature.needs.recent_thoughts(6)
            if thoughts:
                for t in thoughts:
                    lines.append("  " + t)
            else:
                lines.append("  Nothing much has happened to it.")
            sentence = _sentence(self.fort, creature)
            if sentence:
                lines.append("")
                lines.append(Frag(sentence, colors.UI["danger"]))
            elif state.job is not None:
                lines.append("")
                lines.append("Currently: %s" % state.job.label)
        popup(self.app.screen, self.app.term, lines,
              title=creature.display_name(),
              width=min(self.app.screen.width - 4, 68))


class LaborScene(Scene):
    """Which jobs one dwarf is willing to take."""

    def __init__(self, app, fort, dwarf) -> None:
        super().__init__(app)
        self.fort = fort
        self.dwarf = dwarf
        self.menu = ListMenu(self._items(), per_page=18, auto_hotkeys=False)

    def _items(self) -> List[MenuItem]:
        """Every labor, grouped, with its state and the dwarf's skill."""
        labors = self.dwarf.fort.labors
        items: List[MenuItem] = []
        for category in CATEGORIES:
            rows = [l for l in LABORS.values() if l.category == category]
            if not rows:
                continue
            items.append(header(category))
            for lab in rows:
                on = labors.has(lab.id)
                level = self.dwarf.skills.level(lab.skill) if lab.skill else 0
                items.append(MenuItem([
                    Frag("[%s] " % ("x" if on else " "),
                         colors.UI["good"] if on else colors.UI["dim"]),
                    Frag("%-20s " % lab.name,
                         colors.UI["fg"] if on else colors.UI["dim"]),
                    Frag(("skill %d" % level) if lab.skill else "",
                         colors.UI["accent"]),
                ], lab.id, desc=lab.description))
        return items

    def draw(self, scr: Screen) -> None:
        """The labor list."""
        scr.clear(colors.UI["bg"])
        title = "Labors: %s" % dwarf_mod.display_title(self.dwarf)
        scr.frame(0, 0, scr.width, scr.height, title=title)
        self.menu.per_page = max(4, scr.height - 5)
        self.menu.draw(scr, 2, 2, scr.width - 4, scr.height - 5)
        key_hint(scr, 2, scr.height - 2, [
            (keys.SPACE, "toggle"), ("a", "all on"), ("z", "all off"),
            (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Toggle labors."""
        labors = self.dwarf.fort.labors
        if key == keys.ESC:
            self.done = True
            return
        if key == "a":
            for lab in LABORS:
                labors.enable(lab)
            self.menu.set_items(self._items())
            return
        if key == "z":
            labors.enabled.clear()
            self.menu.set_items(self._items())
            return
        if key in (keys.SPACE, keys.ENTER):
            value = self.menu.selected_value
            if value:
                labors.toggle(value)
                index = self.menu.index
                self.menu.set_items(self._items())
                self.menu.index = index
            return
        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
