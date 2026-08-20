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
    ("v", "move quietly; attack unseen for an ambush"),
    ("Z", "raise the dead, if you have learned how"),
    ("P", "perform a song, poem or dance you know"),
    ("s", "search, and read the tracks on the ground"),
    ("m", "mount or dismount"),
    ("U", "disarm a trap you have found"),
    ("B", "set fire to what is beside you"),
    ("E", "tame the animal beside you"),
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
  b      build. A still first, then a farm plot, then beds, then a tavern.
         A farm plot has to stand on soil, and the soil is under the map
         rather than on it: dig a room a level or two down and put it there.
  p      place a stockpile so loose goods get carried indoors.
  o      queue work at a workshop. A still with a repeating 'brew ale' order is
         the difference between a fortress and a graveyard.

  m      the militia: raise squads, arm them, order them about
  w      mark the safe burrow civilians retreat into
  n      paint a pasture for the livestock
  h      health: who is hurt and who can treat them
  c      crime: the sheriff's book, trials and pardons
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

SOIL

Nothing grows on rock. Every map has a sheet of soil a level or two under the
surface -- loam in the green places, sand in the desert, mud in a swamp, and
on a glacier nothing at all. There is level ground outside, but nearly all of
it is under trees: clear a stand and you can put a plot on the grass. Or dig a
room out of the soil instead, and the floor the miners leave behind them is
what you farm.

Below the soil there is only stone. If you want to farm down there, flood the
chamber -- a channel from the river, or an aquifer you were going to have to
deal with anyway -- and the water leaves mud on the rock. Mud takes a crop.
Shut the gate, let it drain, and plant. A floor you have already smoothed will
not soak, which is the point of smoothing it.

THE DEAD

Build coffins. A dwarf that dies leaves a corpse, and a corpse hauled to the
refuse pile with the bones and the rubbish is a dwarf you did not bury.

Put up a coffin -- the mason and the carpenter both make them -- and somebody
carries the body to it and closes it. No designation is needed: a coffin and a
corpse are instructions enough. One coffin holds one dwarf. A coffin in a
decent room is a tomb, and worth something to the fortress.

Leave a dwarf lying for a season and it comes back. A ghost walks through the
walls, cannot be fought and cannot be shut out, and everybody near it is
colder and unhappier for it. There is exactly one way to stop it, and it is
the one you should have used in the first place: put the body in the ground.
If the corpse is gone -- burned, butchered, carried off by a thief -- the
dwarf goes with it, and nothing rises.

GLASS

Sand is worth something. Press d then a to mark a patch of sand, and somebody
with the glassmaking labor brings back a bag of it; the desert stays where it
is, so mark it again. A glass furnace burns sand and fuel into green glass
tables, chairs, coffers, cabinets, doors, statues, flasks and trinkets.

It wants no wood, no ore and no mountain. An embark on sand with nothing
growing on it can still furnish itself and still have something to sell the
autumn caravan, which is most of what a desert is for.

WHAT A METAL IS FOR

Gold, platinum, lead and tin make armour, furniture and mechanisms. They do
not make weapons, and the forge will no longer let you put three bars of gold
into a sword that bends on the first parry. Copper, bronze, iron, steel,
silver and adamantine make both.

SMOOTHING AND ENGRAVING

Press d for designations, then s to smooth and e to engrave.

A mason dresses bare rock: walls, and the floors a pick left behind. Soil
takes no chisel, and neither does anything you built. A smoothed room is
worth more to whoever sleeps in it than the same room rough, and it is worth
more again carved -- but a floor you have dressed will never take mud, so a
grand hall is a decision not to farm there.

An engraver carves something that actually happened -- a siege you survived, a
beast somebody killed, a nation founded four hundred years ago -- out of the
same history the legends screen reads from, into a wall or a floor that has
been smoothed first. The look cursor will read it back to you.

Quality depends on the engraver. A masterful engraving makes the room it is in
worth considerably more, and dwarves who walk past good work -- or stand on it
-- are cheered up by it. Rough scratchings do nothing for anybody.

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

