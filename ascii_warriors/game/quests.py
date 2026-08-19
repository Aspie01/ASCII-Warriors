"""Quests drawn from the world's own history."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from ..data import creatures as creature_data
from ..engine.rng import RNG

#: How far a bounty will send you. The complaint is that they are taking
#: *our* livestock, so the answer is somewhere you could walk to and back.
BOUNTY_RANGE = 4

#: Every kind of quest `generate_quest` can produce. It listed a "deliver"
#: that had no builder, no progress path and no completion: the word appeared
#: nowhere else in the project.
QUEST_KINDS = (
    "slay_beast", "clear_site", "retrieve_artifact", "bounty", "explore",
)


class Quest:
    """One outstanding job."""

    _next_id = 1

    def __init__(self, kind: str, title: str, description: str) -> None:
        self.id = Quest._next_id
        Quest._next_id += 1
        self.kind = kind
        self.title = title
        self.description = description
        self.giver_hf: Optional[int] = None
        self.giver_name = ""
        #: Where the job was taken. A quest recorded who set it and never
        #: where they were standing, so "return to Ustuth to claim your
        #: reward" named a person with no address: walk out of the town and
        #: the log could not tell you which town it had been.
        self.giver_site_name = ""
        self.giver_wx = -1
        self.giver_wy = -1
        self.target_hf: Optional[int] = None
        self.target_def = ""
        self.site_id: Optional[int] = None
        self.site_name = ""
        self.artifact_id: Optional[int] = None
        self.wx = 0
        self.wy = 0
        self.reward = 0
        self.state = "offered"
        self.progress = 0
        self.goal = 1

    @property
    def active(self) -> bool:
        """True while the quest is in progress."""
        return self.state == "active"

    @property
    def done(self) -> bool:
        """True once the quest is finished."""
        return self.state == "done"

    def summary(self) -> str:
        """One-line status."""
        mark = {"offered": "?", "active": "*", "done": "+", "failed": "-"}.get(
            self.state, "?"
        )
        return "[%s] %s (%d/%d)" % (mark, self.title, self.progress, self.goal)

    def detail_lines(self) -> List[str]:
        """Full text for the quest log."""
        out = [self.title, ""]
        out.extend(self.description.split("\n"))
        out.append("")
        if self.giver_name:
            where = ""
            if self.giver_wx >= 0:
                where = " at %s (%d, %d)" % (
                    self.giver_site_name or "a place you have been",
                    self.giver_wx, self.giver_wy)
            out.append("Given by %s%s." % (self.giver_name, where))
        if self.site_name:
            out.append("Location: %s at (%d, %d)." % (self.site_name, self.wx, self.wy))
        else:
            out.append("Location: (%d, %d)." % (self.wx, self.wy))
        out.append("Progress: %d/%d" % (self.progress, self.goal))
        if self.reward:
            out.append("Reward: %d coins." % self.reward)
        return out

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the quest."""
        return {
            "id": self.id, "kind": self.kind, "title": self.title,
            "desc": self.description, "giver": self.giver_hf,
            "giver_name": self.giver_name, "target": self.target_hf,
            "giver_site": self.giver_site_name,
            "giver_wx": self.giver_wx, "giver_wy": self.giver_wy,
            "target_def": self.target_def, "site": self.site_id,
            "site_name": self.site_name, "artifact": self.artifact_id,
            "wx": self.wx, "wy": self.wy, "reward": self.reward,
            "state": self.state, "progress": self.progress, "goal": self.goal,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Quest":
        """Rebuild from :meth:`to_dict`."""
        q = cls(str(d["kind"]), str(d["title"]), str(d.get("desc", "")))
        q.id = int(d.get("id", q.id))
        Quest._next_id = max(Quest._next_id, q.id + 1)
        q.giver_hf = d.get("giver")
        q.giver_name = str(d.get("giver_name", ""))
        q.giver_site_name = str(d.get("giver_site", ""))
        q.giver_wx = int(d.get("giver_wx", -1))
        q.giver_wy = int(d.get("giver_wy", -1))
        q.target_hf = d.get("target")
        q.target_def = str(d.get("target_def", ""))
        q.site_id = d.get("site")
        q.site_name = str(d.get("site_name", ""))
        q.artifact_id = d.get("artifact")
        q.wx = int(d.get("wx", 0))
        q.wy = int(d.get("wy", 0))
        q.reward = int(d.get("reward", 0))
        q.state = str(d.get("state", "offered"))
        q.progress = int(d.get("progress", 0))
        q.goal = int(d.get("goal", 1))
        return q

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Quest(%s)" % self.summary()


class QuestLog:
    """Everything the player has agreed to do."""

    def __init__(self) -> None:
        self.active: List[Quest] = []
        self.completed: List[Quest] = []
        self.offered: List[Quest] = []

    def offer(self, quest: Quest) -> None:
        """Record a quest as offered but not yet accepted."""
        quest.state = "offered"
        self.offered.append(quest)

    def accept(self, quest: Quest) -> None:
        """Take a quest on."""
        quest.state = "active"
        if quest in self.offered:
            self.offered.remove(quest)
        if quest not in self.active:
            self.active.append(quest)

    def complete(self, quest: Quest, game) -> None:
        """Finish a quest and pay out."""
        if quest.state == "done":
            return
        quest.state = "done"
        quest.progress = quest.goal
        if quest in self.active:
            self.active.remove(quest)
        self.completed.append(quest)
        game.log.good("Quest complete: %s" % quest.title)
        if quest.reward:
            from .item import Item

            game.player.inventory.add(Item("coin", "silver", count=quest.reward))
            game.log.good("You receive %d coins." % quest.reward)
        game.player.needs.add_thought("completed a great deed", -12)
        game.player.add_exp("leadership", 60)
        from . import renown as renown_mod

        renown_mod.record_quest(game, quest)

    def fail(self, quest: Quest, game) -> None:
        """Mark a quest failed."""
        quest.state = "failed"
        if quest in self.active:
            self.active.remove(quest)
        self.completed.append(quest)
        game.log.bad("Quest failed: %s" % quest.title)

    # -- triggers ---------------------------------------------------------- #

    def on_kill(self, game, victim) -> None:
        """Advance kill quests when something dies."""
        for q in list(self.active):
            if q.kind in ("slay_beast", "bounty"):
                matched = (
                    (q.target_hf is not None and victim.hf_id == q.target_hf)
                    or (q.target_def and victim.def_id == q.target_def)
                )
                if matched:
                    q.progress += 1
                    if q.progress >= q.goal:
                        game.log.good("You have slain your quarry.")
                        q.state = "active"
                        self._ready(game, q)
            elif q.kind == "clear_site":
                if game.local is not None and game.local.site_id == q.site_id:
                    remaining = [
                        c for c in game.creatures.values()
                        if not c.body.dead and c.faction == "hostile"
                    ]
                    q.progress = max(q.progress, q.goal - len(remaining))
                    if not remaining:
                        self._ready(game, q)

    def world_changed(self, game) -> None:
        """Check outstanding work against a world that kept moving.

        The point of a living world is that it does not hold the door for you.
        Take a month getting to the lair and you may find the hero of some
        other town got there first, and the job you were paid to do is a story
        somebody else is telling.
        """
        world = game.world
        for q in list(self.active) + list(self.offered):
            if q.target_hf is None:
                continue
            fig = world.figures.get(q.target_hf)
            if fig is None or fig.died is None:
                continue
            if q.state == "offered":
                self.offered.remove(q)
                continue
            game.log.warn("Word reaches you: %s is dead already -- %s."
                          % (fig.display_name, fig.death_cause
                             or "nobody says how"))
            self.fail(q, game)

    def on_arrive(self, game, wx: int, wy: int) -> None:
        """Advance travel quests when the player reaches a place."""
        for q in list(self.active):
            if q.kind == "explore" and (q.wx, q.wy) == (wx, wy):
                q.progress = q.goal
                self._ready(game, q)
            elif q.kind in ("slay_beast", "clear_site") and (q.wx, q.wy) == (wx, wy):
                game.log.info("You have arrived at %s." % (q.site_name or "your goal"))

    def on_pickup(self, game, item) -> None:
        """Advance retrieval quests when the player picks something up."""
        for q in list(self.active):
            if q.kind == "retrieve_artifact" and item.artifact_id == q.artifact_id:
                q.progress = q.goal
                game.log.good("You have recovered %s." % item.name())
                self._ready(game, q)

    def _ready(self, game, quest: Quest) -> None:
        """A quest's objective is met; complete it or ask the player to report back."""
        if quest.giver_hf is None:
            self.complete(quest, game)
        else:
            game.log.good(
                "%s is met. Return to %s to claim your reward."
                % (quest.title, quest.giver_name or "the one who sent you")
            )

    def turn_in(self, game, hf_id: Optional[int]) -> List[Quest]:
        """Complete every finished quest given by a particular figure."""
        done: List[Quest] = []
        for q in list(self.active):
            if q.giver_hf == hf_id and q.progress >= q.goal:
                self.complete(q, game)
                done.append(q)
        return done

    def for_site(self, site_id: int) -> List[Quest]:
        """Active quests pointing at a site."""
        return [q for q in self.active if q.site_id == site_id]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the log."""
        return {
            "active": [q.to_dict() for q in self.active],
            "completed": [q.to_dict() for q in self.completed],
            "offered": [q.to_dict() for q in self.offered],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "QuestLog":
        """Rebuild from :meth:`to_dict`."""
        log = cls()
        log.active = [Quest.from_dict(q) for q in d.get("active", [])]
        log.completed = [Quest.from_dict(q) for q in d.get("completed", [])]
        log.offered = [Quest.from_dict(q) for q in d.get("offered", [])]
        return log


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


def generate_quest(rng: RNG, game, giver) -> Optional[Quest]:
    """Build a quest a particular NPC would plausibly hand out."""
    world = game.world
    taken = {
        (q.kind, q.site_id, q.target_hf)
        for q in game.quests.active + game.quests.offered
    }

    builders = [_quest_slay_beast, _quest_clear_site, _quest_retrieve,
                _quest_bounty, _quest_explore]
    rng.shuffle(builders)
    for build in builders:
        q = build(rng, game, giver)
        if q is None:
            continue
        if (q.kind, q.site_id, q.target_hf) in taken:
            continue
        q.giver_name = giver.display_name()
        q.giver_hf = giver.hf_id
        home = game.current_site()
        q.giver_site_name = home.name if home is not None else ""
        q.giver_wx, q.giver_wy = game.player.wx, game.player.wy
        # People pay a name what a name is worth. A wanderer nobody has heard
        # of is offered the same work for rather less.
        from . import renown as renown_mod

        q.reward = int(q.reward * (1.0 + renown_mod.renown(game) / 120.0))
        return q
    return None


def _living_monsters(world) -> List[Any]:
    return [
        f for f in world.figures.values()
        if "monster" in f.flags and f.alive(world.year)
    ]


def _quest_slay_beast(rng: RNG, game, giver) -> Optional[Quest]:
    """Kill a named megabeast that is terrorising the region."""
    world = game.world
    monsters = _living_monsters(world)
    if not monsters:
        return None
    beast = rng.choice(monsters)
    defn = creature_data.get(beast.creature_id)
    # Where it actually lairs. This used to be `rng.choice(lairs)` -- the quest
    # told you where to go and the answer was a coin toss, so the beast was
    # never there and the quest could not be completed by anybody.
    site = next((s for s in world.sites if s.id == beast.site_id), None)
    q = Quest(
        "slay_beast",
        "Slay the %s %s" % (defn.name, beast.display_name),
        "The %s %s has troubled these lands for years. It is said to lair "
        "%s. Kill it, and bring word back to me."
        % (defn.name, beast.display_name,
           "at %s" % site.name if site else "somewhere in the wilds"),
    )
    q.target_hf = beast.id
    q.target_def = defn.id
    if site is not None:
        q.site_id = site.id
        q.site_name = site.name
        q.wx, q.wy = site.wx, site.wy
    else:
        q.wx, q.wy = game.player.wx, game.player.wy
    q.reward = 120 + defn.tier * rng.randint(30, 90)
    return q


def _quest_clear_site(rng: RNG, game, giver) -> Optional[Quest]:
    """Clear out a nest of bandits, goblins or the undead."""
    world = game.world
    candidates = [
        s for s in world.sites
        if s.kind in ("camp", "ruin", "cave", "tomb", "dark_pits")
        and not (s.kind == "ruin" and rng.chance(0.3))
    ]
    if not candidates:
        return None
    px, py = game.player.wx, game.player.wy
    candidates.sort(key=lambda s: max(abs(s.wx - px), abs(s.wy - py)))
    site = rng.choice(candidates[: max(1, len(candidates) // 2)])
    who = {
        "camp": "bandits", "ruin": "the restless dead", "cave": "kobolds",
        "tomb": "the dead", "dark_pits": "goblins",
    }.get(site.kind, "brigands")
    q = Quest(
        "clear_site",
        "Clear %s" % site.name,
        "%s have taken %s, a %s to the %s of here. Drive them out, all of them."
        % (who.capitalize(), site.name, site.kind_name,
           _bearing(px, py, site.wx, site.wy)),
    )
    q.site_id = site.id
    q.site_name = site.name
    q.wx, q.wy = site.wx, site.wy
    q.goal = rng.randint(3, 8)
    q.reward = 80 + rng.randint(30, 140)
    return q


def _quest_retrieve(rng: RNG, game, giver) -> Optional[Quest]:
    """Fetch a lost artifact."""
    world = game.world
    # Not one already in the pack. The ledger clears `site_id` when the
    # player takes an artifact, so this is belt and braces -- but a save made
    # before it did carries the old record forever, and an offer to fetch
    # something you are wearing cannot be finished by anybody: the pickup that
    # would complete it already happened.
    mine = {getattr(i, "artifact_id", None)
            for i in game.player.inventory.items}
    arts = [a for a in world.artifacts
            if a.site_id is not None and a.id not in mine]
    if not arts:
        return None
    art = rng.choice(arts)
    site = world.site(art.site_id)
    if site is None:
        return None
    q = Quest(
        "retrieve_artifact",
        "Recover %s" % art.name,
        "%s was lost to us. It lies at %s, a %s. Bring it back and you will be "
        "well paid." % (art.name, site.name, site.kind_name),
    )
    q.artifact_id = art.id
    q.site_id = site.id
    q.site_name = site.name
    q.wx, q.wy = site.wx, site.wy
    q.reward = 180 + rng.randint(60, 260)
    return q


def _quest_bounty(rng: RNG, game, giver) -> Optional[Quest]:
    """Hunt a set number of a particular creature."""
    world = game.world
    here = world.tile(game.player.wx, game.player.wy)
    options = creature_data.spawnable(here.biome, max_tier=3,
                                      flags_any=("SAVAGE", "EVIL"))
    options = [c for c in options if not c.intelligent or c.has("EVIL")]
    # Nothing that lives underground. The complaint is that they are taking
    # livestock out of a field, and a bounty on something the wildlife roll
    # only ever puts in a cavern sends you to a meadow to look for it.
    options = [c for c in options if not c.has("SUBTERRANEAN")]
    if not options:
        return None
    defn = rng.choice(options)
    count = rng.randint(3, 7)
    # Somewhere they actually live. Every other kind of work names a place;
    # this one pinned the town you were standing in and left the destination
    # blank, so the log read "Location: (59, 20)" for the square under your
    # feet and the map marker pointed at the person who sent you.
    spot = _hunting_ground(rng, game, defn)
    if spot is None:
        return None
    (hx, hy), where = spot
    q = Quest(
        "bounty",
        "Hunt %d %s" % (count, defn.plural),
        "%s have been taking our livestock and worse, out of %s to the %s. "
        "Bring me proof of %d of them."
        % (defn.plural.capitalize(), where,
           _bearing(game.player.wx, game.player.wy, hx, hy), count),
    )
    q.target_def = defn.id
    q.goal = count
    q.wx, q.wy = hx, hy
    q.site_name = where
    q.reward = 20 * count + rng.randint(15, 80)
    return q


def _hunting_ground(rng: RNG, game, defn):
    """A wild square near the player where this creature lives.

    Returns ``((wx, wy), name)`` or None. Near, because a bounty is local
    work: the complaint is that they are taking *our* livestock.
    """
    world = game.world
    px, py = game.player.wx, game.player.wy
    found = []
    for wy in range(max(0, py - BOUNTY_RANGE), min(world.height, py + BOUNTY_RANGE + 1)):
        for wx in range(max(0, px - BOUNTY_RANGE), min(world.width, px + BOUNTY_RANGE + 1)):
            tile = world.tile(wx, wy)
            if tile.is_ocean or tile.site_id is not None:
                continue
            if (wx, wy) == (px, py):
                continue
            if not creature_data.spawnable(tile.biome, max_tier=5):
                continue
            if defn not in creature_data.spawnable(tile.biome, max_tier=5):
                continue
            found.append((wx, wy))
    if not found:
        return None
    wx, wy = rng.choice(found)
    region = world.region_at(wx, wy)
    return ((wx, wy), region.name if region is not None else "the wilds")


def _quest_explore(rng: RNG, game, giver) -> Optional[Quest]:
    """Carry word to a distant settlement."""
    world = game.world
    px, py = game.player.wx, game.player.wy
    far = [
        s for s in world.sites
        if s.is_settlement and max(abs(s.wx - px), abs(s.wy - py)) > 4
    ]
    if not far:
        return None
    site = rng.choice(far)
    q = Quest(
        "explore",
        "Carry word to %s" % site.name,
        "Word must reach %s, a %s to the %s. Travel there and speak with them."
        % (site.name, site.kind_name, _bearing(px, py, site.wx, site.wy)),
    )
    q.site_id = site.id
    q.site_name = site.name
    q.wx, q.wy = site.wx, site.wy
    q.reward = 40 + rng.randint(15, 90)
    return q


def _bearing(x0: int, y0: int, x1: int, y1: int) -> str:
    """Compass direction from one world tile to another."""
    from ..engine.geometry import direction_name

    return direction_name(x1 - x0, y1 - y0)
