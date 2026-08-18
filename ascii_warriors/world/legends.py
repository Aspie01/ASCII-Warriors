"""The legends viewer: turning generated history into readable text."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from ..data import creatures as creature_data
from ..data import items as item_data
from ..data import materials as mat_data
from ..engine import colors
from ..engine.screen import Frag
from . import history as history_mod

_TITLE = colors.UI["title"]
_DIM = colors.UI["dim"]
_FG = colors.UI["fg"]
_ACCENT = colors.UI["accent"]


def _line(text: str, color=None) -> Frag:
    return Frag(text, color or _FG)


def figure_lines(world, hf_id: int) -> List[Frag]:
    """A biography of one historical figure."""
    fig = world.figures.get(hf_id)
    if fig is None:
        return [_line("No such figure.", _DIM)]
    race = creature_data.get(fig.creature_id or fig.race)
    out: List[Frag] = [_line(fig.display_name, _TITLE)]
    out.append(_line("%s %s%s" % (
        race.adjective, fig.profession,
        ", female" if fig.female else "",
    ), _DIM))
    if fig.died is None:
        out.append(_line("Born in the year %d. Still living." % fig.born))
    else:
        out.append(_line("Born %d, died %d%s." % (
            fig.born, fig.died,
            " (%s)" % fig.death_cause if fig.death_cause else "",
        )))
    if fig.civ_id:
        civ = world.civ(fig.civ_id)
        if civ is not None:
            out.append(_line("A member of %s." % civ.name))
    if fig.site_id:
        site = world.site(fig.site_id)
        if site is not None:
            out.append(_line("Associated with %s." % site.name))
    if fig.flags:
        out.append(_line("Noted as: %s." % ", ".join(sorted(fig.flags)), _ACCENT))
    if fig.stats:
        out.append(_line("Prowess %d, cunning %d." % (
            fig.stats.get("prowess", 0), fig.stats.get("cunning", 0)), _DIM))
    from . import religion as religion_mod

    god = religion_mod.deity_of(world, fig)
    if god is not None:
        out.append(_line("Worships %s, god of %s."
                         % (god.display_name, god.sphere_text()), _ACCENT))
    kin = history_mod.relations_of(world, fig)
    if kin:
        out.append(_line(""))
        out.append(_line("Relations:", _ACCENT))
        for kind, other in kin[:20]:
            out.append(_line("  %-12s %s%s" % (
                history_mod.RELATION_NAMES.get(kind, kind),
                other.display_name,
                "" if other.died is None else " (dead)")))
    made = [a for a in world.artifacts if a.creator_hf == hf_id]
    if made:
        out.append(_line(""))
        out.append(_line("Created:", _ACCENT))
        for a in made:
            out.append(_line("  %s (%d)" % (a.name, a.created)))
    events = history_mod.events_about(world, hf_id)
    if events:
        out.append(_line(""))
        out.append(_line("History:", _ACCENT))
        for e in events[-40:]:
            out.append(_line("  " + e.describe(world)))
    return out


def site_lines(world, site_id: int) -> List[Frag]:
    """A description of one site and everything that happened there."""
    site = world.site(site_id)
    if site is None:
        return [_line("No such site.", _DIM)]
    out: List[Frag] = [_line(site.full_name, _TITLE)]
    out.append(_line("A %s at (%d, %d)." % (site.kind_name, site.wx, site.wy), _DIM))
    civ = world.civ(site.civ_id) if site.civ_id else None
    if civ is not None:
        out.append(_line("Part of %s." % civ.name))
    out.append(_line("Founded in the year %d." % site.founded))
    if site.destroyed is not None:
        out.append(_line("Destroyed in the year %d." % site.destroyed,
                         colors.UI["danger"]))
    else:
        out.append(_line("Population: %d." % site.population))
    if site.buildings:
        out.append(_line("Notable buildings: %s." % ", ".join(site.buildings)))
    ruler = world.figures.get(site.ruler_hf) if site.ruler_hf else None
    if ruler is not None:
        out.append(_line("Ruled by %s." % ruler.display_name))
    owner = world.figures.get(site.owner_hf) if site.owner_hf else None
    if owner is not None and owner.alive(world.year):
        out.append(_line("Held by %s." % owner.display_name, colors.UI["warn"]))
    elif owner is not None:
        # Past tense, because the same screen records the death two lines
        # down. Who held a place is a historical fact and stays on the page;
        # saying "holds" about a corpse is the page contradicting itself.
        out.append(_line("Held by %s until %s." % (
            owner.display_name, owner.died), _DIM))
    arts = [a for a in world.artifacts if a.site_id == site_id]
    if arts:
        out.append(_line(""))
        out.append(_line("Artifacts held here:", _ACCENT))
        for a in arts:
            out.append(_line("  %s" % a.name))
    events = history_mod.events_at(world, site_id)
    if events:
        out.append(_line(""))
        out.append(_line("History:", _ACCENT))
        for e in events[-40:]:
            out.append(_line("  " + e.describe(world)))
    return out


def civ_lines(world, civ_id: int) -> List[Frag]:
    """A description of one civilization."""
    civ = world.civ(civ_id)
    if civ is None:
        return [_line("No such civilization.", _DIM)]
    out: List[Frag] = [_line(civ.full_name, _TITLE)]
    out.append(_line("A civilization of %s." %
                     creature_data.get(civ.race).plural, _DIM))
    out.append(_line("Founded in the year %d." % civ.year_founded))
    if civ.destroyed is not None:
        out.append(_line("Fell in the year %d." % civ.destroyed,
                         colors.UI["danger"]))
    leader = world.figures.get(civ.leader_hf) if civ.leader_hf else None
    if leader is not None:
        out.append(_line("Led by %s." % leader.display_name))
    live = [world.site(s) for s in civ.sites]
    live = [s for s in live if s is not None]
    total_pop = sum(s.population for s in live if not s.is_ruin)
    out.append(_line("%d settlements, %d souls." % (
        sum(1 for s in live if not s.is_ruin), total_pop)))
    if civ.at_war_with:
        enemies = [world.civ(c) for c in sorted(civ.at_war_with)]
        names = [e.name for e in enemies if e is not None]
        if names:
            out.append(_line("At war with %s." % ", ".join(names),
                             colors.UI["danger"]))
    if civ.ethics:
        out.append(_line(""))
        out.append(_line("Beliefs:", _ACCENT))
        for k, v in sorted(civ.ethics.items()):
            out.append(_line("  %-18s %s" % (
                k.replace("_", " "), v.replace("_", " "))))
    out.append(_line(""))
    out.append(_line("Settlements:", _ACCENT))
    for s in sorted(live, key=lambda s: -s.population):
        mark = " (in ruins)" if s.is_ruin else ""
        out.append(_line("  %-28s %-16s pop %d%s" % (
            s.name, s.kind_name, s.population, mark)))
    return out


def artifact_lines(world, art_id: int) -> List[Frag]:
    """A description of one artifact."""
    art = world.artifact(art_id)
    if art is None:
        return [_line("No such artifact.", _DIM)]
    defn = item_data.get(art.item_def)
    out: List[Frag] = [_line(art.name, colors.MAGIC)]
    if art.native_name:
        out.append(_line("Known natively as %s." % art.native_name, _DIM))
    out.append(_line("A %s %s." % (mat_data.get(art.material).adjective, defn.name)))
    out.append(_line(art.description))
    creator = world.figures.get(art.creator_hf) if art.creator_hf else None
    if creator is not None:
        out.append(_line("Created by %s in the year %d." % (
            creator.display_name, art.created)))
    holder = world.figures.get(art.holder_hf) if art.holder_hf else None
    if holder is not None and holder.alive(world.year):
        out.append(_line("Held by %s." % holder.display_name, _ACCENT))
    elif holder is not None:
        out.append(_line("Held by %s until %s." % (
            holder.display_name, holder.died), _DIM))
    site = world.site(art.site_id) if art.site_id else None
    if site is not None:
        out.append(_line("Last seen at %s." % site.name, _ACCENT))
    if art.lost:
        out.append(_line("Its whereabouts are unknown.", colors.UI["warn"]))
    return out


def deity_lines(world, deity_id: int) -> List[Frag]:
    """The page for one god: what they govern and who holds them."""
    from . import religion as religion_mod

    god = religion_mod.god(world, deity_id)
    if god is None:
        return [_line("No such god.")]
    out = [_line(god.display_name, _ACCENT)]
    if god.native_name and god.native_name.lower() != god.name.lower():
        out.append(_line("Called %s." % god.native_name, _DIM))
    out.append(_line("God of %s." % god.sphere_text()))
    peoples = [world.civ(c) for c in god.civ_ids]
    peoples = [c for c in peoples if c is not None]
    if peoples:
        out.append(_line(""))
        out.append(_line("Held by:", _ACCENT))
        for civ in peoples:
            out.append(_line("  %s" % civ.name))
    faithful = [f for f in world.figures.values()
                if religion_mod.deity_of(world, f) is god]
    if faithful:
        out.append(_line(""))
        out.append(_line("Among the faithful:", _ACCENT))
        living = [f for f in faithful if f.died is None]
        for f in (living or faithful)[:12]:
            out.append(_line("  %s" % f.summary()))
        out.append(_line("  %d in all, %d of them living."
                         % (len(faithful), len(living)), _DIM))
    return out


def event_lines(world, ev) -> List[Frag]:
    """A single event with its participants."""
    out = [_line(ev.describe(world))]
    for fid in ev.figures:
        fig = world.figures.get(fid)
        if fig is not None:
            out.append(_line("  - %s" % fig.summary(), _DIM))
    return out


def timeline(
    world,
    *,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    kinds: Optional[Sequence[str]] = None,
) -> List[Any]:
    """Filter the world's events by year range and kind."""
    out = []
    for e in world.events:
        if year_from is not None and e.year < year_from:
            continue
        if year_to is not None and e.year > year_to:
            continue
        if kinds and e.kind not in kinds:
            continue
        out.append(e)
    return out


