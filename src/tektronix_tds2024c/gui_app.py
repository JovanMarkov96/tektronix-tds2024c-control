"""Standalone GUI for the Tektronix TDS2024C oscilloscope.

Uses qtpy (PyQt5/PyQt6) + pyqtgraph for fast real-time waveform display.
All VISA I/O runs in a background QThread; the main thread only renders.

Launch:
    python -m tektronix_tds2024c.gui_app
    # or
    tds2024c-gui
"""

from __future__ import annotations

import math
import queue
import time
from typing import Optional

import numpy as np

try:
    import pyqtgraph as pg
    from qtpy.QtCore import QThread, QTimer, Signal, Qt
    from qtpy.QtGui import QColor, QFont
    from qtpy.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False

from .discovery import list_tds2024c_resources
from .errors import TDS2024CConnectionError, TDS2024CMeasurementError
from .instrument import TDS2024C
from .models import (
    AcqMode,
    BandwidthLimit,
    Channel,
    Coupling,
    MeasType,
    TriggerCoupling,
    TriggerMode,
    TriggerSlope,
    TriggerSource,
    TriggerType,
    WfmEncoding,
)
from .waveform import WaveformRecord

# ── Colour palette ─────────────────────────────────────────────────────────────
_CH_COLOURS = ["#FFD700", "#00BFFF", "#FF6B6B", "#98FB98"]   # CH1–CH4: gold, sky, red, green
_CH_IDX = {"CH1": 0, "CH2": 1, "CH3": 2, "CH4": 3}          # source-string → colour index

# ── Trigger-state display (module-level constants, not rebuilt on every call) ──
_TRIG_STATE_COLOURS = {
    "ARMED":   "#FFA500",
    "AUTO":    "#4FC3F7",
    "READY":   "#66BB6A",
    "SAVE":    "#CE93D8",
    "TRIGGER": "#FFD700",
}
_TRIG_STATE_LABELS = {
    "ARMED": "ARMED", "AUTO": "AUTO", "READY": "READY",
    "SAVE": "SAVE", "TRIGGER": "TRIG'D",
}

# ── Standard V/div values ─────────────────────────────────────────────────────
_V_DIV_OPTIONS = [0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0]
_V_DIV_LABELS  = ["2mV", "5mV", "10mV", "20mV", "50mV",
                   "100mV", "200mV", "500mV", "1V", "2V", "5V"]
# Pre-built lookup: value → index (avoids linear scan on every settings poll)
_V_DIV_INDEX = {v: i for i, v in enumerate(_V_DIV_OPTIONS)}

# ── Standard time/div values ──────────────────────────────────────────────────
_T_DIV_OPTIONS = [
    5e-9, 10e-9, 25e-9, 50e-9, 100e-9, 250e-9, 500e-9,
    1e-6, 2.5e-6, 5e-6, 10e-6, 25e-6, 50e-6, 100e-6, 250e-6, 500e-6,
    1e-3, 2.5e-3, 5e-3, 10e-3, 25e-3, 50e-3, 100e-3, 250e-3, 500e-3,
    1.0, 2.5, 5.0, 10.0, 25.0, 50.0,
]
_T_DIV_LABELS = [
    "5ns","10ns","25ns","50ns","100ns","250ns","500ns",
    "1µs","2.5µs","5µs","10µs","25µs","50µs","100µs","250µs","500µs",
    "1ms","2.5ms","5ms","10ms","25ms","50ms","100ms","250ms","500ms",
    "1s","2.5s","5s","10s","25s","50s",
]
_T_DIV_INDEX = {v: i for i, v in enumerate(_T_DIV_OPTIONS)}

# ── Trigger coupling ───────────────────────────────────────────────────────────
_TRIG_COUP_DISPLAY = ["DC", "AC", "HFRej", "LFRej", "NoiseRej"]
_TRIG_COUP_ENUM    = [
    TriggerCoupling.DC, TriggerCoupling.AC,
    TriggerCoupling.HF_REJ, TriggerCoupling.LF_REJ, TriggerCoupling.NOISE_REJ,
]
_TRIG_COUP_BY_LABEL = dict(zip(_TRIG_COUP_DISPLAY, _TRIG_COUP_ENUM))  # display → enum
_TRIG_COUP_FROM_SCPI = {                                               # SCPI upper → display
    "DC": "DC", "AC": "AC",
    "HFREJ": "HFRej", "LFREJ": "LFRej", "NOISEREJ": "NoiseRej",
}

# ── Acquisition mode ───────────────────────────────────────────────────────────
_ACQ_MODE_DISPLAY = ["Sample", "Peak", "Average"]
_ACQ_MODE_ENUM    = [AcqMode.SAMPLE, AcqMode.PEAK, AcqMode.AVERAGE]

# ── Probe attenuation ─────────────────────────────────────────────────────────
_PROBE_LABELS  = ["1×", "10×", "100×", "1000×"]
_PROBE_FACTORS = [1.0, 10.0, 100.0, 1000.0]


def _eng_v(v_per_div: float) -> str:
    """Format V/div with engineering prefix, always includes '/div'."""
    abs_v = abs(v_per_div)
    if abs_v == 0:
        return "0 V/div"
    if abs_v >= 1.0:
        return f"{v_per_div:.4g} V/div"
    if abs_v >= 1e-3:
        return f"{v_per_div*1e3:.4g} mV/div"
    return f"{v_per_div*1e6:.4g} µV/div"


def _eng_t(s_per_div: float) -> str:
    """Format time/div with engineering prefix."""
    abs_v = abs(s_per_div)
    if abs_v == 0:
        return "0 s/div"
    if abs_v >= 1.0:
        return f"{s_per_div:.4g} s/div"
    if abs_v >= 1e-3:
        return f"{s_per_div*1e3:.4g} ms/div"
    if abs_v >= 1e-6:
        return f"{s_per_div*1e6:.4g} µs/div"
    if abs_v >= 1e-9:
        return f"{s_per_div*1e9:.4g} ns/div"
    return f"{s_per_div:.3g} s/div"


def _closest_index(options: list, value: float) -> int:
    """Return the index in *options* whose value is closest to *value*."""
    return min(range(len(options)), key=lambda i: abs(options[i] - value))


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread
# ─────────────────────────────────────────────────────────────────────────────

