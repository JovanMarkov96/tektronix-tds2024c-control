"""API surface tests — no hardware required."""

import pytest


def test_package_import():
    import tektronix_tds2024c as pkg
    assert pkg.__version__ == "0.1.0"


def test_tds2024c_class_importable():
    from tektronix_tds2024c import TDS2024C
    assert callable(TDS2024C)


def test_channel_enum_members():
    from tektronix_tds2024c import Channel
    assert Channel.CH1.value == "CH1"
    assert Channel.CH4.value == "CH4"
    assert Channel.MATH.value == "MATH"
    assert len(Channel.analog()) == 4


def test_coupling_enum():
    from tektronix_tds2024c import Coupling
    assert {c.value for c in Coupling} == {"AC", "DC", "GND"}


def test_acq_mode_enum():
    from tektronix_tds2024c import AcqMode
    values = {m.value for m in AcqMode}
    assert "SAMple" in values
    assert "AVErage" in values
    assert "PEAKdetect" in values


def test_meas_type_enum_has_frequency():
    from tektronix_tds2024c import MeasType
    assert MeasType.FREQUENCY.value == "FREQuency"


def test_meas_type_enum_has_pkpk():
    from tektronix_tds2024c import MeasType
    assert MeasType.PKPK.value == "PK2pk"


def test_wfm_encoding_enum():
    from tektronix_tds2024c import WfmEncoding
    assert WfmEncoding.RIBINARY.value == "RIBinary"
    assert WfmEncoding.ASCII.value == "ASCIi"


def test_meas_no_value_sentinel():
    from tektronix_tds2024c import MEAS_NO_VALUE
    assert abs(MEAS_NO_VALUE - 9.91e37) < 1e33


def test_error_hierarchy():
    from tektronix_tds2024c import (
        TDS2024CError,
        TDS2024CConnectionError,
        TDS2024CCommandError,
        TDS2024CTimeoutError,
        TDS2024CMeasurementError,
    )
    assert issubclass(TDS2024CConnectionError, TDS2024CError)
    assert issubclass(TDS2024CCommandError, TDS2024CError)
    assert issubclass(TDS2024CTimeoutError, TDS2024CError)
    assert issubclass(TDS2024CMeasurementError, TDS2024CError)


def test_command_error_attributes():
    from tektronix_tds2024c import TDS2024CCommandError
    e = TDS2024CCommandError(440, "Query UNTERMINATED")
    assert e.code == 440
    assert "440" in str(e)
    assert "UNTERMINATED" in str(e)


def test_discovery_functions_importable():
    from tektronix_tds2024c import (
        list_tds2024c_resources, list_tektronix_resources, find_first_tds2024c,
    )
    assert callable(list_tds2024c_resources)
    assert callable(list_tektronix_resources)
    assert callable(find_first_tds2024c)


def test_trigger_source_enum():
    from tektronix_tds2024c import TriggerSource
    values = {s.value for s in TriggerSource}
    assert {"CH1", "CH2", "CH3", "CH4", "EXT", "EXT5", "LINE"} <= values


def test_trigger_coupling_enum():
    from tektronix_tds2024c import TriggerCoupling
    values = {c.value for c in TriggerCoupling}
    assert {"AC", "DC", "HFRej", "LFRej", "NOISErej"} <= values


def test_waveform_record_importable():
    from tektronix_tds2024c import WaveformRecord, WaveformPreamble
    assert WaveformRecord is not None
    assert WaveformPreamble is not None


def test_tds2024c_has_required_methods():
    from tektronix_tds2024c import TDS2024C
    required = [
        "connect", "disconnect", "identify", "reset", "clear_status", "self_test",
        "set_acq_mode", "get_acq_mode", "acq_run", "acq_stop", "acq_single",
        "wait_acq_complete", "set_channel_scale", "get_channel_scale",
        "set_channel_coupling", "get_channel_coupling", "set_channel_display",
        "get_channel_display", "set_time_scale", "get_time_scale",
        "set_trigger_level", "get_trigger_level", "set_trigger_source",
        "get_trigger_source", "set_trigger_slope", "get_trigger_slope",
        "force_trigger", "get_trigger_state", "set_immed_source", "set_immed_type",
        "get_immed_value", "measure", "capture_waveform",
        "capture_displayed_channels", "autoset", "lock_front_panel",
        "unlock_front_panel", "drain_event_queue", "is_running", "is_busy",
        "get_trigger_coupling", "set_trigger_coupling", "get_acq_stopafter",
    ]
    for name in required:
        assert hasattr(TDS2024C, name), f"TDS2024C missing method: {name}"


def test_scpi_enum_parses_uppercase_device_responses():
    """The device returns uppercase full words; constructors must accept them."""
    from tektronix_tds2024c import (
        AcqMode, TriggerSlope, TriggerMode, AcqStopAfter, MeasType,
        TriggerSource, TriggerCoupling,
    )
    assert AcqMode("SAMPLE") is AcqMode.SAMPLE
    assert AcqMode("PEAKDETECT") is AcqMode.PEAK
    assert AcqMode("AVERAGE") is AcqMode.AVERAGE
    assert TriggerSlope("RISE") is TriggerSlope.RISE
    assert TriggerSlope("FALL") is TriggerSlope.FALL
    assert TriggerMode("NORMAL") is TriggerMode.NORMAL
    assert AcqStopAfter("RUNSTOP") is AcqStopAfter.RUNSTOP
    assert AcqStopAfter("SEQUENCE") is AcqStopAfter.SEQUENCE
    assert MeasType("PK2PK") is MeasType.PKPK
    assert MeasType("FREQUENCY") is MeasType.FREQUENCY
    assert TriggerSource("LINE") is TriggerSource.LINE
    assert TriggerCoupling("NOISEREJ") is TriggerCoupling.NOISE_REJ


def test_scpi_enum_parses_short_form_and_quotes():
    from tektronix_tds2024c import AcqMode, MeasType
    assert AcqMode("SAM") is AcqMode.SAMPLE          # SCPI short form
    assert MeasType('"FREQ"') is MeasType.FREQUENCY  # quoted + short


def test_scpi_enum_rejects_garbage():
    from tektronix_tds2024c import AcqMode
    import pytest as _pytest
    with _pytest.raises(ValueError):
        AcqMode("NOTAMODE")
