"""Deterministic random number generation.

This is the **only** module in the project permitted to import :mod:`random`.
Everything else takes an :class:`RNG` instance, which keeps world generation,
history and combat perfectly reproducible from a seed.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")


def seed_from_string(s: str) -> int:
    """A stable 63-bit seed derived from a string.

    Uses BLAKE2b rather than :func:`hash` so the value is identical across runs,
    platforms and Python versions (``PYTHONHASHSEED`` does not affect it).
    """
    digest = hashlib.blake2b(str(s).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


class RNG:
    """A seeded, serialisable random source."""

    __slots__ = ("seed", "_r")

    def __init__(self, seed: "int | str") -> None:
        if isinstance(seed, str):
            self.seed = seed_from_string(seed)
        else:
            self.seed = int(seed) & ((1 << 63) - 1)
        self._r = random.Random(self.seed)

    # -- basics ------------------------------------------------------------ #

    def random(self) -> float:
        """A float in ``[0.0, 1.0)``."""
        return self._r.random()

    def randint(self, a: int, b: int) -> int:
        """An int in ``[a, b]`` (inclusive). Returns *a* if ``b < a``."""
        if b < a:
            return a
        return self._r.randint(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        """A uniformly chosen element of *seq*."""
        return self._r.choice(seq)

    def choices(
        self,
        seq: Sequence[T],
        weights: Optional[Sequence[float]] = None,
        k: int = 1,
    ) -> List[T]:
        """*k* elements chosen with replacement, optionally weighted."""
        if not seq:
            return []
        if weights is not None and sum(weights) <= 0:
            weights = None
        return self._r.choices(list(seq), weights=weights, k=k)

    def shuffle(self, seq: List[Any]) -> None:
        """Shuffle *seq* in place."""
        self._r.shuffle(seq)

    def shuffled(self, seq: Iterable[T]) -> List[T]:
        """A shuffled copy of *seq*."""
        out = list(seq)
        self._r.shuffle(out)
        return out

    def sample(self, seq: Sequence[T], k: int) -> List[T]:
        """*k* distinct elements, clamped to ``len(seq)``."""
        seq = list(seq)
        k = max(0, min(k, len(seq)))
        return self._r.sample(seq, k)

    def pick_n(self, seq: Sequence[T], n: int) -> List[T]:
        """Alias of :meth:`sample` that reads better at call sites."""
        return self.sample(seq, n)

    def gauss(self, mu: float, sigma: float) -> float:
        """A normally distributed float."""
        return self._r.gauss(mu, sigma)

    def gauss_int(self, mu: float, sigma: float, lo: int, hi: int) -> int:
        """A normally distributed int clamped to ``[lo, hi]``."""
        v = int(round(self._r.gauss(mu, sigma)))
        return max(lo, min(hi, v))

    def chance(self, p: float) -> bool:
        """True with probability *p*."""
        if p <= 0.0:
            return False
        if p >= 1.0:
            return True
        return self._r.random() < p

    def one_in(self, n: int) -> bool:
        """True with probability ``1/n``."""
        if n <= 1:
            return True
        return self._r.randrange(n) == 0

    def roll(self, n: int, sides: int) -> int:
        """Roll ``n`` dice of ``sides`` faces and sum them."""
        if n <= 0 or sides <= 0:
            return 0
        total = 0
        rr = self._r.randint
        for _ in range(n):
            total += rr(1, sides)
        return total

    def maybe(self, p: float, a: T, b: T) -> T:
        """*a* with probability *p*, otherwise *b*."""
        return a if self.chance(p) else b

    def perturb(self, value: float, pct: float) -> float:
        """Jitter *value* by up to ``+/- pct`` (a fraction, e.g. ``0.1``)."""
        return value * (1.0 + self._r.uniform(-pct, pct))

    def uniform(self, a: float, b: float) -> float:
        """A float in ``[a, b]``."""
        return self._r.uniform(a, b)

    def dir8(self) -> Tuple[int, int]:
        """A random one of the eight compass directions."""
        dirs = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
        return self._r.choice(dirs)

    # -- weighted selection ------------------------------------------------ #

    def weighted(self, table: Mapping[Any, float]) -> Any:
        """Pick a key from a ``key -> weight`` mapping. Zero weights never win."""
        keys: List[Any] = []
        weights: List[float] = []
        for k, w in table.items():
            if w > 0:
                keys.append(k)
                weights.append(float(w))
        if not keys:
            raise ValueError("weighted() needs at least one positive weight")
        return self._r.choices(keys, weights=weights, k=1)[0]

    def pick_index(self, weights: Sequence[float]) -> int:
        """Index into *weights*, chosen proportionally. ``-1`` if all are zero."""
        total = sum(w for w in weights if w > 0)
        if total <= 0:
            return -1
        target = self._r.random() * total
        acc = 0.0
        for i, w in enumerate(weights):
            if w <= 0:
                continue
            acc += w
            if target < acc:
                return i
        for i in range(len(weights) - 1, -1, -1):
            if weights[i] > 0:
                return i
        return -1

    # -- derived streams --------------------------------------------------- #

    def sub(self, name: str) -> "RNG":
        """A deterministic child stream.

        The result depends only on ``(self.seed, name)``, so the same name always
        yields the same stream no matter how much the parent has been consumed.
        """
        return RNG(seed_from_string("%d/%s" % (self.seed, name)))

    # -- serialisation ----------------------------------------------------- #

    def getstate(self) -> Any:
        """JSON-friendly internal state (lists, not tuples)."""
        version, internal, gauss_next = self._r.getstate()
        return [version, list(internal), gauss_next]

    def setstate(self, st: Any) -> None:
        """Restore state produced by :meth:`getstate`."""
        version, internal, gauss_next = st
        self._r.setstate((version, tuple(int(v) for v in internal), gauss_next))

    def to_dict(self) -> Dict[str, Any]:
        """Serialise seed and state together."""
        return {"seed": self.seed, "state": self.getstate()}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "RNG":
        """Rebuild an :class:`RNG` from :meth:`to_dict`."""
        r = cls(int(d["seed"]))
        state = d.get("state")
        if state is not None:
            r.setstate(state)
        return r

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "RNG(seed=%d)" % self.seed
