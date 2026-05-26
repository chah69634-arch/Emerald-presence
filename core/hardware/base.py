"""Phase 0 hardware transport interfaces.

This module intentionally stays below the semantic layers: no memory, pipeline,
scheduler, LLM, data path, or device I/O concerns belong here.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Literal


Direction = Literal["input", "output"]


class HardwareDevice(ABC):
    """Abstract base class for a declared hardware endpoint."""

    @property
    @abstractmethod
    def device_id(self) -> str:
        """Stable in-process identifier for this device."""

    @property
    @abstractmethod
    def modality(self) -> str:
        """Signal modality, such as audio, image, motion, or haptic."""

    @property
    @abstractmethod
    def direction(self) -> Direction:
        """Transport direction for this device."""

    @property
    @abstractmethod
    def dangerous(self) -> bool:
        """Whether this device can affect the physical world or user safety."""


class InputDevice(HardwareDevice):
    """Input endpoint that can yield raw hardware signals."""

    @property
    def direction(self) -> Direction:
        return "input"

    @abstractmethod
    async def signals(self) -> AsyncIterator[object]:
        """Yield raw signals from the transport layer."""


class OutputDevice(HardwareDevice):
    """Output endpoint that can accept low-level hardware commands."""

    @property
    def direction(self) -> Direction:
        return "output"

    @abstractmethod
    async def send_command(self, command: object) -> None:
        """Accept a low-level command for the transport layer."""
