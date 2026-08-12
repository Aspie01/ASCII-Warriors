"""What a fortress leaves behind.

When a fortress falls or is abandoned it does not simply stop existing. It
becomes a place: a real site on the world map, with the corridors you dug, the
workshops you raised, the goods still on the floor, and your dwarves lying
where they fell. An adventurer can walk into it afterwards and find all of it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..data import names as name_data
from ..world.civ import Site


def preserve(fort) -> Dict[str, Any]:
    """Freeze the fortress map, its contents and its dead."""
    return {
        "kind": "fortress",
        "name": fort.name,
        "founded": fort.year_founded,
        "ended": fort.time.year,
        "reason": fort.loss_reason or "abandoned",
        "map": fort.local.to_dict(),
        "creatures": [c.to_dict() for c in fort.creatures.values()],
        "items": {
            "%d,%d,%d" % cell: [i.to_dict() for i in pile]
            for cell, pile in fort.items_on_ground.items() if pile
        },
        "buildings": [b.to_dict() for b in fort.buildings if b.built],
        "artifacts": list(fort.artifacts),
        "wealth": fort.wealth,
        "dead": [c.name for c in fort.creatures.values() if c.body.dead],
    }


def make_site(fort) -> Site:
    """Put the fortress on the world map, as a place with a history."""
    world = fort.world
    existing = world.site(fort.site_id) if fort.site_id is not None else None
    if existing is not None:
        site = existing
    else:
        native = name_data.site_name(fort.rng, "dwarf", "fortress")[0]
        site = Site(world.next_id("site"), fort.name, native, "fortress",
                    fort.wx, fort.wy, "dwarf")
        world.sites.append(site)
        world.tile(fort.wx, fort.wy).site_id = site.id
        fort.site_id = site.id

    site.name = fort.name
    site.kind = "fortress"
    site.founded = fort.year_founded
    site.wealth = fort.wealth
    site.population = len(fort.dwarves())
    site.buildings = sorted({b.kind for b in fort.buildings if b.built})
    if fort.lost:
        site.destroyed = fort.time.year
        site.population = 0
    return site


def record(fort, *, abandoned: bool = False) -> Site:
    """Write the fortress into the world: a site, a map, events and artifacts.

    Called once, when the fortress ends. Afterwards the world knows about the
    place and an adventurer generated in this world can go and find it.
    """
    from ..world.history import Artifact, HistoricalEvent

    world = fort.world
    site = make_site(fort)
    world.preserve(fort.wx, fort.wy, preserve(fort))

    if abandoned:
        text = "%s was abandoned by its people." % fort.name
        kind = "site_abandoned"
    else:
        text = "The fortress of %s fell, %s." % (
            fort.name, fort.loss_reason or "for reasons unrecorded")
        kind = "site_destroyed"
    event = HistoricalEvent(world.next_id("event"), fort.time.year, kind, text)
    event.sites.append(site.id)
    world.events.append(event)

    founding = HistoricalEvent(
        world.next_id("event"), fort.year_founded, "site_founded",
        "%s was founded by seven dwarves." % fort.name)
    founding.sites.append(site.id)
    world.events.insert(0, founding)

    for art in fort.artifacts:
        _record_artifact(fort, site, art)
    return site


def _record_artifact(fort, site, art: Dict[str, Any]) -> None:
    """Add one of the fortress's artifacts to world legends."""
    from ..world.history import Artifact, HistoricalEvent

    world = fort.world
    obj = Artifact(world.next_id("artifact"), art.get("name", "?"),
                   art.get("native", ""), art.get("def_id", "gem"),
                   art.get("material", "stone"))
    obj.site_id = site.id
    obj.created = int(art.get("year", fort.time.year))
    obj.description = "Made in %s by %s." % (
        fort.name, art.get("maker", "a dwarf"))
    world.artifacts.append(obj)
    event = HistoricalEvent(
        world.next_id("event"), int(art.get("year", fort.time.year)),
        "artifact_created",
        "%s created %s, %s, in %s." % (
            art.get("maker", "A dwarf"), art.get("name", "an artifact"),
            art.get("item", "a thing"), fort.name))
    event.sites.append(site.id)
    world.events.append(event)


def describe(payload: Dict[str, Any]) -> List[str]:
    """A few lines about a preserved place, for the travel screen."""
    if not payload:
        return []
    out = ["%s, founded %d" % (payload.get("name", "?"),
                               int(payload.get("founded", 0)))]
    ended = payload.get("ended")
    if ended:
        out.append("ended %d: %s" % (int(ended), payload.get("reason", "")))
    dead = payload.get("dead") or []
    if dead:
        out.append("%d dwarves lie here" % len(dead))
    arts = payload.get("artifacts") or []
    for art in arts[:4]:
        out.append("%s, a %s" % (art.get("name", "?"), art.get("item", "?")))
    return out


def restore(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Turn a preserved payload into the shape the local-map cache wants."""
    if not payload or "map" not in payload:
        return None
    return {
        "map": payload["map"],
        "creatures": payload.get("creatures", []),
        "items": payload.get("items", {}),
    }