The figures in those legends live somewhere, and where they live is a town you
can walk into. The people you meet there are them: ask one about themselves and
they will tell you what the world remembers of them. Retire an adventurer in a
town and the next one you roll can go and find them there.

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

Your forge can make every piece of it. Each uniform names the weapons and
armour it wants, best first, and there is a recipe for all of them -- swords
and long swords, battle axes and great axes, maces and mauls and morningstars,
pikes and halberds, crossbows, and the breastplates, gauntlets, chain leggings
and great helms to go over the top. Costs run with weight: a mace is two bars,
a great axe is five. The clothier does the caps, boots, mittens and socks.

A squad ordered to train is a squad taken off the labour force. Order it to
defend instead if you need the hands back.

Weapon traps do not miss and cannot be parried, and cost you nothing but a
weapon and a mechanic. They are the cheapest defence in the game.

None of that stops a flier. A roc or a demon comes at you in a straight line,
over the moat and the wall and the chasm, and arrives wherever your dwarves
actually are. Terrain is a defence against things with feet. Against wings you
need a roof, or soldiers.

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

FIRE

Trees, saplings and shrubs burn, and so does anything wooden lying on the
ground. Press B with a lit torch in hand to set fire to whatever is next to
you.

Fire spreads to what is beside it, burns down over time and leaves ash. It
will not cross bare rock, so a firebreak is a real thing you can dig. Standing
in one hurts and armour does not help much. It also throws light, which means
you are extremely visible next to one -- worth remembering if you are sneaking.

In the fortress, magma sets fire to anything flammable near it. Keep the
woodpile away from the forge.

FALLING

There is nothing under you but air, and the game now knows it. Step off a
ledge and you go down until something stops you. One level is a step; further
than that hurts, and how much depends on how far — five levels break bones,
ten will usually finish an unarmoured person. Armour helps and does not save
you. Deep water breaks a fall.

Everything falls, not just you: creatures, items, and anybody standing on a
floor that has just been dug out from under them. Channelling normally cuts a
ramp into the level below and is safe; channelling into a space that is
already open is not.

WHAT A FIGHT LEAVES

Cut hard enough and things come off. A severed arm lands where it was taken
and says whose it was; so does everything else a heavy weapon can remove.
Corpses, limbs and blood are all still there when you come back.

LIVING OFF THE LAND

Press N to pick what is growing under or beside you. A shrub is worth picking
and gives you a proper handful; grass is worth searching and usually is not.
Herbalism decides how much you get.

Press Y to fish, with a fishing rod in your pack and open water beside you. It
takes a couple of hours and often catches nothing, and fishing skill decides
how often it does. Not with company.

In the fortress, dwarves with the fishing labor go and stand by the water when
the larder is short of fish, and stop when it is not.

THE FOOD CHAIN

The wilderness feeds itself. Grazers eat grass, predators hunt and scavenge,
and what counts as prey depends on size — a wolf takes a deer but not a bear,
and a pack of wolves will take an elk that one wolf would leave alone.

Prey runs from predators, not only from you, so following a fleeing deer may
show you what it was running from. A hungry enough animal stops caring who is
watching and eats anyway.

NERVE

Nothing fights to the death because it happened to be in the room. A creature
takes courage from whoever is standing with it, loses it when they start
falling, and something that hunts in a pack takes being the last one alive
very badly indeed. Kill two wolves out of four and the rest may not wait
around for you.

Look at something and you are told when it is wavering or about to break.
Goblins, the undead and the great beasts do not care and never run.

In the fortress this cuts both ways: a raid whose nerve goes will turn round
and leave, and the survivors go home rather than dying in your corridor.

FIGHTING WITH YOUR HANDS

Punching, kicking and biting are three different skills — striker, kicker and
biter — and wrestling is for grappling. A wrestler is good at all of them; a
wolf is good at exactly one. Picking the wrestler profession means something
now.

LYING AND WRITING

Boast of your deeds and you speak of what you have really done. With nothing
real to say, you make something up instead, and whether it lands depends on
how good a liar you are against how observant they are. Get caught and they
remember it, and so does everyone who saw.

