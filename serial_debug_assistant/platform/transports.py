from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TransportBinding:
    """Adapt one platform service to the backend byte-transport contract."""

    name: str
    service: Any
    writer: Callable[[bytes], int]
    protocol_enabled: bool = True

    def write(self, payload: bytes) -> int:
        return self.writer(payload)


class TransportRegistry:
    """Select one concrete platform transport without leaking its API upward."""

    def __init__(self) -> None:
        self._bindings: dict[str, TransportBinding] = {}

    def register(self, binding: TransportBinding) -> None:
        if not binding.name:
            raise ValueError("transport name must not be empty")
        if binding.name in self._bindings:
            raise ValueError(f"transport already registered: {binding.name}")
        self._bindings[binding.name] = binding

    def get(self, name: str | None) -> TransportBinding | None:
        if name is None:
            return None
        return self._bindings.get(name)

    def require(self, name: str | None) -> TransportBinding:
        binding = self.get(name)
        if binding is None:
            raise RuntimeError("No hardware transport is open.")
        return binding

    def close_all(self) -> None:
        closed_services: set[int] = set()
        for binding in self._bindings.values():
            service_id = id(binding.service)
            if service_id in closed_services:
                continue
            binding.service.close()
            closed_services.add(service_id)
