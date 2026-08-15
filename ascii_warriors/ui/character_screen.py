"""The character sheet: attributes, skills, wounds, thoughts and quests."""

from __future__ import annotations

from typing import List

from ..engine import colors, keys
from ..engine.screen import Frag, Screen
from ..engine.widgets import Tabs, key_hint, scroll_view
from ..game.attributes import ATTR_NAMES, MENTAL, PHYSICAL
from ..game.skills import SKILLS, SKILL_CATEGORIES, level_name
from ..game import skills as skills_mod
from .app import Scene

TABS = ["Character", "Skills", "Wounds", "Tasks", "Thoughts"]


#: How many of an attribute's skills to name on the character sheet. Two,
#: because the point is to say what the number is for, not to list fifteen
#: crafts at somebody.
HELPS_SHOWN = 2


def _helps_with(creature, attr: str) -> str:
    """The skills this creature actually has that *attr* helps, best first.

    Every attribute governs skills and now something reads that, so the
    character sheet can finally say which. Only trained ones: telling a
    peasant that willpower governs Leadership is a manual, not a sheet.
    """
    have = []
    for sid in skills_mod.governed_by(attr):
        level = creature.skills.level(sid)
        if level > 0:
            have.append((level, SKILLS[sid].name))
    if not have:
        return ""
    have.sort(key=lambda kv: (-kv[0], kv[1]))
    names = [n for _lv, n in have[:HELPS_SHOWN]]
    more = len(have) - len(names)
    tail = " +%d more" % more if more else ""
    return "helps %s%s" % (", ".join(names), tail)