Carry a blank book and press V to write one. You can only write about what you
know well, history and biography aside, and how deep a work you produce
depends on both your writing and your knowledge of the subject. It takes most
of a day or more, and not with company. Bind a blank book from hide.

WEAR AND REPAIR

Things wear out. A weapon wears from landing blows, armour from stopping them,
and clothes simply from being worn — metal lasts far longer than cloth, and an
artifact never wears at all. A worn weapon hits softer and a worn shirt is
worth less, and when something reaches the end of the scale it falls apart and
is gone.

Carry a whetstone and press X to put an edge back on a blade. It works on
things with an edge — a maul is not blunt, it is a maul — and it takes the
damage back a step rather than making the weapon new.

In the fortress this is why you need a clothier. Dwarves arrive dressed, those
clothes wear through in about a year, and a dwarf in rags is a dwarf with
nothing between it and the winter. The craftsdwarf's workshop sews tunics,
trousers, cloaks and hoods, and makes shoes from hide.

Flint and steel will start a fire without a torch already burning.

WEAPON SPEED

A blow takes as long as the weapon makes it take. Thrusting is quick, chopping
and bashing are slow, and a weapon too heavy for you is slower still -- so the
same maul is a plodding weapon for a dwarf and an ordinary one for somebody
strong enough to carry it easily. Skill buys time back: a legendary hammerer
swings about as often as an untrained swordsman.

The examine screen tells you how many blows a weapon is worth per turn in your
hands, and warns you when it is too heavy for you. Time you spend winding up
is time everything else gets to move, so a great axe means taking more hits
between your own.

None of which makes a light weapon better. A dagger swings half again as often
as an axe and still cannot get through a breastplate: a blow has to be hard
enough to matter before speed matters at all.

COLD AND HEAT

The sidebar shows the temperature where you are standing. It follows the
region, the season, the hour and the weather, and a fire warms the ground
around it -- a camp fire is the difference between a blizzard you walk out of
and one you do not.

What you are wearing is what keeps it off you. A cloak, a hood and boots are
worth more against a hard winter than a suit of iron plate, which insulates
almost nothing and is worse than nothing in high summer. Clothing has been in
the game since the start; this is the reason to put it on.

Cold takes your fingers first: get numb enough and you will lose them. Heat
takes your water instead, so a desert crossing is a question of how much you
can carry. Neither happens all at once -- you get told you are cold long
before it matters, and getting indoors or beside a fire pulls you back faster
than the weather pushed you out.

Underground is the same temperature all year, which is most of why dwarves
live there. A fortress dug deep barely notices winter; one built on the
surface notices it a great deal, and its water freezes over. Ice is slippery.

KIN

The people in the world's history are related to each other. They marry, they
have children who take their family name, heroes and the beasts that killed
them are bound together, and the leaders of warring peoples are enemies. Press
G and open any figure to see who they were to whom.

This matters when you kill somebody. If the dead had family and any of them
are standing nearby, those relatives turn on you where they stand, and their
whole people think less of you for every relative you left behind. Killing a
nobody and killing somebody's father are not the same act.

PERSONALITY

Every dwarf and every person in the world has thirty personality facets and
twenty values, and they are not decoration. How hard a thing lands on somebody
depends on who they are: an anxious dwarf takes a death in the fortress much
harder than a stoic one, and gets over it more slowly.

Values decide what somebody cares about at all. A dwarf who prizes
craftsmanship is lifted by a masterful engraving; one who does not walks past
it. A dwarf who values law is cheered when the sheriff does his job and
angered when a criminal walks free. Half your fortress will be indifferent to
any given thing, which is what makes the other half worth noticing.

Perseverance and discipline show up in how much work gets done. Vengefulness
shows up after a brawl: some dwarves forgive a punch and some never do.

Press u and look at a dwarf, or C in adventure mode, to see who you are
dealing with.

TRAPS AND BAD FOOTING

