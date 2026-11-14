"""Plugin resolution. ``kind`` in YAML is either ``"package.module:ClassName"`` (any importable
module, no registration needed) or a short alias registered with :func:`register`."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T", bound=type)
_ALIASES: dict[str, type] = {}


def register(alias: str) -> Callable[[T], T]:
    def deco(cls: T) -> T:
        _ALIASES[alias] = cls
        return cls

    return deco


def resolve(kind: str) -> type:
    if kind in _ALIASES:
        return _ALIASES[kind]
    module_name, sep, class_name = kind.partition(":")
    if not sep:
        raise ValueError(f"unknown plugin {kind!r}: use 'package.module:Class' or a registered alias")
    try:
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"cannot load plugin {kind!r}: {exc}") from exc
