"""What a fortress leaves behind.

When a fortress falls or is abandoned it does not simply stop existing. It
becomes a place: a real site on the world map, with the corridors you dug, the
workshops you raised, the goods still on the floor, and your dwarves lying
where they fell. An adventurer can walk into it afterwards and find all of it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..data import names as name_data
from ..world.civ import Site


def walked_out(c) -> bool:
    """A dwarf of the fortress who is still alive when it ends.

    A fortress is only *lost* once nobody is left standing, so anybody alive
    at this point is alive because the place was abandoned -- and abandoning
    it means they packed the wagon and went home. Freezing them left them
    standing on the map with no job board to answer to and no AI to give them
    one: an adventurer walking into an abandoned fortress found five dwarves
    who had not moved a tile in years, and a reclaim expedition found them
    still there, still not moving, slowly dying on their feet.
    """
    return getattr(c, "fort", None) is not None and not c.body.dead


def preserve(fort) -> Dict[str, Any]:
    """Freeze the fortress map, its contents and its dead.

    The rule for what goes in is *what is physically there*. The water in the
    cisterns, the magma under the floor, the caverns, the wet rock and what
    the engravers carved on the walls are all part of the place and stay.
    Designations, jobs, stockpile rectangles and the militia roster are
    instructions given to dwarves who are dead or gone, and they do not.
    """
    left = [c for c in fort.creatures.values() if not walked_out(c)]
    return {
        "kind": "fortress",
        "name": fort.name,
        "founded": fort.year_founded,
        "ended": fort.time.year,
        "reason": fort.loss_reason or "abandoned",
        "map": fort.local.to_dict(),
        "creatures": [c.to_dict() for c in left],
        "items": {
            "%d,%d,%d" % cell: [i.to_dict() for i in pile]
            for cell, pile in fort.items_on_ground.items() if pile
        },
        "buildings": [b.to_dict() for b in fort.buildings if b.built],
        "artifacts": list(fort.artifacts),
        "wealth": fort.wealth,
        "dead": [c.name for c in left if c.body.dead],
        # The place itself, under and around the map. Without these a reclaim
        # gets a fortress whose magma sea, caverns and aquifer have quietly
        # ceased to exist.
        "water": fort.water.to_dict(),
        "magma": fort.magma.to_dict(),
        "magma_floor": fort.magma_floor,
        "hollow": ["%d,%d,%d" % c for c in fort.hollow],
        "aquifer": ["%d,%d,%d" % c for c in fort.aquifer],
        "engravings": {"%d,%d,%d" % c: a.to_dict()
                       for c, a in fort.engravings.items()},
        "civ": fort.civ_id,
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
    else:
        # A site somebody has gone back to is not a ruin any more. Without
        # this an abandoned-then-reclaimed fortress keeps the destroyed year
        # from the first time it fell and reads as rubble in the legends
        # while eighty dwarves live in it.
        site.destroyed = None
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

    # Once only. A place can fall more than once now, and every fall used to
    # write another founding, so a fortress reclaimed twice read as having
    # been founded three times in the same year.
    if not any(e.kind == "site_founded" and site.id in e.sites
               for e in world.events):
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


def can_reclaim(world, wx: int, wy: int) -> bool:
    """Whether there is a dead fortress here to go back to."""
    payload = world.preserved_map(wx, wy)
    if not payload or "map" not in payload:
        return False
    if str(payload.get("kind", "")) != "fortress":
        return False
    site = world.site_at(wx, wy)
    # Somebody living there has first claim on it, and a fortress that is
    # still being played is not preserved yet in any case.
    return site is None or site.is_ruin


def reclaim(world, wx: int, wy: int, rng, *,
            professions: Sequence[str] = ()) -> Optional[Any]:
    """Send seven more dwarves back into a fortress that already fell.

    Everything physical stays: the corridors, the workshops, the goods on the
    floor and the bodies of whoever was there last. What does not is the
    dwarves themselves. Anybody who walked out of an abandoned fortress
    walked out of it for good, and the job board, the militia and the mayor's
    demands all belonged to a fortress that no longer exists.

    The site keeps its founding year. This is the same place going again, not
    a new one on top of it, and the legends should read that way.
    """
    from ..data import names as name_data
    from . import animals as animal_mod
    from . import dwarf as dwarf_mod
    from . import perform as perform_mod
    from .fortress import Fortress
    from .labors import STARTING_SEVEN

    payload = world.preserved_map(wx, wy)
    if not can_reclaim(world, wx, wy):
        return None

    fort = Fortress.restore(world, {
        "local": payload["map"],
        "rng": rng.to_dict(),
        "name": str(payload.get("name") or "") or name_data.site_name(
            rng, "dwarf", "fortress")[1],
        "wx": wx, "wy": wy,
        "creatures": payload.get("creatures", []),
        "items": payload.get("items", {}),
        "buildings": payload.get("buildings", []),
        "water": payload.get("water") or {},
        "magma": payload.get("magma") or {},
        "magma_floor": payload.get("magma_floor", 0),
        "hollow": payload.get("hollow", []),
        "aquifer": payload.get("aquifer", []),
        "engravings": payload.get("engravings") or {},
        "artifacts": payload.get("artifacts", []),
        "wealth": payload.get("wealth", 0),
        "year_founded": payload.get("founded", world.year),
        "civ_id": payload.get("civ"),
    })
    # The clock and the sky are the world's now, not the dead fortress's.
    from ..game.weather import starting_weather

    tile = world.tile(wx, wy)
    fort.weather = starting_weather(rng, tile.biome, tile.temperature,
                                    fort.time.season)

    # `preserve` has already left the survivors out -- they went home with the
    # wagon. Anything alive on this map is a squatter: whatever emptied the
    # place, or whatever wandered in afterwards, and none of it takes orders.
    for c in list(fort.creatures.values()):
        if walked_out(c):
            fort.remove_creature(c)

    site = world.site_at(wx, wy)
    fort.site_id = site.id if site is not None else None
    fort.lost = False
    fort.loss_reason = ""
    fort.recorded = False
    if site is not None:
        from ..world.history import HistoricalEvent

        event = HistoricalEvent(
            world.next_id("event"), fort.time.year, "site_reclaimed",
            "Seven dwarves reclaimed %s." % fort.name)
        event.sites.append(site.id)
        world.events.append(event)

    wagon = fort._wagon_site()
    fort.z = wagon[2]
    for i, profession in enumerate(professions or STARTING_SEVEN):
        d = dwarf_mod.make_dwarf(rng, profession)
        spot = fort._free_spot(wagon, i)
        d.x, d.y, d.z = spot
        d.wx, d.wy = wx, wy
        fort.add_creature(d)
    fort._unload_wagon(wagon)
    fort._unload_animals(wagon, rng)
    animal_mod.spawn_wildlife(fort, rng)
    perform_mod.teach_embark(fort)

    dead = sum(1 for c in fort.creatures.values() if c.body.dead)
    fort.log.good("%s has been reclaimed." % fort.name)
    ended = payload.get("ended")
    reason = str(payload.get("reason") or "")
    if ended and reason:
        fort.log.info("It was lost in %d, %s." % (int(ended), reason))
    if dead:
        fort.log.warn("%d bodies lie unburied." % dead)
    fort.log.info("Whatever emptied it may not have left.")
    return fort


def restore(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Turn a preserved payload into the shape the local-map cache wants."""
    if not payload or "map" not in payload:
        return None
    return {
        "map": payload["map"],
        "creatures": payload.get("creatures", []),
        "items": payload.get("items", {}),
        # `preserve` has frozen these since it was written and `restore` threw
        # them away, so an adventurer walking into their own fortress found
        # the corridors, the goods and the dead, and bare floor where every
        # workshop had stood. The README has promised otherwise all along.
        "buildings": payload.get("buildings", []),
    }
