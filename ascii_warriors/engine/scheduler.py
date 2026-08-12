"""Energy-based turn scheduling.

Every actor accumulates energy equal to its speed each tick and may act once it
reaches ``ACTION_COST``. A creature with speed 200 therefore acts twice as often
as one with the baseline speed of 100.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

#: Energy required to take one standard action.
ACTION_COST = 100
#: The speed of an unencumbered, unhindered creature.
BASE_SPEED = 100


class Scheduler:
    """Decides which actor acts next and how much game time has passed."""

    __slots__ = ("ticks", "_speed", "_energy", "_order", "_priority", "_seq")

    def __init__(self) -> None:
        #: Total elapsed game ticks.
        self.ticks = 0
        self._speed: Dict[int, int] = {}
        self._energy: Dict[int, float] = {}
        self._order: Dict[int, int] = {}
        self._priority: Dict[int, int] = {}
        self._seq = 0

    # -- membership -------------------------------------------------------- #

    def add(self, actor_id: int, speed: int, *, priority: int = 0) -> None:
        """Register an actor. Higher *priority* wins ties (the player uses 1)."""
        actor_id = int(actor_id)
        if actor_id in self._speed:
            self._speed[actor_id] = max(1, int(speed))
            self._priority[actor_id] = priority
            return
        self._speed[actor_id] = max(1, int(speed))
        self._energy[actor_id] = 0.0
        self._order[actor_id] = self._seq
        self._priority[actor_id] = priority
        self._seq += 1

    def remove(self, actor_id: int) -> None:
        """Deregister an actor; unknown ids are ignored."""
        actor_id = int(actor_id)
        self._speed.pop(actor_id, None)
        self._energy.pop(actor_id, None)
        self._order.pop(actor_id, None)
        self._priority.pop(actor_id, None)

    def contains(self, actor_id: int) -> bool:
        """True if the actor is scheduled."""
        return int(actor_id) in self._speed

    def actors(self) -> List[int]:
        """All scheduled actor ids, in insertion order."""
        return sorted(self._speed, key=lambda a: self._order[a])

    def set_speed(self, actor_id: int, speed: int) -> None:
        """Change an actor's speed, keeping its accumulated energy."""
        actor_id = int(actor_id)
        if actor_id in self._speed:
            self._speed[actor_id] = max(1, int(speed))

    def speed_of(self, actor_id: int) -> int:
        """An actor's current speed, or :data:`BASE_SPEED` if unknown."""
        return self._speed.get(int(actor_id), BASE_SPEED)

    def energy_of(self, actor_id: int) -> float:
        """An actor's accumulated energy."""
        return self._energy.get(int(actor_id), 0.0)

    # -- turn order -------------------------------------------------------- #

    def next_actor(self) -> Optional[int]:
        """Advance time until someone can act and return them, or ``None``."""
        if not self._speed:
            return None
        ready = self._ready()
        if not ready:
            deficit = min(
                (ACTION_COST - self._energy[a]) / self._speed[a] for a in self._speed
            )
            steps = max(1, int(deficit) + (1 if deficit % 1 else 0))
            self.advance(steps)
            ready = self._ready()
            if not ready:  # pragma: no cover - defensive
                self.advance(1)
                ready = self._ready()
                if not ready:
                    return None
        return max(
            ready,
            key=lambda a: (self._energy[a], self._priority[a], -self._order[a]),
        )

    def _ready(self) -> List[int]:
        return [a for a, e in self._energy.items() if e >= ACTION_COST]

    def advance(self, ticks: int) -> None:
        """Give every actor ``speed * ticks`` energy and move the clock forward."""
        if ticks <= 0:
            return
        self.ticks += ticks
        for a, sp in self._speed.items():
            self._energy[a] += sp * ticks

    def spend(self, actor_id: int, cost: int) -> None:
        """Deduct the energy cost of an action."""
        actor_id = int(actor_id)
        if actor_id in self._energy:
            self._energy[actor_id] -= max(0, cost)

    def peek_order(self, n: int = 8) -> List[int]:
        """Predict the next *n* actors without mutating the schedule."""
        energy = dict(self._energy)
        out: List[int] = []
        for _ in range(max(0, n)):
            ready = [a for a, e in energy.items() if e >= ACTION_COST]
            if not ready:
                if not self._speed:
                    break
                deficit = min(
                    (ACTION_COST - energy[a]) / self._speed[a] for a in self._speed
                )
                steps = max(1, int(deficit) + (1 if deficit % 1 else 0))
                for a, sp in self._speed.items():
                    energy[a] += sp * steps
                ready = [a for a, e in energy.items() if e >= ACTION_COST]
                if not ready:
                    break
            nxt = max(
                ready,
                key=lambda a: (energy[a], self._priority[a], -self._order[a]),
            )
            out.append(nxt)
            energy[nxt] -= ACTION_COST
        return out

    def clear(self) -> None:
        """Remove every actor, keeping the clock."""
        self._speed.clear()
        self._energy.clear()
        self._order.clear()
        self._priority.clear()

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the whole schedule."""
        return {
            "ticks": self.ticks,
            "speed": {str(k): v for k, v in self._speed.items()},
            "energy": {str(k): v for k, v in self._energy.items()},
            "order": {str(k): v for k, v in self._order.items()},
            "priority": {str(k): v for k, v in self._priority.items()},
            "seq": self._seq,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Scheduler":
        """Rebuild a scheduler from :meth:`to_dict`."""
        s = cls()
        s.ticks = int(d.get("ticks", 0))
        s._speed = {int(k): int(v) for k, v in d.get("speed", {}).items()}
        s._energy = {int(k): float(v) for k, v in d.get("energy", {}).items()}
        s._order = {int(k): int(v) for k, v in d.get("order", {}).items()}
        s._priority = {int(k): int(v) for k, v in d.get("priority", {}).items()}
        s._seq = int(d.get("seq", len(s._speed)))
        for a in s._speed:
            s._energy.setdefault(a, 0.0)
            s._order.setdefault(a, 0)
            s._priority.setdefault(a, 0)
        return s

    def __len__(self) -> int:
        return len(self._speed)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Scheduler(ticks=%d, actors=%d)" % (self.ticks, len(self._speed))
