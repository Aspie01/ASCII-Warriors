# ASCII Warriors — Architecture & Module Contract

> **This document is the binding contract between modules.** Every implementer must
> follow the signatures here exactly. If something is not specified, the implementer
> chooses — but must not change anything that *is* specified.

ASCII Warriors is a Dwarf-Fortress-inspired ASCII adventure RPG for Windows and Linux.
Procedural world generation, simulated history, z-levels, body-part combat with
materials and tissues, use-based skills, needs, factions, quests and a legends viewer.

---

## 0. Hard rules

1. **Python 3.9+. Standard library only.** No third-party imports anywhere in
   `ascii_warriors/`, `tests/` or `tools/`. No `curses` (not on Windows).
2. Every module starts with `from __future__ import annotations`.
3. Every module must import cleanly on its own:
   `python -c "import ascii_warriors.<pkg>.<mod>"`.
4. No I/O at import time. No `print()` outside `tools/` and `main.py` error paths.
   The renderer owns stdout.
5. Type hints on all public functions. Docstrings on all public classes/functions.
6. Deterministic: **all** randomness goes through `engine.rng.RNG`. Never import
   the `random` module outside `engine/rng.py`. Never use `time`-based seeding
   except when the user asks for a random seed at the top level.
7. Cross-platform: no POSIX-only calls outside the guarded blocks in
   `engine/terminal.py`. No `os.system`, no ANSI writes outside `engine/terminal.py`.
8. Prefer pure ASCII glyphs. Unicode glyphs only via the optional tileset switch.
9. Keep modules focused; if a file exceeds ~1200 lines, that is a smell but not an error.

## 1. Package layout

```
ascii_warriors/
  __init__.py          __main__.py      main.py
  engine/   colors.py terminal.py keys.py screen.py widgets.py
            rng.py geometry.py noise.py pathfind.py fov.py scheduler.py
  data/     materials.py bodies.py items.py creatures.py biomes.py
            calendar.py names.py descriptors.py
  world/    worldgen.py civ.py history.py legends.py tiles.py localmap.py sitegen.py
  game/     attributes.py skills.py personality.py body.py combat.py item.py
            inventory.py entity.py ai.py needs.py actions.py crafting.py
            quests.py conversation.py state.py save.py log.py
  ui/       app.py menus.py charcreate.py worldgen_screen.py play_screen.py
            look_screen.py travel_screen.py inventory_screen.py character_screen.py
            legends_screen.py help_screen.py dialogs.py sidebar.py
tests/      test_*.py           (stdlib unittest only)
tools/      smoke.py
```

---

## 2. `engine/colors.py`

```python
class Color(NamedTuple):
    r: int; g: int; b: int          # 0..255

def rgb(r: int, g: int, b: int) -> Color
def hexc(s: str) -> Color                     # "#ff8800" or "ff8800"
def blend(a: Color, b: Color, t: float) -> Color     # t=0 -> a, t=1 -> b
def darken(c: Color, f: float) -> Color              # f=0 -> black, 1 -> c
def lighten(c: Color, f: float) -> Color
def to_256(c: Color) -> int                   # nearest xterm-256 index
def to_16(c: Color) -> int                    # 0..15 ANSI index
def desaturate(c: Color, f: float) -> Color
```

Named constants (module level, all `Color`): `BLACK WHITE GRAY LGRAY DGRAY
RED DRED LRED GREEN DGREEN LGREEN BLUE DBLUE LBLUE CYAN DCYAN MAGENTA DMAGENTA
YELLOW DYELLOW BROWN DBROWN ORANGE PURPLE PINK TAN OLIVE SLATE STEEL GOLD
SILVER COPPER BLOOD BONE`.

UI semantic palette dict `UI` with keys: `bg fg dim accent accent2 warn danger good
frame frame_hi title select_bg select_fg shadow`.

## 3. `engine/keys.py`

Key names are **strings**. Printable keys are themselves (`"a"`, `"7"`, `"?"`).
Named keys (module constants with the same string value):

```
UP DOWN LEFT RIGHT ENTER ESC TAB BACKTAB BACKSPACE DELETE INSERT
HOME END PGUP PGDN SPACE F1..F12
```
Control keys are `"C-a"` .. `"C-z"`.

```python
DIR_KEYS: dict[str, tuple[int, int]]
```
Maps movement keys to `(dx, dy)`: vi keys `h j k l y u b n`, arrows `UP DOWN
LEFT RIGHT`, numpad digits `"1".."9"` (`"5"` -> `(0,0)` wait). Both lower-case vi
keys and arrows must be present.

```python
def is_printable(key: str) -> bool
def shifted(key: str) -> str
```

## 4. `engine/terminal.py`

```python
class Terminal:
    def __init__(self, color_mode: str = "auto", unicode_glyphs: bool = False) -> None
        # color_mode in {"auto","truecolor","256","16","mono"}
    def open(self) -> None      # raw mode, alt screen, hide cursor, VT on Windows
    def close(self) -> None     # always safe to call twice; restores everything
    def __enter__(self) -> "Terminal"
    def __exit__(self, *exc) -> None
    @property
    def size(self) -> tuple[int, int]        # (width, height), never smaller than (1,1)
    def poll_resize(self) -> bool            # True if size changed since last call
    def read_key(self, timeout: float | None = None) -> str | None
        # None on timeout. Blocks forever when timeout is None.
    def render(self, screen: "Screen") -> None   # diff-render + flush
    def full_redraw(self) -> None                # force next render to redraw all
    def bell(self) -> None
    def set_title(self, title: str) -> None

class HeadlessTerminal(Terminal):
    """Test/CI driver. Never touches a real tty."""
    def __init__(self, width: int = 100, height: int = 34,
                 keys_script: Sequence[str] = (), loop_keys: bool = False) -> None
    frames: list[list[str]]      # each frame = list of plain-text rows
    def feed(self, keys: Sequence[str]) -> None
    def last_text(self) -> str   # last frame joined with "\n"
```
`HeadlessTerminal.read_key` pops from its queue and raises `QuitSignal` when the
queue is exhausted (unless `loop_keys`). `class QuitSignal(Exception)` lives here.

Windows notes: enable `ENABLE_VIRTUAL_TERMINAL_PROCESSING` (0x0004) via
`ctypes.windll.kernel32.SetConsoleMode`, set output CP 65001, read keys with
`msvcrt.getwch()` (prefix `\x00`/`\xe0` = special). POSIX: `termios`+`tty` cbreak,
`select.select` for timeouts, escape-sequence parser for arrows/function keys,
`SIGWINCH` handling. Both paths must restore terminal state in `close()` and on
uncaught exceptions (`main.py` uses `try/finally`).

## 5. `engine/screen.py`

