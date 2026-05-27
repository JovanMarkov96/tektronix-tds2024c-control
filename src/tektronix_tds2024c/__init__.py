"""tektronix_tds2024c — Python driver and GUI for the Tektronix TDS2024C DSO."""

__version__ = "0.1.0"

from .instrument import TDS2024C
from .discovery import (
    list_tektronix_resources,
    list_tds2024c_resources,
    find_first_tds2024c,
)
from .waveform import WaveformRecord, WaveformPreamble
from .models import (
    Channel,
    TriggerSource,
    Coupling,
    TriggerCoupling,
    BandwidthLimit,
    AcqMode,
    AcqStopAfter,
    TriggerType,
    TriggerSlope,
    TriggerMode,
    TriggerState,
    MeasType,
    WfmEncoding,
    WfmWidth,
    MEAS_NO_VALUE,
)
from .errors import (
    TDS2024CError,
    TDS2024CConnectionError,
    TDS2024CCommandError,
    TDS2024CTimeoutError,
    TDS2024CMeasurementError,
)

__all__ = [
    "TDS2024C",
    "list_tektronix_resources",
    "list_tds2024c_resources",
    "find_first_tds2024c",
    "WaveformRecord",
    "WaveformPreamble",
    "Channel",
    "TriggerSource",
    "Coupling",
    "TriggerCoupling",
    "BandwidthLimit",
    "AcqMode",
    "AcqStopAfter",
    "TriggerType",
    "TriggerSlope",
    "TriggerMode",
    "TriggerState",
    "MeasType",
    "WfmEncoding",
    "WfmWidth",
    "MEAS_NO_VALUE",
    "TDS2024CError",
    "TDS2024CConnectionError",
    "TDS2024CCommandError",
    "TDS2024CTimeoutError",
    "TDS2024CMeasurementError",
]
