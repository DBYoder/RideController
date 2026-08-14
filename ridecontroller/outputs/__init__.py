"""Virtual gamepad backends."""

from __future__ import annotations

from .base import GamepadOutput, NullOutput, OutputError
from .debug import DebugOutput

BACKENDS = ("xbox360", "debug", "null")

__all__ = [
    "BACKENDS",
    "DebugOutput",
    "GamepadOutput",
    "NullOutput",
    "OutputError",
    "create_output",
]


def create_output(name: str) -> GamepadOutput:
    """Instantiate a backend by name (not yet opened)."""
    key = name.strip().lower()
    if key == "debug":
        return DebugOutput()
    if key == "null":
        return NullOutput()
    if key == "xbox360":
        from .xbox360 import Xbox360Output

        return Xbox360Output()
    raise OutputError(f"unknown backend {name!r}; expected one of {list(BACKENDS)}")
