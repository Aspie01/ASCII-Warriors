# ASCII Warriors

Two games in one world, in the spirit of Dwarf Fortress, for Windows and Linux.
Build a fortress and try to keep seven dwarves alive in it, or walk out into the
same world alone as an adventurer.

The world is generated once — continents, rivers, biomes, civilizations — and
then a few hundred years of history are simulated: kings crowned, wars declared,
settlements burned, artifacts forged and stolen, megabeasts waking up and eating
their way across the map until somebody kills them. Then you walk into it.

Everything you hear in a tavern is a real event that really happened to a real
figure who may still be out there. Every quest points at something that exists.
When you die, your character is written into the same legends, and the world
carries on without you.

**No hit points.** Every blow lands on a specific body part and drives force
through skin, fat, muscle and bone in turn. You die because something vital was
destroyed, because your head came off, or — most often — because you bled out.

## Fortress mode

Seven dwarves, a wagon, and a mountain. You do not control a dwarf; you paint
designations on the rock, put up workshops, queue orders, and the dwarves work
out the rest for themselves — badly, and eventually fatally.

```
[x3] z-4 | 12th of Slate, 125, 14:20 (Spring)          Mountainhome
.....TT........###########                            |12th of Slate, 125
....T.........##.........##                           |14:20  Spring
.............##...CCC...S.#                           |rain
.......@.....#....CCC...S.#                           |
............##....CCC...S.#                           |Dwarves 11
...@........#.............#                           |Wealth  8412
............#..xxxxxxxx...#                           |Jobs    23
.....@......#..xxxxxxxx...#                           |
............#..===...===..#                           |Stocks
...T........##............#                           |  Drink   312        28 days
.............###.......####                           |  Food    241        21 days
...............#########                              |  Stone   180        44 wood
                                                      |
                                                      |Mood [=========-----------]
                                                      |
                                                      |Working
                                                      |Urist         Mining
                                                      |Dodok         Brewing
                                                      |Litast        Hauling
----------------------------------------------------------------------------------
Zuglar Coalhammer has struck ruby!
A dwarven caravan from the mountainhomes has arrived.
Etur Silvershield has been possessed!
Etur Silvershield has created Goldenpeak, a #steel warhammer#!
```

A dwarf drinks about one unit a day and eats about one. You embark with a
fortnight of both, and no more. A farm plot of plump helmets feeds six dwarves;
a second plot gives the still enough surplus to brew. Get that loop running
before the wagon empties, because a fortress without drink is a short one.

Then migrants arrive and eat it all. Then goblins arrive, and you find out
whether your militia trained. Then somebody is seized by a strange mood and
locks themselves in a workshop; later the mayor demands a statue, nobody
builds it, and the sheriff wants to know whose fault that was.

### One world, two games

When the fortress ends — because you abandoned it, or because the last dwarf
died — it does not disappear. It becomes a real site on the world map, with
everything you built still standing. The world's history records its founding,
its fall, and any artifacts made in it.

Press `a` on the ending screen and you roll an adventurer in the same world.
Travel to your own fortress and walk into it: the corridors you dug, the
workshops you raised, the goods still on the floor, and your dwarves lying
where they fell.

Losing is fun.

```
Urist Boatmurdered | grass | quite content | T318 | 2 tasks
                                                          |Urist Boatmurdered
        ....TT..........                                  |dwarf warrior
       ....TT.........."                                  |
      .....T....g......."                                 |Body  [==================---]
     .........g@g........                                 |Blood [===============------]
     ..........g.........                                 |Food  [=====================]
      ....."..........                                    |Water [==================---]
       ...T............                                   |Rest  [============---------]
                                                          |
                                                          |Wounds
                                                          |left lower arm: broken
                                                          |upper body: cut
                                                          |
                                                          |Wielding
                                                          | *steel battle axe*
                                                          | -iron shield-
                                                          |
                                                          |You see
                                                          | g Snagob the Cruel      1
                                                          | g goblin                1
----------------------------------------------------------------------------------------
You hack the goblin in the left upper arm with a *steel battle axe*, tearing apart
the muscle, shattering the bone, severing it!
The goblin is slain!
Snagob the Cruel stabs you in the left lower arm, tearing the muscle, fracturing the bone!
You are bleeding.
```

