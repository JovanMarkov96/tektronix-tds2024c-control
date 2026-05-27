from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .models import Channel


@dataclass
class WaveformPreamble:
    """Parsed fields from a ``WFMPre?`` response.

    The TDS2000B family returns the preamble in one of two formats depending
    on the ``HEADer`` setting:

    * **HEADer OFF** (this driver's default) — positional, semicolon-separated
      values with no field names::

          1;8;BIN;RI;MSB;2500;"Ch1, ...";Y;1.0E-11;0;-1.25E-8;"s";8.0E-4;0;0;"Volts"

      Field order (16 fields):
      BYT_NR; BIT_NR; ENCDG; BN_FMT; BYT_OR; NR_PT; WFID; PT_FMT;
      XINCR; PT_OFF; XZERO; XUNIT; YMULT; YOFF; YZERO; YUNIT

    * **HEADer ON** — ``KEY value;KEY value;...`` pairs.

    ``from_response`` auto-detects and handles both.
    """
    n_points:   int
    byte_width: int
    bit_width:  int
    encoding:   str       # "BIN" / "ASC"
    bn_fmt:     str       # "RI" / "RP"
    byte_order: str       # "MSB" / "LSB"
    pt_fmt:     str       # "Y" (normal) or "ENV" (peak-detect)
    x_incr:    float      # seconds per sample
    x_zero:    float      # time of first sample (seconds)
    x_unit:    str
    y_mult:    float      # volts per ADC count
    y_off:     float      # vertical offset in ADC counts
    y_zero:    float      # reference level in volts
    y_unit:    str
    pt_off:    int = 0    # trigger point offset in samples
    wfid:      str = ""

    # ── Parsing ────────────────────────────────────────────────────────────────

    @classmethod
    def from_response(cls, response: str) -> "WaveformPreamble":
        response = response.strip()
        if _looks_like_header_on(response):
            return cls._from_header_on(response)
        return cls._from_positional(response)

    @classmethod
    def _from_positional(cls, response: str) -> "WaveformPreamble":
        parts = [p.strip() for p in response.split(";")]
        if len(parts) < 16:
            raise ValueError(
                f"WFMPre? positional response has {len(parts)} fields, "
                f"expected >= 16: {response!r}"
            )

        def _f(idx: int, default: float = 0.0) -> float:
            try:
                return float(parts[idx])
            except (ValueError, IndexError):
                return default

        def _i(idx: int, default: int = 0) -> int:
            try:
                return int(float(parts[idx]))
            except (ValueError, IndexError):
                return default

        def _s(idx: int, default: str = "") -> str:
            try:
                return parts[idx].strip().strip('"')
            except IndexError:
                return default

        return cls(
            byte_width = _i(0, 1),
            bit_width  = _i(1, 8),
            encoding   = _s(2, "BIN"),
            bn_fmt     = _s(3, "RI"),
            byte_order = _s(4, "MSB"),
            n_points   = _i(5, 0),
            wfid       = _s(6),
            pt_fmt     = _s(7, "Y"),
            x_incr     = _f(8, 1.0),
            pt_off     = _i(9, 0),
            x_zero     = _f(10, 0.0),
            x_unit     = _s(11, "s"),
            y_mult     = _f(12, 1.0),
            y_off      = _f(13, 0.0),
            y_zero     = _f(14, 0.0),
            y_unit     = _s(15, "V"),
        )

    @classmethod
    def _from_header_on(cls, response: str) -> "WaveformPreamble":
        fields: dict[str, str] = {}
        for token in response.split(";"):
            token = token.strip()
            # strip a leading ":WFMPRE:" path if present
            if token.upper().startswith(":WFMP"):
                token = token.split(":", 2)[-1]
            if " " in token:
                key, _, val = token.partition(" ")
                fields[key.upper()] = val.strip().strip('"')

        def _f(key: str, default: float) -> float:
            try:
                return float(fields[key])
            except (KeyError, ValueError):
                return default

        def _i(key: str, default: int) -> int:
            try:
                return int(float(fields[key]))
            except (KeyError, ValueError):
                return default

        return cls(
            byte_width = _i("BYT_NR", 1),
            bit_width  = _i("BIT_NR", 8),
            encoding   = fields.get("ENCDG", "BIN"),
            bn_fmt     = fields.get("BN_FMT", "RI"),
            byte_order = fields.get("BYT_OR", "MSB"),
            n_points   = _i("NR_PT", 0),
            wfid       = fields.get("WFID", ""),
            pt_fmt     = fields.get("PT_FMT", "Y"),
            x_incr     = _f("XINCR", 1.0),
            pt_off     = _i("PT_OFF", 0),
            x_zero     = _f("XZERO", 0.0),
            x_unit     = fields.get("XUNIT", "s"),
            y_mult     = _f("YMULT", 1.0),
            y_off      = _f("YOFF", 0.0),
            y_zero     = _f("YZERO", 0.0),
            y_unit     = fields.get("YUNIT", "V"),
        )

    @property
    def is_big_endian(self) -> bool:
        return self.byte_order.upper() == "MSB"