Tombs were sealed to keep people out, and they were sealed with dart traps,
pits, falling rock, snares and alarms. Ruins have a few and lairs sometimes do.

Every trap starts hidden. Press s to search the ground around you -- that is
the same key that reads tracks -- and your Observer skill decides what you
find. You may also spot one just walking past, but do not count on it. A trap
you have found is drawn as a red ^ and you can walk around it, or press U to
take it apart with Mechanic.

A dart carries venom, a snare wraps you in web, a pit drops you a level, and
an alarm tells everything within forty tiles exactly where you are. Armour
counts against all of them, and a dart that cannot get through your mail does
not poison you either.

Ice is slippery. Crossing it is a roll against your Climber skill and your
agility, and going down costs you the turn -- which matters most when
something is walking towards you.

THE WILD

Animals behave like animals. Deer, rabbits and livestock run when a person
gets near, and how near depends entirely on whether they have noticed you --
so sneaking (v) is how you get inside bowshot of dinner, and the tracks you
read with s are how you find where it went.

Predators that ambush -- foxes, tigers, leopards, snakes, alligators, cave
spiders -- do not charge at you across a field. They wait, hidden, until you
are close, and then they are on you with the ambush bonus. Whether you spot
one first is your Observer skill against its cover. A high Observer is the
difference between being attacked and being stalked.

Rats and bats want your food, not your blood. They run from anything bigger
than they are and take anything edible they pass.

RIDING

Horses, donkeys, mules and camels can be ridden; those and a good many other
animals can be tamed. Stand next to one and press E to try to win it over --
it takes a while, a wild animal minds a great deal more than a village one,
and every refusal makes the next attempt a little harder.

Once an animal is yours, press m to get on and m again to get off. Mounted you
move at the animal's pace rather than your own, carry half again as much, and
cross the world map in about two thirds of the time.

Every solid hit you take while mounted is a roll to stay on. Untrained you
come off most of the time; a good rider almost never does. Being thrown leaves
you on the ground and winded next to whatever hit you, which is the risk that
pays for the speed.

VENOM AND WEBS

Some things that bite you are venomous. Nothing happens at the moment it
lands -- that is what makes venom different from a wound. Then it starts, and
for the next while you are slower, in more pain, and in some cases throwing
up. Toughness shortens it and so does Discipline, because what venom mostly
does is make you stop.

There is no antidote. Somebody with Diagnostician 2 or better can cut and bind
a venomous bite (A) and halve what is left of it, and that somebody can be
you.

Giant spiders and scorpions throw webs. A web is a tile you can see and walk
around; walk into one and you are held until you tear out, which takes a few
turns and some strength. Spinners walk their own webs, so you cannot lead one
into its trap. Being stuck while something walks towards you is the oldest
trap there is and it still works.

STANDING

Every people has its own opinion of you, and its own reasons. Their ethics are
generated with them: some think killing unthinkable, some find it acceptable,
and kobolds think theft is required. The same act therefore costs you
differently depending on whose town you did it in.

Kill somebody who was not trying to kill you, where people can see you, and
the watching people will think less of you -- how much less is their business,
not yours. Do enough of it and they attack on sight. Finish work for a people
and it goes the other way; so does a good performance.

They have to see it. Sneaking (v) hides what you did as well as where you are.

Prices move with standing, and so does how people greet you. Press C to see
where you stand with everybody who has made up their mind.

TRACKS

Everything that walks leaves prints on soft ground -- grass, dirt, sand, mud,
snow. Press s to read the ground around you, or look (x) at any cell.

What you get out of a print is your Tracker skill. Untrained, you can tell
that something passed and nothing else. Trained, in order: which way it went,
what it was, how long ago, how many, and whether it was hurt. A trail of blood
outlasts the footprints and does not care what it fell on.

Blood is the exception: it falls on anything, including bare rock, and lasts
longer than a footprint. On stone it is only blood — there is no print to read
a heading or a species from, and it will not pretend otherwise.

Rock takes no print, so a trail of footprints stops at the cave mouth. Snow holds one for
days and sand loses it by evening. Rain washes the lot away -- go after the
storm, not during it.