```python
class Frag(NamedTuple):          # a colored run of text
    text: str
    color: Color = colors.UI["fg"]

Markup = Union[str, Frag, Sequence[Frag]]

class Screen:
    def __init__(self, width: int, height: int) -> None
    width: int; height: int
    def resize(self, width: int, height: int) -> None
    def clear(self, bg: Color = ..., ch: str = " ") -> None
    def put(self, x: int, y: int, ch: str, fg: Color = ..., bg: Color | None = None) -> None
    def get(self, x: int, y: int) -> tuple[str, Color, Color]
    def text(self, x: int, y: int, s: Markup, fg: Color = ..., bg: Color | None = None,
             max_width: int | None = None) -> int          # returns columns written
    def text_center(self, y: int, s: Markup, fg=..., bg=None,
                    x0: int = 0, w: int | None = None) -> None
    def text_right(self, x: int, y: int, s: Markup, fg=..., bg=None) -> None
    def wrapped(self, x: int, y: int, w: int, s: Markup, fg=..., bg=None,
                max_lines: int | None = None) -> int        # returns rows used
    def fill(self, x: int, y: int, w: int, h: int, ch: str = " ",
             fg=..., bg=None) -> None
    def frame(self, x: int, y: int, w: int, h: int, *, title: Markup | None = None,
              fg=..., bg=None, style: str = "single", title_fg=None) -> None
    def hline(self, x, y, w, ch="-", fg=..., bg=None) -> None
    def vline(self, x, y, h, ch="|", fg=..., bg=None) -> None
    def shade(self, x, y, w, h, factor: float) -> None      # darken existing cells
    def blit(self, other: "Screen", x: int, y: int) -> None
    def to_text(self) -> list[str]                          # for tests

def wrap(s: str, width: int) -> list[str]
def frag_len(s: Markup) -> int
def frag_str(s: Markup) -> str
def frag_slice(s: Markup, start: int, end: int) -> list[Frag]
```
All draw calls **must clip silently** to the screen bounds — never raise.
`style` in `{"single","double","heavy","ascii","none"}`; when the Screen is in ASCII
mode all styles fall back to `+ - |`.

## 6. `engine/widgets.py`

Reusable UI pieces, all pure functions/classes over a `Screen`:

```python
class ListMenu:
    def __init__(self, items: Sequence[MenuItem], *, per_page: int = 20,
                 wrap_around: bool = True) -> None
    index: int
    def draw(self, scr, x, y, w, h, *, title=None, show_scroll=True) -> None
    def handle(self, key: str) -> str | None
        # returns "select" | "cancel" | "move" | None
    @property
    def selected(self) -> "MenuItem | None"

class MenuItem:
    def __init__(self, label: Markup, value: Any = None, *, hotkey: str | None = None,
                 desc: Markup = "", enabled: bool = True, group: str | None = None)

def progress_bar(scr, x, y, w, frac: float, *, fg=None, bg=None, ch="=") -> None
def gauge(scr, x, y, w, label: str, frac: float, color) -> None
def text_input(scr, term, x, y, w, *, prompt="", initial="", max_len=32) -> str | None
def scroll_view(scr, x, y, w, h, lines: Sequence[Markup], offset: int) -> int
def key_hint(scr, x, y, pairs: Sequence[tuple[str, str]], fg=None) -> None
def popup(scr, term, lines: Sequence[Markup], *, title="", buttons=("OK",)) -> int
def confirm(scr, term, question: str) -> bool
```

## 7. `engine/rng.py`

```python
def seed_from_string(s: str) -> int          # stable across runs & platforms

class RNG:
    def __init__(self, seed: int | str) -> None
    seed: int
    def random(self) -> float
    def randint(self, a: int, b: int) -> int          # inclusive
    def choice(self, seq)                             # -> element
    def choices(self, seq, weights=None, k=1) -> list
    def shuffle(self, seq: list) -> None
    def sample(self, seq, k: int) -> list
    def gauss(self, mu: float, sigma: float) -> float
    def chance(self, p: float) -> bool
    def roll(self, n: int, sides: int) -> int         # ndS
    def weighted(self, table: Mapping[Any, float])    # -> key
    def pick_index(self, weights: Sequence[float]) -> int
    def sub(self, name: str) -> "RNG"                 # deterministic child stream
    def getstate(self) -> Any
    def setstate(self, st: Any) -> None
```

## 8. `engine/geometry.py`

```python
class Point(NamedTuple): x: int; y: int
class Rect:
    x: int; y: int; w: int; h: int
    x2, y2, center, area
    def contains(self, x, y) -> bool
    def intersects(self, other) -> bool
    def expand(self, n) -> "Rect"
    def clamp_point(self, x, y) -> Point
    def cells(self) -> Iterator[Point]
    def border(self) -> Iterator[Point]

DIRS4: tuple[tuple[int,int], ...]
DIRS8: tuple[tuple[int,int], ...]
def line(x0, y0, x1, y1) -> list[Point]
def circle(cx, cy, r) -> list[Point]           # filled
def ring(cx, cy, r) -> list[Point]
def chebyshev(x0,y0,x1,y1) -> int
def manhattan(x0,y0,x1,y1) -> int
def euclid(x0,y0,x1,y1) -> float
def direction_name(dx, dy) -> str              # "north", "southeast", ...
def normalize_dir(dx, dy) -> tuple[int,int]
```

## 9. `engine/noise.py`

```python
class ValueNoise:
    def __init__(self, rng: RNG) -> None
    def noise2(self, x: float, y: float) -> float          # -1..1
    def fbm(self, x, y, octaves=5, lacunarity=2.0, gain=0.5) -> float   # -1..1
    def ridged(self, x, y, octaves=5) -> float             # 0..1
def normalize_grid(grid: list[list[float]]) -> None        # in-place to 0..1
def smooth_grid(grid, passes=1) -> None
```

## 10. `engine/pathfind.py`

Generic over hashable nodes so it serves the world map, the local map and z-levels.

```python
def astar(start, goal, neighbors: Callable[[Any], Iterable[tuple[Any, float]]],
          heuristic: Callable[[Any, Any], float],
          max_nodes: int = 20000) -> list | None      # includes start & goal, or None

def dijkstra(sources: Iterable[Any], neighbors, max_cost: float = 1e18,
             max_nodes: int = 50000) -> dict[Any, float]

class DijkstraMap:
    def __init__(self, values: dict[Any, float]) -> None
    def best_step(self, node, neighbors, *, flee: bool = False)   # -> node | None
```

## 11. `engine/fov.py`

```python
def compute_fov(ox: int, oy: int, radius: int,
                blocks: Callable[[int, int], bool],
                visit: Callable[[int, int, float], None],
                *, light_walls: bool = True) -> None
def has_los(x0, y0, x1, y1, blocks: Callable[[int,int], bool]) -> bool
```
Recursive shadowcasting, all 8 octants, origin always visited with intensity 1.0.

## 12. `engine/scheduler.py`

Energy-based turn order (DF-like speeds).

```python
class Scheduler:
    def __init__(self) -> None
    def add(self, actor_id: int, speed: int) -> None
    def remove(self, actor_id: int) -> None
    def set_speed(self, actor_id: int, speed: int) -> None
    def next_actor(self) -> int | None    # advances internal clock; None if empty
    def spend(self, actor_id: int, cost: int) -> None
    ticks: int
    def to_dict(self) -> dict ;  @classmethod def from_dict(cls, d) -> "Scheduler"
```
Base speed 100 = one action per 100 ticks. Higher `speed` acts more often.

---

## 13. `data/materials.py`

