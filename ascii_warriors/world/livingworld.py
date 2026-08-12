"""History that keeps happening while you play.

The title screen promises that the world does not wait for you, and until now
it did: history was simulated once at generation and then frozen for the rest
of the game. This runs a quieter version of that simulation, one season at a
time, in both modes. Beasts sack towns you have never visited, heroes take the
kills you were too slow to make, wars start and end, ruins are resettled, and
the legends screen keeps filling up while you play.

Everything here is bounded work: a fixed handful of rolls per season, no
sweeps over the map. It runs inside the fortress's season change, and a
fortress that stutters once a season is a fortress nobody wants to play.
"""

from __future__ import annotations

from typing import Any, List, Optional

from ..data import creatures as creature_data
from ..data import names as name_data
from ..engine.rng import RNG
from . import history as history_mod

#: A world year is four of these.
SEASONS_PER_YEAR = 4

#: Odds per season, tuned so a year of play produces a handful of events and a
#: long fortress produces a chronicle rather than an apocalypse.
BEAST_WAKES = 0.08
BEAST_RAMPAGE = 0.09          # per living beast
HERO_RISES = 0.22
LEADER_DIES = 0.02            # per civilization
WAR_DECLARED = 0.06
BATTLE = 0.14                 # per pair at war
PEACE = 0.07
ARTIFACT_MADE = 0.06
ARTIFACT_MOVES = 0.05
RESETTLE = 0.05
PLAGUE = 0.03
BANDITS = 0.05
NEW_SITE = 0.04

#: More than this many beasts abroad and the world stops waking new ones.
MAX_BEASTS = 8

#: Most a settlement can grow in one season, and the size it stops at. Without
#: growth the world only ever shrinks: every plague and every rampage takes
#: people away and nothing ever puts them back.
GROWTH = 0.015
POP_CAP = 1500


def advance(world, rng: RNG, year: int, *, seasons: int = 1) -> List[Any]:
    """Run the world forward. Returns the events it recorded, in order."""
    mark = len(world.events)
    for _ in range(max(0, seasons)):
        _one_season(world, rng, year)
    world.year = max(world.year, year)
    return world.events[mark:]


def season_index(time) -> int:
    """A single number that changes exactly once per season."""
    return time.year * SEASONS_PER_YEAR + (time.month - 1) // 3


def news_since(world, mark: int, n: int = 3) -> List[Any]:
    """Events recorded since *mark* that are worth repeating."""
    fresh = world.events[mark:]
    worth = [e for e in fresh if e.kind in TOLD_ABOUT]
    return worth[-n:]


#: What people actually gossip about. Nobody carries word of a birth in a
#: village three hundred miles away.
TOLD_ABOUT = frozenset({
    "beast_attack", "beast_slain", "site_destroyed", "site_conquered",
    "war_declared", "peace", "artifact_stolen", "artifact_created",
    "hero_rose", "plague", "became_leader", "resettled", "banditry",
})


def _one_season(world, rng: RNG, year: int) -> None:
    """One season of the world getting on with itself."""
    civs = history_mod._living_civs(world)

    _towns(world, rng, year)
    _leaders(world, rng, year, civs)
    _heroes(world, rng, year, civs)
    _beasts(world, rng, year)
    _wars(world, rng, year, civs)
    _works(world, rng, year, civs)
    _fortunes(world, rng, year, civs)


def _towns(world, rng: RNG, year: int) -> None:
    """Ordinary life: towns fill back up, and empty ones stop being towns.

    Wars, plagues and beasts all take people and none of them put any back,
    so without this the world quietly empties. The second half matters as
    much: a settlement with nobody left in it is a ruin, not a town you can
    walk into and find shops in.
    """
    for site in world.sites:
        if not site.is_settlement or site.is_ruin:
            continue
        if site.population <= 0:
            history_mod._destroy_site(
                world, rng, site, year,
                "when the last of its people were gone")
            continue
        gain = int(site.population * rng.uniform(0.0, GROWTH))
        if not gain and rng.chance(0.25):
            gain = 1
        site.population = min(POP_CAP, site.population + gain)


def _leaders(world, rng: RNG, year: int, civs) -> None:
    """Rulers die and are replaced, in your lifetime rather than before it."""
    for civ in civs:
        leader = world.figures.get(civ.leader_hf) if civ.leader_hf else None
        if leader is None or not leader.alive(year):
            history_mod._pick_leader(world, rng, civ, year)
            continue
        if not rng.chance(LEADER_DIES):
            continue
        age = year - leader.born
        lifespan = creature_data.get(civ.race).lifespan[1]
        if age < lifespan * 0.7:
            continue
        leader.died = year
        leader.death_cause = "died of old age"
        history_mod.record(
            world, year, "death",
            "%s died of old age." % leader.display_name,
            [leader.id], [], [civ.id],
        )
        history_mod._pick_leader(world, rng, civ, year)


