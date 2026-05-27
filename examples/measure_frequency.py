"""Example: continuously poll an immediate frequency measurement on CH2."""

import time
from tektronix_tds2024c import (
    TDS2024C, find_first_tds2024c,
    Channel, Coupling, MeasType, TDS2024CMeasurementError,
)

resource = find_first_tds2024c()
if resource is None:
    print("No Tektronix scope found.")
    raise SystemExit(1)

POLL_INTERVAL = 1.0   # seconds between measurements
N_SAMPLES     = 20

with TDS2024C(resource) as osc:
    osc.set_channel_coupling(Channel.CH2, Coupling.AC)
    osc.set_channel_display(Channel.CH2, True)
    osc.acq_run()

    print(f"{'Time (s)':>10}  {'Frequency (MHz)':>18}")
    print("-" * 32)

    t0 = time.time()
    for _ in range(N_SAMPLES):
        try:
            freq_hz = osc.measure(Channel.CH2, MeasType.FREQUENCY)
            print(f"{time.time() - t0:10.1f}  {freq_hz / 1e6:18.4f}")
        except TDS2024CMeasurementError:
            print(f"{time.time() - t0:10.1f}  {'(no valid signal)':>18}")
        time.sleep(POLL_INTERVAL)