```python
@dataclass(frozen=True)
class Material:
    id: str; name: str; adjective: str; category: str
    density: int                 # kg/m^3
    color: Color
    impact_yield: int; impact_fracture: int; impact_strain: int
    shear_yield: int; shear_fracture: int; shear_strain: int
    max_edge: int                # 0 = cannot hold an edge, 10000 = steel
    value: int                   # base value multiplier
    melting_point: int           # in Urists (10000 = ~room temp)
    flags: frozenset[str]        # {"METAL","STONE","WOOD","GEM","LEATHER","CLOTH",
                                 #  "BONE","GLASS","ORGANIC","EDIBLE","FLAMMABLE",
                                 #  "WEAPON_OK","ARMOR_OK","MAGICAL"}
    def weight_of(self, volume_cm3: float) -> float    # kilograms

MATERIALS: dict[str, Material]
def get(mid: str) -> Material
def by_flag(flag: str) -> list[Material]
def by_category(cat: str) -> list[Material]
WEAPON_METALS: list[str]     # ordered worst -> best
STONE_LAYERS: dict[str, list[str]]   # "sedimentary"|"igneous"|"metamorphic" -> mat ids
```
Required ids (at least): metals `copper bronze bismuth_bronze iron steel silver gold
platinum adamantine`; stones `granite gabbro basalt obsidian marble limestone
sandstone slate microcline orthoclase chalk`; woods `oak willow pine mahogany
feather_wood highwood`; organics `leather bone shell chitin ivory horn tooth`;
cloth `pig_tail_cloth silk_cloth wool_cloth`; gems `diamond ruby sapphire emerald
amethyst topaz`; misc `glass ice water blood fat muscle skin nerve nail hair
cartilage brain lung heart gut soap charcoal ash`.

Tissue materials (`skin fat muscle bone nerve …`) must exist because bodies use them.

## 14. `data/bodies.py`

```python
PART_FLAGS = {"VITAL","GRASP","STANCE","SIGHT","HEARING","SMELL","BREATHE","THOUGHT",
              "CIRCULATION","DIGEST","INTERNAL","SMALL","JOINT","NERVOUS","HEAD",
              "UPPERBODY","LOWERBODY","LIMB","DIGIT","TOTEMABLE","NAIL","TEETH"}

@dataclass(frozen=True)
class Tissue:
    id: str; name: str; material: str
    rel_thickness: int            # relative units within its part
    heal_rate: int; pain_receptors: int
    flags: frozenset[str]         # {"CONNECTIVE","MAJOR_ARTERIES","FUNCTIONAL","STRUCTURAL"}

@dataclass(frozen=True)
class BodyPartDef:
    id: str; name: str; parent: str | None
    rel_size: int                 # relative volume share
    flags: frozenset[str]
    tissues: tuple[str, ...]      # outermost -> innermost, ids into TISSUES
    side: str | None              # "left" | "right" | None
    category: str                 # "head","torso","arm","leg","hand","foot","organ",...

TISSUES: dict[str, Tissue]
BODY_PLANS: dict[str, tuple[BodyPartDef, ...]]

def build_plan(plan_id: str) -> tuple[BodyPartDef, ...]
def plan_ids() -> list[str]
```
Required plans: `humanoid`, `quadruped`, `bird`, `serpent`, `insect`, `fish`,
`blob`, `dragon`, `giant_humanoid`. `humanoid` must include head (with brain, skull,
eyes, ears, nose, mouth, teeth, throat), neck, upper/lower body, heart, lungs, liver,
stomach, guts, spleen, kidneys, spine, ribs, both arms (upper/lower/hand/fingers),
both legs (upper/lower/foot/toes).

## 15. `data/items.py`

```python
@dataclass(frozen=True)
class AttackDef:
    name: str                # "slash", "stab", "bash", "hack", "punch", "bite"
    verb2: str               # "slash" (you)
    verb3: str               # "slashes" (it)
    kind: str                # "edge" | "blunt"
    contact: int             # contact area
    penetration: int         # max penetration depth
    velocity: float = 1.0    # multiplier
    prepare: int = 3; recover: int = 3

@dataclass(frozen=True)
class WeaponDef:
    skill: str               # skill id
    two_handed_size: int     # creature size below which it needs two hands
    min_size: int
    attacks: tuple[AttackDef, ...]
    ranged: str | None = None      # ammo item id for ranged weapons
    shoot_force: int = 0

@dataclass(frozen=True)
class ArmorDef:
    layer: str               # "under" | "over" | "armor" | "cover"
    coverage: tuple[str, ...]        # body part categories or ids covered
    thickness: int
    armor_level: int
    permit_size: int = 0

@dataclass(frozen=True)
class ItemDef:
    id: str; name: str; plural: str; category: str    # see CATEGORIES
    glyph: str; volume: int                            # cm^3
    value: int
    materials: tuple[str, ...]      # allowed material *flags* e.g. ("METAL","STONE")
    weapon: WeaponDef | None = None
    armor: ArmorDef | None = None
    nutrition: int = 0; hydration: int = 0
    stack: bool = False
    flags: frozenset[str] = frozenset()   # {"EDIBLE","DRINK","LIGHT","CONTAINER",
                                          #  "TOOL","AMMO","QUIVER","BAG","INSTRUMENT",
                                          #  "BOOK","COIN","GEM","SHIELD","CORPSE"}

ITEMS: dict[str, ItemDef]
CATEGORIES = ("weapon","armor","clothing","shield","ammo","food","drink","tool",
              "container","gem","coin","furniture","corpse","remains","misc","book")
def get(iid: str) -> ItemDef
def by_category(cat: str) -> list[ItemDef]
def weapons_for_skill(skill: str) -> list[ItemDef]
```
Required weapons: dagger, short sword, sword, long sword, two-handed sword, axe,
battle axe, great axe, mace, morningstar, warhammer, maul, spear, pike, halberd,
scimitar, whip, flail, pick, crossbow (+bolts), bow (+arrows), sling (+stones).
Armor: leather/chain/plate variants of cap/helm, mail shirt, breastplate, greaves,
gauntlets, high boots, shield, buckler, cloak, robe, tunic, trousers, shoes, mitten,
sock, hood. Plus: backpack, waterskin, flask, rope, torch, lantern, lockpick, whetstone,
crutch, bandage, splint, meat, plump helmet, bread, cheese, fish, biscuit, dwarven ale,
wine, water, rum, coin, gem, book, instrument, corpse, severed part, bone, skull.

## 16. `data/creatures.py`

