"""Interface shared by the virtual-gamepad backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..mapping import NEUTRAL, OutputState


class OutputError(RuntimeError):
    """Raised when a backend cannot be created or driven."""


class GamepadOutput(ABC):
    """A sink for :class:`~ridecontroller.mapping.OutputState` snapshots."""

    name = "output"

    def open(self) -> None:
        """Acquire the underlying device. Safe to call once."""

    @abstractmethod
    def apply(self, state: OutputState) -> None:
        """Push a complete state snapshot to the virtual gamepad."""

    def reset(self) -> None:
        """Release everything (used on disconnect and shutdown)."""
        self.apply(NEUTRAL)

    def close(self) -> None:
        """Release the underlying device."""

    def __enter__(self) -> "GamepadOutput":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        try:
            self.reset()
        finally:
            self.close()


class NullOutput(GamepadOutput):
    """Discards everything. Used by ``monitor``, where only inputs matter."""

    name = "null"

    def apply(self, state: OutputState) -> None:
        pass

    def reset(self) -> None:
        pass