def _heroes(world, rng: RNG, year: int, civs) -> None:
    """Somebody, somewhere, becomes worth writing about."""
    if not civs or not rng.chance(HERO_RISES):
        return
    civ = rng.choice(civs)
    live = history_mod._live_sites(world, civ)
    if not live:
        return
    site = rng.choice(live)
    fig = history_mod.new_figure(world, rng, civ.race, civ.id, site.id,
                                 year=year, profession="warrior",
                                 age=rng.randint(20, 45))
    fig.flags.add("hero")
    fig.titles.append(name_data.title_for(rng, "hero"))
    fig.stats["prowess"] = fig.stats.get("prowess", 5) + rng.randint(3, 9)
    history_mod.record(
        world, year, "hero_rose",
        "%s rose to prominence as a warrior of %s." % (fig.display_name,
                                                       civ.name),
        [fig.id], [site.id], [civ.id],
    )


def _beasts(world, rng: RNG, year: int) -> None:
    """Beasts wake, hunt, and occasionally meet somebody better than them."""
    monsters = history_mod._living_monsters(world, year)
    if len(monsters) < MAX_BEASTS and rng.chance(BEAST_WAKES):
        history_mod._spawn_megabeast(world, rng, year)
    for beast in monsters:
        if rng.chance(BEAST_RAMPAGE):
            rampage(world, rng, year, beast)


