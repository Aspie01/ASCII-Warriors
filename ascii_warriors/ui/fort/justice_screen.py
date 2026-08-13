"""The sheriff's book: who did what, who is serving for it, and who walked."""

from __future__ import annotations

from typing import List

from ...engine import colors, keys
from ...engine.screen import Frag, Screen
from ...engine.widgets import ListMenu, MenuItem, header, key_hint
from ...fortress import justice
from ..app import Scene

#: How the list colours a case by how badly the fortress takes it.
SEVERITY_COLORS = {
    1: colors.UI["warn"],
    2: colors.UI["warn"],
    4: colors.UI["danger"],
}


class JusticeScene(Scene):
    """Every crime the fortress knows about, and what can be done about it."""

    def __init__(self, app, fort) -> None:
        super().__init__(app)
        self.fort = fort
        self.menu = ListMenu(self._items(), per_page=18, auto_hotkeys=False)

    # -- contents ---------------------------------------------------------- #

    def _items(self) -> List[MenuItem]:
        """Open cases first, then sentences, then whatever went cold."""
        fort = self.fort
        items: List[MenuItem] = []
        law = justice.sheriff(fort)
        items.append(header(
            "Sheriff: %s" % (law.name if law is not None else "nobody")))
        if law is None:
            items.append(MenuItem([Frag(
                "  A fortress of 18 appoints one. Until then, no trials.",
                colors.UI["dim"])], None))

        open_cases = justice.open_cases(fort)
        items.append(header("Open cases (%d)" % len(open_cases)))
        if not open_cases:
            items.append(MenuItem(
                [Frag("  Nothing outstanding.", colors.UI["dim"])], None))
        for crime in open_cases:
            trial = ("can be tried" if justice.can_try(fort, crime)
                     else "no suspect")
            items.append(MenuItem([
                Frag("  %-44s " % _clip(justice.describe(fort, crime), 44),
                     SEVERITY_COLORS.get(crime.severity, colors.UI["fg"])),
                Frag("%-13s " % trial, colors.UI["dim"]),
                Frag(_ago(fort, crime), colors.UI["dim"]),
            ], ("open", crime.id)))

        serving = justice.serving(fort)
        items.append(header("Serving (%d)" % len(serving)))
        if not serving:
            items.append(MenuItem(
                [Frag("  Nobody is being held.", colors.UI["dim"])], None))
        for crime in serving:
            items.append(MenuItem([
                Frag("  %-44s " % _clip(justice.describe(fort, crime), 44),
                     colors.UI["fg"]),
                Frag("%d days left" % justice.days_left(fort, crime),
                     colors.UI["accent"]),
            ], ("serving", crime.id)))

        closed = [c for c in fort.crimes
                  if c.convicted and c.until <= fort.ticks]
        cold = justice.cold_cases(fort)
        if closed or cold:
            items.append(header("Closed (%d) and cold (%d)"
                                % (len(closed), len(cold))))
        for crime in closed[-6:] + cold[-6:]:
            items.append(MenuItem([
                Frag("  %-44s " % _clip(justice.describe(fort, crime), 44),
                     colors.UI["dim"]),
                Frag(_outcome(crime), colors.UI["dim"]),
            ], None))
        return items

    # -- drawing ----------------------------------------------------------- #

    def draw(self, scr: Screen) -> None:
        """The book."""
        scr.clear(colors.UI["bg"])
        scr.frame(0, 0, scr.width, scr.height,
                  title="Crime and punishment in %s" % self.fort.name)
        self.menu.per_page = max(4, scr.height - 5)
        self.menu.draw(scr, 2, 2, scr.width - 4, scr.height - 5)
        key_hint(scr, 2, scr.height - 2, [
            (keys.ENTER, "try the case"), ("p", "pardon"), (keys.ESC, "back"),
        ])

    # -- input ------------------------------------------------------------- #

    def handle(self, key: str) -> None:
        """Hold a trial, or let somebody out."""
        if key == keys.ESC:
            self.done = True
            return
        value = self.menu.selected_value
        if key == keys.ENTER and value and value[0] == "open":
            self._try_case(value[1])
            return
        if key == "p" and value and value[0] == "serving":
            self._pardon(value[1])
            return
        if self.menu.handle(key) == "cancel":
            self.done = True

    def _crime(self, crime_id: int):
        """Find a case by id."""
        for crime in self.fort.crimes:
            if crime.id == crime_id:
                return crime
        return None

    def _try_case(self, crime_id: int) -> None:
        """Put one case in front of the sheriff, now, rather than in season."""
        fort = self.fort
        crime = self._crime(crime_id)
        if crime is None:
            return
        law = justice.sheriff(fort)
        if law is None or law.body.dead:
            self.app.message(
                "No sheriff",
                "There is nobody to hold the trial.\n\n"
                "A fortress appoints a sheriff once eighteen dwarves live in "
                "it, by preference somebody who keeps the militia labor.")
            return
        if not justice.can_try(fort, crime):
            self.app.message(
                "No suspect",
                "Nobody was caught at this, so there is nobody to try.\n\n"
                "It will go cold in time. Until it does, the fortress will "
                "keep thinking about it.")
            return
        justice.convict(fort, crime, justice.culprit_of(fort, crime), law)
        self._refresh()

    def _pardon(self, crime_id: int) -> None:
        """End a sentence early, and take what the fortress thinks of it."""
        crime = self._crime(crime_id)
        if crime is None:
            return
        who = justice.describe(self.fort, crime)
        if not self.app.confirm("Pardon: %s?" % _clip(who, 48)):
            return
        justice.pardon(self.fort, crime)
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild the list, holding the cursor still."""
        index = self.menu.index
        self.menu.set_items(self._items())
        self.menu.index = min(index, max(0, len(self.menu.visible_items()) - 1))


def _outcome(crime) -> str:
    """How a closed case ended. The book remembers who walked."""
    if not crime.convicted:
        return "never solved"
    return "pardoned" if crime.pardoned else "served"


def _clip(text: str, width: int) -> str:
    """Cut a line to fit the column."""
    return text if len(text) <= width else text[:width - 1] + "…"


def _ago(fort, crime) -> str:
    """How long ago it happened, in the units a dwarf would use."""
    from ...data.calendar import TICKS_PER_DAY

    days = (fort.ticks - crime.tick) // TICKS_PER_DAY
    if days < 1:
        return "today"
    if days == 1:
        return "yesterday"
    return "%d days ago" % days
