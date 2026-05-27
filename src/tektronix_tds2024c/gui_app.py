"""Standalone GUI for the Tektronix TDS2024C oscilloscope.

Uses qtpy (PyQt5/PyQt6) + pyqtgraph for fast real-time waveform display.
All VISA I/O runs in a background QThread; the main thread only renders.

Launch:
    python -m tektronix_tds2024c.gui_app
    # or
    tds2024c-gui
"""

from __future__ import annotations

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

# ── Colour palette for 4 channels ─────────────────────────────────────────────
_CH_COLOURS = ["#FFD700", "#00BFFF", "#FF6B6B", "#98FB98"]  # gold, sky, red, green

# ── Standard V/div values ─────────────────────────────────────────────────────
_V_DIV_OPTIONS = [0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0]
_V_DIV_LABELS  = ["2mV", "5mV", "10mV", "20mV", "50mV",
                   "100mV", "200mV", "500mV", "1V", "2V", "5V"]

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

# ── Trigger-coupling display names ────────────────────────────────────────────
_TRIG_COUP_DISPLAY = ["DC", "AC", "HFRej", "LFRej", "NoiseRej"]
_TRIG_COUP_ENUM = [
    TriggerCoupling.DC, TriggerCoupling.AC,
    TriggerCoupling.HF_REJ, TriggerCoupling.LF_REJ, TriggerCoupling.NOISE_REJ,
]
# Map upper-cased SCPI response → display label
_TRIG_COUP_FROM_SCPI = {
    "DC": "DC", "AC": "AC",
    "HFREJ": "HFRej", "LFREJ": "LFRej", "NOISEREJ": "NoiseRej",
}


def _eng_v(value: float) -> str:
    """Format voltage with engineering prefix."""
    abs_v = abs(value)
    if abs_v == 0:
        return "0 V"
    if abs_v >= 1.0:
        return f"{value:.4g} V/div"
    if abs_v >= 1e-3:
        return f"{value*1e3:.4g} mV/div"
    return f"{value*1e6:.4g} µV/div"


def _eng_t(value: float) -> str:
    """Format time with engineering prefix."""
    abs_v = abs(value)
    if abs_v == 0:
        return "0 s/div"
    if abs_v >= 1.0:
        return f"{value:.4g} s/div"
    if abs_v >= 1e-3:
        return f"{value*1e3:.4g} ms/div"
    if abs_v >= 1e-6:
        return f"{value*1e6:.4g} µs/div"
    if abs_v >= 1e-9:
        return f"{value*1e9:.4g} ns/div"
    return f"{value:.3g} s/div"


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread
# ─────────────────────────────────────────────────────────────────────────────

