"""A backend that prints gamepad state instead of emitting it.

Useful for checking a mapping without ViGEmBus installed, and for running the
bridge on a machine that has no virtual-gamepad driver at all.
"""

from __future__ import annotations

import sys
import time
from typing import TextIO

from ..mapping import OutputState
from .base import GamepadOutput


class DebugOutput(GamepadOutput):
    name = "debug"

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._last: OutputState | None = None
        self._started = time.monotonic()

    def apply(self, state: OutputState) -> None:
        if state == self._last:
            return
        self._last = state
        elapsed = time.monotonic() - self._started
        print(f"[{elapsed:8.3f}s] {state.describe()}", file=self._stream, flush=True)

    def reset(self) -> None:
        super().reset()
        self._last = None