## Running it

You need **Python 3.9 or newer**, and nothing else. There are no dependencies.

**Linux / macOS**

```sh
git clone https://github.com/Aspie01/ASCII-Warriors.git
cd ASCII-Warriors
./play.sh
```

**Windows**

```
git clone https://github.com/Aspie01/ASCII-Warriors.git
cd ASCII-Warriors
play.bat
```

Or, on either platform, from the project directory:

```sh
python -m ascii_warriors
```

Install it properly if you prefer, which puts an `ascii-warriors` command on
your PATH:

```sh
pip install .
ascii-warriors
```

A terminal at least 80x24 is required; 100x34 or larger is much nicer.

### Command line

```
--seed TEXT        world seed (any text); omit for a random world
--size SIZE        pocket | small | medium | large | huge
--history YEARS    years of history to simulate (default 120)
--colors MODE      auto | truecolor | 256 | 16 | mono
--unicode          use Unicode box-drawing glyphs instead of ASCII
--load PATH        load a save directly
--list-saves       list saved games and exit
--dump-world FILE  generate a world, write its full history as text, exit
--headless KEYS    run with no terminal, feeding a comma-separated key script
--debug            show tracebacks
```

`--dump-world` is worth trying on its own. It prints the whole timeline:

```sh
python -m ascii_warriors --dump-world - --size small --history 200 | less
```

## Controls

### Fortress mode

| Key | |
|---|---|
| `Space` | pause and unpause time |
| `+` `-` | faster, slower |
| `< >` | up and down a level |
| arrows | scroll the view (`PgUp`/`PgDn`/`Home`/`End` to scroll fast) |
| `d` | designate: dig, channel, stairs, ramp, smooth, chop, gather |
| `b` | build a workshop, furniture, wall or trap |
| `p` `w` `n` | place a stockpile / mark the safe burrow / paint a pasture |
| `o` | queue work orders at a workshop |
| `m` `h` `L` | the militia / health / levers and gates |
| `c` | crime: the sheriff's book, trials and pardons |
| `u` `z` `j` | units / stocks / outstanding jobs |
| `k` `t` | look / trade with the caravan |
| `?` | help |
| `Esc` | menu, save, abandon |

### Adventure mode

| Key | |
|---|---|
| `h j k l` `y u b n` | move; diagonals on `yubn` |
| arrows / numpad | the same, if you prefer |
| `H J K L` `Y U B N` | run until something happens |
| `< >` | climb up / down stairs and ramps |
| `.` or `5` | wait |
| `g` / `,` | pick up one item / everything here |
| `d` `i` | drop / inventory |
| `w` `W` `r` | wield / wear / remove |
| `e` `q` | eat / drink |
| `x` `t` `s` | look / talk / search |
| `S` `R` | sleep eight hours / rest |
| `o` `c` | open a door / make camp (craft, butcher, cook, fire) |
| `~` `A` `D` | light a torch / apply first aid / examine injuries |
| `a` | attack a direction, aiming at a body part |
| `f` `F` | fire a readied bow / throw something |
| `C` `z` `Q` `G` | character / skills / tasks / legends |
| `p` `P` | your party / perform a song, poem or dance |
| `m` `E` | mount or dismount / tame the animal beside you |
| `U` `B` | disarm a trap you have found / set a fire |
| `T` `M` | travel / view the world map |
| `?` | help |
| `Ctrl-S` | save |
| `Esc` | menu, or go back |

## What is in it

**Fortress mode.** Embark on a square of the world with seven dwarves and the
supplies they could carry. Designate rock to be dug out, channel down, carve
stairways and ramps, fell trees, smooth walls. Put up twenty-three kinds of
building across workshops, furniture and construction; queue any of thirty-five
recipes at them. Zone nine kinds of stockpile and dwarves haul goods into them.
Plant farm plots, brew the harvest, forge what you dig up.

