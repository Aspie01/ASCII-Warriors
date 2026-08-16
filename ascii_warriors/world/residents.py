"""The people in the legends are the people in the town.

The world generates hundreds of historical figures, gives each of them a home
site, and writes their deeds into the legends. The tavern gossips about them by
name. Then you walk into the town they live in and meet twenty strangers called
"peasant".

Measured on a small world: 364 living figures, 356 of them with a home site,
and exactly **8** ever placed on a map -- the eight a site names as its ruler or
owner, the only ones `sitegen` looked at. The other 348 were unmeetable in
principle. A city whose legends named 21 living residents put one of them in
front of the player, out of twenty-nine townsfolk. They were not nobodies
either: 58 warriors, 47 smiths, 42 hunters, 20 poets, 13 scholars and 9
necromancers who existed only as rows in a table.

The fix is to *identify* rather than to add. A town already spawns about the
right number of people; they simply had no names out of the legends. So this
module takes the population a site builder produced and hands out the identities
of the figures who live there, most notable first -- which keeps the town the
size it was and makes the README's "a real figure who may still be out there"
true. A retired adventurer is just another resident figure, so the promise in
`renown.retire`'s docstring comes true with them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: What a title, a kill and a deed are worth when deciding who gets a face
#: first. Titles are rare -- 8 of 377 residents on the measured world -- so
#: they dominate, which is the point: the player should meet the Dragonbane.
TITLE_WORTH = 6
KILL_WORTH = 3
DEED_WORTH = 1

#: An adventurer somebody retired here outranks anybody the world invented.
#: They are the one figure the player already has a reason to look for.
RETIRED_WORTH = 25

#: Events every figure has, which distinguish nobody. Every one of the 377
#: living residents had "events about them", so counting events flatly would
#: have ranked them all equal.
COMMON_DEEDS = frozenset({"birth", "death", "migration"})

#: How much notability buys a level of skill, and the ceiling. A figure with a
#: title and a few kills should be worth being careful around; nobody becomes
#: unkillable by being talked about.
LEVEL_PER = 9
MAX_LEVEL = 6


def notability(world, fig) -> int:
    """How much of a name this figure has, for who gets placed first."""
    score = TITLE_WORTH * len(fig.titles) + KILL_WORTH * len(fig.kills)
    for event in world.events:
        if fig.id in event.figures and event.kind not in COMMON_DEEDS:
            score += DEED_WORTH
    if "retired" in fig.flags or "player" in fig.flags:
        score += RETIRED_WORTH
    return score


def could_be(defn, fig, site) -> bool:
    """Whether the creature standing in a slot could be this figure.

    `defn.civ` is the discriminator and it is already in the data: a creature
    that belongs to a civilization (`human`, `goblin`, `elf`) is a race and
    needs the right one, and a creature that does not (`guard`, `merchant`,
    `hammerdwarf`) is a *job*. `CIVILIZED` is what keeps a name off a troll,
    a zombie and a forgotten beast.

    A job slot needs the site's race as well, which is not the same test.
    Some of a site's listed residents are not its people at all -- a measured
    dwarf fortress had eleven goblins on its rolls, presumably from whatever
    changed hands there -- and `hammerdwarf` and `elf_archer` carry no `civ`
    of their own, so job-slots-are-open-to-anybody put three goblins' names
    on three dwarven hammerers.
    """
    if defn.civ:
        return defn.civ == fig.race
    if not defn.has("CIVILIZED"):
        return False
    return bool(getattr(site, "race", "")) and site.race == fig.race


def residents(world, site) -> List[Any]:
    """Living figures who call this site home, most notable first."""
    if site is None:
        return []
    here = [
        f for f in world.figures.values()
        if f.site_id == site.id and f.died is None and "monster" not in f.flags
    ]
    here.sort(key=lambda f: (-notability(world, f), f.id))
    return here


def name_the_locals(world, site, pop: Sequence[Dict[str, Any]]) -> int:
    """Give a site's population the identities of the legends who live there.

    Returns how many were placed. Slots that already carry an `hf_id` -- the
    ruler, the owner -- are left alone, and a figure takes the slot whose
    profession is its own where there is one, so the town's smith is the smith
    the legends know rather than whoever was standing nearest the door.
    """
    from ..data import creatures as creature_data

    # Builders stamp the ruler's and owner's ids themselves and those slots are
    # left alone. A site's ruler is not always of the site's race -- goblin
    # camps led by humans, a human tower held by a goblin -- but measured over
    # three worlds every such case lands on a `bandit` or a `necromancer`,
    # which carry no race to contradict, so there is nothing here to correct.
    free = [spec for spec in pop if spec.get("hf_id") is None]
    if not free:
        return 0
    taken = {spec.get("hf_id") for spec in pop if spec.get("hf_id") is not None}
    placed = 0
    for fig in residents(world, site):
        if fig.id in taken:
            continue
        fit = [
            spec for spec in free
            if could_be(creature_data.get(str(spec["def_id"])), fig, site)
        ]
        if not fit:
            continue
        # Their own trade first; failing that, anywhere they fit.
        spec = next((s for s in fit if s.get("profession") == fig.profession),
                    fit[0])
        spec["hf_id"] = fig.id
        spec["name"] = fig.name
        if fig.profession:
            spec["profession"] = fig.profession
        spec["level"] = min(
            MAX_LEVEL,
            max(int(spec.get("level", 0)),
                notability(world, fig) // LEVEL_PER),
        )
        free.remove(spec)
        taken.add(fig.id)
        placed += 1
        if not free:
            break
    return placed
