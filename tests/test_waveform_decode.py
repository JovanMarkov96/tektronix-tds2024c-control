"""Tests for WFMPre parsing and WaveformRecord decode — no hardware required."""

import struct
import numpy as np
import pytest

from tektronix_tds2024c.waveform import (
    WaveformPreamble,
    WaveformRecord,
    _strip_block_header,
)
from tektronix_tds2024c.models import Channel


# Real header-off WFMPre? response captured from a TDS2024C (FV:v24.26)
# Channel position = 0 so YZERO=0.0 and YOFF=0.0 — both are zero here.
_REAL_WFMPRE = (
    '1;8;BIN;RI;MSB;2500;"Ch1, DC coupling, 2.0E-2 V/div, 2.5E-9 s/div, '
    '2500 points, Sample mode";Y;1.0E-11;0;-1.25E-8;"s";8.0E-4;0.0E0;0.0E0;"Volts"'
)

# Real header-off WFMPre? response at 200 mV/div with CH1 position = +2.0 div.
# YOFF is non-zero here (50 ADC counts), which is the case that exposes the
# field-13/14 swap bug.  Field order from TDS2000B Table B-1:
#   … YMULT; YZERO; YOFF; YUNIT
#         12;    13;   14;    15
# YZERO (field 13) = 0.0E0 = reference voltage (zero volts)
# YOFF  (field 14) = 5.0E1 = ADC count that maps to YZERO (changes with position)
_REAL_WFMPRE_POS = (
    '1;8;BIN;RI;MSB;2500;"Ch1, DC coupling, 2.0E-1 V/div, 5.0E-7 s/div, '
    '2500 points, Sample mode";Y;2.0E-9;0;-2.5E-6;"s";8.0E-3;0.0E0;5.0E1;"Volts"'
)


def _make_preamble(**overrides) -> WaveformPreamble:
    defaults = dict(
        n_points=10, byte_width=1, bit_width=8, encoding="BIN", bn_fmt="RI",
        byte_order="MSB", pt_fmt="Y", x_incr=1e-8, x_zero=0.0, x_unit="s",
        y_mult=0.04, y_off=0.0, y_zero=0.0, y_unit="V",
    )
    defaults.update(overrides)
    return WaveformPreamble(**defaults)


def _make_block(data: bytes) -> bytes:
    length_str = str(len(data)).encode()
    return b"#" + str(len(length_str)).encode() + length_str + data


# ── _strip_block_header ────────────────────────────────────────────────────────

def test_strip_header_basic():
    payload = b"\x00\x01\x02\x03"
    assert _strip_block_header(_make_block(payload)) == payload


def test_strip_header_4_length_digits():
    payload = bytes(i % 256 for i in range(2500))
    assert _strip_block_header(_make_block(payload)) == payload


def test_strip_header_strips_trailing_newline_when_no_block():
    assert _strip_block_header(b"1,2,3\n") == b"1,2,3"


def test_strip_header_empty():
    assert _strip_block_header(b"") == b""


# ── WFMPre? positional (HEADer OFF) — the real default format ──────────────────

def test_parse_real_positional_wfmpre():
    p = WaveformPreamble.from_response(_REAL_WFMPRE)
    assert p.byte_width == 1
    assert p.bit_width == 8
    assert p.encoding == "BIN"
    assert p.bn_fmt == "RI"
    assert p.byte_order == "MSB"
    assert p.is_big_endian is True
    assert p.n_points == 2500
    assert p.x_incr == pytest.approx(1e-11)
    assert p.x_zero == pytest.approx(-1.25e-8)
    assert p.x_unit == "s"
    assert p.y_mult == pytest.approx(8e-4)
    assert p.y_off == 0.0
    assert p.y_zero == 0.0
    assert p.y_unit == "Volts"
    assert "Ch1" in p.wfid  # quoted WFID with commas survived the split


def test_positional_wfid_with_commas_does_not_break_fields():
    # The WFID field contains commas and spaces; splitting on ';' must keep
    # the trailing scaling fields aligned.
    p = WaveformPreamble.from_response(_REAL_WFMPRE)
    # If WFID had been mis-split, y_mult would not be the 13th field value.
    assert p.y_mult == pytest.approx(8e-4)


def test_positional_too_few_fields_raises():
    with pytest.raises(ValueError):
        WaveformPreamble.from_response("1;8;BIN;RI;MSB")


def test_positional_yzero_yoff_field_order():
    """Field 13 = YZERO, field 14 = YOFF (TDS2000B Table B-1 order).

    This is the *opposite* of alphabetical order.  The bug being guarded
    against is swapping the two assignments, which causes decoded voltages
    to be ~200× wrong when the channel position is non-zero (YOFF != 0).

    _REAL_WFMPRE_POS is captured at 200 mV/div with CH1 position = +2.0 div
    so YOFF = 50 ADC counts and YZERO = 0.0 V.
    """
    p = WaveformPreamble.from_response(_REAL_WFMPRE_POS)
    assert p.y_mult  == pytest.approx(8e-3)
    assert p.y_zero  == pytest.approx(0.0),  "field 13 is YZERO (reference voltage)"
    assert p.y_off   == pytest.approx(50.0), "field 14 is YOFF (ADC count for YZERO)"
    # With YOFF=50, ADC=50 must decode to exactly 0 V
    adc = np.array([50.0])
    v = (adc - p.y_off) * p.y_mult + p.y_zero
    assert abs(v[0]) < 1e-10, f"ADC=50 should give 0 V, got {v[0]!r} V"
    # 500 mVpp sine: ADC spans roughly [19, 81]; voltages ≈ ±0.248 V
    adc_range = np.array([19.0, 81.0])
    v_range = (adc_range - p.y_off) * p.y_mult + p.y_zero
    assert v_range[0] == pytest.approx(-0.248, abs=0.01)
    assert v_range[1] == pytest.approx( 0.248, abs=0.01)