SONGS, POEMS AND DANCES

Every civilization invented its own musical, poetic and dance forms, and they
are real things with names, dates and rules. Most of them are about something
that actually happened, so hearing a good one tells you the history the same
way a book does.

Press P to perform one you know. You start knowing a few of your own people's
work. The audience is whoever can see you, and a tavern crowd that liked it
throws coins -- the only money in this game that does not come off a corpse.
Perform badly and somebody will tell you to sit down.

It is a skill, and an honest one: untrained, you are halting, and nothing will
change that but doing it. A musical form asks for a particular instrument by
name; playing it on the wrong one is worse, and on none at all is much worse.
Every tavern keeps a few of the instruments its own people's music calls for,
lying about the room. What is in the room counts, so it is worth looking at
the floor before you start.

Stand in a tavern and other people will perform at you. You can ask anybody to
(talk to them), and hearing something good may teach you the form. The Art tab
of the legends screen (G) lists every form in the world.

The bard class starts with a lute and the skills to use it.

BOOKS AND SECRETS

A book is about something that really happened in this world. Read one (R in
the inventory, or Enter on it) and you are given the world's own record of the
thing: the events, the years, the names. It is the alternative to walking
three hundred miles to find out.

Reading takes real turns, more if you read badly, and you cannot do it while
anything hostile can see you. A second reading of the same book teaches
nothing, and a treatise will only take a skill so far.

A few of them are not books. A slab -- in a tomb, or at the top of a
necromancer's tower -- is the secret of raising the dead. Read it and press Z
over a corpse: it gets up on your side. Lords, priests, merchants and scholars
carry books; the slab is carried by whatever you have to kill to get it.

STEALTH

Press v to move quietly. Whether it works is rolled separately for every
creature that might look at you: your sneak against their observer, plus
distance, whether you are moving, whether they are asleep, and how much light
you are standing in. A lit torch is the single worst thing you can carry while
sneaking, and the status bar says (lit!) when it is the problem.

It is a skill. Untrained and next to somebody, you are seen. A trained rogue in
the dark at a distance is a real chance. Look (x) at anything while sneaking
and the panel says whether it has noticed you.

Attack something that has not noticed you and it is an ambush: it cannot block
or parry, you hardly have to aim, the blow goes into the neck and lands about
two and a half times as hard. Then you are visible, and it is an ordinary
fight.

THE NIGHT

Necromancers raise the dead they can see, including the dwarves you have just
lost defending the gate. Every casualty you take is one more thing to fight,
so a long defence goes badly: go through the thralls and kill the one in the
hat. A body only rises once, and once the necromancer is down it stays down.

A werebeast's bite is a curse. Whoever survives one changes at the next full
moon -- the status bar says FULL MOON, and the units list says TRANSFORMED --
and turns on the fortress until dawn. Watch who came back from that fight.

Some migrants are not what they say they are. A vampire drinks from whoever is
asleep and nearest, and the body turns up three nights later with a murder in
the sheriff's book that has no name attached, because there was nobody in the
room. There is a defence, and it is not a better lock: dwarves who sleep in a
dormitory have witnesses, and dwarves in fine private bedrooms do not.

A witness puts a name in the book. Acting on it is yours: mark a cell with J,
open the units list with u, and press h on whoever you have decided about.
They are taken there and kept there -- no trial, no evidence, no sentence, and
they will not forgive you for it, nor will their friends. Do it to the wrong
dwarf and you have jailed a mason and the deaths go on. Waiting for the law
instead is a real choice and often the wrong one: a sheriff needs eighteen
dwarves, and a vampire is very good at keeping a fortress under eighteen
dwarves.

FRIENDS AND FAMILIES

Build a tavern (b, Workshops) and dwarves with nothing to do go there instead
of standing in a corridor. That is where friendships happen: bonds move where
dwarves already are, and the tavern is simply where everybody idle ends up at
once.

