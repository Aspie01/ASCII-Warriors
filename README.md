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
locks themselves in a workshop; later the mayor demands a statue.

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
| `p` | your party |
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

**Conversation and quests.** Ask about this place, its ruler, its troubles, the
beasts in the region, or for directions, and you get real answers from the
generated history. Ask for work and you get a quest that points at a real
megabeast in a real lair, or a real artifact in a real ruin. Threaten somebody
and they will either talk or attack you.

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
