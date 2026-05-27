from __future__ import annotations

from enum import Enum


class _ScpiEnum(str, Enum):
    """Base for SCPI keyword enums with robust device-response parsing.

    Tektronix scopes accept the mixed-case short/long form on *set*
    (e.g. ``SAMple`` or ``SAM``) but echo back the **uppercase full word**
    on *query* (e.g. ``SAMPLE``).  Enum *values* in this module store the
    mixed-case long form, so a direct ``AcqMode("SAMPLE")`` would raise
    ``ValueError``.  The ``_missing_`` hook below makes the constructor
    tolerant of:

    * the uppercase full word the device returns (``SAMPLE``)
    * the SCPI short form (``SAM``)
    * surrounding quotes / whitespace
    * any letter casing

    This means every ``EnumType(query_result)`` call site parses correctly
    without special-casing.
    """

    @classmethod
    def _missing_(cls, value):
        if not isinstance(value, str):
            return None
        token = value.strip().strip('"').strip("'").upper()
        if not token:
            return None
        # 1) exact match on the uppercased long form
        for member in cls:
            if member.value.upper() == token:
                return member
        # 2) SCPI short form = leading run of capitals in the stored value
        for member in cls:
            short = ""
            for ch in member.value:
                if ch.islower():
                    break
                short += ch
            if short and token == short.upper():
                return member
        return None


class Channel(_ScpiEnum):
    CH1  = "CH1"
    CH2  = "CH2"
    CH3  = "CH3"
    CH4  = "CH4"
    MATH = "MATH"
    REFA = "REFA"
    REFB = "REFB"
    REFC = "REFC"
    REFD = "REFD"

    @classmethod
    def analog(cls) -> list["Channel"]:
        return [cls.CH1, cls.CH2, cls.CH3, cls.CH4]


class TriggerSource(_ScpiEnum):
    """Valid sources for TRIGger:MAIn:EDGE:SOUrce.

    Superset of the analog channels plus the external and line sources.
    """
    CH1  = "CH1"
    CH2  = "CH2"
    CH3  = "CH3"
    CH4  = "CH4"
    EXT  = "EXT"
    EXT5 = "EXT5"
    LINE = "LINE"


class Coupling(_ScpiEnum):
    AC  = "AC"
    DC  = "DC"
    GND = "GND"


class TriggerCoupling(_ScpiEnum):
    """Edge-trigger coupling — superset of channel coupling."""
    AC       = "AC"
    DC       = "DC"
    HF_REJ   = "HFRej"
    LF_REJ   = "LFRej"
    NOISE_REJ = "NOISErej"


class BandwidthLimit(_ScpiEnum):
    """CH<x>:BANdwidth — ON = full BW, OFF = 20 MHz limit."""
    FULL       = "ON"
    TWENTY_MHZ = "OFF"


class AcqMode(_ScpiEnum):
    SAMPLE  = "SAMple"
    PEAK    = "PEAKdetect"
    AVERAGE = "AVErage"


class AcqStopAfter(_ScpiEnum):
    RUNSTOP  = "RUNSTop"   # free-running
    SEQUENCE = "SEQuence"  # single acquisition


class TriggerType(_ScpiEnum):
    EDGE  = "EDGE"
    PULSE = "PULse"
    VIDEO = "VIDeo"


class TriggerSlope(_ScpiEnum):
    RISE = "RISe"
    FALL = "FALL"


class TriggerMode(_ScpiEnum):
    AUTO   = "AUTO"
    NORMAL = "NORMal"


class TriggerState(_ScpiEnum):
    """Values returned by TRIGger:STATe?"""
    ARMED   = "ARMED"
    AUTO    = "AUTO"
    READY   = "READY"
    SAVE    = "SAVE"
    TRIGGER = "TRIGGER"


class MeasType(_ScpiEnum):
    FREQUENCY = "FREQuency"
    PERIOD    = "PERIod"
    MEAN      = "MEAN"
    PKPK      = "PK2pk"
    RMS       = "RMS"
    RISE      = "RISe"
    FALL      = "FALL"
    WIDTH_POS = "PWIdth"
    WIDTH_NEG = "NWIdth"
    MAXIMUM   = "MAXimum"
    MINIMUM   = "MINimum"


class WfmEncoding(_ScpiEnum):
    ASCII    = "ASCIi"
    RIBINARY = "RIBinary"   # signed binary, fastest
    RPBINARY = "RPBinary"   # unsigned binary


class WfmWidth(int, Enum):
    ONE_BYTE = 1
    TWO_BYTE = 2


# Tektronix sentinel returned by MEASUrement:IMMed:VALue? when a measurement
# cannot be made (no/!valid signal).  Any magnitude >= ~9.9e37 means "no value".
MEAS_NO_VALUE: float = 9.91e+37
