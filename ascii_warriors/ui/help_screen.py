"""The help screen."""

from __future__ import annotations

from typing import List, Tuple

from ..engine import colors, keys
from ..engine.screen import Frag, Screen
from ..engine.widgets import Tabs, key_hint, scroll_view
from .app import Scene

TABS = ["Controls", "Fortress", "Combat", "The world", "Survival"]

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

FORTRESS_TEXT = """\
Fortress mode is the other half of the game. You do not control a dwarf; you
control the fortress, and the dwarves get on with it.

Seven dwarves arrive with a wagon. Time runs by itself -- Space pauses it, + and
- change the speed. Scroll with the arrow keys, and use < and > to move up and
down through the rock.

WHAT TO DO FIRST

  d      designate. Press d again for mining, i for a stairway. Enter marks one
         corner of a rectangle, Enter again paints it. Dig into a hillside.
  b      build. A still first, then a farm plot, then beds.
  p      place a stockpile so loose goods get carried indoors.
  o      queue work at a workshop. A still with a repeating 'brew ale' order is
         the difference between a fortress and a graveyard.

  m      the militia: raise squads, arm them, order them about
  w      mark the safe burrow civilians retreat into
  n      paint a pasture for the livestock
  h      health: who is hurt and who can treat them
  L      levers: link them to gates and pull them
  u      units: everybody, what they are doing, and their labors
  z      stocks: everything you own
  j      what work is outstanding
  k      look at whatever is in the middle of the view
  t      trade, when the autumn caravan is here

FOOD AND DRINK

A dwarf drinks about one unit a day and eats about one. You embark with a
fortnight of both. A farm plot planted with plump helmets feeds roughly six
dwarves; a second plot gives you the surplus a still needs.

Dwarves will drink from a river or a well if the ale runs out. They will
complain about it. On a dry embark there is no such mercy: brew, or die.

Your workshops will not touch the last week of food, and your farmers will not
eat the last of the seed.

ANIMALS

You arrive with two dogs, a cat, two cows and two sheep. The dogs and the cat
belong to particular dwarves and follow them about. The rest are livestock.

Grazers eat grass and there is none on a mountain, so they will eat out of
your food stores instead and tell you they are doing it. Paint a pasture with
n on a patch of grass and they will stay on it and feed themselves. Grass
grows back where it was eaten.

A cow gives milk and a sheep gives wool, on their own, every couple of weeks:
somebody with the farming labor goes out and collects it. Milk becomes cheese
at a kitchen, wool becomes cloth and then bandages at a craftsdwarf's
workshop. A male and a female of the same kind will breed, up to a point.

Press u, pick an animal and press s to mark it for slaughter. A butcher walks
out to it and comes back with meat, hide and bone.

There is wildlife out there too. Most of it is harmless and some of it is
lunch.

THE DEEP

Under the caverns is a sea of magma, and the level above it is warm stone
that tells you so before you cut into it. A pipe of magma stands up out of
the sea into the working levels: mine into the side of that and it comes out
and does not stop.

Magma kills anything that touches it, at any depth, and burns whatever is
lying on the floor. Dwarves will not walk through it and will run from it.
Where magma meets water, both are used up and you get a wall of obsidian --
which is how a careful fortress casts one on purpose.

A magma smelter and a magma forge do the same work as the ordinary kind with
no fuel at all. They have to be built with magma directly underneath them,
which is the whole engineering problem in one sentence.

There is adamantine down there too: a spire of it standing in the sea, worth
more than everything else in your fortress together. It is hollow. Whatever
is inside it has been waiting a long time, and once it is open there is no
closing it.

THE WORLD OUTSIDE

History does not stop while you play. Every season, beasts wake and fall on
towns, heroes rise, wars start and finish, and ruins are resettled. Travellers
bring word of it and the autumn caravan is full of it, and all of it goes into
the legends screen alongside the history you generated.

A fortress worth robbing attracts goblins. A fortress worth a walk across a
continent attracts something older, by name, with everything it has killed
written down. Kill it and the world will record that your fortress is where it
died.

METAL

Veins in the rock are made of something in particular, and they are drawn in
the colour of it: copper and iron are common, tin is what bronze needs, and
gold is mostly for showing off. Coal seams are fuel lying in the wall.

Mining a vein gives you ore, which is a rock until you smelt it. The chain is
short and it is the whole industry:

  wood furnace   log         -> charcoal
  smelter        ore + fuel  -> a bar of that metal
  smelter        copper bar + tin bar + fuel   -> two bronze bars
  smelter        iron bar + flux stone + fuel  -> a steel bar
  forge          bars + fuel -> weapons, armour, bolts, mechanisms

Flux is limestone, marble or chalk. Steel is worth the trouble: the same axe
in steel cuts through armour that copper bounces off.

Nobody smelts or forges unless somebody has the labor for it. The starting
craftsdwarf can run a furnace; a real smith arrives with the migrants, or you
enable the labor yourself with u.

DEFENCE

Goblins come once you have something worth taking. Raise a squad with m, pick
a uniform, and enlist somebody; they will find their own weapons and armour
out of your stockpiles and then train at a barracks until they are dangerous.

A squad ordered to train is a squad taken off the labour force. Order it to
defend instead if you need the hands back.

Weapon traps do not miss and cannot be parried, and cost you nothing but a
weapon and a mechanic. They are the cheapest defence in the game.

When something hostile appears the alarm raises itself and your civilians run
for the burrow you painted with w. Your soldiers do not.

An army is not "some goblins". It is sent by a civilization that exists in the
legends screen, led by somebody with a name, armed to whatever that nation's
metalworking runs to, and it can only be as large as the nation is. Kill
enough of them and the rest break and run for the edge of the map.

Winning costs them: the dead come off the population that raised them, so the
next army from that nation is smaller. It is the only thing a fortress does
that makes the world easier. All of it goes into the legends, including the
line about your fortress being overrun, if it comes to that.

WATER

Water has depth, from one to seven. You can wade through two and you drown in
seven. It falls, it spreads, and it does not go away on its own underground.

Rivers and lakes hold their water until you break the bank. Channel a trench
to one and it pours in for as long as you leave the trench there.

Some rock is wet. Cut into an aquifer and it leaks for ever: the only answers
are to wall it off, to drain it downward, or to dig somewhere else.

A shut floodgate, drawbridge, door or hatch holds water back. Link one to a
lever with L, then pull the lever, and a dwarf will walk over and throw it.
The same drawbridge that keeps the water out keeps the goblins out.

Dwarves will not path through water deep enough to swim in, so a flooded
corridor cuts your fortress in half whether you meant it to or not.

THE WOUNDED

Bleeding kills in minutes, so a hospital is a race. Build hospital beds, keep
bandages in stock, and turn the medicine labor on for somebody who is not
otherwise busy. The nearest doctor is sent immediately, without waiting for
the ordinary job scan.

A dwarf that is hurt stops working and lies down. Resting closes wounds on its
own, slowly. A bandage does it at once, which is the difference between a
scar and a funeral.

ROOMS AND NOBLES

Furniture makes rooms, and rooms make dwarves happy. A bed in a corridor is a
meagre bedroom; the same bed in a smoothed room with a door, a cabinet and a
statue is a great one, and the dwarf sleeping in it says so every season.

As the fortress grows it appoints a manager, a broker, a chief medical dwarf,
a sheriff and eventually a mayor. The mayor will demand things. Ignoring the
demands makes the mayor furious, and a furious dwarf in a fortress full of
unhappy dwarves is how tantrums start: broken furniture, then somebody going
berserk with an axe.

WHEN IT ENDS

Abandon the fortress, or lose it, and it does not disappear. It becomes a real
site on the world map with everything you built still in place, and the
world's history records its founding, its fall and any artifacts made in it.

Press a on the ending screen to roll an adventurer in the same world and walk
back into your own fortress: the corridors you dug, the workshops you raised,
the goods on the floor and your dwarves lying where they fell.

WHAT WILL GO WRONG

Migrants arrive each spring and autumn if word of your wealth has spread, and
they eat as much as anybody. Goblins come once you have something worth taking.
Dwarves who sleep on the floor, eat without a table and run out of drink become
miserable; a miserable fortress is a short one.

Sooner or later a dwarf will be seized by a strange mood, claim a workshop, and
emerge with an artifact nobody asked for.

When the last dwarf dies the fortress falls, and its fall is written into the
world's history where an adventurer can later come and find the ruins.

Losing is fun.
"""

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
The world is generated once, and then it keeps going without you.

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

And it is still happening. Every season that passes while you play, the world
takes another turn: another town sacked, another hero risen, another war
declared or ended. Word of it reaches you on the road and in taverns, and it
goes into the same legends screen.

Quests come from the same place. When a tavern keeper asks you to kill a beast,
that beast exists, has a name, has a history, and is somewhere on the map --
and it is not waiting for you. Take a season getting there and you may hear
that somebody else has already done it, in which case the job is off.

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
            text = {1: FORTRESS_TEXT, 2: COMBAT_TEXT, 3: WORLD_TEXT,
                    4: SURVIVAL_TEXT}[idx]
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