@dataclass
class WaveformRecord:
    """A fully decoded oscilloscope waveform trace (SI units)."""
    channel:  Channel
    t:        np.ndarray   # seconds
    v:        np.ndarray   # volts
    preamble: WaveformPreamble

    @property
    def dt(self) -> float:
        return self.preamble.x_incr

    @property
    def n_points(self) -> int:
        return int(len(self.v))

    @property
    def v_rms(self) -> float:
        return float(np.sqrt(np.mean(self.v ** 2))) if len(self.v) else float("nan")

    @property
    def v_pkpk(self) -> float:
        return float(np.max(self.v) - np.min(self.v)) if len(self.v) else float("nan")

    @property
    def v_mean(self) -> float:
        return float(np.mean(self.v)) if len(self.v) else float("nan")

    # ── Constructors ────────────────────────────────────────────────────────────

    @classmethod
    def from_preamble_and_samples(
        cls,
        channel: Channel,
        preamble: WaveformPreamble,
        samples: Sequence[float] | np.ndarray,
    ) -> "WaveformRecord":
        """Build a record from already-extracted integer ADC samples.

        This is the preferred path: ``pyvisa.query_binary_values`` parses the
        IEEE block header and returns the raw integer samples directly, so we
        only need to apply the scaling transform here.
        """
        adc = np.asarray(samples, dtype=np.float64)
        v = (adc - preamble.y_off) * preamble.y_mult + preamble.y_zero
        t = preamble.x_zero + np.arange(len(v)) * preamble.x_incr
        return cls(channel=channel, t=t, v=v, preamble=preamble)

    @classmethod
    def from_preamble_and_raw(
        cls,
        channel: Channel,
        preamble: WaveformPreamble,
        raw: bytes,
    ) -> "WaveformRecord":
        """Build a record from a raw ``CURVe?`` binary block (with IEEE header).

        Fallback for transports where ``query_binary_values`` is unavailable.
        Strips the ``#<NZDig><len>`` header, then decodes per the preamble.
        """
        data = _strip_block_header(raw)
        if preamble.bit_width <= 8:
            adc = np.frombuffer(data, dtype=np.int8).astype(np.float64)
        else:
            dt = ">i2" if preamble.is_big_endian else "<i2"
            adc = np.frombuffer(data, dtype=dt).astype(np.float64)
        return cls.from_preamble_and_samples(channel, preamble, adc)

    @classmethod
    def from_preamble_and_ascii(
        cls,
        channel: Channel,
        preamble: WaveformPreamble,
        ascii_response: str,
    ) -> "WaveformRecord":
        """Decode an ASCII ``CURVe?`` response (comma-separated integers)."""
        text = ascii_response.strip()
        if not text:
            adc = np.array([], dtype=np.float64)
        else:
            adc = np.array([float(x) for x in text.split(",")], dtype=np.float64)
        return cls.from_preamble_and_samples(channel, preamble, adc)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _looks_like_header_on(response: str) -> bool:
    """True if the WFMPre? response uses ``KEY value`` (header-on) format."""
    first = response.split(";", 1)[0].strip()
    if not first or first.startswith('"'):
        return False
    # header-on first token looks like "BYT_NR 1" or ":WFMPRE:BYT_NR 1"
    head = first.split(" ", 1)[0]
    return (" " in first) and any(c.isalpha() for c in head)


def _strip_block_header(raw: bytes) -> bytes:
    """Remove an IEEE 488.2 definite-length block header ``#NDD..D`` and any
    trailing terminator newline."""
    if not raw:
        return raw
    if raw[0:1] != b"#":
        return raw.rstrip(b"\n\r")
    n_dig = int(chr(raw[1]))
    n_bytes = int(raw[2: 2 + n_dig])
    start = 2 + n_dig
    return raw[start: start + n_bytes]