It is also where they perform. A few times a day somebody in the tavern gets
up and does a song, a poem or a dance their people invented, and the room
feels better for it -- or worse, because anybody may perform and your seven
founders are not musicians. Instruments live in the room rather than in
anybody's pack: build a carpenter's shop, make a lute, and haul it in there.
It is worth two grades of quality to whoever plays it. A song will only calm
a dwarf so far, so a tavern is a good reason to build one and never a reason
to build nothing else.

Who gets on with whom is personality, not luck. Compatibility sets a ceiling,
so a merely agreeable pair will be acquaintances for ever however long they
share a room. About a quarter of pairs can become friends, a few can become
close, and a few cannot stand each other at all. Press u and look at a dwarf
to see who it knows.

The pairs who were always going to get on become lovers, lovers marry, and
married couples have children if there is food in store. Children play rather
than work, and at twelve they take up a profession. Weddings and births are
written into the world's history.

When a dwarf dies the fortress grieves for what it lost. A spouse or a child
is devastating; somebody you had met twice is a bad afternoon. This is where
the death spiral comes from, and a fortress with no friendships in it has
nothing to lose and no reason to keep going either.

CRIME AND THE LAW

A dwarf that has had enough breaks a table or hits whoever is nearest, and
both go in the sheriff's book. So does an ignored mandate — the manager
answers for that one, never the mayor. So does the kobold thief who walks in,
takes the nearest thing worth carrying and walks out again. One thief is not
a siege: it raises no alarm, and you find out from the gap where the gem was.

Press c for the book. A fortress of eighteen appoints a sheriff, and only a
sheriff can try anything. The sheriff opens the book every few days. A conviction is four days off the roster per point
of severity — murder is worth four — and it costs you whatever that dwarf was
good at, which is the entire point of having a law. Everybody else is calmer
for seeing it done.

A crime nobody was caught at cannot be tried at all. It stays open for three
months, and every season it is open the fortress thinks about it and gets
angrier. That is the pressure to grow big enough for a sheriff.

You can hold a trial at once instead of waiting for the season, and you can
pardon somebody. A pardon buys your mason back this afternoon, and every other
dwarf spends a season remembering that the law is whatever you say it is.

WHEN IT ENDS

Abandon the fortress, or lose it, and it does not disappear. It becomes a real
site on the world map with everything you built still in place, and the
world's history records its founding, its fall and any artifacts made in it.

Press a on the ending screen to roll an adventurer in the same world and walk
back into your own fortress: the corridors you dug, the workshops you raised,
the goods on the floor and your dwarves lying where they fell.

Somewhere quiet matters. Every people in the world keeps gods of its own --
of war, of the forge, of the deep, of the long dark -- and your dwarves keep
them too. Build an altar in a decent room and it is a temple: dwarves will
walk to it when they have gone a while without, and come out steadier. A
fortress with nowhere to pray never says so; it is just a worse place to live.

As an adventurer, press _ on an altar to pray at it. Ask a priest about
themselves and they will tell you who they hold to, and the Gods tab of the
legends screen lists every one of them.

Your workshops are ruins by then. Look at one and it tells you what it was and
what it was built out of, but a forge with nobody at it is furniture.

Or go back with seven more dwarves. Put the cursor on a fortress that fell and
Enter reclaims it instead of founding somewhere new: the corridors, the
workshops, the goods and the magma sea are exactly where the last expedition
left them, and so are their bodies. The job board is not — that belonged to
dwarves who are dead. Whatever emptied the place may not have left.

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

Unless it has no blood in it. The undead, the things in the deep caverns, the
demon and the forgotten beast do not bleed and do not faint, so none of that
touches them: you stop one by taking it apart, and it stays up until enough of
it is cut away or broken. Bring the right weapon. A skeleton is bones with
nothing on them, and bone shears far more easily than it crushes -- a battle
axe takes one apart, a hammer rings off it. A zombie still has flesh on it, and
a hammer flattens it.

Armour subtracts from the force of a blow according to its material and its
thickness -- and according to how widely the blow arrived. Armour works by
spreading a strike over more of itself than the strike landed on, so the more
you give it to spread, the more it takes. Every attack has a contact area, and
you can read it on the item screen.

