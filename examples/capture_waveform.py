"""Example: capture a single-shot waveform from CH1 and print statistics."""

from tektronix_tds2024c import (
    TDS2024C, find_first_tds2024c,
    Channel, Coupling, AcqMode, TriggerSource, WfmEncoding,
)

resource = find_first_tds2024c()
if resource is None:
    print("No Tektronix scope found.")
    raise SystemExit(1)

with TDS2024C(resource) as osc:
    # Configure CH1: 500 mV/div, DC coupled, 1× probe
    osc.set_channel_scale(Channel.CH1, 0.5)
    osc.set_channel_coupling(Channel.CH1, Coupling.DC)
    osc.set_channel_probe(Channel.CH1, 1.0)
    osc.set_channel_display(Channel.CH1, True)

    # 100 µs/div time base, trigger on CH1 rising edge at 0 V
    osc.set_time_scale(100e-6)
    osc.set_trigger_source(TriggerSource.CH1)
    osc.set_trigger_level(0.0)

    # One acquisition; force=True returns a frame even with no trigger signal.
    osc.set_acq_mode(AcqMode.SAMPLE)
    osc.single_acquisition(force=True, timeout_s=5.0)

    # Capture waveform (binary, fastest)
    rec = osc.capture_waveform(Channel.CH1, encoding=WfmEncoding.RIBINARY)

print(f"Points   : {rec.n_points}")
print(f"dt       : {rec.dt:.3e} s")
print(f"V mean   : {rec.v_mean*1e3:.2f} mV")
print(f"V pk-pk  : {rec.v_pkpk*1e3:.2f} mV")
print(f"V rms    : {rec.v_rms*1e3:.2f} mV")
print(f"t range  : {rec.t[0]:.3e} .. {rec.t[-1]:.3e} s")