# ── WFMPre? header-on (KEY value) — fallback format ────────────────────────────

def test_parse_header_on_wfmpre():
    response = (
        "BYT_NR 1;BIT_NR 8;ENCDG RIBINARY;BN_FMT RI;BYT_OR MSB;"
        "NR_PT 2500;WFID \"Ch1\";PT_FMT Y;XINCR 4.000E-8;PT_OFF 0;"
        "XZERO -5.000E-5;XUNIT \"s\";YMULT 4.000E-2;YOFF 0.000E+0;"
        "YZERO 0.000E+0;YUNIT \"V\""
    )
    p = WaveformPreamble.from_response(response)
    assert p.n_points == 2500
    assert p.x_incr == pytest.approx(4e-8)
    assert p.y_mult == pytest.approx(0.04)
    assert p.y_unit == "V"


# ── from_preamble_and_samples (primary path, query_binary_values) ──────────────

def test_decode_samples_scaling():
    p = _make_preamble(y_mult=0.04, y_off=0.0, y_zero=0.0)
    rec = WaveformRecord.from_preamble_and_samples(
        Channel.CH1, p, np.array([0, 100, -50], dtype=np.int8)
    )
    np.testing.assert_array_almost_equal(rec.v, [0.0, 4.0, -2.0])


def test_decode_samples_with_offset_and_zero():
    # v = (adc - yoff)*ymult + yzero
    p = _make_preamble(y_mult=0.1, y_off=25.0, y_zero=-1.0)
    rec = WaveformRecord.from_preamble_and_samples(Channel.CH1, p, [50])
    assert rec.v[0] == pytest.approx(1.5)


def test_decode_samples_time_axis():
    p = _make_preamble(x_incr=1e-6, x_zero=-1e-6)
    rec = WaveformRecord.from_preamble_and_samples(Channel.CH1, p, [0, 0, 0])
    np.testing.assert_array_almost_equal(rec.t, [-1e-6, 0.0, 1e-6])


# ── from_preamble_and_raw (fallback, raw block) ────────────────────────────────

def test_decode_raw_block_8bit():
    p = _make_preamble(y_mult=0.04, y_off=0.0, y_zero=0.0)
    block = _make_block(struct.pack("3b", 0, 100, -50))
    rec = WaveformRecord.from_preamble_and_raw(Channel.CH1, p, block)
    np.testing.assert_array_almost_equal(rec.v, [0.0, 4.0, -2.0])


def test_decode_raw_negative():
    p = _make_preamble(y_mult=0.04)
    block = _make_block(struct.pack("b", -50))
    rec = WaveformRecord.from_preamble_and_raw(Channel.CH1, p, block)
    assert rec.v[0] == pytest.approx(-2.0)


def test_decode_channel_label_preserved():
    p = _make_preamble()
    rec = WaveformRecord.from_preamble_and_raw(
        Channel.CH3, p, _make_block(struct.pack("b", 0))
    )
    assert rec.channel == Channel.CH3


# ── Derived properties ─────────────────────────────────────────────────────────

def test_v_pkpk():
    p = _make_preamble(y_mult=1.0)
    rec = WaveformRecord.from_preamble_and_samples(Channel.CH1, p, [-50, 0, 50, 25])
    assert rec.v_pkpk == pytest.approx(100.0)


def test_v_mean():
    p = _make_preamble(y_mult=1.0)
    rec = WaveformRecord.from_preamble_and_samples(Channel.CH1, p, [0, 10, -10, 0])
    assert rec.v_mean == pytest.approx(0.0)


def test_empty_waveform_properties_are_nan():
    p = _make_preamble(n_points=0)
    rec = WaveformRecord.from_preamble_and_samples(Channel.CH1, p, [])
    assert rec.n_points == 0
    assert np.isnan(rec.v_rms)
    assert np.isnan(rec.v_pkpk)


# ── ASCII decode ───────────────────────────────────────────────────────────────

def test_decode_ascii():
    p = _make_preamble(y_mult=1.0)
    rec = WaveformRecord.from_preamble_and_ascii(Channel.CH1, p, "1,2,3")
    np.testing.assert_array_almost_equal(rec.v, [1.0, 2.0, 3.0])


def test_decode_ascii_empty():
    p = _make_preamble(y_mult=1.0)
    rec = WaveformRecord.from_preamble_and_ascii(Channel.CH1, p, "")
    assert rec.n_points == 0