Every dwarf has twenty labors you can switch on and off individually, so your
legendary weaponsmith does not spend the winter carrying rocks. The job board
offers each dwarf only the nearest work its labors allow; dwarves look after
their own hunger, thirst and sleep first, fight when cornered, and fall over
when they are too tired to stand.

Time runs in real time at four speeds, and pauses whenever you want to think.
Everything is saved, including who was halfway through what.

**A militia.** Squads of up to ten with a uniform — axedwarf, hammerdwarf,
swordsdwarf, speardwarf or marksdwarf. Soldiers find their own weapons and
armour out of your stockpiles, train at a barracks until they are dangerous,
and can be stationed, sent to defend, or pointed at something specific. The
alarm raises itself when something hostile appears and your civilians run for
a burrow you painted; your soldiers do not. Weapon and spike traps do not miss
and cannot be parried.

**War.** Sieges are acts by civilizations that exist in the world's history:
a named commander, soldiers off that nation's own population, armed to
whatever its metalworking runs to, sent because it is at war with the people
who sent you. An army that has lost enough of itself breaks and runs for the
edge of the map rather than fighting to the last. The dead come off the
population that raised them, so beating one makes the next one smaller — the
only thing a fortress does that makes the world easier — and the legends
screen records who died at your gates, or that your fortress was overrun.

**A hospital.** Bleeding kills in minutes, so treatment is a race. Wounded
dwarves stop working and take to a bed; the nearest dwarf with the medicine
labor is sent immediately rather than waiting for the next job scan. Bandages
stop bleeding at once, splints set bones, sutures close what is already
closed. Rest closes wounds too, slowly, which is not always fast enough.

**Water, and the engineering to control it.** Water has a depth from one to
seven; it falls, it spreads, and underground it does not go away. Rivers and
lakes hold their water until you break the bank, and then they pour in for as
long as the trench is open. Some rock is an aquifer, and cutting into it leaks
for ever.

Dwarves wade through two and drown in seven, and they will not path through
water deep enough to swim in — so a flooded corridor cuts your fortress in
half whether you meant it to or not. Build a floodgate, a drawbridge, a door
or a hatch, link it to a lever, and pull the lever: a dwarf walks over and
throws it. The same drawbridge that keeps the water out keeps the goblins out.

**A metal industry.** Veins are made of something in particular — copper,
iron, tin, silver, gold, coal, gems — decided when the map is made and drawn
in the colour of the metal, so you can dig towards what you want. Mining one
gives ore, and ore is a rock until it is smelted.

A wood furnace burns logs into charcoal. A smelter turns ore and fuel into
bars, copper and tin into bronze, and iron, flux stone and a great deal of
fuel into steel. The forge works in bars: weapons, armour, bolts and
mechanisms, in whatever metal you fed it. The same axe in steel cuts through
armour that copper bounces off, so the militia is only ever as good as the
industry behind it.

**Rooms, nobles and tempers.** Furniture defines rooms and rooms have quality:
a bed in a corridor is a meagre bedroom, the same bed in a smoothed room with
a door, a cabinet and a statue is a great one, and the dwarf sleeping in it
notices every season. A growing fortress appoints a manager, a broker, a chief
medical dwarf, a sheriff and eventually a mayor, who will demand things.
Ignore enough of it and dwarves start breaking furniture, and then each
other.

**Books, and the things written in them.** A book in this world is about
something that actually happened in it — a nation's history, a hero's life, a
monster, a battle at a place you can walk to, the making of a particular
artifact. Read one and you are handed the world's own record of it: the events,
the years, the names. The world has always kept a history that nothing could
read without walking three hundred miles to find out; a book is the other way.

Reading costs real turns, scaled by how well you read, and you cannot do it
with something hostile in sight. Reading the same book twice teaches nothing,
which is why a library beats one very good book, and a treatise can only take
a skill so far — you can read about the sword all winter, but somebody has to
swing one at you eventually.

Some of them are not books. A slab in a tomb or a necromancer's tower is the
secret of raising the dead, cut into stone. Read it and you can raise the
dead: press `Z` over a corpse and it gets up on your side and goes for your
enemies. Lords, priests, merchants and scholars carry books; necromancers and
whatever is buried in a tomb carry the slab, so the secret is something you go
and take rather than something you find lying about.

