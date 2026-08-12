"""The job board.

Standing orders — designations, building sites, production queues, loose goods —
are turned into jobs. Idle dwarves claim the nearest job their labors allow and
work it until it is done.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..engine import colors, geometry
from ..engine.colors import Color

Cell = Tuple[int, int, int]

#: Job kind -> (label, colour).
JOB_LABELS: Dict[str, Tuple[str, Color]] = {
    "dig": ("Mining", colors.Color(200, 190, 140)),
    "channel": ("Channelling", colors.Color(190, 160, 110)),
    "stairs": ("Carving stairs", colors.Color(200, 200, 170)),
    "ramp": ("Carving a ramp", colors.Color(190, 180, 150)),
    "smooth": ("Smoothing stone", colors.Color(180, 190, 200)),
    "chop": ("Felling a tree", colors.Color(150, 200, 130)),
    "gather": ("Gathering plants", colors.Color(150, 210, 150)),
    "remove": ("Removing a construction", colors.Color(200, 140, 130)),
    "haul": ("Hauling", colors.Color(170, 170, 190)),
    "build": ("Building", colors.Color(200, 180, 120)),
    "craft": ("Working", colors.Color(190, 170, 210)),
    "plant": ("Planting", colors.Color(140, 200, 140)),
    "harvest": ("Harvesting", colors.Color(190, 210, 130)),
    "eat": ("Eating", colors.Color(200, 190, 140)),
    "drink": ("Drinking", colors.Color(170, 190, 220)),
    "sleep": ("Sleeping", colors.Color(150, 150, 190)),
    "treat": ("Treating the wounded", colors.Color(200, 150, 150)),
    "mood": ("Possessed", colors.MAGIC),
}


@dataclass
class Job:
    """One unit of work waiting for, or being done by, a dwarf."""

    id: int
    kind: str
    x: int
    y: int
    z: int
    labor: str = ""
    skill: str = ""
    work: int = 100
    progress: int = 0
    priority: int = 5
    assigned: Optional[int] = None
    #: Designation cell, building id, item id or recipe id, as the kind requires.
    target: Any = None
    carrying: Optional[int] = None
    failed: int = 0

    @property
    def cell(self) -> Cell:
        """Where the work happens."""
        return (self.x, self.y, self.z)

    @property
    def label(self) -> str:
        """Readable name for the units list."""
        return JOB_LABELS.get(self.kind, (self.kind.title(), colors.UI["fg"]))[0]

    @property
    def color(self) -> Color:
        """Colour for the units list."""
        return JOB_LABELS.get(self.kind, ("", colors.UI["fg"]))[1]

    @property
    def done(self) -> bool:
        """True once enough work has been put in."""
        return self.progress >= self.work

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the job."""
        return {
            "id": self.id, "kind": self.kind, "x": self.x, "y": self.y,
            "z": self.z, "labor": self.labor, "skill": self.skill,
            "work": self.work, "progress": self.progress,
            "priority": self.priority, "assigned": self.assigned,
            "target": self.target, "carrying": self.carrying,
            "failed": self.failed,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Job":
        """Rebuild from :meth:`to_dict`."""
        return cls(
            id=int(d["id"]), kind=str(d["kind"]), x=int(d["x"]), y=int(d["y"]),
            z=int(d["z"]), labor=str(d.get("labor", "")),
            skill=str(d.get("skill", "")), work=int(d.get("work", 100)),
            progress=int(d.get("progress", 0)),
            priority=int(d.get("priority", 5)), assigned=d.get("assigned"),
            target=d.get("target"), carrying=d.get("carrying"),
            failed=int(d.get("failed", 0)),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Job(%s at %d,%d,%d)" % (self.kind, self.x, self.y, self.z)


class JobBoard:
    """Every outstanding job, and who has claimed what."""

    def __init__(self) -> None:
        self.jobs: Dict[int, Job] = {}
        self._next_id = 1
        #: Item ids promised to a job, so two haulers do not chase one rock.
        self.reserved_items: Dict[int, int] = {}
        #: Cells already covered by a job, so we do not post duplicates.
        self._cells: Dict[Tuple[str, Cell], int] = {}

    # -- posting ----------------------------------------------------------- #

    def post(self, job: Job) -> Job:
        """Add a job to the board."""
        job.id = self._next_id
        self._next_id += 1
        self.jobs[job.id] = job
        self._cells[(job.kind, job.cell)] = job.id
        return job

    def make(
        self, kind: str, x: int, y: int, z: int, **kw
    ) -> Job:
        """Build and post a job in one step."""
        return self.post(Job(0, kind, x, y, z, **kw))

    def has_job_at(self, kind: str, cell: Cell) -> bool:
        """True if a job of this kind already covers this cell."""
        jid = self._cells.get((kind, cell))
        return jid is not None and jid in self.jobs

    def remove(self, job: Job) -> None:
        """Take a job off the board and release anything it held."""
        self.jobs.pop(job.id, None)
        self._cells.pop((job.kind, job.cell), None)
        for item_id, owner in list(self.reserved_items.items()):
            if owner == job.id:
                del self.reserved_items[item_id]

    def clear_kind(self, kind: str) -> None:
        """Cancel every job of one kind."""
        for job in [j for j in self.jobs.values() if j.kind == kind]:
            self.remove(job)

    # -- reservations ------------------------------------------------------ #

    def reserve_item(self, item_id: int, job: Job) -> bool:
        """Promise an item to a job."""
        if item_id in self.reserved_items:
            return False
        self.reserved_items[item_id] = job.id
        return True

    def is_reserved(self, item_id: int) -> bool:
        """True if some job has already claimed this item."""
        return item_id in self.reserved_items

    def release_item(self, item_id: int) -> None:
        """Give a reserved item back."""
        self.reserved_items.pop(item_id, None)

    # -- assignment -------------------------------------------------------- #

    def unassigned(self) -> List[Job]:
        """Every job nobody is working on, most urgent first."""
        out = [j for j in self.jobs.values() if j.assigned is None]
        out.sort(key=lambda j: (-j.priority, j.failed, j.id))
        return out

    def for_dwarf(self, dwarf) -> List[Job]:
        """Unassigned jobs this dwarf's labors allow, nearest first."""
        pos = (dwarf.x, dwarf.y, dwarf.z)
        out = []
        for job in self.unassigned():
            if job.failed >= 3:
                continue
            if job.labor and not dwarf.labors.has(job.labor):
                continue
            out.append(job)
        out.sort(key=lambda j: (
            -j.priority,
            geometry.chebyshev(pos[0], pos[1], j.x, j.y) + abs(pos[2] - j.z) * 3,
        ))
        return out

    def assign(self, job: Job, dwarf) -> None:
        """Give a job to a dwarf."""
        job.assigned = dwarf.id
        dwarf.job = job

    def release(self, job: Job, *, penalise: bool = True) -> None:
        """Put a job back on the board after a dwarf gives up on it."""
        job.assigned = None
        if penalise:
            job.failed += 1

    def release_all(self, dwarf_id: int) -> None:
        """Free every job a dwarf held."""
        for job in self.jobs.values():
            if job.assigned == dwarf_id:
                self.release(job, penalise=False)

    def assigned_to(self, dwarf_id: int) -> Optional[Job]:
        """The job a dwarf currently holds."""
        for job in self.jobs.values():
            if job.assigned == dwarf_id:
                return job
        return None

    def count(self, kind: str = "") -> int:
        """How many jobs are outstanding, optionally of one kind."""
        if not kind:
            return len(self.jobs)
        return sum(1 for j in self.jobs.values() if j.kind == kind)

    def summary(self) -> List[Tuple[str, int]]:
        """Job counts by kind, busiest first."""
        counts: Dict[str, int] = {}
        for job in self.jobs.values():
            counts[job.kind] = counts.get(job.kind, 0) + 1
        return sorted(counts.items(), key=lambda kv: -kv[1])

    def __len__(self) -> int:
        return len(self.jobs)

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the board."""
        return {
            "jobs": [j.to_dict() for j in self.jobs.values()],
            "next_id": self._next_id,
            "reserved": {str(k): v for k, v in self.reserved_items.items()},
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "JobBoard":
        """Rebuild from :meth:`to_dict`."""
        board = cls()
        for jd in d.get("jobs", []):
            job = Job.from_dict(jd)
            board.jobs[job.id] = job
            board._cells[(job.kind, job.cell)] = job.id
        board._next_id = int(d.get("next_id", len(board.jobs) + 1))
        board.reserved_items = {
            int(k): int(v) for k, v in (d.get("reserved") or {}).items()
        }
        return board


#: :func:`work_rate` counts in hundredths of a work point per tick, so that
#: the difference between a novice and a legend is not lost to integer maths.
WORK_SCALE = 100


def work_rate(dwarf, job: Job) -> int:
    """Hundredths of a work point a dwarf puts in per tick.

    An unhurt, unskilled dwarf manages about one point per tick, so a job's
    ``work`` value reads directly as "roughly this many ticks of labour".
    """
    from ..game.skills import skill_bonus

    rate = float(WORK_SCALE)
    if job.skill:
        rate *= skill_bonus(dwarf.skills.level(job.skill))
    rate *= 0.6 + 0.4 * dwarf.attributes.factor("strength")
    rate *= 0.7 + 0.3 * dwarf.attributes.factor("endurance")
    if dwarf.needs.fatigue > 1200:
        rate *= 0.7
    rate *= max(0.3, 1.0 - dwarf.body.pain_level() * 0.6)
    return max(1, int(rate))
