from __future__ import annotations

__all__ = [
    "CommunicationManager",
    "ProtocolParser",
    "ProtocolRouter",
    "ProtocolSender",
    "RxProcessResult",
]


def __getattr__(name: str):
    """Load compatibility exports without coupling framework imports back to the facade."""
    if name in {"CommunicationManager", "RxProcessResult"}:
        from serial_debug_assistant.comm.communication_manager import CommunicationManager, RxProcessResult

        return {"CommunicationManager": CommunicationManager, "RxProcessResult": RxProcessResult}[name]
    if name == "ProtocolParser":
        from serial_debug_assistant.comm.protocol_parser import ProtocolParser

        return ProtocolParser
    if name == "ProtocolRouter":
        from serial_debug_assistant.comm.protocol_router import ProtocolRouter

        return ProtocolRouter
    if name == "ProtocolSender":
        from serial_debug_assistant.comm.protocol_sender import ProtocolSender

        return ProtocolSender
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
