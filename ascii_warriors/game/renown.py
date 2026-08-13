"""What the world knows about you.

An adventurer used to be written into history exactly once, at the moment of
death. Everything before that happened to nobody in particular: kill the
dragon the tavern keeper sent you after and the legends screen would not have
heard of it.

This gives the player a historical figure from the first turn, records the
deeds that are worth recording as they happen, and turns the total into a
reputation that people react to. Retiring puts the adventurer down as a living
figure in the world rather than a dead one, so the next game can meet them.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ..world import history as history_mod

#: Deeds worth a line in the legends, and what each is worth in renown.
KILL_RENOWN = {
    "megabeast": 25,
    "semimegabeast": 12,
    "night": 10,
    "bandit": 6,
    "leader": 8,
}

#: What finishing a job for somebody is worth.
QUEST_RENOWN = 8

#: Titles, worst first. The last one you qualify for is the one you get.
TITLES: Tuple[Tuple[int, str], ...] = (
    (0, "wanderer"),
    (10, "traveller"),
    (25, "adventurer"),
    (50, "champion"),
    (90, "hero"),
    (150, "legend"),
)


def figure(game):
    """The player's historical figure, made on demand.

    A player who has not done anything yet still needs to exist: the first
    thing they do is the thing the world needs to attribute.
    """
    p = game.player
    if p.hf_id is not None:
        fig = game.world.figures.get(p.hf_id)
        if fig is not None:
            return fig
    fig = history_mod.new_figure(
        game.world, game.rng, p.race, None, None,
        year=game.time.year, profession=p.profession or "adventurer",
        creature_id=p.def_id, age=p.age,
    )
    fig.name = p.name
    fig.flags.add("player")
    p.hf_id = fig.id
    return fig


def renown(game) -> int:
    """How much the world has heard about this adventurer."""
    return _stored(game)


def _stored(game) -> int:
    """Renown lives on the historical figure, because that is what survives."""
    fig = game.world.figures.get(game.player.hf_id) \
        if game.player.hf_id is not None else None
    if fig is None:
        return 0
    return int(fig.stats.get("renown", 0))


def add(game, amount: int) -> int:
    """Add to the adventurer's renown; returns the new total."""
    fig = figure(game)
    total = int(fig.stats.get("renown", 0)) + max(0, amount)
    fig.stats["renown"] = total
    return total


def title(game) -> str:
    """What people would call this adventurer."""
    score = _stored(game)
    name = TITLES[0][1]
    for threshold, word in TITLES:
        if score >= threshold:
            name = word
    return name


def kind_of(victim) -> Optional[str]:
    """Which sort of famous thing this was, if it was one."""
    defn = victim.defn
    if defn.has("MEGABEAST"):
        return "megabeast"
    if defn.has("SEMIMEGABEAST"):
        return "semimegabeast"
    if defn.has("NIGHT_CREATURE") or defn.has("OPPOSED_TO_LIFE"):
        return "night"
    fig = _figure_of(victim)
    if fig is not None:
        if "bandit" in fig.flags or "necromancer" in fig.flags:
            return "bandit"
        if "leader" in fig.flags or "hero" in fig.flags:
            return "leader"
    return None


def _figure_of(victim):
    """The historical figure a creature stands for, if any."""
    return getattr(victim, "_figure", None)


def record_kill(game, victim) -> Optional[Any]:
    """Write a notable kill into the world, with the player's name on it.

    Only notable ones: a legends screen listing every rat an adventurer ever
    stepped on is a legends screen nobody reads.
    """
    world = game.world
    fig = world.figures.get(victim.hf_id) if victim.hf_id is not None else None
    victim._figure = fig
    kind = kind_of(victim)
    if kind is None:
        return None
    if not game.can_see_creature(victim):
        # Something died somewhere else. It is not your story.
        return None

    hero = figure(game)
    add(game, KILL_RENOWN.get(kind, 5))
    where = _where(game)
    if fig is not None:
        # The creature's own death handler has already dated the figure; this
        # is about whose name goes next to it.
        if fig.died is None:
            fig.died = game.time.year
        fig.death_cause = "slain by %s" % hero.name
        if fig.id not in hero.kills:
            hero.kills.append(fig.id)
        hero.flags.add("legendary")
    name = (fig.display_name if fig is not None
            else "a %s" % victim.short_name())
    return history_mod.record(
        game.world, game.time.year, "beast_slain",
        "%s slew %s %s." % (hero.name, name, where),
        [hero.id] + ([fig.id] if fig is not None else []),
        [game.local.site_id] if game.local is not None
        and game.local.site_id else [],
    )


def record_quest(game, quest) -> Optional[Any]:
    """A finished job for somebody is worth remembering too."""
    from . import standing as standing_mod

    hero = figure(game)
    add(game, QUEST_RENOWN)
    # A people find out about a finished job whether or not anybody watched
    # you do it, which is why this is credited by site rather than by witness.
    site_obj = (game.world.site(quest.site_id)
                if getattr(quest, "site_id", None) else None)
    if site_obj is not None and getattr(site_obj, "civ_id", None):
        standing_mod.did(game, "quest", civ_id=site_obj.civ_id)
    site = quest.site_name or "the wilds"
    return history_mod.record(
        game.world, game.time.year, "hero_rose",
        "%s completed a task at %s: %s." % (hero.name, site, quest.title),
        [hero.id], [quest.site_id] if quest.site_id else [],
    )


def _where(game) -> str:
    """A phrase for where something happened."""
    site = game.current_site()
    if site is not None:
        return "at %s" % site.name
    region = game.world.region_at(game.player.wx, game.player.wy)
    if region is not None:
        return "in %s" % region.full_name
    return "in the wilds"


# --------------------------------------------------------------------------- #
# Putting the adventurer down
# --------------------------------------------------------------------------- #


def retire(game) -> Any:
    """Stop playing this adventurer and leave them in the world alive.

    The opposite of dying: the figure stays living, keeps its renown, and is
    somebody the next game can hear about, meet in a tavern, or read about in
    the legends screen.
    """
    hero = figure(game)
    p = game.player
    hero.flags.add("retired")
    site = game.current_site()
    if site is not None:
        hero.site_id = site.id
    where = _where(game)
    event = history_mod.record(
        game.world, game.time.year, "hero_rose",
        "%s the %s settled %s after %d notable %s." % (
            p.name, title(game), where, len(hero.kills),
            "kill" if len(hero.kills) == 1 else "kills"),
        [hero.id], [site.id] if site is not None else [],
    )
    game.game_over = True
    game.death_message = "retired %s" % where
    return event


def summary(game) -> List[str]:
    """A few lines about the adventurer's standing, for the character sheet."""
    hero = game.world.figures.get(game.player.hf_id) \
        if game.player.hf_id is not None else None
    score = _stored(game)
    out = ["Renown: %d (%s)" % (score, title(game))]
    if hero is not None and hero.kills:
        out.append("Notable kills: %d" % len(hero.kills))
    done = [q for q in game.quests.completed if q.state == "done"]
    if done:
        out.append("Tasks completed: %d" % len(done))
    return out
