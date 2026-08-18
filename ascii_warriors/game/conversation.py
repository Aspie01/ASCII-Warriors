"""Talking to people.

Everything an NPC says is grounded in the generated world: they name real
sites, real rulers and real events from :mod:`ascii_warriors.world.history`.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ..data.descriptors import list_join
from ..engine import colors, geometry
from ..engine.screen import Frag
from . import companions as companion_mod
from . import quests as quest_mod
from . import trade as trade_mod
from . import skills as skills_mod

#: Every topic `say` answers. "ask_family" used to be listed and was neither
#: offered by `topics_for` nor handled below -- the string appeared once, here.
TOPICS: Tuple[str, ...] = (
    "greet", "ask_directions", "ask_rumors", "ask_troubles", "ask_self",
    "request_quest", "report_quest", "trade", "ask_beast",
    "ask_site", "brag", "insult", "threaten", "farewell", "recruit",
    "dismiss", "rent_room", "ask_perform",
)

_SAY = colors.UI["accent2"]
_INFO = colors.UI["fg"]
_WARN = colors.UI["warn"]


def _quote(speaker, text: str) -> List[Frag]:
    """Render a line of dialogue."""
    return [
        Frag("%s says: " % speaker.display_name(), colors.UI["dim"]),
        Frag('"%s"' % text, _SAY),
    ]


def topics_for(speaker, listener, game) -> List[Tuple[str, str]]:
    """The conversation options available with this NPC."""
    out: List[Tuple[str, str]] = [
        ("greet", "Greet them"),
        ("ask_rumors", "Ask for news and rumours"),
        ("ask_troubles", "Ask what troubles this place"),
        ("ask_directions", "Ask for directions"),
        ("ask_self", "Ask about themselves"),
        ("ask_beast", "Ask about beasts and monsters"),
        ("ask_site", "Ask about this place"),
    ]
    role = listener.ai.role if listener.ai else ""
    if role in ("lord", "tavern_keeper", "guard", "priest", "merchant"):
        finished = [
            q for q in game.quests.active
            if q.giver_hf == listener.hf_id and q.progress >= q.goal
        ]
        if finished:
            out.append(("report_quest", "Report on your task"))
        out.append(("request_quest", "Ask for work"))
    if trade_mod.is_trader(listener):
        out.append(("trade", "Trade"))
    if role == "tavern_keeper":
        out.append(("rent_room", "Rent a room for the night (%d coins)"
                    % max(4, int(trade_mod.ROOM_PRICE
                                 * listener.personality.greed_factor()))))
    if listener.speech.get("companion"):
        out.append(("dismiss", "Part ways"))
    elif companion_mod.can_recruit(listener):
        out.append(("recruit", "Ask them to travel with you (%d coins)"
                    % companion_mod.hire_price(listener, speaker)))
    if _has_forms(listener, game):
        out.append(("ask_perform", "Ask them to perform"))
    out.append(("brag", "Boast of your deeds"))
    out.append(("insult", "Insult them"))
    out.append(("threaten", "Threaten them"))
    out.append(("farewell", "Take your leave"))
    return out


def greeting(npc, game) -> str:
    """A context-appropriate opening line."""
    from . import standing as standing_mod

    tone = standing_mod.greeting_tone(game, npc)
    if tone in _COLD_WELCOME:
        return _COLD_WELCOME[tone]
    if tone in _WARM_WELCOME:
        return _WARM_WELCOME[tone]
    hour = game.time.hour
    part = ("morning" if hour < 12 else
            "afternoon" if hour < 18 else "evening")
    from . import renown as renown_mod

    role = npc.ai.role if npc.ai else ""
    site = game.current_site()
    standing = renown_mod.renown(game)
    if npc.faction == "hostile":
        return "Get away from me."
    if standing >= 90:
        # People know the name before they know the face.
        return "%s! %s, here, in %s." % (
            game.player.name,
            "The %s themself" % renown_mod.title(game),
            site.name if site else "this place")
    if role == "tavern_keeper":
        return "Good %s. Ale? A bed? Or just the news?" % part
    if role == "guard":
        return "Move along, %s. Keep the peace and we'll have no trouble." % (
            "traveller" if standing < 25 else renown_mod.title(game)
        )
    if role == "lord":
        if standing >= 50:
            return "The %s of some renown. Speak, then." % renown_mod.title(game)
        return "You stand in %s. State your business." % (
            site.name if site else "my hall"
        )
    if role == "merchant":
        return "Good %s! You have the look of someone who needs supplies." % part
    if role == "priest":
        from ..world import religion as religion_mod

        god = religion_mod.deity_of(game.world, npc)
        if god is not None:
            return "%s keep you, traveller." % god.display_name
        return "Peace be on you, traveller."
    return "Good %s to you." % part


def _in_first_person(line: str) -> str:
    """One of `Personality.describe`'s sentences, as the person would say it.

    They and I share every verb form except the copula, so this is "am" for
    "are" and the two pronouns, and nothing else. It used to be a bare
    ``"They " -> "I "`` on phrases conjugated for a singular subject, which is
    where "I has a vivid imagination" came from.
    """
    text = line[5:] if line.startswith("They ") else line
    if text.startswith("are "):
        text = "am " + text[4:]
    return "I " + text.replace("themselves", "myself").replace("their ", "my ")


def rumor_lines(game, hf_id: Optional[int] = None, n: int = 3) -> List[str]:
    """A handful of real historical events, phrased as hearsay.

    With an *hf_id*, what is said about that one figure. The parameter had
    been accepted and ignored since the function was written, so there was no
    way to ask about a particular person even once there was a particular
    person standing in front of you. Their own history is filtered less
    strictly than the tavern's: `notable_events` keeps wars and beasts, and a
    marriage is not notable to a stranger but is the whole of what many people
    have to tell you about themselves.
    """
    from ..world import history as history_mod

    world = game.world
    if hf_id is not None:
        events = [e for e in history_mod.events_about(world, hf_id)
                  if e.kind != "birth"]
        if not events:
            return []
    else:
        events = history_mod.notable_events(world, 40)
    if not events:
        return ["Nothing ever happens here."]
    # People talk about what just happened first. The world keeps moving while
    # you play, and a tavern that only knows ancient history is a dead world.
    fresh = [e for e in events if e.year >= world.year - 2]
    picks = []
    if fresh:
        picks.append(game.rng.choice(fresh))
    rest = [e for e in events if e not in picks]
    picks.extend(game.rng.sample(rest, min(max(0, n - len(picks)), len(rest))))
    prefixes = [
        "They say ", "Word is ", "I heard tell that ", "Folk are saying ",
        "There's talk that ",
    ]
    out = []
    for e in picks:
        text = e.text
        # Only lower-case a leading article; proper names keep their capital.
        first = text.split(" ", 1)[0] if text else ""
        if first in ("The", "A", "An"):
            text = text[0].lower() + text[1:]
        out.append(game.rng.choice(prefixes) + text)
    return out


def _nearest_sites(game, n: int = 4) -> List[Any]:
    """The closest settlements to the player, nearest first."""
    world = game.world
    px, py = game.player.wx, game.player.wy
    sites = [s for s in world.sites if s.is_settlement or s.kind == "lair"]
    sites.sort(key=lambda s: max(abs(s.wx - px), abs(s.wy - py)))
    return sites[:n]


def say(speaker, listener, topic: str, game) -> List[Frag]:
    """Produce the NPC's reply to one conversation topic."""
    world = game.world
    rng = game.rng
    out: List[Frag] = []

    if topic == "greet":
        return _quote(listener, greeting(listener, game))

    if topic == "farewell":
        return _quote(listener, rng.choice([
            "Walk safely.", "May your beard grow long.", "Go on, then.",
            "Mind the roads after dark.", "Farewell.",
        ]))

    if topic == "ask_rumors":
        lines = rumor_lines(game, n=rng.randint(2, 3))
        for ln in lines:
            out.extend(_quote(listener, ln))
            out.append(Frag("", _INFO))
        speaker.add_exp("conversation", 12)
        return out

    if topic == "ask_troubles":
        site = game.current_site()
        troubles: List[str] = []
        if site is not None:
            from ..world import history as history_mod

            for e in history_mod.events_at(world, site.id)[-6:]:
                if e.kind in ("beast_attack", "site_destroyed", "plague",
                              "battle", "banditry"):
                    troubles.append(e.text)
        monsters = [
            f for f in world.figures.values()
            if "monster" in f.flags and f.alive(world.year)
        ]
        if monsters:
            m = rng.choice(monsters)
            from ..data import creatures as creature_data

            troubles.append(
                "The %s %s still lives, and no one has been able to kill it."
                % (creature_data.get(m.creature_id).name, m.display_name)
            )
        if not troubles:
            troubles = ["Quiet enough, these days. Long may it last."]
        for t in rng.sample(troubles, min(2, len(troubles))):
            out.extend(_quote(listener, t))
            out.append(Frag("", _INFO))
        return out

    if topic == "ask_directions":
        sites = _nearest_sites(game, 4)
        px, py = game.player.wx, game.player.wy
        if not sites:
            return _quote(listener, "There's nothing out there but wilderness.")
        for s in sites:
            dist = max(abs(s.wx - px), abs(s.wy - py))
            if dist == 0:
                continue
            bearing = geometry.direction_name(s.wx - px, s.wy - py)
            out.extend(_quote(
                listener,
                "%s, a %s, lies %s of here, %s."
                % (s.name, s.kind_name, bearing,
                   "not far" if dist <= 2 else
                   "a few days' walk" if dist <= 6 else "a long journey"),
            ))
            out.append(Frag("", _INFO))
        speaker.add_exp("conversation", 10)
        return out

    if topic == "ask_site":
        site = game.current_site()
        if site is None:
            return _quote(listener, "This is no place at all. Just open country.")
        civ = world.civ(site.civ_id) if site.civ_id else None
        ruler = world.figures.get(site.ruler_hf) if site.ruler_hf else None
        # Not one you killed on the way in. The seat is filled again within
        # the season by `livingworld._leaders`, and until then the honest
        # answer is that nobody rules here.
        if ruler is not None and not ruler.alive(world.year):
            ruler = None
        lines = ["This is %s, a %s." % (site.name, site.kind_name)]
        if site.native_name and site.native_name != site.name:
            lines.append("In the old tongue it is called %s." % site.native_name)
        if civ is not None:
            lines.append("We belong to %s." % civ.name)
        if ruler is not None:
            lines.append("%s rules here." % ruler.display_name)
        lines.append("It was founded in the year %d." % site.founded)
        if site.buildings:
            lines.append("You'll find %s here." % list_join(site.buildings))
        for ln in lines:
            out.extend(_quote(listener, ln))
            out.append(Frag("", _INFO))
        return out

    if topic == "ask_self":
        civ = world.civ(listener.civ_id) if listener.civ_id else None
        lines = ["I am %s." % listener.display_name()]
        if listener.profession:
            lines.append("I am a %s by trade." % listener.profession)
        if civ is not None:
            lines.append("I am of %s." % civ.name)
        lines.extend(_in_first_person(t)
                     for t in listener.personality.describe()[:2])
        # What the world remembers of them, if it remembers anything. Left in
        # the third person on purpose: the events read "X and Y were married",
        # and the hearsay framing is both what somebody actually says about
        # their own reputation and the only phrasing that cannot come out
        # ungrammatical.
        from ..world import religion as religion_mod

        god = religion_mod.deity_of(world, listener)
        if god is not None:
            lines.append("I hold to %s, god of %s."
                         % (god.display_name, god.sphere_text()))
        if listener.hf_id is not None:
            lines.extend(rumor_lines(game, hf_id=listener.hf_id, n=2))
        for ln in lines:
            out.extend(_quote(listener, ln))
            out.append(Frag("", _INFO))
        return out

    if topic == "ask_beast":
        from ..data import creatures as creature_data
        from ..world import history as history_mod

        monsters = [
            f for f in world.figures.values() if "monster" in f.flags
        ]
        if not monsters:
            return _quote(listener, "No beasts here worth the name.")
        m = rng.choice(monsters)
        defn = creature_data.get(m.creature_id)
        lines = ["The %s %s." % (defn.name, m.display_name)]
        if m.died is not None:
            lines.append("Dead these %d years, thank the gods."
                         % max(1, world.year - m.died))
        else:
            lines.append("Still out there. Still hungry.")
        for e in history_mod.events_about(world, m.id)[-3:]:
            lines.append(e.text)
        for ln in lines:
            out.extend(_quote(listener, ln))
            out.append(Frag("", _INFO))
        return out

    if topic == "request_quest":
        existing = [q for q in game.quests.active if q.giver_hf == listener.hf_id]
        if existing:
            return _quote(
                listener,
                "You already have work from me: %s." % existing[0].title,
            )
        q = quest_mod.generate_quest(rng, game, listener)
        if q is None:
            return _quote(listener, "Nothing needs doing that you could help with.")
        game.quests.accept(q)
        out.extend(_quote(listener, q.description))
        out.append(Frag("", _INFO))
        out.append(Frag("New task: %s" % q.title, colors.UI["good"]))
        if q.reward:
            out.append(Frag("Reward: %d coins." % q.reward, colors.UI["dim"]))
        speaker.add_exp("negotiation", 20)
        return out

    if topic == "report_quest":
        done = game.quests.turn_in(game, listener.hf_id)
        if not done:
            return _quote(listener, "Come back when the work is finished.")
        for q in done:
            out.extend(_quote(listener, "It is done, then. You have my thanks."))
            out.append(Frag("Completed: %s" % q.title, colors.UI["good"]))
        return out

    if topic == "trade":
        if not trade_mod.is_trader(listener):
            return _quote(listener, "I have nothing to sell you.")
        trade_mod.stock_merchant(listener, rng)
        speaker.add_exp("negotiation", 8)
        return _quote(listener, rng.choice([
            "Let us see what you have.",
            "Coin first, then we talk.",
            "Everything here is fairly priced. Mostly.",
        ]))

    if topic == "rent_room":
        ok, message = trade_mod.rent_room(game, listener)
        out.extend(_quote(listener, "Up the stairs. Mind the third step."
                          if ok else "No coin, no bed."))
        out.append(Frag(message, colors.UI["good"] if ok else colors.UI["warn"]))
        return out

    if topic == "recruit":
        ok, message = companion_mod.recruit(game, listener)
        if ok:
            out.extend(_quote(listener, rng.choice([
                "Aye. I have nothing better to do.",
                "Lead on, then.",
                "My blade is yours, while the coin lasts.",
            ])))
            out.append(Frag(message, colors.UI["good"]))
        else:
            out.append(Frag(message, colors.UI["warn"]))
        return out

    if topic == "dismiss":
        ok, message = companion_mod.dismiss(game, listener)
        out.extend(_quote(listener, "Then this is where we part."))
        out.append(Frag(message, colors.UI["dim"] if ok else colors.UI["warn"]))
        return out

    if topic == "ask_perform":
        from . import performance

        mine = performance.repertoire(game.world, listener)
        if not mine:
            return _quote(listener, "I have no song in me, traveller.")
        form = rng.choice(mine)
        audience = [c for c in game.visible_creatures()
                    if c is not listener and not c.is_hostile_to(speaker)]
        result = performance.perform(game, rng, listener, form,
                                     audience + [speaker])
        speaker.add_exp("conversation", 10)
        out.extend(_quote(listener, "As you like. This one is called %s."
                          % form.name))
        for line in performance.describe(result):
            out.append(Frag(line, _INFO if not result.good else _SAY))
        return out

    if topic == "brag":
        kills = len(speaker.kills)
        best = [s for s, lv in speaker.skills.known() if lv >= NOTABLE_SKILL]
        if kills == 0 and not best:
            # Having nothing to boast of used to say "you speak of your 0
            # notable kills" and take the same reaction as a hero. It is the
            # one place a liar has something to offer, and `lying` -- which
            # the thief starts with 3 of and the bard 2, and which nothing had
            # ever read -- is what decides whether it lands. The old test was
            # `not skills.known()`, which is only true of somebody who has
            # never learned anything at all: the branch could not be reached.
            return _brag_falsely(speaker, listener, game, rng, out)
        speaker.add_exp("persuasion", 15)
        reaction = rng.choice([
            "Is that so.", "Hah! A likely tale.", "You have the look of it, I'll say that.",
            "Then you are welcome here.", "Words are cheap, traveller.",
        ])
        if kills:
            out.append(Frag("You speak of your %d notable kills." % kills, _INFO))
        else:
            from .skills import SKILLS

            title = getattr(SKILLS.get(best[0]), "name", best[0])
            out.append(Frag("You speak of your reputation as %s."
                            % _a_an(title.lower()), _INFO))
        return out + _quote(listener, reaction)

    if topic == "insult":
        speaker.add_exp("intimidation", 8)
        listener.needs.add_thought("was insulted", 8)
        if rng.chance(0.25) or listener.personality.facet("anger") > 75:
            listener.hostile_to.add(speaker.id)
            out.extend(_quote(listener, rng.choice([
                "That is the last thing you will ever say.",
                "You will regret that.",
                "Draw your weapon, then.",
            ])))
            out.append(Frag("%s attacks!" % listener.display_name(),
                            colors.UI["danger"]))
        else:
            out.extend(_quote(listener, rng.choice([
                "Charming.", "Go bother someone else.",
                "I've been called worse by better.",
            ])))
        return out

    if topic == "threaten":
        speaker.add_exp("intimidation", 20)
        power = (skills_mod.ability(speaker, "intimidation")
                 + skills_mod.ability(speaker, "fighter"))
        will = listener.personality.facet("bravery") // 10
        if power > will + rng.randint(0, 6):
            out.extend(_quote(listener, rng.choice([
                "Alright! Alright. What do you want to know?",
                "Please. I have a family.",
                "Don't hurt me. I'll tell you anything.",
            ])))
            for ln in rumor_lines(game, n=2):
                out.append(Frag("", _INFO))
                out.extend(_quote(listener, ln))
        else:
            listener.hostile_to.add(speaker.id)
            out.extend(_quote(listener, "You picked the wrong person, stranger."))
            out.append(Frag("%s attacks!" % listener.display_name(),
                            colors.UI["danger"]))
        return out

    return _quote(listener, "I have nothing to say about that.")


