from __future__ import annotations

import serial


APP_VERSION = "1.2.0"
APP_TITLE = f"Serial Debug Assistant v{APP_VERSION}"
APP_GEOMETRY = "1240x962"
APP_MIN_WIDTH = 1080
APP_MIN_HEIGHT = 700
POLL_INTERVAL_MS = 120

DEFAULT_BAUD_RATE = "115200"
DEFAULT_DATA_BITS = "8"
DEFAULT_PARITY = "None"
DEFAULT_STOP_BITS = "1"
DEFAULT_BREAK_MS = "20"
DEFAULT_AUTO_SEND_SECONDS = "1.0"

BAUD_RATES = (
    "1200",
    "2400",
    "4800",
    "9600",
    "19200",
    "38400",
    "57600",
    "115200",
    "230400",
    "460800",
    "921600",
)

PARITY_OPTIONS = {
    "None": serial.PARITY_NONE,
    "Even": serial.PARITY_EVEN,
    "Odd": serial.PARITY_ODD,
    "Mark": serial.PARITY_MARK,
    "Space": serial.PARITY_SPACE,
}

STOP_BITS_OPTIONS = {
    "1": serial.STOPBITS_ONE,
    "1.5": serial.STOPBITS_ONE_POINT_FIVE,
    "2": serial.STOPBITS_TWO,
}

BYTE_SIZES = {
    "5": serial.FIVEBITS,
    "6": serial.SIXBITS,
    "7": serial.SEVENBITS,
    "8": serial.EIGHTBITS,
}