def search(world, query: str) -> List[Tuple[str, int, str]]:
    """Find figures, sites, civilizations and artifacts by name."""
    q = query.strip().lower()
    if not q:
        return []
    out: List[Tuple[str, int, str]] = []
    for f in world.figures.values():
        if q in f.name.lower():
            out.append(("figure", f.id, f.summary()))
    for s in world.sites:
        if q in s.name.lower() or q in s.native_name.lower():
            out.append(("site", s.id, "%s, a %s" % (s.name, s.kind_name)))
    for c in world.civs:
        if q in c.name.lower() or q in c.native_name.lower():
            out.append(("civ", c.id, "%s, a %s civilization" % (c.name, c.race)))
    for a in world.artifacts:
        if q in a.name.lower():
            out.append(("artifact", a.id, "%s, an artifact" % a.name))
    return out[:200]


def world_summary(world) -> List[Frag]:
    """An overview page for the legends screen."""
    from .worldgen import summarize

    out: List[Frag] = [_line(world.name, _TITLE)]
    for ln in summarize(world)[1:]:
        out.append(_line(ln, _DIM))
    out.append(_line(""))
    out.append(_line("Civilizations", _ACCENT))
    for c in world.civs:
        leader = world.figures.get(c.leader_hf) if c.leader_hf else None
        status = "fallen" if c.destroyed is not None else "%d sites" % len([
            s for s in c.sites if world.site(s) and not world.site(s).is_ruin
        ])
        out.append(_line("  %-34s %-8s %-10s %s" % (
            c.name, c.race, status,
            leader.display_name if leader else "",
        )))
    out.append(_line(""))
    out.append(_line("Living legends", _ACCENT))
    legends = [
        f for f in history_mod.living_figures(world, flags=("legendary", "monster",
                                                            "necromancer"))
    ]
    legends.sort(key=lambda f: -f.stats.get("prowess", 0))
    for f in legends[:12]:
        out.append(_line("  %s" % f.summary()))
    if not legends:
        out.append(_line("  None remain.", _DIM))
    out.append(_line(""))
    out.append(_line("Recent events", _ACCENT))
    for e in history_mod.notable_events(world, 14):
        out.append(_line("  " + e.describe(world)))
    return out


def rumor_pool(world, n: int = 60) -> List[str]:
    """Short lines NPCs can repeat as hearsay."""
    out: List[str] = []
    for e in history_mod.notable_events(world, n):
        out.append(e.text)
    return out
