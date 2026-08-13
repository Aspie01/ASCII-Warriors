"""The game state: the single object every screen talks to."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

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
from .weather import Weather, starting_weather

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
        else:
            lm_rng = self.rng.sub("local-%d-%d" % (wx, wy))
            self.local, population = generate_local(
                self.world, wx, wy, lm_rng, site=site
            )
            self.creatures = {}
            self.items_on_ground = {}
            self._populate(population, lm_rng, site)

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
            self.add_creature(c)
        self.spawn_wildlife()

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
        }
        # Keep the cache from growing without bound on long journeys, dropping
        # the tiles the player has not seen for longest.
        self._cache_order = [c for c in self._cache_order if c != key]
        self._cache_order.append(key)
        while len(self._cache_order) > 24:
            stale = self._cache_order.pop(0)
            self._local_cache.pop(stale, None)

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
        """Place a creature on a new cell."""
        c.x, c.y, c.z = x, y, z
        if c.is_player:
            self.update_fov()

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
        if self.local.is_outside(x, y, z):
            return self.time.light_level() * self.weather.light_modifier()
        # Underground: only whatever the player is actually holding alight.
        if self.player_light() > 0:
            return 0.8
        return 0.05

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
        for c in self.creatures_at(x, y, z):
            out.append(Frag("", colors.UI["fg"]))
            out.extend(c.describe())
        pile = self.items_at(x, y, z)
        if pile:
            out.append(Frag("", colors.UI["fg"]))
            out.append(Frag("On the ground:", colors.UI["accent"]))
            for it in pile[:8]:
                out.append(Frag("  " + it.name(article=True), it.color))
        return out

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

        for c in list(self.creatures.values()):
            if c is p or c.body.dead:
                continue
            c.needs.tick(ticks, c, self)
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

        if p.body.dead and not self.game_over:
            self.end_game(p.body.death_cause or "died")

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
        cost = self.world.travel_cost(nx, ny)
        ticks = int(TICKS_PER_DAY * 0.22 * cost)
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
