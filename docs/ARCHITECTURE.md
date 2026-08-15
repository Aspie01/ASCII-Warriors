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

## 97. Style

- `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants.
- Dataclasses for plain data; `__slots__` where objects are numerous (tiles, cells).
- Serialization: every stateful class implements `to_dict()` and
  `from_dict(cls, d)`; ids are ints; references are stored by id, never by object.
- Flavour text matters. Messages should sound like Dwarf Fortress.