class _OscWorker(QThread):
    """Background thread that owns the VISA session exclusively."""

    connected_signal    = Signal(str)
    disconnected_signal = Signal()
    waveform_signal     = Signal(object)           # dict[Channel, WaveformRecord]
    measurement_signal  = Signal(float, str, str)  # value, units, type_name
    settings_signal     = Signal(dict)             # scope settings snapshot (no trig_state)
    log_signal          = Signal(str)
    trig_state_signal   = Signal(str)              # separate — high-frequency badge updates

    def __init__(self, parent=None):
        super().__init__(parent)
        self._osc: Optional[TDS2024C] = None
        self._cmd_queue: queue.Queue = queue.Queue()
        self._running = False
        self._free_run = False
        self._free_run_channels: list[Channel] = [Channel.CH1]
        self._free_run_interval_ms = 100
        self._resource = ""
        # Bidirectional sync
        self._state_poll_interval_ms = 750   # idle polling rate
        self._last_settings_poll = 0.0
        self._last_trig_poll = 0.0
        self._last_emitted_state: dict = {}
        self._last_trig_state = ""
        # Preamble refresh flag: set True when free-run starts so the first
        # capture re-reads WFMPre? for all channels (picks up any front-panel
        # V/div / time-base changes made while the scope was idle).
        self._free_run_needs_preamble_refresh = False

    # ── Public API (called from GUI thread) ────────────────────────────────────

    def cmd_connect(self, resource: str) -> None:
        self._resource = resource
        self._enqueue("__connect__", self._do_connect)

    def cmd_disconnect(self) -> None:
        self._enqueue("__disconnect__", self._do_disconnect)

    def cmd_single_shot(self, channels: list[Channel]) -> None:
        def _do():
            assert self._osc
            self._osc.single_acquisition(force=True, timeout_s=10.0)
            records = {}
            for ch in channels:
                try:
                    # Use read_waveform (not capture_waveform) so that
                    # prepare_waveform_transfer is NOT called again — calling
                    # it would invalidate the entire preamble cache and cause
                    # the next free-run frame to stall for N×~1 s re-fetching
                    # WFMPre? for every channel.  The transfer format was
                    # already configured once in _do_connect.
                    records[ch] = self._osc.read_waveform(ch)
                except Exception as e:
                    self.log_signal.emit(f"Capture {ch.value} failed: {e}")
            if records:
                self.waveform_signal.emit(records)
        self._enqueue("single_shot", _do)

    def cmd_set_free_run(self, enabled: bool, channels: list[Channel],
                         interval_ms: int) -> None:
        # Set _free_run last so the worker never sees enabled=True with
        # the old channel list (avoids a benign CPython GIL-window race).
        was_running = self._free_run
        self._free_run_channels = channels
        self._free_run_interval_ms = interval_ms
        self._free_run = enabled

        if enabled and not was_running:
            # Starting free-run: force a preamble refresh on the first capture
            # so any V/div / timebase changes made from the scope front panel
            # while idle are reflected immediately from frame one.
            self._free_run_needs_preamble_refresh = True

        if not enabled and was_running:
            # Stopping free-run: reset poll timer so the full settings snapshot
            # fires on the very next idle loop iteration (immediate GUI sync).
            self._last_settings_poll = 0.0

    def cmd_measure(self, ch: Channel, mtype: MeasType) -> None:
        def _do():
            assert self._osc
            try:
                val = self._osc.measure(ch, mtype)
                units = self._osc.get_immed_units()
                self.measurement_signal.emit(val, units, mtype.value)
            except TDS2024CMeasurementError:
                self.measurement_signal.emit(float("nan"), "", mtype.value)
        self._enqueue("measure", _do)

    def cmd_autoset(self) -> None:
        def _do():
            assert self._osc
            self._osc.autoset()
            self._emit_settings_snapshot()
        self._enqueue("autoset", _do)

    def cmd_set_channel_scale(self, ch: Channel, v_per_div: float) -> None:
        def _do():
            assert self._osc
            self._osc.set_channel_scale(ch, v_per_div)
        self._enqueue(f"ch_scale_{ch.value}", _do)

    def cmd_set_channel_coupling(self, ch: Channel, coupling: Coupling) -> None:
        def _do():
            assert self._osc
            self._osc.set_channel_coupling(ch, coupling)
        self._enqueue(f"ch_coupling_{ch.value}", _do)

    def cmd_set_channel_display(self, ch: Channel, on: bool) -> None:
        def _do():
            assert self._osc
            self._osc.set_channel_display(ch, on)
        self._enqueue(f"ch_display_{ch.value}", _do)

    def cmd_set_time_scale(self, s_per_div: float) -> None:
        def _do():
            assert self._osc
            self._osc.set_time_scale(s_per_div)
        self._enqueue("time_scale", _do)

    def cmd_set_trigger_level(self, volts: float) -> None:
        def _do():
            assert self._osc
            self._osc.set_trigger_level(volts)
        self._enqueue("trig_level", _do)

    def cmd_set_trigger_source(self, source: TriggerSource) -> None:
        def _do():
            assert self._osc
            self._osc.set_trigger_source(source)
        self._enqueue("trig_source", _do)

    def cmd_set_trigger_slope(self, slope: TriggerSlope) -> None:
        def _do():
            assert self._osc
            self._osc.set_trigger_slope(slope)
        self._enqueue("trig_slope", _do)

    def cmd_set_trigger_mode(self, mode: TriggerMode) -> None:
        def _do():
            assert self._osc
            self._osc.set_trigger_mode(mode)
        self._enqueue("trig_mode", _do)

    def cmd_set_trigger_coupling(self, coupling: TriggerCoupling) -> None:
        def _do():
            assert self._osc
            self._osc.set_trigger_coupling(coupling)
        self._enqueue("trig_coupling", _do)

    def cmd_set_acq_mode(self, mode: AcqMode, numavg: int) -> None:
        def _do():
            assert self._osc
            self._osc.set_acq_mode(mode)
            if mode == AcqMode.AVERAGE:
                self._osc.set_acq_numavg(numavg)
        self._enqueue("acq_mode", _do)

    def cmd_trigger_to_50pct(self) -> None:
        def _do():
            assert self._osc
            self._osc.set_trigger_to_50pct()
        self._enqueue("trig_50pct", _do)

    def cmd_force_trigger(self) -> None:
        def _do():
            assert self._osc
            self._osc.force_trigger()
        self._enqueue("force_trigger", _do)

    def cmd_set_channel_position(self, ch: Channel, divs: float) -> None:
        def _do():
            assert self._osc
            self._osc.set_channel_position(ch, divs)
        self._enqueue(f"ch_position_{ch.value}", _do)

    def cmd_set_channel_probe(self, ch: Channel, factor: float) -> None:
        def _do():
            assert self._osc
            self._osc.set_channel_probe(ch, factor)
        self._enqueue(f"ch_probe_{ch.value}", _do)

    def cmd_set_channel_bwlimit(self, ch: Channel, limited: bool) -> None:
        def _do():
            assert self._osc
            from .models import BandwidthLimit
            self._osc.set_channel_bw_limit(
                ch, BandwidthLimit.TWENTY_MHZ if limited else BandwidthLimit.FULL
            )
        self._enqueue(f"ch_bwlimit_{ch.value}", _do)

    # ── QThread entry point ────────────────────────────────────────────────────

    def run(self) -> None:
        """Main worker loop.

        Two separate poll schedules:

        *Trigger-state badge* (trig_state_signal):
          - During free-run: every ~500 ms (single VISA query, minimal overhead)
          - During idle:     covered by the full settings poll below

        *Full settings poll* (settings_signal):
          - During free-run: every ~3 s  ← avoids the ~600–1200 ms VISA block
                                           that 20+ queries would cause if fired
                                           at 750 ms while captures are running
          - During idle:     every 750 ms (fast device→GUI sync when scope is static)

        ``trig_state`` is *excluded* from the settings comparison so that a
        cycling trigger state (ARMED → TRIGGER → AUTO → …) does not defeat the
        "emit only when something changed" guard and spam _on_settings every tick.
        """
        self._running = True
        last_capture = 0.0
        while self._running:
            self._drain_queue()

            if self._osc:
                now = time.monotonic()

                # ── Waveform capture ──────────────────────────────────────────
                if self._free_run:
                    if now - last_capture >= self._free_run_interval_ms / 1000.0:
                        last_capture = now
                        self._do_free_run_capture()

                # ── Trigger-state badge (lightweight, ~500 ms during free-run) ─
                if self._free_run and now - self._last_trig_poll >= 0.5:
                    self._last_trig_poll = now
                    try:
                        state = self._osc.get_trigger_state()
                        if state != self._last_trig_state:
                            self._last_trig_state = state
                            self.trig_state_signal.emit(state)
                    except Exception:
                        pass

                # ── Full settings poll (idle only) ────────────────────────────
                # The full snapshot sends ~23 VISA queries and takes ~1 s on
                # the TDS2024C.  Running it during free-run would block capture
                # for 1 s every few seconds — unacceptable.  Instead:
                #
                #   • During FREE-RUN: poll is suppressed entirely.  The
                #     trig-state badge above covers the only fast-changing value.
                #     When the user stops free-run, cmd_set_free_run resets
                #     _last_settings_poll to 0 so the sync fires immediately.
                #
                #   • During IDLE: poll every 750 ms for fast device→GUI sync.
                if not self._free_run:
                    if now - self._last_settings_poll >= self._state_poll_interval_ms / 1000.0:
                        self._last_settings_poll = now
                        try:
                            snap, trig_state = self._build_state_snapshot()
                            if snap != self._last_emitted_state:
                                self._last_emitted_state = snap.copy()
                                self.settings_signal.emit(snap)
                            if trig_state and trig_state != self._last_trig_state:
                                self._last_trig_state = trig_state
                                self.trig_state_signal.emit(trig_state)
                        except Exception:
                            pass

            self.msleep(5)

    def stop(self) -> None:
        self._running = False
        self._enqueue("__disconnect__", self._do_disconnect)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _enqueue(self, label: str, fn) -> None:
        self._cmd_queue.put((label, fn))

    def _drain_queue(self) -> None:
        while not self._cmd_queue.empty():
            try:
                label, fn = self._cmd_queue.get_nowait()
                is_mgmt = label.startswith("__")
                if self._osc is None and not is_mgmt:
                    self.log_signal.emit(f"SKIP {label} — not connected")
                    continue
                try:
                    fn()
                    if not is_mgmt:
                        self.log_signal.emit(f"OK: {label}")
                except Exception as exc:
                    self.log_signal.emit(f"ERR: {label} → {exc}")
            except Exception:
                pass

    def _do_connect(self) -> None:
        resource = self._resource
        if not resource:
            found = list_tds2024c_resources()
            if not found:
                self.log_signal.emit("No TDS2024C USB device found")
                return
            resource = found[0]
            self._resource = resource
        try:
            if self._osc is not None:
                try:
                    self._osc.disconnect()
                except Exception:
                    pass
            self._osc = TDS2024C(resource)
            self._osc.connect()
            idn = self._osc.identify()
            # Configure the static waveform-transfer parameters once.
            # After this, live capture only needs DATa:SOUrce + WFMPre? (cached)
            # + CURVe? per frame.  Never call prepare_waveform_transfer again
            # during normal operation — doing so invalidates the preamble cache.
            self._osc.prepare_waveform_transfer()
            self.connected_signal.emit(idn)
            self.log_signal.emit(f"Connected: {resource}")
            self._emit_settings_snapshot()
        except Exception as exc:
            self._osc = None
            self.log_signal.emit(f"Connection failed: {exc}")
            self.disconnected_signal.emit()

    def _do_disconnect(self) -> None:
        if self._osc is not None:
            try:
                self._osc.unlock_front_panel()
                self._osc.disconnect()
            except Exception:
                pass
            self._osc = None
        self.disconnected_signal.emit()
        self.log_signal.emit("Disconnected")

    def _do_free_run_capture(self) -> None:
        # Consume the one-shot preamble-refresh flag.  True only on the first
        # frame after free-run starts, ensuring V/div / timebase changes made
        # from the scope front panel while idle are picked up immediately.
        refresh = self._free_run_needs_preamble_refresh
        self._free_run_needs_preamble_refresh = False

        records = {}
        for ch in self._free_run_channels:
            try:
                records[ch] = self._osc.read_waveform(ch, refresh_preamble=refresh)
            except Exception:
                pass
        if records:
            self.waveform_signal.emit(records)

    def _build_state_snapshot(self) -> tuple[dict, str]:
        """Query scope settings and return (settings_dict, trig_state_str).

        ``trig_state`` is returned *separately* so it can be excluded from the
        settings equality check — a cycling trigger state would otherwise defeat
        the "emit only when something changed" guard and call _on_settings every
        poll tick.
        """
        osc = self._osc
        snap: dict = {}
        snap["time_scale"] = osc.get_time_scale()
        for ch in Channel.analog():
            try:
                snap[f"{ch.value}_scale"]    = osc.get_channel_scale(ch)
                snap[f"{ch.value}_position"] = osc.get_channel_position(ch)
                snap[f"{ch.value}_coupling"] = osc.get_channel_coupling(ch).value
                snap[f"{ch.value}_display"]  = osc.get_channel_display(ch)
                snap[f"{ch.value}_probe"]    = osc.get_channel_probe(ch)
                snap[f"{ch.value}_bwlimit"]  = (osc.get_channel_bw_limit(ch) == BandwidthLimit.TWENTY_MHZ)
            except Exception:
                pass
        snap["trig_level"]  = osc.get_trigger_level()
        snap["trig_source"] = osc.get_trigger_source().value
        snap["trig_slope"]  = osc.get_trigger_slope().value
        try:
            snap["trig_mode"] = osc.get_trigger_mode().value
        except Exception:
            pass
        try:
            snap["trig_coupling"] = osc.get_trigger_coupling().value
        except Exception:
            pass
        trig_state = ""
        try:
            trig_state = osc.get_trigger_state()
        except Exception:
            pass
        return snap, trig_state

    def _emit_settings_snapshot(self) -> None:
        """Called once on connect / after autoset.  Primes the dedup cache."""
        if self._osc is None:
            return
        try:
            snap, trig_state = self._build_state_snapshot()
            self._last_emitted_state = snap.copy()
            # Stamp the poll clock so the idle loop does not immediately fire
            # another full settings query right after connect/autoset.
            self._last_settings_poll = time.monotonic()
            self.settings_signal.emit(snap)
            if trig_state:
                self._last_trig_state = trig_state
                self.trig_state_signal.emit(trig_state)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