An axe hands a mail shirt the whole length of its edge and the mail turns it. A
spear point, a pick or a war hammer hand it a few square millimetres and go
through. That is the whole of the weapon triangle: the edge is for the man with
no armour, the point is for the man who has some.

What your weapon is made of matters for the same reason, and only where things
are hard. Against a man it does not show at all: flesh yields to anything.
Against bone and plate it decides everything. An iron blade will not cut a
skeleton and a steel one will. Copper is heavy and soft and folds on armour.
Adamantine weighs almost nothing, which is a real cost -- it passes through
plate as though it were not there and then arrives behind it carrying very
little -- so it is a light sword against a man and the only thing in the world
that will mark a bronze colossus.

None of that applies to a hammer, and this is the part worth knowing. Stopping
a cut is a question about the armour: either the edge shears it or nothing at
all comes through, and nothing in the weapon table cuts a steel breastplate.
Stopping an impact is a question about where the momentum goes, and the answer
is always "some of it into the man inside". Good armour spreads a great deal of
it -- a breastplate lets through about a seventh of what hits it, mail about a
fifth, and boiled leather does not spread a blunt blow at all -- but no
thickness of steel makes that share nothing.

So: bring an edge to an unarmoured man, a point to one in mail, and a hammer to
the one in plate. Against plate the five best weapons in the game are all
blunt, and a swordsman is reduced to hunting for the gaps.

Armor User is the skill for this, and it is worth training. It takes weight off
what you are wearing, so you dodge and march better in it, and it takes nearly
a third off what a hammer puts through your breastplate -- the difference
between armour that is merely on you and armour you know how to wear.

A point also keeps its force through the tissues instead of spending it, which
is how it reaches a lung behind the ribs. An edge spends everything opening the
width of the wound, which is how it takes an arm off. Neither can do the
other's work.

Edged weapons cut and cause bleeding. Blunt weapons break bones and stun.
Choose accordingly -- or rather, train Fighter and let it choose: skill at arms
is what tells you to thrust at the man in mail instead of swinging at him.

Aim at a body part with 'a' if you want a leg broken or an arm taken off. Aimed
strikes are harder to land.

Arrows and bolts you fire land where they go — in the grass if you missed, or
under whatever you hit — and can be picked up and fired again. Not all of them
survive it: a steel arrow usually does and an obsidian one usually does not, so
walk the ground after a fight before you walk away from it.

Bleeding is what will actually kill you. Carry bandages and use 'A' to bind a
wound the moment the Blood gauge starts dropping; 'D' tells you how many turns
you have left. Splints set broken bones.

You start with three bandages and they do not last a season. When they are
gone, tear up what you are wearing: 'c' and "Tear a bandage" turns any cloth
garment -- a tunic, trousers, a cloak, anything off a corpse -- into four more.
A scratch clots on its own in a few minutes; a deep wound does not clot at all
before it kills you, so bind that one first.

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

Everybody is carrying something, and it is on them when they fall. People
fight with what they were trained in -- an elven archer has a bow and arrows
for it, a marksdwarf a crossbow and bolts, an axedwarf an axe -- and beyond
the weapon they are people: clothes, a coat, bread and cheese, something to
drink, a rope, a torch, a bandage, coins. Archers shoot back, and the arrows
they spend are on the ground afterwards.

Coin is worth carrying. Merchants, smiths, priests and tavern keepers will trade
with you; tavern keepers will also rent you a bed for the night, which is the
only place you can be sure of sleeping safely. People in taverns will travel
with you for a fee -- press 'p' to see your party.

THE WORLD OUTLIVES YOU

The world is saved in a file of its own, and every save writes it back the way
you left it. Retire from the pause menu and your adventurer stays in it alive,
settled where they stood. A fortress that ends becomes a real site on the map,
whether you abandoned it or lost it.

So start a new adventure or a new fortress and, instead of generating a world,
choose one you already have. The list tells you what is waiting in each: who
settled there and is still alive, and what you built and left standing. Travel
to the town your last adventurer retired in and they are in it, by name, and
the tavern will tell you what they did.