**Stealth.** Press `v` and you move quietly. Whether that works is a roll made
separately for every creature that might look at you: your sneaking against
their observation, plus how far away you are, whether you are standing still or
walking, whether they are asleep, and — the one that bites — how much light you
are standing in. The torch you need to see the corridor is the thing that gives
you away, and the status bar tells you so.

It is a skill, not a posture. Untrained and adjacent, you are seen almost
always. A rogue four tiles off in the dark is a coin flip. A legendary sneak at
eight tiles in the dark is a rumour. And look at any hostile while sneaking and
the panel tells you plainly whether it has noticed you.

Attacking something that has not noticed you is an ambush: no block, no parry,
you barely have to aim, it goes into the neck, and it hits about two and a half
times as hard. Then it is over — one devastating blow, and after it an ordinary
fight against somebody who now knows exactly where you are. Kobold thieves,
bandits and ambushing wolves have had the skills for this all along; now they
use them, and your dwarves have to actually spot the thief.

**The night.** The world has always generated necromancers, given them towers
and stocked those towers with the dead. Now they use them. A necromancer
raises whatever corpses it can see — including the ones you just made — so a
tower is not a queue of zombies to grind through, it is a fight you lose
slowly until you reach the necromancer. Every casualty you take is one more
thing to fight. A body only rises once, and once the necromancer is down the
dead stay down.

A werebeast's bite is a curse, not a wound. The cursed change at the full
moon, wherever they happen to be standing: in an inn, or in your dining hall.
A cursed dwarf comes off the roster, out of the militia and out of office
until dawn, when it turns back and remembers none of it. Your adventurer keeps
their own side — the character sheet tells you which moon to fear.

And a vampire hides among your migrants. It says nothing when it arrives. It
drinks from whoever is asleep and nearest, a little each night, so somebody
looks peaky for three nights before anybody finds a body — and the murder goes
into the sheriff's book with no name on it, because nobody saw. Unless
somebody did: sleep your dwarves in a dormitory and a witness names the
culprit, while a corridor of fine private bedrooms never catches anyone.

**Friends, families and the tavern.** Build a tavern and the dwarves with
nothing to do go there instead of standing in a corridor, and that is where
your fortress gets friends in it. Who becomes friends with whom is decided by
personality: compatibility sets a ceiling rather than a rate, so an agreeable
pair plateaus as acquaintances and stays that way for ever, about a quarter of
pairs can become real friends, a handful can become close, and a few simply
cannot stand each other.

The ones who were always going to get on become lovers, and lovers marry, and
married couples have children. Children play instead of working — which is how
they end up in the tavern making friends of their own — and on the birthday
they turn twelve they pick up a profession and a pick. Weddings and births go
into the world's history, where an adventurer can read about them three
hundred years later.

And when somebody dies, the fortress grieves for what it actually lost: a
spouse or a child is devastating, a close friend is bad, somebody you had met
twice is a bad afternoon, and an enemy is a guilty sort of relief. That is
where the classic dwarven death spiral comes from, and it should be — a
fortress that never let anybody make a friend has nothing to lose.

**Crime and punishment.** A dwarf at the end of its rope smashes a table or
punches whoever is standing next to it, and now both go in the sheriff's book.
So does an ignored mandate, which the manager answers for and the mayor never
does. So does the kobold who walks in one night, picks up the nearest thing
worth carrying, and walks back out — one thief, not a siege, so it does not
sound the alarm or call up the militia. You find out from the gap where the
gem used to be.

A fortress of eighteen appoints a sheriff, and the sheriff opens the book
every few days: a conviction is days off the roster, which costs you your legendary mason and
settles everybody else down. A crime nobody was caught at cannot be tried at
all, and every season it stays open the fortress thinks about it and gets
angrier. Press `c` for the book — you can hold a trial now instead of waiting
for the season, or pardon somebody and wear what the rest of them think of it.

