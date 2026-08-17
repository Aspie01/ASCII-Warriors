"""Graph search over arbitrary hashable nodes.

Nothing here assumes a node shape, so the same routines serve the 2D world map,
the 3D local map (``(x, y, z)`` tuples) and abstract site graphs.
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import (
    Any, Callable, Dict, Hashable, Iterable, List, Optional, Set, Tuple,
)

Node = Hashable
Neighbors = Callable[[Any], Iterable[Tuple[Any, float]]]
Heuristic = Callable[[Any, Any], float]


def astar(
    start: Node,
    goal: Node,
    neighbors: Neighbors,
    heuristic: Heuristic,
    max_nodes: int = 20000,
) -> Optional[List[Any]]:
    """A* search. Returns the path including *start* and *goal*, or ``None``."""
    if start == goal:
        return [start]
    counter = 0
    open_heap: List[Tuple[float, int, Any]] = [(0.0, 0, start)]
    came: Dict[Any, Any] = {}
    g_score: Dict[Any, float] = {start: 0.0}
    closed: Set[Any] = set()
    expanded = 0

    while open_heap:
        _f, _c, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            path = [current]
            while current in came:
                current = came[current]
                path.append(current)
            path.reverse()
            return path
        closed.add(current)
        expanded += 1
        if expanded > max_nodes:
            return None
        base = g_score.get(current, 0.0)
        for nxt, cost in neighbors(current):
            if nxt in closed or cost < 0:
                continue
            tentative = base + cost
            if tentative < g_score.get(nxt, float("inf")):
                g_score[nxt] = tentative
                came[nxt] = current
                counter += 1
                heapq.heappush(
                    open_heap, (tentative + heuristic(nxt, goal), counter, nxt)
                )
    return None


def dijkstra(
    sources: Iterable[Node],
    neighbors: Neighbors,
    max_cost: float = 1e18,
    max_nodes: int = 50000,
) -> Dict[Any, float]:
    """Cost from the nearest source to every reachable node."""
    counter = 0
    heap: List[Tuple[float, int, Any]] = []
    dist: Dict[Any, float] = {}
    for s in sources:
        dist[s] = 0.0
        heap.append((0.0, counter, s))
        counter += 1
    heapq.heapify(heap)
    settled: Set[Any] = set()

    while heap and len(settled) < max_nodes:
        d, _c, node = heapq.heappop(heap)
        if node in settled:
            continue
        settled.add(node)
        if d > max_cost:
            continue
        for nxt, cost in neighbors(node):
            if cost < 0 or nxt in settled:
                continue
            nd = d + cost
            if nd <= max_cost and nd < dist.get(nxt, float("inf")):
                dist[nxt] = nd
                counter += 1
                heapq.heappush(heap, (nd, counter, nxt))
    return dist


class DijkstraMap:
    """A scalar field over nodes that actors descend (or ascend, to flee)."""

    __slots__ = ("values",)

    def __init__(self, values: Dict[Any, float]) -> None:
        self.values = values

    @classmethod
    def build(
        cls,
        sources: Iterable[Node],
        neighbors: Neighbors,
        max_cost: float = 1e18,
        max_nodes: int = 50000,
    ) -> "DijkstraMap":
        """Build a map by running :func:`dijkstra` from *sources*."""
        return cls(dijkstra(sources, neighbors, max_cost, max_nodes))

    def value(self, node: Node) -> Optional[float]:
        """The field value at *node*, or ``None`` if unreachable."""
        return self.values.get(node)

    def best_step(
        self, node: Node, neighbors: Neighbors, *, flee: bool = False
    ) -> Optional[Any]:
        """The neighbour that most decreases (or increases, when fleeing) the field."""
        here = self.values.get(node)
        if here is None:
            return None
        best: Optional[Any] = None
        best_v = here
        for nxt, _cost in neighbors(node):
            v = self.values.get(nxt)
            if v is None:
                continue
            if (v > best_v) if flee else (v < best_v):
                best, best_v = nxt, v
        return best

    def scale(self, factor: float) -> "DijkstraMap":
        """A copy with every value multiplied by *factor*."""
        return DijkstraMap({k: v * factor for k, v in self.values.items()})

    def combine(self, other: "DijkstraMap", weight: float = 1.0) -> "DijkstraMap":
        """Add another map's values (times *weight*) to this one."""
        out = dict(self.values)
        for k, v in other.values.items():
            out[k] = out.get(k, 0.0) + v * weight
        return DijkstraMap(out)

    def __len__(self) -> int:
        return len(self.values)


def bfs_reachable(
    start: Node, neighbors: Neighbors, max_nodes: int = 50000
) -> Set[Any]:
    """Every node reachable from *start*, ignoring edge costs."""
    seen: Set[Any] = {start}
    queue = deque([start])
    while queue and len(seen) < max_nodes:
        node = queue.popleft()
        for nxt, _cost in neighbors(node):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def nearest(
    start: Node,
    neighbors: Neighbors,
    predicate: Callable[[Any], bool],
    max_nodes: int = 20000,
) -> Optional[Any]:
    """Breadth-first search for the closest node satisfying *predicate*."""
    if predicate(start):
        return start
    seen: Set[Any] = {start}
    queue = deque([start])
    visited = 0
    while queue and visited < max_nodes:
        node = queue.popleft()
        visited += 1
        for nxt, _cost in neighbors(node):
            if nxt in seen:
                continue
            if predicate(nxt):
                return nxt
            seen.add(nxt)
            queue.append(nxt)
    return None


def path_to(
    start: Node,
    neighbors: Neighbors,
    predicate: Callable[[Any], bool],
    max_nodes: int = 20000,
) -> Optional[List[Any]]:
    """BFS path from *start* to the first node satisfying *predicate*.

    For a goal you can describe but cannot name -- the nearest edge of the
    map, the nearest open air, the nearest anything -- where A* has no single
    cell to aim its heuristic at.
    """
    if predicate(start):
        return [start]
    came: Dict[Any, Any] = {}
    seen: Set[Any] = {start}
    queue = deque([start])
    visited = 0
    while queue and visited < max_nodes:
        node = queue.popleft()
        visited += 1
        for nxt, _cost in neighbors(node):
            if nxt in seen:
                continue
            came[nxt] = node
            if predicate(nxt):
                path = [nxt]
                while path[-1] in came:
                    path.append(came[path[-1]])
                path.reverse()
                return path
            seen.add(nxt)
            queue.append(nxt)
    return None


# `path_cost` used to live here and nothing ever asked it what a path cost.
