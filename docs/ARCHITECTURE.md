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
            medical.py trade.py companions.py weather.py
  ui/       app.py menus.py charcreate.py worldgen_screen.py play_screen.py
            look_screen.py travel_screen.py inventory_screen.py character_screen.py
            legends_screen.py help_screen.py dialogs.py sidebar.py shop_screen.py
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

## 50. Later modules

Added after the first pass; the contract style above applies to them too.

### `game/medical.py`
```python
def treatable(creature) -> list[tuple[PartState, list[str]]]
def needs_treatment(part) -> list[str]        # "bandage" | "splint" | "suture"
def can_treat(healer, treatment) -> tuple[bool, str]
def treat(healer, patient, part_id, treatment, *, rng) -> list[Frag]
def diagnose(healer, patient) -> list[Frag]
def auto_treat(healer, *, rng) -> list[Frag]
```
Bandages cut a part's bleeding, splints set broken bones, sutures close deep
wounds. Each consumes its item and trains its skill; a skilled diagnostician is
told how many turns of blood are left.

### `game/trade.py`
```python
def is_trader(npc) -> bool ; def trader_kind(npc) -> str
def stock_merchant(npc, rng, *, tier=2) -> None    # idempotent
def price_to_buy(item, merchant, customer) -> int
def price_to_sell(item, merchant, customer) -> int
def wants(merchant, item) -> bool
def for_sale(merchant) -> list[Item] ; def sellable(customer, merchant) -> list[Item]
def buy(game, merchant, item, count=1) -> tuple[bool, str]
def sell(game, merchant, item, count=1) -> tuple[bool, str]
def rent_room(game, keeper) -> tuple[bool, str]
```

### `game/companions.py`
```python
def party_limit(player) -> int ; def can_recruit(npc) -> bool
def hire_price(npc, player) -> int
def recruit(game, npc) / dismiss(game, npc) -> tuple[bool, str]
def companions_of(game) -> list[Creature]
def bring_along(game, _unused) -> None      # re-place the party after a move
def on_death(game, npc) -> None
```
Companions are kept **out** of the per-tile creature cache and carried in
`Game.travelling_companions`, so they are never duplicated or left behind.

### `game/weather.py`
```python
class Weather:
    kind: str ; ticks_left: int
    def light_modifier(self) -> float ; def sight_modifier(self) -> float
    def tick(self, ticks, rng, biome, temperature, season) -> str
    def is_severe/is_cold/is_wet(self) -> bool
def starting_weather(rng, biome, temperature, season) -> Weather
```
Transitions are weighted by biome, temperature and season: no snow in a hot
desert, no rain below freezing.

### Additions to `game/state.py`
`Game.weather`, `Game.companion_ids`, `Game.travelling_companions`,
`Game.player_light()`, `Game._cache_order` (LRU order for `_local_cache`).

### Additions to `game/actions.py`
`light_source`, `treat_wound`, `diagnose`, `water_source_near`,
`refill_waterskins`.

## 52. Fortress mode (`fortress/`, `ui/fort/`)

Version 2.0. Fortress mode reuses everything below it — the same world, the
same local maps, the same bodies, the same combat, the same needs — and adds a
layer above: standing orders, a job board, and dwarves who choose their own work.

The player never controls a dwarf. The player paints designations, places
buildings and queues orders; `sim.step()` turns those into jobs and every dwarf
picks the nearest one its labors allow.

### `fortress/labors.py`
```python
LABORS: dict[str, Labor]           # 20 labors over 6 categories
DEFAULT_LABORS: frozenset[str]     # everybody hauls
PROFESSION_LABORS / PROFESSION_SKILLS: dict[str, ...]
STARTING_SEVEN: tuple[str, ...]
class LaborSet: has/enable/disable/toggle/by_category/to_list/from_list
def labors_for_profession(profession) -> LaborSet
def profession_title(dwarf) -> str          # named for its best skill
```

### `fortress/designations.py`
```python
KINDS: dict[str, DesignationKind]  # dig channel stairs ramp smooth chop gather remove
class Designations:
    cells: dict[Cell, str] ; claimed: dict[Cell, int]
    def valid(lm, x, y, z, kind) -> bool     # a wall for dig, a tree for chop
    def set/clear/paint_rect/clear_rect
    def claim(cell, dwarf_id) -> bool        # one miner per wall
def render(kind) -> tuple[str, Color]
```

### `fortress/jobs.py`
```python
@dataclass class Job: id kind x y z labor skill work progress priority
                      assigned target carrying failed
class JobBoard:
    def post/make/has_job_at/remove/clear_kind
    def reserve_item(item_id, job) -> bool   # two haulers never chase one rock
    def unassigned() -> list[Job]            # priority, then failures
    def for_dwarf(dwarf) -> list[Job]        # labor-filtered, nearest first
WORK_SCALE = 100
def work_rate(dwarf, job) -> int             # hundredths of a work point per tick
```
`work_rate` counts in hundredths so the gap between a novice and a legend is not
lost to integer truncation. A job's `work` reads directly as "about this many
ticks of labour".

### `fortress/buildings.py`
```python
KINDS: dict[str, BuildingKind]     # 23 kinds over Workshops/Furniture/Construction
class Building:  kind x y z built materials orders worker owner crop growth planted
class Stockpile: kind x y z w h ; def accepts(item) -> bool
def can_place(lm, kind, x, y, z, buildings) -> tuple[bool, str]
def material_matches(item, kind) -> bool
```

### `fortress/production.py`
```python
RECIPES: dict[str, Recipe]         # ~35 recipes across 7 workshops
CLASS_ITEMS: dict[str, tuple[str, ...]]   # STONE/WOOD/METAL/PLANT/FOOD
def recipes_for(workshop) -> list[Recipe]
def find_inputs(recipe, pool) -> list | None
def output_material(recipe, inputs) -> str
```

### `fortress/dwarf.py`
```python
class DwarfState: labors job path path_goal blocked sleeping nickname bed
                  mood mood_ticks idle_ticks squad carrying workshop
def attach(creature, profession) -> Creature      # adds .fort, .labors, .job
def make_dwarf(rng, profession, *, race="dwarf") -> Creature
def work_positions(lm, goal, *, vertical=True) -> list[Cell]
def at_or_beside(dwarf, cell, *, vertical=True) -> bool
def vertical_reach(job) -> bool                   # VERTICAL_JOBS: dig, channel, ...
def path_to(fort, dwarf, goal, *, adjacent=True, vertical=True) -> bool
def step_along(fort, dwarf) -> bool
def take_turn(fort, dwarf, ticks)     # danger -> needs -> job -> claim -> idle
```

Two invariants here are load-bearing, and breaking either kills a fortress
silently:

- **`work_positions()` and `at_or_beside()` must agree exactly**, `vertical`
  included. If a dwarf can path to a cell it does not believe it has arrived
  at, it walks on the spot until it dies of thirst.
- **Only digging reaches through a floor.** A miner cuts the rock under its
  feet, but reaching a *thing* — a barrel, an item to haul, a patient — needs
  real adjacency. With the generous rule everywhere, every thirsty dwarf in
  the fortress paths to the single tile under the ale, shoves the others off
  it in turn, and the whole crowd dies of thirst one tile from a drink.
- **Needs are served most-urgent-first, not in a fixed order.** A dwarf on a
  long walk to the ale barrel must be allowed to lie down before exhaustion
  kills it two tiles short.

`step_along` also refuses to wait politely: after one beat it shoulders past the
dwarf in its way. Politeness deadlocks a queue at a single barrel.

### `fortress/fortress.py`
```python
class Fortress:
    world local rng time log designations jobs buildings stockpiles
    creatures items_on_ground weather paused speed z ticks season_index
    lost loss_reason wealth migrant_waves siege_count artifacts caravan
    @classmethod embark(world, wx, wy, rng, *, name="", professions=())
    def dwarves/hostiles/creature_at/kill_creature
    def drop_item/take_item/item_cell/items_at/find_item/stock_count
    def food_stock/food_reserve/find_consumable/consume
    def water_sources/nearest_water                 # cached; rivers and wells
    def job_items/fetch_target/pick_up_for/put_down # the fetch phase of a job
    def prepare_job/cancel_preparation/abandon_job/complete_job
    def _finish_<kind>(dwarf, job)                  # one per job kind
    def to_dict/from_dict
SEED_RESERVE = 6 ; FOOD_RESERVE_DAYS = 8
```
`DwarfState` is serialised separately, keyed by creature id, so `Creature`
itself stays identical between the two modes and a dwarf could in principle be
handed to adventure mode unchanged.

The two reserves are what stop a fortress destroying itself: farmers will not
eat the last of the seed, and a still on repeat will not brew the last week of
food into ale.

### `fortress/sim.py`
```python
STEP_TICKS = 10 ; SCAN_INTERVAL = 60
MAX_HAUL_JOBS / MAX_DIG_JOBS / MAX_NEW_JOBS       # the board is bounded
GROW_TICKS = TICKS_PER_DAY * 5 ; MOOD_ODDS = 120000
def step(fort) / run(fort, steps)
def scan_jobs(fort) -> int
    # designations -> buildings -> farms -> workshops -> stockpiles
def migrants(fort, count) -> list[Creature]
def spawn_attack(fort, strength) -> list[Creature]
def appraise(fort) -> int
def record_fall(fort) -> None       # writes the fortress into world history
```
`step()` runs: weather, a periodic job scan, needs and wounds, every dwarf,
every hostile, crops, moods, the calendar, then the loss check. Designations are
scanned into jobs rather than being jobs, so you may paint ten thousand tiles
and only sixty are ever live work.

### `ui/fort/`
```
render.py       cell_appearance, draw_map (zones, designations, buildings,
                items, creatures, cursor, drag region, building ghost)
sidebar.py      draw_sidebar / draw_log / draw_status_line
fort_screen.py  FortScene (realtime), FortEndScene, SCROLL_KEYS, scroll_delta
cursor.py       CursorScene: move, anchor a corner, apply a rectangle
designate.py    DesignateScene
build_menu.py   pick_building, BuildScene, StockpileScene
units.py        UnitsScene, LaborScene
stocks.py       StocksScene
orders.py       pick_workshop, OrderScene
trade_screen.py open_trade, TradeScene
embark.py       site_score, suggest_site, EmbarkScene
```
Fortress mode moves a camera rather than a character, so scrolling lives on the
arrows and the numpad and every letter stays free for a command. A test asserts
no command key is shadowed by `scroll_delta`.

### Additions elsewhere

- `ui/app.py`: `Scene.realtime` and `Scene.frame_time`. The main loop gives a
  real-time scene a timed `read_key()` and ticks it whether or not a key came in.
- `game/save.py`: `save_fortress` / `load_fortress` / `list_fortresses` /
  `describe_fortress`, using the `.awf` suffix beside adventure's `.aws`.
- `world/localmap.py`: `neighbours()` is now **symmetric**. It previously let a
  creature walk down a staircase onto a plain floor with no way back up — a
  one-way edge A* would happily route through, stranding whoever took it.
- `game/needs.py`: `NUTRITION_SCALE`, `HYDRATION_SCALE` and `STRESS_DECAY`. One
  unit of a staple is most of a day; unconsciousness counts as sleep, so a
  creature that collapses from exhaustion can wake up again; and feelings fade.
- `world/tiles.py`: `farm`, `farm_planted`. `data/items.py`: `coffer`, `bin`,
  and jewellery (`crown`, `amulet`, `ring`, `earring`, `bracelet`).

## 53. Military, health, rooms and legacy (v2.1 - v2.4)

### `fortress/military.py`
```python
UNIFORMS: dict[str, Uniform]     # axe hammer sword spear marksdwarf
SQUAD_SIZE = 10 ; ORDERS = ("train", "station", "defend", "kill")
class Squad:   id name uniform members order station target barracks
class Military:
    squads: list[Squad] ; alert: str ; burrow: tuple|None
    def enlist/discharge/squad_of/soldiers/sound_alarm/all_clear/in_burrow
def wanted_items(squad, dwarf) -> list[str]   # one weapon, one per armour slot
def armed(squad, dwarf) -> bool ; def readiness(squad, fort) -> (armed, total)
def combat_level(dwarf) -> int
```
Equipment jobs are posted at priority 9 and **assigned directly** rather than
left on the board. Training jobs are posted one per squad member, at priority
8: with a single job the same dwarf takes it every time and the rest of the
militia never picks up a shield. A squad ordered to train is off the labour
force, which is the cost of having one.

### `fortress/hospital.py`
```python
REST_BLOOD / REST_PAIN / CRITICAL_BLOOD ; TREAT_WORK = 30
def is_hurt(dwarf) / is_critical(dwarf) -> bool
def needs_care(dwarf) -> list[(part id, treatment)]
def patients(fort) / doctors(fort) / hospital_beds(fort) -> list
def free_bed(fort, dwarf) / release_bed(fort, dwarf)
def supplies(fort, treatment) / can_supply(fort, treatment)
def treat(fort, healer, patient, part_id, treatment) -> None
def summary(fort) -> list[(name, condition, wanted)]
```
`sim._triage()` runs **every step**, not on the once-a-minute job scan: a dwarf
with a severed artery does not have a minute. The nearest free doctor is
assigned directly for the same reason.

### `fortress/rooms.py`
```python
ROOM_KINDS: dict[str, str] ; FURNITURE_VALUE: dict[str, int]
def room_cells(lm, centre) -> list[Cell]   # flood fill, stops at walls & doors
def measure(fort, building) -> Room        # quality from furniture + smoothing + size
def rooms(fort) / room_of(fort, dwarf) / dining_quality(fort) / value(fort)
```
`Room.thought` is the seasonal stress change from living there.

### `fortress/nobles.py`
```python
POSITIONS: dict[str, Position]   # leader, manager, broker, chief medical,
                                 # sheriff, mayor — each at a population
MANDATES: tuple[(target, kind, text), ...]
STRESS_UNHAPPY / STRESS_TANTRUM / STRESS_BERSERK ; TANTRUM_ODDS
class Noble: position dwarf_id since mandate
class Court: appoint/vacate/holder/position_of/title_of
def mandate_met(fort, mandate) -> bool
```
`sim._appointments()` fills posts each season and only issues mandates for
things the fortress does *not* already have. `sim._tantrums()` turns stress
into broken furniture and then into a berserk dwarf, which is an ordinary
hostile with a name you recognise.

### `fortress/legacy.py`
```python
def preserve(fort) -> dict            # map, creatures, items, buildings
def make_site(fort) -> Site           # the fortress on the world map
def record(fort, *, abandoned=False) -> Site
def describe(payload) -> list[str]    # for the travel screen
def restore(payload) -> dict|None     # into the local-map cache shape
```
This is the bridge between the two modes. `World.preserved` keeps hand-built
local maps keyed `"wx,wy"`, and `Game.enter_world_tile()` checks it before
generating, so a fortress you abandoned is the map you walk into as an
adventurer — same corridors, same workshops, same corpses. The founding, the
fall and any strange-mood artifacts become real history the legends viewer
shows.

### Additions elsewhere

- `world/worldgen.py`: `World.preserved`, `preserve()`, `preserved_map()`,
  serialised with the world.
- `world/tiles.py`: `barracks`, `trap`, `hatch`.
- `game/combat.py`: `trap_strike()` — traps do not miss and cannot be parried,
  but armour still counts.
- `game/body.py`: `REST_CLOT_TICKS`. `rest_heal()` used to zero the bleeding on
  every wound and delete the wounds outright, so lying down for one tick was a
  complete cure, in adventure mode as much as in the fortress.
- `fortress/jobs.py`: `JobBoard.assign()` releases any job the dwarf already
  holds. Without it a dwarf given a second job orphaned the first for ever —
  it never returned to the board and nobody could ever do it.
- `ui/fort/`: `military_screen.py`, `health.py`; `BurrowScene` in
  `build_menu.py`.

## 54. Water and engineering (v2.5)

### `world/fluids.py`
```python
MAX_DEPTH = 7 ; SWIM_DEPTH = 4 ; EVAPORATE_AT = 1
MAX_ACTIVE = 2500 ; PUSH_RANGE = 400
def can_hold(lm, cell) -> bool    # walls, shut doors and raised bridges say no
class Water:
    depth: dict[Cell, int]        # 1..7, absent when dry
    sources: dict[Cell, int]      # aquifers and springs, produce for ever
    infinite: dict[Cell, int]     # river and lake cells, a fixed reservoir
    sealed: set[Cell]             # the bed and banks, watertight until dug
    def at/deep/wet/set/add/add_source/total
    def step(lm)                  # sources -> push -> natural feed -> fall -> spread
    def seal_banks(lm) / unseal(cell) / rebuild_shore() / wake_all()
def seed_from_terrain(lm) -> Water
```
Five rules make this behave, stay cheap, and still be dangerous:

- **Only wet cells and their neighbours are simulated.** An active set is woken
  by any change; a still map costs nothing.
- **Natural bodies are reservoirs, not weather.** They feed what you dig beside
  them but never spread on their own, or a river creeps over the whole map.
- **Their bed and banks are sealed at generation.** A riverbed holds its water
  until something breaks it, and `unseal()` is what breaking it looks like.
- **Two deep is the smallest difference worth moving.** Half of two is one,
  which levels the pair exactly; chasing a difference of one moves nothing and
  keeps every cell in the pool awake for ever.
- **A saturated source pushes past the level.** Because of the rule above,
  water settles into a shallow staircase and stops. `_push()` walks out from
  any source that has filled its own cell — down and outward, never up, at
  most `PUSH_RANGE` cells — and puts one unit into the nearest shallow water.
  That is the pressure behind an aquifer, and without it breaching one leaves
  a puddle instead of a disaster.

Water only evaporates outdoors. Underground a puddle stays, or a flooded room
quietly empties itself and the flood means nothing.

### Additions to the fortress
```python
Fortress.water / .aquifer / .drowning / ._water_mark
Fortress.dig_out(cell, tile)      # the ONLY way terrain changes
Fortress.path_neighbours(node)    # refuses water deep enough to swim in
Fortress.levers() / gates() / link() / set_gate() / pull_lever()
Fortress._lay_aquifer(rng)        # one whole layer of wet rock
sim._flow(fort, ticks)            # water step, drowning, the flood warning
sim._scan_levers(fort, budget)    # posts the pull job
dwarf._flee_water(fort, dwarf)    # drop the job, get out of rising water
DROWN_STEPS = 6 ; FLOOD_WARN = 1200
```
Everything that changes a tile goes through `dig_out()`, so the water always
finds out. A tunnel that reaches an aquifer and does not flood is a bug the
player cannot see until it is too late to matter. It only breaks the bank when
the tile actually *opens* — smoothing a wall, laying a farm plot and gathering
plants all pass through here and must leave the river where it is.

### Additions elsewhere
- `data/items.py`: `mechanism`; `production.py`: the recipe for it.
- `world/tiles.py`: `lever`, `floodgate_open` / `floodgate_shut`,
  `bridge_down` / `bridge_up`.
- `fortress/buildings.py`: `lever`, `floodgate`, `drawbridge`; `GATE_TILES`
  maps each gate kind to its open and shut tiles; `Building.links`, `.shut`,
  `.pending`.
- `ui/fort/levers.py`, and depth-shaded water in `ui/fort/render.py`.

## 55. The metal industry (v2.6)

Veins are decided at generation and remembered cell by cell, so a fortress can
dig *towards* something:
```python
LocalMap.veins: dict[Cell, str]   # cell -> metal, gem or coal; saved with the map
localmap.ORE_WEIGHTS              # copper and iron common, platinum a story
localmap._add_ore(lm, rng)        # blobs that stay inside the rock
tiles: ore_vein / gem_vein / coal_seam
Fortress._stone_here(cell)        # reads lm.veins, never rolls a die
Fortress._mined_item(cell, mat)   # ore, coal, rough gem, or a plain boulder
```
Rolling the metal when the wall is mined would mean the player could not plan
around what they had found, which is most of what a fortress does.

The chain is three workshops and four recipes:
```
wood_furnace  WOOD 1                          -> charcoal x2
smelter       ore 1 + FUEL 1                  -> bar (the ore's own metal)
smelter       bar:copper + bar:tin + FUEL     -> bar x2, forced to bronze
smelter       bar:iron + FLUX + FUEL x2       -> bar, forced to steel
smith         BAR n + FUEL 1                  -> weapons, armour, bolts, mechanisms
```
Three small additions to `production.py` carry it:

- **Classes.** `BAR`, `ORE`, `FUEL` (charcoal or coal) and `FLUX` (limestone,
  marble or chalk) join `STONE`/`WOOD`/`PLANT`/`FOOD`. `METAL` now means a
  bar, not a metal boulder.
- **`bar:copper`.** A requirement may name one material after a colon, which
  is what makes an alloy an alloy.
- **`Recipe.out_material`.** Bronze is not made of copper and charcoal is not
  made of oak, so a recipe may force what comes out.

`sim._anybody_does(fort, labor)` gates every workshop job: if no living dwarf
has the labor, nothing is posted and the log says so once. A job nobody will
take used to sit on the board looking like a broken workshop.

## 56. The world keeps turning (v2.7)

### `world/livingworld.py`
```python
SEASONS_PER_YEAR = 4 ; MAX_BEASTS = 8 ; GROWTH = 0.015 ; POP_CAP = 1500
TOLD_ABOUT: frozenset       # the event kinds people actually repeat
def advance(world, rng, year, *, seasons=1) -> list[Event]
def season_index(time) -> int        # the edge both modes hang off
def news_since(world, mark, n=3) -> list[Event]
def rampage(world, rng, year, beast) # one beast, one town, maybe a hero
def slay(world, year, killer, beast, where, site=None)
def wandering_beast(world, rng, year)
```
One season of world history per season of play, in both modes: towns grow,
rulers die, heroes rise, beasts wake and fall on settlements, wars are declared
and settled, smiths forge legends, outlaws gather, plagues pass, ruins are
resettled. Bounded work — a fixed handful of rolls plus one sweep of the site
list — because it runs inside the fortress's season change.

It deliberately **does not** share code with `history._simulate_year`. Worlds
must stay reproducible from their seed, and that stops being true the moment
tuning how a season of play feels can change how a world is generated.

Two invariants the sweep enforces, both learned the hard way:

- **Something has to put people back.** Wars, plagues and beasts only ever
  subtract. Without growth every settlement drains to nothing in about twenty
  years of play.
- **An empty settlement is a ruin.** A town at zero population that still
  counts as a town is a place the adventurer walks into expecting shops.

### Where it plugs in
```python
sim._world_turns(fort)        # on the season change in _calendar
sim._maybe_beast(fort)        # BEAST_WEALTH = 4000, BEAST_ODDS = 0.06
sim.spawn_beast(fort, beast)  # the figure's name, title and hf_id on a creature
sim._caravan_news(fort)       # the traders have seen things on the road
Fortress._record_kill(c)      # hf-linked deaths go back into world history
Game._world_season()          # adventure side, off _tick_world
QuestLog.world_changed(game)  # a quest whose target somebody else killed fails
conversation.rumor_lines()    # one pick is always from the last two years
```
The payoff is the megabeast: a fortress worth the walk is visited by a named
figure out of the legends screen, and if the militia brings it down, the world
records that your fortress is where it died.

## 57. Magma and the deep (v2.8)

Magma is `Water` with three class constants changed, because water's machinery
— reservoirs, sealed banks, pressure from a source, the active set — had
already been debugged the hard way:
```python
class Magma(Water):
    NAME = "magma" ; EVAPORATES = False ; VISCOSITY = 3
def quench(magma, water, lm) -> list[Cell]   # both spent, obsidian left behind
def seed_magma(lm, floor, extra) -> Magma    # the sea, and the pipe above it
BURN_DEPTH = 1                               # there is no safe depth
```

### The shape of the bottom of the world
```python
localmap.carve_deep(lm, rng) -> {"floor": z, "hollow": {...}, "spire": (x, y),
                                 "tube": {...}}
Fortress.embark: Z_BELOW 10 -> 13            # room for the sea under the caverns
tiles: warm_stone, obsidian_wall, adamantine_vein
```
The sea is the bottom two levels, hollowed out and filled. Magma does not
climb, so a sea nobody can reach would be scenery: `_magma_tube` stands a pipe
of it up into the working levels, sealed by rock until somebody mines into the
side of it. The cap above the sea is `warm_stone`, which is the only warning
the player gets and is worth more than any number of log lines.

### The pit
```python
Fortress.hollow / .breached / .breach_cell
Fortress._breach_the_spire(cell)   # from dig_out, once, and then for ever
sim.spawn_demons(fort, cell, wave) # DEMON_FIRST_WAVE = 6, DEMON_WAVE = 3
```
The spire is adamantine all the way through except its centre, which is empty.
Mining the centre is the last decision a lot of fortresses make: demons come up
at once and another wave arrives every season, because nothing can be done
about the hole. The world records it, so it shows up in the legends screen.

### Two performance rules learned here
- **The shore is only the cells that can pour somewhere.** Without the
  `can_hold` check a ten-thousand-cell magma sea puts its entire surface on the
  shore list and the fortress spends 10 ms a step rediscovering that rock is
  rock.
- **`unseal()` patches the shore, it does not rebuild it.** A rebuild is a
  sweep of every reservoir cell, and a fortress swings a pick rather often.

### Order matters in `sim._magma`
Burn creatures *before* casting obsidian: a dwarf standing in magma dies of the
magma, not of the wall somebody made out of it half a step later. A creature
standing where the cast lands is encased instead, which is its own way to go.

## 58. Animals (v2.9)

### `fortress/animals.py`
```python
class Animal: pasture owner hunger produce_at breed_at slaughter wild
class Pasture: id x y z w h                  # painted with n
EMBARK_ANIMALS = 2 dogs, a cat, 2 cows, 2 sheep
GRAZE_TICKS = 20 days ; FODDER_AT = 8 days ; FODDER_RESERVE = 20
PRODUCE = {cow: milk, sheep: wool} ; PRODUCE_TICKS = 12 days
BREED_TICKS = 30 days ; HERD_CAP = 10
def step(fort, ticks)          # graze, follow, wander, breed, starve
def spawn_wildlife(fort, rng)  # something moving that is not yours
def produce / butcher_yield / ready_to_produce
```
An animal is a creature with an `.animal` state where a dwarf has a `.fort`
state. Nothing here gives an animal a job: they are livestock, not labour, and
the dwarf side of the work is two ordinary jobs — `tend` (milk or shear) and
`slaughter`, posted by `sim._scan_animals`.

Three rules the milestone turned on:

- **Animals do not use dwarf needs.** `_bodies` skips `needs.tick` for them.
  Ticking thirst on a cow killed the entire herd in three days with a river
  running past the pasture, because nothing was ever going to walk it to the
  water.
- **A mountain has no grass.** The classic dwarven embark would starve its
  livestock every single game, so a hungry grazer eats from the food stores
  above a reserve and says so. Painting a pasture on grass is the fix, and the
  message says which key does it.
- **Jobs aimed at something that walks are keyed by target, not by cell.**
  `JobBoard.has_job_for(kind, target)`: post by cell and the sheep takes two
  steps, another job appears, and the whole fortress queues up to shear it.

Two older bugs fell out of the same idea. A job aimed at a creature has to
follow it: `dwarf.CHASING_JOBS` (`treat`, `tend`, `slaughter`) re-points the
job at its target every turn through `JobBoard.retarget`, because a wounded
dwarf walks to a bed while the doctor walks to where it used to be and the two
of them chase each other until one bleeds out. And `hospital.supplies()` now
takes the *nearest* bandage rather than the first one in dict order — a doctor
that walks past the bandages at the patient's feet to fetch identical ones
from the wagon arrives too late.

`Fortress._free_spot` also had to be rewritten to walk one ring at a time.
Scanning the whole square at every radius counts the middle over and over, so
callers with different offsets got the same tile — every animal (and every
migrant wave) arrived standing on one another.

## 59. War (v3.0)

### `fortress/war.py`
```python
class Siege: civ_id commander_hf strength killed routed recorded fleeing_since
RAIDERS = ("goblin", "kobold") ; NOTICE_WEALTH = 500 ; BASE_STRENGTH = 3
ROUT_LOSSES = 0.55 ; FLEE_TICKS = 3000
def home_civ(fort) / enemies(fort)      # who sent you, and who wants you gone
def strength_for(fort, civ)             # wealth pulls, their population caps
def commander(fort, civ)                # a real figure, or a new one recorded
def plan(fort) -> Siege / launch(fort, siege)
def on_kill(fort, foe) / rout(fort) / retreat_step(fort, foe)
def record(fort, *, won)                # legends, and the enemy's own losses
```
A siege used to be `spawn_attack(fort, strength)` — a number of goblins at the
map edge. Now it is an act by a civilization from the world's history, and the
result is an act on it:

- **They can only send what they have.** `strength_for` caps the army by the
  attacker's living population, so a nation you have beaten twice sends a
  smaller army the third time.
- **Armies break.** At `ROUT_LOSSES` the survivors run for the nearest edge and
  leave the map. Invaders that fight to the last are a grind that takes the
  fortress with them. A rout that gets wedged in a corridor is gone anyway
  after `FLEE_TICKS`, or the alarm never stops ringing.
- **The dead come off the population that raised them.** Winning is the only
  thing a fortress does that makes the world easier, and `history.record`
  writes both outcomes: who broke against your walls, or who overran you.

`Fortress.civ_id` is the expedition's home civilization, found on demand.
Everything the living world does to civ relations — declaring war, making peace
— feeds `enemies()` without any further plumbing.

## 60. Engravings (v3.1)

### `fortress/art.py`
```python
class Engraving: quality text event_id maker
QUALITY_NAMES ; QUALITY_VALUE ; ADMIRE_AT = 4
SUBJECTS: event kind -> the picture   # "%(a)s is striking down %(b)s."
RELATES:  event kind -> the caption   # "the slaying of %(b)s by %(a)s"
def subject(fort, rng) -> (text, event_id)
def engrave(fort, dwarf, cell) / at / room_value / admire
```
An engraver smooths a wall and then carves a real event out of `world.events`
into it, phrased in two halves: the picture ("Urist the dwarf and a dragon.
The dragon is striking down Urist.") and the caption ("The artwork relates to
the slaying of Urist by the dragon Uzol in the year 174."). Reading only —
nothing here writes to history.

Three details that make it read right rather than merely work:

- **Recent history first.** Sixty per cent of subjects come from the last
  twenty-five events, and anything that happened at this fortress is weighted
  again on top. Otherwise a fortress spends its life carving the fourteenth
  village its civilization founded three centuries ago.
- **The caption is a noun phrase**, per event kind, falling back to the first
  sentence of the historian's text. "The artwork relates to the battle at
  Boatspring" reads; "relates to the Diamond Bridges broke against Boatspring.
  4 of them died" does not.
- **Plain names in pictures.** "Urist the dwarf", not "Urist Ironhand the
  Brave the dwarf": the engraving is a picture, not a citation.

`engrave` is designation `engrave` -> job -> `Fortress._finish_engrave`, valid
only on `wall_constructed` (a smoothed wall), with its own labor and the
existing engraving skill. `rooms.measure` counts `art.room_value` of the walls
around a room, and `sim._season_thoughts` calls `art.admire`.

## 61. Renown (v3.2)

### `game/renown.py`
```python
KILL_RENOWN = {megabeast: 25, semimegabeast: 12, night: 10, bandit: 6,
               leader: 8} ; QUEST_RENOWN = 8
TITLES: wanderer -> traveller -> adventurer -> champion -> hero -> legend
def figure(game)                 # the player's HistoricalFigure, made on demand
def renown(game) / add(game, n) / title(game)
def record_kill(game, victim) / record_quest(game, quest)
def retire(game)                 # alive, in the world, still in the legends
def summary(game)                # the Deeds block on the character sheet
```
The adventurer used to enter history exactly once, at death. Now the figure
exists from the first turn — everything that happens needs somebody to be
attributed to — and renown lives in `fig.stats["renown"]`, on the figure,
because the figure is what survives the save, the death and the game.

Three rules keep the legends readable:

- **Only notable kills are recorded.** `kind_of()` gates on megabeast,
  semi-megabeast, night creature, bandit or leader. A legends screen listing
  every rat is a legends screen nobody reads.
- **Only what you saw.** `can_see_creature` gates attribution, because
  `Game.kill_creature` runs for every death on the map, not only the player's.
- **The creature's own death handler dates the figure; `record_kill` names
  the killer.** Requiring `fig.died is None` silently attributed nothing.

Renown is visible in play rather than only on the sheet: `conversation.
greeting` changes with standing, `quests.generate_quest` scales the reward by
`1 + renown/120`, and the pause menu can retire the adventurer — the opposite
of dying, and the adventure-mode mirror of retiring a fortress in v2.4.

## 62. Crime and punishment (v3.3)

### `fortress/justice.py`
```python
CRIMES = {vandalism:1, assault:2, theft:2, murder:4, neglect:1}  # kind -> severity
JAIL_TICKS = 4 days per point ; COLD_CASE = 90 days ; UNSOLVED_STRESS = 3
class Crime: id kind culprit tick detail convicted until pardoned
def report(fort, kind, culprit, detail) -> Optional[Crime]
def open_cases / cold_cases / serving / is_jailed / culprit_of / describe
def sheriff(fort) / can_try(fort, crime) / hold_court(fort) / convict / pardon
def tick(fort)     # every step: hold court every 3 days, release the served
def season(fort)   # unsolved crime raises stress; warns to appoint a sheriff
def days_left(fort, crime) / summary(fort)
```
The fortress had dwarves who smash the furniture and mayors who demand statues
nobody builds, and no consequences for any of it. This is the consequences.

Four things generate crime, and none of them is a special case bolted on:

- **Vandalism** — `sim._throw_tantrum` already destroyed a building; now it
  writes down who.
- **Assault**, and **murder** when it goes too far — `sim._start_brawl`, taken
  35% of the time in place of breaking furniture. One barehanded blow at an
  adjacent dwarf: a fistfight in the dining hall is a crime and a bruise, not
  an execution, but `melee_attack` is real combat and it can still kill.
- **Theft** — `sim._maybe_thief` sends one kobold a season at a fortress worth
  400. It walks to the nearest item worth 20, takes it, and leaves by
  `war.retreat_step`. The crime is filed with `culprit=None`.
- **Neglect** — `sim._blame_for_mandate` pins an ignored mandate on the
  manager, or the expedition leader if there is no manager. Never the mayor.

Five rules make it a system rather than a log:

- **A thief is not a siege.** `Fortress.hostiles()` excludes `c.thief`, so one
  kobold with its eye on a mug does not sound the alarm, call up the militia
  and stop everybody drinking. The fortress finds out from the gap where the
  mug used to be. Dwarves that can *see* it still react — soldiers chase,
  civilians run — because `dwarf._handle_danger` scans the faction directly.
  The alarm is fortress-wide; seeing a kobold is local.
- **Nothing may loiter.** A thief that finds nothing worth taking leaves after
  `THIEF_PATIENCE`, and one that cannot walk out at all — `retreat_step` heads
  for the nearest edge on one z-level, so a robbery five levels down ends at a
  wall — is gone after `THIEF_GONE`. Both are the lesson `war.FLEE_TICKS`
  already learned: a creature wedged in a corridor that nobody hunts is a
  permanent resident, and every dwarf working near it flees for ever.
- **A crime with no suspect cannot be tried.** `can_try` needs a living
  culprit still in the fortress. A theft in the night stays open until
  `COLD_CASE`, and `season()` charges the fortress stress for every day of it.
  That gap is the pressure to appoint a sheriff, not a bug in the trial.
- **The law has to be visible.** `tick()` holds court every three days, not
  once a season: a bad week fills the book with a dozen cases, and a sheriff
  who answers them in three months is a sheriff nobody can see working. The
  status line carries both halves — unsolved *and* serving — because a
  fortress with four fifths of its labour in a cell needs telling.
- **A sentence has to cost something.** `dwarf._serving_time` runs after needs
  and before jobs: a convicted dwarf eats, drinks and sleeps, drops its job
  and takes no other. Four days without your legendary mason is the entire
  point of having a law, and `pardon()` is the button that buys the mason back
  at the price of everyone else's opinion of you.

`ui/fort/justice_screen.py` (`c`) is the sheriff's book: open cases, sentences
with days left, and what went cold. Enter tries a case now rather than waiting
for the season; `p` pardons. The status line carries `justice.summary` and the
units list shows "serving time" where the job would be.

## 63. Friends, families and the tavern (v3.4)

### `fortress/social.py`
```python
LEVELS: 80 close friend / 45 friend / 15 friendly with / -14 knows /
        -44 annoyed by / -100 enemy of
APPROACH = 14 ; MEET_COOLDOWN = 1 day ; CENTRE = 0.19 ; SPREAD = 1.6
LOVE_AT = 70 ; MARRY_ODDS = 0.4 ; CHILD_AGE = 12 ; BIRTH_ODDS = 0.35
class Bond: a b value kind met      # kind: lover/spouse/widowed/child
def compatibility(a, b) -> -1..1 / ceiling(a, b) -> -100..100
def meet(fort, a, b) / bond / bonds_of / spouse_of / describe / forget
def grieve(fort, dead)              # thoughts in proportion to the bond
def court(fort) / eligible / couples / maybe_born / born / birthdays
def lonely(fort, dwarf) / season(fort) / is_child / children / summary
```
A fortress used to be seven strangers sharing a corridor. Every dwarf got the
same thought when anybody died — "lost a friend to a violent death" — whether
they had ever stood next to the corpse or not, which is the kind of detail
that quietly admits the friendship was never modelled.

**Compatibility is a ceiling, not a rate.** This is the load-bearing decision.
As a rate, every pair given enough months in the same room ends up
inseparable, and thirty days of tavern turned a seven-dwarf fortress into a
commune where every bond sat at 100. As a ceiling, a merely agreeable pair
plateaus as friendly acquaintances and stays there for ever, and only a
well-matched one gets as far as marrying. `CENTRE`/`SPREAD` then pull tails
out of what is otherwise a narrow band of mild fondness — they are all the
same race with the same racial bias, so raw compatibility never goes negative
and never gets close. Tuned to roughly: a quarter of pairs can become friends,
1.5% close friends, 4% could be lovers, 7% end up annoyed, 0.6% enemies.

**Bonds move where dwarves already are.** `sim._mingle` buckets dwarves by
cell each step and pairs up neighbours; `meet` closes `1/APPROACH` of the
distance still to run, once per pair per day. There is no socialising
simulation and no social job — which is why the tavern matters. It is a
building that defines a room (`rooms.ROOM_KINDS`), and `dwarf._to_the_tavern`
sends idle dwarves to it instead of wandering. Two miners sharing a shaft
become colleagues over months; the tavern is faster only because it is where
everybody with nothing to do ends up at once.

Two things had to be got right for the tavern not to cost more than it is
worth. Nineteen dwarves converging on one 3×3 building shove each other off
it for ever, and every shove throws away a path and buys another A* search —
so "arrived" means anywhere within `TAVERN_RADIUS` of the middle, and a dwarf
that has arrived clears its path and stops planning. Route-finding is gated to
one attempt per `TAVERN_REPATH` idle ticks; walking is every tick. With those,
a 19-dwarf idle fortress runs *faster* with a tavern (1.6 ms/step) than
without one (5.1 ms/step, the same on v3.3), because idle dwarves stop
wandering the map.

**Grief replaces a lie.** `Fortress.kill_creature` used to hand +18 stress to
everybody; now it calls `social.grieve`, which pays out on the actual bond —
90 for a spouse or a child, 45 for a close friend, 8 for somebody you knew,
and `SPITE` (a guilty −6) for an enemy — and everybody else merely "saw a
death in the fortress". A widow's bond becomes `widowed` rather than being
deleted, and the dead keep their bonds, because who the dead were close to is
exactly what the survivors are grieving.

**Lovers marry; there is no second threshold.** An earlier draft needed a bond
of 90 to wed, which only 0.4% of pairs could ever reach — a wedding the game
would never show anybody. Now `LOVE_AT` makes lovers of a pair whose ceiling
is high enough and whose `love_propensity` rolls, and lovers marry on seasonal
odds. Married couples have children if the fortress has food and room;
children take no jobs (`dwarf._too_young` idles them, so they end up in the
tavern making friends of their own), age a year per fortress year via
`social.birthdays`, and pick up a profession and its labors on the birthday
they stop being children. Marriages and births are written to world history,
so an adventurer can read about them three centuries later.

`ui/fort/units.py` shows the bonds in a dwarf's detail panel, closest first,
and "playing" where the job would be for a child. The status line carries the
child count; `profession_title` returns "Child".

## 64. The night (v3.5)

### `game/night.py`
```python
RAISE_RANGE = 7 ; RAISE_COOLDOWN = 60 ticks ; RAISE_MIN_SIZE = 3000
CURSES = {werebeast -> werewolf @0.30, vampire @0.10} ; CARRIERS = inverse
FULL_MOON = "full moon"   # the calendar's own name, not a second calculation
FEED_SHARE = 0.28
def is_necromancer / raisable / corpses_near / raise_corpse / necromancy_turn
def cursed_with / afflict / on_bite / moon_is_full / should_change
def transform(world, c) / revert(world, c)
def is_vampire / can_feed_on / feed(world, vampire, victim)
```
The world had generated necromancers, given them towers and stocked those
towers with zombies since v1. It generated vampires and werewolves too. None
of it did anything: the undead stood where the map maker put them, and a
werewolf was a wolf that hit harder.

Each of the three is a rule about **time and place**, not a monster:

- **The corpse on the floor.** `necromancy_turn` runs before either AI decides
  where to walk, in both modes — a necromancer with a body in front of it does
  not chase you, it makes the body chase you. It raises what *you* killed, so
  a tower stops being a queue of zombies and becomes a fight you lose slowly
  until you reach the necromancer. Killing it ends the loop; that is the
  design, and `test_a_dead_necromancer_raises_nothing` pins it.

  **A body rises once.** `corpse_of` marks the corpse of anything that was
  itself raised, and `raisable` refuses it. The first build had no such mark:
  the militia put a zombie down, the corpse went back on the floor, and the
  same body got up again for ever. A full-scale raid went from 13 raisings, 12
  undead standing and 9 dead dwarves to 1 raising, 0 dead dwarves and a
  necromancer killed at step 826 — an unbounded grind turned into a fight.
- **The phase of the moon.** `moon_is_full` asks the calendar for its own
  phase name rather than recomputing the cycle. The first version computed
  `day % 28` independently and turned people on a night the status bar called
  "waxing gibbous" — one source of truth, or the UI lies on the worst night of
  the year. A cursed dwarf that turns is discharged from the militia and
  vacated from office until dawn, and `Fortress.dwarves()` filters it out —
  but it *keeps its DwarfState*. Clearing that state is the obvious way to
  take it off the roster and it loses the dwarf permanently the moment
  somebody saves during a full moon, because only creatures with a DwarfState
  get serialised at all. The player keeps its own side, because a game that
  takes the character away is not a game.
- **The dwarf who sleeps alone.** `sim._feed_vampires` drains the nearest
  sleeping dwarf, ~28% of its blood a night, so somebody looks peaky for three
  nights before anybody finds a body. The crime is filed with `culprit=None`
  unless somebody awake was within four tiles — which means a dormitory
  catches a vampire and a corridor of fine private bedrooms never does. An
  unwitnessed feeding is a murder `justice.can_try` returns False for: it sits
  open until it goes cold and charges the fortress stress every season it
  does. That is v3.3's unsolvable-case machinery finally having something
  genuinely unsolvable to hold.

**Curses travel by bite.** `combat.melee_attack` calls `night.on_bite` when
the attack that landed is in `BITES` — being clawed by a werewolf is a bad
afternoon, being bitten is a life. This exposed a quiet bug: `make_creature`
armed werebeasts, and an armed werewolf picks from its weapon's attacks and
*never bites*, so the curse could not spread at all. Night creatures are now
built unarmed (`NIGHT_CREATURE` skips the equip block) and fight with what
they are.

Arrival paths, so the layer is reachable rather than theoretical: a migrant
wave hides a vampire at `VAMPIRE_ODDS`; `sim._maybe_night_attack` sends a lone
werebeast on a full moon or a named necromancer with a handful of thralls.
The status line shows FULL MOON, the units list shows TRANSFORMED, and the
character sheet carries an Affliction block that tells you which moon to fear.

## 65. Stealth (v3.6)

### `game/stealth.py`
```python
UNTRAINED = -40.0 ; SKILL_WEIGHT = 6.0 ; CURVE = 12.0   # logistic, 3%..97%
NOISE = {still: -3, move: +2, run: +8, fight: +24, open: +6}
TORCH_PENALTY = 14 ; ASLEEP_HELP = 40 ; DISTANCE_HELP = 0.9 ; COVER_HELP = 5
AMBUSH_MOMENTUM = 2.4 ; AMBUSH_PARTS = (neck, throat, head, upper_body)
def is_sneaking / set_sneaking / natural_sneak / hidden / note_action
def hide_chance(world, sneaker, watcher) -> 0..1
def noticed_by(world, sneaker, watcher) / unnoticed(world, attacker, defender)
def ambush_part(defender, rng) / on_ambush(world, attacker, defender)
```
The game has had a rogue class since the beginning — dagger 4, sneak 5,
dodging 4, observer 3 — and sneaking did nothing at all. `sneak` and
`ambusher` were handed to kobolds, bandits, wolves, four character classes and
the thief that robs your fortress, and no line of code ever read either. The
numbers to build a stealth system with were already in the save file.

**Hidden is a fact about a pair, not a property of a creature.** The guard by
the fire has not seen you; the one on the wall has. `noticed_by(world,
sneaker, watcher)` is the whole interface and everything is built on it:
`ai.hostile_targets` filters through it, so line of sight stops meaning
"noticed"; `dwarf._handle_danger` filters through it, so the kobold thief is
finally as sneaky as its skill says. The roll is made fresh each time rather
than stored, because stepping into the light should be enough for the guard
that missed you a second ago to see you.

**Sneaking is a skill, and `UNTRAINED` is what makes it one.** The first cut
centred the logistic on zero, which handed a character who had never sneaked
in their life a 58% chance of standing next to a bandit unnoticed. With a −40
floor the curve reads: untrained and adjacent 4.5%, a rogue four tiles off in
the dark 50%, the same rogue in daylight 6%, a legendary sneak at eight tiles
in the dark 97% (the cap). Moving costs about ten points of it.

**The torch you need to see is the thing they see.** `light_at` was already on
`Game`; `Fortress` grew the same method so the roll can be asked in either
mode without knowing which one it is in. Carrying something lit costs
`TORCH_PENALTY`, which finally charges for the trade the torch system has
implied since v1.

**An ambush is a different weapon.** `melee_attack` takes an optional *world*;
with it, an attack on somebody who has not noticed you skips block and parry,
takes an `AMBUSH_HIT` floor instead of the aimed-strike penalty, aims for the
neck, and multiplies momentum by 2.4. Measured: 172 hits per 200 against 93,
mean damage 65k against 27k, landing in the neck 162 times out of 172. Then
`on_ambush` drops you out of stealth — one devastating blow, and after it an
ordinary fight against somebody who knows exactly where you are. Without a
*world* nothing is ever an ambush, which is why the two fortress combat loops
stay fair by default.

**The player opts in; NPCs do not have to.** `natural_sneak` hides a creature
whose skills say it moves quietly anyway — but never the player. A character
that hides without being asked is one the status bar is lying about, and it
takes away the decision stealth is actually made of.

`v` toggles it (free — a posture, not an action), running breaks it, the
status line shows SNEAKING and `(lit!)` when your own torch is the problem,
and the look panel tells you whether each hostile has noticed you, which is
the only thing that makes a hidden roll playable rather than a dice cup.

## 66. Books and secrets (v3.7)

### `game/books.py`
```python
SUBJECTS: 12 kinds -> (title pattern, skill it teaches or None)
SECRETS = {"necromancy": "the secret of life and death"}
READ_TURNS = 40/depth ; BOOK_SKILL_CAP = 6 ; DEPTH_VALUE = 1.0..3.2
class Book: kind title subject depth skill author
            event_ids figure_id site_id civ_id artifact_id secret read_by
def of(item) / bind / attach / make_book / make_slab / value_of / summary
def read(world, reader, book) -> lines ; read_turns / can_read / already_read
def discover(where, book) -> newly revealed history
def knows_secret(creature, "necromancy")
```
There has been a scholar class since character creation was written —
knowledge 6, reading 5, writing 4, diagnose 3 — and every one of those skills
did nothing. There has been a `book` item with a BOOK flag and a value of 200
that was pure inventory weight, and towers and towns have generated rooms
called "library" that were four pieces of furniture. Exactly the hole stealth
was in before v3.6.

**A book is about something that actually happened.** `_bind_subject` points
each one at a real civ, figure, monster, battle or artifact and collects the
`HistoricalEvent` ids that cover it; reading it hands you those events. The
world has always kept a history that nothing could read without walking three
hundred miles to it — a book is that way. Kinds with no subject available fall
back to a general treatise rather than to nonsense, which is what
`test_every_kind_of_book_binds_to_the_world` pins.

**The work lives in the item's `flags` dict**, not as an attribute: `Item` has
`__slots__`, and flags already serialise, so a book keeps what is written in it
across a save for free. That did need `Item.to_dict` to serialise flag values
that expose a `to_dict` — without it the first save with a book in the
inventory dies on "Object of type Book is not JSON serializable".

**Re-reading teaches nothing** (`read_by` on the work), which is what makes a
library worth more than one very good book, and a book cannot push a skill
past `BOOK_SKILL_CAP` — you can read about the sword all winter, but at some
point somebody has to swing one at you.

**Secrets are the other half.** A slab carries `secret` instead of a subject,
and reading one appends to `creature.secrets`. `night.is_necromancer` now
checks that list first, which is the entire integration: v3.5's raising
machinery was written to take *any* creature and *any* world, so a player who
reads the slab becomes a necromancer with no special case anywhere.
`actions.raise_dead` (`Z`) is twelve lines calling v3.5 functions, and the
risen come up on the player's faction and attack the player's enemies.

**Getting the books into the world** rides on the people who own them.
Sitegen returns a population, not a floor plan, so `Game._give_books` hands a
book to lords, priests, merchants and scholars, and a *slab* to a necromancer
or a `tomb_lord`. That last profession is new: towers only generate in larger
worlds, and a secret that four worlds in ten cannot reach at all is not a
secret, so tombs mark their first occupant and ruins mark one 40% of the time.
Measured over six pocket worlds: four have a reachable slab, two do not, and
that variance is the intended shape.

Reading is `R` in the inventory (or Enter on a book), costs real turns scaled
by the reading skill, and refuses to start while anything hostile is in sight.

## 68. Art and performance (v3.8)

The audit that found stealth in v3.6 and books in v3.7 -- *which skills does
the data hand out that no line of code reads?* -- had three answers left.
`music` and `dancing` appeared nowhere in the codebase outside the table that
defines them. `poetry` appeared once, as a book subject. There was a `lute` in
the item data with an `INSTRUMENT` flag and a value of 300 that nothing ever
asked about. Every town generates a tavern and v3.4 let the fortress build
one, and the only thing that had ever happened in either was that people stood
near each other.

**A form belongs to a people.** `world/artforms.py` generates musical, poetic
and dance forms per civilization at the end of worldgen -- after history runs,
because a form that is about the war needs the war to have happened. Each has
a name in its own language and a translation, a year, a structure ("three
voices that answer each other", "paired lines where the second reverses the
first"), a purpose, and for music the instrument it calls for by name. About
45% of them are *about* something that actually happened, and the invention
year is pushed forward to the event's if it has to be, because nobody wrote
the song about the battle before the battle.

**`game/performance.py` is the act, and both modes call it.** A fortress
performance and a tavern performance three hundred miles away differ only in
who is in the room. Quality is a band from `halting` to `legendary`, rolled
against the form's own skill plus knowing it, plus the instrument, plus
playing your own people's work to your own people. The bands come off an
explicit threshold table rather than an offset and a divisor: the first cut
did it the other way and quietly handed an untrained dwarf who happened to
know the song a `moving` performance, which is the same mistake v3.6's stealth
made by centring its logistic on zero. The curve now reads: untrained is
`halting` 61% of the time and can never exceed `plain`; skill 7 with the right
instrument is `fine`; `legendary` wants a skill in the high teens.

**Instruments are furniture, not luggage.** A fortress dwarf never carries a
harp around, so `instrument_for` checks what is lying in the room as well as
what is in the performer's hands. Without that second half the measurement was
unambiguous: a fortress performed *identically* with and without a single
instrument in it, so every instrument recipe in the game would have been
decoration. The carpenter now makes lutes, flutes and harps and the
craftsdwarf makes drums, and hauling one into the tavern is worth two quality
bands.

**Everything that moves stress goes through one funnel.** `performance.felt`
clamps a performance's effect into a window: relief stops at -45 and annoyance
stops at +45. Outside it the thought is still recorded and the number stops
moving. This is not a detail -- without it the entire mood system collapses
into the tavern. Measured over three hundred performances, a fortress with one
good musician sat pinned at the -150 stress floor for ever, and a fortress
with only amateurs climbed to +198, which is a tantrum spiral caused entirely
by bad poetry. Two separate paths bypassed the window in the first cut -- the
fortress topping up its own tavern bonus, and the performer's own thought
about how it went -- and each one silently undid it. `mood` is a parameter to
`perform` for exactly that reason, the same way v2.5 made `dig_out` the one
funnel every tile change goes through.

**Forms travel, and carry history with them.** A listener has a chance of
learning the form scaled by how good it was -- nobody learns a song off
somebody butchering it -- and because a form is bound to a real event, hearing
a good one opens that event the same way reading a book does. That is how a
dwarven song ends up sung in a human town, and how you find out what happened
at a battle you were nowhere near.

The world writes down 4% of legendary performances given to four or more
listeners. Without that gate a fortress with a good bard produced two hundred
history events in fifty measured days, which is not a history, it is a diary.

`P` performs in adventure mode; a crowd that liked it throws coins and it is
the only income in the game that does not involve killing something. Standing
in a tavern, other people perform at you. Any townsperson can be asked to.
The legends screen grew an **Art** tab, and there is a **bard** class that
starts with a lute.

**A v3.4 bug this milestone's benchmark found.** Measuring the sim step with a
tavern gave 76 ms against 1.5 ms for the same fortress without one, and the
A/B against v3.7 was flat -- so it predated v3.8 entirely. The cause was the
failure `work_positions` already warns about in its own docstring: `path_to`
will happily route to a cell *adjacent* to the goal, one z-level away
included, while `_to_the_tavern`'s arrival test insisted on the tavern
centre's own z. When the centre stops being walkable -- a cave-in, a flood, a
wall built across the room -- every idle dwarf paths somewhere it does not
believe it has arrived, throws the path away and searches again, and a failing
A* expands the whole reachable map first. 36 of every 37 seconds were inside
it.

`dwarf.tavern_spot` now returns the one cell both halves use: the centre when
it is walkable, otherwise the nearest walkable cell in the room. When there is
none the tavern is genuinely sealed and `_tavern_blocked_until` stops the
whole fortress trying for a while, because one dwarf finding out is enough
information for everybody. 76 ms/step to 1.43. `perform.in_tavern` and
`perform.instruments` read the same spot, so the audience is measured where
dwarves actually stand.

## 69. Tracking (v3.9)

The fourth answer from the same audit. The hunter class has had `tracker` 4
since character creation was written and the fortress hunter labor has had
`tracker` 3 since labors existed, and no line of code ever read either.

`game/tracks.py` is a layer of at most 400 footprints, keyed by cell, holding
only the last thing that crossed each one. Nothing steps it: a track knows
what tick it was made on and answers questions relative to now, so ageing
costs nothing and the cap is what keeps a long game from leaking. Recording
happens in `Game.move_creature` -- the one funnel every move in adventure
mode goes through, for the same reason v2.5 put every tile change through
`dig_out`.

**Finding a trail is not the skill; reading it is.** Anybody can see that
something passed. Direction, species, age, number and condition are five
separate facts the tracker skill hands over one at a time, at levels 1, 4, 7,
10 and 13. A clerk and a hunter looking at the same print disagree about what
it says, not about whether it is there.

Ground decides how long a print lasts -- snow holds one for three days, sand
for half a day, rock takes none at all, which is why a trail stops at the cave
mouth and why `tracker` is an outdoor skill. Blood outlasts a footprint and
does not care what it fell on, so a wounded animal is followable long after
its tracks are not.

Rain washes the trail out, which is the first thing in the game that has ever
cared whether it was raining: weather has been in since v1 as a light and
sight modifier only. It is the reason to set out after the storm rather than
during it.

The player's own prints are recorded but filtered out of `nearby`, because
finding your own footprints and mistaking them for a wolf is a worse
experience than the system is worth. `s` reads the ground and the look panel
reports a trail on any cell, both routed through the same `read`.

## 70. Ethics and standing (v3.10)

`Civilization.ethics` has been generated since civilizations were: six moral
positions per people -- killing, theft, trespassing, slavery, eating the dead,
felling trees -- each `unthinkable`, `shun`, `misguided`, a `personal_matter`,
`acceptable` or `required`. Elves have always thought felling a tree
unthinkable and eating a sapient acceptable; kobolds have always thought theft
*required*. The only thing that ever read any of it was the legends screen,
which printed it.

So the game had renown, which only goes up and is the same number to
everybody, and nothing else. Killing a merchant in the middle of a human town
left the town's opinion of you unchanged, because the town had no opinion.

**Standing is per-people and signed.** One value from -100 to 100 per
civilization in `game/standing.py`. What a deed costs depends on whose ethics
it offends: `ETHIC_WEIGHT` turns `unthinkable` into the full price and
`acceptable` into nothing, so the same murder is ruinous in a dwarven town and
free in a goblin one. `required` is negative on purpose -- a people who think
theft is required think *better* of a thief.

**Being seen is the whole of it.** Witnesses come from v3.6's `noticed_by`, so
a murder nobody saw is a murder nobody minds, and the stealth skill that has
hidden you from a guard's attention since v3.6 now hides what you did from a
nation's memory. Deeds a people find out about anyway -- a finished job, a
beast killed in their name -- are credited by site instead.

Consequences run through machinery that already existed. `enforce` adds the
player to the `hostile_to` set that `Creature.is_hostile_to` already consults,
rather than teaching that method about civilizations: it is called on every
pair in every combat check and has no game to ask. Prices take a factor, and
`price_to_buy`/`price_to_sell` gained an optional `game` because two of their
four callers quote a price with no world to hand. Greetings lead with the
welcome before the ordinary line, because how a town treats you is the first
thing you should learn on walking into it.

**Peoples fall out for reasons now.** `_wars` used to be `rng.sample(civs, 2)`
-- nothing had ever asked *why* two civilizations fought. `ethical_distance`
scores how far apart two moral codes are, and the pair is drawn weighted by
it, so an elf nation and a goblin one have measurably more to fall out about
than two human ones, without making a war between friends impossible.

## 71. Venom and webs (v3.11)

The audit widened from skills to flags. `POISON_BITE` has been on the giant
cave spider, the giant desert scorpion and the alligator since the creature
data was written; `WEBBER` has been on the two spinners; and the tile table has
had a `web` tile with a `WEB` flag for just as long. Not one of the three was
ever read by a line of code. A giant cave spider was a large animal that bit
you, which is not what a giant cave spider is for.

**A syndrome is a clock, not a number.** The combat model is about tissue --
momentum through skin, fat, muscle and bone, leaving a wound that bleeds and
hurts. Venom is the thing that model has no vocabulary for, because it does
nothing at the moment it lands. `game/venom.py` gives each dose an onset, a
duration and a per-tick effect: pain and bleeding feed the existing body
model, `slow` feeds `effective_speed` so a poisoned adventurer is slower in
the only way the scheduler understands, and nausea costs food.

A second dose *extends* the clock rather than adding a second one, bounded at
2.5x the base. Otherwise a nest of spiders is arithmetic rather than a fight
you should have run from. Toughness shortens it, and so does `discipline` --
the first line in the game to read that skill, and the right one, because what
a syndrome mostly does is make you stop.

Treatment is `diagnose` rather than a new skill: there is no antidote in this
world, only somebody who has seen it before and knows to cut and bind. It
halves what is left.

**A web is a tile, not a status.** It sits on the floor, it is visible, it can
be walked around, and it catches whatever walks in -- except spinners, who
walk their own, which is both true of spiders and the only thing stopping one
webbing itself into a corner. Getting out is a strength roll against the
strands, and a failed struggle still tears `MIN_TEAR` away, so nobody is ever
permanently stuck by bad luck: the worst case is several turns of being
somewhere a spider knows about, which is bad enough.

A spinner aims *ahead* of its prey rather than at it. A web laid where
somebody already stands is one they walk out of next turn; a web laid in their
path is a trap.

## 72. Mounts and taming (v3.12)

The last of the four skills the audit started with. `rider` has been in the
skill table since the skill table was written and no line of code ever read
it. `MOUNT` has been on the horse, the donkey, the mule and the camel since
the creature data was written, `TRAINABLE` on ten creatures besides, and a
horse was a thing you could kill.

**A ridden mount comes off the map.** While you are on it, it is held on
`player.mount` rather than standing in `game.creatures` -- the same shape as
`travelling_companions` holding a follower between world tiles. The
alternative, two creatures on two cells that must move as one, is a whole
class of bugs about which of them is where, who gets attacked, what happens
in a one-tile corridor and what the scheduler thinks it is doing. It costs
one thing: the mount cannot be attacked out from under you. Being unseated by
a solid hit is what replaces that, and it is the better mechanic.

**Riding is a skill and falling off is how you learn it.** Every hit above
`UNSEAT_THRESHOLD` momentum is a `rider` roll, made at the point in
`melee_attack` that already knows how hard the blow landed, because nothing
else does. Untrained you stay on 30% of the time, at skill 10 it is 85%, and
a legendary rider is at the 97% ceiling. Failing puts you on the ground,
winded, beside something still swinging.

Taming is the same skill and takes real time whether or not it works. A
refusal is one attempt that did not work rather than a verdict, but each one
makes the animal warier, which is what stops it being a button held down until
the horse is yours. A wild animal minds considerably more than one that grew
up around people.

What a mount is actually for is the numbers: 85% of the animal's speed rather
than your own (93 to 155 for a human on a horse), 1.6x carrying capacity, and
overland tiles that cost 62% of the time they did on foot.

## 73. The wild (v3.13)

Three creature flags had never been read. `BENIGN` is on the cow, pig, sheep,
chicken, duck, deer and rabbit; `AMBUSHER` on the kobold, fox, tiger, leopard,
alligator, snake, giant cave spider and gremlin; `VERMIN` on the rat, the bat
and the cave spider. The wilderness was a set of creatures that either
attacked you or stood still.

**`BENIGN` means it runs**, and not because it is hurt -- `opportunity_to_flee`
already covers that, and it is a different question. It runs because a person
came near. That is what makes hunting an activity: v3.9 put tracks in the
ground and v3.6 put stealth in so you could close the distance, and neither
had a point while dinner waited politely for you to arrive. How near is near
comes out of `noticed_by`, so sneaking well is what gets you inside a deer's
flight distance. Flight lasts fourteen turns, because an animal that flees one
step and stops just gets shot standing still.

**`AMBUSHER` means it does not charge.** It holds while you are far off and
springs inside `STRIKE_RANGE`. Measured at seven tiles: against an untrained
observer a tiger lurks 15 turns in 20, and against a trained one it lurks 2
and comes on 18. The observer skill is what decides whether you are stalked or
merely attacked.

Two defects turned up building it. The flag put a creature into
`natural_sneak`'s hiding game and then the roll noticed it every single time,
because a tiger has no `sneak` skill at all -- so `lurk` was dead code. The
flag is now worth `AMBUSHER_HELP` in the roll directly, which is the honest
statement that an ambush predator is not a trained sneak but an animal built
to be invisible in its own cover. And `waiting` set its give-up counter
straight to the ceiling on a single noticed roll, which permanently ended
lurking for that animal after one unlucky turn -- `noticed_by` is rolled fresh
every time by design, so one True is not a verdict.

**`VERMIN` means it wants your food.** It flees anything bigger than itself
and takes edible items off the ground on its way past.

A latent trap fixed in passing: `is_hostile_to` let the `wild_hostile` faction
fall through to `False`, so the one faction with "hostile" in its name was the
one that never attacked anybody. Nothing spawns with it today, which is why it
was a trap and not a bug.

## 74. Traps and treacherous ground (v3.14)

The tile table has had a `trap` tile with a `TRAP` flag since it existed, and
an `ice` tile with an `ICE` flag that glacier biomes have been laying down all
along. The fortress reads neither -- its traps are buildings with their own
machinery -- and adventure mode read neither either, so a tomb sealed four
hundred years ago to keep people out was a room with a skeleton in it, and a
glacier was a white floor.

**A trap you can see is a puzzle; a trap you cannot is a tax.** Every trap
starts hidden and every one can be found before it goes off: by searching,
which v3.9 already made the verb for reading the ground, or by walking past
with a good enough Observer. Once found it is drawn as a red `^`, named, and
can be disarmed with `mechanics` or simply walked around. What a trap must
never be is an unavoidable die roll on entering a room.

The first spotting curve divided by 20 on a 0.45 base, which made each
Observer rank worth a fifth of the whole range: an untrained searcher found a
pit 1% of the time and a level-5 one found it 95%. A cliff, not a skill --
the same mistake v3.6's stealth and v3.8's performance each made once. It now
runs 14% to 95% across twenty ranks, with hidden traps a full tier harder than
obvious ones.

**They spring what the game already has.** A dart carries v3.11's venom, a
snare lays v3.11's web, a pit drops you a level, and an alarm wakes everything
within forty tiles -- the one that turns a tomb from a fight into a running
fight. Damage goes through `combat.trap_strike`, which the fortress has used
since traps were buildings and which already handles armour, body parts and
the wound model. A second damage path for the same idea is how two systems
quietly stop agreeing about what a spike does.

Venom is gated on the strike getting through. A dart that failed to penetrate
armour has not envenomed anybody, and armour mattering for the wound but not
the venom is armour mattering for half the trap.

**Ice is the other half.** `ICE` ground is a roll against agility and
`climbing` every time it is crossed, and failing costs the turn and leaves you
stunned for one. The danger of ice is not that it hurts; it is that you are on
the floor for a moment while something else is not.

Traps are seeded when a local map is generated rather than at worldgen,
because a trap belongs to a floor plan and floor plans are made on arrival:
tombs get three to six, ruins one to three, lairs nought to two.

## 75. Personality that does something (v3.15)

Thirty personality facets and twenty cultural values have been rolled for
every creature in the game since personalities existed, written into every
save, and printed on the character sheet. Three of them were ever read by
anything: `bravery`, `anger` and `love_propensity`. The module docstring has
claimed since it was written that facets "drive whether a creature stands and
fights, runs, bargains or picks a quarrel" and that values "shape what a
creature thinks of what it sees". Neither was true.

**One funnel, fifty-six call sites.** There are fifty-six places in the game
that make somebody feel something and every one of them goes through
`Needs.add_thought`. Rather than teach fifty-six callers about personalities,
`Needs` gained an `owner` back-reference and `add_thought` scales what it is
handed by `personality.sensitivity`. An anxious dwarf swayed by its emotions
and a confident, tolerant one now take the same funeral differently: measured
over two hundred dwarves, the same 20-point event lands between 16 and 25.
Stress drift reads `resilience` the same way, so somebody may take a thing
badly and get over it quickly, or shrug it off and never quite let it go.

**Values decide whether you care at all.** `Creature.value_thought` adds a
thought weighted by how strongly that creature holds the value, and returns
zero for the indifferent -- which is the point, because half a fortress should
walk past the new statue. Wired to engravings and performances (`artwork`),
convictions and pardons (`law`, `fairness`), weddings and births (`romance`,
`family`). Races hold their own: dwarves are measurably keen on
`craftsmanship` because worldgen has always said so.

`work_rate` reads `diligence` -- perseverance, discipline and restlessness,
worth about a fifth either way, which is nothing in a day and a great deal
over a season. A brawl now reads `vengefulness` and `hate_propensity`: a
forgiving dwarf lets a punch go and a vengeful one takes it out of v3.4's
bond and remembers.

The swings are deliberately narrow. A dwarf is not four times another dwarf
because it is keen, and a personality system that decides everything is as
wrong as one that decides nothing.

One defect the save test caught: `Creature.from_dict` replaces the `Needs` the
constructor made, and with it the back-reference the whole thing reads
through. Without one line restoring it, a *loaded* game silently ignored every
personality in it while a fresh one worked perfectly.

## 76. Kin and rivals (v3.16)

`HistoricalFigure.relationships` is a `Dict[int, str]` that has been declared,
serialised and reloaded since figures existed, and never once written to or
read from. `"marriage"` has been in `EVENT_KINDS` just as long and was never
recorded either. So the world had heroes, rulers, slain beasts and four
hundred remembered names, and not one of them was anybody's anything.

**`relate(a, b, kind)` writes both halves.** A relationship recorded one way
only is a relationship half the code will fail to find, so `OPPOSITE` pairs
every kind with its mirror and the test suite checks reciprocity across every
figure in a generated world.

Worldgen now fills it: people marry, have children, and the children take
their parent's family name -- a child of Varen Kettleby called Adelin Fenwick
is two strangers and a family the legends screen cannot draw. Heroes and the
beasts that killed them become `slayer`/`slain_by`. Leaders of peoples at war
become `enemy`.

The first cut was unbounded and one prolific couple accumulated fifteen
children and eight siblings apiece, with births making up four hundred of the
world's four hundred and sixty-seven figures. A history where most of the
names are somebody's youngest child is not a history: `MAX_CHILDREN` caps a
couple at four and the odds came down to match.

**The payoff is that kin remember.** `standing._kin_remember` is the first
thing in play to read the graph: kill somebody with a family and anybody on
that map who was blood or marriage to them turns on you outright, and their
people think less of you for every relative you have left behind. Killing a
nobody and killing somebody's father were the same act until the world's
figures had relationships, and now they are not.

The legends screen lists a figure's relations by name, marking the dead.

## 77. Fire (v3.17)

`FLAMMABLE` is on the tree, the sapling and the shrub in the tile table; on
oak, willow, pine, cedar, birch, coal and charcoal in the material table; and
on the torch and the log in the item table. Magma has been flowing in
fortresses since v2.5 and adventurers have carried burning torches since v1.
Nothing in the game had ever caught alight.

**`world/fire.py` is v2.5's fluid layer with the water taken out.** A dict of
burning cells, an active set so a map that is not on fire costs nothing to
step, and a hard cap on how much may burn at once -- `MAX_BURNING`, which is
`MAX_ACTIVE` under another name and for the same reason. Measured: a dense
forest burns 732 cells over 153 steps at 0.221 ms a step, peaking at 518 alight
at once, and an unlit map steps in 0.0003 ms.

What burns is what the data says burns. The tile decides most of it -- a tree
is thirty steps of fire and a shrub is six -- and flammable items on the cell
add to it, which is why a woodpile next to the forge is a decision. Spent
cells become **ash**, a tile added for this and which v3.9's track layer had
already been listing as soft ground it could hold a footprint in.

Both modes step the same layer. The fortress does it beside `_flow`, because
the fluid layer and the fire layer are the same shape of problem, and magma
lights flammable neighbours at low odds -- a fortress that ignites the moment
it strikes the magma sea is one nobody digs deep in twice. Adventure mode
lights fires with the torch it has been carrying since v1.

Damage goes through `combat.trap_strike`, the same path v3.14's traps use, so
there is one table of things that hit you and cannot be parried rather than
three sets of numbers drifting apart.

**Fire is light**, and both modes' `light_at` max it in, which means v3.6's
stealth charges for standing next to a burning tree without knowing that fire
exists.

## 78. Temperature (v3.18)

Every world tile has carried a `temperature` since worldgen was written. The
embark screen called it *freezing* or *scorching*, the travel screen printed
it, and the weather asked it one question -- whether falling water should be
snow. Beyond that a glacier and a desert were the same place to stand in.

Meanwhile every material in the table carried a `melting_point` that nothing
had ever read, and the reason it is worth reading is the scale it is written
on. It is Dwarf Fortress's -- degrees above absolute zero in Urists, where ice
melts at 10000. Subtract `URIST_OFFSET` and you are in the degrees the world
map is already using. **The bridge between the material table and the climate
was sitting in both of them the whole time**, which is why `heat.FREEZING` is
not a constant anybody chose: it is ice's melting point, converted.

**Temperature is three questions.** What the air is doing (`ambient`: the
world tile, its biome, the season, the hour, the weather, and how far
underground you are). What is nearby (`source_heat`: v3.17's fire and v2.5's
magma, because a fire that does not warm you is a light bulb). And what you
are wearing (`insulation`) -- the first thing in this game that has ever cared,
after nine versions of shirts and cloaks and mittens being traded, stockpiled,
tailored and worn for no reason at all. Coverage comes out of the body table's
`rel_size`, which combat has always used to decide where a blow lands and
nothing had used to decide how much of somebody a cloak actually covers.

A biome's `temperature_bias` is taken at a quarter. Worldgen picked the biome
*from* the tile's temperature, so believing the whole bias is the same climate
counted twice -- it puts a glacier at ninety below, where nothing you can wear
matters.

**Cold takes your fingers; heat takes your water.** Cold ends in frostbite,
through `combat.trap_strike` with the `prefer` hint the body model has always
had, so there is still one table of things you cannot parry. Heat ends in
thirst, which has been able to kill since v1 and needed nothing new. Exposure
is a number that moves rather than a threshold that trips, because the
interesting decision is when to turn back and a threshold gives no warning to
act on. Coming in out of the cold is faster than going into it: shelter is
meant to be worth reaching.

**Frost** freezes water and thaws it back, remembering the tile it covered and
the depth it swallowed so a thaw undoes it exactly. It works on v2.5's fluid
layer in the fortress and on terrain in adventure mode, and it puts `ice`
tiles where a player walks -- which v3.14 has been ready to make you slip on
since it shipped. It is sampled on a cadence, which is v3.17's lesson applied
before the mistake instead of after: the cost is never the work, it is doing
the work every step.

**One bug, found by adding the sixth of something.** Fires, frost, traps and
webs belong to a *map*, not to the game. Each was added in its own version and
each was wired by hand into the branch of `enter_world_tile` that generates a
fresh map -- and every one was missed on the branch that loads a cached one.
Walking out of a burning forest onto a map you had already visited took the
fire with you, still alight, at the same coordinates, over water or inside a
wall. Four layers made the same mistake four times. They go through
`_store_layers`/`_restore_layers` now, and the map cache carries them.

## 79. The weight of a blow (v3.19)

`prepare` and `recover` -- the wind-up and the follow-through -- have been on
every attack in the item table and every natural attack in the creature table
since both were written, and nothing had ever read either of them. A dagger
flick and a maul swing each cost one action, so the only question a weapon
ever asked was how hard it hit. The energy scheduler to express the answer has
been there since v1.

`combat.attack_cost` prices one strike against `ACTION_COST`, out of three
things: the attack's own `prepare + recover`; how heavy the weapon is for
*this* creature, measured against `carry_capacity`, which already knows size
and strength; and skill, which shaves up to a third off. `AttackResult.cost`
carries it out, and every melee path spends it -- bump-attack included, which
is the one the player actually uses and the one a "second path" would have
quietly left at a flat cost.

**What the table actually says**, read rather than assumed: thrusting is quick
(4), blades and spears are ordinary (5-6), and everything that chops or bashes
is slow (8). A dagger and a sword have *identical* swing times; what separates
them is weight, and weight only bites a creature not big enough for the
weapon. So a dwarf swings a sword and a dagger at the same rate, a kobold does
not, and a maul is 0.58 blows a turn for a dwarf against 0.75 for a stronger
human. `speed_word` has three words because the data has three clusters;
finer words would be inventing resolution.

Both ends of the band are reached, by the right things: a bare fist sits on
the floor because a bare fist is the fastest attack there is, and a kobold
that has picked up a maul sits on the ceiling. What stops speed from beating
weight is not the floor -- it is armour. Measured over four hundred duels
against an armoured human, a dagger swinging half again as often kills 3 times
in 400 where a great axe kills 342: momentum has to clear the tissue's yield
before it does anything at all.

**The fortress has no energy scheduler** -- it steps every creature once per
tick whatever it is holding -- so `combat.timed_strike` banks a standard
action each step and swings only when it has saved enough, carrying the
change. A hammerer really does land fewer blows than a swordsman over a siege,
without the fortress needing a second time model. A tantrum still goes through
`melee_attack` directly: it is one outburst, not an exchange.

`ArmorDef.permit_size` is also unread, and was left that way. It is `0` for
every piece in the table, so making it real means authoring a column rather
than reading one -- a different kind of change from this.

## 80. Wear (v3.20)

`Item.wear_tick` has been on the item class since there were items: a per-call
chance, a lower one for metal, an exemption for artifacts, and a `True` return
meaning the thing has finally come apart. It was called from exactly one place
-- a weapon that lands a blow -- and **its return value was thrown away**.

Because nothing was ever destroyed by use, `wear` had no ceiling. It is
clamped to 0..3 in the constructor and was incremented without one, so a
weapon that landed enough blows walked off the end of the scale: `wear_factor`
is `1 - 0.15 * wear`, which hits zero at 6 and goes **negative** at 7, and
`compute_momentum` multiplies by it. A well-used sword quietly became worse
than a bare fist, and the examine screen could not say so because the
condition names stop at "XX". `wear_tick` clamps at `MAX_WEAR` now and keeps
returning `True` once there.

**Wear is what use costs**: a weapon wears from landing a blow, armour from
stopping one, clothing from being worn. The odds live on the item; `wear.py`
decides how often to ask. Measured at 26 wear points over 6,748 landed blows
against a predicted 27 -- a sword outlasts a war, and a shirt does not outlast
a year. Everything that removes a worn-out item goes through `wear.destroy`,
because an item gone from the hands but still in the pack -- or still on the
body, or still counted by a stockpile -- is the shape of bug this project
keeps finding, and four call sites is how it keeps happening.

**The loop this exists for.** v3.18 dressed every dwarf and made rags a way to
freeze; v3.20 wears those clothes out. So the fortress needed to be able to
make more, and could not: it had recipes for cloth and none for clothing. It
has them now, at the craftsdwarf's, and a dwarf missing a garment posts the
same `equip` job a soldier uses to fetch its uniform -- a second way to pick
something up and put it on is a second way for it to go wrong. A fortress with
no clothier ends up with cold dwarves in rags, which is the mechanic and not
an accident.

Two more dead tools were wired while they were in reach. The `sharpen_weapon`
recipe took a whetstone and handed back a whetstone, because there was never
anything blunt; a whetstone now takes an edge back a step, on things that have
an edge, which a maul does not. And `flint_and_steel` -- tradeable and
lootable since the item table was written, never once asked for -- now lights
what v3.17 needed a burning torch for.

## 81. The skills you were sold (v3.21)

The skill table has sixty-seven entries. Auditing which of them any code
outside the table itself reads turned up a cluster that character creation
*hands out* and nothing had ever asked for.

**`striker`, `kicker` and `biter`.** The wrestler profession -- "No weapon. No
armour. No mercy." -- starts with `striker` 4 and `kicker` 3. Nine species
carry an authored `biter`; a dragon has 12 of it. Every unarmed attack asked
for `wrestling`, which a dragon does not have and which a wrestler was given
for grappling. `skill_for_attack` reads the *attack* when there is no weapon:
bites and stings are done with the mouth, kicks with the feet, and everything
else a body does to somebody is striking. `_skill_for_weapon` stays for the
places that ask about a creature's weapon rather than about a blow -- parrying,
and pricing a swing before one has been chosen.

That change would have silently gutted eight species. Gorilla, troll, ogre,
cyclops, bronze colossus, night troll, zombie and demon were authored with
`wrestling` *because that is what the game read*, and punch/kick/bite would
suddenly have found nothing. They were given the specialisations their data
meant -- a bronze colossus is a legendary striker -- and kept `wrestling`,
which still governs grappling. **An audit that reads data differently has to
check who was writing for the old reading.**

**`lying`**, which the thief starts with 3 of and the bard 2. Bragging with
nothing to show used to print "You speak of your 0 notable kills" and take the
same reaction as a hero. It is now a lie, and `lie_chance` weighs the liar's
skill against the listener's `observer` and their `trust` facet: a thief is
believed by about two listeners in five and by one in ten who is paying
attention. Getting caught costs standing through v3.10 and a thought through
v3.15. The guard on the old branch was `not skills.known()` -- true only of
somebody who had never learned anything at all -- so it could not be reached;
it is a notable *reputation* (`NOTABLE_SKILL`, "Talented") or real kills that
count as something to boast about.

**`writing`**, which the scholar starts with 4 of. Every book in the world
arrived already written and nobody could add one, though `bind` had done the
work since v3.7. A writer can only write what they know -- `KNOWS_ENOUGH` in
the subject, or history and biography, which are open to anybody literate --
and depth comes from the craft and the knowledge together, so a brilliant
surgeon who cannot write produces a pamphlet. It takes hundreds of turns and
cannot be done with hostiles in sight. There was nothing blank to write in, so
the crafting table binds one.

Left dead and deliberately: `misc_weapon` and `ArmorDef.permit_size`, which no
row in either table populates, and `surgery`, which exists as a book topic but
would need an operation to perform rather than a wiring.

## 82. Nerve (v3.22)

`combat.opportunity_to_flee` has decided whether a creature breaks off since
there was combat, out of health, `bravery` and `NO_FEAR` -- and it asks about
one creature alone in the world. Meanwhile `ai.allies_near` sat in the AI
module the whole time, complete and correct and **called by nothing**, and
`PACK` was read once at spawn to decide how many wolves to put on the map and
never looked at again. Seven wolves arrived together and then fought as seven
separate animals, not one of which noticed when the other six were dead.

`morale.nerve` is what the company is worth. Numbers steady a creature, up to
a handful; being the last one standing does not; and something built to hunt
in a pack takes being alone much harder than something that never had one.
Watching an ally go down is a shock that wears off, so a hard fight grinds a
side down rather than flipping it -- the third death breaks a line, not the
first. `opportunity_to_flee` keeps its name, because that is what the AI has
always called, and hands the question to `morale` when it is given a world.

**The two modes had opposite halves of this.** Adventure mode had individual
fear and no idea of a group. The fortress had `war`, which routs a whole army
on its losses and gives the individuals in it no say at all: an invader fought
to the death whatever was happening around it. Both ask `broke` now, and a
broken invader leaves the way a routed army leaves -- through
`war.retreat_step` -- rather than by a second set of rules.

Measured against v3.21 across six sieges: four ran bit-identically (goblins
carry `NO_FEAR`, so nothing changed for them), and both that differed
improved. One ended in 47 steps instead of 395 with the fortress losing nobody
instead of four dwarves, because the kobolds broke and ran early rather than
dying in the corridor.

**Two things I built and then took out again.** A bound on how long a broken
invader may spend retreating, and a rule sending invaders home when no dwarves
are left -- both aimed at a kobold that seemed to squat on the map for five
thousand steps. It was not squatting: `sim.step` returns immediately once
`fort.lost` is set, so a fortress with no dwarves is not simulated at all and
the scenario cannot happen in play. Unreachable code written to fix an
unreachable bug is the thing this project keeps finding in itself; the test
for it went out with it.

## 83. The food chain (v3.23)

Two halves of one hole. `CreatureDef.diet` classifies all eighty species as
carnivore, herbivore or omnivore and **nothing had ever read it** -- everything
wild shares the faction `"wild"`, `is_hostile_to` returns `False` for the same
faction, so a wolf and a deer were on the same side. And every creature without
`NO_EAT` has accrued hunger and thirst since needs existed, with no way to
answer either: **46 animals on a fresh map, all alive on day three, 43 of them
dead of thirst on day four.** The three survivors were the undead and the
megabeasts, who are exempt. The wilderness was a peaceable kingdom in which
nothing ate anything and everything quietly died of thirst.

`feeding` reads the diet and answers the clock. Animals graze what they are
standing on, scavenge carrion, and hunt -- and `is_prey` is not a straight
size comparison, because a wolf is 40 litres and a deer is 100. A hunter takes
up to `PREY_RATIO` of its own size, and `PACK_REACH` extends that per packmate.
That constant was sized against the bestiary rather than guessed: at first it
was decoration, because nothing in the table sat between a lone wolf's reach
and a pack of four's. Three wolves bring down an elk now, which is what a pack
is for.

**Two things the fix had to admit.** A local map draws no water at all unless
the world tile is a river or a lake -- a temperate forest generates 1,647
cells of grass and zero of water -- so an animal that could only drink from
terrain could not drink in most of the world. Grass and meat are mostly water,
which is where a great many real animals get most of theirs, and that is the
honest model at a resolution with no puddles in it. And `Needs` was written
for somebody with a waterskin: `WILD_NEED_SCALE` runs an animal's clock
slower, not as a fudge but because it is foraging continuously in ways the map
has no cells for. What the clock is still for is the interesting part -- when
to hunt, when to graze, and when to do either with something watching.

**The mistake this made, and the rule that fixed it.** `pick_mode` asks
`wild.frightener` before anything else, so the moment prey started running
from predators, a rabbit within sight of a fox fled until it died of thirst
standing on grass. Hunger and thirst outrank fear past `DESPERATE_THIRST`,
which is what a real animal does and the only thing that lets prey and
predator share a map. Measured after: 42 of 42 alive on day four, and by day
fourteen the commonest cause of death is being eaten.

One crash went in and out with it: the new prey branch wrote to `creature.ai`,
which `pick_mode` may be asked about before `take_turn` has built one. It was
the first branch there ever to write to that state.

## 84. Living off the land (v3.24)

Two whole chains, each missing one link.

**Fishing.** The `fishing` skill is in the skill table. The `fishing` labor is
in the fortress labor list and the hunter profession carries it. `fishing_rod`
is in the item table. `fish_food` is in the item table, in the fortress larder,
in the stockpile categories and on the sidebar's food list. `cook_fish` is in
the crafting table. Carp and pike swim in the bestiary on a `fish` body plan
written for them. **Nobody, in either mode, had ever caught a fish.** Both can
now: an adventurer with a rod beside open water, and a fortress that posts
`fish` work when the larder is short of it.

**Gathering.** The fortress has had herbalism wired end to end since it had
farms -- a dwarf gathers plants, sows them, harvests them and gets better at
it. An adventurer standing on the same shrub could do nothing at all. v3.23
gave the wilderness animals that eat; this is the half where you can too.

Both are slow on purpose. An afternoon at the water is an afternoon not
walking, which is what makes a survival mechanic a decision. And both are
capped where they need to be: `FISH_STOCK` stops a fortress fishing once the
larder is full, and `MAX_ANGLERS` stops it putting everybody on the bank.

**A bug in my own return value.** `gather` and `fish` first returned the
`Item` they had made -- and `Inventory.add` merges a stack into one already
carried, leaving the passed item holding nothing. A yield of seven berries
read back as zero, and the message built from it said "a plump helmet" when
seven had been picked. They return `(id, count)` pairs now and name the catch
before it goes in the pack. The test that caught it was comparing a skilled
herbalist against an unskilled one and getting zero from the better of them.

## 85. What a fight leaves behind (v3.25)

**Severed limbs did not exist.** `combat.severed_items` builds them, checking
the body model's `severed` flag and the wound's age so the same arm is not
dropped twice, and `item.severed_part` names them -- "a goblin left lower leg",
with the species recorded on the item. Both were complete. **Neither had ever
been called.** You could take a goblin's arm off with an axe and the arm was
nowhere. They drop now, in both modes: `melee_attack` gained a `ground`
parameter separate from `world`, because `world` is what turns on v3.6's
ambush rules and the fortress deliberately passes none -- it wants the limbs
without the stealth. Measured: 200 axe duels against goblins leave 386 pieces
on the floor.

**Blood did not fall on stone.** `tracks.leave` returned early unless the
ground took a print, so a bleeding creature crossing rock recorded nothing --
while `BLOOD_FADE`'s own comment said "blood outlasts a footprint and does not
care what it fell on", the fade logic already gave it its own longer life, and
the help screen promised the player a trail that "does not care what it fell
on". Three places describing behaviour the one function that mattered did not
have. A wounded thing running into a cave is exactly when a trail is worth
following and exactly where there was none.

Blood marks any ground now. A mark on bare rock carries `printed = False`, and
`read` reports it as blood and nothing else: no heading, no species from the
depth of a print that is not there. Inventing the missing half would be worse
than the bug.

## 86. Gravity (v3.26)

`LocalMap.has_floor` has answered "is anything holding this creature up" since
there were z-levels, and it was asked in **one place**: the player's own step,
which quietly slid you down to the first solid thing and did nothing else about
it. You could walk off a ten-level cliff and land unhurt. Nothing else in the
game fell at all -- not other creatures, not items, and not a dwarf standing on
a floor that had just been channelled away. The `chasm` tile has been in the
table since the table was written, flagged `OPEN` and `CHASM`, and no generator
ever placed one, because a hole in the floor could not do anything.

`gravity.settle` is called from each mode's one funnel -- `Game.move_creature`
in adventure, and the fortress's own step plus `Fortress.settle_above` wherever
the ground is taken away -- so there is no second way to be standing in mid-air.
Items settle too.

**A fall needed its own row in the trap table, not the `pit` trap's.** Reusing
`pit` looked like the right reuse and was measurably wrong: a breastplate ate a
six-storey drop entirely, because a trap's numbers are a trap's. A fall is the
whole body arriving at once -- an enormous contact area and almost no
penetration -- and it needed roughly ten times the momentum. Calibrated against
an unarmoured human: two levels bruises, five breaks something six times in
ten, and ten levels breaks something *every* time and kills three in ten. Iron
plate roughly halves all of it, which is the right shape: armour helps and does
not save you.

**Ordinary channelling is still safe**, and that is not an oversight. It cuts a
ramp into the level below, so a dwarf steps down onto it. What is dangerous is
cutting into a void that is already there, which is the case worth having and
the case the test covers.

Worth recording while it was found: `Body.apply_damage` takes `contact` and
never reads it, and `penetration` only gates whether an organ can be hit. The
comment above it describes force "delivered to the contact area". Both were
left alone -- rebalancing every weapon in the game around a newly live
parameter is a milestone of its own, not a footnote to this one.

## 87. Contact area (v3.27)

Every attack in the game has carried a contact area since the weapon table was
written -- a dagger's point is 5, a mace's head 20, a great axe's edge 90000 --
and the number reached exactly one place: `Body.apply_damage`, which passed it
recursively to `_maybe_hit_organ`, which did not read it either. A thrust and a
chop with the same weapon behaved identically. `contact` was the last dead
parameter at the heart of the combat model, and v3.26's own commit message said
so.

`game/contact.py` is one function and three readers. `spread(contact)` is how
widely a blow spends its force, `(contact / 40) ** 0.13` clamped to 0.75..2.60.
Armour absorption multiplies by it, tissue damage per layer multiplies by it,
and organ reach divides by it.

**The reference is a kick, not a sword.** The bestiary was balanced when
nothing read contact, so putting the neutral point in the middle of the
*natural* attacks -- kick 40, gore 40, claw 30, bite 20 -- leaves every beast
in the game fighting as it always did and makes the weapon table carry the
whole deviation. That is the difference between a rebalance and a bug report.

**Armour spreads a blow, which is what armour is for.** A great axe hands a
mail shirt the length of its edge and the mail takes 3.4x what it takes from a
spear point. Measured through an iron mail shirt, against v3.26: a pick's
thrust +10%, a dagger's +33%, a war hammer and a morningstar from stopped to
through -- and a sword's cut, an axe's hack and a short sword's cut from
through to stopped. A great axe still cuts mail; nothing smaller does. That is
the weapon triangle, and it was in the data the whole time.

**The tissue trade is real and it cost two attempts to get right.** A torso is
skin, fat, muscle, bone. At the force that puts a point into the muscle, an
edge is still in the fat; at the force that puts a point on the bone, the edge
has taken the skin and the fat off entirely and stopped in the muscle. Blows
to take a bare forearm off, v3.26 -> v3.27: axe 19.2 -> 10.8, two-handed sword
11.3 -> 6.9, great axe 9.5 -> 6.3. Through mail, a two-hander's chance of
taking that arm off goes 60.8% -> 13.3%.

**`bite()` is capped at 1.0 and `spread()` is not.** The first version charged
an edge for its width twice -- once in the layer it was cutting and again in
the force it had left -- and measurably wrecked the heavy edged weapons: a
great axe's organ hits went 25.6% -> 0% and a sword's cut lost half its depth,
because `hurt` was already saturated at the top of the range so the widening
bought nothing while the cost was charged in full. The width an edge buys comes
out of the layer above, not the depth below. A point's cost falls off faster
than its width (`PIERCE_POWER = 2`), which is what lets a thin blade arrive at
the far side of the ribs still carrying something.

**A weapon with two attacks is two weapons, so somebody has to choose.**
`choose_attack` rolled a flat die between a sword's edge and its point, which
threw the whole triangle away as variance. It now weights the roll by what each
attack would actually deliver to the defender's chest, sharpened by the
attacker's `fighter` level. Against leather, where both attacks work, the
preference is a gradient -- 50/50 untrained, 62/38 at `fighter` 15. Against
mail it is absolute from `fighter` 2 upwards, because there the cut delivers
literally nothing and a weight of zero is never drawn; skill only decides
whether he notices. A farmhand still swings whatever is in his hand. Natural
attacks are judged the same way, which is worth something now that v3.21 gave
nine species real `biter` and `striker` levels.

**Judging by the chest, not by the least armoured part.** Scoring against a bare
thigh as well was tried and is worse: a blow lands where it lands, and a fighter
who reasons about a target he cannot aim at is not reasoning. When nothing at
all reaches the chest the choice falls back to a coin toss, which is honest --
there is no judgement to make against a man in full plate.

**Two short-circuits, both bought by measurement.** Judging cost 0.024 ms on a
0.078 ms strike -- a third of every blow struck in the game. Walking forty body
parts to find the chest is now memoised per body plan rather than per swing,
and a defender with no armour on the judged part and no natural armour skips
the scoring entirely, because with nothing to spread the blow every attack
lands with the momentum it was swung with and the ranking collapses to which
one is quickest. Judging is down to 0.017 ms against an armoured target and
0.003 ms against a bare one. A siege step measured 2.19 ms against v3.26's
2.15 ms, and the same fourteen embarks held 13 times against 12 with the mean
survivors identical at 3.1 -- the model is more lethal per blow and the
fortress is exactly as safe.

**Found and deliberately not fixed: a steel breastplate stops every melee
weapon in the game.** Absorption is roughly 3.5x the heaviest blow the weapon
table can throw, so plate is not hard to beat, it is impossible, and it was
impossible before this change too. The help screen used to promise the opposite
in as many words and now says what is true. Recalibrating what armour is worth
is a milestone of its own; doing it inside this one would have confounded every
measurement above.

## 87.1. What the contact numbers already said

Three comments in `TRAP_STRIKES` were written to explain contact areas back
when nothing read them -- fire at 2 ("armour helps a great deal less against
burning, which is what the low contact area buys"), frostbite at 4, and a fall
at 2000 ("an enormous contact area, so armour spreads it rather than stopping
it"). All three are true statements about the running game now, and none of
them needed a line changed.

## 88. What armour is worth (v3.28)

Armour decided what it absorbed by comparing the blow to its own material:
shear yield against an edge, impact yield against a hammer. Half of that is
right. Steel's impact yield is three and a half times its shear yield, so every
piece of armour in the game was three and a half times *better* against a mace
than against an axe -- a steel breastplate absorbed 322,000 from a war hammer
carrying 51,000. The hammerman's entire pitch at character creation, "armour
does not help against a hammer", was exactly inverted, and had been since both
were written.

**The two blows are not the same question.** Stopping a cut is a question about
the armour: either the edge shears the plate or nothing at all gets through.
That part was right, and a breastplate no weapon in the game can cut is a
feature. Stopping an impact is a question about where the momentum goes -- the
plate is not cut, it is driven into the man inside it -- and a share of it
always arrives. So `game/armour.py` caps blunt absorption at a share of what
was swung and transmits the rest.

**The cap is a ceiling, not a floor.** A wool tunic's own absorption is 400,
which is nowhere near the cap, so the `min` never fires and a hammer goes
through a shirt exactly as it always did. The cap only ever binds on metal,
which is the only place the defect was.

**Rigidity is geometry, not metallurgy.** Without it the cap binds equally on
mail and plate and a breastplate is worth exactly a mail shirt against a mace,
which is not what a breastplate is. What decides how well a shell spreads an
impact is thickness and `armor_level`, not whether the metal is hard to cut, so
that is what the term is built from and the material yield is deliberately
absent from it.

Blows to put a man down, v3.27 -> v3.28. Against mail: mace 26.0 -> 8.8,
war hammer 25.9 -> 8.4, flail 16.6 -> 7.6. Against full plate: mace
15.3 -> 8.5, war hammer 15.3 -> 8.7, maul 11.0 -> 6.2, morningstar
14.9 -> 7.5. **Every pure edge is unchanged to the decimal** -- sword 18.4,
dagger 28.9, great axe 9.0, two-handed sword 10.7 -- because the cap is on
blunt only and v3.27's calibration had to come through untouched. Against plate
the five best weapons in the game are now all blunt; they were the five worst.

**`armor_use` had been levelling up for nothing.** In the skill table with a
blank description, granted to four professions, three species and the fortress
soldier labor, counted in the squad list's danger score, and awarded experience
every single time a blow was turned -- and read by no code anywhere. It now
does the two things the name means. It takes weight off what is worn, in
`encumbrance()` and nowhere else so that dodging and walking pace get it by the
one route; and it takes up to 29% off what a hammer puts through a breastplate,
because a blow arriving on well-padded, well-fitted plate is a different event
from one arriving on plate that is merely present. A knight at legendary takes
10.5 hammer blows to put down against a novice's 7.7. Both curves were
stretched to reach their limit at level 20 rather than 15: a skill whose last
five levels buy nothing lies to whoever is training it.

**Nobody wrote the spearman.** A spear's point is stopped dead by a breastplate
and its shaft is not, so v3.27's attack judgement reads the difference off the
same numbers and a trained spearman facing a knight clubs him with the shaft
every time -- and thrusts again the moment the armour comes off. The contact
model and the armour model compose without being told to.

## 88.1. The traps that never cut anybody

Measuring the blunt cap turned up a spelling. `TRAP_STRIKES` was written with
damage kinds `"edged"` and `"piercing"`; the model has only ever known `"edge"`
and `"blunt"`, and both the armour test and the tissue test are `kind ==
"edge"`. So a weapon trap that "slashes" you, a spike trap that "impales" you
and a dart that pierces you all fell through to the blunt branch -- which does
not bleed, does not puncture and cannot sever. Cut or puncture wounds from all
three: 0%. A dart drew no blood at all.

They are `"edge"` now, and the low contact areas they were already given do the
rest: a dart carries 9,000 and a mail shirt turns it, a spike trap carries
24,000 and goes through. All three draw blood 99% of the time.

## 88.2. Still dead

`ArmorDef.permit_size` is declared, is settable through `_armor()`, and is 0 on
every one of the twenty armour pieces in the table. Unlike `contact` this is
not data waiting to be read -- there is no data. Authoring what may be worn
over what is a design decision, not a wiring job, and it is left alone.

## 89. Swimming (v3.29)

`TileDef.swim` has been on the water tiles since the tile table was written --
`water` and `deep_water` carry it, `shallow_water` does not -- and no code had
ever read it. What decided whether water could be entered was `TileDef.walk`,
and both deep tiles are `walk=False`, so a river was a wall. `Game.is_passable`
even had a branch letting a `SWIMMER` or an `AQUATIC` creature into deep water;
it sat below the `walk` test and had never once been reached. The `swimming`
skill was in the table with a blank description, was awarded experience in
three places, and outside the fortress's drowning loop was read by nothing.

**The two modes had drifted, which is usually why a thing like this survives.**
The fortress models water as a fluid layer of depth 0 to 7 over the terrain and
has drowned people since v2.5. Adventure mode has no fluid layer at all -- its
water is terrain -- so it had no depth to consult and no drowning to do.
`swimming.TILE_DEPTH` is what lets one rule serve both: it says what depth each
water tile stands for, and `stroke_chance` is now the single answer to "does
this creature keep its head up", asked by both. The fortress's own
`0.25 + skill * 0.06` is gone.

**One clock each, and no pretending otherwise.** The fortress steps ten ticks
at a time and rolls per step; adventure advances by however long the last
creature's action took. Rolling per call would make drowning depend on how many
goblins happened to be awake, so adventure integrates the odds instead of
rolling them, and holds breath as a float. The first version rounded each slice
to an int and treated a zero as "head above water", which threw the entire held
breath away every time the world advanced by a tick or two -- on a busy map,
most of the time. Nothing would ever have drowned.

**The unit was wrong by a factor of thirty.** An actor gains its speed in
energy each tick and acts at `ACTION_COST`, so at the baseline speed one
standard action is *one tick*. `DROWN_TICKS` was first written as 800 -- most
of a minute of continuous drowning. It is 24.

**A hard threshold rather than a steep slope.** Load was a subtraction from the
stroke chance, and at legendary swimming a man in full plate still came out at
even odds. "You cannot swim in a steel breastplate" is worth more as a rule
than as a slope, so `SINK_LOAD` is a floor: above it no skill is any use.
Strokes before drowning, unencumbered: 17 untrained, 52 at fifteen, safe at
twenty. In mail: 13 to 37 -- dangerous at every level. In plate: 11, at every
level, for ever. `armor_use` helps in mail and cannot save anybody in plate,
which is exactly right and was not arranged.

**Three tiles, three named cases.** `water` is the base, `deep_water` is worse,
and water to the ceiling is a flooded room and not a lake -- interpolating
would have been inventing detail the data does not have.

**A deer does not swim a lake for the sake of it.** Once water could be entered
at all, every wandering animal could walk into one and hold its breath until it
stopped. `swimming.avoids`, called from the AI's one movement funnel
`ai._move_to`, refuses it -- unless the creature is already swimming, which it
must be able to do to reach the bank, or is fleeing, which is what water is
for. Measured: 0 of 400 wandering steps in, 400 of 400 fleeing ones. The player
does not go through `_move_to` and keeps the freedom to drown themselves.

## 89.1. The river that was never a biome

`river` is a biome in the table. Five species live in it. `biomes.classify`
cannot return it and no other code assigns it, so no world tile has ever been
one -- and carp and pike list `lake` and `river` and nowhere else, so in a game
that draws a river across half its local maps, neither fish had ever existed.
`lake` is assigned, once in about four thousand tiles.

The world tile knows it has a river running through it, which is enough:
`spawn_wildlife` now adds the river dwellers to what a river tile offers. A
fish also needs putting somewhere it can be -- `random_open` deliberately
avoids water, so a carp placed by it landed on the bank, where `is_passable`
would not let it move and it flapped for ever. `LocalMap.random_water` is the
third place `swim` is now read.

## 90. The attributes you were rolled (v3.30)

Every skill in the table has declared the two or three attributes that govern
it since the table was written. `SkillDef.attrs` had never been read by
anything. The consequence was quiet and large: **ten of the nineteen
attributes** -- analytical ability, creativity, memory, patience, willpower,
empathy, linguistic ability, spatial sense, musicality and disease resistance
-- were rolled for every creature in the world, printed on the character sheet,
and read by no line of code anywhere. A dwarf with legendary creativity crafted
exactly like a dull one, because quality was `skill + d6 - difficulty` in
adventure mode and `random() + level * 0.035` in the fortress, and neither had
an attribute in it.

`skills.aptitude` averages the governing attributes' factors, and
`skills.ability` is trained level times that. Nineteen of nineteen attributes
now reach an outcome.

**Combat is deliberately untouched.** It has its own hand-written attribute
model -- `attack_power` reaches for agility and kinesthetic sense itself -- and
that model has been calibrated against measurements in every milestone from
v3.19 to v3.28. Running aptitude over the top of it would count agility twice
and invalidate all of it. Aptitude is for the places that had nothing, and
there is a test that keeps it out.

**The band decides how many levels talent is worth, and that is the whole
balance of the thing.** At 0.82 to 1.18 the ratio is 1.44, so talent stands in
for a little under half your current level -- three levels to a journeyman,
never four -- and a dull veteran always out-works the most gifted apprentice
alive. A wider band (0.70 to 1.35) was tried first and measured: a prodigy at 8
beat a plodder at 12, which is not what practice is for. `TALENT_WORTH` is
derived from the two constants and asserted against a sweep of every level, so
the rule and the numbers cannot drift apart.

**Rolls and magnitudes, not knowledge thresholds.** This is the distinction the
first version got wrong. How good the work came out, how much was gathered, how
far a price moved, how well a wound was dressed -- all rolls, all take
aptitude. But `tracks.read` and `medical.diagnose` are *bands of what a reader
can tell you*, and running aptitude over those meant a player who trained
Tracker to exactly the documented threshold silently did not get the thing they
trained for. A dull tracker still knows what a deer print looks like once he
has been taught; he is worse at everything the roll decides. Both were reverted
and the rule is written into `ability`'s docstring, because the next person to
wire a site will need it.

**Three hand-written attribute terms were replaced rather than added to.**
`_haggle_factor` multiplied both trade skills by `social_awareness`, which is
one attribute out of the four appraisal and negotiation actually declare;
`medical._quality` added a flat agility term to every treatment including the
ones the table says want empathy; and the stealth score picked agility for the
sneak and intuition for the watcher, ignoring spatial sense -- the one a
creeping man is chiefly using. Adding aptitude on top of any of them would have
counted an attribute twice.

**Where the last two went.** `disease_resistance` had no skill and no reader;
`venom.resistance` is the one thing in the game a syndrome could ever have
meant. `musicality` governs exactly one skill, `music`, so it reaches an
outcome through `performance.score` and nowhere else.

**Nineteen numbers on a character sheet mean nothing until you can see what
each is for.** Every attribute line now names the skills the reader actually
has that it helps, best first, and every skill line says whether it comes
easily or is a struggle. Only trained skills: telling a peasant that willpower
governs Leadership is a manual, not a sheet.

## 91. An industry that can arm its own soldiers (v3.31)

Found by asking a question the dead-data audit does not: not "is this field
read" but "can this ever appear in a game at all". Every weapon and armour
piece in the item table was checked against every production recipe, every
crafting recipe, every starting kit and every uniform.

**Sixteen of the thirty-two weapons and ten of the twenty armour pieces had no
maker anywhere.** No recipe, no kit, no loot table, nothing. Among them: the
sword, the mace, the pick, the battle axe, the long sword, the crossbow, the
breastplate, the gauntlets, the chain leggings and the great helm. The
two-handed sword was worse than unmakeable -- outside its own line in the item
table it was not mentioned by a single line of code in the project, and every
combat milestone from v3.27 onwards has been measuring a weapon nobody could
ever hold.

**Every one of the five uniforms in `military.UNIFORMS` asked for equipment no
fortress could produce.** The swordsdwarf's uniform lists the long sword, the
sword and the scimitar; the forge managed a short sword. The marksdwarf's asks
for a crossbow, which nothing anywhere made. All five want a breastplate. The
equip step worked perfectly and always had -- a squad handed the kit puts it
on, 3 of 3, five to seven pieces each -- so the militia was never broken. It
was starved.

Thirty-two recipes close it: nineteen at the forge, eight at the clothier, and
the crossbow at the carpenter beside the bow that was already there. Costs run
with weight and reach, and a test asserts the ordering rather than the numbers
-- a great axe above a battle axe above a mace -- because an industry whose
prices invert is telling the player something false about what they are
choosing between. The magma-forge duplication at the bottom of the module picks
the new forge recipes up without being written twice.

**Adventure-mode crafting was deliberately left alone.** Its table is field
work -- torches, bandages, arrows, rope, a bone dagger, and two forge recipes
for when you are standing at one. A lone adventurer hammering out a breastplate
in a wood is not the same game.

## 92. Things that fly (v3.32)

`FLIER` has been on ten creature definitions since the bestiary was written --
the duck, the raven, the eagle, the buzzard, the bat, the giant bat, the giant
cave swallow, the roc, the dragon and the demon -- and no line of code in the
project had ever read it. Nine of the ten also carry a pair of wings in their
body plan, modelled down to the tissue, which nothing had ever asked about
either. A raven walked. A dragon walked. Everything that could fly was
pathfinding around lakes and falling down holes with the cows.

Flight is mostly a set of exemptions from rules written for things with feet,
so `game/flight.py` is the one place that says who is exempt. v3.26 made
everything fall; a flier does not. v3.29 made deep water swimmable and
drownable; a flier crosses it dry. A chasm and an open shaft are walls to a
walker and a road to a flier.

**Three things are deliberately not exemptions.** Rock is still rock. Magma is
still magma and fire is still fire -- a creature occupies a whole cell in this
game, so "over the lava" is not a place there is any way to be, and letting
wings past that would have handed every flier free passage across a magma pipe.
And water to the ceiling still drowns: a flooded room has no air in it, which
is what keeps v2.5's sealed-room drowning honest now that a demon can turn up
in one. The rule lives in `swimming.stroke_chance`, so the fortress gets it
without a second copy.

**Wings are why it is worth modelling rather than flagging.** A wing is a body
part with tissues and the combat model has been able to break and sever those
since long before this. Take the wings off a roc and `can_fly` goes false, and
the next call to `gravity.settle` brings it down through however many levels
the drop is worth. That is a fight you can win by aiming. The demon has no
wings in its plan and flies regardless -- whatever is carrying it is not a pair
of wings and cannot be cut off.

`can_fly` also asks the questions that ground anything else: dead, unconscious,
stunned, incapacitated, or carrying more than `FLIGHT_LOAD`. A roc can carry
off a goat and not a granite block.

**Not done: fortress pathing.** `Fortress.is_passable` is documented as "true
if a dwarf could stand there" and takes no creature, so a flying siege still
walks. Threading a creature through it is a refactor of the fortress's whole
route planner and belongs to whoever wants flying sieges, not to this.

## 92.1. The skill nobody could train

The same sweep asked which skills any creature can ever have above zero:
granted by a profession, granted by a creature definition, or awarded
experience anywhere. Sixty-six of sixty-seven passed. `discipline` was granted
by nothing and trained by nothing, so every creature in the game had it at zero
for ever -- and `venom.resistance` has read it since v3.x, meaning the grit
half of shrugging off a syndrome was always worth exactly nothing.

Its description says "keeping your head when things go badly", which names its
two homes precisely: enduring a syndrome, and standing there while the shock of
watching somebody die wears off. Both awards are small on purpose, because both
are clocks and a long one would otherwise hand out a legendary skill for
standing still.

## 93. A siege with wings (v3.33)

v3.32 built flight and left the fortress out of it, on the grounds that
`Fortress.is_passable` is documented as "true if a dwarf could stand there",
takes no creature, and threading one through looked like a refactor of the
whole route planner. That was half right. The structure was contained --
`path_neighbours` has exactly two callers, one for dwarves and one for
hostiles -- and the trouble was somewhere else entirely.

**`LocalMap.flier_neighbours` is the walking graph's superset.** A walker's
edges are built from `walkable`, which means floors, because a walker needs
something under its feet. A flier needs the cell to be *open*, which is a
different set: air, a chasm, the space over a river. It also changes level
anywhere rather than only on stairs and ramps, which is the whole of what
wings buy inside a fortress. Measured over three embarks: 11,097 air cells
reachable that a walker cannot reach, 165 cells of deep water, and **zero**
cells lost -- if the flying graph ever drops an edge the walking one has, a
roc is worse at getting about than a goblin, so there is a test for it.

**Pathing a flier with A* was built, measured and thrown away.** The flying
graph has seven and a half times the edges (17,071 against 2,257 on one map).
Six rocs took the fortress step from 1.5 ms to **100 ms**, and the routes were
*worse*: the roc ended thirty-eight cells from the dwarves where a goblin
walking ended fifteen. `_flier_step` replaced it with a greedy step straight at
the target through any open cell -- which is what wings actually mean, costs
nothing, and is more direct by construction. Six rocs now cost 3.4 ms against
2.6 ms for six goblins: flight is worth about a third more than walking, not
seventy times.

It falls back to the walking planner when no neighbour improves its position,
so a greedy flier boxed into a corner still moves.

**One line nearly shipped the whole thing broken.** The step that follows a
route tested `local.walkable(nxt)` before moving. A flier's route runs through
air, which is never walkable, so every flying path would have been discarded
the instant it was followed: A* would have burned the hundred milliseconds and
the roc would have stood still. It is the shape of bug that a change looks
finished without.

**The test measured the wrong thing first, too.** Final distance to the first
dwarf: a roc that had killed five and chased the sixth into a corner scored 65,
and a goblin that killed one and stopped beside the body scored 1. Closest
approach at any point is the honest measure of "did the terrain stop it".

## 94. What a save keeps (v3.34)

Found by a different question again: not "is this read" but "does this survive
being written down". Every class with a `to_dict` was checked by diffing every
attribute across a round trip, rather than by reading the serialiser and
thinking about it.

Adventure mode came back clean -- which is worth a test saying rather than
having been established once and forgotten, because most of the state the last
dozen milestones added lives there. The fortress did not.

**Held breath.** `Fortress.drowning` was not written. Adventure mode has saved
its copy since v3.29 and the fortress never has, so saving a flooding fortress
handed everybody drowning in it a fresh lungful. The two modes have carried the
same dict under the same name since v2.5, which is exactly the kind of near-
symmetry that hides a gap.

**Whether a dwarf is asleep.** `DwarfState.sleeping` was not written, so a save
woke the entire fortress. That is worse than it sounds: the flag is read by the
vampire's victim search as well as by the sleep loop, so a vampire that had
picked its night quietly had nobody to feed on after a reload.

**Two behaviour counters and a clock.** `idle_ticks` paces what an idle dwarf
does, `blocked` counts pathing retries before a dwarf gives up on a route, and
`Water.ticks` is the phase of the cadence magma moves on. All small; none of
them the game you saved.

**Three fields were vestigial rather than lost.** `Body.bleeding_wounds` and
`Body.nausea` were set in `__init__` and never read or written by anything --
`bleeding_rate` sums the wounds on the parts, and venom's nausea comes out of
its own table into `needs`. Both are gone. `DwarfState.carrying` is written
whenever a dwarf picks something up for a job and read nowhere; the item is in
the dwarf's inventory and `put_down` finds it from the job, so it is a
debugging aid and is now commented as one rather than left looking like state a
save ought to be keeping.

**The guarantee is the deliverable, not the five fixes.**
`TestWhatASaveKeeps` diffs every attribute of a busy fortress, its water, and
one dwarf's state, body and needs across a round trip. `TRANSIENT` is a named
list with a reason against each entry, and it is the whole point: anything new
that fails to survive breaks the suite until somebody either serialises it or
comes and writes down why it should not be. Verified by breaking the
serialisation again and watching two tests fail.

## 95. Spent ammunition (v3.35)

Throwing a dagger and firing an arrow are the same act with different tackle,
and the game treated them as different kinds of event. `actions.throw` walks
the flight path, works out where the thing came down and drops it there, so a
thrown dagger is lying in the grass afterwards. `combat.ranged_attack` did
`ammo.count -= 1` and that was the end of the arrow. **Every shot fired in the
history of this project annihilated its own ammunition**, and the asymmetry was
inside one file.

It matters most where ammunition is hardest to come by: an archer forty tiles
from anywhere runs dry with nothing to do about it, and a fortress that forges
twenty bolts from a bar of iron watches a siege drain the stock with nothing to
sweep up. Stockpiles already accept ammunition, so the hauling half needed
nothing -- there was simply never anything on the floor to haul.

**Some of it has to break or an archer never runs out at all.** A shot that
struck something breaks more often than one that went into the turf, and the
material decides the rest. Measured over 250 shots each: obsidian 36% recovered,
oak 41%, copper 54%, iron 64%, steel 78%. Toughness is bounded at both ends,
so no material makes ammunition permanent and none makes it single-use.

**`spend` splits the stack.** Dropping the ammunition object itself would have
put the whole quiver on the floor and left the archer holding nothing --
`Item.split` has known how to do this since throwing needed it, and firing
simply never asked.

The `ground` parameter is the same one, for the same reason, as the one v3.25
added to the melee path for severed limbs: combat is called from two modes and
from tests that have no world at all, so the caller says where the floor is or
there is no floor.

## 96. The workshops you raised (v3.36)

The README's headline promise, and the reason fortress mode and adventure mode
are one program rather than two, is this: *"Travel to your own fortress and walk
into it: the corridors you dug, the workshops you raised, the goods still on the
floor, and your dwarves lying where they fell."*

Measured through the real `legacy.record` path, three of those four clauses were
true. `preserve` had frozen `buildings` since the day it was written; `restore`
handed back `map`, `creatures` and `items` and dropped them on the floor. An
adventurer who walked into the fortress they had spent a year digging found the
corridors, the goods and the dead exactly as promised, and **bare smooth floor
where every workshop had stood**.

**They come back as ruins, not as buildings.** `game/ruins.py` reads
`Building.to_dict`'s shape as plain data: neither mode imports the other's
classes to do it. A ruin stands there, takes up its footprint, draws itself and
answers the look cursor. It does not take orders. Carrying the job board across
would mean dragging production, hauling and labour into adventure mode to serve
one screen nobody would open.

**Most buildings did not need carrying, and the data says which.** A building
stamps a tile when it goes up, and the map is frozen too -- so a statue already
*is* a `statue` tile, a lever a `lever` tile, a constructed wall a
`wall_constructed`. Carrying those would draw an identical glyph on top of
itself and make the look cursor say "Statue" and then "granite statue, long
abandoned." Of 36 building kinds, exactly 12 draw a glyph their tile does not:
the eleven workshops, which stand on plain smooth floor, and the hospital, which
stands on a bed. That is precisely the set whose identity the map cannot record,
and precisely the clause of the promise that was broken.

`marks_the_ground` therefore compares the kind's glyph to its tile's glyph
rather than keeping a list. A workshop added later is carried without anybody
remembering to come back here, and a workshop given its own distinctive tile
some day stops being carried, correctly.

**Passability was never the ruin's business.** A wall building sets an
impassable tile, and the tile is in the frozen map, so an adventurer already
could not walk through a ruined wall. A ruin is scenery over terrain that
already knows what it is.

`cells()` derives the footprint from `BuildingKind.width`/`height` the way
`Building.cells` does, rather than storing a second copy of the rectangle.
`_local_cache` is the adventurer's own store and separate from
`world.preserved_map`, so filtering on load never rewrites the world's payload;
the full building list stays frozen there for whatever wants it later.

**v3.34's round-trip guard did not catch this one, and that is worth recording.**
`Game.ruins` was serialised correctly, but deleting the line from `to_dict`
left both guard tests green: the fixture is ordinary wilderness, `ruins` is `[]`
on both sides, and a shape-only diff cannot tell an empty list from a field that
was never written. The guard now seeds a ruin before saving. A guard that cannot
fail is worth nothing, and the only way to know is to break the thing on purpose
and watch.

## 97. Reclaim (v3.37)

v3.36 let an adventurer walk into a fortress they lost. The other half of that
story is walking back in with seven more dwarves, and it did not exist. Worse,
the game actively refused: `legacy.make_site` sets `world.tile(wx, wy).site_id`
when a fortress falls, and the embark screen rejected any tile with a `site_id`
with **"Somebody already lives there."** — about a site with `is_ruin = True`
and `population = 0`, where the only residents were the seven corpses you left.

**`preserve` was keeping the contents and losing the place.** Measured against
what a `Fortress` actually holds, twelve things were dropped, including a
67,000-unit magma sea, the caverns, and a 2,047-cell aquifer. A reclaim built
on that payload would have handed the player a fortress whose deep had quietly
ceased to exist.

The rule for what `preserve` now freezes is **what is physically there**. Water
in the cisterns, magma under the floor, the caverns, the wet rock and what the
engravers carved on the walls are the place, and stay. Designations, jobs,
stockpile rectangles, the militia roster and the mayor's demands are
instructions given to dwarves who are dead or gone, and do not. It is the same
line v3.36 drew for ruins, applied to the layers instead of the buildings.

**`Fortress.restore(world, d)`** is `from_dict` split in two. `from_dict` makes
a *copy* of the world, which is right for loading a save and catastrophic for a
reclaim — the site, the legends and the artifacts an expedition walks back into
have to be the ones the rest of the game is holding. Everything but `local` and
`rng` was already optional, so a caller with only part of a fortress (which is
all a preserved ruin is) gets an empty job board and an empty court rather than
a crash. Reclaim and save-loading now share one restoration path.

**Two defects surfaced by building on that path:**

*A reclaimed fortress did not know what year it was.* `restore` overwrote
`__init__`'s clock with `GameTime.from_dict(d.get("time") or {})`, and an
absent `time` is the year 0 — so the site's second fall was recorded as
happening in year 0, before the world began. It now only overwrites when the
payload actually has a time.

*A place was founded once per fall.* `record` inserted a `site_founded` event
every time, which nothing noticed while a fortress could only fall once. A
fortress reclaimed twice read as having been founded three times in the same
year. Going back is now its own `site_reclaimed` event, and it is in
`notable_events` — somebody walking into the fortress that killed seven dwarves
is the most interesting thing that ever happens to a ruin.

**An abandoned fortress was freezing its living dwarves.** This one predates
reclaim and v3.36 made it visible. A fortress is only *lost* once `dwarves()`
is empty, so anybody alive when `preserve` runs is alive because the place was
abandoned — and abandoning it means they packed the wagon and went home.
Freezing them left them on the map with no job board to answer to and no AI to
give them one: an adventurer walking into an abandoned fortress met five
dwarves who had not moved a tile in years, and over 3,000 ticks of a reclaim
two of them died standing still. `walked_out` filters them at the source, which
fixes it in both modes at once.

**A workshop works again.** This is the fortress-side counterpart to v3.36's
read-only ruins, and it needs no special case: fortress mode has a job board,
so a restored `Building` is simply a building. What does not come back is its
order queue and its assigned worker.

### 97.1. The high-water mark

Working in `restore` turned up a save bug with nothing to do with reclaim.
`to_dict` saved `magma_mark` and not `_water_mark`, so **every load reset the
high-water mark to zero**, and the next step compared the map's whole river
against nothing: `water.total() > 0 + FLOOD_WARN`. Any fortress holding more
than 1,200 units announced *"The fortress is flooding!"* the moment it came
back — measured, not reasoned about, by deleting the fix and watching the line
appear.

v3.34's round-trip guard could not have caught it. Its diff skips names
beginning with an underscore, and both marks are private. The new test names
them directly.

Both marks now default to what the payload is loading with rather than to
zero, which is what a high-water mark means and what a reclaim needs: the
magma check has *no* threshold, so a reclaim over a 67,000-unit magma sea
would otherwise have reported the sea itself as a breach on its first step.

## 98. The people in the legends are the people in the town (v3.38)

The README's second paragraph is the whole pitch: *"Everything you hear in a
tavern is a real event that really happened to a real figure **who may still be
out there**."* The first half was true — measured, the rumour lines are real
events about real figures at real sites. The second half was not.

`sitegen` placed exactly two kinds of historical figure: a site's `ruler_hf`
and its `owner_hf`. Measured on a small world: **364 living figures, 356 with a
home site, and 8 ever placed on a map.** The other 348 were unmeetable in
principle. A city whose legends named 21 living residents put one of them in
front of the player, among twenty-nine townsfolk. They were not nobodies: 58
warriors, 47 smiths, 42 hunters, 20 poets, 13 scholars and 9 necromancers who
existed only as rows in a table and as names in the gossip.

**Identify, do not add.** A town already spawns about the right number of
people; they simply had no names out of the legends. `residents.name_the_locals`
takes the population a builder produced and hands out the identities of the
figures who live there, so the town stays the size it was. Called once from
`build_site`, which every site kind already goes through, so no builder has to
remember to ask. 283 of 295 resident figures now have faces.

**Ordering is the whole game**, because there are usually more figures than
slots — a forest retreat had 80 residents and 17 places to stand. `notability`
ranks by titles, kills and deeds, so if somebody has to be left out it is not
the Dragonbane. Events every figure has (`birth`, `death`, `migration`) are
excluded: all 377 living residents had "events about them", so counting events
flatly ranked them all equal.

**`could_be` is two rules, both from the data.** `defn.civ` distinguishes a race
(`human`, `goblin`) from a job (`guard`, `merchant`, `necromancer`): a race slot
needs the matching race, a job slot needs `CIVILIZED`, which is what keeps a
name off a troll or a zombie. The job rule needs the *site's* race as well, and
that second half was missing in the first version — some of a site's listed
residents are not its people at all (a dwarf fortress had eleven goblins on its
rolls), and `hammerdwarf` and `elf_archer` carry no `civ`, so three goblins'
names went onto three dwarven hammerers before the probe caught it.

A retired adventurer is just another resident figure, so `renown.retire`'s
docstring promise — "somebody the next game can hear about, meet in a tavern"
— came true with them and needed no code of its own.

### 98.1. Two dead things next to each other

`rumor_lines(game, hf_id=...)` had accepted an `hf_id` and never referenced it,
so there was no way to ask about a particular person even once there was a
particular person standing in front of you. It now filters to that figure's own
history, and less strictly than the tavern's: `notable_events` keeps wars and
beasts, and a marriage is not notable to a stranger but is the whole of what
most people have to tell you about themselves.

`ask_self` gave name, trade, civ and temperament and never a deed — while
`ask_beast`, two branches below it, quoted a monster's history out of the same
world. It now says what the legends say. The lines stay in the third person on
purpose: the events read "X and Y were married", and the hearsay framing is
both what somebody actually says about their own reputation and the only
phrasing that cannot come out ungrammatical.

### 98.2. "They has no vanity."

Putting named legends in every town made the character sheet worth reading,
which is how this surfaced: **every personality line in the game was
ungrammatical.** The phrases in `_FACET_PHRASES` were third-person singular
("is a coward", "prefers solitude", "has a vivid imagination"), the one thing
that reads them prefixes `"They "`, and where a phrase began `"is "` the code
deleted it. So the game said "They has no vanity.", "They prefers solitude."
and "They a coward." — on the character sheet and the look cursor, not only in
conversation.

The table is now written for a plural or first-person subject, which are the
same in every verb form but the copula. `describe` is `"They %s."` and
`_in_first_person` is `"I %s."` with `are` → `am`, plus the two possessives
(`themselves` → `myself`, `their` → `my`). The old first-person conversion was
a bare `"They " -> "I "` on singular phrases, which is where "I has a vivid
imagination" came from.

## 99. Things that said so and did not (v3.39)

A sweep for two defect shapes the previous milestones kept turning up by hand:
module-level names that appear exactly once — at their own definition — and
function parameters the body never reads. Most hits were legitimate (colour
palettes, uniform dispatch signatures like every `_finish_*` taking a `dwarf`,
`__exit__(exc)`), so the sweep is a lead generator, not a verdict. These are
the ones where the code made a claim it did not keep.

**Two documented behaviours that never happened:**

*A mount did not let you see any further.* Every other constant in `mounts.py`
was wired up — `SPEED_SHARE`, `CARRY_SHARE`, `TRAVEL_FACTOR` — and
`SIGHT_BONUS` was declared, documented as "how far a mount lets you see over a
crowd or a hedge", and read by nothing. Applied after the weather multiplier,
because being higher up does not help you see through fog.

*The hospital never asked for bandages until somebody was bleeding.*
`BANDAGE_PER_DWARF` said it "tries to keep [them] in stock, per dwarf" and
nothing read it, so the only warning was the one that fires with a patient
already on the floor and the cupboard bare. Bandages take a craftsdwarf and a
bolt of cloth; the point of saying so early is that there is still time.

**Standing in a fire left bruises.** Fire and frostbite are blunt to the tissue
model — neither shears anything — so both described themselves with the blunt
wording, and `WOUND_KINDS` listed a `burn` that nothing in the game could
produce. `apply_damage` now takes a `wound` override for the cases the physics
cannot name, and `combat.TRAP_WOUNDS` supplies it. The clause table was
rewritten as a lookup at the same time; it says exactly what the branches said,
which is what `test_an_ordinary_blow_is_unchanged` pins.

**Four enumerations that lied.** These are worth keeping — they document a
field's valid values — so the fix is to make them true, not to delete them:

- `QUEST_KINDS` listed a `deliver` with no builder, no progress path and no
  completion. The word appeared nowhere else in the project.
- `TOPICS` listed an `ask_family` that `topics_for` never offered and `say`
  never answered. The string appeared once, in the tuple.
- `WOUND_KINDS` listed a puncture and a tear that nothing produced. A spear's
  `stab` attack has kind `edge`, so a thrust cuts.
- `EVENT_KINDS` was missing all four kinds a fortress ending, a reclaim or a
  resettling writes, and carried a `tavern_founded` nothing has ever recorded.

**A near miss worth recording.** The first attempt at `EVENT_KINDS` "fixed"
`founded_site` into `site_founded`, on the reasoning that the fortress writes
the second. The test caught it: both are real. Worldgen and the living world
write `founded_site`, and `art.py` and `artforms.py` match engraving phrases
against it; the fortress writes `site_founded`. Renaming either would have
silently stopped an engraving being about anything. The duplication is a wart,
but it is a load-bearing one, and it is now written down as such.

**And a guard that would have gone blind.** These tests work by counting string
literals across the source, so an explanatory comment that quotes a dead value
is a second occurrence — re-adding `"puncture"` to the tuple would have made
the count 2 and the test silent. Verified by reverting every fix and watching
seven of the nine guards fail; the comments now name dead values in backticks.

**Dead constants removed**, each checked for whether the rule it described was
enforced elsewhere: `TRAIN_EXP` (`_finish_train` grants 12 and 20 by hand),
`_NEEDS_SOLID` (`valid()` checks each kind against its own tile test),
`BURN_MOMENTUM` (the same 5200 lives in `TRAP_STRIKES["fire"]`, which is what
`fire.burn` actually goes through), `ORE_METALS` (smelting takes a generic
`ore` input). And one dead parameter: `_haggle_factor` took a `merchant` it
never read — their greed is applied by the callers, and counting it twice
would have been the bug rather than the fix.

## 100. Gods (v3.40)

The game has been building temples since `sitegen` was written. It furnishes
them with an altar and a statue, stations a priest inside, sells you a book at
the door, and calls any room with an altar in it a "temple" — and there was
nothing to worship. `"altar": "temple"` in `rooms.ROOM_KINDS` was the **only**
mention of a temple in the whole of fortress mode: a named room with a quality
score that no dwarf ever had a reason to walk into. A search for
`god|deity|worship|pray` across the project found two hits, both incidental.

**Every people gets a pantheon at worldgen.** Three to six gods, each with a
name in that people's own tongue, an epithet and a sphere. The spheres are not
decoration: `SPHERE_FOR_PROFESSION` sends a smith to the god of craft and a
soldier to the god of war, so a dwarf's prayer sounds like it came from that
dwarf.

**Who worships whom is not stored.** `deity_of` derives it from the
worshipper's own id against their people's pantheon, which costs nothing to
save, cannot be lost in a reload, and gives the same answer in both modes — a
dwarf in your fortress and the same figure met later in the ruins pray to the
same god. It needed one fallback: `Fortress.civ_id` is optional and `embark`
never sets one, so a fortress expedition has no civilization and without a
fall-back to their own race's gods nobody in fortress mode would have had a
god at all — in the one place the temple was built for.

**A temple is now what an altar was always described as.** `Needs` gained
`prayer`, a want rather than a need: it accumulates like hunger but nothing
ever dies of it. A dwarf who has gone a week without a quiet place walks to
the best temple in the fortress, stands in it, and comes out with a good
thought naming their god. A fortress with no altar is told in the only way
that matters — everybody is a little unhappier, seasonally, and there is no
warning box, because building one is a choice rather than an emergency. The
partial count lives in `DwarfState.praying` so a dwarf interrupted halfway
keeps what it has; without that, nobody in a busy fortress would ever finish.

**An adventurer prays at an altar with `_`** — the altar's own glyph, which is
the only mnemonic that needs no explaining in a game you read by its glyphs.
Priests greet you in their god's name and `ask_self` says who they hold to,
which is the second thing v3.38's named locals gave the player to ask about.

The legends screen gains a Gods tab, a page per god listing the peoples that
hold them and their living faithful, and a line on every figure's page saying
who they worship.

**The naming bug worth recording**, because it is the third time this shape
has appeared in this project: `rng.sub("god")` inside the per-god loop is the
*same* sub-RNG every iteration, so the first version named every god of a
people the same thing. One stream, created once and advanced, is the fix — the
same mistake as re-seeding an RNG inside a test loop, which was caught twice in
v3.39.

## 101. The biomes that could not happen (v3.41)

A reachability sweep over the data tables — every creature, item, tile and
biome, asking what a player can never meet — came back clean on creatures
(0 of 80 unreachable) and items (0 of 115), and found this. Measured across
**fifteen worlds and 73,615 tiles**:

| biome | tiles |
|---|---|
| desert | **0** |
| badlands | **0** |
| swamp | **3** |
| marsh | 35 |
| lake | 49 |

Not rare. *Impossible.* `biomes.classify` asks for `rainfall < 0.16` to make a
desert; the generator produced rainfall in **0.236 – 0.941**. The two ranges do
not overlap, so no world has ever contained a desert, and none ever could. Same
story in drainage: the classifier wants below 0.22 for a swamp and above 0.72
for badlands, and the generator produced 0.210 – 0.796 with 90% of tiles between
0.35 and 0.65.

**The comment was the tell.** `# Orographic rainfall: wet near the sea, dry in
rain shadows` sat above three lines that were a noise field, a small latitude
term and a small altitude term. **There was no rain shadow** — nothing looked
upwind at all. The pass below it, commented "Coastal tiles get more rain; deep
inland gets less", only ever *added* to the coast; nothing was ever reduced for
being inland. Both halves of both comments were aspirations.

**Rainfall is now three things.** A latitude band — wet at the equator, dry
through the subtropical highs where Earth keeps its great deserts, wet again in
the westerlies — multiplied by the weather noise; minus continentality, from a
flood fill of distance to the nearest sea; minus a real rain shadow, which
walks back along a per-world prevailing wind and takes rain out of anything
standing in the lee of high ground. Drainage was widened at both ends and
tilted by elevation, because high land sheds water and flat low land holds it,
which is what puts badlands on dry uplands and swamps in wet hollows.

**The first attempt overcorrected and the numbers said so.** Desert went from
0% of land to about 60%, and temperate forest from 40% to 1.4% — a desert
planet, wrong in the other direction. The constants were then swept against a
target (`RAIN_BASE`, `SHADOW_STRENGTH`, `CONTINENT_DRYNESS`) rather than
guessed at twice. Where it landed, as a share of land: desert 10%, badlands 3%,
woodland 35%, and every one of the twenty-one terrain biomes present. Sites,
civilizations and `suggest_site` were re-measured afterwards — 5 civs and 47–66
sites per world, and the suggested embark is still a well-watered river tile.

**`river` is not a terrain type and must not be "fixed" into one.** `classify`
never returns it and no tile is ever one; it is a *habitat tag*, listed by carp,
pike and alligators, which `Game._wildlife_for` asks for when a tile has a river
running through it. The guard test names it as the one deliberate exception so
the next reader does not spend an afternoon on it.

### 101.1. What a worldgen change costs

Ten tests broke, none of them about biomes. That is worth writing down, because
the cause is structural: **the fortress suite is calibrated against one
generated world**, and changing the generator moves the ground under it. The
failures were an embark with no river, a box of rock that used to hold fifty
diggable walls and now held eighteen, a kobold thief wedged at the map edge, a
burrow across a chasm, and an underground dwarf who was *colder* than one on
the roof because the surface had turned tropical.

Two wrong ways to fix that, both tried and abandoned. Hunting for a seed whose
world happens to satisfy every test is whack-a-mole -- each candidate passed a
different subset, and the best one failed five. Moving the fixture to a 65x65
world fixes the scarcity outright and costs the fortress suite about eight
times as long, because every embark copies the world and a small one has four
times the tiles.

What worked was making each test establish what it needs: `embark(water=True)`
for the dozen that want a river (the wet embark is opt-in, because founding on
an occupied square puts a second site on the tile and the legacy tests count
those), digging down until fifty walls are found rather than assuming two fixed
levels, placing the thief where the border beside it is walkable, choosing a
burrow that is *reachable* rather than merely walkable, and asking for winter
before claiming the deep is warmer than the roof. Six tests that had been
silently skipping with "this embark has no open water" now actually run.

## 102. Soil (v3.42)

Version 3.41 gave the world deserts, badlands and swamps that had never
occurred before. The question that raised was whether embarking in one is a
*different game*, and the honest answer was no: the first thing anybody does
in a fortress is farm, and `can_place` had no soil requirement at all. A farm
plot went on any walkable non-water tile. A probe confirmed it: a plot built
on bare granite six levels under the surface grew plump helmets on schedule,
while the building's own description said "Plump helmets grow underground on
nothing but mud and patience."

So soil is now a thing the map has, and a thing a farm needs.

**What soil is.** A `SOIL` flag in `world/tiles.py`, on `dirt`, `sand`, `mud`,
`grass`, `grass_dead` and the two farm tiles. Not on `floor` (dug rock), not on
`stone_floor` (cavern floor), not on `snow`, `ice` or anything constructed.
`SOIL_TILES` maps a biome's soil name to the tile that soil looks like, and
`soil_tile()` is the only place that mapping lives: `_fill_columns`, the web
that gets brushed off a floor, and a freshly dug soil wall all ask it.

**Where soil is.** `_fill_columns` has always laid three levels of `soil_wall`
under every column, but nothing preserved it: `_carve_caves` hollowed out
anything below the surface, topsoil included. Measured on the shared test map,
1730 of 4800 columns had any soil left, and the whole eighty-by-sixty map
offered **one** legal three-by-three farm plot. A cave has a rock roof —
topsoil does not arch over an empty room, it falls into it — so the carver now
skips `soil_wall`. That takes the sheet to 4795 of 4800 columns intact and 641
diggable soil rooms within twenty tiles of the wagon.

**What a dig leaves.** `_finish_dig` used to write `"floor"` whatever it cut
through, which threw away the distinction the moment it mattered. It now asks
`_dug_floor`: soil leaves the biome's soil, rock leaves bare floor. Stairs,
ramps and channels are unchanged — nobody farms a staircase.

**Why the surface is not the answer.** The outdoors is 41% `ramp_up` and
another 27% trees and shrubs; nine flat tiles of grass in a row is rare enough
that the map above offered one of them. That is not a bug to fix, it is the
shape of the game — *wrong on the first half, and §127 says why: the ramps
were the terrain noise aliasing, and once it was slowed down to something a
tile grid can draw, `ramp_up` fell from 36% of the surface to 16% and grass
became the commonest tile on the map. The trees are real, and the rest of this
paragraph stands*: the fortress digs a room in the soil a level down and farms
there, which is where a Dwarf Fortress player puts the farm anyway, and it is
safer from whatever is outside. The founding log says so in as many words, and
so does the build menu when it refuses a plot.

**Irrigation.** Below the soil there is only stone, and a fortress that wants
to farm at depth floods the chamber. `sim._irrigate` runs after every water
step: any cell in `water.moving()` holding at least `MUD_DEPTH` over `floor`
or `stone_floor` becomes `mud`. Only the moving set, so a still map costs
nothing and a river does not silt a whole level at once; only bare rock, so a
floor the player smoothed stays smoothed. It goes through `dig_out` like every
other tile change, where it takes the "changes nothing the water cares about"
early return. This is what the v2.5 engineering was always for: a channel from
the river, a floodgate, a lever, and a decision about when to shut it.

**What the player is told.** The embark report gains a `Soil` row — loam, sand,
mud, or "ice, and no crop" — so a glacier can be recognised before seven
dwarves are committed to it. The founding names the soil and says it is under
their feet rather than at them. The refusal names the way out: "Nothing grows
on bare rock. Flood it and let the mud dry, or dig down to the soil."

`TestSoil` pins fifteen of these, including the three that would silently rot:
that the soil sheet survives cave carving (measured as a fraction of columns,
so a regression in `_carve_caves` fails it), that every biome's soil names a
real tile, and that a smoothed floor does not soak. Each was re-broken in turn
to confirm the guard fails when the fix is removed.

## 102.1. The tests that were farming granite

`test_farm_grows_and_is_harvested` and `test_economy` both searched near the
dwarves for anywhere `can_place` would take a farm, and both had been quietly
building on cavern `stone_floor` — the very thing this milestone forbids. They
now use a `soil_room` helper that mines a room out of the soil sheet starting
from a wall the dwarves could already walk up to, so what it digs is connected
to where they are, and re-checks reachability afterwards because rock inside
the block can cut a corner off. It tries the two dozen nearest soil walls in
turn rather than the single closest, because a block against the map edge can
hold no square nine at all — which is what a player does too.

`_open_spot` — the "somewhere near the dwarves this would fit" helper the
workshop, tavern and temple tests use — had the same problem for a different
reason. It only ever looked outdoors at the wagon's level, and the surface it
was looking at only ever had room because the caverns had eaten it. It now
falls back to mining a room, which is where a fortress puts a workshop anyway.

`TestArt._wall` took the first `rock_wall` in scan order, which after the map
change was on the map border with nowhere to stand beside it: the engraving
was designated, no dwarf could take the job, and the test blamed the engraver.
It now asks for a wall with reachable ground next to it.

Three helpers, one lesson, and it is the same one as §101.1: a test that hunts
the generated map for something convenient is calibrated against that map, and
the next generator change breaks it. A test that *builds* or *digs* what it
needs does not care.

## 102.2. Five sieges that could not work

Keeping the soil sheet whole moved every walkable surface cell on the map,
and with them the corner an army arrives at. On the shared test map the
raiders now land on high ground in the north-east and walk down a slope to
reach the fortress — and that turned up five defects that had been sitting
behind a lucky spawn point. Four of them are the same sentence: *an invader
that cannot get to the fortress is not a siege.*

**A goblin that never moved.** Measured, on the shared map: dropped at the
north-east corner, twenty-five tiles from the dwarves, it stood on its spawn
tile for a hundred and twenty steps. Three things were wrong at once.

`_hostile_step` re-planned whenever the goal changed, and the goal is the
prey's exact cell, which moves every tick — so A* ran once per tick per
invader, which is why its node cap was 2500, and 2500 nodes will not cross
this map with a hill in the way. It now re-plans when the route stops
applying: `REPATH_SLACK` tiles of drift, a change of level, or running off
the end of its own path. That buys `HOSTILE_SEARCH` at 20000 nodes *and* it
is faster — six invaders cost 1.12 ms a step instead of 3.90, because a
search that fails burns its whole budget and these mostly succeed.

The fallback for when there is no route at all was a single step in the
compass direction of the prey, taken only if that exact tile was walkable.
`_shove_towards` replaces it: the best neighbour *on the creature's own
graph*, which is a swerve rather than a shrug. That is also what an invader
does now when the next tile of its route is occupied by somebody it came
with — five raiders following one route in single file used to spend the
siege blocking each other, covering seventeen tiles in two hundred and fifty
steps.

And a flier that ran out of greedy moves fell back to the *walking* planner,
which is no use to something hovering over a hillside: no walking
neighbours, no route, nothing walkable to step onto. A roc flew two thirds of
the way to the dwarves and then hovered in one cell for eighty steps. It
plans on the flying graph now. Pathing a flier every step is what `_flier_step`'s own
comment records as measured and rejected; pathing it on the rare step where
greed fails, and keeping the route, is not.

**A retreat that could not climb.** `war.retreat_step` stepped in x or y on
the invader's own z. An army that had walked *down* to reach the gate could
therefore never walk back up, and a goblin that broke at the bottom of the
slope stood on that tile for the rest of the fortress's life.

The first fix was "take any neighbour strictly closer to the edge", on the
walking graph so ramps and stairs count. That is wrong in a way worth writing
down: the distance to the edge is a function of x and y only, so a step that
*only* changes z — which is exactly what climbing a ramp out of a pit is —
never looks like progress, and the invader stays in the pit. Greedy on the
wrong metric is not better than greedy on the wrong axes.

So the route is searched for: `pathfind.path_to` breadth-first to the first
cell on the map border, cached in the same scratch state the approach uses
and re-searched only when the invader is no longer standing on its own path.
"Any edge of the map" is a goal you can describe and cannot point at, which
is why this is a BFS to a predicate and not A* to a cell. An invader with no
route out at all stops moving, which is what a besieger in a sealed corridor
should do, and `FLEE_TICKS` clears it eventually.

**A siege that outlived everybody in it.** `fort.siege` was only cleared in the
routed branch, which needs `ROUT_LOSSES` of the army dead. A raid of two never
gets there: its members lose their nerve one at a time, walk off the map
individually, and the alarm went on ringing over an empty map. `_hostiles` now
ends a siege when there is nobody left on the map who came with it, however
they went, and records the battle the same way a rout does.

Neither was caused by the soil work; both were found by it, which is the usual
way. The measurement that separated them from "the map changed and a test got
unlucky" was reverting `_carve_caves` alone and watching the same siege finish
in 67 steps.

## 102.3. Nine wrappers nobody called

Adding `soil_tile` and `is_soil` to `world/tiles.py` meant looking at what else
was in there, and the answer was nine one-line predicates with zero callers:
`walkable`, `blocks_sight`, `is_wall`, `is_open`, `is_water`, `is_stair_up`,
`is_stair_down`, `is_diggable` and `by_flag`. Every site in the game reaches
for `tile_data.get(tid).has("WALL")` directly and always has. `LocalMap` has
its own `walkable(x, y, z)`, which is what the two hundred call sites mean when
they say walkable, and which is why the module-level one looked used from a
distance and never was. Deleted, with a comment saying which nine went so the
next person adding a wrapper knows the house does not use them.

`engine/pathfind.py` had two of its own. `path_cost` was never asked what a
path cost, and is gone. `path_to` was never called either — and its `goal`
parameter was dead *inside* it, because a BFS to a predicate has no single
cell to aim at and the body never looked at the argument. It got a caller
instead of a funeral: the routed invader above needs a route to "any edge of
the map", which is exactly the shape `path_to` is for and exactly the shape
A* cannot take. The dead parameter went with the fix.

## 103. Smooth stone (v3.43)

The audit this time was of the *interface*: for everything the game defines,
can the player ask for it? Nine designation kinds, four build categories, ten
stockpile types, eleven workshops' worth of recipes, twenty-two labours,
fifteen keys the help promises on the fortress screen. All of it reachable —
except one.

**`engrave` had no key.** `ui/fort/designate.py` binds each designation to a
letter in a `BINDINGS` tuple, and `engrave` was not in it; `extra_key` reads
nothing else. So `fortress/art.py`, `world/artforms.py`, engraving quality,
the history an engraver carves, what an engraving is worth to the room it is
in, the dwarves cheered by walking past one, the look cursor that reads it
back, a README paragraph and a help section — none of it
could be asked for from the keyboard. `TestArt` never noticed because it calls
`fort.designations.set` directly, which is the lesson: a test that reaches
past the interface cannot tell you the interface is missing.

`TestDesignations.test_every_kind_has_a_key` now holds `BINDINGS` against
`KINDS` in both directions, and checks no two share a letter and none of them
is `x`, which erases.

**Floors take a chisel now.** The designation has described itself as "Smooth
a rough wall or floor" since it was written, and `valid()` answered
`t.has("WALL")`. Two things followed from that. One: the mason could dress the
walls of a hall and never its floor. Two — and this is the measurable one —
`rooms.measure` counts the *smoothed cells of a room*, and a room's cells are
its floors, so that term was zero in every fortress ever built. Measured on a
five-by-five chamber: quality 12 rough, 31 with the floor dressed.

The rule is bare rock only: `floor` and `stone_floor`, which `world/tiles.py`
now names once as `BARE_ROCK` because `sim.SOAKS` is the same set for the same
reason. Soil takes no chisel; a constructed floor is already finished. And
that shared constant is a decision the player now makes: **a floor you have
dressed will never take mud**, so a grand dining hall is a decision not to
farm there.

**And they take an engraving.** `engrave` accepts `floor_constructed` as well
as `wall_constructed`; `art.admire` looks at the cell the dwarf is standing on
as well as the four beside it.

`art.room_value` had to change to allow it. It walked every cell of the room
and added the value of anything engraved on the four cells around it — so a
wall in an alcove, touched by two room cells, was worth twice a wall in a
straight corridor, and a *floor* engraving in the middle of a room would have
been worth five times one at the edge. It now counts the room's own cells once
and the ring of walls around it once.

## 104. Glass, and what a material may become (v3.44)

The audit that found the missing engrave key also produced a list of flags the
data tables declare and no code reads. Two of them were a whole industry and a
whole rule.

**`GLASS` and `SAND`.** The `glass` material has been in the table since the
beginning — density 2600, value 5, shear yield 800, `max_edge` 8000, a bright
brittle thing — and nothing in the game could produce a single piece of it. The
`SAND` flag sat on one tile and was read by nobody. So:

- A `sand` designation, valid on anything flagged `SAND`, bound to `a`. The
  job drops a bag and leaves the tile alone; `complete_job` clears the
  designation for every designation kind, so a desert is infinite and you
  re-paint it, which is what a desert is.
- A `glass_furnace`, a `glassmaking` labour and a `glassmaking` skill.
- Eight recipes, all `sand` + `FUEL` with `out_material="glass"`: table,
  chair, coffer, cabinet, door, statue, crafts, flasks.

None of it wants wood, ore or a mountain, which is the point. v3.41 made
deserts occur and v3.42 made them hard to farm; this is the other side of that
bargain. A fortress on sand with nothing growing on it can furnish itself and
still have something for the autumn caravan.

**`WEAPON_OK` and `ARMOR_OK`.** Declared on forty-four materials, read by
nobody. Gold, platinum, lead and tin all say *not a weapon* and the forge
would happily take three bars of gold and a load of charcoal and give you a
sword that bends on the first parry. `production.material_allows` now asks,
for any input that is not `FUEL` or `FLUX` — those are burned, not shaped, and
checking them was the first version's bug: it rejected the coal and no recipe
could be made at all.

The rule found two gaps in the data rather than the other way round.
`wood_shield` and `make_whip` are recipes that already existed and that no
material could satisfy any more, because wood had no `ARMOR_OK` and leather no
`WEAPON_OK`. A wooden shield and a leather whip are both real things. The test
that caught it — "for each input, is there any material this item could
plausibly be made of that the rule lets through?" — is worth more than the
rule: a gate that forbids everything is not a rule, it is an outage.

**Six tiles made of nothing.** `dirt`, `sand`, `mud` and three more named
materials that did not exist. `mat_data.get` falls through to iron and
`Item.__init__` silently swaps an unknown material for iron rather than
complain, so a bag of sand would have been a bag of iron and nobody would have
seen a traceback. The three soils are real materials now, and a test walks
every tile's material name.

`Item.base_name` needed one more line for it: it dropped the material
adjective when the noun *started* with it, so "bag of sand" came out as "sand
bag of sand". It now also drops it when the adjective appears as a word
anywhere in the noun. A sand bag would be a bag made of sand, which is a
different object.

## 105. The dead (v3.45)

Until now a dwarf died, dropped a corpse, gave everybody a bad thought, and
that was the end of it. The corpse could be hauled to the refuse pile with the
bones and the rubbish and left there for the rest of the fortress's life, and
nothing anywhere minded. There were no coffins, no burial, no graves and no
consequence — in a game whose whole subject is what a fortress leaves behind.

**Coffins.** A one-tile piece of furniture out of stone or wood, in the
`Furniture` build category, `ROOM_KINDS["coffin"] = "tomb"`. A `Building`
gained `buried` and `buried_name`: the id because two migrants can arrive with
the same name, and the name because it has to outlive the creature record.

**Burial needs no designation.** `sim._scan_burials` matches an unburied body
to an empty coffin and posts a `bury` job, ahead of ordinary hauling in
priority — a corpse in a refuse stockpile is still a corpse nobody buried. The
job reuses the hauling machinery exactly: `job_items` was already the single
place that says what a job needs in hand, so adding `"bury"` to one tuple gave
the fetch, the carry, the drop-on-abandon and the reservation for free. The
coffin is `building_at(job.cell)` rather than a second target field, so the two
cannot disagree.

**`fort.unburied`** is dwarf id → the tick it died, written in `kill_creature`
and cleared by burial. That dict is the whole bookkeeping.

**Ghosts** are `fortress/ghosts.py`, deliberately not creatures. A ghost has no
body, no needs and no inventory; giving it one so the combat system would
accept it would hand the fortress a monster it can neither kill nor flee,
which is a different and much worse game. It drifts one cell a step towards
the nearest dwarf *through the walls* — no pathing, because it has no feet,
and no door in the fortress will keep it out. Every `CHILL_TICKS` it costs
everybody within `HAUNT_RANGE` a thought.

It rises `HAUNT_AFTER` — one season — after the death, and only while there is
still a body to bury. That last clause is the important one: there is no
memorial slab in this game, so without it a corpse that was burned, butchered
or carried off by a thief would leave a haunting the player has no way on
earth to end. Burying the body lays the ghost, and everybody feels the relief.

**Two guards that were not guards.** Writing the re-break pass caught two
tests passing for the wrong reason. "Burial takes the body off the floor" was
satisfied by a dwarf that picked the corpse up and never put it down — it now
also checks the coffin holds them and nobody is still carrying it. And "a body
that is gone raises nothing" survived removing the check in `restless`,
because `rise` refuses too; the rule is guarded in both places and the test
only fails when both go. Worth knowing which of the two a green test was
actually resting on.

## 106. The corridor (v3.46)

Every previous milestone was found by auditing the code. This one was found by
playing the game: a year of fortress, competently set up, left running. On day
ninety every dwarf was dead of thirst. There were two thousand one hundred and
ninety-three units of ale in the stockpile.

Nothing in the fortress reported a problem, because nothing in the fortress
believed there was one. Instrumenting the drink loop showed `_go_drink`
returning `True` three hundred times in a row for a dwarf that had not moved a
tile. The dwarf asked for a drink every single step of its life and was told,
every single step, that it was on its way.

**The cause.** `_step_around` is the rule for what a dwarf does when something
is standing where it wanted to step: wait one beat, then shoulder past, then
give up on the route. Only the middle clause had a qualifier on it, and the
qualifier was wrong — it shouldered past *another dwarf*, tested as "has fortress
state". Livestock has no fortress state. Livestock also does not queue, does not
path and does not get out of anybody's way. Of two hundred blocking events
logged in the failing run, a hundred and fifty-six were cows.

So three cows in a corridor were a wall with no door in it, and the fortress
starved to death behind them. `_step_around` now shoulders past anything that
is not `hostile`; a hostile is not shoved aside, because that is what the axe
is for.

**Why nobody noticed.** `_step_around` returns `True` on every path through it,
including the one where the dwarf does not move. That value is `step_along`'s
answer to "did I get anywhere", and it is what the need loops watch to decide
whether a plan is working. A blocked dwarf therefore reported success for ever,
so nothing escalated, nothing re-planned, and no warning fired. A failure that
reports itself as a success is invisible to every test that asks the system how
it is doing; the only thing that catches it is asking the *world* — which is
what "is anybody dead of thirst while there is ale in the barrel" does.

**Somebody has to yield, and it has to be the same somebody.** Widening the
shove exposed the reason it had been narrow. Two dwarves heading the same way
down a one-tile corridor, each free to shove the other, trade places for ever —
and each reports a successful step, so again nothing escalates. `_outranks` makes
the relation total and antisymmetric: need first, so the one dying of thirst
gets past the one out for a walk, then id as the tiebreak. A pair can never
disagree about which of them is yielding.

**What a shoved creature needs of the tile.** The tile a dwarf vacates is
walkable — but that is a fact about dwarves. Everywhere else in the game an
`AQUATIC` creature cannot enter a tile without water in it, so `_may_stand`
keeps the shove from putting a carp on the riverbank. When it refuses, the
third clause of `_step_around` is still there to route the dwarf around.

**A test that could not fail.** The first version of the rank test asserted
that two dwarves sent down one corridor both arrive. It was green with
`_outranks` deleted entirely — because they start one behind the other, so the
front one simply walks to the goal and the back one follows, and the rule under
test is never reached. Worse, the assertion is false on its face: one tile
holds one dwarf. The replacement counts how many times the goal *changes hands*
after somebody first reaches it — twenty-six in forty turns with a symmetric
rule, none with a ranked one. That is the thing a symmetric rule actually does
to a fortress: the dwarf that reaches the barrel is shoved off it by the next
one to want it, for ever, and neither of them ever gets a drink.

**What the fix uncovered.** The same two hundred and forty days, re-run: the
fortress lives the whole year, ale reaches seven thousand, wealth eighty-five
thousand, two artifacts get made. Nobody dies of thirst. What kills them now is
each other — forty-seven assaults, one murder and one theft on the crime
register, ten dwarves bled to death and one drained of blood. That is a
different fortress with a different problem, and it was invisible while they
were all dying of thirst by day ninety first. Fixing the thing in front of you
is how you find out what is behind it.

### 106.1. Three tests that were measuring the seed

Widening the shove changes when a dwarf takes a step, which changes what the
RNG is asked next, which changes the weather and the whole trajectory of a
fortress. Three tests went red. None of them was a regression, and all three
were asserting something narrower or luckier than the thing they were named
for.

**A cow's thirst was asserted to be exactly what it had been.** It was 74.
`sim._bodies` deliberately does not tick dwarf needs on an animal — "ticking
dwarf needs on a cow kills the whole herd of thirst in three days" — but
`world/heat.py` writes `needs.thirst` directly on everything with a body,
animals included, so a hot afternoon moves the number and the cow grazes it
back off. Measured over fifteen hundred steps on five embarks, a cow peaks at
306 against the 9000 that counts as thirsty; with the exemption in `_bodies`
removed, the same cows reach 15306. The assertion is now "below thirsty",
which is fifty times clear of the noise and still catches the defect it exists
for.

**A roc's chase was asserted on one embark.** It reached a dwarf there and the
test said fliers beat walkers. Measured across eight embarks it is not true:
the roc reaches somebody on four of them, the goblin on seven. `_flier_step`
is greedy by design — the flying graph was measured and rejected — and a
greedy chaser orbits a local minimum. On the seeds where it fails it is still
moving on every one of a hundred and twenty steps: never stuck, never closer.
That is a real defect, it is the flier's, and it was hidden behind one lucky
map. The test now pins what flight does provide and names what it does not.
(Fixed in v3.48 — §108. The cause was not the greedy step but greed and the
plan overruling each other every other turn.)

**A tavern's attendance was asserted on one embark.** The test already carried
a comment about an earlier version of itself passing on map luck. Attendance
swings from none of the fortress to all of it depending on the layout — one of
five seeds puts nobody in the room under any version of the pathing rules — so
it is counted across five now: 66% of dwarves, against a few percent for
wandering at random into a nine-tile room.

The pattern is one thing three times. A test pinned to a single seed is pinned
to the RNG, and the RNG is downstream of every behavioural change in the
program. When such a test goes red, the question is never only "did I break
this" — it is also "was this ever measuring what it says".

The lesson is the milestone. Reading code finds what contradicts itself. Only
playing the game finds what is perfectly consistent and wrong — and only the
re-break pass finds the test that was agreeing with you for free.

## 107. The accusation (v3.47)

The fortress v3.46 left running was thriving: eighty-five thousand in wealth,
seven thousand units of ale, two artifacts, two hundred and forty days. Ten of
its twelve dwarves were dead. One vampire killed all of them.

It was not hidden. A vampire that feeds where somebody is awake to see it puts
its own name in the log — *"X wakes to find Y bent over Z"* — and then in the
sheriff's book. Forty-seven of those nights were written down with the killer
named on every one. The player could read the name of the thing killing the
fortress and there was no verb in the game to act on it.

**Why the law never came.** A sheriff is appointed at a population of eighteen.
This fortress peaked at twelve, because the vampire was eating it. That is not
a bug in the threshold — it is documented in the help and on the justice screen
— but it does mean the fortress most in need of a sheriff is the one that
cannot have one, and the defence the help recommends (sleep in a dormitory so
there are witnesses) produces evidence nobody can act on.

**The verb.** `justice.confine` holds a dwarf on nothing but the player's
say-so. No trial, no evidence, no sentence: `u` for the units list, `h` on
whoever you have decided about. It costs what that costs — the held dwarf takes
a bad thought and so does anybody who was close to them, and if you are wrong
you have jailed a mason and the deaths go on.

**Holding has to be a place.** The first version stopped a held dwarf working
and left it where it stood, and that does nothing to a vampire: it was still
sleeping in the dormitory, still next to the beds, still feeding. `J` marks the
cell, and a held dwarf walks there and stays. The test states the reason out
loud rather than trusting the map — the cell must be further from the beds than
`sim.FEED_RANGE`, which is thirty.

**And a cell has to feed its occupant.** `take_turn` ran the needs *before*
`_serving_time`, so a held dwarf left the cell the moment it was hungry and was
back in the dormitory every night — held on paper and at large in fact. The
order is now reversed and `_keep` answers the needs where the dwarf stands,
out of the same stores everybody else eats from. A cell that starves its
occupant is not a punishment, and holding somebody now costs the fortress food
as well as a pair of hands.

**One funnel.** `justice.is_jailed` answers for both kinds of holding —
sentenced and merely suspected. `dwarf._serving_time` and the units list were
already asking it, so neither had to learn about the new one, and the two kinds
cannot come apart.

### 107.1. Three hypotheses the measurements killed

The chain took four probes to find and the first three were wrong, each
plausibly so.

**"They are brawling."** `_start_brawl` calls `melee_attack(..., weapon=None)`,
and `weapon=None` in that function means *use whatever you are wielding* — so a
docstring promising "barehanded... a bruise, not an execution" appeared to be
handing brawlers their axes. A perfect promise-versus-reality defect, and
entirely irrelevant: instrumenting the function recorded **zero brawls** in two
hundred days. Stress never reached the tantrum threshold at all. The reading
was right about the code and wrong about the game.

**"The court is broken."** With the crime book full and every case open, the
obvious suspect was `hold_court`. It works: called directly it convicts on the
first try. Two experiments then failed to disprove it for two different reasons
of my own making — one checked for an expedition leader before any had been
appointed, so it never appointed the sheriff it thought it had; the next
appointed one and never noticed the sheriff had died, since a dead noble still
holds the position. A probe that silently does nothing looks exactly like a
probe that found nothing.

**"Every map is dry."** Fourteen embarks, zero water tiles, and dwarves dying of
thirst beside a `_drink_water` function that never fires. Fourteen for fourteen
is the tell: `tests.embark` copies one shared world and calls `suggest_site`, so
every seed is the *same square* — the seed varies the fortress's dice, not where
it stands. The survey measured the test fixture. `embark(water=True)` exists
for exactly this reason.

What survived all of that is the thing that needed no inference: the game names
the killer and offers nothing to do about it.

## 108. The roc that paced (v3.48)

v3.46 measured the flier and wrote the result down rather than acting on it: a
roc reaches somebody on four of eight embarks, a walking goblin on seven. On
the seeds where it failed it was never stuck — it moved on every one of a
hundred and twenty steps and never came closer. This is that defect.

**What it was doing.** Tracing one chase: a hundred and twenty steps, **three
distinct cells**. The roc paced between two of them for the whole siege, sixty
steps forward and sixty steps back, ending fifty-seven tiles from a fortress it
had started sixty-four from.

**Greed and the plan were fighting.** `_hostile_step` tried the cheap greedy
`_flier_step` first and only planned when greed ran out of moves. But a flier's
plan exists *precisely because* greed ran out — so it is always a route around
something, and the first step of a route around something is usually away from
the goal. That is exactly the step greed undoes. The two alternated: the plan
stepped the roc out of the pocket, greed dragged it straight back in, the plan
was discarded as stale and re-planned, for ever.

The fix is one condition. Greed only gets a turn when there is no plan to
follow:

```python
if flies and stale and _flier_step(fort, foe, goal):
    return
```

Eight of eight embarks now reach a dwarf, against four before, and the roc
stops pacing: fourteen steps, fourteen distinct cells.

**And it is cheaper.** Flier A* was rejected once on cost — six rocs took the
step from 1.5 ms to 100 ms — and the fear was that leaning on it would bring
that back. It does the opposite, because following a plan is cheaper than
re-planning every other step: six rocs measured at **1.32 ms a step against
1.92 before**. The pacing was not just useless, it was the expensive option.

### 108.1. Three reasons a roc stands still, none of them hovering

The guard for this is "a flier never stands still out in the open", and
writing it took four attempts because a roc that *arrives* stops moving for
three separate reasons that have nothing to do with flight:

- it is **unconscious** — it reached the fortress at step twenty-one, killed
  four dwarves and was beaten senseless by the rest, then lay there twenty-seven
  steps and died of it. The trace said `unconscious 170`;
- its **morale broke** — twelve more steps, awake, wounded, going nowhere,
  which `_hostiles` already documents as "an invader boxed in stops moving and
  stops fighting";
- it is simply **fighting**, which is standing next to somebody and swinging.

Every one of those looked like the bug when counted from outside, and the first
version of the guard failed on all three. The honest boundary is arrival:
count the approach, stop at the moment it gets there, and say so. What happens
afterwards belongs to combat and morale, and a flier test that ranges into
them is measuring the wrong system.

The near-miss is worth keeping. Having just fixed a real pacing bug, a metric
saying "still pacing" reads as confirmation, and the temptation is to fix
harder. It took reading `unconscious 170` in a trace to notice that the second
number was not the first defect at all.

## 109. The feeling that never lasted (v3.49)

Two hundred days of a fortress that lost ten of its twelve dwarves to a
vampire. Not one tantrum. Not one brawl. Every survivor sitting at a stress of
exactly zero. The whole unhappiness system — unhappy, tantrum, berserk, brawl,
and the sheriff's book that hangs off it — had never once been reached.

**The rate.** `STRESS_DECAY = 900` is documented as "ticks for one point of
stress to fade back towards indifference". The code was:

```python
drift = ticks / float(STRESS_DECAY) * self.recovery()
self.stress -= int(math.copysign(max(1, int(drift)), self.stress))
```

The floor of one exists because `int(0.011)` is zero and stress that never
fades is worse than stress that fades too fast. But it applies **per call**,
not per tick, and the fortress calls this every ten-tick step: a whole point
every step, fourteen hundred and forty a day against the sixteen the constant
asks for. Ninety times too fast. Every dwarf was permanently at zero, which is
why nothing ever happened and why nothing looked wrong — a fortress full of
dwarves feeling nothing in particular reads exactly like a fortress full of
contented ones.

The fix is a carry: bank the fading and spend it a whole point at a time.
Banked as **ticks**, not as fractions of a point, because ninety lots of one
ninetieth add up to 0.9999999999999999 and nine hundred ticks has to shed
exactly one. The first version of this banked fractions and the test caught it.

**And sleeping never settled anybody.** `sleep()` was
`self.stress -= ticks // 400`, and a fortress sleeps in forty-tick
instalments: forty over four hundred is zero, every time, for the whole life
of the game. The same carry, banked as integer ticks so that four hundred
ticks of sleep settles exactly one point.

**What it looks like now.** A hundred and five days, measured: content for the
first sixty (stress around −90, which is a fortress where everything is fine),
and then a spiral as it starts losing people — eight tantrums, two brawls, two
berserk dwarves, and four of seven crossing the unhappy threshold. Before the
fix the same fortress produced nothing at all. It reacts, and it only reacts
when something is wrong.

### 109.1. A bug that was waiting for its trigger

`_start_brawl` opens: *"Barehanded, and only one blow: a fistfight in the
dining hall is a crime and a bruise, not an execution."* It called
`melee_attack(..., weapon=None)`, and `weapon=None` in that function means
**use whatever you are holding**. A miner threw its tantrum with a pick.

This was already visible in v3.47, when a probe went looking for it as the
cause of ten deaths. It was not the cause — the probe recorded zero brawls,
because no dwarf was ever unhappy enough to throw one. So it was a real defect
sitting behind an unreachable code path, harmless precisely because the other
bug kept it that way, and fixing the stress rate armed it.

`melee_attack` gained an explicit `unarmed` flag rather than a new sentinel
value: `weapon=None` is the right default for a fight and the wrong one for a
scuffle, and those are different questions that deserve different arguments.

The lesson is about the shape of dead code. Nothing about `_start_brawl` looks
unreachable — it is called, it is tested, it has a comment explaining its odds.
It was unreachable because a rounding error four modules away kept the number
that gates it pinned at zero. "Can this happen at all" is a question about the
whole system, not about the function.

## 110. The job nobody could reach (v3.50)

One embark ran at **twelve hundred and forty milliseconds a step**. An ordinary
one runs at one and a half. A fortress at that speed is not slow, it is
unplayable, and nothing about it looked wrong from the outside: seven dwarves,
four jobs, no siege, no water, no fire.

Profiling ten steps: ninety-one A* searches accounted for fifty of the
fifty-one seconds, expanding 3.6 million cells between them — some forty
thousand apiece. Instrumenting the searches, **forty-two of forty-four
failed**, on a handful of repeated goals. Four `tend` jobs, on animals sealed
away in a cavern, retried by every idle dwarf on every step for the life of
the fortress.

**Every part needed to stop it already existed.** `job.failed` counts
give-ups. `JobBoard.for_dwarf` skips a job at three failures. `_prune` drops it
at three. `fort.unreachable` maps a cell to the tick it is worth trying again.
None of it helped, for two reasons that only matter together:

- the counter lives on the **job**, and the scanners post a fresh one the
  moment `_prune` drops the old — so `failed` reset to zero for ever, and a cow
  in a sealed cavern is four `tend` jobs that keep coming back;
- `fort.unreachable` is the memory that *would* survive that, because it is
  keyed by cell rather than by job — but it was only ever consulted by the
  designation scanner. Everything nobody designated went unguarded.

The fix is four lines in `_claim_job`, which is the one place a dwarf takes a
job: skip a cell that is currently marked, and mark it when the search fails.
`fort.dig_out` — the one funnel every tile change goes through — clears the
marks, because digging is precisely the answer to "nobody can get there" and
cannot be the one thing that leaves the note saying so in place.

**1240 ms a step became 1.44.** An ordinary embark measured 1.25 before and
1.28 after.

**And it costs nothing.** A sixty-day fortress run either side of the fix
finishes byte-identical — seven dwarves, wealth 12405, twenty-five food, 1171
ale, six buildings, an empty job board — because on a fortress where everything
is reachable the mark is never set. That comparison is the one that mattered: a
speed fix that quietly stopped dwarves taking work would be worse than the bug
it cured.

The mark is per cell and not per dwarf, so a job one dwarf cannot reach is set
aside for all of them. That is the cheap assumption rather than the correct
one — two dwarves can be in different connected components — and what makes it
safe is that it expires. `RETRY_DELAY` is four hours; digging clears it sooner.

### 110.1. Two ways to lose your own work

Both worth writing down, because neither is about the game.

**A stash held across a background job.** The productivity comparison ran
`git stash push`, the benchmark, then `git stash pop`, in the background — and
while it ran I kept editing the same two files. For four minutes the working
tree held the *unfixed* code, so a probe reported the fix doing nothing and a
`grep` for it came back empty. Nothing was lost, because the pop restored it,
but the minutes spent debugging a fix that was sitting in `stash@{0}` were.
Never background a command that stashes and pops files you are still working
in.

**A `pkill -f` pattern that matched its own replacement.** Killing the old
probe and starting the new one in a single invocation killed both: `-f`
matches the whole command line, including the `bash -c` wrapper of the
command being launched alongside it. The same hazard is already noted for
`pgrep`; it is worse for `pkill`, because the evidence is a process that
exited before it printed anything.

## 111. Playing the other half (v3.51)

Six milestones running, every defect has come out of the same method: set the
fortress going, leave it a year, and look at the wreckage. A fortress dead of
thirst with two thousand units of ale in it. A roc that paced between two cells
for a whole siege. A vampire named forty-seven times in a book nobody could
act on. None of them was visible in the code.

Adventure mode had no such instrument. `tools/smoke` proves the screens fit
together; `tools/fuzz` presses keys at random. Neither plays. So this milestone
is the missing instrument, and the audit it made possible.

**`tools/play`** drives the real action layer through `Game.player_acts`, the
way the play screen does, and looks after the character the way a player would
— drink, eat, sleep, hit what is adjacent, otherwise wander. It ends in
assertions rather than a wall of output: needs that never moved, a death by
thirst beside water, or a run that stopped without dying are all reported as
problems and exit non-zero.

**The audit found nothing.** That is the result, and it is worth writing down
so nobody repeats it:

- step cost is flat across twenty-four embarks, 1.31 to 1.77 ms, with no
  outlier of the kind v3.50 fixed;
- an ordinary adventure turn costs 3.7 ms, and an eight-hour sleep 148 ms for
  the 4800 ticks of world it simulates — proportionate, not pathological;
- every key the help promises is handled by the screen it belongs to;
- `refill_waterskins` invents water out of nothing, and has exactly one caller,
  correctly guarded by `water_source_near`;
- the local map an adventurer walks into holds thirty to forty creatures.

One piece of genuinely dead code turned up and is left alone deliberately:
`refill_waterskins` opens with "no skins, no water", which cannot fire —
with no skin the capacity is zero and the very next line returns zero anyway.
Deleting it changes no behaviour, which is exactly why the test that tried to
pin it could not fail. The test now pins what a skin actually does, and says
why.

### 111.1. Three probes, three self-inflicted wounds

The instrument exists because the ad-hoc probes kept lying, and all three
failures were mine rather than the game's.

**A probe that never took a turn.** The first driver called the action
functions and then `game.advance()`. That is not a turn: nothing charges the
player its energy, so the scheduler hands the turn straight back and the clock
barely moves. Two hundred "turns" advanced the world by two ticks, thirst rose
by two, and the reading — *an adventurer would need four million turns to get
thirsty* — looked exactly like a discovery about the survival layer. It was a
discovery about `player_acts`. The first guard in `TestPlayingTheAdventure`
now pins the real rate, so the next probe that gets this wrong fails a test
instead of writing a milestone.

**A pipe that ate the evidence.** Two long runs printed nothing at all for
twelve minutes, because they were piped through `tail`, which buffers until
the process exits — and both were killed by their timeout first. A background
run that reports progress must not be piped.

**A `pkill` that killed its own replacement.** Documented one milestone
earlier, in §110.1, and repeated anyway: killing the old probe and launching
the new one in a single shell invocation matches the new one's `bash -c`
wrapper too. Writing a hazard down is not the same as not walking into it. The
rule is now the stronger one: kill in one call, launch in the next.

## 112. The beast that was never there (v3.52)

v3.51 built an instrument for playing adventure mode and found nothing. This
is what it found when pointed at the README's own headline promise — *"Every
quest points at something that exists"* — and asked the next question: it
exists, but is it **there**?

Generating every kind of quest across three worlds, every target checked out.
The figure was alive, the site was real, the coordinates were on land. Then
travelling to each one and looking:

| quest | at the place |
|---|---|
| `clear_site` | hostiles waiting, as promised |
| `explore` | arrival registers |
| `slay_beast` | **no quarry** |
| `bounty` | **no quarry** |

**A megabeast had nowhere to live.** `_spawn_megabeast` gave the figure a name,
a species and a prowess score, and no home at all; each year it raided a random
settlement from nowhere in particular. So `_quest_slay_beast` had nothing to
point at, and said *"It is said to lair at ..."* with `rng.choice(lairs)` — the
game told the player where to go and the answer was a coin toss.

Meanwhile `build_lair` put a beast of a **random species** with **no `hf_id`**
in every lair. So there were three halves of a feature — a named beast in the
histories, a lair with an anonymous monster in it, and a quest that named both
— and none of them were joined. `on_kill` matches on `victim.hf_id`, so even
standing over a dead beast nothing could ever count.

The fix joins them, using fields that already existed:

- `_spawn_megabeast` gives the figure a `site_id`, which every
  `HistoricalFigure` has had and which the save already writes. One beast to a
  cave, or the quest naming the place could still send you at the wrong one.
- `sitegen.build_site` places it — in `build_site`, not in a builder, for the
  same reason the residents are named there. **Three** builders make somewhere
  a beast can live: `build_lair`, `build_cave`, and `build_ruin` for the cave
  that fell in since. The first fix touched two of them and the one it missed
  was the one that mattered.
- `_quest_slay_beast` names the beast's own lair.

Everything downstream already worked: the creature is named from its figure in
`Game.enter_world_tile`, `quests.on_kill` matches on `hf_id`, and
`renown.record_kill` writes the death into the histories. Killing the thing now
closes the quest and puts a date on the figure — the beast that has been eating
villages for a century has an end, and the legends say who ended it.

### 112.1. An early return that skipped the funnel

`build_site` is the one funnel — its own comment says so, above the line that
names the locals — but it opened with

```python
if site.is_ruin and site.kind not in ("ruin", "tomb"):
    return build_ruin(lm, world, site, rng)
```

and that `return` skipped the funnel's tail entirely. On one world in four,
the beast's cave had fallen into ruin since it moved in, and that beast alone
came out missing. Every other one was fine, which is exactly the shape of bug
that ships: it is only visible if the test walks *every* beast rather than the
first.

A funnel with an early return above it is not a funnel. The ruin branch now
falls through to the shared tail like everything else.

### 112.2. A guard that a coin toss could pass

The re-break for "the quest names a random cave again" did not fail, because a
cave picked at random is sometimes the right cave. On the single world the test
used, the old rule got lucky. The guard now checks four worlds and fails if any
of them is wrong — the same lesson as §106.1, arrived at from the other
direction: a test on one seed is a test of that seed.

### 112.3. What moving the dice shook out

Giving a beast a lair draws from the world's RNG, so every world after this
change is a different world. Four tests went red and one went quiet, none of
them from the logic:

- **two mount tests** put the horse on the tile east of the player and assumed
  it empty. A wandering troll stood there instead, and `ride_or_dismount`
  found the troll when it went looking for something to get on. The fixture
  now clears the player's neighbours and places the horse on a tile it has
  checked is free.
- **the adventure clock test**, written one milestone ago, shared its hamlet
  with that troll and measured 81 ticks out of 200 — because `player_acts`
  does nothing once the game is over, so a dead player's turns are free. It
  clears the hostiles first and asserts the run has not ended.
- **a residents guard** insisted every creature carrying an `hf_id` was
  civilised or matched its civ's race. A named megabeast is neither: it is
  drawn as its `creature_id`, while `new_figure` left its `race` as the
  "human" it was made with. The guard now knows about monsters and checks the
  stronger thing — that the creature on the map is the species the histories
  name.
- **a kin test skipped itself**, "nobody in this world was slain by anybody",
  and the skip count going from one to two was the only sign. It hunted the
  generated history for a slaying instead of staging one. It stages one now.

Four seed-fragile tests and one silent skip is a fair toll for a worldgen
change, and every one of them was a test that measured the seed rather than
the game. The skip is the one worth watching for: a red test argues, a skipped
test says nothing at all.

## 113. The artifact that was never there (v3.53)

v3.52 fixed one half of the audit and left the other unproven: the probe that
looked for artifacts at a site used `local.items`, which is `None`, so the
reading meant nothing and was recorded as unproven rather than as a finding.
With the right accessor — `game.items_on_ground` — it is a finding. Three
worlds, three sites named by three quests, and **no artifact on the ground or
in anybody's hands** at any of them.

**Nothing had ever placed one.** The word "artifact" does not appear in
`sitegen.py`. `Item.artifact_id` is read for the item's colour, read for its
name, copied by `clone`, written to the save and loaded back from it — and
**set nowhere in the game**. `quests.on_pickup` matches on exactly that field.
So a retrieve-the-artifact quest could be offered, accepted, travelled to, and
finished by nobody.

The rest of the chain was already correct, which is what made it invisible:
`_quest_retrieve` picks a real artifact and names *its own* site, not a random
one — the mistake `_quest_slay_beast` made — so the quest text was true and
only the world was empty.

**`game/artifacts.py`** places them, called from `enter_world_tile` beside
`traps_mod.populate` and for the same stated reason: a floor to lie on is part
of a floor plan, and floor plans are made when the player walks in. An
artifact goes into the hands of its `holder_hf` if that figure is standing
here and on the floor otherwise — so a hydra guarding a treasure is what the
histories said all along, now that v3.52 puts the hydra in its lair.

### 113.1. A cache that hands out seconds

The local map cache holds twenty-four tiles and then evicts the oldest. A site
rebuilt from scratch is rebuilt completely, so without a guard the crown you
are wearing is lying on the floor of the tomb you took it from, as often as you
care to walk back. `populate` skips an artifact the player already carries.

Worth noting what is *not* fixed: taking an artifact does not update the
world's own record of where it is. `art.site_id` and `art.holder_hf` still say
it is in the tomb. Nothing reads them except the placer and the quest
generator, so the only visible consequence is that a second quest may send you
after something already in your pack — which is a smaller and more interesting
problem than the one this fixed, and belongs to whoever wants the histories to
follow the player around.

### 113.2. A guard that could not fail, twice over

The re-break for "a taken artifact is laid out again" did not fail, and the
reason was the test rather than the code. `enter_world_tile` stashes the map it
is leaving into the cache *before* loading the next one, so clearing the cache
and re-entering the tile you are standing on reads back exactly what you asked
it to forget. The test travels a tile away, forgets, and comes back.

That is the fourth guard this session that had to be rewritten because it could
not fail — after the two in v3.51 and the coin-toss one in §112.2. The pattern
in all four is the same: the assertion was true for a reason other than the one
it was written for, and only re-breaking the fix exposed which.

## 114. Who the dragons are (v3.54)

v3.52 gave a named megabeast a lair, pointed the quest at it, and made killing
it write a date into the histories. Surveying the wilderness afterwards showed
the point of all that quietly undone.

**Eight** named megabeasts in the whole world. **Fifteen** nameless ones inside
forty-four tiles of the player's own doorstep — three dragons, five bronze
colossi, and the rest ettins, cyclopes and ogres. A quest to find and kill
*Tzamorg Zhatuth the Devourer* is worth rather less when you passed three
unnamed dragons on the way to the tavern that offered it.

`Game.spawn_wildlife` asked `creature_data.spawnable` for anything up to tier
five on a savage tile, with **no flags excluded at all**. The fortress has
excluded them since it had wildlife — *"wildlife, not enemies: a siege arrives
as a siege, and the walking dead are not something you hunt for the hides"* —
and adventure mode had never been told.

The fix is the fortress's own rule, said once more where the other half of the
game can hear it. Fifteen becomes zero, and the wild is no poorer for it:
thirty-eight species still walk it — wolves, trolls, night trolls, werewolves,
goblins, bandits — and one tile in thirty-five comes out empty, which was true
before as well.

**A rule in two places that could not see each other.** The fortress kept its
exclusions inline in the call and adventure mode kept none, which is a
disagreement no test could notice. Both are named constants now —
`animals.WILD_NEVER` and `Game.WILD_NEVER` — and a guard fails if either
forgets the megabeast flags. Naming a rule is not decoration when the same
rule has to hold in two programs that share a world.

### 114.1. Moving the dice, again

Excluding four species from a spawn table changes every world after it, and it
broke two of the artifact tests written one milestone earlier: on the new dice
the artifact on seed `art1` is in a monster's claws rather than on the tomb
floor, and both tests had assumed the floor.

The fix is the interesting part. They do not assert the floor now, nor pick a
luckier seed: they take the thing however it is being kept — walk to it if it
is loose, kill the holder if it is not, which is what a player does about a
hydra sitting on a crown. The test got broader by being made robust, and it
now covers the holder path that v3.53 wrote and nothing exercised.

That is the third worldgen change this session to take out a handful of tests
(§112.3, and the corridor's five in §106.1). The toll is always the same kind:
a test that measured the seed rather than the game.

## 115. The necromancer who never built a tower (v3.55)

The histories tell this story every twenty years or so:

> *Kelric Marsh learned the secrets of life and death and fled into the
> wilderness.*

and the README repeats it — *"necromancers flee into the wilderness and take up
residence in towers"*. Going to look: **twenty-six named necromancers across
three worlds, and one tower between them.** Every necromancer's `site_id` still
pointed at the city it is on record as having fled. Two of the three worlds had
no tower standing at all.

Two independent generators, neither aware of the other. `place_lairs_and_ruins`
scatters sites from a seventeen-entry weight list with `"tower"` appearing once,
and then downgrades it to a ruin unless the tile's evil is over 55 — so a world
gets none or one. `history.py` creates a necromancer at five percent a year, so
a world gets six to eleven. The code that was supposed to join them was three
lines that did the wrong thing quietly:

```python
towers = [s for s in world.sites if s.kind == "tower"]
if towers:
    tower = rng.choice(towers)
    tower.owner_hf = fig.id
```

Pick any tower, claimed or not, and stamp your id over whoever was there. Never
set `fig.site_id`, so the figure goes on living in the town it fled. With one
tower in a world and eleven necromancers, ten of them overwrote the eleventh and
none of them lived anywhere.

### 115.1. What that cost

Not flavour. `build_tower` is the **only** thing in the game that creates a
creature whose profession is `necromancer`, and `Game._give_books` gives a
`necromancer` a slab a hundred percent of the time. The help screen:

> *A slab — in a tomb, or at the top of a necromancer's tower — is the secret
> of raising the dead. Read it and press Z.*

So the whole night half of the game — `night.raise_dead`, `books._learn_secret`,
the player becoming a necromancer, the Z key — hung off a site kind that two
worlds in three did not contain. The machinery was written, documented and
tested, and the tests all built their own necromancer to test it against. The
only other slab-bearer is a tomb lord who carries one three times in five.

That is the shape of it: **every piece tested, the world never asked.**

### 115.2. Raising the tower when the story says so

`_tower_for` claims a free tower if the world scattered one, and otherwise
raises it: `_dark_spot` takes the empty land tile with the highest evil out of
the darkest tenth, and the site is stamped onto its world tile the way
`place_lairs_and_ruins` stamps its own — `site_id` and `feature` — because a
site the tile does not know about is a name in the legends with nowhere to
travel to. Wealth and buildings match a scattered tower, so the legends screen
reads the same either way.

One necromancer to a tower. `build_tower` puts a single `site.owner_hf` on the
map, so two owners means the one you were sent after is not the one standing
there — hence the `owner_hf is None` filter, and `fig.site_id = tower.id` so
the figure and the site agree. Them disagreeing is what made this invisible.

Measured after, on the same four seeds: **six to twelve necromancers, six to
twelve towers, one each, every `site_id` matching its owner.** Walking into one:
the named necromancer at the top of five floors with eight to twelve undead
below him, carrying the slab.

One more piece of the same defect lives in the interface. The travel screen
is where you decide whether to walk somewhere, and it showed a site's name,
kind and population and nothing about who is in it — which is the whole of the
decision when the site is a tower. It says *held by Ustgath the Foul* now, the
same line the legends screen has always had. A fact the game knows and never
puts on the screen you need it on is not a fact the player has.

### 115.3. Who is standing in a tower nobody has cleared

`build_tower` used to place its necromancer unconditionally, with
`hf_id=site.owner_hf` — usually `None`. Now that towers have named owners, that
matters in both directions:

- **The owner is dead.** You killed him, and the legends recorded it. He does
  not come back the next time the map is built. A tower whose necromancer was
  killed three hundred years ago is an empty tower with its dead still walking
  in it.
- **Nobody owns it.** A scattered tower the histories never claimed still gets
  a necromancer — that is what a tower *is* — it just has no name to put to
  him.

The first draft of the guard had only the first half (`owner is not None and
owner.alive(...)`), which silently emptied every unclaimed tower. Necromancers
outnumber scattered towers almost always, so no world in the sample had one,
and no test would have caught it. It came out of asking what the condition says
rather than what the measurement showed.

### 115.4. Guards that can fail

Fifteen, and the re-break pass ran once per fix rather than once for the
milestone:

| broken | guards that fired |
|---|---|
| `_tower_for` → the old three lines | 14 of 14 |
| the dead-owner check dropped | `..._is_dead_holds_only_its_dead` |
| the unclaimed-tower half dropped | `..._unclaimed_tower_still_has_its_necromancer` |
| the world-tile stamp dropped | 6, incl. `..._stands_where_the_map_says` |
| the travel screen's owner line | `test_travel_screen_says_who_holds_a_place` |
| `Water._push` deleted (§115.5) | `..._breached_aquifer_does_not_stop_at_a_puddle` |

The first pass caught eleven and three passed regardless: two looped over
`if site.owner_hf is None: continue` and skipped every tower in a world that no
longer had any, and one iterated `towers[:3]` over an empty list. All three
were vacuously green — the third guard-that-could-not-fail this session
(§112.2, §113.2), and the same fix each time: a guard that walks a collection
has to assert the collection was not empty.

The end-to-end one generates a world nobody arranged, finds a tower on the
map, walks in, BFS-checks from where you arrive to where he stands — five
floors up, and a necromancer on a floor with no stair is a necromancer nobody
meets — takes the slab off him and reads it. That is the promise the help
screen makes, asked of the game rather than of a fixture.

### 115.5. Three tests that were not running

Moving the dice again (§112.3, §114.1), and this time the toll was not red
tests but the skip count: **1 became 2**, which is the only visible trace a
skipped test leaves. Pulling that thread took the suite from two conditional
skips to none, and turned up a shipped fix that nothing had ever tested.

`test_fire_does_not_cross_bare_ground` laid two trees six tiles apart starting
from wherever the player happened to spawn, and skipped if there was not six
tiles of clear ground running east. Raising towers moved every start location
in the game, and one of them landed somewhere with no room. Rebuilt to *make*
the row it needs, which is the same lesson §112.3 and §114.1 both ended on.

Chasing that turned up the other one, which is worse. This is the whole of
`test_a_deep_cell_is_steadier_than_the_surface` as it stood:

```python
surf = lm.surface_z(p.x, p.y)
if surf - 20 < 0:
    self.skipTest("map is too shallow")
```

A local map spans `-Z_BELOW` to `Z_ABOVE`, which is eleven levels; a surface
column sits near zero. `surf - 20` is **never** ≥ 0. The test had not run once
since it was written, and the suite reported it as a pass-with-one-skip every
time. `heat.CAVE_DEPTH` is 6, which the map does have room for. It now finds a
column deep enough, checks the rock is at `CAVE_TEMP`, and then actually
measures the word in its own name: half a year passes, the surface notices and
the cave does not.

The fire test needed a second look as well. It only asked whether the far
tree survived, which a fire that crosses three tiles of rock and then gutters
out passes: made to fail under a re-break (`TILE_FUEL["floor"] = 90`), it
didn't. It asks about the ground in between now.

The fortress suite had one of its own, and it was hiding the most. Two aquifer
tests began `if not fort.aquifer: self.skipTest(...)` — `_lay_aquifer` is a
coin toss weighted by rainfall, so a seed has one about half the time. Trying
eight embarks instead of one turns that into a pass or a loud failure, and the
one that had been skipping failed immediately.

It was breaching the aquifer by opening **one cell in the middle of the wet
layer**, with solid rock on all six sides but the one it came in by, and then
asserting the water in it kept rising. That is a bucket, not a breach: it fills
to seven and there is nowhere for the next unit to go. The test now digs a room
under the wet layer first, which is the only breach that means anything.

And under *that* was a fix with no guard at all. `Water._push` is v2.5's answer
to a leak that levels into a shallow staircase and freezes (§54) — and deleting
the call outright left all twenty water tests green. Measured on the room:

| | min depth | median | total |
|---|---|---|---|
| with `_push` | 6 | 6 | 1490 |
| without | 1 | 4 | 1276 |

An inch of water at the far wall, which is precisely the shape `_push` exists
to beat. The test asserts the filled room now, and fails without it.

**A red test argues; a skipped one says nothing.** Skips this suite takes are
conditional on the seed, so the count moves whenever worldgen does — which
makes "the skip count changed" a signal worth reading every time, and the same
signal that caught `TestKin` going quiet in §112.3.

### 115.6. A restore that restored nothing

The re-break pass for the temperature fix reported the guard failing *after*
the fix was put back, which is the one result that means the method itself is
broken. `git diff` on the file was empty and the source read correctly.

`min(1.0, ...)` and `min(0.90, ...)` are the same number of bytes. Python
invalidates a `.pyc` on the source's size and its mtime **in whole seconds**,
so a break-and-restore that changes no bytes and lands inside one second is
invisible to it: the interpreter went on running the broken bytecode from
cache. Every earlier re-break this session changed the file length, which is
the only reason none of them were poisoned the same way.

`PYTHONDONTWRITEBYTECODE=1` on every command in a re-break pass, and the third
entry in §110.1's list of ways to lose your own work.

## 116. The ledger (v3.56)

The histories know where every artifact is: which site it lies in, and whose
hands it is in there. `_quest_retrieve` reads exactly that —

> *The Bridge of the Tower was lost to us. It lies at Wall Moon, a tomb. Bring
> it back and you will be well paid.*

— and v3.53 finally put the thing on the floor for you to find. **Nothing ever
told the histories you had picked it up.** `art.site_id` and `art.holder_hf`
went on naming the tomb and the dead king who was buried with it.

So the generator offers it again. Measured on seed `ledger`: take the crown,
ask around, and twelve offers in a hundred and twenty are to go and fetch the
crown you are wearing. Accept one and it reads `state=active, progress=0/1`
for the rest of the game — the pickup that would complete it already happened,
and there is nothing at the site to happen again.

That is the README's one flat promise about quests failing in the quietest
possible way: *"Every quest points at something that exists."* It does. It is
in your pack.

### 116.1. The record follows the object

`game/ledger.py` is one idea in two directions. `took` when something reaches
the player's hands, `gave_up` when it leaves them — dropped, sold, or fallen
with the body — and `Game.player_took` / `Game.player_gave_up` are the funnels
the rest of the game calls.

That funnel is the point. Three places already knew an item had reached the
player and each called `quests.on_pickup` on its own: `pick_up`, `pick_up_all`,
and `trade.buy`. A fourth thing now has to happen at the same moment, and the
number of ways to acquire something only ever goes up, so the three call one
method and the method knows both halves.

The rules are small:

| where it is | `holder_hf` | `site_id` | `lost` |
|---|---|---|---|
| in the player's pack | the player's own figure | `None` | false |
| dropped or sold at a site | whoever took it, or nobody | that site | false |
| dropped in open country | nobody | `None` | **true** |

An artifact on a wandering adventurer is at no site, and that is what takes it
out of the quest pool: `_quest_retrieve` asks for artifacts with somewhere to
send a hero, and there is no longer anywhere to send them. Put it down in a
town and it is offered again — twelve in a hundred and twenty, the same as
before you touched it. The record tracks the object rather than remembering
one moment of it.

The player's side of it costs nothing extra: `renown.figure(game)` has made
the adventurer a historical figure on demand since v3.30, so *Held by Lorn
Marsh* on the artifact's legends page is the same mechanism that writes your
kills into the histories. You take a crown and the world's record of that
crown names you.

### 116.2. Belt and braces for a save that already lies

A game saved before any of this carries `site_id` pointing at the tomb with
the crown already in the pack, and nothing on load repairs it. So
`_quest_retrieve` also refuses to name an artifact the player is carrying,
whatever the record says. Two mechanisms, one outcome — and the guard for the
second one has to construct the stale state by hand, because the first one
makes it unreachable in a new game.

### 116.3. A page that contradicts itself

The other half of a ledger is the reading of it. Two screens printed a holder
in the present tense with no question asked:

- `legends.site_lines` — kill a tower's necromancer and the page said *Held by
  Skarul the Pitiless* three lines above the event recording his death. Unlike
  a town's ruler, which `livingworld._leaders` replaces within the season,
  `owner_hf` is never reassigned, so that one stood for the rest of the game.
- `legends.artifact_lines` — the same, for whoever the histories last had
  holding it.
- `conversation.say("ask_site")` — a townsman answering *"%s rules here"* with
  the name of somebody you killed on the way in.

Who held a place is a historical fact and belongs on the page. Only the tense
was wrong: *Held by Skarul the Pitiless until 146.* The conversation is the
one case where saying nothing is right — the seat is genuinely empty until the
season turns.

Note what was **not** done. Clearing `owner_hf` on death would have been the
obvious fix and it would have quietly undone v3.55: `build_tower` gives an
unclaimed tower a nameless necromancer, so erasing the owner would repopulate
every tower the player had just cleared. The data is right. The readers were
asking it the wrong question.

### 116.4. What was measured and left alone

Three other seats were checked and are working:

- **A civilization's leader** self-heals. `livingworld._leaders` reappoints
  within one season of the death, and killing a capital's ruler is repaired by
  the same call that sets the capital's `ruler_hf`.
- **A beast's lair.** v3.52's `lair_beast` asks whether the figure is alive, so
  a slain megabeast does not respawn in its cave.
- **Vampires and werewolves** are reachable: three to six carriers inside a
  seven-by-seven block of world tiles around the start, on each of three
  worlds. The night machinery has something to bite you.

And two dead entries turned up in the sweep that are worth naming rather than
fixing: `"curse"` and `"founded_civ"` are declared in `EVENT_KINDS` and named
in `artforms._bind_history`'s want-lists, and nothing anywhere records either
one. Both want-lists have live kinds beside them, so no art form ends up
about nothing — dead weight, not a defect.

### 116.5. Guards that can fail

Eleven, six re-breaks:

| broken | guards that fired |
|---|---|
| `ledger.took` no-ops | 3, incl. `..._taking_an_artifact_moves_the_record` |
| `ledger.gave_up` no-ops | 3, incl. `..._killing_the_holder_leaves_it_where_the_body_is` |
| `kill_creature` stops telling the ledger | `..._killing_the_holder_leaves_it...` |
| `_quest_retrieve` stops asking what you carry | `..._an_old_save_is_not_sent_after_its_own_pack` |
| `legends` drops both alive checks | both page guards |
| `conversation` drops its alive check | `..._nobody_says_a_dead_ruler_rules_here` |

`test_nobody_sends_you_after_what_you_are_carrying` deliberately survives the
first break: the quest filter catches that case on its own. It measures the
outcome a player would notice rather than which of the two mechanisms
delivered it, which is what it is for; the mechanism has its own guard beside
it.

## 117. The empty deep (v3.57)

A local map is eleven z-levels and six of them are underground. The README
sells them:

> *cave systems carved by cellular automata below, ore and gem veins in the
> rock* … *light a torch before you go underground and douse it when you come
> back out.*

Sixteen tiles around an adventurer's start, counting what stands where:

| | creatures | kinds |
|---|---|---|
| above the surface | 358 | 34 |
| below it (≈92,000 walkable cells) | **0** | **0** |

`creature_data.spawnable` has taken an `underground` flag since it was
written. Eleven species carry `SUBTERRANEAN`. The one caller in the game is
`Game.spawn_wildlife`, and it read:

```python
underground = False
...
options = creature_data.spawnable(tile.biome, underground=underground, ...)
```

A local assigned `False` on one line and passed to the parameter on the next,
never varied. **`spawnable(underground=True)` had never been called by
anything.** The torch lights an empty room.

### 117.1. Four species that had never existed

Being unreachable is not the same as being unwritten. Of the eleven,
`giant_rat`, `bat`, `giant_bat` and `troll` list surface biomes too and turn
up on the grass. Four list `UNDERGROUND` and nothing else — the cave spider,
the giant cave spider, the giant cave swallow and the gremlin — so no world
had ever contained one. `game/venom.py` carries an entry for
`giant_cave_spider`: a venom table keyed on a creature that could not be met.

After: **74 creatures of 8 kinds** under the same sixteen tiles, all four of
them among the eight.

### 117.2. Two halves, and the second one is the placement

Selecting cave species is half of it. The placement loop ended:

```python
z = self.local.surface_z(x, y)
if not self.is_passable(x, y, z, c):
    x, y, z = ox, oy, oz
```

Every member of every group was walked up to the surface of whatever column
the jitter landed it on, and only fell back to where it was placed if that
surface happened to be blocked. Fixing the species selection alone yields
**one** creature underground across sixteen tiles instead of seventy-four, and
a guard that only asks for "more than none" calls that a pass — which is
exactly what the first draft of these guards did.

`LocalMap.random_cave` is the funnel: a walkable, dry cell strictly below its
column's surface. `random_open` prefers the surface and can only be pinned to
one z at a time, so nothing could ask the question before.

### 117.3. The budget, not a bigger budget

The deep is a third of the wildlife budget rather than an addition to it
(`CAVE_SHARE`). Above ground goes 358 → 293 and the total moves 358 → 367,
which is group-size noise. A turn stays at 2.4 ms with a map's worth of
creatures on it either way, and the caverns are meant to feel emptier than a
meadow — not empty.

The dark suits them. `entity.py` has given `SUBTERRANEAN` and `NOCTURNAL`
creatures night vision since it was written, and this is the first thing in
the game that puts one where the light is not.

### 117.4. The rest of the bestiary

The audit that opened this counted **eleven of eighty creature definitions
that appear in no world at all** — every site of two worlds, an eighty-one
tile block of wilderness, and every historical figure. Down to two, and the
other nine were reachable or made reachable:

- **The four cave species**, above.
- **`axedwarf`.** `build_fortress` read `"hammerdwarf" if race == "dwarf" else
  "guard"`. Both dwarven soldiers have been in the table since it was written
  — six levels of axe against six of hammer — and one of them was named in the
  one line that could have produced it. It picks between them now.
- **`alligator`, `duck`, `hippopotamus`, `pike`, `carp`** are river species,
  and a world puts a river on 1% of its land. Entering 41 river tiles across
  two worlds finds all five, 7 to 68 of each. Rare, not absent — the earlier
  count missed them because the block it walked had no river in it.
- **`cyclops`** is in the megabeast pool at the same frequency as the hydra
  and the bronze colossus, and two worlds did not roll one.

What is left is honest:

- **`demon`** exists only when a fortress breaches the adamantine
  (`spawn_demons`), which is where it belongs. An adventurer walking into a
  dark fortress does not meet one, and that is a design choice rather than a
  gap.
- **`peasant`** is a fossil. It is a *human* creature definition, and
  `build_town` has long since settled on `_pop(race, …, profession="peasant")`
  — a townsman is a person of the town's race who farms, not a separate
  species. Wiring the definition in would put humans in dwarven hamlets.
  Measured dead, deliberately left dead.

`Game.spawn_wildlife(n=…)` was also dead — no caller anywhere passes it. It is
the total budget now, split inside, so the parameter means one number a caller
would actually want.

### 117.5. Guards that can fail

Eight, five re-breaks:

| broken | guards that fired |
|---|---|
| no cave pass (`deep = 0`) | all 5 cave guards |
| the group walked up to `surface_z` | 2, incl. `..._what_is_down_there_belongs_down_there` |
| `random_cave` always gives up | 6 |
| `random_cave` allows the surface | 3 |
| `build_fortress` names one dwarf | `test_a_dwarven_keep_fields_both` |

The second row is the one worth keeping. The first draft asserted
`len(below) > 0`, which one stray gremlin satisfies, so the break that costs
you 73 of 74 cave dwellers passed it clean. The guard asks for at least one
per tile walked now, and separately that cave species are not standing about
in meadows.

### 117.6. And the skip count moved again

Populating the caves draws from the game's dice, which shifts every adventure
fixture after it, and the sweep came back **954 passed, one skipped** where the
last two milestones had none. Reading it (§115.5) found
`test_a_dart_that_cannot_get_through_does_not_envenom`:

```python
landed = self.traps._hurt(self.game, p, "dart")
if landed:
    self.skipTest("the dart got through this time")
self.assertFalse(p.venom)
```

Two things wrong, and the skip was the smaller one. `traps._hurt` **does not
apply venom** — `spring` does, on the line after it, gated on whether the
strike landed. So on the runs the test did not skip, it asserted that a
function which never touches venom had not applied any. Deleting the gate it
exists to guard (`if defn.get("venom") and landed:` → `if defn.get("venom"):`)
left it green.

It springs a real trap forty times now, counts wounds before and after to see
whether the dart got through, and asserts the invariant on the rounds where it
did not. The re-break fails it. `_trap`'s own *"no walkable ground beside the
player"* skip is gone the same way: it digs a floor tile if the six offsets it
tries are all rock.

That is two guards-that-could-not-fail in one milestone — the `len(below) > 0`
one I wrote and this one I inherited — and both were found by the same
question: *break the thing on purpose, and see whether anything notices.*

## 118. The jeweller (v3.58)

Over five rows of `data/items.py` sits a comment stating their own design:

```python
# Jewellery. Worth many times the stone it is cut from, which is the point.
    ("crown",    "crown",    "crowns",    400, 300),
    ("amulet",   "amulet",   "amulets",   120, 120),
    ("ring",     "ring",     "rings",      40,  90),
    ("earring",  "earring",  "earrings",   30,  70),
    ("bracelet", "bracelet", "bracelets",  90, 100),
```

Nothing cut a stone. Nothing set one.

A gem vein is one roll in five of every vein `_add_ore` lays down — twenty to
fifty-eight cells of it on an embark — and mining one yields a `rough_gem`
worth thirty. **No recipe anywhere could consume a rough gem or a cut one.**
Two of the five pieces could be produced by nothing at all in either half of
the game; the other three only as a strange mood's output, at about one mood a
season, from the craftsdwarf's workshop, **which had no recipe for any of
them**.

So the whole of it was a value written next to a name.

### 118.1. What the audit was actually looking for

This came out of asking the reachability question of the data tables rather
than the bestiary (§117.4). Item ids named nowhere in the code outside their
own table: `bin`, `bracelet`, `earring`, `quiver`, `shovel`. Only five of a
hundred and seventeen — but pulling on two of them found the trade they
belonged to, and the audit that mattered was the next one:

> Which items can no recipe, anywhere, produce?

Thirty-seven, and most of them are gathered rather than made (a log, an ore, a
boulder, a corpse). The ones that were neither gathered nor craftable were the
five pieces and the gems they are made of.

### 118.2. A workshop, a labor, a skill, six recipes

- **`jeweler`** in `buildings.KINDS` and `WORKSHOP_KINDS`, so the build menu
  offers it where it offers the rest.
- **`gemcutting`** as a labor under Crafts, on the craftsdwarf's profession so
  the embark can work it on day one, and as a skill in its own right.
  Stonecrafting is not gem cutting, and a labor whose display name lies about
  what it does is worse than a new row.
- **Six recipes.** Cutting is one trade: a stone worth thirty becomes a gem
  worth a hundred, which is the comment's own promise, executed. Setting is
  another: rough stone plus a metal bar into each of the five pieces.

Every piece is set from the **rough** stone, not a cut one — and that is a
correction the first draft needed. A ring set from a cut gem is worth less
than the gem was:

| | in | out (silver) |
|---|---|---|
| `cut_gem` | 157 | 525 |
| `set_ring` from a *cut* gem | 605 | 360 |
| `set_ring` from a rough one | 237 | 360 |

**A recipe nobody would ever queue is a recipe that does not exist.** The guard
that checks it walks every jeweller recipe and fails if any of them destroys
value in silver — in copper they lose, and a fortress is welcome to make that
mistake.

### 118.3. A promise the workshop could not keep

`MOOD_OUTPUT["craftsdwarf"]` read `("gem", "amulet", "ring", "crown")`. Three
of those four were things that workshop had no recipe for, and a mood is a
once-a-season event a player remembers. It now reads `("gem", "mechanism",
"drum", "flute")` — the things a craftsdwarf actually makes — and the
jeweller's line holds all five pieces.

The guard asks the question generally: for every entry in `MOOD_OUTPUT`, is
each output in `recipes_for(that workshop)`? Written the loose way first —
"can *anything* make it" — it passed with the old table in place, because the
jeweller could now make the crown the craftsdwarf was promising.

### 118.4. An order at the wrong bench

Re-breaking by moving the jeweller's recipes onto the craftsdwarf left the
fortress tests green: `_scan_orders` looked the recipe up in the global
`RECIPES` table and never asked whether it belonged to the workshop it was
queued at. Nothing player-facing — the build menu only offers
`recipes_for(kind)` — but it is how a save from another version quietly gets a
jeweller brewing ale. One clause, and the re-break now takes five guards with
it instead of two.

### 118.5. The other half of the game

The five pieces are one set of definitions shared by both modes, so an
adventurer could no more find a ring than a fortress could make one. They are
in `_LOOT_TABLE["treasure"]` beside the gems now: a ring in a tomb and a ring
on a jeweller's bench are the same row of the table, and before this neither
existed.

### 118.6. Guards that can fail

Nine, six re-breaks:

| broken | guards that fired |
|---|---|
| recipes moved off the jeweller | 5 |
| `jeweler` out of `WORKSHOP_KINDS` | 5 |
| the old `MOOD_OUTPUT` line | `..._mood_only_promises_what_its_workshop_can_make` |
| the `gemcutting` labor deleted | `..._labor_and_the_skill_both_exist` |
| jewellery out of the loot table | `..._treasure_table_has_something_to_find` |

Two of them had to be tightened before they could fail: the value guard
iterated `recipes_for("jeweler")` without asking whether it was empty, and the
mood guard asked the loose question above. Both are the same mistake as
§117.5's `len(below) > 0` — a guard that walks a collection has to say how big
it expects the collection to be.

## 119. Playing the fortress (v3.59)

`tools/play` was v3.51's answer to a whole half of the game that nothing ever
played: `smoke` proves the screens fit together, `fuzz` presses keys at
random, and neither of them survives a night in the open. It found three
defects in an afternoon.

The fortress had the same hole and kept it for eight versions. `tools/fort`
is its driver: it designates a stairway down and a floor of rooms, marks the
trees and the shrubs, puts up a still and a farm and beds for everybody,
queues standing orders, and then watches the season turn.

### 119.1. What it is allowed to conclude

The first draft asserted that the fortress should be alive at the end of the
year, and that is the wrong assertion for this tool. Whether seven dwarves
survive a winter depends on how well the *script* plays -- and the script is a
hundred lines of my own judgement about where to put a farm. A driver that
plays badly must not be able to report a defect in the game.

So the invariants are about the **job board**, which the driver does control
and which is the thing every one of its scripted actions feeds: painted work
that can be reached has to get done. A thousand trees marked for felling and
none felled is a defect whoever wrote the script. Seven dwarves starving on an
embark whose surface is bare rock is a bad script.

### 119.2. Four things it turned up

None of them is the dramatic one I first thought I had. The measurement that
opened this looked like *seven dwarves stand idle beside a full job board and
starve*, and re-measuring took it apart: the shaft had run into an aquifer and
flooded, which is what an aquifer is for; the remaining seven hundred and
ninety-one trees were across the water; and the starvation was the driver
never managing to place a farm. **The story did not survive the second look,
and the fixes it led to are worth having anyway.**

| | what was wrong |
|---|---|
| `_scan_designations` | read `fort.unreachable` with `in`. The value is *the tick a cell may be retried*, and testing membership meant a cell set aside once stayed set aside until something called `dig_out` -- which is the one thing a fortress that cannot dig will not do. A plain bug: the map was being used as a set. |
| `_scan_designations` | walked the dict from the top on every scan, so the first `MAX_DIG_JOBS` painted cells could hold the whole budget for ever. The first thing a player paints is the room they have not reached yet. A cursor now rotates through them. |
| `_claim_job` | sliced twelve candidates off the board and *then* skipped the ones it already knew were unreachable, so a dwarf could look at twelve known-dead jobs and find nothing with work sitting thirteenth. Filtered before the window now. |
| `_claim_job` | left an unreachable designation job posted. `_scan_designations` will not replace a job that is still on the board, so it sat holding one of sixty slots until the retry fell due. It comes off; the designation stays painted and the memory brings it back. |

Measured end to end on the driver's first embark, the last of those is the
only one that moves the number: **415 designated cells worked against 384**.
The other three are correctness rather than throughput, and each has a guard
that fails without it.

### 119.3. What the first draft of the script was measuring

The catastrophe the driver first reported -- seven dead in a fortnight, not one
wall dug -- was mostly the script. It marked **every tree on the map**: one
thousand one hundred and eighty-four chop designations, against sixty job
slots, on an embark whose surface is bare rock so the farm it tried to place
never went down. A player marks the stand within walking distance and farms
the soil. With sixty trees and twenty shrubs marked and a farm on soil, the
same embark comes out: **every painted cell worked inside five days, seven
alive of seven, a farm and a still standing.**

That is the second half of §119.1 and worth saying twice. A driver's report is
only as good as the play behind it, so its invariants have to be things that
hold however badly it plays.

One thing did survive the rewrite, and it is a measurement rather than a fix:
seven days of the same script costs **20 seconds on seed `f1`, 19 on `fort`,
and 430 on `f2`.** A twenty-one-fold spread for the same week of simulation.
§110's note on `_claim_job` describes the shape of it -- every dwarf inside a
full-budget A* that cannot succeed -- and one embark in three still finds a
way there. That is somebody's next milestone.

### 119.4. Guards that can fail

Five, four re-breaks, one guard each:

| broken | guard |
|---|---|
| membership instead of expiry | `..._set_aside_is_tried_again_when_its_time_is_up` |
| scan from the top every time | `..._does_not_start_from_the_top_every_time` |
| filter inside the twelve-window | `..._looks_past_the_ones_it_knows_it_cannot_reach` |
| leave the unreachable job posted | `..._nobody_can_reach_comes_off_the_board` |

The fifth pins the other half of the retry: a cell whose time is *not* up must
stay set aside, and one set-aside cell must not stop the scan.

All four are built rather than found -- a wall the map happens to contain, a
cell with no work position at all -- because a job-board test that hunts the
seed for the state it needs is a job-board test that skips (§115.5).

## 120. What searching costs (v3.60)

§119 ended with a number handed forward: seven days of the same script cost
twenty seconds on one embark and four hundred and thirty on another. This is
what is under it, and — being honest about where this one got to — it is a
measurement and a guard rather than a fix.

`tools/fort` now counts what the pathfinder was asked over a played day:

| embark | found | nodes each | failed | nodes each | total |
|---|---|---|---|---|---|
| `f1`   |  180 |  94 |     0 |     — |     16,980 |
| `fort` |  117 |  25 |    21 | 3,596 |     78,532 |
| `f2`   |  136 |  28 | **3,066** | **4,045** | **12,406,098** |

**Seven hundred and thirty times the work for the same simulated day, and
ninety-nine point four percent of it spent proving there is no way there.**

The asymmetry is the whole of it. A* finds a route by walking towards the
goal, so a search that succeeds is over in a couple of dozen nodes. A search
that *fails* has to expand the entire component the dwarf is standing in
before it can say no — four thousand and forty-five nodes, every time, because
that is the size of the fortress on that embark. The price of "no" is the
size of the map, and `_claim_job` asks it once per candidate job per dwarf per
step.

Wall clock is not quoted as a result anywhere here. On this box it moves by a
factor of three with whatever else is running, which is enough to have made
three of the attempts below look better or worse than they were. Node counts
do not move at all.

### 120.1. Seven attempts, and why each one is not in the tree

| attempt | `f1` | `f2` | `fort` |
|---|---|---|---|
| eager flood fill, one component per dwarf | **283s** | 23s | — |
| fill invalidated on the deep-water signature | slow | — | — |
| A* budget scaled by distance to the goal | 25s | 64s | 3.4s |
| fill drawn only after 8 failures, redrawn every 600 ticks | 3.5s | 95s | **16s** |
| the same, redrawn every 2400 ticks | 3.4s | 83s | **7.1s** |
| at most two failed searches per dwarf per turn | 3.4s | 257s | 4.3s |
| `RETRY_DELAY` from four hours to two days | 3.4s | 273s | 4.3s |

(baseline: 3.3s, 300s, 3.4s)

Each one is a real idea and each one has a reason it does not ship:

- **The flood fill is right and its cost is wrong.** One fill answers "can
  anybody standing here reach there" for every cell at once, which is exactly
  the question A* is being made to answer the expensive way. But the fill
  costs the size of the component too — and on an open embark like `f1` the
  component is thirty-five thousand cells, redrawn every time the water
  crosses the wading line, which it does a hundred and fifty times a day. It
  is ruinous precisely where it is not needed: `f1` never runs a failing
  search at all.
- **Capping the search by distance** refuses long routes that do exist. `f1`
  went from zero failures to enough of them to be seven times slower.
- **Capping failures per turn** barely moved `f2`, because its failures are
  spread thinly across steps rather than bunched in one.
- **Waiting longer before a retry** did nothing, and the measurement says why:
  fifty-nine cells were set aside on `f2` over a whole day. The three thousand
  failures are three thousand *different* cells — the round-robin scanner of
  §119.2 walking the designation set — so a memory keyed on the cell has
  almost nothing to remember.

The shape of the real fix is visible from that last line: the question is not
"has this cell failed before" but "is this cell in a part of the map anybody
can get to", and the answer wants to be computed once for the map rather than
once per cell. The flood fill is that answer; what it needs is to be
maintained incrementally as the water moves rather than thrown away, and that
is a bigger piece of work than a milestone that started out measuring
something else.

### 120.2. What is in the tree

The measurement, made reproducible. `tools/fort` reports `found`, `failed`,
`nodes_per_success`, `nodes_per_failure` and `nodes_total` for every run, so
the next attempt starts from the table above rather than from a stopwatch.

And a guard that pins the asymmetry itself: a search to an adjacent cell
against a search into sealed rock, on the same embark, asserting the second
costs at least twenty times the first. If a future change makes failure cheap,
that test fails and the table in this section is what needs rewriting.

**A milestone that ends in a measurement is not a milestone that failed.** The
thing that was unknown at the start of it — *why* one embark costs ninety
times another — is a table now, and the seven approaches that do not work are
written down so nobody spends another afternoon on them.

## 121. Drawing the map (v3.61)

§120 measured the thing and could not fix it. This is the fix, and it is the
idea that section ended on: the question `_claim_job` asks is *"is this work
somewhere I can get to"*, and A* answers it by expanding the whole component
and then saying no. One flood fill answers it for every cell at once, and
everybody standing in the component shares the answer.

Seven approaches were tried and measured in §120.1 and the flood fill was the
best of them and still did not ship, because it cost more than it saved on an
ordinary embark. What makes it work is knowing **when not to draw one**, and
the three conditions came out of counting rather than taste.

### 121.1. Counting the fill as well as the searches

The first version looked like a nine-fold win and was not one: the counter in
`tools/fort` wraps `astar`, and a fill is not an A*. Moving work somewhere
nobody is measuring is not a saving. `Fortress.reach_from` counts its own
fills and the cells they walk, `tools/fort` reports `fills`, `fill_cells` and
`nodes_and_fills`, and every number below is the honest total.

With the fill counted, the first version came out **three times worse** on the
embark that never fails a search at all, because one stray failure drew a map
of thirty-five thousand cells.

### 121.2. Three conditions, each from a measurement

A fill costs the size of the component. So does the failure that asks for one.
It is therefore only worth drawing when it will answer *more than one further
question*, and the three conditions are three ways of asking that:

- **The failure has to have cost something.** `path_to` returns False without
  searching at all when the goal has nowhere to stand beside it — sealed rock.
  Drawing a map to answer a free question is how the embark with zero failed
  searches ended up paying for thirty-five thousand cells. Checked by asking
  `work_positions` first.
- **The failures have to come in a run.** An ordinary fortress fails twenty
  searches a day and never twice in a turn; measured, that was nineteen fills
  preventing nothing. The second failure in a turn draws the map, the first
  does not.
- **There has to be board left to answer.** A fill drawn on the last candidate
  of a turn is pure cost.

And the map is thrown away by `dig_out`, and by the water **receding** but not
by it rising. That asymmetry is exact rather than a guess: rising water can
only close a way through, and a map that says reachable when it is not just
hands the question back to A*, which answers it correctly and pays once.
Receding water opens one, and a map that says unreachable when it is not would
have a dwarf refuse work it could walk to.

### 121.3. What it comes to

One played day, every cost counted:

| embark | before | after | fills | failed searches |
|---|---|---|---|---|
| `f1`   |     16,980 |     16,980 |  0 |     0 → 0 |
| `fort` |     78,532 |     78,532 |  0 |   21 → 21 |
| `f2`   | 12,406,098 |  3,088,951 | 58 | 3,066 → 705 |

**Four times less work on the embark that was ninety times the others, and not
one node more on either of the ordinary ones.** An earlier version got `f2` to
1.7 million — seven times — at the price of making `fort` nearly twice as
expensive, and no regression anywhere is worth more than the extra two-fold.

### 121.4. A guard that came out again

`test_digging_throws_the_map_away` was written, passed, and was deleted before
this shipped. `dig_out` does call `invalidate_reach` and should — digging is
the answer to "nobody can get there", so it cannot be the one thing that
leaves the old answer standing — but taking the call out again did not make
the test fail, and this session has now found four guards that could not fail
(§115.4, §117.5, §118.6). A guard that cannot fail is worse than no guard,
because it reads like cover. The invalidation stays; a comment where the test
was says what is unguarded and why.

## 122. The world outlives the character (v3.62)

Three places in this codebase promised the same thing, and none of them could
keep it.

`renown.retire`'s docstring: *"somebody the next game can hear about, meet in
a tavern, or read about in the legends screen."* The README: *"Retire from the
pause menu and your adventurer settles where they stand, alive, in this
world's legends -- where the next adventurer, or a fortress in the same world,
can read about them."* The dialog the player actually sees on retiring: *"They
are in this world's legends now: another adventurer may hear of them, and a
fortress may read about them."*

There was no next adventurer in the same world. Every world was generated
fresh from a seed at the start of a game -- "New adventure" and "New fortress"
both went straight to `WorldGenScene` -- and lived only inside that game's save
file. Nothing in the menu opened a world anybody had played in. Retiring
autosaved and returned to the title screen, and the title screen had no idea
that world existed.

So `residents.RETIRED_WORTH = 25` -- *"an adventurer somebody retired here
outranks anybody the world invented"* -- had never once been added to a score
in a game a player could reach. The code was written, correct, tested at the
unit level, and unreachable in principle: to score a retired figure you must be
building a site in a world where somebody retired, and there was no way to be
in one.

### 122.1. What was measured

A retired adventurer, in the world they retired in, one function call away
from the town they settled in:

| | |
|---|---|
| retired figure's notability | 26, first of 13 residents of Highhelm |
| a world, gzipped | 149 KiB |
| the world's share of an adventure save | 74% |
| doors from a played world into a new character | 0 |

The world was already in every save on disk. It was three quarters of the
file. There was just no way to open it.

### 122.2. Worlds are files

`.awd` beside `.aws` and `.awf`, in the same save directory, written by the
same atomic tmp-and-replace. `World.uid` is the stem -- the world's own name,
`_2` on collision, claimed once by `ensure_uid` and serialised with the rest of
it, so every later save by any character who plays here lands on the same file.

The writeback is one funnel per mode: `save_game` and `save_fortress` both
call `save_world` after writing their own file. Retiring autosaves; dying
autosaves; both therefore leave the world on disk as that character left it.
The character's file goes first, so a failed world write costs the world's
last few hours and never the story.

**Adoption.** `load_game` and `load_fortress` call `adopt_world`, which writes
the save's own world to the list *only if no file for it exists*. That is what
makes a save from before this section still playable-in: every save carries a
whole world, and opening one puts it on the list. The never-overwrite half
matters more than it looks -- a world file is the world as the last character
*left* it, and loading an older save of somebody who used to live there is not
a reason to roll everybody else back.

**Divergence, stated honestly.** A save stays self-contained: it keeps its own
copy of the world, and loading it gives you that copy, not the file. So if A
saves at turn 100, B plays and retires, and you then load A, A's world does not
have B in it. The rule is that the *file* is the shared world and a *save* is a
snapshot of one character's, and the game never silently rebases one onto the
other. Dwarf Fortress avoids the question by allowing one at a time; this
allows both and says which is which.

### 122.3. The door

`WorldGenScene` gained one entry -- *"Play in a world you already have"* --
below "Generate world", so the smoke script's three downs still land on
"Generate world". It opens `WorldMenu`, which lists the worlds and, under the
list, what the last character left in the one under the cursor:

```
WORLD                  YEAR   SITES   LIVING  WHO IS THERE
The Vaults of the Gold 121    142     387     Kadol Steelfist settled here

The Vaults of the Gold, year 121 -- 142 sites, 387 living
  Kadol Steelfist settled here and is still alive.
  Anvilmoon stands where you left it.
```

`WorldGenScene` carries the mode, so the same door serves both halves of the
promise: choose a world and either the next adventurer is rolled in it or the
next fortress embarks in it. The seed for that character comes from
`continue_seed` -- the world's seed, its event count and its figure count --
so a world in a given state always rolls the same next character, and a world
somebody has lived in is never in the same state as one nobody has.

The title screen's Legends entry browses world files now rather than saves,
through the same `WorldMenu` with `mode="legends"`; `LegendsScene` takes an
explicit world for it. That left `SaveMenu`'s `mode` parameter with one
possible value, so it came out.

### 122.4. The epitaph was lying too

`FortEndScene` says *"%s stands on the world map now, exactly as you left
it."* It was recorded by `_become_adventurer` -- the `a` key. Press enter for
the menu instead and `record_fall` never ran: the corridors, the dead, the
artifacts and the founding went with it. Recording moved to `on_enter`, where
it happens whichever key you press next, and the world is written there too.

### 122.5. Does it work

The whole loop, end to end, as a test class that runs it once in `setUpClass`:
retire Kadol Testfist at a settlement of their own race, save, load the world
back off the disk, roll a different character in it, and walk into that town.

Kadol is standing there. Same `hf_id`, same name, ranked first of the site's
residents, and the tavern will tell you about them: *"They say Kadol Steelfist
the wanderer settled at Highhelm."* A fortress embarked in that world finds
them too.

Three things the loop exposed on the way:

- **What you retire holding went nowhere.** `ledger.on_death` puts a dead
  adventurer's artifacts back on the map and `ledger.gave_up` gives a sold one
  the town it was sold in, but retirement did neither: the crown kept its
  holder and lost its place, which is the one combination the histories cannot
  point at and `artifacts.populate` cannot put on a map. The next character
  would have met the person and never seen it. `ledger.settled` gives it the
  site they stopped in, and `populate` already hands an artifact to whoever
  holds it if that figure is standing there -- so the crown is in the hands of
  the adventurer you used to be.
- The retirement event read *"settled at Highhelm after 0 notable kills"* for
  an adventurer who had killed nothing. It is the line the tavern repeats for
  years, so it has to read like something a person would say.
- The legends page said *"Noted as: player, retired."* A page written by the
  world should not have a word in it for the person holding the keyboard.
  `player` is filtered and `retired` reads as a sentence.

### 122.6. What the re-break pass found

Fourteen of the fifteen new guards failed when their fix was removed. The two
that did not were both worth the trouble of checking:

**A real bug.** `test_opening_an_old_save_does_not_roll_the_world_back`
passed with `adopt_world`'s never-overwrite guard deleted -- because
`save_game` serialised the world *before* `save_world` stamped its uid, so
every first save carried `uid = ""`, and adopting it claimed a *second*
filename rather than overwriting the first. The test passed for the wrong
reason and the shipping behaviour was wrong: save a fresh world, reopen it
once, and one world became two. `ensure_uid` is now called before the payload
is built, and the test asserts the world count as well as the contents.

**Two paths covering each other.** The world menu names the retired adventurer
twice -- in the list line from `describe_world` and in the detail panel -- and
breaking either one left the name on the screen from the other. The test now
asserts both sentences separately.

### 122.7. What it costs

`save_world` is 250 ms on a small world, so an adventurer's save is now about
1.7x what it was and a fortress's about 1.5x. Every save in this game is a
deliberate keystroke -- there is no periodic autosave in either mode -- so it
is 250 ms on ctrl-S, on the pause menu, and on the two moments a character
stops. That is the price of the world being somewhere other than inside one
character's file, and it is worth it.

## 123. What everybody is carrying (v3.63)

Walk an adventurer into every site in a world and across a grid of the
wilderness between them -- 109 world squares, 14 biomes, every settlement,
tower, tomb, lair and ruin -- and count what you are ever shown. The item
table declares 117 things. You see **34**.

Not because the missing ones are exotic. You never see a tunic, a pair of
trousers, shoes, a cloak, a hood, a robe. You never see bread, cheese,
berries, wine, beer, mead. You never see a waterskin, a torch, a rope, a
backpack, a bandage, a whetstone. You never see a breastplate, greaves,
gauntlets, a great helm. You never see a long sword, a scimitar, a halberd,
a pike, a maul, a crossbow. And you never, anywhere, see an arrow.

### 123.1. Nobody had anything

Made directly: 1440 people of 24 kinds carry **24 distinct item ids between
them** -- a weapon, sometimes one piece of armour, sometimes a shield,
sometimes coins, and for the big ones sometimes a gem. Meanwhile
`item.starting_kit` sets the *player* out with a waterskin, three water, a
backpack, meat, bread, ale, two torches, rope, coin, three pieces of clothing
chosen for their profession, and arrows if they are an archer. The player
walked out of character creation better equipped than every single person
they would meet.

`item.random_loot` declares seven categories to draw from -- weapon, armor,
clothing, food, drink, tool, treasure, about a hundred item ids. It has one
caller, and that caller asks for `("treasure",)`. Six of the seven had never
been drawn from by anything.

### 123.2. And the archers had nothing to shoot

```
creatures given a ranged weapon:  248
what they are wielding:           {'(empty hands)': 248}
what they have to shoot:          {'(no ammunition)': 248}
```

Two causes and one root. `Inventory.best_weapon` skips ranged weapons
deliberately -- it answers *"what do I swing"* -- and two places used it to
ask *"do I have a bow"*:

- `make_creature` did `weapon = inventory.weapon() or inventory.best_weapon()`
  and then `if weapon.is_ranged:` before handing out ammunition. Nothing was
  equipped yet, so it fell to `best_weapon`, which cannot return a bow. The
  ammunition line was unreachable code.
- `auto_equip` wielded `best_weapon()` and nothing else, so an elf whose only
  weapon was a bow ended up holding nothing at all.

Downstream, `ai.py` shoots when *"the wielded weapon is ranged and there is
ammunition readied"*. Neither had ever been true. `combat.ranged_attack`,
`ammo.spend`, `ammo.land`, the arrows that stick in the grass and the two in
three that shatter -- the whole of §80's spent-arrow system -- were reachable
only by the player's own bow. `elf_archer`, a creature type with `bow` 7 in
its skills, walked up and punched you.

`Inventory.ranged_weapon` is the accessor that was missing. `auto_equip` draws
it when there is nothing to swing -- and only then, because the AI shoots with
what is readied and a spearman who nocked an arrow because one was in the pack
is a worse spearman.

### 123.3. One place says what a bow eats

`items.ammo_for` was written to be the funnel and had **zero callers**. Three
places open-coded what it does, all three carrying the same patch:

```python
ammo_id = "stone_ammo" if wanted == "stone" else wanted
```

Because `WeaponDef.ranged` said `"stone"` for a sling and there is no item
called that -- `items.get("stone")` falls through to `boulder`. The data was
wrong, so every reader worked around it, and the function written to hold the
workaround once was never called. The sling now says `stone_ammo`, `ammo_for`
is three lines with no special case, and `actions.fire`, `items.validate` and
the arming code all ask it.

### 123.4. The table already said who fights with what

`elf_archer` has `bow` 7. `axedwarf` has `axe` 6. `hammerdwarf` has `hammer`
6. `guard` has `spear` 4. `merchant` has `appraisal` 5 and no weapon skill at
all. And `make_creature` ignored every word of it, drawing from five lists
keyed on *race*: the archer got a spear two times in three, the axedwarf got a
warhammer, and the town's baker got whatever the town's guard got.

`trained_weapons` reads the skills and `items.weapons_for_skill` -- another
function whose only caller was a test -- turns the skill into weapons. That is
where the long sword, the scimitar, the halberd and the pike came into the
world: they were always in the table under skills nobody was asked about.

`usable_weapons` filters by size, which was needed the moment weapons stopped
being hand-picked: a gremlin is 15,000 and a battle axe wants 27,500, so a
gremlin handed one off a race list carried it around and fought with its
hands. 32 of 40 did.

`_fights` decides who gets a weapon at all, from `fighter`, `EVIL` and the
faction. A peasant carries a knife; a goblin raider with `fighter` 1 still
raids.

**The marksdwarf.** The item table has a crossbow and bolts to feed it and
there was nobody in any world trained to use one -- `elf_archer` was the only
marksman of any kind and elves shoot bows. `marksdwarf` is the third dwarven
soldier beside the hammerer and the axedwarf, and `sitegen` posts it to the
gate with them.

### 123.5. And clothes

Everybody `CIVILIZED` is dressed now -- the same line `residents.could_be`
already uses to decide who can have a name, and the right one here for the
same reason: nothing in the item table is cut for a giant, and a cyclops in
shoes is a worse world than a cyclops without. Night creatures are dressed and
not armed: a werebeast fights with what it is, and is a person the rest of the
month.

The oddments come through `random_loot`'s categories, so the tables that exist
are the tables used. `weapon`, `armor` and `clothing` came *out* of that table
instead: `entity` hands those out itself and has to, because a coat and a
cloak and a shirt go in three different layers and a flat random draw put
three cloaks on one man. Two tables naming the same items is how they drift.
`random_loot` also stopped substituting the tool table for a category nobody
declared -- quietly handing out rope for a typo is how "everyone carries rope"
ships.

### 123.6. The tavern had no floor

`tiles.py` has had a `tavern` floor since it was written, with its own glyph
and its own colour. Two things test for it: `_tavern_music`, which is the
entire reason to walk into a tavern in the evening, and `_applaud`, which pays
a crowd more when they are indoors. `sitegen._furnish` dropped tables, chairs
and beds into a tavern and **never laid its floor**, so no tavern in any world
had one and neither feature had ever happened once.

`ROOM_FLOORS` lays it. And with a floor there is somewhere to put the house
instruments, which is the other half of the same hole:
`performance.instrument_for` scores +8 for the right instrument in the
performer's hands, +3 for the wrong one lying in the room and **-14 for
nothing at all**, and its own docstring says a game that crafted every
instrument in it would otherwise perform identically to one with none. In
adventure mode it was the second kind: six instrument definitions and not one
of them in any room in any world. `game/furnishings.py` is the third module in
the arrival sequence beside `traps.populate` and `artifacts.populate` -- the
things a place keeps because of what it is for -- and it stocks a tavern with
the instruments its own civilization's music calls for. `_tavern_music` now
passes the room to the performance, which it never did, so the instruments
would not have counted even if they had been there.

Measured on one tavern: a form that wants a flute scored **-4 with an empty
room and 13 with the room** -- across the threshold from *halting* to
*measured*. And with somebody standing in it: *"Perrine Kettleby dances The
Raised Silver. It is plain."*

### 123.7. What the world shows you now

| | before | after |
|---|---|---|
| item ids seen in one world | 34 / 117 | **68 / 117** |
| distinct ids on 1440 people | 24 | 59 |
| archers wielding their bow | 0 of 248 | all of them |
| archers with ammunition | 0 of 248 | all of them |
| loot categories ever drawn | 1 of 7 | 4 of 4 |
| taverns with a floor | 0 | all of them |

What is still never seen is worth writing down rather than implying. Most of
it is correct: `bed`, `table`, `chair`, `barrel`, `bin`, `cabinet`, `chest`,
`coffer`, `coffin`, `mechanism`, `statue`, `altar`, `bar`, `ore`, `coal`,
`log`, `cloth`, `wool`, `sand` and `cave_wheat` are things a fortress makes,
and `corpse`, `skull`, `bone_item`, `hide` and `severed_part` come off things
that die. The rest is a list rather than an argument: `crown`, `crutch`,
`splint`, `flask`, `lantern`, `fishing_rod`, `pick`, `mittens`, `socks`,
`milk`, `cooked_meat`, `prepared_meal` and `fish_food` are in no table
anybody draws from; `great_axe`, `maul`, `morningstar` and `flail` are
two-handed and every creature trained in their skill also carries a shield;
and `quiver` and `shovel` are still named nowhere in the codebase at all, as
they have been since §101 wrote them down.

### 123.8. What moving the dice shook loose

Every change here draws differently from the world RNG, so every world after
it is a different world -- and one test out of 1503 fell over.
`test_a_death_shakes_the_side_that_took_it` took `hostiles()[1]` as the
creature that gets frightened by a death: whichever species the world's
politics happened to send. Goblins carry `NO_FEAR`. The test had been
asserting that somebody who cannot be frightened was frightened, and passed
only because the draw had not yet handed it a goblin.

Its own sibling `_afraid_invader` exists for exactly this and says so in its
docstring -- *"not whichever species the world's politics happened to send"*.
The test builds its watcher now. That is the third time in this codebase that
a test which *picks* what it measures has been rewritten to *build* it, and
the rule is worth stating plainly: a test that hunts through generated data
for a subject is a test with a seed in it, whatever it looks like.

## 124. Running errands (v3.64)

`tools/fort` plays a fortress for a year and judges the wreckage; four defects
came out of it in §119. `tools/play` was supposed to be its opposite number
and, since v3.51, it drank when thirsty, ate when hungry, slept when tired,
hit what was next to it and otherwise wandered in a circle. That found three
defects and then measured nothing for a dozen versions, because looking after
a body is not playing this game.

The README spends most of its adventure half on one loop: travel, a town,
somebody to talk to, work to take, a place the work points at, the thing
waiting there, the walk back to be paid. **Nothing had ever walked it.** The
unit tests check the pieces; no test and no driver had ever put them in a row.

So the driver runs errands now, and six defects were sitting in the loop.

### 124.1. Before it could play, it had to survive

Three of the six are in the driver itself, and each had been quietly ruining
every run since v3.51.

**An action that did not happen claimed the turn.** `_look_after` returned
`actions.drink(game)` whatever it came back as, and a failed drink costs
nothing. Measured on the first errand run: **3971 of 4000 turns pressing
"drink" with nothing to drink**, and 3940 of 4000 on sleep in the next one --
`sleep` returns free when there are enemies nearby, which there usually are.
The invariants never noticed, because needs pinned at the ceiling have
certainly moved.

**It could not hit an animal.** `_adjacent_foe` asked `c.faction ==
"hostile"`. A wolf's faction is `"wild"`; the question everything else in the
game asks is `is_hostile_to`. So a wolf could chew through an adventurer who
never once swung back, and the run reported `fought: 0` under a log full of
bites.

**It swam.** `_walk_toward` used `local.path_neighbours`, which is what a
creature can *get through* and includes the river. The driver walked into one
with a full pack on, kept fighting a goblin from chest-deep water, and drowned
-- and reported `dead=True drowned` with nothing in the log about water,
because it printed the cause and not the last six lines. It walks round now,
climbs out if it is ever in, and prints what was said before the end.

### 124.2. A bounty sent you nowhere

Every kind of work in the game names a destination -- *"It lies at Goldwheel,
a tomb"*, *"Word must reach Frozencoal, a hamlet to the north"* -- except one.
Measured over 127 quest givers in four worlds:

| kind | offered | no destination | pinned on the town you are standing in |
|---|---|---|---|
| clear_site | 31 | 0 | 0 |
| slay_beast | 28 | 0 | 0 |
| explore | 26 | 0 | 0 |
| retrieve_artifact | 21 | 0 | 0 |
| **bounty** | **21** | **21** | **21** |

`_quest_bounty` set `q.wx, q.wy = game.player.wx, game.player.wy` and never
set `site_name`, so the log read `Location: (59, 20)` for the square under
your feet and the map marker pointed at the person who had just sent you out.
`_hunting_ground` picks a wild square within four tiles where that creature
lives and names its region, so the job reads *"out of The Wandering Dunes to
the north-east"* and points there.

### 124.3. And it did not remember where you took it

`_ready` says *"Return to Ustuth to claim your reward"* and `Quest` recorded
`giver_hf` and `giver_name` and **nowhere they were standing**. Walk out of
the town and the quest log could not tell you which town it had been. Quests
carry `giver_site_name`, `giver_wx` and `giver_wy` now, and the log says
*"Given by Ustuth Roughclasp at Roaring Lock (18, 28)."*

### 124.4. What it sent you for was not there

The sharpest one, and the driver found it by standing in the right place for
**11,956 turns** hunting something that was not in it.

`spawnable(biome)` says which species *can* live somewhere; the wildlife roll
then draws a handful of groups out of twenty candidates. So a bounty for giant
rats in the desert named a species that was genuinely at home there and was
present on arrival **seven times in forty-two**.

`artifacts.populate` and `sitegen._add_lair_beast` already hold this line for
the other two kinds of quest -- what a quest names is there when you arrive.
`Game._spawn_the_hunted` holds it for the third, and holds it twice over:

- **On arrival**, including on a map you have already crossed. The local map
  cache restores the wildlife that was there *before* you were sent after
  anything, so walking back to a meadow you had passed through was the one
  case guaranteed to fail.
- **In numbers you can finish the job with.** A group is one to three and a
  bounty asks for three to seven, so arriving, killing the pair that were
  there and standing in an empty field was the rest of the errand. It places
  groups until the remaining goal is on the map.

Placement moved into `Game._place_group` so the thing a bounty sends you after
is placed exactly the way everything else that lives there is placed.

Bounties also stopped naming cave dwellers. `giant_bat` carries
`SUBTERRANEAN`, the wildlife roll only ever puts it in a cavern, and the
complaint the quest text makes is that they are taking livestock out of a
field.

### 124.5. Two things about the body

Both found the same way, by a driver that had to survive to measure anything.

**Nothing to bind a wound with.** `starting_kit` gives a waterskin, water, a
backpack, meat, bread, ale, two torches, rope and coin. No bandage. Bleeding
is what kills an adventurer -- four seeds, four deaths, thirteen turns in a
row reporting *"bleeding, and nothing to bind it with"* -- and since §123
every person in the world carries one. Three bandages and a splint now.

**A skin of ale is not a drink.** `actions.drink(game)` with nothing chosen
looks for water underfoot, then falls back to the pack -- and the fallback
reached exactly one item id, `water_drink`. An adventurer carrying four ales,
a wine and a mead was told *"There is nothing to drink here"*, while
`Needs.drink` takes any drink there is and the loot tables hand out five kinds.

### 124.6. What the driver asserts, and what it does not

The invariants judge correctness, not competence, because an alarm that
always fires is not an alarm:

- work with no destination,
- **arriving where the job is and the job not being there**,
- a job met, carried back, reported, and never paid,
- drowning with dry land one step away,
- dying of thirst beside water,
- needs that never moved, and nobody in the world having any work.

The second one is the guard on §124.4 and it fires: with `_spawn_the_hunted`
removed, seed `e4` reports *"1 times it walked to where the job was and the
job was not there"* and exits non-zero.

What it does **not** assert is that it finished the job, and that is worth
writing down rather than implying. The driver takes work, travels to it, and
then has to catch wildlife that wanders and flees across an eighty-by-sixty
map; over twelve thousand turns it fights thirty-one times and finishes
nothing. That is a bot that hunts badly, not a game that cannot be played, and
pretending otherwise with a failing invariant would make the driver useless as
a check. Making it hunt is the next thing to do to it.

## 125. The things that could not be killed (v3.65)

§124 left the driver taking work and finishing none of it, and said the next
thing to do was make it hunt. It turned out not to be a hunting problem. The
driver took a bounty for three zombies, walked to where they were, swung at
one twenty-nine times, and bled to death without killing it.

`Body._check_state` ends a life three ways:

```python
if frac <= BLOOD_DEATH:            self._die("bled to death")
if not self.can_breathe():         self._die("suffocated")
if part.destroyed and VITAL/THOUGHT: self._die("%s destroyed")
```

**Ten of the eighty-one creatures in the table have no blood.** The four
undead; the cave spider, the giant cave spider and the giant desert scorpion,
which is to say three of the things §117 put in the caverns; the demon; the
bronze colossus; and the forgotten beast. For every one of them the first rule
could never fire, the faint that precedes it could never fire, and the third
needs a blow to reach a heart or a brain, which almost never happens.

They were, in practice, unkillable. Measured, forty duels each:

| | wins | exchanges |
|---|---|---|
| starting warrior vs wolf | **40 / 40** | 7 |
| starting warrior vs goblin | 36 / 40 | 7 |
| starting warrior vs zombie | **2 / 40** | 55 |
| starting warrior vs skeleton | 2 / 40 | 111 |
| starting warrior vs mummy | **0 / 40** | 16 |
| dwarf with a steel warhammer vs skeleton | **0 / 40** | 135 |

Taking a zombie apart and looking at what was left after forty-eight
exchanges: **sixty-six wounds across eighteen parts, nothing destroyed**, the
skin, fat and muscle cut off its torso, neck, both arms and both legs, and the
model with nothing to say about any of it. `blood_fraction` reads 1.00 for a
body that does not bleed, so the rule that ends nearly every fight in this
game was reading a constant.

### 125.1. What stops one is being taken apart

`Body.structure_fraction` is the measure the bloodless needed, and it is built
entirely out of bookkeeping that was already there: each part's tissue layers
already carry a remaining fraction, and `PartState.broken` is already set when
a blow cracks bone. Averaged per part over its layers, weighted by part size
so a torso opened up counts for more than a finger, and a broken bone worth
`BROKEN_WORTH` of what the part was -- a thing held together by its skeleton
is not held together by a snapped one.

```python
if self.bloodless and self.structure_fraction() <= STRUCTURE_DEATH:
    self._die("hacked apart")
```

Gated on `bloodless`, so nothing alive changed: a man with no muscle left is a
man who has bled to death, and the blood rule is what should say so. The wolf
and the goblin duels come out identical to the digit.

### 125.2. A skeleton is bones with nothing on them

`TISSUE_OVERRIDES` mapped a skeleton's skin, fat and muscle to the material
`bone` -- which is not "it has no flesh", it is **four layers of the toughest
tissue in the game**. A skeleton was tougher than a living man, and a dwarf
with a steel warhammer lost to one forty times in forty over a hundred and
thirty-five exchanges.

`Body` takes a `missing` list now, and a skeleton is missing skin, fat, muscle,
hair and nails. Its torso reads `{'bone': 1.0}`, which is what a skeleton is.

### 125.3. Where it leaves the bestiary

Unopposed, with a good steel axe, blows to kill:

| | before | after |
|---|---|---|
| ghoul | never | 14 |
| zombie | never | 16 |
| mummy | never | 18 |
| forgotten beast | never | 17 |
| demon | never | 32 |
| cave spider | never | 52 |
| giant cave spider | never | 483 |
| skeleton | never | 775 |
| giant desert scorpion | never | 782 |
| **bronze colossus** | never | **still never** |

And in a real fight, with the thing hitting back: a starting warrior now beats
a zombie 26 times in 30 with the iron sword they set out with, and 30 in 30
with a steel hammer or axe. A skeleton takes a chopping weapon -- 24 in 30 with
a steel battle axe, 3 in 30 with a sword, 0 with a hammer -- which follows from
bone shearing at 115,000 and resisting impact at 200,000, numbers this project
took from Dwarf Fortress and has no business changing to make a fight easier.

### 125.4. The colossus, measured and left

A bronze colossus takes **zero wounds from two thousand blows of an adamantine
axe** -- adamantine shears at 5,000,000 against bronze's 130,000, so this is
not toughness, it is a wall. `combat` subtracts `natural_armor * 3000` from
every blow and the colossus has 10 of it: a flat thirty thousand kilopascals,
which nothing in the game swings hard enough to clear.

That is a different axis -- weapon force against natural armour, which sets
the shape of every fight in the game -- and it wants its own measurement pass
rather than a threshold nudged at the end of this one. It is written down here
and named in `test_every_bloodless_thing_but_one_can_be_killed`, so the
exception is deliberate and visible rather than a gap somebody finds later.

### 125.4a. And the errand it was blocking

The bounty the driver was stuck on -- three zombies in the Iron Meadows,
eleven thousand nine hundred and fifty-six turns of swinging at something that
could not die -- **completes in 180 turns now**. That is the whole loop closed
by playing: walk into a town, take work, cross the world to where it points,
kill what is there, and carry it back. `explore` closes too. The other three
kinds still end with the driver bleeding to death on the road, which is §124.6
and is still true.

### 125.5. And three things the driver needed to get there

Found on the way, because a driver that cannot reach the job cannot report on
it.

**It had no map.** `tools/play` walked greedily at its destination and tried
four neighbouring squares when a step failed. Three runs in ten spent **every
one of four thousand turns hemmed in**, stopped by a coastline four tiles
wide. The travel screen has drawn a proper route since it was written and kept
it to itself; `Game.route_overland` is that A* moved down into the game, and
the screen and the driver both ask it now.

**It crossed rivers with an empty waterskin.** It drank when parched and
never otherwise, so it walked past water with a half-full skin and died of
thirst in the next desert twice in ten runs. It tops up at every source now,
which is what the skin is for.

**It walked over what it needed.** Everybody in the world carries a bandage
since §123 and it falls to the floor when they do; the driver had three from
its own kit and then spent ninety-five turns in one run reporting *"bleeding,
and nothing to bind it with"*. It picks up bandages, food and drink off what
it kills.

## 126. The metal in your sword (v3.66)

§125.4 left the bronze colossus taking zero wounds from two thousand blows of
an adamantine axe, and said the reason wanted its own measurement pass rather
than a threshold nudged at the end of that one. This is that pass, and the
colossus turned out to be the smallest part of it.

The README calls this "real material science". Every material in the table
carries shear and impact yields in kilopascals. And a *weapon's* material was
used for exactly one thing:

```python
def effective_kind(weapon, attack_def):
    """Whether an attack actually cuts, given the weapon's material."""
    if attack_def.kind != "edge":  return "blunt"
    if not attack_material(weapon, attack_def).can_hold_edge:  return "blunt"
    return "edge"
```

A boolean. Nowhere else. What decided a blow was momentum, and momentum is
mostly mass:

```python
momentum += WEIGHT_MOMENTUM * mass * strength
```

So the metal in your sword mattered only through how much it weighed.

### 126.1. Which points the wrong way

Blows to put down an unarmoured goblin, median of fifteen, same weapon, same
quality, different metal:

| | copper | bronze | iron | steel | adamantine |
|---|---|---|---|---|---|
| sword | 7 | 6 | 5 | 7 | **10** |
| battle axe | 4 | 6 | 4 | 6 | **10** |
| warhammer | 7 | 9 | 10 | 8 | **20** |

**Copper beat steel, and adamantine was the worst material in the game** --
twice the blows of anything else. Copper is the densest metal in the table
(8930) and adamantine the lightest (200), and that is the whole explanation.
The hardest substance in the world, shearing at five million against steel's
four hundred and thirty thousand, the point of the deepest mine in the game,
made the worst weapons in it.

That table also says something else worth knowing: against *flesh*, nothing
distinguishes the metals, because `hurt` is clamped at 1.0 and skin yields at
20,000. Any metal is already at the cap. The metal is supposed to matter where
things are hard -- bone, plate, a thing made of bronze -- and that is where the
measurement had to be taken.

### 126.2. What the edge is worth

`body.keenness` is one function, anchored on iron because iron is what the
game is balanced around and what almost everybody in the world carries:

```python
keen = clamp((edge.shear_yield / iron.shear_yield) ** 0.5, 0.6, 6.0)
```

Square-rooted because the raw ratio spans a factor of forty; floored so a
wooden club is not useless; and the ceiling at 6.0 rather than 3.0 because at
3.0 adamantine came out *still worse than steel* -- it is thirty-nine times
lighter, and the ceiling has to let the data say what the data says.

It is asked in two places, and both of them were missing it:

- `Body.apply_damage` divides a tissue layer's resistance by it -- **but only
  for a layer that is hard**. Skin shears at 20,000 and muscle at 30,000
  against bone's 115,000, and no metal is better than any other at cutting
  something soft. That threshold is the difference between a fix and a
  rebalance: scaling every layer flattened the weapon triangle, because a
  spear's narrow bite is not at the damage cap and lifting it pushed a spear
  over a threshold that belongs to an axe. Measured with the flat version, an
  axe and a spear both took an arm off in twelve trials of twelve.
- `combat.armor_protection` divides what armour absorbs by it, because a
  blade much harder than the plate defeats more of the plate. Nothing here
  asked before: armour stopped a copper knife and an adamantine one
  identically, which is the whole reason the colossus could not be scratched.

### 126.3. Where it leaves things

Blows to put something down, median of thirteen, 500 the cap:

| target | copper | bronze | iron | steel | adamantine |
|---|---|---|---|---|---|
| skeleton (sword) | never | never | never | **47** | **21** |
| skeleton (axe) | 111 | 36 | 33 | **18** | 22 |
| **bronze colossus (sword)** | never | never | never | never | **282** |
| man in steel plate (sword) | 11 | 13 | 14 | 13 | 21 |

An iron blade cannot cut bone and a steel one can. A bronze colossus falls to
adamantine and to nothing else. Both are what the numbers in the material
table have said all along.

The last row is the model saying something it could not say before and is
worth reading twice: an adamantine sword is *slower* against an armoured man
than an iron one. It goes through the plate as though it were not there --
that is what dividing the absorption by 5.7 does -- and then arrives at the
flesh behind it carrying a fifth of the momentum, because it weighs a
fortieth of what steel does and flesh does not care how sharp you are. The
legendary metal is for what is hard. Against a man it is a light sword.

And the ordinary fight did not move at all, which is what anchoring on iron
and gating on hardness were both for:

| | v3.65 | v3.66 |
|---|---|---|
| warrior vs wolf | 40 / 0 | 40 / 0 |
| warrior vs goblin | 36 / 4 | 37 / 3 |
| warrior vs zombie | 32 / 8 | 32 / 8 |
| warrior vs skeleton | 2 / 37 | 2 / 37 |
| warrior vs mummy | 1 / 39 | 1 / 39 |
| hammerdwarf vs skeleton | 0 / 38 | 0 / 38 |

Everything in the world carries iron, and iron is 1.0.

### 126.4. One thing left named

The ranged path already carried its own material term, two dozen lines above
where the armour is subtracted:

```python
momentum *= 1.0 + ammo.mat.shear_yield / 400000.0
```

That is the same idea as `keenness` written a second way, and it predates it.
Passing both would count the metal twice, so the arrow keeps the older one and
the call site says why. Which of the two should go is a question about
archery's balance rather than about material science, and it is left named
rather than half-changed.

### 126.5. And what the fuzzer found while checking it

Moving the dice moved the fuzzer's key sequences, and adventure seed 23
crashed on frame 1088:

```
AttributeError: 'str' object has no attribute 'full_description'
```

The inventory screen had highlighted an empty armour slot and asked the string
`"Head           (empty)"` to describe itself. Two defects in the shared widget
layer, both general, both there since it was written:

```python
self.value = value if value is not None else frag_str(label)
```

**A row could not mean nothing.** Standing for its own text is the right
default and most menus want it -- but passing `None` explicitly got it too, so
every row that meant *nothing* (an empty slot, a heading, "(no saved games)")
came back as the string it was drawn with. A sentinel separates "no value
given" from "a value of None".

**And a row that was switched off was still a selection.** `ListMenu.selected`
excluded headings and not disabled rows, so a greyed-out row could be
highlighted and acted on, and every screen had to remember to check for
itself. Now it cannot be selected at all.

Either fix alone stops the crash, which is why the test that reproduces it
only fails with both reverted -- and it is worth having anyway, because what
it asserts is the thing the player cares about: walking the cursor down every
row of the equipment screen does not end the game.

## 127. Ground you can build on (v3.67)

A fortress played properly for a year, rather than for the seven days
`tools/fort` stops at:

```
day 16: everybody died -- starved, thirsted and forgotten
```

The driver's own report for the same embark, one line, exit code zero:

```
FORT OK: fort, 7 days, 7 alive of 7
built ['still', 'carpenter', 'bed', 'bed', 'bed', 'bed', 'bed', 'bed', 'bed']
```

Nine buildings out of a plan of eleven. The two missing were the farms, and
nothing said so: `_put_up_the_workshops` could not find anywhere to put them
and moved on to the next entry with a bare `continue`. Nobody grew anything
all year and the run stopped nine days before it mattered.

### 127.1. What the ground was made of

`_clear_spot` searched one z-plane — the wagon's — for a level three-by-three.
The reason it kept finding nothing is the terrain itself:

| measured over one 80x60 embark | before | after |
| --- | ---: | ---: |
| commonest surface tile | `ramp_up` (1743) | `grass` (2021) |
| `ramp_up` columns | 1743 | 787 |
| neighbouring columns at different heights | 31% | 14% |
| level three-by-three patches | 449 of 4524 | 2182 of 4524 |
| patches that would take a workshop today | 21 | 60 |
| ...and that would take a farm plot | 2 | 10 |

Two flat squares on an entire map, overlapping, so one farm. The cause is one
line of `_build_heightmap`:

```python
detail = noise.fbm(x * 0.12, y * 0.12, 4) * 0.5 + 0.5
```

`fbm` doubles the frequency each octave, so four octaves from 0.12 put the
finest one at **0.96 cycles per tile**: a full rise and fall inside a single
stride, against a Nyquist limit of 0.5 for a grid you sample once per tile.
What landed on the map was not that wave, it was the aliasing of it — and
after `int(round(...))` the aliasing is a one-tile step. The ground was
sandpaper, not landscape.

```python
DETAIL_FREQ = 0.045
DETAIL_OCTAVES = 3
```

Finest octave 0.18 cycles per tile: a slope takes four tiles to climb a level,
which is what a hillside does. The large-scale relief is untouched — the same
embark still spans the same seven z-levels — so what changed is that the
levels come in plateaus instead of spatter. The test is arithmetic, and it is
the rule rather than the number: `DETAIL_FREQ * 2 ** (DETAIL_OCTAVES - 1)` may
not exceed a quarter cycle per tile.

Nine tenths of the level ground is still under trees (2010 of 2182 patches),
which is what a forest is, and clearing it is the player's job.

### 127.2. The aquifer under the topsoil

The driver's own embark still dug nothing at all: sixty-two cells painted,
none dug, seven dwarves idle for a year, and the wood kept coming in from the
surface so the run reported OK. Digging the stairway one step at a time and
watching the water:

```
dig (40, 30, -8)  tile=grass      aquifer=False   shaft dry
dig (40, 30, -9)  tile=soil_wall  aquifer=True    shaft: z=-9 water 7
```

The aquifer was the *first* layer under the grass. `_lay_aquifer` scored
candidate layers with a bonus for being shallow — "an aquifer you only meet at
the bottom of the map is an aquifer you never meet" — and on a low-lying
embark the shallowest mostly-rock layer is the one directly under the topsoil.

That is not an obstacle, it is a wall. An aquifer wets a whole z-level, there
is no pump in this game, and the one cell anybody could stand in to cut the
next step down is at the bottom of the flooded shaft. `_prune` files every
designation below it as unreachable and retries them for ever.

Measured over ten embarks: four had an aquifer, and on two of those it lay
within one level of the wagon. So the layer is chosen per column now:

```python
def soaks(x, y, z):
    t = tile_data.get(lm.tile(x, y, z))
    return (t.has("DIGGABLE") and t.has("WALL")
            and lm.surface_z(x, y) - z >= AQUIFER_CLEARANCE)
```

Per column rather than per layer, so the water table stops where the ground
dips towards it instead of the whole map losing its aquifer to one gully.

And the layer is taken rather than scored — the shallowest one that soaks
`AQUIFER_CELLS` cells, searched downward from the ground:

```python
for z in range(min(top, lm.zmax) - 1, self.magma_floor + 1, -1):
    if count * 4 >= AQUIFER_CELLS:
        best_z = z
        break
```

Scoring layers and taking the best sounds like the same thing and is not.
With clearance in the test, a shallow layer only qualifies under the high
ground, so it soaks fewer columns than a deep one and loses on count: keeping
the old `count * (1 + 0.15 * (z - zmin))` sank every aquifer to the floor of
the diggable rock at z=-10, one level above the warm stone, where nobody would
ever meet it. "The shallowest layer that is really an aquifer" is the rule the
comment always claimed and the arithmetic never quite said.

Over the same ten embarks the count is unchanged at three in ten, and the
depths moved from -10, -10, -9 to -8, -9, -8. The shallowest wet cell on any
of them is four levels under its own patch of ground, which is the guarantee
that makes the difference: a fortress always has somewhere dry to start.

### 127.3. And a stairway sunk in a lake

That fixed two embarks and not the third, which had no aquifer at all and
still flooded. `_wagon_site` picks the flattest, most open ground near the
middle of the map — and beside a lake, that is the shore. The wagon stopped
one tile from open water and the driver sank its stairway where the wagon
stood.

The wagon is not wrong to stop there; migrants and caravans arrive at it. The
driver was wrong to dig there, so it looks for somewhere dry first:

```python
def _home(fort):
    wagon = fort.wagon if getattr(fort, "wagon", None) else fort._wagon_site()
    return _dry_ground(fort, wagon[0], wagon[1]) or wagon
```

Level ground within `SITE_RANGE` of the wagon, no open water within
`DRY_MARGIN` **at or above** that level — water runs downhill into the hole and
not up out of it — and `DEEP_ENOUGH` levels of diggable rock underneath it.
The workshops go up around the same spot, because a fortress is one place.

### 127.4. What the driver says now

Three things it did not say before:

- **The buildings it could not put up.** `_put_up_the_workshops` returns
  `(built, missed, felled, furthest)`, and a non-empty `missed` fails the run.
  The search covers the whole map rather than thirty tiles, because "there is
  nowhere on this map to put a farm" is worth knowing and "nowhere within
  thirty tiles" is not; how far it had to walk is in the report instead.
- **The last word on a site belongs to the game.** The driver pre-filters, and
  then asks `buildings.can_place` — the same call the build menu makes. A site
  the driver likes and the game refuses is reported as a miss rather than
  built anyway. The driver is not allowed its own idea of buildable ground.
- **Nothing dug.** Sixty-two cells painted for digging, none dug, and every
  dwarf idle is now a `FORT PROBLEM` and a non-zero exit. That is the invariant
  that would have caught all of this on the day it appeared.

Trees on the chosen site come down first, through `Fortress.fell_tree` — the
one place a tree stops being a tree, split out of `_finish_chop` so the driver
clears ground exactly the way a dwarf does. A felled trunk leaves grass, which
is soil, which will take a farm.

Across eight seeds, before and after, seven days each:

| | before | after |
| --- | --- | --- |
| embarks that built all eleven buildings | 3 of 8 | 8 of 8 |
| embarks that dug every cell they painted | 6 of 8 | 8 of 8 |
| embarks that dug nothing at all | 1 of 8 | 0 of 8 |

### 127.5. What a terrain change costs the tests

Ten tests went red, and the ones that mattered were the ones whose fixtures
had been telling themselves stories. Reverting the terrain alone told them
apart: eight passed again with the old heightmap, so those were fixtures built
on the shape of one map; two survived the revert, and both were the aquifer.

- **A "walled-off" cell you can walk to.** `_walled_off` looked for diggable
  rock with somewhere to stand beside it and called that unreachable. Five of
  the twelve it handed back were reachable — the caverns now join the surface
  across the whole map, and the component a dwarf stands in is 22828 cells. It
  asks the fill now.
- **Twenty dig jobs nobody could claim.** `_wall` took the first *n* diggable
  cells in map order. Most of a map's diggable cells are buried inside other
  diggable cells with no way in, so a test about which job a dwarf picks off a
  crowded board was handed a board of impossible work.
- **A workshop across a wall from the wagon.** `_open_spot` asked
  `can_place`, which answers whether the tiles will take a building and not
  whether anybody can get at it. The smelter and the furnace ran; the forge
  went up in a pocket of open floor eighteen tiles away and nobody ever
  arrived. Both helpers ask the fill now, and the fill they draw is refunded
  to `fort.reach_fills` so a fixture cannot bill the game for its own
  scaffolding.
- **A cow standing on grass.** Two animal tests meant "there is no grass on a
  mountain" and relied on the cow being somewhere bare. There is more grass
  than there was — 2021 columns against 1453, because the ramps that used to
  cover the ground are gone — so the cow grazed instead of eating the store,
  and instead of starving. They put it on bare ground now.
- **A bag of sand made of mud.** Not terrain at all: `sand` was the only item
  in the game whose material came from the `SOIL` flag, so `rng.choice` picked
  between dirt, sand and mud and the test's seed had been choosing sand. Sand
  carries a `SAND` flag of its own now. The first attempt let a definition
  name its material outright instead, which read better and was wrong:
  `ItemDef.materials` is a tuple of flags everywhere else that touches it, and
  giving the field a second meaning broke `test_every_recipe_can_still_be_made`
  three files away.
- **Two thresholds that disagreed.** The flier test measured "arrived" at
  eight tiles and "never arrived" at two; one embark's roc now lands between
  them, closing to four and manoeuvring there without ever standing still. It
  reads the same constant for both. Its hover count is the longest run rather
  than the total, because the defect it guards against was eighty steps in one
  cell and the two steps it now sees at the map edge are a hard tile.
- **A retreat further than the search can see.** `RETREAT_SEARCH` is 8000
  nodes and the deepest cell a dwarf can walk to is a hundred and fifteen
  steps away through the caverns: a route out exists and costs 20000 nodes to
  find. A besieger routs at the gate, so the test puts its invader in the
  fortress under it rather than at the bottom of the cave system — and the
  limit is named below rather than paid for.

### 127.6. Measured and left

- **A farm forty tiles from the stairway.** One seed has almost no surface
  soil near its fortress, and the whole-map search dutifully found the nearest
  patch 41 tiles away. The player's answer is the one the founding log already
  gives — dig a room in the soil sheet and farm underground — and the driver
  cannot do that until it can build after digging rather than before.
- **A dwarf starved to death beside forty units of food and six hundred of
  ale.** Same seed, both before and after this milestone, and it is the next
  thing worth chasing: it is not about ground at all.
- **There is no way past an aquifer.** Meeting one is the bottom of your
  fortress, permanently — no pumps, no casting obsidian, no double-slit. That
  is now a floor four levels down instead of a wall at the top, which is the
  difference between an obstacle and an ending, but it is still not the
  obstacle it should be.
- **One farm plot barely feeds seven dwarves.** Sixty days on one plot: food
  hovering between 20 and 70, drink falling steadily from 438 to 30. Two plots
  is the difference between a fortress and a slow death, which makes the farm
  the most important building in the game and the one the driver could not
  place.
- **A routed invader more than 8000 nodes of walking from a map edge stops
  where it is** and waits for `FLEE_TICKS` to clear it. That was unreachable
  before the caverns joined up; it is reachable now, and the honest fix is
  probably to retreat along the route the army arrived by rather than to
  search for the sea.
- **A dwarf can refuse work the fill says it can reach.** `path_to` tries the
  six nearest standing spots and gives up; the fill says yes if *any* spot is
  reachable. `test_nobody_refuses_work_the_map_says_they_can_reach` pins the
  two together for a goal you stand on and not for one you stand beside.
- **The world map's own noise is past Nyquist too** — `3.4 / max(w, h)` over
  six octaves puts its finest at about 1.1 cycles per world tile. A world tile
  is a region rather than a surface you walk on, so the aliasing shows up as
  speckled biomes rather than as ground you cannot build on, and every world
  ever generated would change. Measured, named, not touched.

## 128. Nobody arrives where they cannot leave (v3.68)

§127.6 left this: *a dwarf starved to death beside forty units of food and six
hundred of ale, before and after, and it is the next thing worth chasing.*

Onul Coalgate, day six, seed s3. Everything about it looked like a food
problem and none of it was:

```
day 1  Onul Coalgate  at (38, 32, 2)  hunger 14400  thirst  8656
day 3  Onul Coalgate  at (38, 32, 2)  hunger 43200  thirst   630
day 5  Onul Coalgate  at (38, 32, 2)  hunger 72000  thirst   784
day 6  DEAD: starved to death, at (38, 32, 2)
```

Thirst stays low the whole time. It was drinking, and eating nothing. The
ground around it, tiles and water depth:

```
       soil_wall  soil_wall  soil_wall  water 5   soil_wall
       soil_wall  soil_wall *shallow 2  water 5   soil_wall
       soil_wall  soil_wall  soil_wall  water 5   soil_wall
```

A two-cell ledge of shallow water inside a river channel, walled in by soil at
its own level and by five units of water on the other side. Its component was
two cells. It drank because it was standing in a river, and it starved because
the fortress was three tiles away across water it could not wade.

It did not walk in. It was **founded** there: `Fortress.embark` places the
seven with `_free_spot`, and `_free_spot` asked one question about a tile.

```python
if not self.local.walkable(*cell):
    continue
```

Shallow water is walkable.

### 128.1. The two doors everybody comes through

`_free_spot` places the seven, every migrant wave, the caravan, a siege, a
raid, a thief, a werewolf and every megabeast. It takes the cells in rings
around a point and hands out the *offset*-th one that is walkable and empty.
It now also has to be one the arrival could walk back off:

```python
within = self.reach_from(near) if self.local.walkable(*near) else None
...
if within is not None and cell not in within:
    continue
```

Ahead of that is the other door, and it was seven copies of the same two
lines:

```python
side = fort.rng.choice(["north", "south", "east", "west"])
entry = fort.local.edge_entry(fort.rng, side)
```

Nothing in that asks whether the side it picked can reach the fortress.
Measured over eight embarks, walkable edge cells that can:

```
fort   N 57/57  S 59/59  E 39/39  W 39/39
s3     N 52/52  S 58/58  E 39/40  W 34/34
s4     N 51/51  S 51/56  E 32/34  W 41/41
s6     N  0/55  S 55/55  E 31/37  W 18/34
s8     N 77/77  S 76/76  E 58/58  W 53/53
```

Not one of the fifty-five walkable cells along s6's north edge could reach the
fortress: a river ran between. A quarter of everything that map would ever
see — every migrant wave, every siege, every caravan, the autumn trade —
arrived on the far bank. Migrants who starved where they stood; a siege that
besieged nothing.

`Fortress.edge_arrival` is the one door now, and the seven call sites are one
line each. It draws the side, keeps the cells on it that can reach the wagon,
and only if that side has none does it try the others. **The draw is unchanged
wherever the map is whole**: `rng.choice` over the walkable cells of a side
that all connect is the same choice it always made, so only the maps with a
wrong side of the river move at all — which is why this milestone cost the
tests nothing.

If every edge is cut off, they arrive anyway, on the side they were heading
for. A wall keeps a caravan out; it does not keep it at home.

| eight embarks | before | after |
| --- | ---: | ---: |
| founders placed where they cannot reach the wagon | 1 | 0 |
| arrivals (144 per map) that cannot reach the fortress | 71 | 0 |
| ...of those, stranded in a pocket under 50 cells | 11 | 0 |
| dwarves lost over seven days | 1 | 0 |

### 128.2. And nothing offered that cannot be fetched

Fixing the founding does not fix the rest of it. A dwarf sealed in by a
cave-in, a bridge raised behind it, a river that rose — the fortress hands it
food it cannot get to and it dies looking at the wall. Measured directly:
twenty units of meat sealed two tiles from a hungry dwarf, twenty more it
could walk to, three hundred steps.

It ate neither.

`find_consumable` promised "the nearest food or drink a dwarf could go and
consume" and delivered the nearest in a straight line; `_go_eat` walked at it,
failed to find a route, and asked the same question again next step, for ever.
Both now ask `Fortress.can_reach`, which is the flood fill of §120 rather than
a search — the question is asked of a *list*, and A* charges the size of the
component to say no. The eight cells around the target count, the same way
`at_or_beside` does: a barrel against a wall is drunk from the floor beside
it, and water deep enough to swim in is never walkable at all.

`nearest_water` had the same promise and the same hole, and now shares the
same answer.

The contrast worth keeping: sleep already degraded gracefully. A dwarf that
cannot get to its bed lies down where it stands and takes a "slept on the
floor" thought. Eating had no such floor, so it was the one that killed
somebody.

### 128.3. What the fill costs

`tools/fort` reports it, which is the only reason this is a number and not a
worry. Seven days, per seed:

| seed | nodes and fills before | after | fills |
| --- | ---: | ---: | ---: |
| fort | 35,563 | 49,715 | 0 → 4 |
| s3 | 205,824 | 195,098 | 55 → 12 |
| s5 | 18,994 | 98,394 | 0 → 2 |
| year1 | 463,369 | 492,540 | 9 → 11 |

s5 is the worst case and it is one fortress-week: two fills of a
39,608-cell component. s3 is *cheaper* than it was, because the dwarf that
used to spend five days failing to path to a sealed larder is not there any
more. The cache does the work — a fill is drawn once per component and thrown
away when the map changes shape.

### 128.4. Measured and left

- **A dwarf stranded after it arrives still dies quietly.** The fortress says
  "Your dwarves are starving!" without a name or a place, which is the
  difference between noticing and not. Nothing digs a ramp to fetch them.
- **A bed nobody can reach is still assigned.** `bed_for` claims the first
  free one without asking, and the only reason it does not matter is that
  `_go_sleep` gives up and sleeps on the floor.
- **`_free_spot` will still put somebody in a river** if the river is
  connected to where they came from. Standing in water is not fatal until it
  deepens, and the drowning path already handles that, so this is named rather
  than guessed at.

## 129. Something to bind it with (v3.69)

Eight adventurers, played by `tools/play` on eight seeds. Eight deaths, and
every one of them the same:

```
a1  81 turns  bled to death      a5  121 turns  bled to death
a2  36 turns  bled to death      a6  600 turns  alive
a3  66 turns  bled to death      a7  124 turns  bled to death
a4  60 turns  bled to death      a8   64 turns  bled to death
```

Seven of the eight counted the same two lines in their action tally:

```
'patched itself up': 3, 'bleeding, and nothing to bind it with': 21
```

Three, every time. Three is how many bandages the kit holds.

### 129.1. Clotting had no rate

```python
if rng.chance(min(0.9, 0.0018 * ticks * toughness)):
    w.bleeding = max(0, w.bleeding - 1)
```

A chance per *call* to `Body.tick`, and the game calls it with whatever slice
of time the scheduler happened to hand over: one tick in a fight, four
thousand for a night's sleep. Clamped at 0.9, so a single long call could only
ever close one point. The same twenty-point wound over the same four thousand
ticks of game time:

| ticks per call | points still open |
| ---: | ---: |
| 1 | 13.2 |
| 10 | 13.7 |
| 100 | 13.0 |
| 1000 | 16.3 |
| 4000 | 19.1 |

Sleeping through the night healed less than walking through it. It is banked
time now — `_clot_ticks += ticks * toughness`, a point off every wound per
`CLOT_TICKS` — so an hour is an hour however it arrives.

Fifteen ticks a point, which is a minute and a half, chosen so the two ends of
the model say different things: a three-point scratch closes in a few minutes,
and the twenty-eight points a troll leaves in a thigh take seven hundred ticks
to close on their own, which is a good deal longer than you have. **Small
wounds close. Big ones need a bandage.** Before this, a one-point scratch on a
finger took ten hours of game time to stop and cost two and a half litres
getting there.

One clock, not two. `REST_CLOT_TICKS` was a second constant for lying down,
and the two drifted the moment either moved: at five ticks a point against
`_handle_wounds`'s three-times multiplier it closed six points a *step*, which
out-healed a mortal wound and made the bandage decorative. Resting banks the
same clock now, and the caller's multiplier is the whole of the difference.

`BLEED_PER_POINT` did not move, and the reason is worth writing down. It was
tried at a quarter — the two constants only ever meant anything together, and
with clotting thirty-seven times slower than the bleed every wound in the game
was a slow fatal bleed. A quarter bought an adventurer half again as long to
live: median survival 163 turns against 104. It also made every fight in the
game two to three times longer, because what kills things here *is* bleeding:

| iron sword, blows to put down | 0.004 | 0.001 |
| --- | ---: | ---: |
| wolf | 6 | 12 |
| goblin | 8 | 18 |
| kobold | 7 | 13 |
| human | 6 | 13 |

§126 anchored those numbers deliberately — "a wolf has to cost what a wolf
cost" — and `test_an_ordinary_fight_did_not_move` caught it. How long a fight
lasts is its own question with its own measurement, and it is not a side
effect of fixing the clock on clotting. The rate went back.

### 129.2. And bleeding had no ceiling

`bleeding_rate` was the sum of every open wound and nothing else. Instrumented
through a real troll fight, the player's total:

```
pts  22 -> blood 4.900   pts 183 -> blood 3.872
pts  57 -> blood 4.636   pts 232 -> blood 3.140
pts 134 -> blood 4.408   pts 263 -> blood 1.252 -> 0.200, dead
```

Two hundred and sixty-three points of bleeding is 1.05 litres a tick out of a
body that holds 4.9 and dies at 0.98 — a fifth of your blood every six
seconds. Wounds do not add up like that. A heart can only pump so fast, and
past a certain point more holes do not empty you any quicker.

`BLEED_CAP = 0.03` — three percent of your own volume per tick, thirty percent
a minute: a severed artery, four minutes from whole to dead. It binds only on
a mauling; one bad wound of twenty points still bleeds at its own rate.

### 129.3. The recipe the person bleeding could not make

There is exactly one recipe in the game that answers bleeding:

```python
_r("make_bandage", "Tear a bandage", "crafting", 0, (("cloak", 1),), "bandage", 4)
```

A cloak. The adventurer's starting kit is a sword, a shield, a mail shirt, a
helm, boots, a waterskin, a backpack, food, a torch, a rope, three bandages
and a splint — armour over nothing at all, while `_dress` puts a tunic,
trousers and shoes on every other creature in the world and outerwear on a
third of them. The one person in the world who could not make a bandage was
the one bleeding.

Two changes, both small. The adventurer gets dressed, out of the same
`CLOTHING` list everybody else wears. And a recipe input in capitals now names
a *kind* of thing:

```python
CLASSES: Dict[str, str] = {"CLOTH": "clothing"}

def _satisfies(item, need: str) -> bool:
    if item.def_id == need:
        return True
    category = CLASSES.get(need)
    return (category is not None and item.category == category
            and need in item.mat.flags)
```

Cloth *and* clothing, both halves: a mail shirt is armour, a leather tunic is
not cloth, and a cloth rope is neither — you want the rope for the climb down.
Anything you are wearing is four bandages.

### 129.4. What the driver does with it

`_staunch` used to reach the end of `medical.auto_treat`, hear "there is
nothing you can do", count it and walk on bleeding. It tears up a shirt now,
which is also the first time anything has exercised adventure crafting in
play.

Twenty-four adventurers, six hundred turns each, before and after:

| | before | after |
| --- | ---: | ---: |
| median turns survived | 75 | 104 |
| upper quartile | 171 | 419 |
| alive at the end | 3 of 24 | 4 of 24 |
| bled to death | 21 | 15 |
| died of anything else | 0 | 5 |
| bandages torn from clothing | 0 | 34 |

The line that matters is the last two rows. Before, bleeding was not the
commonest way to die, it was the *only* way to die: twenty-one deaths out of
twenty-one. Now people also die of thirst and of having their upper body
destroyed, which are things that should kill an adventurer.

### 129.5. And the wounded had to lie down

Faster bleeding cost the fortress its hospital, and the trace said why. A
mortal wound, a stocked ward, a trained doctor standing next to the patient:

```
step  2 blood 77%  doctor_job treat  jobs [('treat', (41, 34, -1), 4)]
step  4 blood 63%  doctor_job treat  jobs [('treat', (40, 33, -1), 4)]
step  6 blood 50%  doctor_job treat  jobs [('treat', (40, 32, -1), 4)]
step  7 blood 44%  doctor_job treat  jobs [('treat', (39, 31, -1), 4)]
step 12 blood 20%  dead
```

The job's cell moves every step. `_handle_wounds` sends a hurt dwarf to a
hospital bed, so the patient was walking to the ward while the doctor walked
after it, and the pair of them lost a race neither was running. A dwarf that
is *critical* — bleeding, and under `CRITICAL_BLOOD` — lies down where it is
now. You do not march a haemorrhaging patient across a fortress.

What that buys, with the doctor and the dressings in the ward: measured over
three embarks, ten points of bleeding clot on their own and leave the patient
at half its blood, fourteen kill an untreated dwarf in seven steps and are
bound in five by a doctor standing over it, and twenty are over before anybody
can do anything at all. What it does not buy is a doctor from across the
fortress — a mortal bleed runs out in a minute or two, and the patient dies on
the same step with a stocked ward as without one. That is named below rather
than tuned away.

### 129.6. And two tests that had been passing by luck

Moving the dice moved world history, and two tests fell over that had never
been testing what they said.

`test_travel_screen_says_who_holds_a_place` set the scene's cursor and *then*
pushed the scene — and `Scene.on_enter` puts the cursor back on the player. It
only ever passed while the player happened to be standing on the site it had
just handed a lord to.

`test_the_metal_decides_whether_you_can_cut_bone` asserted `iron == 300`,
which is the number the loop gives up at: a saturating proxy that stops
meaning anything the moment iron gets there in two hundred and ninety-nine,
which is what the new dice did. It asserts the ratio now — copper 300, iron
193, steel 40, adamantine 22, and iron more than three times steel.

There was nearly a third. `if site.owner_hf` reads a site owned by figure zero
as owned by nobody, in `travel_screen`, `legends` and `sitegen` alike, and it
looked like the cause until the ids were counted: historical figures are
numbered from one. The line is unreachable, the change was reverted, and this
paragraph is what is left of it — a fix with no failing case is not a fix.

### 129.7. Measured and left

- **The driver still dies with the answer in its pack.** Of nine runs that
  bled out, four had bandages left (three and four of them) and eight still
  had clothes on. One died in thirty-three turns having never once fought or
  reached for a dressing. `_staunch` binds only below `PATCH_UP_AT` and only
  when nothing is adjacent unless it is below `BIND_IT_NOW`, and between those
  two thresholds it does nothing at all. That is the bot's judgement, not the
  game's, and it is the next thing.
- **Wounds are never cleared while you are awake.** `rest_heal` prunes closed
  wounds and `tick` does not, so a body that fought its way across a map
  carries a hundred and thirty-three of them. Nothing reads the list except
  bandaging and the bleeding sum, so it costs correctness nothing and it is
  still wrong.
- **One bandage treats one body part.** With sixty wounds spread over a dozen
  parts that is a long night, and it is not obvious whether the answer is
  faster dressing or fewer wounds.
- **A doctor across the fortress always loses.** A mortal bleed runs its course
  in one to two minutes of game time, which is not long enough to walk
  anywhere. Either the wounded get carried or somebody is posted in the ward,
  and both of those are a hospital milestone rather than a bleeding one.

## 130. Water to drink (v3.70)

Twenty-four adventurers, six hundred turns each, and what they got done:

```
quests taken 25, finished 1, failed 0
turns spent: fought 1144, working 840, blocked 681, patched itself up 398,
             ... nothing to drink 81, no water on this map 66
```

Take death out of it — hold the player's blood at full and clear their wounds
every tick — and twelve adventurers over two thousand turns each finished two
quests between them, with the turn budget going the same way:

```
nothing to drink 1366, no water on this map 1340
```

Thirteen hundred turns of being thirsty somewhere there was nothing to drink.
So: how much of the world has water on it?

### 130.1. One land tile in eighty

Forty wilderness maps, sampled across a whole world, scanned for a single cell
of water at any depth:

```
maps with water: 0, without: 40
```

Not one. The world map has 2997 land tiles and carves **32 river tiles and 4
lakes** onto them — `_carve_rivers` takes the top `(w*h)/220` highland tiles,
uses half of them as sources, and each river runs three or four tiles before
it reaches the sea or a basin. Everything else is dry, at every scale: dry on
the world map, and dry on the ground when you walk onto it.

`rainfall` is a field the world map has computed since v1, used for biomes and
for nothing else. A grassland under half a metre of rain has water standing in
its hollows.

```python
POND_RAIN = 0.35
POND_RADIUS = (3, 6)
```

`_dig_pond` sinks a pool into the low ground of any wilderness map wet enough
to hold one — the lowest of twenty-four sampled spots, a disc three to six
tiles across, two levels deep in the middle and one at the rim so the edge is
shallow enough to drink from and walk out of.

Dug, not flooded to a level. Filling every column below some height is the
obvious implementation and it does not work: measured over fourteen wet maps,
the lowest height covered anything from four columns to all three thousand of
them, so the same rule gives a puddle on one map and a lake across a whole
plateau on the next. A pool is a hole with water in it, so this digs the hole.

| sixty land tiles sampled | before | after |
| --- | ---: | ---: |
| with water on the surface | 0 | 33 |
| ...and a bank to drink from | 0 | 33 |

The dry ones are shrubland, desert, glacier, savanna and badlands, which is
the point: rain decides, and the drylands stay dry.

### 130.2. The beach with no sea on it

The other half of the same question. Seven hundred and six land tiles on this
world border the ocean, and every one of them generated a local map with not a
drop of water on it — the coastline stopped dead at the tile boundary.
`_fill_columns` set a water level only when the tile *is* ocean or lake.

The heightmap already samples its neighbours' elevation, so the ground on a
coastal map slopes down towards the sea. It just never got wet.

The first attempt flooded those maps to local z 0 and produced this:

```
(48, 4) glacier   elev 0.58 -> land    0  water 3072 (100%)
(64,31) mountain  elev 0.88 -> land  120  water 2947 (96%)
```

Zero is not sea level. The local heightmap measures every column against its
*own* world tile's elevation, so flooding to zero drowns a mountain that
happens to look out over the water. `sea_level_z` is the rule stated once —
`(SEA_LEVEL - elevation) * ELEVATION_SCALE` — and on a cliff top it comes out
below the floor of the terrain, where it touches nothing.

And a land tile keeps its land. The corners of a low coastal map average in
the ocean next door, so the whole of one can still end up under sea level: a
beach at elevation 0.43 came out 100% water with nowhere on it to stand.
`SHORE_DRY` holds the water down to leave two fifths of the map dry. The world
map calls this tile land; the sea comes up to the shore, and the shore is on
the map.

### 130.3. What the guards had to be told

Five fixes, five re-breaks, and four of them passed first time with the fix
taken out — every one because the *fixture* was wrong rather than the
assertion.

The beach test picked the first coastal tile in map order, which had rainfall
0.44 and therefore a pool on it: it passed with the coast turned off, because
a pond was providing the water. It picks the lowest coast on the world now and
asks for five hundred cells rather than one, which is a sea and not a puddle.
The land-keeps-its-land test had the same fixture and the same hole. And the
cliff test picked a coastal tile at elevation 0.68 rather than the highest one
there is.

`_pick` takes a `key` now, so a test about the sea flooding a map asks for the
lowest coast and one about it not flooding a cliff asks for the highest.

The sea-level rule could not be guarded through generation at all: `SHORE_DRY`
pulls the water back down on a high map, so a cliff comes out dry whichever
formula is in place. It is asserted as arithmetic instead — the same shape as
the Nyquist guard in §127 — which is why `sea_level_z` is a function rather
than three lines inside `_fill_columns`.

And one line went the other way. The pool carver skipped columns whose ground
rose more than a level above the pool, so it would not cut a pit into a
hillside. Measured with and without over twelve hilly wet maps: 851 water
cells and two walled-in cells either way. It was doing nothing, and it is
gone.

### 130.4. Measured and left

- **A quarter of the driver's turns are `blocked`.** It walks into things: on
  twenty-four runs, 1058 turns of a random walk that went nowhere. That is the
  bot, not the game, but it is the biggest single line in the tally.
- **An adventurer finishes one quest in twenty-four lifetimes**, and three
  with this milestone's water. Even immortal and given two thousand turns they
  manage two. Whether that is the bot, the quest design or the world being too
  big to cross is the next thing to measure.
- **Rivers are still 32 tiles in 2997.** The pools make the world drinkable;
  they do not make it a landscape with streams in it. `_carve_rivers` gives
  each source three or four tiles before it hits the sea, and a river you can
  follow is a different milestone.

## 131. Who is fighting (v3.71)

A hundred-day fortress run, twice, on two unrelated seeds:

```
day  56: 7 alive, 53 food, 1388 drink
day  84: 0 alive, 31 food, 1889 drink
  deaths  {'bled to death': 7}
FORT OK: year1, 84 days, 0 alive of 7
```

A siege came for a fortress with no military and killed everybody. That is
the game working — the log says "Losing is fun." and means it. What is not
the game working is the account of it. Fifty-seven lines were written while
the fortress died. **Fifty of them said "the dwarf" or "the goblin".** Three
used a name, and two of those three were the death notices:

```
The kobold slashes the dwarf in the upper body with a #steel dagger#, ...
The kobold stabs the dwarf in the right lower leg with a #gold short sword#, ...
Gemid Rockvault has died: bled to death.
```

You cannot tell from that which of your seven is dying, how many raiders
there are, or whether the one that killed your miner is the one now standing
over your mason.

### 131.1. The names were already there

Worldgen names every intelligent creature it makes, and has since there was a
worldgen:

```
name='Gemid Goldsong'       short_name='dwarf'   display_name='Gemid Goldsong'
name='Uzzgul Skullsplitter' short_name='goblin'  display_name='Uzzgul Skullsplitter'
name='Lorn Crane'           short_name='rabbit'  display_name='rabbit'
```

The sidebar has drawn `display_name()` all along, so a player watching a
siege reads "Uzzgul Skullsplitter" in the unit list and "the goblin" in the
log, about the same creature, in the same frame. `display_name` even
documents itself as "how this creature is referred to in messages". Combat
called `short_name()` — "the species name, used when the creature is **not**
known by name".

`Creature.known_by_name` asks the one question — is this a person the game
knows the name of? — and `subject_name` / `object_name` answer it in the two
grammatical roles a sentence needs:

| | player | named | animal |
| --- | --- | --- | --- |
| `subject_name()` | `You` | `Uzzgul Skullsplitter` | `The wolf` |
| `object_name()` | `you` | `Uzzgul Skullsplitter` | `the wolf` |

Same fight, same seed, same fifty-seven lines:

| of 57 log lines | before | after |
| --- | ---: | ---: |
| "the dwarf" / "the goblin" | 50 | 0 |
| somebody named | 3 | 53 |

```
Thugdush Skullsplitter bashes Thob Goldmurdered in the head with a *lead
    mace*, tearing apart the skin, tearing apart the fat, bruising the muscle!
Thob Goldmurdered has died: bled to death.
Nomal Anvilhammer punches Thugdush Skullsplitter in the right upper leg ...
```

The rule already existed, once, for one thing. `mounts._the` — "``the
horse``, but ``Bardur`` for anything that has a name of its own" — is exactly
this, written for mounts and never generalised. It is gone now; mounts ask
the creature like everybody else.

And the README has been promising it the whole time. Its sample screen ends:

```
Snagob the Cruel stabs you in the left lower arm, tearing the muscle, ...
```

which is a line the code could not produce — `_subject` would have written
"The goblin". The same eight lines show a message *wrapped* onto a second
row, which §131.4 is about. The screenshot was written from what the game
ought to look like, and nobody ever diffed it against what it printed.

### 131.2. "Goblin slips."

Five other places built a subject as `short_name().capitalize()` and dropped
the article on the floor: `webs` ("Goblin tears free."), `traps` ("Goblin
sets off a bear trap.", "Goblin slips."), and `ai` ("Giant cave spider throws
a web!", "Goblin snatches a golden crown and bolts."). Every one of them was
written separately, which is the argument for the funnel.

`capitalize()` is also a trap of its own once names arrive:
`"Uzzgul Skullsplitter".capitalize()` is `"Uzzgul skullsplitter"`. That is
why `subject_name` returns the capitalised form itself and its docstring
tells callers not to touch it.

### 131.3. The second mention

Naming both sides breaks one sentence, and only one:

```
Thugdush Skullsplitter bashes at Nomal Anvilhammer, but Nomal Anvilhammer dodges.
```

Blocks and parries never had the problem ("but the blow is parried"); the
dodge is the only line that refers to the defender twice. `Creature.pronoun`
fixes it — `you` / `he` / `she` / `it`. `female` has been rolled for every
creature since creatures could be made, and no line of text had ever asked
it. It keys on `intelligent`, not on `known_by_name`: an unnamed goblin is
still a he or a she.

### 131.4. The half of the sentence that was on the floor

Both message panes drew `frag_slice(msg.display(), 0, w)` — the first *w*
columns, and the rest thrown away. A blow reads

```
<who> <verb> <whom> in the <part> with a <weapon>, <what it did to the tissue>
```

so the half that says how bad it is is the half at the end. Measured over one
fight: median line 55 columns, longest 138, and **twenty-five of fifty-seven
ran past eighty**. `MIN_WIDTH` is 72.

`wrap_frags` — a colour-preserving word wrap — has been sitting in
`screen.py` the whole time and neither pane called it. Wrapping costs rows,
so fewer events fit in the seven-line pane. That is the trade, and half a
sentence is not an event.

### 131.5. FORT OK over a graveyard

`tools/fort.py` printed `FORT OK` on a run where every dwarf was dead. Its
invariants are deliberately about the job board rather than about survival —
"a fortress that plays badly should not be reported as a defect in the game"
— and that is right. But the run *stops* at the last death, so every number
it prints after that is measured on a corpse: the food, the wealth, the beds,
the work left on the board. It says `FORT LOST` now, and exits non-zero.

Two seeds, one outcome, the same fortnight. Whether seven civilians should
survive the first siege is a question about difficulty and it is not this
milestone's; a driver that cannot report the fortress falling is a guard that
cannot fail, and that is.

### 131.6. Measured and left

- **The status line still says "riding horse".** `mount_status` is the last
  `short_name()` left in a sentence, and it is a compact status bar rather
  than prose.
- **A named enemy is named on sight**, because the sidebar already named it.
  Whether an adventurer should have to *ask* before the log calls a stranger
  Uzzgul Skullsplitter is a question about knowledge, and a real one — the
  fortress, where you know everybody, does not have it.
- **The log collapses an exact repeat into one line with a count.** Two
  goblins hitting two dwarves identically used to be one message; naming them
  makes them the two events they always were.

## 132. You cannot bandage your way out (v3.72)

§130.4 left a question: an adventurer finishes one quest in twenty-four
lifetimes, and "whether that is the bot, the quest design or the world being
too big to cross is the next thing to measure". Twenty-four adventurers, six
hundred turns each:

```
quests: 25 taken, 3 finished, 0 failed
turns 5859 over 24 lives -- a mean life of 244 turns
deaths: bled to death 15, lower body destroyed 1, died of thirst 1
```

None of the three. **Seventeen of twenty-four died, fifteen of them bleeding**,
less than halfway through the turns they were given. The quest loop is not
what is stopping them.

### 132.1. Seventeen bandages and a corpse

One doomed life, traced turn by turn:

```
t32  blood  70%  speed 38  bleed 0.147  foes<=6 4 (nearest 1)  -> patched itself up
t33  blood  67%  speed 38  bleed 0.147  foes<=6 4 (nearest 1)  -> patched itself up
 ...  seventeen consecutive turns of it ...
t48  blood  19%  speed 38  bleed 0.147  foes<=6 4 (nearest 1)  -> patched itself up
dead=True bled to death on turn 49
```

The rate reads **0.147 on every one of those turns**, which is
`BLEED_CAP` × 4.9 litres exactly — the ceiling. The obvious reading is that
bandaging is broken. It is not:

```
t39  pts  94.0 ->  79.0 (treat -15.0) ->  88.0 (turn  +9.0)
t42  pts 101.0 ->  86.0 (treat -15.0) ->  99.0 (turn +13.0)
t45  pts  97.0 ->  86.0 (treat -11.0) ->  113.0 (turn +27.0)
```

Each bandage really closes eleven to seventeen points. Four adjacent foes open
three to twenty-seven a turn, the total climbs from forty to a hundred and
twenty-four against a ceiling of thirty-seven, and the rate cannot move until
the total gets back under it. **The treatment works; the turn is wrong.** And
nothing on the screen said so — the three existing warnings are about how much
blood is *left*, a number that keeps moving, and this is the one number that
stops.

`Body.tick` now says it once, and re-arms when the wounds come back under the
ceiling: *"You are bleeding faster than you can bind it."*

### 132.2. Rest was sleep with the guard taken off

`rest` and `sleep` call the same `Body.rest_heal`, for the same ticks. `sleep`
refused when anything hostile was in sight. `rest` asked nothing:

```
wolf adjacent, half the blood gone, ten presses of R:
  1: blood 2.379   2: 2.648   3: 2.917  ...  10: 4.039   (of 4.20)
```

Full, in melee, while the wolf bit thirteen times an hour. The world does get
its hour — both a rest and six waits log the same thirteen wolf attacks — the
healing simply outruns it.

The rule was already written and already named. `Game.hostiles_in_sight` has
guarded reading, writing and fishing since it existed, with a docstring that
says why: "a book is not a thing you finish while somebody is walking towards
you." Sleeping kept its own inline copy of the same test; resting had none. So
you could not read a novel with a wolf nearby, and you could heal to full.
Both verbs ask the one function now.

### 132.3. Four foes sum to nothing

The driver ran away twenty-nine times in five thousand eight hundred and
fifty-nine turns. Two reasons, both in `tools/play.py`:

- `_staunch` is asked before `_run_away` and claimed the turn whenever
  anything was left to bind — which, at the ceiling, is always.
- when it did get asked, the flee step was the **sum of the directions its
  attackers were in**. For four attackers evenly around you that is `(0, 0)`,
  read as "nowhere to run", and it stood in the middle of them. That is the
  one arrangement it most needed to leave.

`_run_away` picks a cell now, scored `(ground gained on the nearest, ground
gained on all of them)`. The second half is what handles the cross: hemmed in
on four sides every step still leaves you touching somebody, so the first
number cannot improve, and stepping diagonally still puts two of them behind
you.

### 132.4. And it did not help

The same twenty-four seeds, before and after:

| | before | after |
| --- | ---: | ---: |
| ran | 29 | 169 |
| patched itself up | 294 | 135 |
| bleeding, and nothing to bind it with | 37 | 0 |
| rested | — | 14 |
| **died** | **17** | **17** |
| **quests finished** | **3 of 25** | **3 of 25** |
| turns lived | 5859 | 5703 |

Running five times as often saves nobody. That is the measurement this
milestone is really for, and it is not about the driver:

```
a wolf chases a man across open ground
  whole      : held at 6 tiles      your speed 91 vs wolf 172
  60% blood  : reached 16 tiles     your speed 92 vs wolf 158
  35% blood  : caught, and killed   your speed 37 vs wolf 167
```

The state in which running is the right move is the state in which running
does not work. By the time the ceiling warning fires you are at a fifth of a
wolf's speed. The decision has to be made earlier than the game gives you any
reason to make it — and *that* is the next thing to fix.

> **Corrected in v3.73.** This section first said "blood loss and pain both
> multiply into `effective_speed`". Blood loss does not: `effective_speed`
> reads standing, broken stance parts, encumbrance, pain, agility, fatigue,
> venom and exposure, and blood reaches it only through `can_stand` once you
> have lost enough to go down. Setting blood to a quarter and changing nothing
> else leaves the number at 92. What collapsed the chased man to 37 was the
> pain and the broken legs he had collected by then. The finding stands; the
> mechanism named was wrong. See §133.

### 132.5. Measured and left

- **The one lever left is not starting the fight**, and the game tells you
  nothing about what a thing can do to you until it has done it.
- **`blocked` is still a sixth of every turn** — 1000 of 5703, the random walk
  going nowhere. Unchanged since §130.4, and still the bot rather than the
  game.
- **Hurt and quiet almost never coincide.** Over twelve lives, ten had *zero*
  turns both wounded and with nothing in sight; the two that had any were the
  two that lived. Resting is a verb for adventurers who are already winning.

## 133. What you can tell by looking (v3.73)

§132 ended on the adventurer dying because the moment to leave passes before
the game gives any reason to notice it. This is the screen a player would
have to notice it on — the look cursor, pointed at a wolf:

```
Maddox Grimsby the wolf
They do not hunt alone.
A an adolescent wolf.
It is in perfect health.
Skills: Skilled Biter and Competent Dodger.
It is wavering.
```

A person's name on an animal, two articles, and not one word about the number
that decides the whole question. The wolf is at 170. The man is at 92.

### 133.1. The roll the player cannot see

`_awareness`, one function above the one this milestone adds, already makes
the argument in its own docstring:

> The single most useful thing a stealth game can tell you, and the only way
> the roll is playable rather than a hidden dice cup: look at the guard and
> find out whether the guard is looking at you.

`effective_speed` is the roll that decides every disengagement in the game and
it appears in **no screen at all** — grep it and every hit is the scheduler.
Meanwhile:

```
of 81 creature kinds: 50 faster than a man, 22 the same, 9 slower
speeds run 70 (zombie) to 210 (giant cave swallow)
```

Fifty of eighty-one, and the only way to find out which was to try to leave.

`_pace_of` says it in bands rather than numbers, because 160 against 100 means
nothing on its own and because *your* end of it moves:

| ratio | line |
| --- | --- |
| ≥ 1.35 | It is much faster than you. |
| ≥ 1.12 | It is faster than you. |
| ~1 | It moves at about your pace. |
| ≤ 1/1.12 | You are faster than it. |
| ≤ 1/1.35 | You are much faster than it. |

A goblin runs at 100 and a whole man at 92 — the same pace, as far as anybody
is concerned. In enough pain the man is in the high fifties and the goblin is
a different problem entirely. The panel says so.

### 133.2. Blood loss does not slow you down

v3.72's help text and §132.4 both said it did. Measured, holding everything
else still:

```
whole, kitted out    92
at 80% blood         92
at 60% blood         92
at 35% blood         92
at 25% blood         92
in a lot of pain     70
```

`effective_speed` reads standing, broken stance parts, encumbrance, pain,
agility, fatigue, venom and exposure. Blood reaches it only through
`can_stand`, once you have lost enough to go down. What collapsed the chased
man in §132.4 from 91 to 37 was the pain and the broken legs he had collected
over those forty turns, not the blood he had lost. **The finding stands and
the mechanism named was wrong**; both places now say pain and a broken leg.

The fix for the class of error, rather than the instance: `_speed_factors`
returns `(factor, why)` pairs, `effective_speed` multiplies them and
`slowed_by` names them. Written out twice they drift, and the copy that drifts
is the one the player reads. The Wounds tab prints both:

```
Pace: 57   slowed by pain and what you carry
```

### 133.3. "A an adolescent wolf."

`age_desc` returned "a baby", "a child", "an adolescent", "a young adult", "an
adult" — and then "middle-aged", "elderly", "ancient". Five with an article
and three without, from one function, and its single caller wrote `"A %s %s."`
in front of whatever came back. So most of the wildlife in the game was
introduced twice.

`with_article` was already in the same file, thirty lines below. `age_desc`
names the stage now and the sentence does the grammar.

### 133.4. The last place that ignored the rule

`full_title` is documented as "name, profession and race for the character
sheet", where the subject is always the player. `Creature.describe` — the look
panel — called it on whatever the cursor was over, which is how an animal came
to be introduced as "Maddox Grimsby the wolf". v3.71 established
`known_by_name` as the one question for this and swept combat, deaths, webs,
traps and mounts; the look panel was the place it did not reach.

### 133.5. Measured and left

- **It still does not say how hard something hits.** Pace is the disengagement
  question; "would I win" is a different one, and armour, weapon and skill are
  already on the panel as facts rather than as a verdict.
- **Nothing warns you when your own pace drops.** The Wounds tab will tell you
  if you look. `Body.tick` warns about blood at three thresholds and about the
  bleeding ceiling since §132; a broken leg is at least as worth an
  interruption, and is not one yet.

## 134. The only thing that could not walk downhill (v3.74)

Three milestones had circled the adventurer's death rate and the last two did
not move it: 17 of 24 dead before v3.72, 17 of 24 after v3.73. So this one
started by asking where a life actually goes, and split the survivors from
the dead:

```
survived: 7 of 24, 4200 turns between them
   blocked 991, working 840, fought 330, on the road to the job 244
```

**A quarter of a surviving adventurer's life was spent walking into things.**
§130.4 had already noticed the line and written it off — "that is the bot, not
the game" — twice. This time it got measured.

### 134.1. What it was walking into

```
764 wandering attempts, 360 of them went nowhere (47%)
what it walked into: open space 356, tree 4
walkable neighbours at the time: 3 of 8 (107), 4 of 8 (136), 5 of 8 (97)
```

Not a wall — air. And the ground one level under that air was walkable 356
times out of 360.

The write-off was half right. The player is on the ground every time
(`p.z - surface_z` was 0 in all 360), and **twenty distinct spots account for
all 360 refusals**, one of them 107 times: the bot lands next to a drop, half
its moves fail, it has no errand to run, and it random-walks in place for
hundreds of turns. That much is the bot.

What is not the bot is the refusal itself.

### 134.2. The graph and the copy of it

`LocalMap.neighbours` is the rule for what a walker can do, and its docstring
says what it is for:

> These edges are deliberately symmetric: if you can get from A to B you can
> get back. An asymmetric graph gives you one-way drops that A* will
> cheerfully route through, stranding whoever took them.

Level ground, up a staircase, down a staircase, up the slope of a ramp you are
standing on, **down onto a ramp on the level below**. Every creature in the
game is moved by it.

`actions.move_or_attack` — the player's own step — reimplemented the up half
and nothing else:

```python
        # Try stepping up onto a ramp or ledge.
        if game.is_passable(nx, ny, nz + 1, p) and tile_data.get(
            game.local.tile(p.x, p.y, p.z)
        ).has("RAMP"):
```

Sorting the 360 refusals by what else could have made that step:

| at a refused step | count |
| --- | ---: |
| **A\* can step down here, the player cannot** | **184** |
| a ramp below, but the step is diagonal — neither can | 99 |
| no ramp at all — nobody can step down | 73 |
| genuinely solid | 4 |

The player was the only thing on the map that could not walk downhill.

`_step_on_the_graph` asks `neighbours` instead of copying it, and the answer
falls through to the same tail as any other step, so a walk down a slope
crosses the same traps, items and water as a walk along one.

```
360 refused steps -> 14
blocked, over twenty-four lifetimes: 1000 -> 162
```

`gravity.SAFE_DROP` is 1 and has been all along: the damage model already said
a one-level drop costs nothing while the movement model said you cannot go
that way.

### 134.3. It made the death rate worse

Honestly, and by a lot:

| twenty-four lifetimes | before | after |
| --- | ---: | ---: |
| died | 17 | 22 |
| mean life, turns | 238 | 196 |
| turns `blocked` | 1000 | 162 |
| turns `fought` | 874 | 1608 |
| world squares visited | 270 | 270 |
| quests finished | 3 | 3 |

Nobody died of a fall — the causes are the same three as before, twenty of
them bleeding. What changed is that the driver stopped standing in a corner
for a quarter of its life, and standing in a corner is an extremely safe way
to live. The dead now last 159 turns each rather than 88 and see more of the
world on the way; the two that lived finished both of the quests they took.

This is a fix to a defect, not a balance change, and the number it moved is
not the number a balance change would move. The adventurer's survival is
still the open question it was in §132 — but it is no longer being measured
through a driver that spent a quarter of its life facing a wall.

### 134.4. Measured and left

- **Diagonal ramps.** 99 of the 360 were a ramp one level down on a diagonal.
  `neighbours` offers ramp-up orthogonally only, so allowing ramp-down
  diagonally would break the symmetry the graph exists to keep. Both halves
  would have to move together.
- **73 bare one-tile cliffs**, where the terrain drops a level with no ramp
  and nothing can get down. `_dig_pond` and the heightmap make these; whether
  worldgen should ramp its own slope edges is a terrain question.
- **An unknown tile id is silently a floor.** `tiles.get` defaults to `floor`,
  which is right for reading an old save with a retired id in it, but
  `set_tile(x, y, z, "wall")` — there is no tile called `wall` — quietly
  writes walkable ground. It cost an hour in this milestone's own test bench.
  Audited: the game writes 28 distinct tile ids and every one of them exists,
  so there is nothing to fix today.

## 135. The wound that stopped hurting (v3.75)

Four milestones had gone at the adventurer's death rate from outside. This one
asked the RPG question instead: does an adventurer who lives ever get any
better at it? Twenty duels against a goblin at each rung of the sword ladder:

| sword skill | won of 20 | rounds | blood you lose |
| ---: | ---: | ---: | ---: |
| 0 (Dabbling) | 14 | 33.0 | 0.92 l |
| 6 (Talented) | 19 | 31.1 | 0.85 l |
| 15 (Legendary) | 20 | 28.5 | 0.27 l |

Skill works. It decides whether you win and it decides what winning costs —
three and a half times the blood between the ends of the ladder. What it
barely touches is how long the fight takes, and following that led somewhere
else entirely.

### 135.1. Eleven swings after it is over

A legendary swordsman saturates a goblin's bleeding ceiling in 2.0 rounds and
a man who has never held a sword takes 8.9 — the skill system doing exactly
what it should. Then both of them stand there for another twenty-four rounds
while the goblin bleeds out, and it fights back the whole way:

```
round   foe blood  foe pain  foe speed  wounds  blows landed on you
  1       1.00       0.070      92         1            1
 10       0.91       0.320      83         6            4
 20       0.75       0.500      76        12           11
 30       0.54       0.430      78        16           21
 35       0.51       0.380      80        16           26
```

Read the pain column. It peaks at 0.50 on round twenty and **recedes** to 0.38
by round thirty-five, while the wounds go from twelve to sixteen and the blood
from three quarters to a half. And `effective_speed` reads pain (§133), so the
goblin gets *faster* as it is cut apart: 76 back up to 80.

### 135.2. A rate per call is not a rate

```python
w.pain = max(0, w.pain - max(1, int(ticks * 0.02)))
```

At one tick, `int(1 * 0.02)` is zero, the floor of one fires, and the wound
sheds **fifty times** the pain the number names. The same wound, the same
hundred ticks of game time, four wounds of twenty-five pain each:

| how the hundred ticks arrived | wound pain left |
| --- | ---: |
| one tick at a time | **0** of 100 |
| ten at a time | 60 |
| fifty at a time | 92 |
| all at once | 92 |

Adventure mode hands out about one tick a turn — a turn is 1.1 ticks — and the
fortress steps ten. The same wound on the same body stopped hurting an
adventurer almost at once and went on hurting a dwarf.

§129 found this exact shape in clotting and said so at the time:

> It was a coin flip per call to `Body.tick` — `rng.chance(0.0018 * ticks)` —
> and the same wound over the same four thousand ticks of game time came out
> at 13.2 points still open if time arrived one tick at a time and 19.1 if it
> arrived in one lump.

It banked the time and fixed clotting. Pain is the other half of the same
loop, four lines further down, and was not swept. `_pain_ticks` banks it the
same way, and `PAIN_FADE` is the rate written where it can be read.

After, all four deliveries agree at 92 of 100, and the fight reads the way a
fight should:

| round | pain before | pain after | speed before | speed after |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 0.32 | 0.40 | 83 | 80 |
| 20 | 0.50 | 0.61 | 76 | 72 |
| 30 | 0.43 | **0.69** | 78 | **69** |
| end | 0.41 | **0.76** | — | — |

Pain rises the whole way now and speed falls and stays down. A creature is
worse off at the end of a fight than in the middle, which is what being
wounded is supposed to mean.

### 135.3. What it did not move

The anchor §126 set — an ordinary fight has to cost what it cost — is
untouched, at every rung of the ladder:

```
skill   rounds to death   before / after
0            31.4  /  31.4
6            29.6  /  29.6
15           27.6  /  27.6
20           26.3  /  26.3
```

The duel harness hands both sides one blow a round whatever their speed, which
is why the length does not move there; in the real game the scheduler reads
`effective_speed` and a wounded thing acts less often. Over twenty-four
adventurer lifetimes that came out as noise — 21 dead of 24 against 22, mean
life 205 turns against 196 — with more of the time going on `patched itself
up` (276 → 509) and `could not set out` (188 → 420), which is what being hurt
for longer looks like. Three fortress seeds ran seven days with seven alive.

Like §134 this is a correctness fix rather than a balance change, and the
number it moved is not the one a balance change would move.

### 135.4. Measured and left

- **Nothing gives up.** A goblin at half its blood with sixteen open wounds
  lands blows at the same rate as a fresh one; what changed here is the pain
  and the speed, not the will. Morale exists and `_nerve_of` reads it for the
  look panel, but no creature has ever surrendered or been beaten into
  submission.
- **`PAIN_BODY_FADE`** lets the body's own shock settle faster than the wounds
  under it, floored at their sum. The number is asserted only through that
  floor; how fast shock *should* pass is its own question.
- **Blood loss still does nothing but kill you.** §133 established it does not
  slow you; it does not sicken, weaken or blur you either. A creature at a
  third of its blood fights exactly as well as one at full until the moment it
  falls over.

## 136. Nothing ever gave up (v3.76)

§135 left it: "no creature has ever surrendered or been beaten into
submission." The machinery is all there and all wired — `pick_mode` asks
`combat.opportunity_to_flee`, which asks `morale.broke`, which asks
`morale.nerve` — so the question was only ever whether it fires. Eight
adventurer lifetimes, every creature-turn spent within eight tiles of the
player and hostile to them:

```
kind             turns   broke   lowest nerve
skeleton          743      0       1.00
ghoul             258      0       1.00
kobold            232      0       0.49
wolf              222      0       0.39
goblin snatcher   194     86      -0.01
necromancer       104      0       0.49
bandit            102      0       0.42
```

1908 creature-turns, and the only thing that ever broke off was the goblin
snatcher — which is a thief and was always going to run. The wolf got to 0.39
and the bandit to 0.42, against a `BREAK_AT` of 0.35, and neither ever
crossed it.

### 136.1. The floor was the ceiling

```python
left = creature.personality.bravery_factor()
left *= 0.35 + 0.65 * creature.body.health_fraction()
```

That bottoms out at `bravery * 0.35`, and `BREAK_AT` is 0.35. **Anything with
a bravery factor of 1.0 or better could not break at any wound**, down to and
including having no body left. Sampling a hundred of each: the median goblin
rolls 1.14, the median dwarf 0.97, the median human 0.82.

The two 0.35s are the same number by accident rather than by intent — one is
"what is left of your nerve when your body is gone" and the other is "where
nerve gives out", and nothing says they should be equal. `HURT_FLOOR` is the
first of them, written down at 0.05, and the ladder comes out:

| bravery | breaks below | with half its blood gone |
| ---: | ---: | ---: |
| 0.50 | 68% health | any wound at all |
| 0.85 | 38% | 69% |
| 1.14 | 27% | 50% |
| 1.50 | 19% | 36% |

A fresh creature still sits exactly at its bravery factor, so nothing about
what walks up to you changed — only what walks away.

### 136.2. Blood, at last

§135 ended on "blood loss still does nothing in this game but kill you": it
does not slow you (§133), it does not weaken you, and it did not frighten you
either. `health_fraction` is structure, which is a different question — a body
opened in twenty places can be intact and nearly empty at the same time, and
the nerve calculation only ever saw the first half.

`BLED_NERVE` subtracts half a point of nerve at no blood left, pro rata. It is
the second column of the table above.

### 136.3. Who is exempt, and on purpose

The commonest enemy in both modes is not covered by any of this, and should
not be. The goblin's entry in `creatures.py` says why:

> Cruel, tireless and unaging. **They do not fear death.**

`NO_FEAR` is a design statement written in the data, and the undead, the
megabeasts and the demons carry it for the same kind of reason — fifteen of
eighty-one kinds in all. This milestone did not touch the list, and a test
pins it so that a later one does not drift into it by accident.

Measured again after the change, the same eight lifetimes:

| | before | after |
| --- | ---: | ---: |
| creature-turns facing the player | 1908 | 1905 |
| broke off | 86 | 181 |
| ...of those, something other than a thief | **0** | **63** |

### 136.4. It did not move the death rate either

Three milestones running now:

| twenty-four lifetimes | v3.74 | v3.75 | v3.76 |
| --- | ---: | ---: | ---: |
| died | 22 | 21 | 22 |
| mean life, turns | 196 | 205 | 190 |
| quests finished | 3 | 2 | 3 |

And the reason is in the table at the top of this section. **The two things
the adventurer spends most of its life fighting are skeletons and ghouls** —
743 and 258 creature-turns of 1908, more than half between them — and both are
fearless on purpose. Morale cannot reach the thing that is killing
adventurers, because the thing that is killing adventurers is undead. That is
worth knowing before the next milestone goes looking for the death rate again.

### 136.5. Measured and left

- **Nothing surrenders.** Breaking off is the whole of it: a creature that has
  had enough runs, and if it is cornered it fights on to the death. Yielding,
  being taken prisoner and begging for quarter are all still absent.
- **A coward flees on sight**, and always has: a fresh creature's nerve is its
  bravery factor, so a bandit rolling below 0.35 leaves before anybody touches
  it. That is arguably correct and it is certainly untouched by this
  milestone; it is written down here because it cost an hour in the test
  bench.
- **`PACK_ALONE` is a big number.** A lone wolf is docked 0.45 and starts at
  0.38, which is close enough to the line that half of them will not engage
  at all. v3.49 chose it deliberately; whether it is still right after the
  floor moved is a separate measurement.

## 137. The manual is a promise (v3.77)

§136 ended by pointing at the adventurer's death rate and saying not to go
back at it, so this one went at the other mode — and at the one artifact in
the game that had never been audited at all.

The help screen is where a fortress player gets the figures they plan with.
There are about sixty sentences in it carrying a number. **Nothing had ever
checked one of them.** Thirteen were pulled out and put to the code, and
three were wrong.

### 137.1. "A dwarf drinks about one unit a day"

It does not. Four fortresses, twelve days each, counting the barrels:

```
r1: 7 dwarves, food 1.04/day each, drink 1.54/day each
r2: 7 dwarves, food 0.98/day each, drink 1.67/day each
r3: 7 dwarves, food 1.01/day each, drink 1.58/day each
r4: 7 dwarves, food 1.00/day each, drink 1.54/day each
```

Food is exactly what the manual says. Drink is **half again** what it says,
on the resource the same page calls "the difference between a fortress and a
graveyard".

The constant is `THIRST_URGENT`, in `fortress/dwarf.py`, and it is 9000
against a 14400-tick day: **1.60 drinks a day**, which is the measured 1.58 to
within the rounding. (`needs.THIRST_THIRSTY` is a different number for a
different mode — it is when an adventurer is *told* they are thirsty. Doubling
it moves the fortress rate by nothing at all, which is how this paragraph came
to be written twice.)

The embark knew the truth the whole time. A hundred and fifty units of ale is

```
150 / (7 dwarves x 1.58 a day) = 13.6 days
150 / (7 dwarves x 1.00 a day) = 21.4 days
```

— so "you embark with a fortnight of both" is *correct*, and correct only at
the rate the sentence three words earlier denied. The stockpile was balanced
against the real number and the prose against an imagined one.

### 137.2. Two more

**"You can wade through two and you drown in seven."** `SWIM_DEPTH` is 4, so
three is still wading; and drowning is not a depth at all — past 4 your feet
leave the bottom and `DROWN_TICKS` starts counting, which is a thing that
happens to bad swimmers rather than a thing that happens at seven.

**"Mounted you carry half again as much."** `CARRY_SHARE` is 1.6. "Half again"
is a rounded English phrase for 1.5 and the constant is deliberate — the
sentence moved, not the number.

### 137.3. What was already true

Worth listing, because an audit that only reports its hits is not a
measurement:

| claim | code |
| --- | --- |
| Seven dwarves arrive with a wagon | 7 |
| two dogs, a cat, two cows and two sheep | exactly that |
| a dwarf eats about one a day | 1.01 |
| you embark with a fortnight of both | 13.6 and 15.0 days |
| a farm plot feeds roughly six dwarves | 7.7 |
| water has depth, from one to seven | `MAX_DEPTH` 7 |
| one level is a step | `SAFE_DROP` 1 |
| a sheriff needs eighteen dwarves | `at_population` 18 |
| thirty personality facets and twenty values | 30 and 20 |
| an alarm carries forty tiles | `ALARM_RANGE` 40 |

Ten of thirteen. The manual is mostly honest, which is why the three that
were not had gone unnoticed.

### 137.4. The guard is the point

Correcting three sentences is worth an afternoon. What is worth more is that
`TestTheManualIsAPromise` now pins each of these to the constant behind it:
change `SWIM_DEPTH` and the test that reads the wading sentence fails, change
the thirst clock and the test that counts barrels fails. The manual is a
checked artifact now rather than prose that happens to sit near the code.

The drink test measures rather than reads: it embarks a fortress, runs eight
days and counts what went out of the barrels, because the clock rate (2.00)
and the rate a player experiences (1.58) are different numbers and the player
only ever sees the second one.

### 137.5. Measured and left

- **Fifty-odd numeric sentences are still unpinned** — the ones about combat
  timing, temperature, skill ladders and world generation. Thirteen was what
  fitted in one milestone; the class is set up to grow.
- **The siege gives forty minutes.** Measured from the announcement to the
  first blow: an army lands 23 tiles out and is on the dwarves in 40 steps,
  2.8% of a day. That is not enough to raise and arm a militia, and it is not
  meant to be — the DEFENCE section says to have one standing before you are
  worth robbing. Checked, correct, left alone.
- **Undead are 12% of what spawns and 58% of what an adventurer fights.**
  §136 wondered whether there were too many of them; there are not. They are
  simply relentless, which is what being undead is for. 129 of 1107 creatures
  across eight lifetimes.

## 138. What decides how fast you swing (v3.78)

§137 pinned thirteen of the manual's numbers and left "fifty-odd numeric
sentences still unpinned — the ones about combat timing, temperature, skill
ladders and world generation." Ten more went to the code here. Seven were
already true. The three that were not were all about weapons, and all three
turned out to be the same wrong belief written down four times.

### 138.1. The belief

> a dagger swings half again as often as a sword — `FASTEST`/`SLOWEST`
>
> A dagger is most of two blows to a sword's one — `attack_cost`
>
> A maul is worth nearly two sword-blows of somebody else's time —
> `AttackResult.cost`
>
> A dagger swings half again as often as an axe — the manual

None of it is true, and the table says so. `swing_time` is `prepare +
recover` **on the attack**, against a `BASELINE_SWING` of 6, and every weapon
in the game draws from the same five attacks:

| attack | untrained cost |
| --- | ---: |
| stab, lash | 66 |
| slash | 100 |
| hack, bash | 133 |

A dagger and a sword both slash and both stab, at exactly the same two
prices. **A dagger is not faster than a sword at all.** An axe is slow because
every attack it owns is a hack or a bash, and a great axe has only the hack.
What a lighter weapon buys is the *option*: a spear, a halberd, a morningstar
and a pick each carry a stab beside their heavy attack and can choose; a maul
cannot.

`heft` charges for weight only past what the wielder can comfortably swing,
and a strength-1008 human is past it with none of these — so the "costs run
with weight" story, which is what the four comments were all reaching for,
does not apply to a man holding anything in the item table.

### 138.2. Three measurements it took to get there

Worth recording, because two of the three were wrong and the third only
looked right:

1. **Comparing weapons by one attack each.** `choose_attack(f, w, RNG("a"),
   f)` is a coin toss between a weapon's attacks. Comparing a dagger's draw
   against an axe's draw gave 66 against 133 and "a dagger swings twice as
   often as an axe" — which is true of *those two attacks* and says nothing
   about the weapons.
2. **Forgetting that cost depends on the fighter.** The tiers are 66/100/133
   untrained, 59/89/118 at skill five and 55/73/98 at legendary. The first
   version of this milestone's own test asserted 66/100/133 flat and failed
   on a fighter with skill — which is how the dependency was noticed at all.
3. **Only then**: cost per *named attack*, for a stated fighter, across every
   melee weapon in the table. Every attack costs the same on every weapon
   that has it, and that is the whole rule.

### 138.3. "Against plate the five best weapons are all blunt"

Also wrong, and it took three attempts to establish honestly.

The first measurement armoured four body parts and counted wounds anywhere,
which put the great axe first — because it was taking legs off, not defeating
the breastplate. Aiming at the armoured part instead:

```
1500 blows each, aimed at an upper body in an iron breastplate
   halberd            edge          0.471
   morningstar        blunt/edge    0.399
   warhammer          blunt         0.338
   maul               blunt         0.310
   spear              blunt/edge    0.287
   ...
   sword              edge          0.074
   great_axe          edge          0.000
```

The best anti-plate weapon in the game is an **edge-only halberd**, and a
great axe gets *nothing* through — which is exactly what `_armour_absorb`'s
docstring says should happen: "A great axe hands a breastplate the whole
length of its edge and the plate takes almost all of it; a spear point hands
it a few square millimetres and goes through."

So the model is right and richer than the sentence: impact always transmits
something through plate (`blunt_cap`), and a *point* concentrates on an area
too small to spread. Hammers and spikes get through; cutting edges do not.
The sentence immediately before it in the manual — "bring an edge to an
unarmoured man, a point to one in mail, and a hammer to the one in plate" —
was right all along, and the next sentence overreached past it.

### 138.4. Measured and left

- **Forty-odd numeric sentences are still unpinned.** Two passes have taken
  twenty-three of them and found six wrong, which is a rate worth continuing.
- **`heft` never fires for a human.** Every melee weapon in the table is
  inside a strength-1008 human's comfortable swing, so `HEFT_PENALTY` only
  ever charges a kobold or a child. The constant is doing something; it is
  not doing it to the player.
- **`pick` is the only weapon whose cost does not fall with skill**, because
  it is not covered by any weapon skill the test raised. Whether a miner
  should get better at swinging a pick at people is a question about the
  skill table.

## 139. The skill nobody could have (v3.79)

§138 left the skill table as an open question — "whether a miner should get
better at swinging a pick at people is a question about the skill table" — so
the table got the declared-but-unreachable treatment §99 is named for.

The pick turned out to be fine: every melee weapon in the game maps to a real
skill and every one of them gains experience from being swung, measured over
forty blows each. Two other things did not survive the look.

### 139.1. The pikeman who mined

```python
_s("pick", "Pikeman", "weapon", _MELEE_ATTRS, "Mining tools turned to war.")
```

Its own description says what it is for. A pike is governed by `spear`, whose
skill is called Spearman, and there is no `pike` skill at all — so the name
was free to sit on the wrong weapon without ever colliding with anything. A
dwarf who fought with a pick was listed as a pikeman on the character sheet
and in the units list. It is `Pick User` now.

### 139.2. Misc. Object User

`misc_weapon` was defined once, in `skills.py`, and referenced **nowhere else
in the game**:

```
   misc_weapon   Misc. Object User   mentioned 1 times in the source
```

Nothing could reach it, for two separate reasons. `Inventory.slot_for` put an
item in a hand only when `defn.category == "weapon"`, so there was no way to
be holding anything else; and `skill_for_attack`, asked about one anyway,
answered `wrestling` — which is the skill for having nothing in your hands at
all.

It is a real feature and it was three-quarters built. `compute_momentum` has
always added whatever is in the hand to the blow by its mass, so the physics
of hitting somebody with a chair were already there and waiting. What was
missing was permission to hold one, a skill to be bad at it with, and an
attack that is not a punch.

| | before | after |
| --- | --- | --- |
| wield a chair | "You cannot wear or wield that." | "You wield a slate chair." |
| skill | `wrestling` | `misc_weapon` |
| attack | `punch`, cost 55 | `club`, cost 133 |
| the message | "kicks Ustnok in the leg with a slate chair" | "clubs Ustnok in the leg with a slate chair" |

Over five hundred blows: bare hands 0.26 severity, a chair 1.37, a sword 1.47.
A chair is nearly a sword's damage and swings at two thirds of an axe's speed,
which is the trade: it is what you grab when you have nothing, and you put it
down when you find a sword.

### 139.3. Three things measured wrong on the way

- **`SWINGABLE_VOLUME` was guessed at 60000** on the assumption that a chair
  was 15000 and a statue half a million. A chair is 2000, a boulder 3000, a
  table, bed and log 4000, a coffer 5000, a barrel 6000 — and a statue is
  30000. The guess let you fight with a statue. Read off the table, the line
  is 8000.
- **The verb was "swings"**, which produced "swings Ustnok Eyegouger in the
  right lower leg". Every other verb in the attack table is transitive on the
  victim, because the message is `"%s %s %s in the %s"`. It is "clubs".
- **A sandwich is worse than a bare fist** over five hundred blows (0.16
  against 0.26) and better over a hundred and fifty (0.31 against 0.23). A
  wide soft swing against a narrow hard one is close enough that the ordering
  is noise at any sample size the suite can afford, so the test asserts the
  two orderings that hold and says in a comment why it does not assert the
  third.

### 139.4. Measured and left

- **Nobody picks anything up.** The player can wield a chair; no AI ever will,
  and a dwarf whose axe is taken does not reach for the furniture. The rule
  exists now; deciding to use it is a separate question.
- **A chair is nearly as good as a sword.** Slate is heavy and the damage
  comes off mass, so a stone chair hits about as hard as an iron blade and is
  simply slower. Whether improvised weapons should be worse than that is a
  balance question and this milestone did not answer it.
- **Forty-odd of the manual's numeric sentences are still unpinned** — this
  one went at the skill table instead. Three passes have taken twenty-three
  claims and found six wrong.

## 140. The barrel it set out for (v3.80)

Since §131 the hundred-day fortress had ended the same way every time: seven
alive on day fifty-six, none on day eighty-four, every one of them bled to
death. v3.71 made the driver report that honestly (`FORT LOST`) and left the
question open — was that the game, or the script?

It was the script. `tools/fort.py` plays what a competent player does in a
first year, and a competent player raises a militia; the manual's own DEFENCE
section says so, and §137 measured that a siege is on you forty steps after it
lands. The driver had no soldiers at all.

`_raise_the_militia` builds a barracks, forms a squad and enlists the last two
dwarves on the list — the last two because the first few are the miners, and a
fortress that puts its only miner under arms never finishes its stairway.

| year1, a hundred days | before | with a militia |
| --- | ---: | ---: |
| outcome | LOST on day 84 | ran the full hundred |
| alive | 0 of 7 | 3 of 7 |
| wealth | 22633 | 31210 |

### 140.1. And then it found this

The first defended run did not report OK. It reported the driver's own
invariant, the one written in §119 for exactly this:

```
FORT PROBLEM: died of thirst on a map with 360 cells of water
drink in store: 1474
```

A dwarf died of thirst on day sixty-four with fourteen hundred units of ale in
the fortress. Not trapped: it could reach 14629 cells, including everybody
else, and `find_consumable` handed it a barrel every time it was asked. It
simply never arrived. Forty steps of it:

```
(36,21,-2), (36,20,-3), (36,21,-2), (36,20,-3), ...
2 distinct cells over 40 steps
```

### 140.2. Three wrong answers first

Worth writing down, because each was plausible and each was measured away.

1. **"It is walled in."** No — 14629 reachable cells, and the other dwarves
   among them.
2. **"`vertical=False` stops it changing level."** No — that flag restricts
   which cell you may *stand on* to reach a thing, so you cannot pick a barrel
   up through the ceiling. The route may still use ramps, and
   `path_to(vertical=False)` returned True.
3. **"A\* gives inconsistent first steps."** No — planned from either cell,
   the route was correct and forward:

   ```
   from (36,20,-3) -> [(36,20,-3), (36,21,-2), (36,22,-2), (36,23,-2), ...]
   from (36,21,-2) -> [(36,21,-2), (36,22,-2), (36,23,-2), (36,24,-3), ...]
   ```

### 140.3. What it actually was

`find_consumable` measures from where the dwarf is standing, and the dwarf
asked again every single step:

```
standing at (36,20,-3) -> ale  at (36,33,-3)
standing at (36,21,-2) -> milk at (40,8,-2)
```

The z-term in that distance is three tiles a level. Stepping up the ramp put
the ale three further off and the milk three nearer; stepping back down did
the reverse. Two drinks either side of one ramp is a trap with no way out of
it, and the dwarf walked up and down until it died.

`DwarfState.errand` remembers what it set out for. `_errand_item` keeps that
choice while the item is still there, still the right kind and still
reachable, and picks again only when one of those stops being true. Choosing
the nearest was never wrong; choosing it *again from the new cell* was.

```
before: died of thirst on day 64, 1474 units in store
after : nobody got thirsty in a hundred days
```

| year1, a hundred days | before | militia | militia + errand |
| --- | ---: | ---: | ---: |
| outcome | LOST day 84 | PROBLEM | **OK, ran the hundred** |
| alive | 0 of 7 | 3 of 7 | **6 of 7** |
| wealth | 22633 | 31210 | **36311** |

More than seven have died in that last run and six are alive, which is what a
fortress that survives long enough to take migrants looks like.

### 140.4. And the driver found a third one

Adding seed `alpha` to the driver ritual turned up the same invariant again,
on a seed that breaches a magma pipe on day one:

```
FORT PROBLEM: died of thirst on a map with 360 cells of water
```

Not a regression -- v3.79 fails the same seed harder. And not the errand
either: with `_errand_item` reverted the run is identical, the fill and A\*
agree here, a fresh fill changes nothing, and stepping `_handle_needs` by hand
walks the dwarf straight at the ale. The stale-`reach_from` theory was wrong.

It is one line further up. `take_turn` asks `_flee_water` first, and fleeing
takes the whole turn -- including when it finds nowhere better and moves
nowhere at all. `_magma_near` is true of a cell and the eight around it, so
with nine thousand cells of loose magma the dwarf is permanently *near* it
while standing on safe ground:

```
take_turn    : 30 turns,  1 distinct cell,  thirst 18304 throughout
_handle_needs: 30 steps, 14 distinct cells, thirst 18304 -> 5504
```

Its own cell held no magma, and `_desperate` was already true of it.
`_hold_position` has consulted that predicate since it was written; this had
never asked. It does now -- but only while the danger is next door rather than
underfoot, because no thirst is worth a turn spent standing in magma. Pathing
refuses magma and deep water outright, so letting the needs run cannot walk
anybody into either.

`_magma_near`'s own docstring predicted this failure exactly -- "a dwarf that
runs from that runs for ever, back and forth, until it dies of thirst beside a
barrel of ale" -- and fixed it for the sealed pipe and the magma sea. Loose
magma was the case left over.

| seed alpha, seven days | v3.79 | militia + errand | + the floor |
| --- | ---: | ---: | ---: |
| outcome | PROBLEM | PROBLEM | **FORT OK** |
| alive | 0 of 7 | 2 of 7 | **4 of 7** |
| died of thirst | 3 | 2 | **0** |
| burned to death | 4 | 3 | 3 |
| days survived | 4 | 7 | 7 |

The three who still burn are the ones the magma actually reaches, which is the
game working. Nobody dies of thirst on that map any more.

### 140.5. Measured and left

- **The fixture skipped five times out of five** on the first attempt, because
  it looked for open ground either side of a dwarf and an embark is a
  hillside. A skipped test is more dangerous than a red one; it cuts its own
  corridor now.
- **`errand` is not serialised**, like `path` and `path_goal`. A reload
  re-decides once, and re-deciding once is not what did the damage.
- **The same shape may be elsewhere.** Anything that picks "the nearest" every
  step and moves one tile between picks can oscillate. `_go_pray`, the job
  board's `_claim_job` and the hauling destination all choose by distance; none
  of them were measured here.
- **The thirst invariant is a proxy.** `tools/fort.py` reports a defect when
  anybody dies of thirst on a map with any water cell anywhere on it. It has
  now caught two real bugs, so it earns its place -- but what it measures is
  the map, not whether that dwarf could have drunk, and a fortress being
  destroyed is not a defect in the game. Sharpening it is its own milestone.
- **The fuzz driver does not replay.** `tools/fuzz.py` says "each run is
  seeded, so a failure can be replayed exactly". It is not: six runs of
  `--mode adventure --seed 11` on identical source gave 447 keys three times
  and 835 three times. Strictly two values, so one binary decision is
  flipping rather than the whole run drifting. It is not hash randomisation
  (`PYTHONHASHSEED=0` gives both) and not the worldgen screen's clock-derived
  seed at `ui/worldgen_screen.py:143` (pinning it gives both). The suspect
  left standing -- iteration over a container of objects hashed by identity,
  whose order moves with the allocator between processes -- is unconfirmed.
  Two consequences: a fuzz failure may not replay, and fuzz key counts are not
  comparable between runs, which is how this was found. Fortress-mode seeds
  gave identical counts across two rituals; only adventure varied.
- **`tools/play.py --seed play` reports a defect that is not one.** The
  adventurer is killed by a wolf on turn 36, so thirst reaches 36 of the 100
  the check wants and it prints "needs never moved: the clock is not running".
  Identical output on v3.79, byte for byte; the same proxy problem as above,
  at the other end of the game. Left for the same milestone.

## 141. A run you cannot replay (v3.81)

`tools/fuzz.py` has said this since it was written:

> Every run is seeded, so a failure can be replayed exactly.

It was not true. Six runs, same source, same seed, same key count:

```
835, 447, 835, 835, 447, 835
```

Strictly two answers, so one binary decision was flipping. That is worse than
an ordinary bug: the fuzzer is the thing that finds crashes nobody thought of,
and a crash it reports against seed 11 has to still be there when you run
seed 11.

### 141.1. Two wrong answers first

- **String hash randomisation.** `PYTHONHASHSEED=0`, six more runs: still
  bimodal. Not it.
- **The clock-derived seed.** `ui/worldgen_screen.py` falls back to
  `int(time.time() * 1000)` when the seed box is empty, and random keys can
  empty it. Spying on `_generate` showed the seed it actually used was `'11'`
  every time. Never taken.

### 141.2. What it was

The spy that ruled out the clock also, accidentally, made the run
deterministic -- because it set `ASCII_WARRIORS_SAVE_DIR` to a scratch
directory, which the plain command line did not.

`tools/fort.py` and `tools/play.py` both redirect their saves. `tools/fuzz.py`
and `tools/smoke.py` did not. So a fuzz run read, and wrote, the player's own
save folder:

| the folder the run started with | keys consumed |
| --- | ---: |
| empty | 459, four runs of four |
| held at 144 files | 447, four runs of four |
| left as the ritual left it | 447 and 835, alternating |

Hold the directory still and the run is perfectly repeatable. It was never the
game that was random.

One saved fortress is the whole of it -- 459 becomes 835. A fortress on disk
puts another entry on the title screen, and the fuzzer navigates that screen
by counting keystrokes, so every key after it lands somewhere else. Ninety
saved *worlds* change nothing; one `.awf` changes everything. That is why the
ritual saw it: it runs `fuzz --mode fortress` and `fuzz --mode adventure`
alternately, and the fortress run writes the `.awf` the adventure run then
trips over.

### 141.3. The part that is not about testing

The drivers were writing into the player's real save folder. This repository's
had accumulated 144 files -- 69 worlds, 48 fortresses, 27 characters -- every
one of them litter from a verification run. Anybody who ran the fuzzer once
got a world they never made in their save list.

`tools.scratch_saves()` is one funnel that all four drivers call first. It
uses `setdefault`, so replaying a failure against a chosen directory still
works, and it lives in `tools/__init__.py` where the next driver cannot avoid
finding it.

### 141.4. A guard that had to be rewritten to be one

The obvious end-to-end guard is to run the same seed twice with the folder
dirtied in between and diff the screens. Measured with the funnel removed,
that comparison passed: identical frames at 120 keys, at 300, and at 600. The
two runs only tell each other apart over the full 1500-key run. A guard that
needs ninety seconds to notice is a guard that gets turned off.

What replaced it asserts the condition the promise rests on: the run never
resolves the player's folder at all. Every `save_dir()` call the run makes is
watched, and the player's folder must not be among the answers. That fails
immediately with the funnel removed, and it says what is actually meant.

The re-break pass then found that `fort` and `play` had no guard on this
either -- their own tests set a save directory in `setUp`, so taking the
redirect out left all of them green. Both are covered now by stopping the
driver at the instant it starts playing and asking where its saves point: a
seven-day fortress is a minute and a half, and what matters is the ordering,
not the run. Eight cases, no misses.

### 141.5. Measured and left

- **The two proxy invariants from §140.5 are still proxies.** `tools/fort.py`
  reports a thirst defect from the map rather than from whether that dwarf
  could have drunk, and `tools/play.py --seed play` still reports "the clock is
  not running" for an adventurer a wolf kills on turn 36.
- **Nothing else was audited for the same shape.** "What does this run depend
  on besides its seed" was asked of the four drivers and of nothing else. The
  test suite sets its own save directory in `setUp`, which is exactly why it
  never saw any of this: the harness was insulated and the drivers were not.

## 142. An alarm you can trust (v3.82)

Two of the drivers' invariants were measuring a proxy, and §140.5 and §141.5
both wrote them down and left them. This is them.

Neither was wrong to exist. Between them they found the errand bug of §140 and
the fleeing bug of §140.4. They were asking the wrong question, and an alarm
that cries wolf is one you stop reading -- `tools/play.py --seed play` printed
PLAY PROBLEM in every run of the ritual from v3.71 to v3.81, and the honest
answer each time was "yes, we know, ignore that one".

### 142.1. The clock that was running perfectly

    if out["peak"]["thirst"] < 100:
        problems.append("needs never moved: the clock is not running")

How many ticks a turn buys depends entirely on what the turn was. Walking the
world map moves the clock in strides of a hundred; trading blows with a wolf
moves it by one. Seed `play` is jumped on the road and dead in 36 local turns,
so 36 ticks pass and thirst reaches 36.

The first replacement was worse than the original: comparing thirst against
*elapsed* ticks, on the assumption that one followed the other. It failed
`beta` immediately -- 22126 thirst over 109921 ticks -- and the measurement
says why:

| seed | ticks | peak thirst | ratio |
| --- | ---: | ---: | ---: |
| play | 36 | 36 | 1.000 |
| epsilon | 3586 | 4097 | 1.142 |
| gamma | 11600 | 11600 | 1.000 |
| zeta | 115506 | 16904 | 0.146 |
| beta | 109921 | 22126 | 0.201 |
| delta | 118368 | 28797 | 0.243 |

Thirst is not proportional to time. It climbs about a point a tick until the
character *drinks*, and then it flattens: the first three seeds have not drunk
yet and the last three have. So the original shape -- an absolute floor -- was
right all along. What was missing was a gate: ask only once enough game time
has passed to clear it. `CLOCK_ENOUGH = 600` against `CLOCK_FLOOR = 100`
leaves six times the margin an honest run needs, and a clock that has genuinely
stopped still trips it.

### 142.2. The map is not the dwarf

    if out["water_cells"] and "died of thirst" in out["deaths"]:

`water_cells` counts every WATER tile in the whole three-dimensional map --
the sea, sealed caverns, and the aquifer soaked into the rock. Seed alpha
breaches a magma pipe on day one and burns half the fortress; the dwarves who
then died of thirst were reported as a defect in the game because 360 cells of
water existed somewhere on the map. A fortress being destroyed is the game
working.

`_could_have_drunk` asks the question that was meant: could *that dwarf*,
standing where it fell, have walked to a drink -- a barrel within
`reach_from`, or open water `nearest_water` says it could get to. Both use the
game's own reachability, so the alarm and the dwarf agree about what reachable
means.

It is asked at the moment of death, inside the day loop, rather than over the
corpses at the end. The map does not hold still: magma spreads, water flows,
and a corpse's surroundings an hour later are not the ones it died in.

### 142.3. Two guards that could not fail

The re-break pass caught both. `test_a_barrel_it_could_walk_to_counts` passed
with the barrel half of the predicate deleted, because the embark has a brook
and the water half answered instead. And `test_a_bare_corridor_does_not`
passed with the reachability check deleted, because an empty floor returns
False either way -- the drink has to be somewhere *unreachable* for the check
to be the thing under test. Ten cases, no misses, after both were rebuilt.

With both alarms asking the right question, the ritual is green end to end for
the first time: 23 of 23, and the fortress numbers unchanged from v3.81 (85,
109, 100 and 36 designated cells worked), because what changed is what gets
reported and not what gets simulated.

### 142.4. Measured and left

- **The other invariants have not been audited this way.** `fort` has seven
  more and `play` has eight; only these two were asked what they actually
  measure. The rest were read and left, which is not the same as checked.
- **`_could_have_drunk` is asked once, at death.** A dwarf that could reach a
  barrel all week and is walled in an hour before it dies is recorded as
  honestly stranded. That is the right answer to a different question than the
  one v3.80 was hunting.

## 143. The checks that never ran (v3.83)

§142.4 left the rest of the drivers' invariants unaudited -- "read and left,
which is not the same as checked". Seven more in `fort` and eight in `play`.
Asked what each one measures, three of them turn out never to have run at all.

### 143.1. A gate that could not open

    if out["drink"] <= 0 and "brew_ale" in out["orders"]:
        problems.append("the still had a standing order and made nothing")

`drink` is the ale in store when the run stops, and an embark arrives with 150
units of it. Measured over three seeds, the stock went 150 to 413, 150 to 617
and 150 to 427 -- so the fortress would have to drink its way through
everything it brought *and* everything it brewed before this could fire. In a
seven-day run it never can.

It was wrong the other way as well. A still that worked all year for dwarves
who drank the lot would have been reported as a still that made nothing.

Leftovers were never the question. `_watch_the_workshops` counts the work
instead: a finished `craft` job carries the building it was done at, so the
driver now reports `made {'still': 162, 'carpenter': 4}` and asks whether the
still brewed, not whether anything is left.

### 143.2. Two more, gated on an outcome that never happens

    if out["world_tiles"] < 2 and not out["dead"]: ...
    if not out["quests_taken"] and not out["dead"]: ...

Twelve seeds measured, twelve dead. Every adventurer in the ritual bleeds to
death, most of them inside 300 turns of a 16000-turn budget:

```
play 36  beta 230  gamma 138  delta 189  epsilon 52  zeta 645
eta 288  theta 69  iota 43   kappa 70   lambda 50   mu 69
```

So `not dead` was a gate that never opened, and neither check had ever run.

Gated on opportunity instead. An adventurer killed on turn 36 has not failed
to travel; one that lived 300 turns on a single world square has. The seeds
that died inside 70 turns saw one or two squares and the ones that lived 189
or more saw between 5 and 34, so `TRAVEL_ENOUGH = 100` sits in the gap.

A third, "stopped early without dying", is dormant for the same reason and has
been left exactly as it is: it guards the driver against truncating a run
silently, it only means anything about a run that ended alive, and it cannot
fire wrongly. Dormant by design is not the same as broken, and the difference
is worth writing down rather than papering over.

### 143.3. Numbers worked out every day and thrown away

`low_food` and `low_drink` are recomputed on every one of the seven days,
stored in the result, and read by nothing -- neither printed nor asserted on.
So are `left_undug` and `lost`. The driver was already measuring the low-water
mark of the larder and then discarding it; seed `fort` bottoms out at 18 units
of food, which is the sort of number the whole driver exists to surface.

All four are printed now. They are not asserted on: a fortress that runs its
larder down to 18 is a fortress playing badly, and §119's rule is that playing
badly is not a defect in the game.

### 143.4. Measured and left

- **Every adventurer bleeds to death.** Twelve of twelve, and `tools/play.py`
  has a `BLOOD_REST` threshold whose whole purpose is to break off a fight
  before that happens. The driver is asking for 16000 turns and getting
  between 36 and 645, so nothing past the first few percent of an adventure
  has ever been exercised. That is the next milestone.
- **`play` computes `coins`, `kinds_taken`, `quests_failed` and `kinds_done`
  and shows none of them.** The same shape as §143.3 on the other side of the
  game, left for whoever needs one of those numbers.

## 144. You cannot outrun a wolf (v3.84)

§143.4 left this: every adventurer bleeds to death, twelve of twelve, and the
driver runs away below 62% blood from creatures it cannot possibly outrun.

`Game._pace_of` has told the *player* since v3.73, in its own docstring:
"Fifty of the eighty-one creature kinds are quicker than a man -- a wolf is
160 to your 100 -- and until now the only way to find that out was to try to
leave." The driver never asked. A wolf at 160 against a starting warrior's 102
takes 1.57 actions to your one, so every step of a retreat is a free attack
handed over.

### 144.1. The hypothesis, and its refutation

The correlation looked damning. Over twelve seeds, the runs that ran most died
soonest and the runs that stood and fought lived longest:

```
iota   ran 27, fought   0 ->  43 turns
play   ran 25, fought   5 ->  36 turns
theta  ran 20, fought   3 ->  69 turns
beta   ran 53, fought  72 -> 230 turns
eta    ran 11, fought 176 -> 288 turns
zeta   ran 27, fought 366 -> 645 turns
```

It is the wrong way round. Twelve seeds cannot separate an effect from noise
when survival ranges from 23 to 653 turns, and forty seeds run both ways say
so:

| | mean | median | max | flee actions | survived |
| --- | ---: | ---: | ---: | ---: | ---: |
| flee anything | 311.9 | 123.0 | 4207 | 482 | 0 of 40 |
| flee only the slower | 328.7 | 138.5 | 4214 | 88 | 0 of 40 |

Paired by seed: 20 longer, 9 shorter, 11 unchanged, mean +16.8 turns on a mean
of 312. That is not a fix for anything. **Adventurers that are losing run
more, and adventurers that are losing die** -- the running was a symptom.

### 144.2. What is left, and is still true

394 of those 482 retreats were from something faster with nothing else on
them, and a step that cannot gain ground is a turn spent on a move that cannot
work. The gate stays on those grounds rather than on a survival claim it does
not support. Thirty-one of the eighty-one kinds are slower than a man, so it
is not a gate that never opens -- the mistake §143 was written about.

### 144.2.1. And the suite caught the blanket version

The first cut applied the gate to every retreat, and the full suite failed:
`TestKnowingWhenToRun.test_surrounded_is_the_one_time_it_must_leave`, from the
milestone that fixed the flee vector, asserts that four foes on four sides
must still produce a step. That earlier milestone had *measured* it -- moving
diagonally out of a cross puts two of them behind you -- and the gain has
nothing to do with outpacing anybody. It is fewer things able to reach you.

So the gate governs only the case it was measured on: one thing chasing you,
which you cannot shake. With two or more in contact the step is worth taking
whatever their speed. The refined rule is also the better one -- 9 seeds
shorter rather than 12, and a mean of 328.7 rather than 324.7.

### 144.3. Where the turns actually go

Forty seeds, 12987 turns:

| | turns | share |
| --- | ---: | ---: |
| fought | 5090 | 39.2% |
| working | 3090 | 23.8% |
| nothing to drink | 1318 | 10.1% |
| no water on this map | 1261 | 9.7% |
| patched itself up | 485 | 3.7% |
| bleeding, nothing to bind it with | 216 | 1.7% |

Those two water lines look like a fifth of everything the adventurer does, and
that reading is wrong -- they are counter increments, not turns, and they are
concentrated rather than typical. Measured again for the shape rather than the
total: **two seeds of the forty** ever report a waterless map, and seed `s28`
supplies 1059 of the 1318 by itself, one for almost every turn of its 1107.
Nobody dies of thirst at all; the forty deaths are 38 bled to death and 2 with
the upper body destroyed.

What is real is the cost. `_find_water` scans the whole local map on each of
those 1318 calls to re-derive a fact that cannot change while the adventurer
stays on that world square: 7.66 seconds across the run. `_look_after`'s own
docstring was written about the half of this that consumed the turn; the half
that keeps re-deriving the answer is still there, and it is the same shape as
`TAVERN_UNREACHABLE_BACKOFF` in `dwarf.py` -- one actor finding out is enough
information for the rest of the run.

### 144.4. Measured and left

- **Nothing survives.** 0 of 40 reach the 16000 turns the driver asks for, and
  the longest life measured is 4207. Three quarters of the run this driver
  requests has never been exercised by anything.
- **The gate is neutral-to-slightly-positive and is not claimed as more.**
  Twelve of forty seeds get shorter. Shipped because the move it removes
  cannot work, not because the numbers went up.

## 145. The shape that did not recur (v3.85)

§140.5 has been open since v3.80:

> **The same shape may be elsewhere.** Anything that picks "the nearest" every
> step and moves one tile between picks can oscillate. `_go_pray`, the job
> board's `_claim_job` and the hauling destination all choose by distance;
> none of them were measured here.

Measured now. It does not recur, and this milestone changes no game code --
it closes the question and pins the answer.

### 145.1. Why each one is immune

| | how it chooses | why it cannot oscillate |
| --- | --- | --- |
| `_go_pray` | `temples(fort)[0]` | sorted by **quality**, not distance; the cells it then sorts are all in one room |
| `_claim_job` | first reachable on the board | only runs with no job in hand; once assigned the job is held on `DwarfState.job` |
| `fetch_target` | `job_items(job)` | reserved item **ids**, so where the dwarf stands cannot change the answer |
| `free_bed` | first bed owned by this dwarf | "keeping the one it already has", in its own docstring |
| `_to_the_tavern` | `tavern_spot` | keeps `path_goal`, re-plans only on a timer |

### 145.2. The one that still asks every step

`_drink_water` does call `nearest_water` on every step, and that function has
the *bigger* z-penalty of the two -- four tiles a level against the three that
sprang the barrel trap. It looked like the same bug.

It is not, and the first thing measuring showed is why nobody had ever seen
it: **`_drink_water` is called zero times in a hundred days of `year1`.** The
embark arrives with 150 units of ale, `_go_drink` finds one every time, and
the fallback below it is never reached.

Strip the ale out and it runs -- 820 calls over twenty days:

```
calls                                    820
goal changed under a walking dwarf       187
of those, changes back to where it came    6
```

Six, out of 820. And the goals converge rather than alternate:

```
(47,31,-3), (43,26,-2), (42,29,-2) x4, (42,26,-2) x8 ...
```

That is a dwarf finding genuinely nearer water as it walks, which is the
behaviour wanted. All seven survived the twenty dry days.

### 145.3. What this milestone ships

Guards, and nothing else. Each immunity above is now pinned by a test that
fails when it is removed -- hauling made to follow the nearest pile, the ward
chosen by distance, the temple list sorted by position -- so the shape cannot
come back unnoticed. Four re-break cases, no misses.

One of those guards had to be rebuilt to be a guard: the hauling test dropped
a single log, and "the nearest pile" and "the item this job booked" agree when
there is only one. It drops a decoy nearer than the booked one now.

### 145.4. Measured and left

- **`_drink_water` is a fallback nobody exercises.** Zero calls in a hundred
  days. It works when forced -- seven of seven alive over twenty dry days --
  and that is now pinned, but every other property of that path is still
  untested by anything.
- **`_find_water` in `tools/play.py` is the adventurer-side version of the
  same waste** (§144.3): 1318 full-map scans, 7.66 seconds over forty seeds,
  to re-derive a fact that cannot change while the adventurer stands still.
  Not fixed here; this milestone is about the fortress.

## 146. The tables nobody reads (v3.86)

The audit method's first item is dead constants, and it had not been run
mechanically. Every module-level constant in the package, against every name
read anywhere in the package, the tests and the tools:

```
module-level constants   740
read by nothing           28
```

Twenty-two of the twenty-eight are the colour palette, which is a palette and
is meant to be complete. `creatures.HOT` and `creatures.WATER` are unused
shorthand for biome groups the creature table spells out longhand -- the
desert biomes are referenced 27 to 45 times each, just not through that
alias. Neither is a defect. The remaining ones are.

### 146.1. Thirteen modes, and two of them impossible

`ai.MODES` lists what a creature can be doing. Nothing read it, so nothing
kept it true:

| | |
| --- | --- |
| declared, no code path can produce | `talk`, `travel` |
| produced by `take_turn`, not declared | `spin`, `stuck` |

`spin` is a spider throwing a web and `stuck` is anything caught in one. Both
lists were thirteen long, which is how the error stayed invisible.

Measured in play as well as in the source -- three fortresses over seven days,
four adventures -- the modes actually entered were idle 31207, wander 6794,
follow 2000, flee 1200, guard 1199, hunt 800. The other seven never came up,
but only `talk` and `travel` are *impossible*: `pick_mode` returns "sleep" for
anything unconscious, "graze" and "forage" for a hungry herbivore and "lurk"
for an ambusher, and none of those arose in the sample. Rare is not dead, and
the difference is the whole point of checking rather than guessing.

### 146.2. Two more of the same kind

- **`medical.TREATMENTS`** was a third copy of a list that `TREATMENT_NAMES`
  and `TREATMENT_SKILL` already hold, sitting beside them, read by nothing and
  free to disagree with either. Derived from `TREATMENT_NAMES` now.
- **`calendar.SECONDS_PER_TICK = 6`** was declared and read by nothing, while
  `TICKS_PER_MINUTE = 10` sat under it as a bare number that happened to
  agree. "One tick is six seconds" is repeated all through this document and
  rested on a comment. The minute is derived from it now, so the claim is a
  fact about the code. `TICKS_PER_DAY` is still 14400, so no world moved.

### 146.3. The guard that makes an unread table safe

A corrected list would drift again for exactly the reason the first one did.
So the guard derives the truth from the source -- every string `pick_mode`
returns, every literal assigned to `ai.mode` -- and fails when `MODES` and the
code disagree in either direction. The constant is read by a test now, which
is the only thing that keeps a constant honest.

Five re-break cases, no misses.

### 146.4. Measured and left

- **`bodies.FLESH_SOFT` and `worldgen.MOUNTAIN_LEVEL` are still unread.** Both
  look like documentation of a threshold used elsewhere by literal; neither
  was chased down, and saying so is better than quietly dropping them.
- **The sweep only covers module-level constants.** Class attributes, dict
  entries and enum members were not looked at, and the same rot can grow in
  any of them.

## 147. Re-deriving what cannot change (v3.87)

Recorded and left twice -- §144.3 and §145.4 -- so this closes it.

`tools/play.py` asked where the water was by walking every tile of every
level, on every turn it was thirsty. On a small world's local map that is 64
by 48 over eleven levels: **33792 cells**, 5.41 ms, to answer a question about
terrain that does not move while the adventurer stands on it.

```
1318 calls over forty seeds          7.66 s
of those, on maps with no water      1261
seed s28                             1059 calls in a life of 1107 turns
```

Twelve hundred and sixty-one times it walked the whole map to say "none"
again.

### 147.1. The lesson the fortress already learned

`dwarf.py` has carried it since the walled-off tavern cost 76 ms a step:

> Nobody else try either. One dwarf finding out the tavern is cut off is
> enough information for the whole fortress, and it is the only thing that
> keeps the cost of a walled-off tavern bounded.

`_water_cells` remembers its scan the same way, keyed on the world square
**and on the map object itself** -- so a square revisited with a freshly
generated map is scanned again rather than answered from the last visit.

```
one map, repeated calls    5.41 ms  ->  0.03 ms a call
the whole forty-seed run   7.66 s   ->  0.22 s over the same 1318 calls
```

The two numbers differ because the run-wide figure still pays for the first
scan of every map the adventurer walks onto, which is the scan that has to
happen. A hundred and eighty times cheaper once warm, thirty-five times
cheaper across a real run, and the same answer: the guard compares a cache hit
against a fresh scan on a map with known water in it.

### 147.2. A guard that could not fail, again

The first version of that comparison passed with the cache deliberately
returning the wrong list. Two reasons, both worth naming. It compared the
*first* call, which is a miss and so never runs the line that answers from the
cache at all; and it ran on a map that happened to have no water, where two
empty lists agree whatever the code does. It builds a pond of its own now and
compares a hit.

That is the fifth guard this run of five milestones has had to rebuild --
§142.3 twice, §143's plan test, §145.3's single log, and this one. The
re-break pass is the only thing that finds them.

### 147.3. Measured and left

- **Nothing else in `play.py` was swept for the same shape.** This was the
  one the counters happened to expose; the question "what else does this
  recompute every turn" was not asked of the rest of the file.
- **The adventurer still dies every time.** 0 of 40 reach the 16000 turns the
  driver asks for (§144.4), and none of these five milestones changed that.

## 148. A warrior who cannot use a sword (v3.88)

Three milestones have now recorded the same thing and left it: §143.4, §144.4
and §147 each note that no adventurer survives -- 0 of 40 reach the 16000
turns `tools/play.py` asks for, and three quarters of the run it requests has
never been exercised by anything.

The cause is one line that was never written.

```python
player.profession = profession
for skill, level in (player_spec.get("skills") or {}).items():
    player.skills.set_level(skill, level)
```

`Game.new_game` takes a profession, stores it on the character, and then
applies whatever skills the *caller* passed alongside. It never consults the
table that says what a profession knows -- that lived in `ui/charcreate.py`,
where the game layer could not see it. The character-creation screen passes
the skills, so a real player gets a real warrior. `tests/test_systems.py`
reaches into the UI and applies the table by hand, in three separate places.
`tools/play.py` passes this:

```python
Game.new_game(world, {"race": "human", "profession": "warrior"}, rng)
```

and gets a man with an iron sword, a mail shirt, a helm, and `fighter 0`,
`sword 0`.

### 148.1. Two true statements about different warriors

`TestWhatTheModelCannotSay` says, in its own docstring, that "a starting
warrior beats a wolf forty times in forty in seven exchanges". Duelled twenty
times, the warrior `play()` actually made won **one of twenty** against a
wolf, and none at all against a goblin. Both statements are true. They were
never about the same character.

The measurements that led here, in order, and four of them wrong:

| | |
| --- | --- |
| 38 of 40 bled to death | so it is bleeding, not blunt trauma |
| only 12 of 40 ever ran out of bandages | so it is not the supply -- 28 died with dressings in hand |
| worn cloth *is* reachable by crafting | `equip` leaves the item in `items`, so the shirt on your back can be torn |
| median 28 consecutive swings at one creature | so fights *do* run to a finish; they are not being interrupted |
| 4994 swings, **11 kills** | one kill per 454 swings, and 619 swings at badgers killed no badger |
| sword in hand for all 1048 sampled swings, 67% hit | so it is not the weapon, and not the aim |

The last one is what pointed at the character rather than the fight.

### 148.2. What it is worth

Forty seeds, the same seeds both ways:

| | mean | median | longest | survived |
| --- | ---: | ---: | ---: | ---: |
| `fighter 0`, as it was | 328.7 | 138.5 | 4214 | 0 of 40 |
| `fighter 4`, as asked for | **679.5** | 155.0 | **16000** | **1 of 40** |

Thirty-eight of the forty lived longer. One reached the sixteen thousand turns
the driver asks for, which nothing had ever done.

The table now lives in `data/professions.py` where the game can see it,
`new_game` applies it, and skills the caller passes still win -- so character
creation behaves exactly as before, and the UI re-exports the table rather
than keeping a second copy to drift.

### 148.3. What this does to the earlier numbers

Every adventure measurement before this one was taken on the novice. That does
not overturn §144's conclusion -- fleeing was a symptom rather than the cause,
and 394 retreats from things that cannot be outrun are still 394 wasted turns
-- but the numbers in §144.1 and §144.3 describe a character who no longer
exists, and should be read that way. Whether the flee gate is still the right
call for a warrior who can fight has not been re-measured.

### 148.4. Two tests were measuring the novice too

The full suite failed twice, and neither was collateral -- both were the same
defect, one layer further in.

`TestTheMetalInYourSword` builds its swordsman with the same
`new_game(..., "warrior")` call, so every claim that class makes about what a
metal does was measured by somebody who had never held a blade. It pins the
skill now, because the class is about the blade and not about who swings it:

| twenty-five samples, cap 400 | copper | iron | steel | adamantine |
| --- | ---: | ---: | ---: | ---: |
| the novice it used to get | 400 | 400 | 37 | 22 |
| a warrior who can use a sword | 400 | 81 | 30 | 17 |

The ordering never moved. Only the threshold did -- ten times becomes two and
a half, because skill closes on the metal a little -- so the assertion is
`iron > steel * 2` and says so. The failing run's `iron 56, steel 69` was
nine-sample noise; at twenty-five the gap is clean.

`TestSkillsYouWereSold._scholar` laid a scholar's skills over the fixture's
warrior and returned it. That warrior now comes with `sword 4`, so the
"scholar" could write a treatise on swordsmanship -- which the very next test
forbids. It builds a scholar now instead of dressing one up.

### 148.5. Measured and left

- **One survivor of forty is not a solved game.** The median life is still 155
  turns. What kills them now is worth its own measurement: the causes have
  changed shape, with a head severed and a throat destroyed among them where
  before it was almost uniformly bleeding.
- **`smoke.py` makes its character the same way** and was not touched here.

## 149. Style

- `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants.
- Dataclasses for plain data; `__slots__` where objects are numerous (tiles, cells).
- Serialization: every stateful class implements `to_dict()` and
  `from_dict(cls, d)`; ids are ints; references are stored by id, never by object.
- Flavour text matters. Messages should sound like Dwarf Fortress.