class _OscWorker(QThread):
    """Background thread that owns the VISA session exclusively."""

    connected_signal    = Signal(str)
    disconnected_signal = Signal()
    waveform_signal     = Signal(object)           # dict[Channel, WaveformRecord]
    measurement_signal  = Signal(float, str, str)  # value, units, type_name
    settings_signal     = Signal(dict)             # scope settings snapshot
    log_signal          = Signal(str)
    trig_state_signal   = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._osc: Optional[TDS2024C] = None
        self._cmd_queue: queue.Queue = queue.Queue()
        self._running = False
        self._free_run = False
        self._free_run_channels: list[Channel] = [Channel.CH1]
        self._free_run_interval_ms = 100
        self._resource = ""
        # Bidirectional sync: poll device settings at ~1.3 Hz
        self._state_poll_interval_ms = 750
        self._last_state_poll = 0.0
        self._last_emitted_state: dict = {}

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
                    records[ch] = self._osc.capture_waveform(ch)
                except Exception as e:
                    self.log_signal.emit(f"Capture {ch.value} failed: {e}")
            self.waveform_signal.emit(records)
        self._enqueue("single_shot", _do)

    def cmd_set_free_run(self, enabled: bool, channels: list[Channel],
                         interval_ms: int) -> None:
        self._free_run = enabled
        self._free_run_channels = channels
        self._free_run_interval_ms = interval_ms

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

    def cmd_set_acq_mode(self, mode: AcqMode, numavg: int) -> None:
        def _do():
            assert self._osc
            self._osc.set_acq_mode(mode)
            if mode == AcqMode.AVERAGE:
                self._osc.set_acq_numavg(numavg)
        self._enqueue("acq_mode", _do)

    # ── QThread entry point ────────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True
        last_capture = 0.0
        while self._running:
            self._drain_queue()

            if self._osc:
                now = time.monotonic()

                if self._free_run:
                    if now - last_capture >= self._free_run_interval_ms / 1000.0:
                        last_capture = now
                        self._do_free_run_capture()

                # Device → GUI state-poll: emit only when something changed
                if now - self._last_state_poll >= self._state_poll_interval_ms / 1000.0:
                    self._last_state_poll = now
                    try:
                        snap = self._build_state_snapshot()
                        if snap != self._last_emitted_state:
                            self._last_emitted_state = snap
                            self.settings_signal.emit(snap)
                        # Trigger state always forwarded so the badge stays live
                        state = snap.get("trig_state", "")
                        if state:
                            self.trig_state_signal.emit(state)
                    except Exception:
                        pass

            self.msleep(5)

    def stop(self) -> None:
        self._running = False
        self._do_disconnect()

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
            # Set the static waveform-transfer format once; live capture then
            # only sends source + preamble + curve per frame.
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
        records = {}
        for ch in self._free_run_channels:
            try:
                records[ch] = self._osc.read_waveform(ch)  # fast path (format preset)
            except Exception:
                pass
        if records:
            self.waveform_signal.emit(records)

    def _build_state_snapshot(self) -> dict:
        """Query ~20 scope settings for the bidirectional-sync poll."""
        osc = self._osc
        snap: dict = {}
        snap["time_scale"] = osc.get_time_scale()
        for ch in Channel.analog():
            try:
                snap[f"{ch.value}_scale"]    = osc.get_channel_scale(ch)
                snap[f"{ch.value}_position"] = osc.get_channel_position(ch)
                snap[f"{ch.value}_coupling"] = osc.get_channel_coupling(ch).value
                snap[f"{ch.value}_display"]  = osc.get_channel_display(ch)
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
        try:
            snap["trig_state"] = osc.get_trigger_state()
        except Exception:
            pass
        return snap

    def _emit_settings_snapshot(self) -> None:
        if self._osc is None:
            return
        try:
            snap = self._build_state_snapshot()
            self._last_emitted_state = snap
            self.settings_signal.emit(snap)
            state = snap.get("trig_state", "")
            if state:
                self.trig_state_signal.emit(state)
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
        self._vdiv_label = None   # pg.LabelItem
        self._trig_badge = None   # pg.LabelItem
        self._suppress_signals = False

        # Per-channel state for plot scaling (updated from _on_settings)
        self._ch_v_per_div: dict[Channel, float] = {ch: 0.5 for ch in Channel.analog()}
        self._ch_position: dict[Channel, float]  = {ch: 0.0 for ch in Channel.analog()}
        self._trig_level_v   = 0.0
        self._trig_source_str = "CH1"
        self._time_scale_s   = 100e-6

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
            scale_cb.setCurrentIndex(7)  # default 500 mV/div
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

            # Single "On" checkbox: drives both scope display AND free-run capture
            disp_cb = QCheckBox("On")
            disp_cb.setChecked(i == 0)  # CH1 on by default
            disp_cb.stateChanged.connect(
                lambda state, c=ch: self._on_ch_display_changed(c, state)
            )
            col.addWidget(disp_cb)

            self._ch_widgets[ch] = {
                "scale": scale_cb,
                "coupling": coup_cb,
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
        self._time_scale_cb.setCurrentIndex(13)  # default 100 µs/div
        self._time_scale_cb.currentIndexChanged.connect(self._on_time_scale_changed)
        layout.addWidget(self._time_scale_cb)

        layout.addStretch()
        return box

    def _build_acq_panel(self) -> QGroupBox:
        box = QGroupBox("Acquisition")
        layout = QHBoxLayout(box)

        self._acq_mode_cb = QComboBox()
        self._acq_mode_cb.addItems(["Sample", "Peak", "Average"])
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

        # Plot controls — channel selection is unified in the Channel panel above
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

        # Per-channel waveform curves
        for i, ch in enumerate(Channel.analog()):
            curve = self._plot_widget.plot(
                [], [], name=ch.value,
                pen=pg.mkPen(color=_CH_COLOURS[i], width=1),
            )
            self._plot_curves[ch] = curve

        # Ground-reference lines: horizontal dashed line per channel at pos_div
        for i, ch in enumerate(Channel.analog()):
            line = pg.InfiniteLine(
                pos=0.0, angle=0,
                pen=pg.mkPen(color=_CH_COLOURS[i], width=1.5,
                             style=Qt.DashLine),
                movable=False,
            )
            line.setVisible(False)
            self._plot_widget.addItem(line)
            self._ground_lines[ch] = line

        # Trigger-level line: horizontal dotted line in trigger-source colour
        self._trig_line = pg.InfiniteLine(
            pos=0.0, angle=0,
            pen=pg.mkPen(color=_CH_COLOURS[0], width=1, style=Qt.DotLine),
            movable=False,
        )
        self._plot_widget.addItem(self._trig_line)

        # V/div label strip: bottom-left corner of the plot viewport
        self._vdiv_label = pg.LabelItem(text="", justify="left",
                                        color="#cccccc", size="8pt")
        self._vdiv_label.setParentItem(self._plot_widget.getPlotItem())
        self._vdiv_label.anchor(itemPos=(0, 1), parentPos=(0, 1),
                                offset=(5, -5))

        # Trigger-state badge: top-right corner of the plot viewport
        self._trig_badge = pg.LabelItem(text="---", justify="right",
                                        color="#4FC3F7", size="9pt")
        self._trig_badge.setParentItem(self._plot_widget.getPlotItem())
        self._trig_badge.anchor(itemPos=(1, 0), parentPos=(1, 0),
                                offset=(-5, 5))

        layout.addWidget(self._plot_widget)
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
        else:
            self._on_log("No TDS2024C devices found on USB")

    def _connect(self):
        resource = self._resource_combo.currentText().strip()
        self._worker.cmd_connect(resource)

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
        channels = self._active_channels()
        interval = self._refresh_spin.value()
        self._worker.cmd_set_free_run(enabled, channels, interval)
        self._btn_free_run.setText("■ Stop" if enabled else "▶ Free Run")

    def _do_measure(self):
        src_text = self._meas_src_cb.currentText()
        mtype    = self._meas_type_cb.currentData()
        ch       = Channel(src_text)
        self._worker.cmd_measure(ch, mtype)

    def _toggle_continuous_meas(self, enabled: bool):
        if enabled:
            interval_ms = int(self._meas_interval_spin.value() * 1000)
            self._meas_timer.start(interval_ms)
        else:
            self._meas_timer.stop()

    def _on_ch_scale_changed(self, ch: Channel, idx: int):
        if self._suppress_signals:
            return
        v_per_div = _V_DIV_OPTIONS[idx]
        self._ch_v_per_div[ch] = v_per_div
        self._update_vdiv_label()
        self._update_trig_line()
        self._worker.cmd_set_channel_scale(ch, v_per_div)

    def _on_ch_coupling_changed(self, ch: Channel, text: str):
        if self._suppress_signals:
            return
        self._worker.cmd_set_channel_coupling(ch, Coupling(text))

    def _on_ch_display_changed(self, ch: Channel, state: int):
        if self._suppress_signals:
            return
        on = bool(state)
        self._worker.cmd_set_channel_display(ch, on)
        # Sync ground-ref line visibility
        if ch in self._ground_lines:
            self._ground_lines[ch].setVisible(on)
        self._update_vdiv_label()
        # Update free-run capture list if running
        if self._btn_free_run.isChecked():
            self._worker.cmd_set_free_run(
                True, self._active_channels(), self._refresh_spin.value()
            )

    def _on_time_scale_changed(self, idx: int):
        if self._suppress_signals:
            return
        self._time_scale_s = _T_DIV_OPTIONS[idx]
        self._update_vdiv_label()
        self._worker.cmd_set_time_scale(_T_DIV_OPTIONS[idx])

    def _on_trig_source_changed(self, text: str):
        if self._suppress_signals:
            return
        self._trig_source_str = text
        self._update_trig_line_color()
        self._update_trig_line()
        try:
            self._worker.cmd_set_trigger_source(TriggerSource(text))
        except ValueError:
            pass

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
        try:
            idx = _TRIG_COUP_DISPLAY.index(text)
            self._worker.cmd_set_trigger_coupling(_TRIG_COUP_ENUM[idx])
        except (ValueError, IndexError):
            pass

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
            if v_per_div > 0:
                y_div = rec.v / v_per_div + pos_div
            else:
                y_div = np.zeros_like(rec.v)
            self._plot_curves[ch].setData(rec.t, y_div)

    def _on_measurement(self, value: float, units: str, type_name: str):
        import math
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
        """Apply a scope-state snapshot to all widgets (device → GUI direction)."""
        self._suppress_signals = True
        try:
            if "time_scale" in snap:
                val = snap["time_scale"]
                self._time_scale_s = val
                idx = min(range(len(_T_DIV_OPTIONS)),
                          key=lambda i: abs(_T_DIV_OPTIONS[i] - val))
                self._time_scale_cb.setCurrentIndex(idx)

            for ch in Channel.analog():
                w = self._ch_widgets[ch]

                scale_key = f"{ch.value}_scale"
                if scale_key in snap:
                    val = snap[scale_key]
                    self._ch_v_per_div[ch] = val
                    idx = min(range(len(_V_DIV_OPTIONS)),
                              key=lambda i: abs(_V_DIV_OPTIONS[i] - val))
                    w["scale"].setCurrentIndex(idx)

                pos_key = f"{ch.value}_position"
                if pos_key in snap:
                    self._ch_position[ch] = snap[pos_key]
                    if ch in self._ground_lines:
                        self._ground_lines[ch].setPos(snap[pos_key])

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

        self._update_trig_line()
        self._update_vdiv_label()

    def _on_log(self, msg: str):
        self._log_box.appendPlainText(msg)

    def _on_trig_state(self, state: str):
        _colours = {
            "ARMED":   "#FFA500",
            "AUTO":    "#4FC3F7",
            "READY":   "#66BB6A",
            "SAVE":    "#CE93D8",
            "TRIGGER": "#FFD700",
        }
        colour = _colours.get(state.upper(), "gray")
        self._lbl_trig_state.setStyleSheet(
            f"color: {colour}; font-size: 18px;"
        )
        self._lbl_trig_state.setToolTip(state)
        if self._trig_badge is not None:
            _labels = {
                "ARMED": "ARMED", "AUTO": "AUTO", "READY": "READY",
                "SAVE": "SAVE", "TRIGGER": "TRIG'D",
            }
            label = _labels.get(state.upper(), state)
            self._trig_badge.setText(label, color=colour, size="9pt")

    # ── Plot overlay helpers ───────────────────────────────────────────────────

    def _trig_source_colour(self) -> str:
        src = self._trig_source_str.upper()
        _idx = {"CH1": 0, "CH2": 1, "CH3": 2, "CH4": 3}
        return _CH_COLOURS[_idx[src]] if src in _idx else "#FFFFFF"

    def _update_trig_line_color(self):
        if self._trig_line is None:
            return
        self._trig_line.setPen(
            pg.mkPen(color=self._trig_source_colour(), width=1, style=Qt.DotLine)
        )

    def _update_trig_line(self):
        """Reposition the trigger-level line in division units."""
        if self._trig_line is None:
            return
        src = self._trig_source_str.upper()
        _ch_map = {"CH1": Channel.CH1, "CH2": Channel.CH2,
                   "CH3": Channel.CH3, "CH4": Channel.CH4}
        if src in _ch_map:
            ch = _ch_map[src]
            v_per_div = self._ch_v_per_div.get(ch, 0.5)
            pos_div   = self._ch_position.get(ch, 0.0)
            trig_div  = (self._trig_level_v / v_per_div + pos_div
                         if v_per_div > 0 else 0.0)
        else:
            trig_div = 0.0
        self._trig_line.setPos(trig_div)

    def _update_vdiv_label(self):
        """Refresh the per-channel V/div + time/div text strip."""
        if self._vdiv_label is None:
            return
        parts = []
        for i, ch in enumerate(Channel.analog()):
            if self._ch_widgets[ch]["display"].isChecked():
                v = self._ch_v_per_div.get(ch, 0.5)
                parts.append(f"{ch.value}: {_eng_v(v)}")
        parts.append(_eng_t(self._time_scale_s))
        self._vdiv_label.setText("   ".join(parts))

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_connected(self, connected: bool):
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)
        self._btn_single.setEnabled(connected)
        self._btn_free_run.setEnabled(connected)
        self._btn_autoset.setEnabled(connected)
        self._btn_measure.setEnabled(connected)
        self._btn_force_trig.setEnabled(connected)
        self._btn_set_50pct.setEnabled(connected)
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
