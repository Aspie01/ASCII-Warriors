"""Conversation and other in-world dialogue screens."""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..engine import colors, keys
from ..engine.screen import Frag, Screen
from ..engine.widgets import ListMenu, MenuItem, key_hint, scroll_view
from ..game import conversation
from .app import Scene


class ConversationScene(Scene):
    """Talk to somebody."""

    def __init__(self, app, other) -> None:
        super().__init__(app)
        self.other = other
        self.transcript: List[Frag] = []
        self.menu = ListMenu([], per_page=14)
        self.offset = 0

    def on_enter(self) -> None:
        game = self.game
        if game is None or self.other is None:
            self.done = True
            return
        if not self.transcript:
            self.transcript.extend(
                conversation.say(game.player, self.other, "greet", game)
            )
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the topic list."""
        game = self.game
        topics = conversation.topics_for(game.player, self.other, game)
        self.menu.set_items([MenuItem(label, topic) for topic, label in topics])

    def draw(self, scr: Screen) -> None:
        """Draw the transcript above and the topics below."""
        other = self.other
        title = other.display_name()
        if other.profession:
            title += " the %s" % other.profession
        scr.frame(0, 0, scr.width, scr.height - 1, title=title)

        topic_h = min(12, len(self.menu.items) + 1)
        transcript_h = scr.height - topic_h - 5
        visible = self.transcript[-(transcript_h * 2):]
        wrapped: List[Frag] = []
        for frag in visible:
            wrapped.append(frag)
        self.offset = max(0, len(wrapped) - transcript_h)
        row = 2
        for frag in wrapped[self.offset:]:
            if row >= 2 + transcript_h:
                break
            used = scr.wrapped(2, row, scr.width - 4, [frag])
            row += max(1, used)

        sep = 2 + transcript_h
        scr.hline(1, sep, scr.width - 2, "-", colors.UI["frame"])
        self.menu.draw(scr, 2, sep + 1, scr.width - 4, topic_h - 1,
                       show_desc=False)
        key_hint(scr, 2, scr.height - 2, [
            (keys.ENTER, "say"), (keys.ESC, "leave"),
        ])

    def handle(self, key: str) -> None:
        """Choose a topic to raise."""
        game = self.game
        result = self.menu.handle(key)
        if result == "cancel":
            self.done = True
            return
        if result != "select":
            return
        topic = self.menu.selected_value
        if topic == "farewell":
            self.transcript.extend(
                conversation.say(game.player, self.other, "farewell", game)
            )
            self.done = True
            return
        reply = conversation.say(game.player, self.other, topic, game)
        self.transcript.append(Frag(""))
        self.transcript.extend(reply)
        if self.other.id in game.player.hostile_to or \
                game.player.id in self.other.hostile_to:
            self.done = True
        self.refresh()