**Engravings.** Smooth a wall, then carve it. An engraver picks something that
actually happened out of the world's history — the siege you survived last
spring, a beast slain three hundred years before you arrived — and the look
cursor reads it back: *"On the wall is a masterful engraving of Smenok the
goblin. They are fighting. The artwork relates to the battle at Boatspring in
the year 16."* Quality depends on the engraver, good work makes a room worth
more, and dwarves are cheered up by walking past it.

**Animals.** You embark with dogs, a cat, cows and sheep. The pets belong to
particular dwarves and follow them about; the livestock grazes, breeds, gives
milk and wool, and ends up as meat, hide and bone when you mark it for
slaughter. Milk becomes cheese, wool becomes cloth and then bandages.

Grazers need grass, and the classic dwarven embark is a mountain with none, so
they will quietly eat out of your food stores until you paint them a pasture
on something green — and the grass grows back where they ate it. Wildlife
wanders the map on its own account.

**The deep.** Under the caverns is a sea of magma, capped by warm stone that
warns you, with a pipe standing up out of it into the working levels. Magma is
the same fluid simulation as water with three constants changed: thicker, never
drying, and fatal at any depth. It burns what it touches, dwarves refuse to
walk through it, and where it meets water both are spent and you get a wall of
obsidian — which is how a careful fortress casts one deliberately.

A magma smelter and a magma forge do everything the ordinary ones do with no
fuel at all, and must be built with magma directly beneath them: getting it
there is the engineering problem the whole layer exists for.

And there is a spire of adamantine standing in the sea, worth more than
everything else you own. It is hollow. What is inside has been waiting since
before the first fortress, and once the wall is open there is no closing it.

**A world that keeps going.** History does not stop when the game starts. Every
season, wherever you are, beasts wake and sack towns, heroes make names for
themselves, wars are declared and settled, plagues pass through, smiths forge
legends, outlaws gather, and ruins are resettled — all of it written into the
same legends screen as the history you generated.

You hear it as news: travellers bring word to your fortress, the autumn caravan
arrives full of it, and taverns gossip about what happened last season rather
than last century. It has teeth, too. Take too long over a contract to kill a
beast and some other hero will get there first, and your quest fails with word
of who beat you to it. And a fortress rich enough to be worth the walk will
eventually be visited by something out of the legends — by name, with its kills
listed. Kill it, and the world records that your fortress was where it died.

**World generation.** Fractal-noise continents with droplet erosion, ocean by
threshold, temperature from latitude and altitude, orographic rainfall, drainage,
rivers traced downhill to the sea, 22 biomes, named regions with DF-style
savagery and good/evil alignment.

**History.** Five civilizations settle where their people like to live — dwarves
in the mountains, elves in the forest, goblins wherever they can be cruel — then
history runs year by year. Leaders are crowned and die of old age. Wars start,
battles are fought, settlements are conquered or destroyed. Smiths forge named
artifacts. Bandits steal them. Megabeasts wake, sack settlements, and are hunted
down by heroes who sometimes win. Necromancers flee into the wilderness and take
up residence in towers. Plagues sweep through towns. All of it is recorded, and
all of it is browsable in the legends viewer.

**Z-levels.** Each world tile expands into a 64x48 local map spanning eleven
levels: cave systems carved by cellular automata below, ore and gem veins in the
rock, rivers cut into the surface, tree canopies above. Open space shows you what
is on the level below, dimmed by depth, the way Dwarf Fortress does.

**Sites.** Towns with houses, a tavern, a temple, a market, a keep and roads
between them. Dwarven fortresses with a surface hall over carved underground
levels. Goblin dark fortresses ringed by barracks. Necromancer towers with
undead on every floor. Kobold warrens, bandit camps, beast lairs, crypts, ruins
and roadside shrines. Everyone who lives in them is placed where they belong:
the lord in the keep, the tavern keeper behind the bar, the guards on the street.

**Combat.** Real material science. Every material has shear and impact yield and
fracture figures in kilopascals; every body part is built from tissue layers with
their own materials. A strike's momentum comes from your strength, the weapon's
mass, its velocity and your skill. Armour subtracts according to its material and
thickness. What is left goes into the tissues in order.

