"""Deterministic random streams.

One root ``seed`` per scenario; every component gets its own generator derived from the seed and its
string id. Adding or removing a sensor therefore never changes the numbers drawn by the others.
"""

from __future__ import annotations

import hashlib

import numpy as np


def _key_to_ints(*keys: str) -> list[int]:
    digest = hashlib.sha256("/".join(keys).encode("utf-8")).digest()
    return [int.from_bytes(digest[i : i + 4], "little") for i in range(0, 16, 4)]


def derive(seed: int, *keys: str) -> np.random.Generator:
    """Generator for ``(seed, keys)``; identical inputs always give the identical stream."""
    return np.random.default_rng(np.random.SeedSequence([seed, *_key_to_ints(*keys)]))
