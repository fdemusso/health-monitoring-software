"""Cache of the warm-up (``ares3 serve --warmup-cache DIR``).

The warm-up is deterministic (one root seed), so the state after N simulated hours is always the same. It is pickled once and a
restart loads it instead of simulating the hours again. The file name carries a key (hash of the resolved scenario, the warm-up
length, the package sources and the model files): any change to code, scenario or models gives another name, so a stale state is
never loaded; the old file is deleted on the next save. A cache that cannot be read or written is never fatal: the server falls
back to the normal warm-up. SECURITY: pickle runs code on load, so DIR must be writable only by us (like the ``.joblib`` models).
"""

from __future__ import annotations

import hashlib
import os
import pickle
import sys
from pathlib import Path

import ares3
from ares3.schemas.scenario import Scenario
from ares3.serve.session import Session

_FIELDS = ("engine", "_latest", "_events", "_owed", "_history", "_vitals", "_wearables")
_PREFIX = "warmup-"


def cache_key(scenario: Scenario, warmup_s: float, models_dir: str | Path = "models") -> str:
    h = hashlib.sha256()
    h.update(f"{sys.version_info[:2]}|{pickle.HIGHEST_PROTOCOL}|{warmup_s}|".encode())
    h.update(scenario.model_dump_json().encode())
    roots = [Path(ares3.__file__).parent, Path(models_dir)]
    for root in roots:
        for f in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in {".py", ".joblib", ".yaml", ".json"}):
            h.update(str(f.relative_to(root)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:20]


def _path(directory: str | Path, key: str) -> Path:
    return Path(directory) / f"{_PREFIX}{key}.pkl"


def load(session: Session, directory: str | Path, key: str) -> bool:
    """Restore the warmed-up state into ``session``; False (and the session untouched) when there is none or it is unreadable."""
    path = _path(directory, key)
    if not path.is_file():
        return False
    try:
        with path.open("rb") as fh:
            state = pickle.load(fh)  # our own file, see the module docstring
        for name in _FIELDS:
            if name not in state:
                return False
    except Exception as exc:  # noqa: BLE001 corrupt or from another version: warm up normally
        print(f"warm-up cache {path.name} unusable ({exc!r}), warming up", file=sys.stderr, flush=True)
        return False
    for name in _FIELDS:
        value = state[name]
        if name in ("_history", "_vitals"):
            getattr(session, name).extend(value)
        else:
            setattr(session, name, value)
    session._events = []
    session.state = "live"
    return True


def save(session: Session, directory: str | Path, key: str) -> Path | None:
    """Write the state atomically and drop older caches of this directory; None when it could not be written."""
    path = _path(directory, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {name: getattr(session, name) for name in _FIELDS}
        state["_history"], state["_vitals"] = list(session._history), list(session._vitals)
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        with tmp.open("wb") as fh:
            pickle.dump(state, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        for old in path.parent.glob(f"{_PREFIX}*.pkl"):
            if old != path:
                old.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        print(f"warm-up cache not written ({exc!r})", file=sys.stderr, flush=True)
        return None
    return path