```python
@dataclass(frozen=True)
class NaturalAttack:
    part: str                # body part id the attack uses, "" = whole body
    attack: AttackDef

@dataclass(frozen=True)
class CreatureDef:
    id: str; name: str; plural: str; adjective: str
    glyph: str; color: Color
    body_plan: str
    size: int                    # cm^3 adult volume (dwarf 60000, human 70000)
    tier: int                    # 0 vermin .. 5 megabeast; used for spawn/threat
    attributes: dict[str, int]   # base means, missing => 1000
    skills: dict[str, int]       # innate skill levels
    attacks: tuple[NaturalAttack, ...]
    biomes: frozenset[str]
    flags: frozenset[str]
    group: tuple[int, int] = (1, 1)
    speed: int = 100
    frequency: int = 50          # 0..100 spawn weight
    diet: str = "omnivore"       # herbivore|carnivore|omnivore|none
    blood: str = "blood"         # material id, "" = bloodless
    lifespan: tuple[int, int] = (60, 100)
    civ: str | None = None       # civilization id if this is a civilized race
    child_name: str = ""
    description: str = ""

CREATURES: dict[str, CreatureDef]
PLAYABLE_RACES: tuple[str, ...]     # ("dwarf","human","elf","goblin","kobold")
def get(cid: str) -> CreatureDef
def spawnable(biome: str, *, underground: bool = False,
              max_tier: int = 5, flags_any=(), flags_none=()) -> list[CreatureDef]
def megabeasts() -> list[CreatureDef]
def random_forgotten_beast(rng: RNG, name: str) -> CreatureDef   # procedural
```
Flags used elsewhere: `INTELLIGENT CIVILIZED EVIL GOOD SAVAGE MEGABEAST SEMIMEGABEAST
NIGHT_CREATURE UNDEAD FLIER SWIMMER AQUATIC AMBUSHER PACK GRAZER MOUNT PET VERMIN
NO_EAT NO_DRINK NO_SLEEP NO_FEAR TRAINABLE BENIGN SUBTERRANEAN CAN_SPEAK OPPOSED_TO_LIFE
FIREIMMUNE WEBBER POISON_BITE`.

Minimum roster (~70): the 5 playable races + goblin/kobold variants, wolf, dog, cat,
horse, donkey, mule, cow, bull, pig, sheep, goat, chicken, duck, deer, elk, boar,
bear (grizzly/black), lion, tiger, leopard, wolverine, badger, fox, rabbit, rat,
giant rat, cave spider, giant cave spider, bat, giant bat, raven, eagle, buzzard,
carp, pike, alligator, snake, giant desert scorpion, elephant, rhinoceros,
hippopotamus, camel, gorilla, troll, ogre, minotaur, cyclops, ettin, hydra, dragon,
roc, bronze colossus, giant, blind cave ogre, gremlin, night troll, zombie, skeleton,
ghoul, mummy, vampire, werewolf, necromancer, bandit, merchant, guard, peasant,
hammerman, macedwarf, elf archer, goblin snatcher, forgotten beast (template).

## 17. `data/biomes.py`

```python
@dataclass(frozen=True)
class Biome:
    id: str; name: str; glyph: str; color: Color; map_color: Color
    tree_density: float; shrub_density: float; grass: bool
    soil: str; stone: str                 # default material ids
    savagery_bias: int; temperature_bias: int
    flags: frozenset[str]                 # {"WATER","FROZEN","DESERT","FOREST",
                                          #  "MOUNTAIN","WETLAND","GRASS","EVIL","GOOD"}
    travel_cost: float = 1.0
    description: str = ""

BIOMES: dict[str, Biome]
def get(bid: str) -> Biome
def classify(elevation: float, rainfall: float, temperature: float,
             drainage: float, *, is_water: bool = False) -> str
```
Required biome ids: `ocean deep_ocean lake river glacier tundra taiga
temperate_forest temperate_broadleaf tropical_forest jungle savanna shrubland
grassland desert badlands mountain hills marsh swamp beach volcano`.

## 18. `data/calendar.py`

```python
MONTHS: tuple[str, ...]      # Granite, Slate, Felsite, Hematite, Malachite, Galena,
                             # Limestone, Sandstone, Timber, Moonstone, Opal, Obsidian
SEASONS: tuple[str, ...]     # Spring, Summer, Autumn, Winter
DAYS_PER_MONTH = 28
SECONDS_PER_TICK = 6         # one tick is one standard action at base speed
TICKS_PER_MINUTE = 10 ; TICKS_PER_HOUR = 600 ; TICKS_PER_DAY = 14400
DAYS_PER_YEAR  = 336

@dataclass
class GameTime:
    ticks: int = 0
    year: int ; month: int ; day: int ; hour: int ; minute: int   # derived properties
    season: str
    def advance(self, ticks: int) -> None
    def is_night(self) -> bool               # 20:00 .. 05:00
    def light_level(self) -> float           # 0..1 outdoors
    def date_str(self) -> str                # "12th of Granite, 125"
    def time_str(self) -> str                # "14:32"
    def full_str(self) -> str
    def to_dict(self) / from_dict(cls, d)
def ordinal(n: int) -> str                   # 1 -> "1st"
```
`GameTime` starts at year 125 unless told otherwise (world gen sets it).

## 19. `data/names.py`

```python
def dwarf_name(rng, female: bool = False) -> str         # "Urist Mineglazed"
def human_name(rng, female: bool = False) -> str
def elf_name(rng, female: bool = False) -> str
def goblin_name(rng, female: bool = False) -> str
def kobold_name(rng, female: bool = False) -> str
def name_for_race(race: str, rng: RNG, female: bool = False) -> str
def site_name(rng, race: str, kind: str) -> tuple[str, str]   # (native, translated)
def civ_name(rng, race: str) -> tuple[str, str]
def artifact_name(rng, race: str) -> tuple[str, str]
def region_name(rng, biome: str) -> str        # "The Sunken Wilds"
def beast_name(rng) -> str
def group_name(rng, kind: str) -> str          # bandit gangs, mercenary companies
```
Compound "dwarvish" style: syllable tables + a small translated-word dictionary, so
`("Kadolmomuz", "Boatmurdered")` style pairs are produced.

## 20. `data/descriptors.py`

```python
def attribute_desc(attr: str, value: int) -> str          # "unbelievably strong"
def skill_level_name(level: int) -> str                   # "Proficient"
def quality_name(q: int) -> str                           # "", "-", "+", "*", "≡", "☼", "artifact"
def quality_wrap(q: int, s: str) -> str                   # "*iron short sword*"
def wear_name(w: int) -> str                              # "", "x", "X", "XX"
def size_desc(volume: int) -> str
def wound_severity(frac: float) -> str
def personality_desc(trait: str, value: int) -> str
def stress_desc(stress: int) -> str
def relationship_desc(value: int) -> str
def age_desc(years: int, race: str) -> str
```

---

## 21. `game/attributes.py`

```python
PHYSICAL = ("strength","agility","toughness","endurance","recuperation","disease_resistance")
MENTAL = ("analytical_ability","focus","willpower","creativity","intuition","patience",
          "memory","linguistic_ability","spatial_sense","musicality","kinesthetic_sense",
          "empathy","social_awareness")
ALL_ATTRS = PHYSICAL + MENTAL
ATTR_NAMES: dict[str, str]           # id -> "Strength"

class Attributes:
    def __init__(self, values: dict[str, int] | None = None) -> None
    def get(self, attr: str) -> int              # current (after wounds/fatigue)
    def base(self, attr: str) -> int
    def set(self, attr: str, value: int) -> None
    def modify(self, attr: str, delta: int) -> None
    def factor(self, attr: str) -> float         # ~0.5 .. 2.0, 1.0 at 1000
    def describe(self, attr: str) -> str
    def to_dict(self) / from_dict(cls, d)

def roll_attributes(rng: RNG, base: Mapping[str, int]) -> Attributes
```
Attribute scale: 0..5000, 1000 = average. `factor()` = the multiplier used by combat
and skills.

## 22. `game/skills.py`

