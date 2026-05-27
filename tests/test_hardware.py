"""Hardware-in-the-loop tests.

These run only when a Tektronix scope is connected via USB; otherwise the whole
module is skipped.  They are read-mostly and restore acquisition to RUN at the
end, but they DO change settings (acq mode, trigger source/coupling), so do not
run them while the instrument is mid-measurement in another application.

Run explicitly with::

    pytest tests/test_hardware.py -v
"""

import pytest

pytestmark = pytest.mark.hardware

from tektronix_tds2024c import (   # noqa: E402
    TDS2024C, find_first_tds2024c,
    Channel, Coupling, AcqMode, TriggerSource, TriggerSlope, TriggerCoupling,
    TriggerType, TriggerMode, MeasType, WfmEncoding,
)

_RESOURCE = find_first_tds2024c()

if _RESOURCE is None:
    pytest.skip("No Tektronix scope connected on USB", allow_module_level=True)


@pytest.fixture(scope="module")
def osc():
    o = TDS2024C(_RESOURCE)
    o.connect()
    yield o
    # leave the scope free-running in AUTO for the next user
    try:
        o.set_trigger_source(TriggerSource.CH1)
        o.set_trigger_mode(TriggerMode.AUTO)
        o.set_channel_coupling(Channel.CH1, Coupling.DC)
        o.acq_run()
    except Exception:
        pass
    o.disconnect()


def test_identify_is_tektronix(osc):
    idn = osc.identify()
    assert "TEKTRONIX" in idn.upper()


def test_self_test(osc):
    assert osc.self_test() is True


def test_record_length(osc):
    assert osc.get_record_length() == 2500


@pytest.mark.parametrize("mode", [AcqMode.SAMPLE, AcqMode.PEAK, AcqMode.AVERAGE])
def test_acq_mode_round_trip(osc, mode):
    osc.set_acq_mode(mode)
    assert osc.get_acq_mode() is mode


@pytest.mark.parametrize("slope", [TriggerSlope.RISE, TriggerSlope.FALL])
def test_trigger_slope_round_trip(osc, slope):
    osc.set_trigger_slope(slope)
    assert osc.get_trigger_slope() is slope


@pytest.mark.parametrize("src", [TriggerSource.CH1, TriggerSource.CH2,
                                  TriggerSource.EXT, TriggerSource.LINE])
def test_trigger_source_round_trip(osc, src):
    osc.set_trigger_source(src)
    assert osc.get_trigger_source() is src


@pytest.mark.parametrize("coup", [TriggerCoupling.AC, TriggerCoupling.DC,
                                   TriggerCoupling.HF_REJ, TriggerCoupling.LF_REJ,
                                   TriggerCoupling.NOISE_REJ])
def test_trigger_coupling_round_trip(osc, coup):
    # EDGE coupling is locked when the source is LINE — pin source to CH1 first.
    osc.set_trigger_source(TriggerSource.CH1)
    osc.set_trigger_coupling(coup)
    assert osc.get_trigger_coupling() is coup


@pytest.mark.parametrize("coup", [Coupling.AC, Coupling.DC, Coupling.GND])
def test_channel_coupling_round_trip(osc, coup):
    osc.set_channel_coupling(Channel.CH1, coup)
    assert osc.get_channel_coupling(Channel.CH1) is coup


@pytest.mark.parametrize("scale", [0.02, 0.1, 0.5, 1.0])
def test_channel_scale_round_trip(osc, scale):
    osc.set_channel_scale(Channel.CH1, scale)
    assert osc.get_channel_scale(Channel.CH1) == pytest.approx(scale, rel=0.01)


def test_trigger_type_is_edge(osc):
    osc.set_trigger_type(TriggerType.EDGE)
    assert osc.get_trigger_type() is TriggerType.EDGE


def test_capture_binary_full_record(osc):
    osc.set_channel_display(Channel.CH1, True)
    osc.set_acq_mode(AcqMode.SAMPLE)
    osc.acq_run()
    rec = osc.capture_waveform(Channel.CH1, encoding=WfmEncoding.RIBINARY)
    assert rec.n_points == 2500
    assert rec.t.shape == (2500,)
    assert rec.v.shape == (2500,)
    assert rec.dt > 0
    # voltage scaling must be finite and sane (y_mult parsed from positional WFMPre)
    assert rec.preamble.y_mult > 0
    assert rec.preamble.y_unit  # non-empty units string


def test_capture_ascii_matches_length(osc):
    rec = osc.capture_waveform(Channel.CH1, encoding=WfmEncoding.ASCII, stop=50)
    assert rec.n_points == 50


def test_binary_and_ascii_agree(osc):
    """Binary and ASCII transfers of the same record must decode identically."""
    osc.acq_stop()  # freeze the record so both reads see the same data
    try:
        rb = osc.capture_waveform(Channel.CH1, encoding=WfmEncoding.RIBINARY, stop=100)
        ra = osc.capture_waveform(Channel.CH1, encoding=WfmEncoding.ASCII, stop=100)
        import numpy as np
        np.testing.assert_array_almost_equal(rb.v, ra.v, decimal=6)
    finally:
        osc.acq_run()


def test_measure_no_signal_raises_or_returns_float(osc):
    """With no signal, frequency either errors (sentinel) or returns a float."""
    from tektronix_tds2024c import TDS2024CMeasurementError
    osc.acq_run()
    try:
        val = osc.measure(Channel.CH1, MeasType.FREQUENCY)
        assert isinstance(val, float)
    except TDS2024CMeasurementError:
        pass  # expected when input is flat/absent


def test_single_acquisition_forced_completes(osc):
    # force=True guarantees completion even with no signal connected.
    osc.single_acquisition(force=True, timeout_s=5.0)
    assert osc.is_busy() is False


def test_event_queue_drains(osc):
    osc.clear_status()
    events = osc.drain_event_queue()
    assert isinstance(events, list)
