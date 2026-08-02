from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_KEIL_SYMBOL_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_$][\w$.:<>~@?]*)\s+"
    r"(?P<address>0x[0-9A-Fa-f]+)\s+"
    r"(?:Thumb\s+Code|ARM\s+Code|Code|Data)\b"
)
_ADDRESS_FIRST_RE = re.compile(
    r"^\s*(?P<address>0x[0-9A-Fa-f]+)\s+"
    r"(?:(?:[tT])\s+)?(?P<name>[A-Za-z_$][\w$.:<>~@?]*)\s*$"
)
_ARMCLANG_SECTION_RE = re.compile(
    r"^\s*(?P<address>0x[0-9A-Fa-f]+)\s+"
    r"(?:0x[0-9A-Fa-f]+|COMPRESSED)\s+0x[0-9A-Fa-f]+\s+"
    r"(?:Code|Data)\s+(?:RO|RW|ZI)\s+\d+\s+"
    r"\.(?:text|data|bss|rodata)\.(?P<name>\S+)\s+\S+"
)


@dataclass(frozen=True, slots=True)
class MapSymbol:
    name: str
    address: int


class SectionMap:
    def __init__(self, symbols: dict[int, MapSymbol], source: Path) -> None:
        self.symbols = symbols
        self.source = source

    @classmethod
    def load(cls, path: str | Path) -> "SectionMap":
        source = Path(path)
        symbols: dict[int, MapSymbol] = {}
        text = source.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            match = (
                _KEIL_SYMBOL_RE.match(line)
                or _ARMCLANG_SECTION_RE.match(line)
                or _ADDRESS_FIRST_RE.match(line)
            )
            if match is None:
                continue
            address = int(match.group("address"), 16)
            symbols.setdefault(address, MapSymbol(match.group("name"), address))
        return cls(symbols, source)

    def resolve(self, address: int) -> MapSymbol | None:
        symbol = self.symbols.get(address)
        if symbol is not None:
            return symbol
        return self.symbols.get(address & ~1)
