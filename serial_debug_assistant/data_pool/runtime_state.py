from __future__ import annotations

import threading
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class ConnectionSnapshot:
    """Immutable view of the active backend connection."""

    revision: int = 0
    transport: str | None = None
    endpoint: str | None = None

    @property
    def connected(self) -> bool:
        return self.transport is not None


class RuntimeStatePool:
    """Own the single private copy of shared backend runtime state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connection = ConnectionSnapshot()
        self.business = RuntimeBusinessInterface(self)
        self.exchange = RuntimeExchangeInterface(self)

    def _read_connection(self) -> ConnectionSnapshot:
        with self._lock:
            return replace(self._connection)

    def _publish_connection(self, transport: str, endpoint: str) -> ConnectionSnapshot:
        if not transport:
            raise ValueError("transport must not be empty")
        if not endpoint:
            raise ValueError("endpoint must not be empty")
        with self._lock:
            self._connection = ConnectionSnapshot(
                revision=self._connection.revision + 1,
                transport=transport,
                endpoint=endpoint,
            )
            return replace(self._connection)

    def _clear_connection(self) -> ConnectionSnapshot:
        with self._lock:
            self._connection = ConnectionSnapshot(revision=self._connection.revision + 1)
            return replace(self._connection)


class RuntimeBusinessInterface:
    """Read-only, typed interface used by backend business logic."""

    def __init__(self, pool: RuntimeStatePool) -> None:
        self._pool = pool

    def connection(self) -> ConnectionSnapshot:
        return self._pool._read_connection()


class RuntimeExchangeInterface:
    """Write interface used by transport data sources."""

    def __init__(self, pool: RuntimeStatePool) -> None:
        self._pool = pool

    def publish_connection(self, *, transport: str, endpoint: str) -> ConnectionSnapshot:
        return self._pool._publish_connection(transport, endpoint)

    def clear_connection(self) -> ConnectionSnapshot:
        return self._pool._clear_connection()