```python
@dataclass(frozen=True)
class SkillDef:
    id: str; name: str; category: str      # "combat","weapon","social","craft",
                                           # "medical","outdoor","misc"
    attrs: tuple[str, ...]                 # governing attributes
    description: str = ""

SKILLS: dict[str, SkillDef]
LEVEL_NAMES: tuple[str, ...]               # index 0..20 -> Dabbling..Legendary
MAX_LEVEL = 20

def exp_for_level(level: int) -> int
def level_from_exp(exp: int) -> int

class SkillSet:
    def __init__(self, levels: Mapping[str, int] | None = None) -> None
    def level(self, sid: str) -> int
    def exp(self, sid: str) -> int
    def set_level(self, sid: str, level: int) -> None
    def add_exp(self, sid: str, amount: int) -> int | None   # new level or None
    def rust(self, sid: str, amount: int = 1) -> None
    def known(self) -> list[tuple[str, int]]                 # sorted by level desc
    def to_dict(self) / from_dict(cls, d)
```
Required skill ids: weapon skills matching `ItemDef.weapon.skill`
(`sword axe mace hammer spear dagger pick crossbow bow sling whip lash misc_weapon`),
plus `wrestling striker biter kicker dodging shield_use armor_use fighter
observer swimming climbing ambusher tracker rider sneak throwing
appraisal negotiation persuasion intimidation conversation lying leadership
diagnose surgery suturing bone_setting wound_dressing crush_dodge
butchery cooking brewing herbalism fishing smithing weaponsmithing armorsmithing
mining woodcutting carpentry masonry mechanics crafting engraving
reading writing music dancing poetry knowledge concentration discipline`.

## 23. `game/personality.py`

```python
FACETS: tuple[str, ...]      # ~30 DF-style facets: love_propensity, hate_propensity,
                             # bravery, cheer, anxiety, anger, greed, curiosity, ...
VALUES: tuple[str, ...]      # law, loyalty, family, friendship, power, cunning,
                             # eloquence, fairness, knowledge, nature, ...

class Personality:
    def __init__(self, facets=None, values=None) -> None
    def facet(self, name: str) -> int         # 0..100, 50 average
    def value(self, name: str) -> int         # -50..50
    def describe(self) -> list[str]           # a few sentences
    def bravery_factor(self) -> float
    def to_dict(self) / from_dict(cls, d)

def roll_personality(rng: RNG, race: str) -> Personality
```

## 24. `game/log.py`

```python
class Message:
    frags: list[Frag]; turn: int; count: int; kind: str   # "info","combat","warn",
                                                          # "good","bad","social"
class MessageLog:
    def __init__(self, capacity: int = 2000) -> None
    def add(self, text: Markup, kind: str = "info") -> None
    def combat(self, text: Markup) -> None
    def warn / good / bad / social(self, text: Markup) -> None
    def recent(self, n: int) -> list[Message]
    def all(self) -> list[Message]
    def clear_new(self) -> None ; new_count: int
    def to_dict(self) / from_dict(cls, d)
```
Repeated identical messages collapse to `"... (x3)"`.

## 25. `game/item.py`

```python
QUALITY_NAMES = ("", "well-crafted", "finely-crafted", "superior", "exceptional",
                 "masterwork", "artifact")

class Item:
    id: int                                  # unique per game
    def __init__(self, def_id: str, material: str, *, quality: int = 0,
                 wear: int = 0, count: int = 1, maker: str = "",
                 name_override: str = "") -> None
    defn -> ItemDef ; mat -> Material
    weight: float          # kg, = material.weight_of(volume) * count
    value: int
    def name(self, *, article: bool = False, plural: bool = False,
             full: bool = True) -> str        # "a masterwork steel long sword"
    def colored_name(self) -> list[Frag]
    def is_weapon / is_armor / is_edible / is_drink / is_shield -> bool
    def attacks(self) -> list[AttackDef]
    def damage_class(self) -> str
    def stack_with(self, other: "Item") -> bool
    def split(self, n: int) -> "Item"
    def wear_tick(self, rng: RNG) -> bool     # True if destroyed
    def to_dict(self) / from_dict(cls, d) -> "Item"

def make_item(rng: RNG, def_id: str, *, material: str | None = None,
              quality: int | None = None, tier: int = 1) -> Item
def random_loot(rng: RNG, tier: int, kinds: Sequence[str] = ()) -> list[Item]
def corpse_of(creature) -> Item
```

## 26. `game/inventory.py`

```python
BODY_SLOTS = ("head","neck","torso_under","torso_over","torso_armor","hands",
              "legs","feet","back","weapon","offhand","ring1","ring2","ammo")

class Inventory:
    def __init__(self, owner=None) -> None
    items: list[Item]
    equipped: dict[str, Item]         # slot -> item
    def add(self, item: Item) -> Item                # merges stacks
    def remove(self, item: Item, count: int = 1) -> Item | None
    def total_weight(self) -> float
    def equip(self, item: Item, slot: str | None = None) -> tuple[bool, str]
    def unequip(self, slot: str) -> Item | None
    def slot_for(self, item: Item) -> str | None
    def best_weapon(self) -> Item | None
    def armor_on(self, part_category: str) -> list[Item]
    def find(self, pred) -> list[Item]
    def by_category(self, cat: str) -> list[Item]
    def to_dict(self) / from_dict(cls, d, owner=None)
```
Weight over `carry_capacity` slows the creature (`Creature.effective_speed`).

## 27. `game/body.py`

```python
@dataclass
class Wound:
    part: str; tissue: str; severity: float      # 0..1 of that tissue
    kind: str                                    # "cut","bruise","fracture","puncture",
                                                 # "burn","tear"
    bleeding: int; pain: int; age: int
    severed: bool = False
    def describe(self) -> str

class PartState:
    id: str; defn: BodyPartDef
    size: int
    tissues: dict[str, float]     # tissue id -> remaining fraction 0..1
    wounds: list[Wound]
    severed: bool ; destroyed: bool ; broken: bool ; missing_from: str | None
    def functional(self) -> bool
    def damage_fraction(self) -> float
    def status(self) -> str        # "mangled", "broken", "bruised", ...

class Body:
    def __init__(self, plan_id: str, size: int, materials: Mapping[str, str] | None = None)
    parts: dict[str, PartState]
    blood: float ; max_blood: float
    pain: int ; stunned: int ; unconscious: int ; winded: int
    dead: bool ; death_cause: str
    def part(self, pid) -> PartState | None
    def parts_by_flag(self, flag: str) -> list[PartState]
    def random_part(self, rng: RNG, *, weighted: bool = True,
                    prefer: str | None = None) -> PartState
    def apply_damage(self, part_id: str, kind: str, force: float,
                     contact: int, penetration: int, rng: RNG) -> list[str]
        # returns human-readable effect clauses; mutates state
    def sever(self, part_id: str) -> list[str]
    def can_stand(self) -> bool
    def can_grasp(self) -> int          # number of working grasp parts
    def can_see(self) -> bool
    def can_breathe(self) -> bool
    def bleeding_rate(self) -> float
    def pain_level(self) -> float       # 0..1 relative to tolerance
    def tick(self, rng: RNG, ticks: int, toughness: float, recuperation: float) -> list[str]
    def status_lines(self) -> list[Frag]
    def wound_summary(self) -> str
    def to_dict(self) / from_dict(cls, d)
```
Death conditions: destroyed VITAL part, severed head/upper body, blood < 20 %,
`can_breathe()` false for too long. Set `dead=True` and `death_cause`.

