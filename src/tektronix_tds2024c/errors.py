from __future__ import annotations


class TDS2024CError(Exception):
    """Base exception for all TDS2024C driver errors."""


class TDS2024CConnectionError(TDS2024CError):
    """Raised when the USB/VISA connection cannot be opened or is lost."""


class TDS2024CCommandError(TDS2024CError):
    """Raised when the oscilloscope reports a command or execution error.

    Attributes
    ----------
    code : int
        Tektronix event code from EVENT? query.
    message : str
        Human-readable message from EVMsg? query.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"TDS2024C event {code}: {message}")
        self.code = code
        self.message = message


class TDS2024CTimeoutError(TDS2024CError):
    """Raised when a VISA read/write times out."""


class TDS2024CMeasurementError(TDS2024CError):
    """Raised when a measurement returns the no-value sentinel (9.91e+37)."""
