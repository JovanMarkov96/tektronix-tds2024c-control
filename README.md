# tektronix-tds2024c-control

Python driver and real-time GUI for the **Tektronix TDS2024C** Digital Storage
Oscilloscope (TDS2000B family, 4-channel, 200 MHz).

## Supported Models

| Model | Channels | Bandwidth | Interface |
|---|---|---|---|
| TDS2024C | 4 | 200 MHz | USB (USBTMC) |
| TDS2014C | 4 | 100 MHz | USB (USBTMC) |
| TDS2004C | 4 | 70 MHz | USB (USBTMC) |

The TDS2000B series communicates via **USB only** (no RS-232, no GPIB without
the optional TEK-USB-488 adapter).  This driver uses pyvisa with the USBTMC
transport (USB488 subclass).

## Installation

```bash
pip install pyvisa pyvisa-py numpy
# For GUI:
pip install qtpy pyqtgraph PyQt5
# Or from this repo:
pip install -e ".[gui]"
```

**USB driver (Windows)**: Install
[Zadig](https://zadig.akeo.ie/) and bind the TDS2024C to the **WinUSB** driver,
or install the Tektronix OpenChoice PC Communications software to use NI-VISA.

**Linux / macOS**: `pyvisa-py` with `libusb` works without additional drivers.
Ensure the user is in the `plugdev` / `usbfs` group, or add a udev rule:
```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0699", MODE="0666"
```

## Quick Start

```python
from tektronix_tds2024c import TDS2024C, find_first_tds2024c, Channel, MeasType

resource = find_first_tds2024c()          # e.g. "USB0::0x0699::0x03A6::C0XXXXX::INSTR"
with TDS2024C(resource) as osc:
    print(osc.identify())                 # TEKTRONIX,TDS 2024C,...,FV:vXX.XX

    # One acquisition (force=True returns a frame even without a trigger signal)
    osc.single_acquisition(force=True)
    rec = osc.capture_waveform(Channel.CH1)
    print(f"Vpp = {rec.v_pkpk*1e3:.1f} mV  ({rec.n_points} pts)")

    # Immediate frequency measurement on CH2
    freq = osc.measure(Channel.CH2, MeasType.FREQUENCY)
    print(f"Freq = {freq/1e6:.4f} MHz")
```

## Launch GUI

```bash
tds2024c-gui
# or
python -m tektronix_tds2024c.gui_app
```

The GUI uses **pyqtgraph** for fast real-time waveform display (sub-100 ms
refresh rates).  All four channels can be overlaid simultaneously.

## Feature Summary

| Subsystem | Features |
|---|---|
| Acquisition | Sample / Peak-detect / Average modes; single-shot; free-run |
| Vertical | Scale, coupling (AC/DC/GND), position, probe, BW limit, display |
| Horizontal | Time/div, trigger position, record length readback |
| Trigger | Edge type; source, level, slope, coupling, mode; force trigger |
| Measurement | Immediate: frequency, period, mean, Vpp, RMS, rise/fall time |
| Waveform | Binary (RIBinary) or ASCII transfer; full 2500-point record |
| Misc | AutoSet, front-panel lock/unlock, event queue drain |

## Waveform Decode

The driver captures the full 2500-point record as signed 8-bit binary
(fastest transfer) and applies the oscilloscope's scaling factors:

```
v[i] = (raw_byte[i] - YOFf) × YMUlt + YZEro
t[i] = XZEro + i × XINcr
```

The resulting `WaveformRecord` contains numpy arrays `t` and `v` in SI units
(seconds, volts) along with derived properties `v_mean`, `v_pkpk`, `v_rms`.

## Legal Notice

Tektronix® and TDS2024C® are registered trademarks of Tektronix, Inc.
This project is not affiliated with, endorsed by, or sponsored by Tektronix, Inc.

## License

MIT — see [LICENSE](LICENSE).