## 28. `game/combat.py`

```python
@dataclass
class AttackResult:
    hit: bool; messages: list[Frag]; killed: bool; damage: float
    part: str | None; blocked: bool; dodged: bool; parried: bool

def melee_attack(attacker, defender, *, weapon=None, attack_def=None,
                 target_part: str | None = None, rng: RNG, log=None) -> AttackResult
def ranged_attack(attacker, defender, weapon, ammo, *, rng: RNG, log=None) -> AttackResult
def throw_item(attacker, item, tx, ty, *, rng, game) -> AttackResult
def wrestle(attacker, defender, move: str, *, rng, log=None) -> AttackResult
def to_hit_chance(attacker, defender, skill: str) -> float
def compute_momentum(attacker, weapon, attack_def) -> float
def armor_protection(defender, part_id, kind: str) -> tuple[float, Item | None]
def opportunity_to_flee(creature) -> bool
```
Model (documented, tunable constants at the top of the module):
`momentum = velocity * (weapon_mass + strength_term) * skill_term`; layered armor
subtracts by material `shear/impact yield`; remaining force goes to
`Body.apply_damage`. Messages must read like DF:
`"You slash the goblin in the left upper arm, tearing apart the muscle and shattering the bone!"`

## 29. `game/entity.py`

```python
class Creature:
    next_id: ClassVar[int]
    def __init__(self, def_id: str, *, rng: RNG, name: str = "", female: bool | None = None,
                 age: int | None = None, player: bool = False, faction: str = "wild",
                 level: int = 0) -> None
    id: int ; def_id: str ; defn: CreatureDef ; name: str ; female: bool ; age: int
    x: int; y: int; z: int
    wx: int; wy: int                       # world tile
    body: Body ; attributes: Attributes ; skills: SkillSet ; personality: Personality
    inventory: Inventory
    faction: str ; hostile_to: set[str]
    needs: "Needs" ; ai: "AIState | None"
    is_player: bool ; alive: bool ; profession: str ; title: str
    hf_id: int | None                      # link to historical figure
    def display_name(self, *, with_title: bool = True) -> str
    def glyph_and_color(self) -> tuple[str, Color]
    def effective_speed(self) -> int
    def carry_capacity(self) -> float
    def sight_radius(self, light: float) -> int
    def is_hostile_to(self, other: "Creature") -> bool
    def take_turn(self, game) -> int        # returns ticks spent; AI only
    def on_death(self, game, cause: str) -> None
    def add_exp(self, skill: str, amount: int) -> None
    def describe(self) -> list[Frag]
    def to_dict(self) / from_dict(cls, d) -> "Creature"
```

## 30. `game/needs.py`

```python
class Needs:
    hunger: int ; thirst: int ; drowsy: int ; fatigue: int ; stress: int
    def tick(self, ticks: int, creature, game) -> list[str]
    def eat(self, item: Item) -> str
    def drink(self, item: Item) -> str
    def sleep(self, ticks: int) -> None
    def status(self) -> list[tuple[str, float, str]]   # (label, 0..1, severity)
    def add_thought(self, text: str, value: int) -> None
    thoughts: list[tuple[str, int]]
    def to_dict(self) / from_dict(cls, d)
```
Thresholds produce log warnings ("You are starving!") and attribute penalties.

## 31. `game/ai.py`

```python
class AIState:
    mode: str          # "idle","wander","hunt","flee","follow","sleep","guard",
                       # "graze","travel","talk"
    target_id: int | None ; home: tuple[int,int] | None
    path: list ; alertness: int ; last_seen: tuple[int,int] | None
    leader_id: int | None

def take_turn(creature, game) -> int          # ticks spent
def pick_mode(creature, game) -> str
def hostile_targets(creature, game) -> list
```
AI must use `engine.fov.has_los`, `engine.pathfind.astar`, flee when badly wounded or
`personality.bravery_factor()` is low, pack up with same-faction creatures.

## 32. `game/actions.py`

Player-facing verbs. Each returns ticks spent (0 = no turn passed).

```python
def move_or_attack(game, dx: int, dy: int) -> int
def move_z(game, dz: int) -> int
def wait(game, ticks: int = 100) -> int
def pick_up(game, item: Item | None = None) -> int
def drop(game, item: Item) -> int
def equip(game, item: Item) -> int
def unequip(game, slot: str) -> int
def eat(game, item: Item) -> int
def drink(game, item: Item | None = None) -> int
def sleep(game, hours: int = 8) -> int
def open_close(game, dx, dy) -> int
def climb(game, dx, dy) -> int
def swim(game) -> int
def butcher(game, corpse: Item) -> int
def build_fire(game) -> int
def travel_start(game) -> int
def attack_dir(game, dx, dy, *, part: str | None = None) -> int
def throw(game, item: Item, tx: int, ty: int) -> int
def fire(game, tx: int, ty: int) -> int
def talk(game, other) -> int
def search(game) -> int
def rest(game, ticks: int) -> int
```

## 33. `game/crafting.py`

```python
@dataclass(frozen=True)
class Recipe:
    id: str; name: str; skill: str; difficulty: int
    inputs: tuple[tuple[str, int], ...]        # (item def id or material flag, count)
    output: str; out_count: int = 1
    needs: tuple[str, ...] = ()                # "fire","anvil","workshop"
RECIPES: dict[str, Recipe]
def available(creature, game) -> list[Recipe]
def craft(creature, recipe: Recipe, game) -> tuple[bool, str]
def butcher_corpse(creature, corpse: Item, game) -> list[Item]
def cook(creature, items: Sequence[Item], game) -> Item | None
```

## 34. `game/quests.py`

```python
@dataclass
class Quest:
    id: int; kind: str        # "slay_beast","clear_site","retrieve_artifact",
                              # "deliver","bounty","escort","explore"
    title: str; description: str
    giver_hf: int | None ; target_hf: int | None
    site_id: int | None ; item_id: int | None
    wx: int; wy: int
    reward: int ; state: str  # "offered","active","done","failed"
    progress: int ; goal: int
    def summary(self) -> str
    def to_dict(self) / from_dict(cls, d)

class QuestLog:
    active: list[Quest] ; completed: list[Quest]
    def offer(self, quest) / accept(self, quest) / complete(self, quest, game)
    def on_kill(self, game, victim) -> None
    def on_arrive(self, game, wx, wy) -> None
    def on_pickup(self, game, item) -> None
def generate_quest(rng, game, giver) -> Quest | None
```

## 35. `game/conversation.py`

```python
TOPICS = ("greet","ask_directions","ask_rumors","ask_troubles","ask_family",
          "ask_self","request_quest","trade","insult","threaten","farewell",
          "recruit","ask_beast","ask_site","brag")
def topics_for(speaker, listener, game) -> list[tuple[str, str]]   # (topic, label)
def say(speaker, listener, topic: str, game) -> list[Frag]
def rumor_lines(game, hf_id: int | None = None, n: int = 3) -> list[str]
def greeting(npc, game) -> str
```
Answers must draw on generated history (`world.history`) so NPCs reference real
events, figures and sites.

## 36. `game/state.py`

The single object the UI talks to.

