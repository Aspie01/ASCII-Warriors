"""The help screen."""

from __future__ import annotations

from typing import List, Tuple

from ..engine import colors, keys
from ..engine.screen import Frag, Screen
from ..engine.widgets import Tabs, key_hint, scroll_view
from .app import Scene

TABS = ["Controls", "Combat", "The world", "Survival"]

CONTROLS: List[Tuple[str, str]] = [
    ("", "MOVEMENT"),
    ("h j k l  y u b n", "move (vi keys); diagonals on yubn"),
    ("arrows / numpad", "the same, if you prefer"),
    ("H J K L  Y U B N", "run in that direction until something happens"),
    ("< >", "climb up / down stairs and ramps"),
    (". or 5", "wait one turn"),
    ("", ""),
    ("", "ADVENTURING"),
    ("g", "pick up one item"),
    (",", "pick up everything here"),
    ("d", "drop something"),
    ("i", "inventory and equipment"),
    ("w / W", "wield a weapon / wear armour"),
    ("r", "remove something you are wearing"),
    ("e / q", "eat / drink"),
    ("x", "look around with a cursor"),
    ("t", "talk to somebody"),
    ("s", "search the area carefully"),
    ("S", "sleep for eight hours"),
    ("R", "rest a while"),
    ("o", "open or close a door"),
    ("c", "make camp: craft, butcher, cook, build a fire"),
    ("~", "light or douse a torch or lantern"),
    ("A", "apply first aid: bind wounds, set bones"),
    ("D", "examine injuries in detail"),
    ("p", "your party"),
    ("", ""),
    ("", "FIGHTING"),
    ("(move into a foe)", "attack it"),
    ("a", "attack in a direction, aiming at a body part"),
    ("f", "fire a readied bow, crossbow or sling"),
    ("F", "throw something"),
    ("", ""),
    ("", "SCREENS"),
    ("C", "character sheet"),
    ("z", "skills"),
    ("Q", "your tasks"),
    ("G", "legends of this world"),
    ("T", "travel the world map"),
    ("M", "view the world map"),
    ("?", "this help"),
    ("Ctrl-S", "save"),
    ("Ctrl-L", "redraw the screen"),
    ("Esc", "menu / go back"),
]

COMBAT_TEXT = """\
There are no hit points.

Every blow lands on a particular body part and drives force through that part's
tissues in order: skin, then fat, then muscle, then bone. What gets through
depends on the weapon's weight, your strength, your skill, and what the target
is wearing.

A creature dies when something vital is destroyed, when its head or upper body
is severed, or when it bleeds out. That last one is the most common. A deep cut
to a limb will kill a goblin in a minute or two of fighting even if you never
land another blow.

Armour subtracts from the force of a blow according to the material and the
thickness. A steel breastplate will stop a dagger completely. It will not stop
a war hammer, because a hammer does not need to cut you: it crushes the bone
underneath the plate.

Edged weapons cut and cause bleeding. Blunt weapons break bones, stun, and work
through armour. Choose accordingly.

Aim at a body part with 'a' if you want a leg broken or an arm taken off. Aimed
strikes are harder to land.

Bleeding is what will actually kill you. Carry bandages and use 'A' to bind a
wound the moment the Blood gauge starts dropping; 'D' tells you how many turns
you have left. Splints set broken bones.

You can dodge, block with a shield and parry with a weapon. All three improve
with use. So does everything else.
"""

WORLD_TEXT = """\
The world is generated once, and then it is simply the world.

Elevation, rainfall and temperature decide the biomes. Rivers run downhill to
the sea. Civilizations settle where their people like to live: dwarves in the
mountains, elves in the forest, goblins wherever they can be cruel.

Then history runs. Leaders are crowned and die. Wars are declared, battles are
fought, settlements are burned. Megabeasts wake and eat their way through the
countryside until somebody kills them. Smiths forge artifacts, and bandits
steal them.

All of that happened before you arrived, and all of it is written down. Press G
to read it. Talk to people and they will tell you about it: the rumours you
hear are real events involving real figures who are still out there.

Quests come from the same place. When a tavern keeper asks you to kill a beast,
that beast exists, has a name, has a history, and is somewhere on the map.

Press T to travel. Moving between world tiles takes hours and makes you hungry.

Coin is worth carrying. Merchants, smiths, priests and tavern keepers will trade
with you; tavern keepers will also rent you a bed for the night, which is the
only place you can be sure of sleeping safely. People in taverns will travel
with you for a fee -- press 'p' to see your party.
"""

SURVIVAL_TEXT = """\
You need to eat, drink and sleep.

Hunger and thirst build slowly, then start taking chunks out of your strength
and agility. Sleep with 'S', but not with enemies nearby.

Wounds heal on their own, slowly. Resting ('R') and sleeping heal much faster.
Bleeding is the urgent problem: if the sidebar's Blood gauge is dropping, break
off the fight.

Carrying too much slows you down. Your pack capacity depends on your strength,
and a backpack helps.

Press 'c' to make camp: butcher a corpse for meat, bone and hide, build a fire
and cook the meat. Raw meat feeds you far less than a roast.

Torches burn down, but only while they are lit -- press '~' to light one before
you go underground and douse it when you come back out. Underground you can see
almost nothing without a light.

Weather matters. Fog and storms cut how far you can see, cloud and rain darken
the day, and cold weather makes you burn through food faster.

Death is permanent. When you die your character is written into the world's
legends, and the world carries on without you.
"""


class HelpScene(Scene):
    """Scrollable help pages."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.tabs = Tabs(TABS)
        self.offset = 0

    def _lines(self) -> List[Frag]:
        """Build the lines for the active page."""
        idx = self.tabs.index
        out: List[Frag] = []
        if idx == 0:
            for key, desc in CONTROLS:
                if not key and desc:
                    out.append(Frag(desc, colors.UI["accent"]))
                elif not key and not desc:
                    out.append(Frag(""))
                else:
                    out.append(Frag("  %-20s %s" % (key, desc), colors.UI["fg"]))
        else:
            text = {1: COMBAT_TEXT, 2: WORLD_TEXT, 3: SURVIVAL_TEXT}[idx]
            for para in text.split("\n"):
                out.append(Frag(para, colors.UI["fg"]))
        return out

    def draw(self, scr: Screen) -> None:
        """Draw the help page."""
        scr.frame(0, 0, scr.width, scr.height - 1, title="ASCII Warriors - Help")
        self.tabs.draw(scr, 2, 1, scr.width - 4)
        lines = self._lines()
        self.offset = scroll_view(scr, 2, 3, scr.width - 4, scr.height - 6,
                                  lines, self.offset)
        key_hint(scr, 2, scr.height - 2, [
            (keys.TAB, "next page"), ("jk", "scroll"), (keys.ESC, "back"),
        ])

    def handle(self, key: str) -> None:
        """Scroll or change page."""
        if self.tabs.handle(key):
            self.offset = 0
            return
        if key in (keys.DOWN, "j"):
            self.offset += 1
        elif key in (keys.UP, "k"):
            self.offset = max(0, self.offset - 1)
        elif key == keys.PGDN:
            self.offset += 12
        elif key == keys.PGUP:
            self.offset = max(0, self.offset - 12)
        elif key in (keys.ESC, "q", "?"):
            self.done = True
