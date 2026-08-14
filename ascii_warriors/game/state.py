"""The game state: the single object every screen talks to."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..data import biomes as biome_data
from ..data import creatures as creature_data
from ..data import names as name_data
from ..data.calendar import GameTime, TICKS_PER_DAY
from ..engine import colors
from ..engine.fov import compute_fov
from ..engine.rng import RNG
from ..engine.scheduler import Scheduler
from ..engine.screen import Frag
from ..world import tiles as tile_data
from ..world.localmap import LocalMap, generate_local
from ..world.worldgen import World
from .ai import AIState
from .entity import Creature, make_creature
from .item import Item, corpse_of, starting_kit
from .log import MessageLog
from .quests import QuestLog
from ..world.fire import Fire as FireLayer
from ..world.heat import Frost
from . import standing as standing_mod
from . import traps as traps_mod
from . import venom as venom_mod
from . import webs as webs_mod
from . import tracks as tracks_mod
from .weather import Weather, starting_weather

#: How much of the trail one tick of rain takes.
WASHOUT_PER_TICK = 0.002

#: Ticks between performances in a tavern you are standing in. Long enough
#: that a night in one is a few songs rather than a jukebox.
TAVERN_MUSIC = 900

#: How far a tavern performance carries.
TAVERN_HEARING = 9

#: How many world tiles of wilderness get wildlife when you arrive.
WILDLIFE_MIN = 3
WILDLIFE_MAX = 9


class Game:
    """Everything about one playthrough."""

    def __init__(self, world: World, player: Creature, rng: RNG) -> None:
        self.world = world
        self.player = player
        self.rng = rng
        self.local: Optional[LocalMap] = None
        self.creatures: Dict[int, Creature] = {}
        self.items_on_ground: Dict[Tuple[int, int, int], List[Item]] = {}
        self.time = GameTime.at(world.year, 1, 1, 8, 0)
        self.log = MessageLog()
        self.quests = QuestLog()
        self.scheduler = Scheduler()
        self.turn = 0
        self.mode = "local"
        self.seen: Set[Tuple[int, int, int]] = set()
        self.visible: Dict[Tuple[int, int, int], float] = {}
        self.game_over = False
        self.death_message = ""
        self.travel_target: Optional[Tuple[int, int]] = None
        self.weather = Weather()
        #: Everything currently alight on this map.
        self.fire = FireLayer()
        #: What the cold has taken on this map.
        self.frost = Frost()
        #: Ids of the companions following the player.
        self.companion_ids: List[int] = []
        #: Companions in transit between local maps.
        self.travelling_companions: List[Creature] = []
        self._local_cache: Dict[Tuple[int, int], Dict[str, Any]] = {}
        #: Visit order for the local-map cache, oldest first.
        self._cache_order: List[Tuple[int, int]] = []
        #: The world season last simulated, so history keeps happening while
        #: the player walks around in it.
        self._season_mark = 0

    # -- construction ------------------------------------------------------ #

    @classmethod
    def new_game(cls, world: World, player_spec: Mapping[str, Any], rng: RNG) -> "Game":
        """Start a fresh game from a character-creation spec."""
        race = str(player_spec.get("race", "dwarf"))
        profession = str(player_spec.get("profession", "warrior"))
        name = str(player_spec.get("name", "")) or name_data.name_for_race(
            race, rng, bool(player_spec.get("female", False))
        )
        player = Creature(
            race, rng=rng, name=name,
            female=bool(player_spec.get("female", False)),
            player=True, faction="player",
        )
        player.profession = profession
        for skill, level in (player_spec.get("skills") or {}).items():
            player.skills.set_level(skill, level)
        for attr, value in (player_spec.get("attributes") or {}).items():
            player.attributes.set(attr, value)
        for it in starting_kit(rng, race, profession):
            player.inventory.add(it)
        player.inventory.auto_equip()
        _teach_own_forms(world, rng, player, race)

        game = cls(world, player, rng)
        start = game._starting_tile()
        player.wx, player.wy = start
        game.log.info("You are %s." % player.full_title())
        game.log.info(
            "The world of %s, in the year %d." % (world.name, world.year)
        )
        game.enter_world_tile(start[0], start[1], entry="center")
        game.log.info("Press ? for help.")
        return game

    def _starting_tile(self) -> Tuple[int, int]:
        """Pick where the adventurer begins: a friendly settlement if possible."""
        race = self.player.def_id
        candidates = [
            s for s in self.world.sites
            if s.is_settlement and not s.hostile and s.race == race
        ]
        if not candidates:
            candidates = [
                s for s in self.world.sites if s.is_settlement and not s.hostile
            ]
        # Never start somewhere with nowhere to walk to: a one-tile island
        # would strand the adventurer forever.
        reachable = [s for s in candidates if self._land_neighbours(s.wx, s.wy) >= 2]
        if reachable:
            candidates = reachable
        if candidates:
            site = self.rng.choice(candidates)
            return (site.wx, site.wy)
        land = [
            (x, y) for (x, y) in self.world.land_tiles()
            if self._land_neighbours(x, y) >= 2
        ] or self.world.land_tiles()
        return self.rng.choice(land) if land else (
            self.world.width // 2, self.world.height // 2
        )

    def _land_neighbours(self, wx: int, wy: int) -> int:
        """How many of a world tile's neighbours can be walked onto."""
        return sum(
            1 for nx, ny in self.world.neighbours(wx, wy)
            if not self.world.tile(nx, ny).is_ocean
        )

    # -- map management ---------------------------------------------------- #

    def current_site(self):
        """The site the player is standing in, if any."""
        return self.world.site_at(self.player.wx, self.player.wy)

    def enter_world_tile(self, wx: int, wy: int, *, entry: str = "edge") -> None:
        """Load or generate the local map for a world tile and place the player."""
        wx = max(0, min(self.world.width - 1, wx))
        wy = max(0, min(self.world.height - 1, wy))
        self._store_local()

        site = self.world.site_at(wx, wy)
        cached = self._local_cache.get((wx, wy))
        if cached is None:
            # A place the player built in fortress mode is kept whole, not
            # regenerated: the corridors, the workshops and the dead are all
            # exactly where they were left.
            from ..fortress import legacy

            cached = legacy.restore(self.world.preserved_map(wx, wy))
        if cached is not None:
            self.local = LocalMap.from_dict(cached["map"])
            population: List[Dict[str, Any]] = []
            self.creatures = {}
            self.items_on_ground = {
                tuple(int(v) for v in k.split(",")): [
                    Item.from_dict(i) for i in items
                ]
                for k, items in cached["items"].items()
            }
            for cd in cached["creatures"]:
                c = Creature.from_dict(cd)
                self.creatures[c.id] = c
            self._restore_layers(cached.get("layers") or {})
        else:
            lm_rng = self.rng.sub("local-%d-%d" % (wx, wy))
            self.local, population = generate_local(
                self.world, wx, wy, lm_rng, site=site
            )
            self.creatures = {}
            self.items_on_ground = {}
            self._restore_layers({})
            self._populate(population, lm_rng, site)
            # Traps belong to a floor plan, and floor plans are made here
            # rather than at worldgen, so this is where they go in.
            traps_mod.populate(self, site, lm_rng)

        self.player.wx, self.player.wy = wx, wy
        self.world.tile(wx, wy).explored = True
        if site is not None:
            site.visited = True

        pos = self._entry_position(entry)
        self.player.x, self.player.y, self.player.z = pos
        self.creatures[self.player.id] = self.player

        from . import companions as companion_mod

        companion_mod.bring_along(self, None)

        self.scheduler = Scheduler()
        self.scheduler.add(self.player.id, self.player.effective_speed(), priority=1)
        for c in self.creatures.values():
            if c is not self.player and not c.body.dead:
                self.scheduler.add(c.id, c.effective_speed())

        self.seen = set()
        self.visible = {}
        self.update_fov()
        self.quests.on_arrive(self, wx, wy)

        region = self.world.region_at(wx, wy)
        where = site.name if site is not None else (
            region.name if region is not None else "the wilds"
        )
        self.log.info("You arrive at %s." % where)
        if self.weather.ticks_left <= 0:
            tile = self.world.tile(wx, wy)
            self.weather = starting_weather(
                self.rng, tile.biome, tile.temperature, self.time.season)
        if self.weather.kind != "clear":
            self.log.info(self.weather.describe())

    def _entry_position(self, entry: str) -> Tuple[int, int, int]:
        """Where the player appears on a newly entered map."""
        lm = self.local
        assert lm is not None
        if entry in ("west", "east", "north", "south"):
            return lm.edge_entry(self.rng, entry)
        if entry == "center":
            return lm.entry_points.get("center") or lm.central_open(self.rng)
        if entry in lm.entry_points:
            return lm.entry_points[entry]
        return lm.random_open(self.rng)

    def _populate(self, population: Sequence[Dict[str, Any]], rng: RNG, site) -> None:
        """Spawn a site's inhabitants and the local wildlife."""
        for spec in population:
            c = make_creature(
                rng, str(spec["def_id"]), faction=str(spec.get("faction", "town")),
                level=int(spec.get("level", 0)),
            )
            c.x, c.y, c.z = int(spec["x"]), int(spec["y"]), int(spec["z"])
            c.wx, c.wy = self.player.wx, self.player.wy
            c.profession = str(spec.get("profession", ""))
            c.hf_id = spec.get("hf_id")
            c.site_id = site.id if site is not None else None
            if site is not None and site.civ_id:
                c.civ_id = site.civ_id
            if spec.get("name"):
                c.name = str(spec["name"])
            if c.hf_id is not None:
                fig = self.world.figures.get(c.hf_id)
                if fig is not None:
                    c.name = fig.name
                    c.title = fig.titles[-1] if fig.titles else ""
            c.ai = AIState("idle", role=str(spec.get("role", "")))
            c.ai.home = (c.x, c.y, c.z)
            c.ai.site_id = site.id if site is not None else None
            if not self.local.walkable(c.x, c.y, c.z):
                c.x, c.y, c.z = self.local.random_open(rng)
            self._give_books(c, rng)
            self.add_creature(c)
        self.spawn_wildlife()

    #: Who is carrying something worth reading, and how likely they are to be.
    BOOKISH = {"necromancer": 1.0, "tomb_lord": 0.6, "priest": 0.5,
               "lord": 0.35, "scholar": 0.9, "merchant": 0.2}

    def _give_books(self, c, rng: RNG) -> None:
        """Put the written word where somebody would actually have it.

        Sitegen returns people, not floors, so the books ride in on the people
        who would own them. A necromancer carries its own slab, which makes
        the secret something you have to go and take rather than something you
        find lying about.
        """
        from . import books
        from .item import make_item

        odds = self.BOOKISH.get(c.profession, 0.0)
        if odds <= 0.0 or not rng.chance(odds):
            return
        if c.profession in ("necromancer", "tomb_lord"):
            slab = make_item(rng, "book")
            books.attach(slab, books.make_slab(rng))
            c.inventory.add(slab)
            return
        item = make_item(rng, "book")
        books.bind(self.world, rng, item, author=c.name)
        c.inventory.add(item)

    def _store_local(self) -> None:
        """Cache the current local map so returning to it is consistent."""
        if self.local is None:
            return
        key = (self.local.wx, self.local.wy)
        companions = [
            c for c in self.creatures.values() if c.id in self.companion_ids
        ]
        self.travelling_companions = companions
        self._local_cache[key] = {
            "map": self.local.to_dict(),
            "creatures": [
                c.to_dict() for c in self.creatures.values()
                if not c.is_player and c.id not in self.companion_ids
            ],
            "items": {
                "%d,%d,%d" % k: [i.to_dict() for i in v]
                for k, v in self.items_on_ground.items() if v
            },
            "layers": self._store_layers(),
        }
        # Keep the cache from growing without bound on long journeys, dropping
        # the tiles the player has not seen for longest.
        self._cache_order = [c for c in self._cache_order if c != key]
        self._cache_order.append(key)
        while len(self._cache_order) > 24:
            stale = self._cache_order.pop(0)
            self._local_cache.pop(stale, None)

    # -- per-map layers ----------------------------------------------------- #
    #
    # Fires, frost, traps and webs belong to a *map*, not to the game. Each
    # was added in its own version and each was wired by hand into the branch
    # that generates a fresh map -- and every one of them was missed on the
    # branch that loads a cached one, so walking out of a burning forest onto
    # a map you had already visited took the fire with you, still alight, at
    # the same coordinates, over water or inside a wall. Four layers made the
    # same mistake four times; they go through one pair of functions now.

    def _store_layers(self) -> Dict[str, Any]:
        """The current map's own layers, to be kept with the map."""
        return {
            "fire": self.fire.to_list(),
            "frost": self.frost.to_list(),
            "traps": traps_mod.to_list(self),
            "webs": webs_mod.to_list(self),
        }

    def _restore_layers(self, d: Mapping[str, Any]) -> None:
        """Put a map's layers back. An empty mapping is a clean map."""
        self.fire = FireLayer.from_list(d.get("fire") or [])
        self.frost = Frost.from_list(d.get("frost") or [])
        self.traps = {}
        self.webs = {}
        traps_mod.from_list(self, d.get("traps") or [])
        webs_mod.from_list(self, d.get("webs") or [])

    def spawn_wildlife(self, n: Optional[int] = None) -> None:
        """Populate the wilderness with creatures suited to the biome."""
        if self.local is None:
            return
        tile = self.world.tile(self.local.wx, self.local.wy)
        underground = False
        options = creature_data.spawnable(
            tile.biome, underground=underground,
            max_tier=3 if tile.savagery < 60 else 5,
        )
        options = [c for c in options if not c.intelligent or c.has("EVIL")]
        if not options:
            return
        if n is not None:
            count = n
        else:
            count = self.rng.randint(WILDLIFE_MIN, WILDLIFE_MAX)
            site = self.world.site_at(self.local.wx, self.local.wy)
            if site is not None and site.is_settlement:
                # Guards keep most of the wildlife out of an inhabited place.
                count = max(0, count // 3)
        weights = {c.id: float(c.frequency) for c in options}
        for _ in range(count):
            cid = self.rng.weighted(weights)
            defn = creature_data.get(cid)
            lo, hi = defn.group
            group = self.rng.randint(lo, hi)
            ox, oy, oz = self.local.random_open(self.rng)
            leader_id: Optional[int] = None
            for i in range(group):
                c = make_creature(self.rng, cid, faction=(
                    "hostile" if defn.has("EVIL") else "wild"
                ))
                x = max(0, min(self.local.width - 1, ox + self.rng.randint(-2, 2)))
                y = max(0, min(self.local.height - 1, oy + self.rng.randint(-2, 2)))
                z = self.local.surface_z(x, y)
                if not self.local.walkable(x, y, z):
                    x, y, z = ox, oy, oz
                c.x, c.y, c.z = x, y, z
                c.wx, c.wy = self.local.wx, self.local.wy
                c.ai = AIState("wander")
                c.ai.home = (x, y, z)
                if i == 0:
                    leader_id = c.id
                elif defn.has("PACK"):
                    c.ai.leader_id = leader_id
                self.add_creature(c)

    # -- creature bookkeeping ---------------------------------------------- #

    def add_creature(self, c: Creature) -> None:
        """Register a creature on the current map."""
        self.creatures[c.id] = c
        if not c.body.dead:
            self.scheduler.add(
                c.id, c.effective_speed(), priority=1 if c.is_player else 0
            )

    def remove_creature(self, c: Creature) -> None:
        """Take a creature off the map."""
        self.creatures.pop(c.id, None)
        self.scheduler.remove(c.id)

    def creature_at(self, x: int, y: int, z: int) -> Optional[Creature]:
        """The living creature standing on a cell, if any."""
        for c in self.creatures.values():
            if c.x == x and c.y == y and c.z == z and not c.body.dead:
                return c
        return None

    def creatures_at(self, x: int, y: int, z: int) -> List[Creature]:
        """Every creature, alive or dead, on a cell."""
        return [
            c for c in self.creatures.values()
            if c.x == x and c.y == y and c.z == z
        ]

    def move_creature(self, c: Creature, x: int, y: int, z: int) -> None:
        """Place a creature on a new cell.

        Moving is louder than standing still, which is the only thing that
        makes standing still a tactic.
        """
        from . import stealth, tracks

        was = (c.x, c.y, c.z)
        c.x, c.y, c.z = x, y, z
        stealth.note_action(c, "move")
        tracks.leave(self, c, was)
        if c.is_player:
            self.update_fov()

    def hostiles_in_sight(self) -> bool:
        """Whether anything the player can see would like it dead.

        Used to refuse the long, absorbing actions -- reading, mostly. A book
        is not a thing you finish while somebody is walking towards you.
        """
        return any(c.is_hostile_to(self.player)
                   for c in self.visible_creatures())

    def visible_creatures(self) -> List[Creature]:
        """Every creature the player can currently see."""
        out = []
        for c in self.creatures.values():
            if c is self.player or c.body.dead:
                continue
            if (c.x, c.y, c.z) in self.visible:
                out.append(c)
        out.sort(key=lambda c: self.player.distance_to(c))
        return out

    def can_see_creature(self, c: Creature) -> bool:
        """True if the player can see this creature."""
        return (c.x, c.y, c.z) in self.visible

    # -- items ------------------------------------------------------------- #

    def items_at(self, x: int, y: int, z: int) -> List[Item]:
        """Items lying on a cell."""
        return self.items_on_ground.get((x, y, z), [])

    def drop_item(self, item: Item, x: int, y: int, z: int) -> None:
        """Put an item on the ground."""
        pile = self.items_on_ground.setdefault((x, y, z), [])
        for existing in pile:
            if existing.stack_with(item):
                return
        pile.append(item)

    def take_item(self, item: Item, x: int, y: int, z: int) -> bool:
        """Remove an item from the ground."""
        pile = self.items_on_ground.get((x, y, z))
        if not pile or item not in pile:
            return False
        pile.remove(item)
        if not pile:
            del self.items_on_ground[(x, y, z)]
        return True

    # -- terrain queries --------------------------------------------------- #

    def is_passable(self, x: int, y: int, z: int, creature=None) -> bool:
        """True if a creature could stand on a cell."""
        if self.local is None or not self.local.in_bounds(x, y, z):
            return False
        tid = self.local.tile(x, y, z)
        t = tile_data.get(tid)
        if not t.walk:
            return False
        if t.has("WATER") and t.has("DEEP"):
            if creature is not None and not (
                creature.defn.has("SWIMMER") or creature.defn.has("AQUATIC")
            ):
                return False
        if creature is not None and creature.defn.has("AQUATIC") and not t.has("WATER"):
            return False
        return True

    def blocks_sight(self, x: int, y: int, z: int) -> bool:
        """True if a cell stops line of sight."""
        if self.local is None:
            return True
        return self.local.blocks_sight(x, y, z)

    def light_at(self, x: int, y: int, z: int) -> float:
        """Ambient light at a cell, 0..1."""
        if self.local is None:
            return 1.0
        # A fire lights the ground around it, which means v3.6's stealth
        # charges for standing next to a burning tree without ever needing to
        # know that fire exists.
        flame = self.fire.light_at(x, y, z)
        if self.local.is_outside(x, y, z):
            return max(flame,
                       self.time.light_level() * self.weather.light_modifier())
        # Underground: only whatever the player is actually holding alight.
        if self.player_light() > 0:
            return max(flame, 0.8)
        return max(flame, 0.05)

    def temperature_at(self, x: int, y: int, z: int) -> float:
        """How cold or hot a cell is, in degrees.

        The world tile's own figure, its biome, the season, the hour and the
        weather, damped by how far underground the cell is -- and then
        whatever is burning nearby, because a fire that does not warm you is
        a light bulb.
        """
        from ..world import heat

        tile = self.world.tile(self.player.wx, self.player.wy)
        if self.local is None:
            return heat.ambient(
                tile.temperature, biome=biome_data.get(tile.biome),
                season=self.time.season, hour=self.time.hour,
                weather=self.weather.kind)
        outside = self.local.is_outside(x, y, z)
        air = heat.ambient(
            tile.temperature, biome=biome_data.get(tile.biome),
            season=self.time.season, hour=self.time.hour,
            weather=self.weather.kind,
            depth=max(0, self.local.surface_z(x, y) - z), outside=outside)
        return air + heat.source_heat((x, y, z), fire=self.fire)

    def _wear_out(self) -> None:
        """Clothes wear through, on everyone near enough to matter."""
        from . import wear as wear_mod

        now = self.time.ticks
        for c in [self.player] + [
                c for c in self.creatures.values()
                if c is not self.player and not c.body.dead
                and self.can_see_creature(c)]:
            if not wear_mod.due(c, now):
                continue
            wear_mod.mark(c, now)
            wear_mod.wearing(c, self.rng,
                             log=self.log if c.is_player else None)

    def _weather_bite(self, ticks: int) -> None:
        """What the temperature does to everyone standing in it.

        Only the player and whoever is near enough to matter: the weather is
        the same everywhere on the map, and stepping ten thousand off-screen
        squirrels through a chill model is how a step gets slow.
        """
        from ..world import heat

        p = self.player
        for m in heat.tick(p, self.temperature_at(p.x, p.y, p.z),
                           ticks, self.rng, log=self.log):
            self.log.warn(m)
        if p.body.dead:
            return
        for c in list(self.creatures.values()):
            if c is p or c.body.dead or not self.can_see_creature(c):
                continue
            heat.tick(c, self.temperature_at(c.x, c.y, c.z), ticks, self.rng)
            if c.body.dead:
                self.kill_creature(c)
        if self.local is not None:
            self.frost.step(self.local, self.rng, lambda cell:
                            self.temperature_at(*cell), self.time.ticks)

    def player_light(self) -> int:
        """Burn time remaining on the player's lit light sources."""
        return sum(
            it.charges for it in self.player.inventory.items
            if it.is_light and it.flags.get("lit") and it.charges > 0
        )

    def update_fov(self) -> None:
        """Recompute what the player can see."""
        if self.local is None:
            return
        self.visible = {}
        p = self.player
        light = self.light_at(p.x, p.y, p.z)
        radius = p.sight_radius(light)
        if self.local.is_outside(p.x, p.y, p.z):
            radius = max(2, int(radius * self.weather.sight_modifier()))
        z = p.z

        def blocks(x: int, y: int) -> bool:
            return self.local.blocks_sight(x, y, z)

        def visit(x: int, y: int, intensity: float) -> None:
            key = (x, y, z)
            self.visible[key] = intensity
            self.seen.add(key)

        compute_fov(p.x, p.y, radius, blocks, visit)
        # You can always see the cell you are standing on and the one below.
        self.visible[(p.x, p.y, p.z)] = 1.0
        self.seen.add((p.x, p.y, p.z))

    def describe_tile(self, x: int, y: int, z: int) -> List[Frag]:
        """Everything notable about a cell, for the look cursor."""
        out: List[Frag] = []
        if self.local is None or not self.local.in_bounds(x, y, z):
            return [Frag("Nothing at all.", colors.UI["dim"])]
        t = tile_data.get(self.local.tile(x, y, z))
        out.append(Frag(t.name.capitalize(), t.color))
        if t.description:
            out.append(Frag(t.description, colors.UI["dim"]))
        if self.frost.is_frozen(x, y, z):
            out.append(Frag("The water here has frozen over.", colors.ICE))
        if self.fire.burning(x, y, z):
            out.append(Frag("It is on fire.", colors.EMBER))
        for c in self.creatures_at(x, y, z):
            out.append(Frag("", colors.UI["fg"]))
            out.extend(c.describe())
            out.extend(self._awareness(c))
        pile = self.items_at(x, y, z)
        if pile:
            out.append(Frag("", colors.UI["fg"]))
            out.append(Frag("On the ground:", colors.UI["accent"]))
            for it in pile[:8]:
                out.append(Frag("  " + it.name(article=True), it.color))
        out.extend(self._tracks_here(x, y, z))
        return out

    def _tracks_here(self, x: int, y: int, z: int) -> List[Frag]:
        """What walked over this cell, as much of it as you can tell.

        On the look panel rather than behind a key of its own, because the
        question "what is this" already had a place to be answered and a
        footprint is a thing on a tile like any other.
        """
        track = tracks_mod.readable(self, (x, y, z))
        if track is None:
            return []
        if track.player:
            return [Frag("", colors.UI["fg"]),
                    Frag("Your own footprints.", colors.UI["dim"])]
        out = [Frag("", colors.UI["fg"])]
        for line in tracks_mod.read(self, self.player, (x, y, z), track):
            out.append(Frag(line, colors.UI["accent2"]))
        return out

    def _awareness(self, c: Creature) -> List[Frag]:
        """Whether this creature has noticed the player, while sneaking.

        The single most useful thing a stealth game can tell you, and the only
        way the roll is playable rather than a hidden dice cup: look at the
        guard and find out whether the guard is looking at you.
        """
        from . import stealth

        p = self.player
        if c is p or c.body.dead or not stealth.is_sneaking(p):
            return []
        if not c.is_hostile_to(p) and not p.is_hostile_to(c):
            return []
        chance = stealth.hide_chance(self, p, c)
        if chance >= 0.75:
            word, colour = "It has no idea you are there.", colors.UI["good"]
        elif chance >= 0.4:
            word, colour = "It might not see you.", colors.UI["warn"]
        else:
            word, colour = "It will see you.", colors.UI["danger"]
        return [Frag(word, colour)]

    # -- time and turns ---------------------------------------------------- #

    def player_acts(self, cost: int) -> None:
        """Charge the player for an action and let the world catch up."""
        if cost <= 0:
            return
        self.scheduler.spend(self.player.id, cost)
        self.advance()

    def advance(self, max_iterations: int = 4000) -> None:
        """Run every creature until it is the player's turn again."""
        if self.game_over:
            return
        last_tick = self.scheduler.ticks
        for _ in range(max_iterations):
            actor_id = self.scheduler.next_actor()
            if actor_id is None:
                break
            elapsed = self.scheduler.ticks - last_tick
            if elapsed > 0:
                self._tick_world(elapsed)
                last_tick = self.scheduler.ticks
            if self.game_over:
                return
            if actor_id == self.player.id:
                self.turn += 1
                self.log.turn = self.turn
                self.update_fov()
                return
            c = self.creatures.get(actor_id)
            if c is None or c.body.dead:
                self.scheduler.remove(actor_id)
                continue
            cost = c.take_turn(self)
            self.scheduler.spend(actor_id, max(1, cost))
            self.scheduler.set_speed(actor_id, c.effective_speed())
            if c.body.dead:
                self.kill_creature(c)

    def _tick_world(self, ticks: int) -> None:
        """Advance the clock, weather, needs, wounds and item state."""
        self.time.advance(ticks)
        self._world_season()
        self._moon()
        p = self.player

        tile = self.world.tile(p.wx, p.wy)
        change = self.weather.tick(
            ticks, self.rng, tile.biome, tile.temperature, self.time.season)
        if change:
            self.log.info(change)
        if self.weather.is_wet():
            # Rain takes the trail. Weather has been in the game since v1 and
            # nothing has ever cared whether it was raining; this is the
            # reason to set out after the storm rather than during it.
            tracks_mod.wipe(self, WASHOUT_PER_TICK * ticks)
        if self.weather.is_cold() and self.local is not None \
                and self.local.is_outside(p.x, p.y, p.z):
            # Keeping warm burns food faster.
            p.needs.hunger += ticks // 2

        msgs = p.needs.tick(ticks, p, self)
        for m in msgs:
            self.log.warn(m)
        msgs = p.body.tick(
            self.rng, ticks, p.attributes.factor("toughness"),
            p.attributes.factor("recuperation"),
        )
        for m in msgs:
            self.log.warn(m)
        for m in venom_mod.tick(p, ticks, self.rng):
            if m:
                self.log.warn(m)

        for c in list(self.creatures.values()):
            if c is p or c.body.dead:
                continue
            c.needs.tick(ticks, c, self)
            venom_mod.tick(c, ticks, self.rng)
            c.body.tick(
                self.rng, ticks, c.attributes.factor("toughness"),
                c.attributes.factor("recuperation"),
            )
            if c.body.dead:
                self.kill_creature(c)

        for it in list(p.inventory.items):
            if not it.is_light or not it.flags.get("lit"):
                continue
            it.charges = max(0, it.charges - ticks)
            if it.charges == 0:
                it.flags["lit"] = False
                self.log.warn("Your %s burns out." % it.base_name())
                if it.def_id == "torch":
                    it.count -= 1
                    if it.count <= 0:
                        p.inventory.unequip_item(it)
                        if it in p.inventory.items:
                            p.inventory.items.remove(it)

        self._burn(ticks)
        self._weather_bite(ticks)
        self._wear_out()
        self._tavern_music(ticks)

        if p.body.dead and not self.game_over:
            self.end_game(p.body.death_cause or "died")

    def _burn(self, ticks: int) -> None:
        """Fires spread, burn down and go out.

        Stepped once per world tick rather than per turn, so a fire runs at
        the same speed whether you are standing still or walking.
        """
        from ..world import fire as fire_mod

        blaze = self.fire
        if not blaze.anything_burning or self.local is None:
            return
        blaze.step(self.local, self.rng, items_at=self.items_at,
                   on_burn_out=lambda item, cell: self.take_item(item, *cell))
        for c in list(self.creatures.values()):
            if not blaze.burning(c.x, c.y, c.z) or not c.alive:
                continue
            fire_mod.burn(c, self.rng,
                          log=self.log if (c.is_player
                                           or self.can_see_creature(c))
                          else None)
            if c.body.dead:
                self.kill_creature(c)

    def _tavern_music(self, ticks: int) -> None:
        """Somebody in the tavern performs, and you are in the room for it.

        The only reason a tavern has ever been worth walking into is a bed and
        a quest. This is the other thing taverns are for: a song you have not
        heard, about a battle you were nowhere near, off somebody who grew up
        four hundred miles from where you did.
        """
        from ..world import artforms
        from . import performance

        p = self.player
        if self.local is None or self.local.tile(p.x, p.y, p.z) != "tavern":
            return
        self._tavern_wait = getattr(self, "_tavern_wait", TAVERN_MUSIC) - ticks
        if self._tavern_wait > 0:
            return
        self._tavern_wait = TAVERN_MUSIC

        near = [c for c in self.visible_creatures()
                if not c.is_hostile_to(p) and p.distance_to(c) <= TAVERN_HEARING]
        if not near:
            return
        players = [c for c in near if performance.repertoire(self.world, c)]
        if not players:
            # Nobody here knows anything: they grew up somewhere, so teach it
            # once and let the room be a room with music in it after that.
            for c in near[:3]:
                performance.teach_civ(self.world, self.rng, c, None, n=2)
            players = [c for c in near if performance.repertoire(self.world, c)]
            if not players:
                return
        who = self.rng.choice(players)
        form = self.rng.choice(performance.repertoire(self.world, who))
        audience = [c for c in near if c is not who] + [p]
        result = performance.perform(self, self.rng, who, form, audience)
        for line in performance.describe(result):
            self.log.good(line) if result.good else self.log.info(line)

    def _moon(self) -> None:
        """Change whoever the moon has a claim on, and change them back.

        Everybody on the map, not only the player: the innkeeper you have been
        buying rooms from all week is the one who turns, which is the whole
        point of a curse being something people carry rather than a monster
        that lives somewhere.
        """
        from . import night

        for c in list(self.creatures.values()):
            if c.body.dead or not night.cursed_with(c):
                continue
            if night.should_change(c, self.time):
                night.transform(self, c)
            elif c.changed:
                night.revert(self, c)

    def _world_season(self) -> None:
        """Let the rest of the world have its season while you have yours.

        Beasts sack towns, heroes make names, wars start and finish. You hear
        about it the way anyone would: as news, some of which is about a job
        you took and somebody else has now done.
        """
        from ..world import livingworld

        mark = livingworld.season_index(self.time)
        if self._season_mark == 0:
            self._season_mark = mark
            return
        if mark <= self._season_mark:
            return
        seasons = min(8, mark - self._season_mark)
        self._season_mark = mark
        before = len(self.world.events)
        livingworld.advance(self.world, self.rng, self.time.year,
                            seasons=seasons)
        for ev in livingworld.news_since(self.world, before, 2):
            self.log.info("Word reaches you: %s" % ev.text)
        self.quests.world_changed(self)

    def kill_creature(self, c: Creature) -> None:
        """Handle a creature's death: corpse, loot, legends and quests."""
        if c.is_player:
            self.end_game(c.body.death_cause or "died")
            return
        if not c.alive:
            return
        c.on_death(self, c.body.death_cause)
        self.scheduler.remove(c.id)
        if c.id in self.companion_ids:
            from . import companions as companion_mod

            companion_mod.on_death(self, c)
        if self.can_see_creature(c):
            self.log.combat("The %s is dead." % c.short_name())
        corpse = corpse_of(c)
        self.drop_item(corpse, c.x, c.y, c.z)
        for it in c.inventory.remove_all():
            self.drop_item(it, c.x, c.y, c.z)
        self.player.kills.append(c.display_name())
        self.quests.on_kill(self, c)
        self.player.needs.add_thought("killed a foe", -2)
        from . import renown as renown_mod

        # Beside the renown record rather than at the top of the method: this
        # is the point the game already treats a death as the player's doing,
        # and standing is the other half of that ledger -- the half that can
        # go down.
        standing_mod.on_kill(self, c)
        told = renown_mod.record_kill(self, c)
        if told is not None:
            self.log.good("They will tell this one. (%s)"
                          % renown_mod.title(self))

    def end_game(self, cause: str) -> None:
        """Finish the run and write the player into the world's legends."""
        if self.game_over:
            return
        self.game_over = True
        self.death_message = cause
        self.log.bad("You have died: %s." % cause)
        p = self.player
        if p.hf_id is None:
            from ..world.history import new_figure, record

            fig = new_figure(
                self.world, self.rng, p.race, None, None,
                year=self.time.year, profession=p.profession or "adventurer",
                creature_id=p.def_id, age=p.age,
            )
            fig.name = p.name
            fig.flags.add("player")
            if len(p.kills) >= 5:
                fig.flags.add("legendary")
            fig.died = self.time.year
            fig.death_cause = cause
            fig.kills = []
            p.hf_id = fig.id
            record(
                self.world, self.time.year, "death",
                "%s the adventurer died: %s. %d foes had fallen to them."
                % (p.name, cause, len(p.kills)),
                [fig.id],
            )

    # -- travel ------------------------------------------------------------ #

    def travel_step(self, dx: int, dy: int) -> bool:
        """Move one tile on the world map. Returns False if blocked."""
        nx, ny = self.player.wx + dx, self.player.wy + dy
        if not self.world.in_bounds(nx, ny):
            self.log.warn("The world ends here.")
            return False
        tile = self.world.tile(nx, ny)
        if tile.is_ocean:
            self.log.warn("You cannot cross open water.")
            return False
        from . import mounts as mounts_mod

        cost = self.world.travel_cost(nx, ny)
        ticks = int(TICKS_PER_DAY * 0.22 * cost * mounts_mod.travel_factor(self))
        entry = {
            (1, 0): "west", (-1, 0): "east", (0, 1): "north", (0, -1): "south",
        }.get((dx, dy), "edge")
        self.enter_world_tile(nx, ny, entry=entry)
        self._tick_world(ticks)
        self.player.needs.exert(20)
        self.player.add_exp("navigation", 6)
        return True

    def can_travel(self) -> bool:
        """True if the player may enter world-map travel right now."""
        for c in self.visible_creatures():
            if c.is_hostile_to(self.player) and self.player.distance_to(c) <= 6:
                return False
        return True

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the whole game."""
        self._store_local()
        return {
            "world": self.world.to_dict(),
            "player": self.player.to_dict(),
            "rng": self.rng.to_dict(),
            "time": self.time.to_dict(),
            "log": self.log.to_dict(),
            "quests": self.quests.to_dict(),
            "scheduler": self.scheduler.to_dict(),
            "turn": self.turn,
            "mode": self.mode,
            "seen": ["%d,%d,%d" % k for k in self.seen],
            "game_over": self.game_over,
            "death_message": self.death_message,
            "weather": self.weather.to_dict(),
            "tracks": tracks_mod.to_list(self),
            "standing": standing_mod.book(self).to_dict(),
            "webs": webs_mod.to_list(self),
            "traps": traps_mod.to_list(self),
            "fire": self.fire.to_list(),
            "frost": self.frost.to_list(),
            "companion_ids": list(self.companion_ids),
            "companions": [c.to_dict() for c in self.travelling_companions],
            "cache": {
                "%d,%d" % k: v for k, v in self._local_cache.items()
            },
            "cache_order": ["%d,%d" % k for k in self._cache_order],
            "here": [self.player.wx, self.player.wy],
            "season_mark": self._season_mark,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Game":
        """Rebuild a game from :meth:`to_dict`."""
        world = World.from_dict(d["world"])
        player = Creature.from_dict(d["player"])
        rng = RNG.from_dict(d["rng"])
        game = cls(world, player, rng)
        game.time = GameTime.from_dict(d.get("time") or {})
        game.log = MessageLog.from_dict(d.get("log") or {})
        game.quests = QuestLog.from_dict(d.get("quests") or {})
        game.scheduler = Scheduler.from_dict(d.get("scheduler") or {})
        game.turn = int(d.get("turn", 0))
        game.mode = str(d.get("mode", "local"))
        game.game_over = bool(d.get("game_over", False))
        game.death_message = str(d.get("death_message", ""))
        game.weather = Weather.from_dict(d.get("weather") or {})
        tracks_mod.from_list(game, d.get("tracks") or [])
        game.standing = standing_mod.Standing.from_dict(
            d.get("standing") or {})
        webs_mod.from_list(game, d.get("webs") or [])
        traps_mod.from_list(game, d.get("traps") or [])
        game.fire = FireLayer.from_list(d.get("fire") or [])
        game.frost = Frost.from_list(d.get("frost") or [])
        game.companion_ids = [int(i) for i in d.get("companion_ids", [])]
        game._season_mark = int(d.get("season_mark", 0))
        game.travelling_companions = [
            Creature.from_dict(c) for c in d.get("companions", [])
        ]
        game._local_cache = {
            tuple(int(v) for v in k.split(",")): v
            for k, v in (d.get("cache") or {}).items()
        }
        game._cache_order = [
            tuple(int(v) for v in k.split(","))
            for k in d.get("cache_order", [])
            if tuple(int(v) for v in k.split(",")) in game._local_cache
        ]
        for key in game._local_cache:
            if key not in game._cache_order:
                game._cache_order.append(key)
        game.seen = {
            tuple(int(v) for v in k.split(",")) for k in d.get("seen", [])
        }

        wx, wy = d.get("here", [player.wx, player.wy])
        cached = game._local_cache.get((wx, wy))
        if cached is not None:
            game.local = LocalMap.from_dict(cached["map"])
            game.creatures = {}
            for cd in cached["creatures"]:
                c = Creature.from_dict(cd)
                game.creatures[c.id] = c
            game.items_on_ground = {
                tuple(int(v) for v in k.split(",")): [
                    Item.from_dict(i) for i in items
                ]
                for k, items in cached["items"].items()
            }
            game.creatures[player.id] = player
            from . import companions as companion_mod

            companion_mod.bring_along(game, None)
            game.scheduler = Scheduler.from_dict(d.get("scheduler") or {})
            for c in game.creatures.values():
                if not game.scheduler.contains(c.id) and not c.body.dead:
                    game.scheduler.add(
                        c.id, c.effective_speed(), priority=1 if c.is_player else 0)
        else:
            game.enter_world_tile(wx, wy, entry="center")
        game.update_fov()
        return game

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Game(%s, turn %d, %s)" % (
            self.player.name, self.turn, self.time.date_str()
        )


def _teach_own_forms(world, rng, player, race: str) -> None:
    """Give a new adventurer the songs of the people they grew up among.

    Nobody arrives in the world knowing nothing of it. Which forms depends on
    the race, which is the only tie a player character has to a civilization.
    """
    from . import performance

    home = None
    for civ in getattr(world, "civs", ()):
        if civ.race == race:
            home = civ.id
            break
    performance.teach_civ(world, rng, player, home)