```python
class Game:
    world: "World" ; player: Creature ; local: "LocalMap"
    creatures: dict[int, Creature]            # in the active local map
    items_on_ground: dict[tuple[int,int,int], list[Item]]
    time: GameTime ; log: MessageLog ; rng: RNG ; quests: QuestLog
    scheduler: Scheduler ; turn: int ; mode: str        # "local" | "travel"
    seen: set ; visible: set
    def __init__(self, world, player, rng) -> None
    @classmethod
    def new_game(cls, world, player_spec: dict, rng: RNG) -> "Game"
    def enter_world_tile(self, wx: int, wy: int, *, entry: str = "edge") -> None
    def creature_at(self, x, y, z) -> Creature | None
    def items_at(self, x, y, z) -> list[Item]
    def add_creature(self, c) / remove_creature(self, c)
    def spawn_wildlife(self, n: int | None = None) -> None
    def update_fov(self) -> None
    def advance(self, ticks: int) -> None        # runs AI/scheduler until player's turn
    def player_acts(self, ticks: int) -> None
    def is_passable(self, x, y, z, creature=None) -> bool
    def blocks_sight(self, x, y, z) -> bool
    def light_at(self, x, y, z) -> float
    def describe_tile(self, x, y, z) -> list[Frag]
    def travel_step(self, dx, dy) -> bool
    def game_over: bool ; death_message: str
    def to_dict(self) / from_dict(cls, d) -> "Game"
```

## 37. `game/save.py`

```python
SAVE_VERSION = 1
def save_dir() -> Path                 # %APPDATA%/ASCIIWarriors or ~/.local/share/...
def list_saves() -> list[dict]         # [{name, path, when, char, race, year}]
def save_game(game, name: str) -> Path
def load_game(path) -> "Game"
def delete_save(path) -> None
def autosave(game) -> None
```
Format: gzip-compressed JSON. Must round-trip a `Game` exactly (tests enforce it).

---

## 38. `world/tiles.py`

```python
@dataclass(frozen=True)
class TileDef:
    id: str; name: str; glyph: str; color: Color; bg: Color | None
    walk: bool; sight: bool; swim: bool; climb: bool
    flags: frozenset[str]   # {"WALL","FLOOR","WATER","DEEP","TREE","STAIR_UP",
                            #  "STAIR_DOWN","RAMP","DOOR","OPEN","LAVA","ICE",
                            #  "GRASS","SAND","CONSTRUCTED","FURNITURE","DIGGABLE"}
    material: str = ""
TILES: dict[str, TileDef]
def get(tid: str) -> TileDef
```
Required ids: `air floor grass dirt sand mud stone_floor rock_wall soil_wall
tree shrub sapling water shallow_water deep_water ice lava chasm boulder
stair_up stair_down stair_updown ramp_up ramp_down door_closed door_open
wall_constructed floor_constructed bridge road bed table chair cabinet coffer
altar statue well fire campfire rubble grass_dead snow track`.

## 39. `world/worldgen.py`

```python
WORLD_SIZES = {"pocket":33, "small":65, "medium":97, "large":129, "huge":161}

@dataclass
class WorldTile:
    elevation: float; rainfall: float; temperature: float; drainage: float
    volcanism: float; savagery: float; evil: float
    biome: str; river: int; river_dir: int; is_ocean: bool; is_lake: bool
    region_id: int; site_id: int | None; civ_id: int | None
    explored: bool = False

class World:
    name: str; seed: int; width: int; height: int
    tiles: list[list[WorldTile]]
    regions: list["Region"] ; civs: list["Civilization"] ; sites: list["Site"]
    figures: dict[int, "HistoricalFigure"] ; events: list["HistoricalEvent"]
    artifacts: list["Artifact"] ; year: int
    def tile(self, x, y) -> WorldTile
    def in_bounds(self, x, y) -> bool
    def site_at(self, x, y) -> "Site | None"
    def biome_at(self, x, y) -> str
    def region_at(self, x, y) -> "Region"
    def neighbours(self, x, y) -> list[tuple[int,int]]
    def travel_cost(self, x, y) -> float
    def to_dict(self) / from_dict(cls, d)

@dataclass
class Region:
    id: int; name: str; biome: str; tiles: list[tuple[int,int]]
    savagery: str; evil: str

def generate_world(rng: RNG, *, size: str = "medium", name: str = "",
                   history_years: int = 120,
                   progress: Callable[[str, float], None] | None = None) -> World
```
`progress(stage_label, fraction)` is called throughout so the UI can draw a
generation screen. Pipeline: elevation fbm -> ocean threshold -> temperature by
latitude+altitude -> rainfall (orographic) -> drainage -> rivers by downhill flow ->
lakes -> biome classification -> regions (flood fill) -> volcanism/savagery/evil ->
civs -> `world.history.simulate`.

## 40. `world/civ.py`

```python
@dataclass
class Site:
    id: int; name: str; native_name: str; kind: str
        # "fortress","hillocks","town","hamlet","city","castle","forest_retreat",
        # "dark_fortress","dark_pits","cave","ruin","tower","lair","camp","shrine","tomb"
    wx: int; wy: int; civ_id: int | None; race: str
    population: int; founded: int; destroyed: int | None
    ruler_hf: int | None ; owner_hf: int | None
    buildings: list[str] ; wealth: int
    def glyph(self) -> tuple[str, Color]
    def to_dict(self) / from_dict(cls, d)

@dataclass
class Civilization:
    id: int; name: str; native_name: str; race: str
    sites: list[int] ; leader_hf: int | None ; capital: int | None
    at_war_with: set[int] ; ethics: dict[str, str] ; year_founded: int
    def to_dict(self) / from_dict(cls, d)

def place_civilizations(world, rng, progress=None) -> None
def found_site(world, civ, rng, kind: str) -> Site | None
def site_kind_for(race: str, rank: str) -> str
```

## 41. `world/history.py`

```python
@dataclass
class HistoricalFigure:
    id: int; name: str; native_name: str; race: str; female: bool
    born: int; died: int | None; death_cause: str
    civ_id: int | None; site_id: int | None
    profession: str; titles: list[str]
    kills: list[int]; relationships: dict[int, str]
    flags: set[str]           # {"leader","hero","monster","necromancer","bandit",
                              #  "vampire","legendary","player"}
    stats: dict[str, int]
    def alive(self, year: int) -> bool
    def summary(self) -> str

@dataclass
class HistoricalEvent:
    id: int; year: int; kind: str; text: str
    figures: list[int]; sites: list[int]; civs: list[int]
    def describe(self, world) -> str

@dataclass
class Artifact:
    id: int; name: str; native_name: str; item_def: str; material: str
    creator_hf: int | None; created: int; site_id: int | None
    holder_hf: int | None; description: str; lost: bool

def simulate(world, rng, years: int, progress=None) -> None
def new_figure(world, rng, race, civ_id=None, site_id=None, **kw) -> HistoricalFigure
def record(world, year, kind, text, figures=(), sites=(), civs=()) -> HistoricalEvent
```
Event kinds to implement: `founded_site, became_leader, birth, death, war_declared,
peace, battle, site_destroyed, site_conquered, artifact_created, artifact_stolen,
beast_attack, beast_slain, hero_rose, became_necromancer, tower_built, curse,
banditry, marriage, migration, plague, tavern_founded`.