class CharacterScene(Scene):
    """A paged view of everything about the player."""

    def __init__(self, app, tab: int = 0) -> None:
        super().__init__(app)
        self.tabs = Tabs(TABS, tab)
        self.offset = 0

    def _lines(self) -> List[Frag]:
        """Build the lines for the active tab."""
        game = self.game
        if game is None:
            return []
        p = game.player
        out: List[Frag] = []
        idx = self.tabs.index

        if idx == 0:
            out.append(Frag(p.full_title(), colors.UI["title"]))
            out.append(Frag("%s, %d years old" % (
                "female" if p.female else "male", p.age), colors.UI["dim"]))
            out.append(Frag(""))
            out.append(Frag("A %s of the world of %s." % (
                p.defn.name, game.world.name), colors.UI["fg"]))
            out.append(Frag(""))
            for group, label in ((PHYSICAL, "Physical"), (MENTAL, "Mental")):
                out.append(Frag(label, colors.UI["accent"]))
                for attr in group:
                    desc = p.attributes.describe(attr)
                    out.append(Frag("  %-22s %5d  %s" % (
                        ATTR_NAMES[attr], p.attributes.get(attr), desc),
                        colors.UI["fg"] if desc else colors.UI["dim"]))
                    helps = _helps_with(p, attr)
                    if helps:
                        out.append(Frag("      %s" % helps, colors.UI["dim"]))
                if label == "Physical":
                    out.append(Frag(""))
            out.append(Frag(""))
            out.append(Frag("Temperament", colors.UI["accent"]))
            for line in p.personality.describe():
                out.append(Frag("  " + line, colors.UI["fg"]))
            if p.curse:
                from ..game import night as night_mod

                out.append(Frag(""))
                out.append(Frag("Affliction", colors.MAGIC))
                out.append(Frag("  " + _curse_line(game, p, night_mod),
                                colors.MAGIC))
            out.append(Frag(""))
            out.append(Frag("Deeds", colors.UI["accent"]))
            from ..game import renown as renown_mod

            for line in renown_mod.summary(game):
                out.append(Frag("  " + line, colors.UI["fg"]))
            out.append(Frag("  %d foes slain" % len(p.kills), colors.UI["fg"]))
            from ..game import standing as standing_mod

            out.append(Frag(""))
            out.append(Frag("Standing", colors.UI["accent"]))
            for line in standing_mod.summary(game):
                colour = (colors.UI["danger"] if "-" in line.split()[-1]
                          else colors.UI["good"] if "+" in line
                          else colors.UI["dim"])
                out.append(Frag("  " + line, colour))
            for k in p.kills[-8:]:
                out.append(Frag("    %s" % k, colors.UI["dim"]))

        elif idx == 1:
            known = p.skills.known()
            if not known:
                out.append(Frag("You have learned nothing yet.", colors.UI["dim"]))
            by_cat = {}
            for sid, lv in known:
                by_cat.setdefault(SKILLS[sid].category, []).append((sid, lv))
            for cat in SKILL_CATEGORIES:
                pool = by_cat.get(cat)
                if not pool:
                    continue
                out.append(Frag(cat.capitalize(), colors.UI["accent"]))
                for sid, lv in pool:
                    pct = int(p.skills.progress(sid) * 100)
                    bar = "=" * (pct // 10) + "-" * (10 - pct // 10)
                    out.append(Frag("  %-24s %-16s [%s] %3d%%" % (
                        SKILLS[sid].name, level_name(lv), bar, pct),
                        colors.UI["fg"]))
                    knack = skills_mod.aptitude_word(
                        skills_mod.aptitude(p, sid))
                    if knack:
                        out.append(Frag("      %s" % knack, colors.UI["dim"]))
                out.append(Frag(""))

        elif idx == 2:
            out.append(Frag("Condition", colors.UI["accent"]))
            for line in p.body.describe_state() or ["You are unhurt."]:
                out.append(Frag("  " + line, colors.UI["fg"]))
            out.append(Frag(""))
            out.append(Frag("Blood: %d%%   Pain: %d%%" % (
                int(p.body.blood_fraction() * 100),
                int(min(1.0, p.body.pain_level()) * 100)), colors.UI["dim"]))
            out.append(Frag(""))
            out.append(Frag("Body", colors.UI["accent"]))
            lines = p.body.status_lines()
            for frag in lines:
                out.append(Frag("  " + frag.text, frag.color))

        elif idx == 3:
            if not game.quests.active and not game.quests.completed:
                out.append(Frag("You have taken on no tasks.", colors.UI["dim"]))
            if game.quests.active:
                out.append(Frag("Active", colors.UI["accent"]))
                for q in game.quests.active:
                    out.append(Frag("  " + q.summary(), colors.UI["fg"]))
                    for line in q.detail_lines()[2:]:
                        out.append(Frag("    " + line, colors.UI["dim"]))
                    out.append(Frag(""))
            if game.quests.completed:
                out.append(Frag("Finished", colors.UI["accent"]))
                for q in game.quests.completed[-12:]:
                    colour = (colors.UI["good"] if q.state == "done"
                              else colors.UI["danger"])
                    out.append(Frag("  " + q.summary(), colour))

        else:
            out.append(Frag("Mood: %s" % p.needs.mood(), colors.UI["accent"]))
            out.append(Frag(""))
            out.append(Frag("You are %s, %s and %s." % (
                p.needs.hunger_word(), p.needs.thirst_word(),
                p.needs.sleep_word()), colors.UI["fg"]))
            out.append(Frag(""))
            thoughts = p.needs.recent_thoughts(14)
            if thoughts:
                out.append(Frag("Recently", colors.UI["accent"]))
                for t in thoughts:
                    out.append(Frag("  You %s." % t, colors.UI["fg"]))
            else:
                out.append(Frag("Nothing has moved you lately.", colors.UI["dim"]))
        return out

    def draw(self, scr: Screen) -> None:
        """Draw the sheet."""
        scr.frame(0, 0, scr.width, scr.height - 1, title="Character")
        self.tabs.draw(scr, 2, 1, scr.width - 4)
        lines = self._lines()
        self.offset = scroll_view(scr, 2, 3, scr.width - 4, scr.height - 6,
                                  lines, self.offset)
        key_hint(scr, 2, scr.height - 2, [
            (keys.TAB, "next tab"), ("jk", "scroll"), (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Switch tabs or scroll."""
        if self.tabs.handle(key):
            self.offset = 0
            return
        if key in (keys.DOWN, "j"):
            self.offset += 1
        elif key in (keys.UP, "k"):
            self.offset = max(0, self.offset - 1)
        elif key == keys.PGDN:
            self.offset += 10
        elif key == keys.PGUP:
            self.offset = max(0, self.offset - 10)
        elif key == keys.HOME:
            self.offset = 0
        elif key in (keys.ESC, "q", "C"):
            self.done = True


def _curse_line(game, player, night_mod) -> str:
    """What the character sheet says about a curse, and when it next bites."""
    if player.changed:
        return "You are not yourself tonight. You are a %s." % player.def_id
    if night_mod.cursed_with(player) == "werebeast":
        moon = game.time.moon_phase()
        if night_mod.moon_is_full(game.time):
            return "Werebeast. The moon is full. Do not be near anyone."
        return "Werebeast. The moon is %s; it will not always be." % moon
    return "Vampire. You do not get hungry the way you used to."