class TDS2024CGUI(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tektronix TDS2024C")
        self.resize(1200, 750)

        self._worker = _OscWorker()
        self._worker.connected_signal.connect(self._on_connected)
        self._worker.disconnected_signal.connect(self._on_disconnected)
        self._worker.waveform_signal.connect(self._on_waveform)
        self._worker.measurement_signal.connect(self._on_measurement)
        self._worker.settings_signal.connect(self._on_settings)
        self._worker.log_signal.connect(self._on_log)
        self._worker.trig_state_signal.connect(self._on_trig_state)
        self._worker.start()

        self._plot_curves: dict[Channel, pg.PlotDataItem] = {}
        self._ground_lines: dict[Channel, pg.InfiniteLine] = {}
        self._trig_line: Optional[pg.InfiniteLine] = None
        self._vdiv_label = None    # pg.LabelItem
        self._trig_badge = None    # pg.LabelItem
        self._suppress_signals = False

        # Per-channel state for divisions-based plot (updated from _on_settings)
        self._ch_v_per_div: dict[Channel, float] = {ch: 0.5 for ch in Channel.analog()}
        self._ch_position:  dict[Channel, float] = {ch: 0.0 for ch in Channel.analog()}
        self._trig_level_v    = 0.0
        self._trig_source_str = "CH1"
        self._time_scale_s    = 100e-6

        # Auto-free-run flag: set True after auto-connect so that the first
        # settings snapshot (from _do_connect → _emit_settings_snapshot) triggers
        # free run automatically.  Cleared on first use.
        self._pending_auto_free_run = False

        self._build_ui()
        self._set_connected(False)
        self._discover()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(4)
        root.addLayout(self._build_connection_bar())

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, stretch=1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(4)
        left_layout.addWidget(self._build_channel_panel())
        left_layout.addWidget(self._build_horizontal_panel())
        left_layout.addWidget(self._build_acq_panel())
        left_layout.addWidget(self._build_trigger_panel())
        left_layout.addStretch()
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(4)
        right_layout.addWidget(self._build_plot_panel(), stretch=3)
        right_layout.addWidget(self._build_measurement_panel())
        right_layout.addWidget(self._build_log_panel())
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def _build_connection_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("Resource:"))

        self._resource_combo = QComboBox()
        self._resource_combo.setEditable(True)
        self._resource_combo.setMinimumWidth(280)
        layout.addWidget(self._resource_combo)

        btn_discover = QPushButton("Discover")
        btn_discover.clicked.connect(self._discover)
        layout.addWidget(btn_discover)

        self._btn_connect = QPushButton("Connect")
        self._btn_connect.clicked.connect(self._connect)
        layout.addWidget(self._btn_connect)

        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_disconnect.clicked.connect(self._disconnect)
        layout.addWidget(self._btn_disconnect)

        self._lbl_status = QLabel("● Disconnected")
        self._lbl_status.setStyleSheet("color: #FF6B6B; font-weight: bold;")
        layout.addWidget(self._lbl_status)

        self._lbl_idn = QLabel("")
        self._lbl_idn.setStyleSheet("color: #aaa;")
        layout.addWidget(self._lbl_idn, stretch=1)

        return layout

    def _build_channel_panel(self) -> QGroupBox:
        box = QGroupBox("Channels")
        layout = QHBoxLayout(box)
        self._ch_widgets: dict[Channel, dict] = {}

        for i, ch in enumerate(Channel.analog()):
            col = QVBoxLayout()
            col.setSpacing(2)

            lbl = QLabel(ch.value)
            lbl.setStyleSheet(f"color: {_CH_COLOURS[i]}; font-weight: bold;")
            col.addWidget(lbl)

            scale_cb = QComboBox()
            scale_cb.addItems(_V_DIV_LABELS)
            scale_cb.setCurrentIndex(7)   # 500 mV/div
            scale_cb.currentIndexChanged.connect(
                lambda idx, c=ch: self._on_ch_scale_changed(c, idx)
            )
            col.addWidget(scale_cb)

            coup_cb = QComboBox()
            coup_cb.addItems(["DC", "AC", "GND"])
            coup_cb.currentTextChanged.connect(
                lambda txt, c=ch: self._on_ch_coupling_changed(c, txt)
            )
            col.addWidget(coup_cb)

            col.addWidget(QLabel("Pos:"))
            pos_sb = QDoubleSpinBox()
            pos_sb.setRange(-4.0, 4.0)
            pos_sb.setSingleStep(0.5)
            pos_sb.setDecimals(2)
            pos_sb.setSuffix(" div")
            pos_sb.setValue(0.0)
            col.addWidget(pos_sb)
            pos_sb.valueChanged.connect(lambda v, c=ch: self._on_ch_position_changed(c, v))

            col.addWidget(QLabel("Probe:"))
            probe_cb = QComboBox()
            probe_cb.addItems(_PROBE_LABELS)
            probe_cb.setCurrentIndex(0)
            col.addWidget(probe_cb)
            probe_cb.currentTextChanged.connect(lambda t, c=ch: self._on_ch_probe_changed(c, t))

            bw_cb = QCheckBox("20M BW")
            col.addWidget(bw_cb)
            bw_cb.stateChanged.connect(lambda s, c=ch: self._on_ch_bwlimit_changed(c, s))

            # Single "On" checkbox — single source of truth for both
            # scope display (SELect:CH<n>) and free-run capture list.
            disp_cb = QCheckBox("On")
            disp_cb.setChecked(i == 0)    # CH1 on by default
            disp_cb.stateChanged.connect(
                lambda state, c=ch: self._on_ch_display_changed(c, state)
            )
            col.addWidget(disp_cb)

            self._ch_widgets[ch] = {
                "scale": scale_cb,
                "coupling": coup_cb,
                "position": pos_sb,
                "probe": probe_cb,
                "bwlimit": bw_cb,
                "display": disp_cb,
            }
            layout.addLayout(col)

        return box

    def _build_horizontal_panel(self) -> QGroupBox:
        box = QGroupBox("Horizontal")
        layout = QHBoxLayout(box)

        layout.addWidget(QLabel("Time/div:"))
        self._time_scale_cb = QComboBox()
        self._time_scale_cb.addItems(_T_DIV_LABELS)
        self._time_scale_cb.setCurrentIndex(13)   # 100 µs/div
        self._time_scale_cb.currentIndexChanged.connect(self._on_time_scale_changed)
        layout.addWidget(self._time_scale_cb)

        layout.addStretch()
        return box

    def _build_acq_panel(self) -> QGroupBox:
        box = QGroupBox("Acquisition")
        layout = QHBoxLayout(box)

        self._acq_mode_cb = QComboBox()
        self._acq_mode_cb.addItems(_ACQ_MODE_DISPLAY)
        self._acq_mode_cb.currentIndexChanged.connect(self._on_acq_mode_changed)
        layout.addWidget(self._acq_mode_cb)

        layout.addWidget(QLabel("Avg:"))
        self._avg_spin = QSpinBox()
        self._avg_spin.setRange(4, 512)
        self._avg_spin.setValue(16)
        self._avg_spin.setSingleStep(4)
        layout.addWidget(self._avg_spin)

        self._btn_autoset = QPushButton("AutoSet")
        self._btn_autoset.clicked.connect(self._autoset)
        layout.addWidget(self._btn_autoset)

        layout.addStretch()
        return box

    def _build_trigger_panel(self) -> QGroupBox:
        box = QGroupBox("Trigger")
        layout = QVBoxLayout(box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Src:"))
        self._trig_src_cb = QComboBox()
        self._trig_src_cb.addItems(["CH1", "CH2", "CH3", "CH4", "EXT", "EXT5", "LINE"])
        self._trig_src_cb.currentTextChanged.connect(self._on_trig_source_changed)
        row1.addWidget(self._trig_src_cb)

        row1.addWidget(QLabel("Level:"))
        self._trig_level_spin = QDoubleSpinBox()
        self._trig_level_spin.setRange(-50.0, 50.0)
        self._trig_level_spin.setSingleStep(0.01)
        self._trig_level_spin.setValue(0.0)
        self._trig_level_spin.setSuffix(" V")
        self._trig_level_spin.valueChanged.connect(self._on_trig_level_changed)
        row1.addWidget(self._trig_level_spin)

        row1.addWidget(QLabel("Slope:"))
        self._trig_slope_cb = QComboBox()
        self._trig_slope_cb.addItems(["Rise", "Fall"])
        self._trig_slope_cb.currentTextChanged.connect(self._on_trig_slope_changed)
        row1.addWidget(self._trig_slope_cb)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Mode:"))
        self._trig_mode_cb = QComboBox()
        self._trig_mode_cb.addItems(["Auto", "Normal"])
        self._trig_mode_cb.currentTextChanged.connect(self._on_trig_mode_changed)
        row2.addWidget(self._trig_mode_cb)

        row2.addWidget(QLabel("Coup:"))
        self._trig_coup_cb = QComboBox()
        self._trig_coup_cb.addItems(_TRIG_COUP_DISPLAY)
        self._trig_coup_cb.currentTextChanged.connect(self._on_trig_coupling_changed)
        row2.addWidget(self._trig_coup_cb)

        self._btn_set_50pct = QPushButton("Set 50%")
        self._btn_set_50pct.clicked.connect(lambda: self._worker.cmd_trigger_to_50pct())
        row2.addWidget(self._btn_set_50pct)

        self._btn_force_trig = QPushButton("Force")
        self._btn_force_trig.clicked.connect(lambda: self._worker.cmd_force_trigger())
        row2.addWidget(self._btn_force_trig)

        self._lbl_trig_state = QLabel("●")
        self._lbl_trig_state.setStyleSheet("color: gray; font-size: 18px;")
        row2.addWidget(self._lbl_trig_state)

        row2.addStretch()
        layout.addLayout(row2)
        return box

    def _build_plot_panel(self) -> QGroupBox:
        box = QGroupBox("Waveform")
        layout = QVBoxLayout(box)

        # Controls — channel selection is in the Channel panel (unified)
        ctrl = QHBoxLayout()
        self._btn_single = QPushButton("Single Shot")
        self._btn_single.clicked.connect(self._single_shot)
        ctrl.addWidget(self._btn_single)

        self._btn_free_run = QPushButton("▶ Free Run")
        self._btn_free_run.setCheckable(True)
        self._btn_free_run.toggled.connect(self._toggle_free_run)
        ctrl.addWidget(self._btn_free_run)

        ctrl.addWidget(QLabel("Interval:"))
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(20, 10000)
        self._refresh_spin.setValue(100)
        self._refresh_spin.setSuffix(" ms")
        ctrl.addWidget(self._refresh_spin)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # pyqtgraph plot — divisions-based, fixed ±4 div y-range
        pg.setConfigOptions(antialias=True, background="#1a1a2e")
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setLabel("left", "Divisions")
        self._plot_widget.setLabel("bottom", "Time", units="s")
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self._plot_widget.setYRange(-4.0, 4.0, padding=0)
        self._plot_widget.setLimits(yMin=-4.5, yMax=4.5)

        for i, ch in enumerate(Channel.analog()):
            curve = self._plot_widget.plot(
                [], [], name=ch.value,
                pen=pg.mkPen(color=_CH_COLOURS[i], width=1),
            )
            self._plot_curves[ch] = curve

        # Ground-reference lines: dashed horizontal line at pos_div per channel
        for i, ch in enumerate(Channel.analog()):
            line = pg.InfiniteLine(
                pos=0.0, angle=0,
                pen=pg.mkPen(color=_CH_COLOURS[i], width=1.5, style=Qt.DashLine),
                movable=False,
            )
            # Visibility mirrors the "On" checkbox default (CH1 on, rest off)
            line.setVisible(i == 0)
            self._plot_widget.addItem(line)
            self._ground_lines[ch] = line

        # Trigger-level line: dotted horizontal line in trigger-source colour
        self._trig_line = pg.InfiniteLine(
            pos=0.0, angle=0,
            pen=pg.mkPen(color=_CH_COLOURS[0], width=1, style=Qt.DotLine),
            movable=False,
        )
        self._plot_widget.addItem(self._trig_line)

        # V/div label strip: bottom-left corner of plot viewport.
        # Color is driven per-channel via HTML in _update_vdiv_label; we set
        # a non-empty color here only to ensure LabelItem initialises its
        # QGraphicsTextItem in the correct font size.
        self._vdiv_label = pg.LabelItem(text="", justify="left",
                                        color="#cccccc", size="8pt")
        self._vdiv_label.setParentItem(self._plot_widget.getPlotItem())
        self._vdiv_label.anchor(itemPos=(0, 1), parentPos=(0, 1), offset=(5, -5))

        # Trigger-state badge: top-right corner of plot viewport
        self._trig_badge = pg.LabelItem(text="---", justify="right",
                                        color="#4FC3F7", size="9pt")
        self._trig_badge.setParentItem(self._plot_widget.getPlotItem())
        self._trig_badge.anchor(itemPos=(1, 0), parentPos=(1, 0), offset=(-5, 5))

        layout.addWidget(self._plot_widget)

        # Initialise labels now that the panel is constructed
        self._update_vdiv_label()
        return box

    def _build_measurement_panel(self) -> QGroupBox:
        box = QGroupBox("Measurement")
        layout = QHBoxLayout(box)

        layout.addWidget(QLabel("Src:"))
        self._meas_src_cb = QComboBox()
        self._meas_src_cb.addItems(["CH1", "CH2", "CH3", "CH4"])
        layout.addWidget(self._meas_src_cb)

        layout.addWidget(QLabel("Type:"))
        self._meas_type_cb = QComboBox()
        for m in MeasType:
            self._meas_type_cb.addItem(m.name, m)
        layout.addWidget(self._meas_type_cb)

        self._btn_measure = QPushButton("Measure")
        self._btn_measure.clicked.connect(self._do_measure)
        layout.addWidget(self._btn_measure)

        self._cb_continuous = QCheckBox("Continuous")
        self._cb_continuous.toggled.connect(self._toggle_continuous_meas)
        layout.addWidget(self._cb_continuous)

        layout.addWidget(QLabel("Interval:"))
        self._meas_interval_spin = QDoubleSpinBox()
        self._meas_interval_spin.setRange(0.5, 60.0)
        self._meas_interval_spin.setValue(1.0)
        self._meas_interval_spin.setSuffix(" s")
        layout.addWidget(self._meas_interval_spin)

        self._lbl_meas_value = QLabel("---")
        self._lbl_meas_value.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #FFD700; min-width: 160px;"
        )
        layout.addWidget(self._lbl_meas_value)
        layout.addStretch()

        self._meas_timer = QTimer()
        self._meas_timer.timeout.connect(self._do_measure)
        return box

    def _build_log_panel(self) -> QGroupBox:
        box = QGroupBox("Command Log")
        layout = QHBoxLayout(box)

        self._log_box = QPlainTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setMaximumHeight(80)
        self._log_box.setStyleSheet("font-family: monospace; font-size: 10px;")
        layout.addWidget(self._log_box)

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedWidth(50)
        btn_clear.clicked.connect(self._log_box.clear)
        layout.addWidget(btn_clear, alignment=Qt.AlignTop)
        return box

    # ── Slot handlers ──────────────────────────────────────────────────────────

    def _discover(self):
        resources = list_tds2024c_resources()
        self._resource_combo.clear()
        if resources:
            self._resource_combo.addItems(resources)
            self._on_log(f"Found {len(resources)} device(s)")
            # Auto-connect if there is exactly one scope on the bus.
            # The flag triggers auto-free-run once the first settings snapshot
            # arrives (see _on_settings).
            if len(resources) == 1:
                self._on_log("Auto-connecting to single device …")
                self._pending_auto_free_run = True
                self._worker.cmd_connect(resources[0])
        else:
            self._on_log("No TDS2024C devices found on USB")

    def _connect(self):
        self._worker.cmd_connect(self._resource_combo.currentText().strip())

    def _disconnect(self):
        self._worker.cmd_disconnect()

    def _autoset(self):
        self._worker.cmd_autoset()

    def _active_channels(self) -> list[Channel]:
        """Channels whose 'On' checkbox is ticked — single source of truth."""
        return [ch for ch in Channel.analog()
                if self._ch_widgets[ch]["display"].isChecked()]

    def _single_shot(self):
        channels = self._active_channels()
        if channels:
            self._worker.cmd_single_shot(channels)

    def _toggle_free_run(self, enabled: bool):
        self._worker.cmd_set_free_run(enabled, self._active_channels(),
                                      self._refresh_spin.value())
        self._btn_free_run.setText("■ Stop" if enabled else "▶ Free Run")

    def _do_measure(self):
        ch    = Channel(self._meas_src_cb.currentText())
        mtype = self._meas_type_cb.currentData()
        self._worker.cmd_measure(ch, mtype)

    def _toggle_continuous_meas(self, enabled: bool):
        if enabled:
            self._meas_timer.start(int(self._meas_interval_spin.value() * 1000))
        else:
            self._meas_timer.stop()

    # -- Per-channel --

    def _on_ch_scale_changed(self, ch: Channel, idx: int):
        if self._suppress_signals:
            return
        v = _V_DIV_OPTIONS[idx]
        self._ch_v_per_div[ch] = v
        self._update_vdiv_label()
        self._update_trig_line()
        self._worker.cmd_set_channel_scale(ch, v)

    def _on_ch_coupling_changed(self, ch: Channel, text: str):
        if self._suppress_signals:
            return
        self._worker.cmd_set_channel_coupling(ch, Coupling(text))

    def _on_ch_display_changed(self, ch: Channel, state: int):
        if self._suppress_signals:
            return
        on = bool(state)
        self._worker.cmd_set_channel_display(ch, on)
        if ch in self._ground_lines:
            self._ground_lines[ch].setVisible(on)
        self._update_vdiv_label()
        # Keep free-run capture list in sync with the checkbox state
        if self._btn_free_run.isChecked():
            self._worker.cmd_set_free_run(True, self._active_channels(),
                                          self._refresh_spin.value())

    def _on_ch_position_changed(self, ch: Channel, value: float):
        if self._suppress_signals:
            return
        self._ch_position[ch] = value
        if ch in self._ground_lines:
            self._ground_lines[ch].setPos(value)
        self._update_trig_line()
        self._update_vdiv_label()
        self._worker.cmd_set_channel_position(ch, value)

    def _on_ch_probe_changed(self, ch: Channel, text: str):
        if self._suppress_signals:
            return
        idx = _PROBE_LABELS.index(text) if text in _PROBE_LABELS else 0
        factor = _PROBE_FACTORS[idx]
        self._worker.cmd_set_channel_probe(ch, factor)

    def _on_ch_bwlimit_changed(self, ch: Channel, state: int):
        if self._suppress_signals:
            return
        limited = bool(state)
        self._worker.cmd_set_channel_bwlimit(ch, limited)

    # -- Horizontal --

    def _on_time_scale_changed(self, idx: int):
        if self._suppress_signals:
            return
        self._time_scale_s = _T_DIV_OPTIONS[idx]
        self._update_vdiv_label()
        self._worker.cmd_set_time_scale(_T_DIV_OPTIONS[idx])

    # -- Acquisition --

    def _on_acq_mode_changed(self, idx: int):
        if self._suppress_signals:
            return
        mode = _ACQ_MODE_ENUM[idx]
        numavg = self._avg_spin.value()
        self._worker.cmd_set_acq_mode(mode, numavg)

    # -- Trigger --

    def _on_trig_source_changed(self, text: str):
        if self._suppress_signals:
            return
        self._trig_source_str = text
        self._update_trig_line_color()
        self._update_trig_line()
        ts = TriggerSource(text)   # _ScpiEnum._missing_ returns None on bad input
        if ts is not None:
            self._worker.cmd_set_trigger_source(ts)
        else:
            self._on_log(f"WARN: unknown trigger source '{text}' — ignored")

    def _on_trig_level_changed(self, value: float):
        if self._suppress_signals:
            return
        self._trig_level_v = value
        self._update_trig_line()
        self._worker.cmd_set_trigger_level(value)

    def _on_trig_slope_changed(self, text: str):
        if self._suppress_signals:
            return
        slope = TriggerSlope.RISE if text == "Rise" else TriggerSlope.FALL
        self._worker.cmd_set_trigger_slope(slope)

    def _on_trig_mode_changed(self, text: str):
        if self._suppress_signals:
            return
        mode = TriggerMode.AUTO if text == "Auto" else TriggerMode.NORMAL
        self._worker.cmd_set_trigger_mode(mode)

    def _on_trig_coupling_changed(self, text: str):
        if self._suppress_signals:
            return
        coupling = _TRIG_COUP_BY_LABEL.get(text)
        if coupling is not None:
            self._worker.cmd_set_trigger_coupling(coupling)

    # ── Worker signals → GUI ───────────────────────────────────────────────────

    def _on_connected(self, idn: str):
        self._set_connected(True)
        self._lbl_idn.setText(idn.strip())

    def _on_disconnected(self):
        self._set_connected(False)
        self._lbl_idn.setText("")

    def _on_waveform(self, data):
        if isinstance(data, WaveformRecord):
            data = {data.channel: data}
        for ch, rec in data.items():
            if ch not in self._plot_curves:
                continue
            v_per_div = self._ch_v_per_div.get(ch, 0.5)
            pos_div   = self._ch_position.get(ch, 0.0)
            y_div = rec.v / v_per_div + pos_div if v_per_div > 0 else np.zeros_like(rec.v)
            self._plot_curves[ch].setData(rec.t, y_div)

    def _on_measurement(self, value: float, units: str, type_name: str):
        if math.isnan(value):
            self._lbl_meas_value.setText("---")
            self._lbl_meas_value.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #FF6B6B;"
            )
        else:
            if "Hz" in units and value >= 1e6:
                display = f"{value/1e6:.4f} MHz"
            elif "Hz" in units and value >= 1e3:
                display = f"{value/1e3:.4f} kHz"
            elif "V" in units and abs(value) < 1.0:
                display = f"{value*1e3:.3f} mV"
            else:
                display = f"{value:.5g} {units}"
            self._lbl_meas_value.setText(display)
            self._lbl_meas_value.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #FFD700;"
            )

    def _on_settings(self, snap: dict):
        """Apply a scope-state snapshot to all widgets (device → GUI direction).

        Called from the worker's settings_signal — does NOT contain trig_state
        (that comes via trig_state_signal on its own faster schedule).
        """
        self._suppress_signals = True
        try:
            if "time_scale" in snap:
                val = snap["time_scale"]
                self._time_scale_s = val
                # Use pre-built lookup; fall back to closest match for non-standard values
                idx = _T_DIV_INDEX.get(val, _closest_index(_T_DIV_OPTIONS, val))
                self._time_scale_cb.setCurrentIndex(idx)

            for ch in Channel.analog():
                w = self._ch_widgets[ch]

                scale_key = f"{ch.value}_scale"
                if scale_key in snap:
                    val = snap[scale_key]
                    self._ch_v_per_div[ch] = val
                    idx = _V_DIV_INDEX.get(val, _closest_index(_V_DIV_OPTIONS, val))
                    w["scale"].setCurrentIndex(idx)

                pos_key = f"{ch.value}_position"
                if pos_key in snap:
                    pos = snap[pos_key]
                    self._ch_position[ch] = pos
                    w["position"].setValue(pos)
                    if ch in self._ground_lines:
                        self._ground_lines[ch].setPos(pos)

                probe_key = f"{ch.value}_probe"
                if probe_key in snap:
                    factor = snap[probe_key]
                    closest = min(range(len(_PROBE_FACTORS)), key=lambda i: abs(_PROBE_FACTORS[i] - factor))
                    w["probe"].setCurrentIndex(closest)

                bw_key = f"{ch.value}_bwlimit"
                if bw_key in snap:
                    w["bwlimit"].setChecked(snap[bw_key])

                coup_key = f"{ch.value}_coupling"
                if coup_key in snap:
                    idx = w["coupling"].findText(snap[coup_key])
                    if idx >= 0:
                        w["coupling"].setCurrentIndex(idx)

                disp_key = f"{ch.value}_display"
                if disp_key in snap:
                    on = snap[disp_key]
                    w["display"].setChecked(on)
                    if ch in self._ground_lines:
                        self._ground_lines[ch].setVisible(on)

            if "trig_level" in snap:
                self._trig_level_v = snap["trig_level"]
                self._trig_level_spin.setValue(snap["trig_level"])

            if "trig_source" in snap:
                self._trig_source_str = snap["trig_source"]
                idx = self._trig_src_cb.findText(snap["trig_source"])
                if idx >= 0:
                    self._trig_src_cb.setCurrentIndex(idx)
                self._update_trig_line_color()

            if "trig_slope" in snap:
                text = "Rise" if "RIS" in snap["trig_slope"].upper() else "Fall"
                idx = self._trig_slope_cb.findText(text)
                if idx >= 0:
                    self._trig_slope_cb.setCurrentIndex(idx)

            if "trig_mode" in snap:
                text = "Auto" if "AUTO" in snap["trig_mode"].upper() else "Normal"
                idx = self._trig_mode_cb.findText(text)
                if idx >= 0:
                    self._trig_mode_cb.setCurrentIndex(idx)

            if "trig_coupling" in snap:
                display = _TRIG_COUP_FROM_SCPI.get(
                    snap["trig_coupling"].upper(), snap["trig_coupling"]
                )
                idx = self._trig_coup_cb.findText(display)
                if idx >= 0:
                    self._trig_coup_cb.setCurrentIndex(idx)

        finally:
            self._suppress_signals = False

        # After syncing display states, refresh the worker's free-run capture
        # list.  This is necessary because setChecked() above is suppressed and
        # cannot call _on_ch_display_changed, so if a channel was toggled via
        # the scope's front-panel button the worker would keep capturing the
        # stale channel list.
        if self._btn_free_run.isChecked():
            self._worker.cmd_set_free_run(True, self._active_channels(),
                                          self._refresh_spin.value())

        # Auto-start free run on first settings snapshot after auto-connect.
        # We wait for the snapshot (rather than acting in _on_connected) so that
        # _ch_v_per_div / _ch_position are already populated before waveforms
        # start arriving, giving correct division-based scaling from frame one.
        if self._pending_auto_free_run:
            self._pending_auto_free_run = False
            self._btn_free_run.setChecked(True)   # triggers _toggle_free_run

        self._update_trig_line()
        self._update_vdiv_label()

    def _on_log(self, msg: str):
        self._log_box.appendPlainText(msg)

    def _on_trig_state(self, state: str):
        colour = _TRIG_STATE_COLOURS.get(state.upper(), "gray")
        self._lbl_trig_state.setStyleSheet(f"color: {colour}; font-size: 18px;")
        self._lbl_trig_state.setToolTip(state)
        if self._trig_badge is not None:
            label = _TRIG_STATE_LABELS.get(state.upper(), state)
            self._trig_badge.setText(label, color=colour, size="9pt")

    # ── Plot overlay helpers ───────────────────────────────────────────────────

    def _trig_source_colour(self) -> str:
        idx = _CH_IDX.get(self._trig_source_str.upper())
        return _CH_COLOURS[idx] if idx is not None else "#FFFFFF"

    def _update_trig_line_color(self):
        if self._trig_line is None:
            return
        self._trig_line.setPen(
            pg.mkPen(color=self._trig_source_colour(), width=1, style=Qt.DotLine)
        )

    def _update_trig_line(self):
        """Reposition (and show/hide) the trigger-level line in division units."""
        if self._trig_line is None:
            return
        src = self._trig_source_str.upper()
        _ch_map = {"CH1": Channel.CH1, "CH2": Channel.CH2,
                   "CH3": Channel.CH3, "CH4": Channel.CH4}
        if src in _ch_map:
            ch        = _ch_map[src]
            v_per_div = self._ch_v_per_div.get(ch, 0.5)
            pos_div   = self._ch_position.get(ch, 0.0)
            trig_div  = (self._trig_level_v / v_per_div + pos_div
                         if v_per_div > 0 else 0.0)
            self._trig_line.setPos(trig_div)
            self._trig_line.setVisible(True)
        else:
            # EXT / EXT5 / LINE — no channel voltage reference; hide the line
            self._trig_line.setVisible(False)

    def _update_vdiv_label(self):
        """Refresh per-channel V/div + time/div strip (bottom-left, colored per channel).

        Uses HTML injected directly into LabelItem.item (QGraphicsTextItem) so that
        each channel label carries its own trace colour — pyqtgraph's setText() only
        supports a single uniform color for the whole item.
        """
        if self._vdiv_label is None:
            return
        parts = []
        for i, ch in enumerate(Channel.analog()):
            if self._ch_widgets[ch]["display"].isChecked():
                colour = _CH_COLOURS[i]
                txt = f"{ch.value}: {_eng_v(self._ch_v_per_div.get(ch, 0.5))}"
                parts.append(f"<span style='color:{colour};'>{txt}</span>")
        t_txt = _eng_t(self._time_scale_s)
        parts.append(f"<span style='color:#aaaaaa;'>{t_txt}</span>")
        html = ("<span style='font-size:8pt;'>"
                + "&nbsp;&nbsp;&nbsp;".join(parts)
                + "</span>")
        self._vdiv_label.item.setHtml(html)
        # Notify the LabelItem that its content changed so it re-measures itself.
        try:
            self._vdiv_label.updateMin()
            self._vdiv_label.resizeEvent(None)
            self._vdiv_label.updateGeometry()
        except Exception:
            pass

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_connected(self, connected: bool):
        for btn in (self._btn_single, self._btn_free_run, self._btn_autoset,
                    self._btn_measure, self._btn_force_trig, self._btn_set_50pct):
            btn.setEnabled(connected)
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)
        if connected:
            self._lbl_status.setText("● Connected")
            self._lbl_status.setStyleSheet("color: #66BB6A; font-weight: bold;")
        else:
            self._lbl_status.setText("● Disconnected")
            self._lbl_status.setStyleSheet("color: #FF6B6B; font-weight: bold;")

    def closeEvent(self, event):
        self._worker.stop()
        self._worker.wait(3000)
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not _QT_AVAILABLE:
        raise ImportError(
            "GUI dependencies not installed. Run: pip install qtpy pyqtgraph PyQt5"
        )
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    win = TDS2024CGUI()
    win.show()
    sys.exit(app.exec_() if hasattr(app, "exec_") else app.exec())


if __name__ == "__main__":
    main()
