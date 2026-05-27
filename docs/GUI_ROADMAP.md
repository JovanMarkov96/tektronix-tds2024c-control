# GUI Roadmap — Tektronix TDS2024C Standalone Application

## Architecture

**Framework**: `qtpy` (PyQt5/PyQt6 abstraction) + `pyqtgraph` for real-time plots.
Chosen over Matplotlib for sub-100 ms waveform refresh rates.

**Threading model**:
- Main (GUI) thread: renders widgets, processes user input.
- Worker `QThread`: owns the VISA session; all VISA I/O happens here.
- Communication: `pyqtSignal` for worker→GUI updates; `queue.Queue` for GUI→worker commands.
- Waveform arrays transferred via signal carrying `WaveformRecord`; pyqtgraph
  `PlotDataItem.setData()` called in GUI thread slot.

## Window Layout

```
┌─────────────────────────────────────────────────────────────┐
│ [USB Resource ▼] [Auto-discover]  [Connect] [Disconnect]    │
│ Status: CONNECTED  TEKTRONIX,TDS2024C,C012345,...            │
├───────────────────────────┬─────────────────────────────────┤
│  CHANNELS                 │  WAVEFORM PLOT                  │
│  ┌──CH1──┐ ┌──CH2──┐     │  ┌─────────────────────────────┐│
│  │V/div  │ │V/div  │     │  │                             ││
│  │[0.5V▼]│ │[1.0V▼]│     │  │  pyqtgraph PlotWidget       ││
│  │Coupl  │ │Coupl  │     │  │  (t vs V, auto-scaled)      ││
│  │[DC ▼] │ │[DC ▼] │     │  │                             ││
│  │[☑ On] │ │[☑ On] │     │  └─────────────────────────────┘│
│  └───────┘ └───────┘     │  [Single Shot] [▶ Free Run] [■] │
│  ┌──CH3──┐ ┌──CH4──┐     ├─────────────────────────────────┤
│  │  ...  │ │  ...  │     │  MEASUREMENT                    │
│  └───────┘ └───────┘     │  Source [CH1▼] Type [Freq ▼]   │
├───────────────────────────┤  [Measure Once]  123.456 MHz   │
│  HORIZONTAL               │  [☑ Continuous poll]  1.0 s   │
│  Time/div [100µs ▼]       ├─────────────────────────────────┤
│  Position [0.000 s]       │  TRIGGER                        │
├───────────────────────────┤  Type [Edge▼] Src [CH1▼]       │
│  ACQ MODE                 │  Level [0.000 V] Slope [Rise▼] │
│  [Sample▼] Avg [16]       │  Mode [Auto▼]  [Force Trigger] │
│  [AutoSet]                │  State: ● READY                 │
├───────────────────────────┴─────────────────────────────────┤
│  Command log                                        [Clear] │
│  > CH1:SCAle 5.000E-01                                      │
│  > MEASUrement:IMMed:VALue? → 1.234567E+08                  │
└─────────────────────────────────────────────────────────────┘
```

## Panel Descriptions

### Connection Bar
- Editable combo box: type resource string or select from auto-discovered list.
- **Auto-discover** button: calls `list_tds2024c_resources()`, populates dropdown.
- **Connect** / **Disconnect** buttons; status LED (green/red) + IDN label.

### Channel Strip (×4, CH1–CH4)
- **V/div**: `QComboBox` with standard values: 2mV, 5mV, 10mV, 20mV, 50mV, 100mV,
  200mV, 500mV, 1V, 2V, 5V.  Sends `CHx:SCAle` on change.
- **Coupling**: `QComboBox` AC / DC / GND.  Sends `CHx:COUPling`.
- **Display**: `QCheckBox`.  Sends `SELect:CHx ON/OFF`.
- Probe and position: available in a collapsible "Advanced" section.

### Horizontal Panel
- **Time/div**: `QComboBox` with standard values from 5ns to 50s.
- **Position**: `QDoubleSpinBox`.

### Acquisition Panel
- **Mode**: Sample / Peak / Average.  When Average is selected, Avg count spinbox
  becomes enabled.
- **AutoSet** button: sends `AUTOSet EXECUTE`, polls `BUSY?`, refreshes all settings.

### Waveform Plot (pyqtgraph)
- `pyqtgraph.PlotWidget` with white background, labeled axes.
- Up to 4 `PlotDataItem` objects (one per channel), distinct colours.
- **Single Shot**: `acq_single()` → `wait_acq_complete()` → `capture_waveform()` → plot.
- **Free Run** toggle: background worker polls `capture_waveform()` every N ms; configurable
  via a "Refresh" interval spinbox (min 100 ms, default 500 ms).
- **Stop** (■) button: halts free run.
- Plot auto-scales on first capture; then fixed unless "Auto Scale" checkbox is checked.
- CH selector checkboxes above plot determine which channels are overlaid.

### Measurement Panel
- Source: `QComboBox` CH1–CH4.
- Type: `QComboBox` listing all `MeasType` values.
- **Measure Once** button → displays result + units.
- **Continuous poll** checkbox + interval spinbox (0.5–10 s).
- Invalid measurement (sentinel) shown as `---` in red.

### Trigger Panel
- Type: Edge only in Phase 1.
- Source, Level, Slope, Mode controls.
- **Force Trigger** button.
- State indicator: coloured label (ARMED=orange, READY=green, TRIGGER=yellow, AUTO=blue).

### Command Log
- Read-only `QPlainTextEdit`.
- Background worker emits `log_signal(str)` for every command sent and response received.
- **Clear** button.

## Phase-Based Execution Plan

### Phase 1 (current)
- Connection bar + worker thread
- Channel strip (all 4 channels)
- Single-shot + manual waveform capture with pyqtgraph plot
- Measurement panel (single + continuous)
- Trigger panel (edge only)
- Command log

### Phase 2
- Free-run continuous capture with configurable refresh rate
- Multi-channel overlay plot
- Trigger state indicator

### Phase 3
- Cursor overlay on waveform plot (drag-to-measure)
- Screenshot button (`SAVe:IMAGe` if USB flash present)
- Settings save/restore

## Safety Rules
- All VISA I/O in worker thread only — never in Qt event loop.
- Disconnect gracefully on window close: `osc.unlock_front_panel()` then `osc.disconnect()`.
- `AUTOSet` and `*RST` show a confirmation dialog before sending (destructive to current setup).