def rampage(world, rng: RNG, year: int, beast) -> Optional[Any]:
    """One beast falls on one settlement. A hero may answer for it.

    The same shape as the yearly history, kept here rather than shared with it
    so that changing how a season plays out cannot change how a world is
    generated. Worlds must stay reproducible from their seed.
    """
    targets = [s for s in world.sites if s.is_settlement and not s.is_ruin]
    if not targets:
        return None
    site = rng.choice(targets)
    defn = creature_data.get(beast.creature_id)
    killed = rng.randint(1, max(2, site.population // 8))
    site.population = max(0, site.population - killed)
    ev = history_mod.record(
        world, year, "beast_attack",
        "The %s %s attacked %s and killed %d." % (
            defn.name, beast.display_name, site.name, killed),
        [beast.id], [site.id], [site.civ_id] if site.civ_id else [],
    )
    beast.stats["renown"] = beast.stats.get("renown", 0) + killed
    if site.population <= 0:
        history_mod._destroy_site(
            world, rng, site, year,
            "by the %s %s" % (defn.name, beast.display_name), beast)
        return ev

    heroes = [
        f for f in world.figures.values()
        if "hero" in f.flags and f.alive(year) and f.civ_id == site.civ_id
    ]
    if not heroes or not rng.chance(0.5):
        return ev
    hero = rng.choice(heroes)
    if hero.stats.get("prowess", 5) + rng.randint(0, 8) > \
            beast.stats.get("prowess", 12) + rng.randint(0, 8):
        slay(world, year, hero, beast, "near %s" % site.name, site)
    else:
        hero.died = year
        hero.death_cause = "slain by the %s %s" % (defn.name,
                                                   beast.display_name)
        beast.kills.append(hero.id)
        history_mod.record(
            world, year, "death",
            "%s was slain by the %s %s near %s." % (
                hero.display_name, defn.name, beast.display_name, site.name),
            [hero.id, beast.id], [site.id],
        )
    return ev


def slay(world, year: int, killer, beast, where: str, site=None) -> Any:
    """Write a beast out of the world, and its killer into it.

    Used by the world simulation when a hero gets there first, and by the
    fortress when a militia brings one down on its own doorstep.
    """
    defn = creature_data.get(beast.creature_id)
    beast.died = year
    beast.death_cause = "slain by %s" % killer.display_name
    killer.kills.append(beast.id)
    killer.flags.add("legendary")
    return history_mod.record(
        world, year, "beast_slain",
        "%s slew the %s %s %s." % (killer.display_name, defn.name,
                                   beast.display_name, where),
        [killer.id, beast.id], [site.id] if site is not None else [],
    )


def _wars(world, rng: RNG, year: int, civs) -> None:
    """Wars are declared, fought and ended while you dig."""
    if len(civs) >= 2 and rng.chance(WAR_DECLARED):
        a, b = rng.sample(civs, 2)
        if b.id not in a.at_war_with:
            a.at_war_with.add(b.id)
            b.at_war_with.add(a.id)
            history_mod.record(
                world, year, "war_declared",
                "%s declared war on %s." % (a.name, b.name),
                [], [], [a.id, b.id],
            )
    for civ in civs:
        for enemy_id in list(civ.at_war_with):
            enemy = world.civ(enemy_id)
            if enemy is None or enemy.destroyed is not None:
                civ.at_war_with.discard(enemy_id)
                continue
            if civ.id > enemy.id:
                continue
            if rng.chance(BATTLE):
                history_mod._fight_battle(world, rng, civ, enemy, year)
            elif rng.chance(PEACE):
                civ.at_war_with.discard(enemy.id)
                enemy.at_war_with.discard(civ.id)
                history_mod.record(
                    world, year, "peace",
                    "%s and %s made peace." % (civ.name, enemy.name),
                    [], [], [civ.id, enemy.id],
                )


def _works(world, rng: RNG, year: int, civs) -> None:
    """Smiths make legends, outlaws gather, civilizations spread."""
    if rng.chance(ARTIFACT_MADE) and civs:
        civ = rng.choice(civs)
        live = history_mod._live_sites(world, civ)
        if live:
            site = rng.choice(live)
            smith = history_mod.new_figure(
                world, rng, civ.race, civ.id, site.id, year=year,
                profession="smith", age=rng.randint(25, 60))
            history_mod._make_artifact(world, rng, smith, year, site)

    if rng.chance(BANDITS):
        camps = [s for s in world.sites if s.kind == "camp"
                 and s.owner_hf is None]
        if camps:
            camp = rng.choice(camps)
            leader = history_mod.new_figure(
                world, rng, "human", None, camp.id, year=year,
                profession="bandit leader")
            leader.flags.add("bandit")
            camp.owner_hf = leader.id
            camp.name = name_data.group_name(rng, "bandit")
            history_mod.record(
                world, year, "banditry",
                "%s gathered a band of outlaws at %s." % (leader.display_name,
                                                          camp.name),
                [leader.id], [camp.id],
            )

    if rng.chance(NEW_SITE) and civs:
        from .civ import found_site, site_kind_for

        civ = rng.choice(civs)
        if history_mod._live_sites(world, civ):
            site = found_site(world, civ, rng,
                              site_kind_for(civ.race, "minor"), year)
            if site is not None:
                history_mod.record(
                    world, year, "founded_site",
                    "%s founded %s." % (civ.name, site.name),
                    [], [site.id], [civ.id],
                )


def _fortunes(world, rng: RNG, year: int, civs) -> None:
    """Plagues, stolen legends, and ruins somebody decides to rebuild."""
    if rng.chance(PLAGUE):
        settlements = [s for s in world.sites if s.is_settlement
                       and not s.is_ruin]
        if settlements:
            site = rng.choice(settlements)
            lost = rng.randint(1, max(2, site.population // 6))
            site.population = max(0, site.population - lost)
            history_mod.record(
                world, year, "plague",
                "A plague swept through %s, killing %d." % (site.name, lost),
                [], [site.id],
            )
            if site.population <= 0:
                # An empty town is a ruin, not a town with nobody in it.
                history_mod._destroy_site(world, rng, site, year,
                                          "by plague")

    if rng.chance(ARTIFACT_MOVES) and world.artifacts:
        art = rng.choice([a for a in world.artifacts if not a.lost]
                         or world.artifacts)
        thieves = [
            f for f in world.figures.values()
            if f.alive(year) and ("bandit" in f.flags or "monster" in f.flags)
        ]
        if thieves and not art.lost:
            thief = rng.choice(thieves)
            art.holder_hf = thief.id
            art.site_id = thief.site_id
            history_mod.record(
                world, year, "artifact_stolen",
                "%s stole %s." % (thief.display_name, art.name),
                [thief.id], [art.site_id] if art.site_id else [],
            )

    if rng.chance(RESETTLE) and civs:
        ruins = [s for s in world.sites if s.is_ruin and s.is_settlement]
        if ruins:
            site = rng.choice(ruins)
            civ = rng.choice(civs)
            site.destroyed = None
            site.population = rng.randint(12, 60)
            site.civ_id = civ.id
            if site.id not in civ.sites:
                civ.sites.append(site.id)
            world.tile(site.wx, site.wy).feature = "site"
            history_mod.record(
                world, year, "resettled",
                "%s resettled the ruins of %s." % (civ.name, site.name),
                [], [site.id], [civ.id],
            )


def wandering_beast(world, rng: RNG, year: int) -> Optional[Any]:
    """Pick a living megabeast, if there is one abroad."""
    monsters = history_mod._living_monsters(world, year)
    if not monsters:
        return None
    return rng.choice(monsters)