## 42. `world/legends.py`

```python
def figure_lines(world, hf_id: int) -> list[Frag]
def site_lines(world, site_id: int) -> list[Frag]
def civ_lines(world, civ_id: int) -> list[Frag]
def artifact_lines(world, art_id: int) -> list[Frag]
def event_lines(world, ev) -> list[Frag]
def timeline(world, *, year_from=None, year_to=None, kinds=None) -> list[HistoricalEvent]
def search(world, query: str) -> list[tuple[str, int, str]]   # (kind, id, label)
def world_summary(world) -> list[Frag]
```

## 43. `world/localmap.py`

```python
class LocalMap:
    width: int; height: int; zmin: int; zmax: int
    wx: int; wy: int; biome: str; site_id: int | None
    def __init__(self, width, height, zmin, zmax, *, wx=0, wy=0, biome="grassland")
    def tile(self, x, y, z) -> str                  # tile def id
    def set_tile(self, x, y, z, tid: str) -> None
    def in_bounds(self, x, y, z) -> bool
    def walkable(self, x, y, z) -> bool
    def blocks_sight(self, x, y, z) -> bool
    def surface_z(self, x, y) -> int
    def is_outside(self, x, y, z) -> bool
    def neighbours(self, x, y, z) -> Iterator[tuple[int,int,int]]   # incl. stairs/ramps
    def random_open(self, rng, z=None) -> tuple[int,int,int]
    def to_dict(self) / from_dict(cls, d)

LOCAL_W = 64 ; LOCAL_H = 48 ; Z_BELOW = 6 ; Z_ABOVE = 4

def generate_local(world, wx, wy, rng: RNG, *, site=None
                   ) -> tuple[LocalMap, list[dict]]
    # Returns the map together with the population spec list that
    # world/sitegen.py produced, which game/state.py uses to spawn inhabitants.
def LocalMap.central_open(self, rng) -> tuple[int, int, int]
    # The best arrival spot near the middle of the map: open ground, on a road
    # where there is one. Site maps are generated perfectly flat at z=0 so that
    # streets, halls and the people in them all share one level.
```
Generation: local heightmap interpolated from world neighbours, soil/stone layers,
trees per biome density, water bodies/rivers, cave systems below (cellular automata),
ore veins, and site structures via `world/sitegen.py`.

## 44. `world/sitegen.py`

```python
def build_site(lm: LocalMap, world, site, rng: RNG) -> list[dict]
    # returns "population spec" dicts: {"def_id","name","x","y","z","faction",
    #                                   "profession","hf_id","items":[...]}
def build_town(...) / build_fortress(...) / build_cave(...) / build_tower(...)
def build_ruin(...) / build_camp(...) / build_lair(...)
```
Towns get buildings with doors, roads, a tavern, a market, a keep, a temple;
fortresses get gates and underground halls; caves get winding tunnels; towers get
multiple z-levels.

---

## 45. `ui/*`

`ui/app.py` owns the state machine and the main loop.

```python
class App:
    def __init__(self, term: Terminal, *, seed: str | None = None,
                 debug: bool = False) -> None
    screen: Screen ; term: Terminal ; game: Game | None
    def run(self) -> int                      # process exit code
    def push(self, scene: "Scene") / pop(self) / replace(self, scene)

class Scene:
    app: App
    def on_enter(self) -> None
    def draw(self, scr: Screen) -> None
    def handle(self, key: str) -> None        # may call app.push/pop
    def tick(self) -> None                    # optional real-time update
    done: bool
```
Every screen module exposes a `Scene` subclass:
`menus.MainMenu`, `menus.SaveMenu`, `worldgen_screen.WorldGenScene`,
`charcreate.CharCreateScene`, `play_screen.PlayScene`, `look_screen.LookScene`,
`travel_screen.TravelScene`, `inventory_screen.InventoryScene`,
`character_screen.CharacterScene`, `legends_screen.LegendsScene`,
`help_screen.HelpScene`, `dialogs.*` helpers, `sidebar.draw_sidebar(scr, rect, game)`.

Layout (min terminal 80x24, target 100x34): map viewport left, sidebar right
(28 cols: name, needs gauges, wounds, equipped, time/date/weather, nearby
creatures), message log bottom (6 rows), top status line.

### Key bindings (documented in `help_screen` and README)

```
movement  hjkl yubn / arrows / numpad     < >  up/down stairs   .  or 5  wait
g  pick up      d drop        i inventory     e eat      q drink   w wield
W  wear         r remove      x look          t talk     T travel  s search
a  attack dir   f fire        Th throw        S sleep    C character sheet
L  legends      M world map   ? help          Esc menu   Ctrl-S save
z  skills       @ status      c craft         b butcher  , pick up all
```

---

## 46. `main.py` / `__main__.py`

```python
def build_parser() -> argparse.ArgumentParser
    # --seed S  --size SIZE  --history YEARS  --colors MODE  --unicode
    # --load PATH  --new  --headless SCRIPT  --version  --dump-world FILE
def main(argv: list[str] | None = None) -> int
```
`main()` must restore the terminal in a `finally` block and print a traceback to
stderr on crash (after restoring), never leaving the tty broken.

## 47. `tools/smoke.py`

Boots the app with a `HeadlessTerminal` and a scripted key list, asserts no
exception, and prints the final frame. Used by CI and by implementers to verify
integration:

```
python -m tools.smoke --seed test --keys "ENTER,ENTER,..." --frames out.txt
```

## 48. Tests (`tests/`, stdlib `unittest`)

Minimum coverage: colors, screen clipping/wrap, rng determinism, geometry, fov,
pathfind, scheduler, materials/bodies/items/creatures data integrity (every
referenced id resolves), worldgen determinism (same seed -> same world hash),
history invariants (no figure dies before birth), localmap connectivity,
combat (attacks terminate, corpses are produced), inventory/equip, save/load
round-trip, and a headless end-to-end smoke run.

Run with: `python -m unittest discover -s tests -v`

---

## 49. Implementation notes

Where the built code refines this contract:

- **Time.** One tick is one standard action for a creature of speed 100, about
  six seconds of world time. `engine/scheduler.py` grants `speed * ticks`
  energy per tick and an action costs `ACTION_COST` (100).
- **Bleeding is the usual cause of death.** `game/body.py` drains
  `BLEED_PER_POINT` litres per tick per point of wound bleeding, warns the
  player once per crossed blood threshold, and regenerates blood steadily once
  the wounds have closed.
- **`Scene.overlay`** — `ui/app.py` draws the deepest non-overlay scene and
  everything above it, so modal scenes (the pause menu) keep the map behind them.
- **`generate_local` returns a tuple**, as documented in section 43 above.
- **World serialisation rounds floats.** `world_hash` rounds rather than
  truncates so a save/load round trip cannot change a world's digest.
- **`Item.name()`** wraps the name in quality symbols and appends a wear marker;
  `article=True` picks "a"/"an" from the *unwrapped* name.

## 50. Style

- `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants.
- Dataclasses for plain data; `__slots__` where objects are numerous (tiles, cells).
- Serialization: every stateful class implements `to_dict()` and
  `from_dict(cls, d)`; ids are ints; references are stored by id, never by object.
- Flavour text matters. Messages should sound like Dwarf Fortress.