An iron mail shirt will stop a bronze dagger completely. It will not stop a war
hammer, because a hammer does not need to cut you. A steel battle axe will take
a goblin's arm off in one swing if it gets through. Edged weapons cause bleeding;
blunt weapons break bones and stun. You can dodge, block with a shield and parry.
Aim at a specific body part if you want a leg broken.

A bronze colossus is made of bronze all the way through, and your iron sword will
not do anything to it at all.

**Characters.** Nineteen attributes on a 0–5000 scale with DF's descriptive
ladder ("unbelievably strong", "abysmally clumsy"). Sixty-odd skills that improve
by use, from Dabbling to Legendary+5. Thirty personality facets and twenty
cultural values that decide whether somebody stands and fights, runs, bargains
or takes a swing at you for saying the wrong thing.

**Survival.** Hunger, thirst, sleep, fatigue and stress. Butcher corpses for
meat, bone and hide. Build a fire and cook — raw meat feeds you far less. Fill
your waterskin at rivers and wells. Light a torch before you go underground and
douse it when you come back out; they only burn while lit.

**Field medicine.** Bleeding is what actually kills people, so bandages matter
more than anything else you carry. Bind a wound to stop the bleeding, splint a
broken bone to set it, stitch a deep cut closed. A skilled diagnostician can
tell you exactly how many turns you have before you bleed out. You can treat
your companions too.

**Weather.** Rain, storms, snow, blizzards and fog, chosen by biome and season.
Fog and storms cut how far you can see, cloud darkens the day, and cold weather
makes you burn through food faster.

**Trade and companions.** Merchants, smiths, priests and tavern keepers buy and
sell, at prices your Appraiser and Negotiator skills move in your favour and the
merchant's greed moves back. Tavern keepers rent rooms — the only guaranteed
safe night's sleep. And people in taverns will travel with you for coin: they
follow you between world tiles, fight what you fight, and can be patched up when
they get hurt.

**Renown, and retiring.** Your adventurer is a figure in the world's history
from the first turn, not only when they die. Slay something the world knows —
a megabeast, a bandit chief, a necromancer — and it is recorded with your name
on it and your renown rises; finished work counts too. Renown is visible in
play: guards and lords change their tone, people pay a name better than a
stranger, and past a point they greet you by name. Retire from the pause menu
and your adventurer settles where they stand, alive, in this world's legends —
where the next adventurer, or a fortress in the same world, can read about them.

**Conversation and quests.** Ask about this place, its ruler, its troubles, the
beasts in the region, or for directions, and you get real answers from the
generated history. Ask for work and you get a quest that points at a real
megabeast in a real lair, or a real artifact in a real ruin. Threaten somebody
and they will either talk or attack you.

**Fire.** Trees, saplings, shrubs and anything wooden on the ground will burn.
Set one with a lit torch, and it spreads to what is beside it, burns down over
time and leaves ash — but it will not cross bare rock, so a firebreak is a real
thing you can dig. Standing in a fire hurts and armour helps little; it also
throws light, so you are extremely visible next to one. In the fortress, magma
sets light to anything flammable near it.

**What a fight leaves behind.** Cut hard enough and limbs come off, land where
they were taken and say whose they were. Blood falls on anything — including
the bare rock a footprint will not hold — and outlasts the prints, so a wounded
thing running into a cave can still be followed.

**Living off the land.** Pick what is growing — a shrub gives a handful, grass
mostly gives nothing, and herbalism decides which. Fish, with a rod and open
water, for a couple of hours at a time and often for nothing. In the fortress
dwarves with the fishing labor go to the water when the larder is short.

**A wilderness that feeds itself.** Grazers eat, predators hunt and scavenge,
and size decides what counts as prey — a wolf takes a deer but not a bear, and
a pack takes an elk one wolf would leave alone. Prey runs from predators, not
just from you, so a fleeing deer is worth looking past. Hungry enough, an
animal eats anyway.

**Nerve.** Nothing fights to the death just because it is in the room. A
creature takes courage from whoever stands with it, loses it as they fall, and
a pack animal takes being the last one alive very badly. Kill two wolves of
four and the others may not wait for you. Goblins and the undead never run. In
the fortress a raid that loses its nerve turns round and goes home instead of
dying in your corridor.

