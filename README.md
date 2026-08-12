# ASCII Warriors

An ASCII adventure RPG in the spirit of Dwarf Fortress, for Windows and Linux.

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
| `o` `c` `b` `B` | open door / craft / butcher / build a fire |
| `a` | attack a direction, aiming at a body part |
| `f` `F` | fire a readied bow / throw something |
| `C` `z` `Q` `L` | character / skills / tasks / legends |
| `T` `M` | travel / view the world map |
| `?` | help |
| `Ctrl-S` | save |
| `Esc` | menu, or go back |

## What is in it

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
your waterskin at rivers and wells. Torches burn down, and underground you can
see almost nothing without one.

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
python -m unittest discover -s tests -v     # 201 tests
python -m tools.smoke                       # headless end-to-end play-through
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
