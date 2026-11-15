"""Reading the crew datasets (``crew.parquet`` + ``meta.json`` of every run) from one or more directories, read-only.

A run is a directory with both files (the generator writes ``<name>.tmp`` and renames it when it is complete, so a directory
without ``.tmp`` is whole). ``meta["job"]`` has ``group`` (N1, M3, ...), ``split`` (train / val / test), ``npc``, ``event``,
``activity_at_start``; ``meta["faults"]`` the faults with ``start_s`` / ``duration_s``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


def _output_dir() -> Path:
    """``output/ml`` that holds the ``crew*`` run folders: this checkout's, or the main one's when this is a git worktree (``output/`` is not
    in the repository, so the data stays in the main checkout); ``ARES3_ML_DATA`` overrides both."""
    import os
    import subprocess

    if os.environ.get("ARES3_ML_DATA"):
        return Path(os.environ["ARES3_ML_DATA"])
    root = Path(__file__).resolve().parents[2]
    candidates = [root / "output" / "ml"]
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        candidates.append((root / common).resolve().parent / "output" / "ml")
    except (OSError, subprocess.CalledProcessError):
        pass
    return next((c for c in candidates if any(c.glob("crew*"))), candidates[0])


OUTPUT = _output_dir()
CREW_PREFIX = "crew-"


@dataclass
class CrewRun:
    path: Path
    meta: dict
    _crew: pd.DataFrame | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def job(self) -> dict:
        return self.meta["job"]

    @property
    def group(self) -> str:
        return self.job.get("group", "")

    @property
    def seed(self) -> int:
        return int(self.job["seed"])

    @property
    def days(self) -> float:
        return float(self.job["days"])

    @property
    def jitter(self) -> bool:
        return "crew_schedule" in self.job  # the generator writes the jittered programme into the job

    @property
    def faults(self) -> dict:
        return self.meta["faults"]

    @property
    def features(self) -> pd.DataFrame:
        """``features.parquet``: the station features (the stage B input), one row per minute once the 3 h windows are full."""
        return pd.read_parquet(self.path / "features.parquet")

    @property
    def crew(self) -> pd.DataFrame:
        if self._crew is None:
            self._crew = pd.read_parquet(self.path / "crew.parquet")
        return self._crew

    def free(self) -> None:
        self._crew = None


def find_runs(dirs: list[str | Path], prefix: str = CREW_PREFIX, need: str = "crew.parquet") -> list[CrewRun]:
    """Every complete run directly inside ``dirs`` (names starting with ``prefix``, holding the file ``need``), sorted by name; a name
    found twice (a run copied between machines) is read once. ``prefix=""`` and ``need="features.parquet"`` read the older catalog runs."""
    seen: dict[str, CrewRun] = {}
    for d in dirs:
        for p in sorted(Path(d).iterdir()):
            if p.is_dir() and p.name.startswith(prefix) and not p.name.endswith(".tmp") \
                    and (p / need).exists() and (p / "meta.json").exists() and p.name not in seen:
                seen[p.name] = CrewRun(p, json.loads((p / "meta.json").read_text(encoding="utf-8")))
    return sorted(seen.values(), key=lambda r: r.name)


def default_dirs() -> list[Path]:
    """Every ``crew*`` folder of ``output/ml`` of the main checkout (the data is not in the repository): waves 1, 2 and the twins."""
    return sorted(d for d in OUTPUT.glob("crew*") if d.is_dir())


def parse_seeds(text: str) -> list[int]:
    seeds: list[int] = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        seeds += range(int(a), int(b or a) + 1)
    return seeds