**Hands, lies and books.** Punching, kicking and biting are three different
skills, and wrestling is for grappling — so the wrestler profession means
something, and a wolf is good at exactly one thing. Boasting with nothing real
to say is a lie, and whether it lands weighs your skill at it against how
observant they are; get caught and it costs you. And you can write a book —
about what you actually know, as deep as your craft and your knowledge allow,
signed with your name for somebody else to find.

**Things wear out.** A weapon wears from landing blows, armour from stopping
them, clothes from being worn — metal far slower than cloth, artifacts never.
Worn gear hits softer and is worth less, and at the end of the scale it falls
apart. Carry a whetstone to put an edge back on a blade. In the fortress this
is why you need a clothier: dwarves arrive dressed, those clothes last about a
year, and a dwarf in rags has nothing between it and the winter.

**The weight of a blow.** A weapon takes as long to swing as it deserves.
Thrusting is quick, chopping and bashing are slow, and anything too heavy for
you is slower still — the same maul plods for a dwarf and swings normally for
someone strong enough to carry it. Skill buys the time back. Winding up is time
everything else gets to move, so a great axe means taking more hits between
your own — and none of that makes a dagger good, because a blow still has to be
hard enough to get through armour before its speed counts for anything.

**Cold and heat.** The temperature follows the region, the season, the hour and
the weather, and what you are wearing is what keeps it off you — a cloak, a
hood and boots beat a suit of iron plate, which insulates almost nothing and is
worse than useless in high summer. Cold takes your fingers; heat takes your
water. Neither arrives all at once, and a camp fire will pull you back from
either. Underground is the same temperature all year, which is most of why
dwarves live there: a fortress dug deep barely notices winter, while one built
on the surface watches its water freeze over — and ice is slippery.

**A history of people, not just deeds.** The figures in the world's history
are related to each other: they marry, have children who carry the family
name, and heroes are bound to the beasts that killed them. Kill somebody with
a family and any relative standing nearby turns on you on the spot, while
their whole people think less of you for each one you left behind — killing a
nobody and killing somebody's father are not the same act.

**Personalities that matter.** Every creature has thirty personality facets
and twenty cultural values, and they decide how the world lands on it. The
same funeral costs an anxious dwarf considerably more than a stoic one, and
the anxious one gets over it more slowly. Values decide what somebody cares
about at all — a dwarf who prizes craftsmanship is lifted by a masterful
engraving and one who does not walks straight past it, so half your fortress
is indifferent to any given thing. Perseverance shows up in the work rate;
vengefulness shows up after a brawl.

**Traps.** Tombs were sealed to keep people out — with dart traps, pits,
falling rock, snares and alarms — and ruins and lairs have their share. Every
one starts hidden; searching finds them, your Observer skill decides how well,
and Mechanic takes them apart. A dart carries venom, a snare wraps you in web,
a pit drops you a level, and an alarm tells everything within forty tiles
where you are. Armour counts, and a dart that cannot get through your mail
does not poison you either. Ice is slippery, and going down costs you the turn.

**A wilderness that behaves like one.** Deer, rabbits and livestock run when
you come near, and how near depends on whether they have noticed you — so
stealth is how you get within bowshot of dinner and tracking is how you find
where it went. Ambush predators don't charge across open ground: they hold
still and hidden until you are close, and whether you spot one first is your
Observer skill against its cover. Rats and bats flee anything bigger and steal
any food they pass.

**Mounts.** Horses, donkeys, mules and camels can be tamed and ridden, and a
good many other animals can be tamed. Taming takes time and every refusal
makes the next try harder; a wild animal minds far more than a village one.
Mounted you move at the animal's pace rather than your own, carry half again
as much, and cross the world in two thirds of the time — but every solid hit
is a roll to stay on, and untrained you come off most of the time.