The Legends entry on the title screen reads any of those worlds without playing
in it.
"""

SURVIVAL_TEXT = """\
You need to eat, drink and sleep.

Hunger and thirst build slowly, then start taking chunks out of your strength
and agility. Sleep with 'S', but not with enemies nearby.

Fill your skin whenever you pass water. There is a pool or a stream on most
land that gets rain, and none at all in the deserts, the badlands, the
shrublands and the ice -- so top up before you cross one and look at the
rainfall on the travel screen before you set out.

Wounds heal on their own, slowly. Resting ('R') and sleeping heal much faster.
Neither is something you do with company: both want the same quiet the game
asks for before you read a book, and you will be told so if you try.

Bleeding is the urgent problem: if the sidebar's Blood gauge is dropping, break
off the fight. There is a ceiling on how fast a body can lose blood, and past
it a bandage still closes the wound it is tied round but the bleeding does not
slow at all -- the game says "you are bleeding faster than you can bind it"
when you reach it. That is not a cue to bind harder. Bind what you can when
nothing is swinging at you, and when something is, leave.

Leave early. Pain and a broken leg both cut your speed -- and so does what you
are carrying, being tired, poison and the cold -- so the longer you stand there
trading blows, the less able you are to go. Whole, you can hold a wolf at arm's
length across open ground; badly enough hurt you are moving at a fifth of its
speed and the decision has been made for you. The Wounds tab shows your pace
and what is taking it off you.

Know before you start. Fifty of the eighty-one kinds of creature in the world
are quicker than a man on foot. Look at something ('x') and the panel will tell
you whether it is faster than you, along with what it is carrying, what it is
skilled at, how hurt it is and whether it is about to run.

Carrying too much slows you down. Your pack capacity depends on your strength,
and a backpack helps.

Water is water and not a wall. Walk into a river and you swim it: slower than
walking, twice as tiring, and only for as long as your breath lasts. The status
bar says SWIMMING while your head is up and counts down from UNDER 100% once it
is not, and when it reaches nothing you drown. Get to a bank, or to water
shallow enough to stand in, and it all comes back.

What decides how long you have is the Swimmer skill and what you are carrying.
Unencumbered you can cross most things; in a mail shirt you had better be
close to the far side; and in a steel breastplate you cannot swim at all, at
any skill, ever. Take it off or go round. Deep water is worse than ordinary
water, and water to the ceiling -- a flooded room, not a lake -- is nearly
hopeless.

Things live in there. Carp and pike are in the rivers now, and a hippo in one
is not a joke.

Some things do not have to bother. Ravens, eagles, bats, rocs, dragons and
demons fly: they cross water and chasms without a thought and cannot be
cornered by terrain. What they cannot cross is rock, magma or fire, and a room
flooded to the ceiling drowns them like anything else. Their wings are real --
break or sever one and the thing comes out of the sky, which is worth aiming
for on something you cannot otherwise reach.

Press 'c' to make camp: butcher a corpse for meat, bone and hide, build a fire
and cook the meat. Raw meat feeds you far less than a roast.

Torches burn down, but only while they are lit -- press '~' to light one before
you go underground and douse it when you come back out. Underground you can see
almost nothing without a light.

Weather matters. Fog and storms cut how far you can see, cloud and rain darken
the day, and cold weather makes you burn through food faster.

Death is permanent. When you die your character is written into the world's
legends, and the world carries on without you.

You are in those legends from the first turn, not only at the end of it. Kill
something the world has heard of -- a megabeast, a bandit chief, a
necromancer -- and the deed is recorded with your name on it, and your renown
goes up. Finishing work for people counts too.

Renown is worth something. Guards and lords speak to you differently, people
pay a name better than they pay a stranger, and past a certain point they
greet you by name before you have said anything.

And you can stop while you are ahead. Retire from the pause menu and your
adventurer settles down where they stand, alive, as a figure in this world's
history: another adventurer can hear about them, and a fortress in the same
world can read about them in the legends.
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