#: The level at which a skill is worth boasting about -- "Talented" in the
#: descriptor table. Below it you are bragging about being competent.
NOTABLE_SKILL = 6


def _a_an(word: str) -> str:
    """"a swordsman" / "an axeman", for the one place that needs it."""
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


#: What a lie is worth against a listener who is paying attention. A liar
#: is believed roughly as often as a fighter lands a blow, which is to say
#: often enough to try and not often enough to rely on.
LIE_BASE = 0.30
LIE_PER_LEVEL = 0.055


def lie_chance(speaker, listener) -> float:
    """Whether a story about nothing gets believed."""
    skill = skills_mod.ability(speaker, "lying")
    doubt = skills_mod.ability(listener, "observer")
    odds = LIE_BASE + LIE_PER_LEVEL * skill - 0.055 * doubt
    # A trusting listener is easier. v3.15 rolled thirty facets per creature
    # and this is another of them finally being asked.
    odds += (listener.personality.facet("trust") - 50) / 400.0
    return max(0.02, min(0.92, odds))


def _brag_falsely(speaker, listener, game, rng, out) -> List[Frag]:
    """Boast of things you have not done."""
    from . import standing as standing_mod

    if speaker.skills.level("lying") <= 0:
        out.append(Frag("You have done nothing worth the telling.",
                        colors.UI["dim"]))
        return out
    speaker.add_exp("lying", 18)
    out.append(Frag("You tell them a story about yourself.", _INFO))
    if rng.chance(lie_chance(speaker, listener)):
        listener.speech["impressed"] = True
        return out + _quote(listener, rng.choice([
            "You have led quite a life.",
            "Well! We do not get many like you through here.",
            "Then you are welcome at my table.",
        ]))
    listener.needs.add_thought("was lied to", 5)
    standing_mod.did(game, "insult", seen_by=[listener])
    return out + _quote(listener, rng.choice([
        "That is not how I heard it.",
        "You have never done any such thing.",
        "Save it for somebody who was not there.",
    ]))


def _has_forms(listener, game) -> bool:
    """Whether this person has anything to perform, teaching them if they might.

    Everybody grew up somewhere. Rather than seed every generated townsperson
    with a repertoire they will probably never be asked for, they learn one
    the first time somebody looks at them and wonders.
    """
    from . import performance

    if getattr(listener, "forms", None):
        return True
    if not listener.defn.intelligent or listener.is_hostile_to(game.player):
        return False
    performance.teach_civ(game.world, game.rng, listener, None, n=2)
    return bool(getattr(listener, "forms", None))


#: What somebody says when their people have made up their mind about you.
#: Ahead of the ordinary greeting, because how a stranger's town treats you is
#: the first thing you should learn on walking into it.
_COLD_WELCOME = {
    "hated": "Get out. You know what you did.",
    "disliked": "We know your face here. Keep walking.",
    "distrusted": "...you. What do you want?",
}
_WARM_WELCOME = {
    "welcome": "You are welcome here, traveller.",
    "honoured": "It is good to see you again. Sit, if you like.",
    "revered": "They still tell the story. You honour us.",
}