**Venom and webs.** Venomous things do nothing at the moment they bite you —
that is what separates venom from a wound. Then it starts: slower, in pain,
and for some of them throwing up, for the next several hundred turns.
Toughness and Discipline shorten it, a second dose extends the clock rather
than doubling the effect, and there is no antidote — only somebody who knows
to cut and bind, which halves what is left. Giant spiders and scorpions throw
webs, which are tiles you can see and walk around; walk into one and you are
held until you tear out. Spinners walk their own, so you cannot lead one into
its own trap.

**Standing, and why it differs by people.** Every civilization is generated
with its own ethics — whether killing, theft, trespassing, slavery, eating the
dead and felling trees are unthinkable, acceptable or somewhere between — and
those ethics decide what your deeds cost. The same murder ruins you with a
people who think killing unthinkable and costs nothing among goblins who do
not. They have to see it, and witnesses are found the same way guards notice a
sneak, so a killing nobody saw is a killing nobody minds. Standing moves
prices, changes how you are greeted, and past a point gets you attacked on
sight. Civilizations also go to war with the peoples they disagree with rather
than at random.

**Tracking.** Everything that walks leaves prints on soft ground, and what you
get out of one is your Tracker skill: untrained you can tell only that
something passed, and trained you get its direction, its species, how old the
trail is, how many went by, and whether it was bleeding. Rock takes no print,
so a trail stops at the cave mouth; snow holds one for days and sand loses it
by evening; and rain washes the lot away, which is the first thing in the game
that ever made the weather worth waiting out.

**Songs, poems and dances.** Every civilization invented its own musical,
poetic and dance forms — named in its own language, dated, with rules ("three
voices that answer each other", "paired lines where the second reverses the
first"), and usually *about* something that actually happened in this world.
Perform one with `P`; a tavern crowd that liked it throws coins, which is the
only money in the game that does not come off a corpse. Stand in a tavern and
others will perform at you, and hearing a good one both teaches you the form
and tells you the history behind it. A musical form asks for a particular
instrument by name, and playing it on the wrong one shows. In the fortress,
the tavern you built for friendships is also where somebody gets up a few
times a day and performs — well, if you gave them the skill and hauled an
instrument in there, and badly if you did not.

**79 creatures**, from rats and chickens through wolves, bears and alligators to
trolls, minotaurs, hydras, dragons, bronze colossuses and procedurally generated
forgotten beasts with their own names, shapes, materials and special abilities.

## Development

```sh
python -m unittest discover -s tests -v     # 347 tests
python -m tools.smoke                       # headless adventure play-through
python -m tools.smoke --mode fortress       # headless fortress play-through
python -m tools.fuzz --mode fortress        # random keys, looking for crashes
python -m compileall ascii_warriors
```

`tools/smoke.py` boots the whole game against a scripted fake terminal, plays
through every screen and prints the final frame. It needs no tty, which is how
CI runs it on Windows and Linux.

The module contract lives in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Layout:

```
ascii_warriors/
  engine/   terminal, screen buffer, widgets, rng, geometry,
            noise, pathfinding, field of view, turn scheduler
  data/     materials, body plans, items, creatures, biomes,
            calendar, names, descriptive text
  world/    world generation, civilizations, history simulation,
            local maps, site building, legends
  game/     attributes, skills, personality, bodies, combat, items,
            inventory, needs, entities, AI, actions, crafting,
            quests, conversation, game state, saving
  ui/       the screens
```

Saves are gzipped JSON in `%APPDATA%\ASCIIWarriors\saves` on Windows and
`~/.local/share/ASCIIWarriors/saves` on Linux. Set `ASCII_WARRIORS_SAVE_DIR` to
put them somewhere else.

## Notes on the terminal

There is no `curses` here — it does not exist on Windows. `engine/terminal.py`
does raw input and ANSI output itself: `termios` and `select` on POSIX, and
`ctypes` plus `msvcrt` on Windows, where it enables virtual-terminal processing
and switches the console to UTF-8. Rendering diffs each frame against the last
and emits only the cells that changed.

Colour is auto-detected — 24-bit if the terminal advertises it, 256 or 16 if
not, monochrome when piped to a file. `NO_COLOR` is respected. Glyphs are pure
ASCII by default so nothing depends on your font; `--unicode` turns on nicer box
drawing.

## License

MIT. See [LICENSE](LICENSE).
