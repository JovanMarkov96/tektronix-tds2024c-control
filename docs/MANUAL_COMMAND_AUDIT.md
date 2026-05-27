# Manual Command Audit — Tektronix TDS2024C

## Source

Manual: *TDS200, TDS1000/TDS2000, TDS1000B/TDS2000B, and TPS2000 Series
Digital Oscilloscopes Programmer Manual*, part number **071-1075-04**.

The TDS2024C belongs to the **TDS2000B** variant group.  Key facts confirmed
from Tables 1-1 and 1-2 of the manual:

| Property | Evidence |
|---|---|
| Communication | **USB Device** only (Table 1-1, TDS1000B/TDS2000B row) |
| USB class | USBTMC / USB488 subclass (Section 2, Command Groups intro) |
| GPIB | Not available without TEK-USB-488 adapter |
| RS-232 | Not available on TDS2000B |
| Terminator | USB EOM bit in last transfer packet (Section 2, Message Terminators) |

## Command Groups Audited

### Acquisition (Table 2-8)
| Command | Description | Implementation |
|---|---|---|
| `ACQuire:MODe` | SAMple / PEAKdetect / AVErage | `set_acq_mode` / `get_acq_mode` |
| `ACQuire:NUMAVg` | Number of averages (4–512) | `set_acq_numavg` / `get_acq_numavg` |
| `ACQuire:NUMACq?` | Count of acquisitions obtained | not implemented |
| `ACQuire:STATE` | RUN / STOP | `acq_run` / `acq_stop` / `acq_single` |
| `ACQuire:STOPAfter` | RUNSTop / SEQuence | used internally by `acq_run` / `acq_single` |

### Vertical (Table 2-25)
| Command | Description | Implementation |
|---|---|---|
| `CH<x>:SCAle` | V/div | `set_channel_scale` / `get_channel_scale` |
| `CH<x>:POSition` | Divisions up/down | `set_channel_position` / `get_channel_position` |
| `CH<x>:COUPling` | AC / DC / GND | `set_channel_coupling` / `get_channel_coupling` |
| `CH<x>:BANdwidth` | ON (full) / OFF (20 MHz) | `set_channel_bw_limit` / `get_channel_bw_limit` |
| `CH<x>:PROBe` | Attenuation factor | `set_channel_probe` / `get_channel_probe` |
| `CH<x>:INVert` | Invert waveform | not implemented |
| `CH<x>:YUNit` | TDS2000B only | not implemented |
| `SELect:<wfm>` | Display on/off | `set_channel_display` / `get_channel_display` |

### Horizontal (Table 2-14)
| Command | Description | Implementation |
|---|---|---|
| `HORizontal:MAIn:SCAle` | s/div | `set_time_scale` / `get_time_scale` |
| `HORizontal:MAIn:POSition` | Trigger point position | `set_time_position` / `get_time_position` |
| `HORizontal:RECOrdlength` | Record length (read-only) | `get_record_length` |
| `HORizontal:VIEW` | MAIN / WINDOW | not implemented |
| `HORizontal:DELay:*` | Delayed sweep | not implemented |

### Trigger (Table 2-24)
| Command | Description | Implementation |
|---|---|---|
| `TRIGger:MAIn:TYPe` | EDGE / PULse / VIDeo | `set_trigger_type` / `get_trigger_type` |
| `TRIGger:MAIn:LEVel` | Trigger voltage | `set_trigger_level` / `get_trigger_level` |
| `TRIGger:MAIn:EDGE:SOUrce` | CH1–CH4 / EXT | `set_trigger_source` / `get_trigger_source` |
| `TRIGger:MAIn:EDGE:SLOpe` | RISe / FALL | `set_trigger_slope` / `get_trigger_slope` |
| `TRIGger:MAIn:EDGE:COUPling` | DC / AC / HFRej / LFRej / NOISErej | `set_trigger_coupling` / `get_trigger_coupling` |
| `TRIGger:MAIn:MODe` | AUTO / NORMal | `set_trigger_mode` / `get_trigger_mode` |
| `TRIGger:MAIn:HOLDOff:VALue` | Holdoff time | not implemented |
| `TRIGger:MAIn:FREQuency?` | Trigger frequency readout | not implemented |
| `TRIGger:STATe?` | ARMED / AUTO / READY / SAVE / TRIGGER | `get_trigger_state` |
| `TRIGger` (command) | Force trigger | `force_trigger` |

### Measurement (Table 2-16)
| Command | Description | Implementation |
|---|---|---|
| `MEASUrement:IMMed:SOUrce1` | Source channel | `set_immed_source` |
| `MEASUrement:IMMed:TYPe` | FREQuency / MEAN / PK2pk / RMS / etc. | `set_immed_type` |
| `MEASUrement:IMMed:VALue?` | Measurement result | `get_immed_value` |
| `MEASUrement:IMMed:UNIts?` | Units string | `get_immed_units` |
| `MEASUrement:MEAS<x>:TYPe` | On-screen measurement slots 1–5 | not implemented |
| `MEASUrement:MEAS<x>:VALue?` | On-screen measurement value | not implemented |

**Note on `9.91E+37` sentinel** (confirmed from manual Section 2, Measurement Commands):
The oscilloscope returns `9.91E+37` when a measurement cannot be made (no valid signal,
wrong signal type, etc.).  The driver raises `TDS2024CMeasurementError` in this case.

### Waveform (Tables 2-26 through 2-40)
| Command | Description | Implementation |
|---|---|---|
| `DATa:SOUrce` | Select channel for curve transfer | `set_waveform_source` |
| `DATa:ENCdg` | ASCIi / RIBinary / RPBinary | `set_waveform_encoding` |
| `DATa:WIDth` | 1 or 2 bytes per point | `set_waveform_width` |
| `DATa:STARt` | First sample index | `set_waveform_start` |
| `DATa:STOP` | Last sample index | `set_waveform_stop` |
| `WFMPre?` | Full preamble (scaling, units, etc.) | `get_waveform_preamble` |
| `CURVe?` | Binary or ASCII data block | `get_curve_raw` |
| `DATa:DESTination` | Waveform destination (for sending to scope) | not implemented |

**Binary decode formula** (confirmed from manual Section 2, Waveform Data Formats):
```
v[i] = (raw_byte[i] - YOFf) * YMUlt + YZEro
t[i] = XZEro + i * XINcr
```

### Miscellaneous (Table 2-17)
| Command | Description | Implementation |
|---|---|---|
| `*IDN?` | Identification | `identify` |
| `*RST` | Reset | `reset` |
| `*CLS` | Clear status | `clear_status` |
| `*TST?` | Self-test | `self_test` |
| `*OPC?` | Operation complete | used internally by `_wait_opc` |
| `AUTOSet EXECUTE` | Automatic setup | `autoset` |
| `LOCk ALL` | Lock front panel | `lock_front_panel` |
| `UNLock ALL` | Unlock front panel | `unlock_front_panel` |
| `HEADer ON/OFF` | Include header in responses | `set_header` |
| `BUSY?` | Acquisition busy flag | `is_busy` |
| `EVENT?` | Event code | `get_event` |
| `EVMsg?` | Event message | `get_event` |
| `EVQty?` | Number of events queued | `drain_event_queue` |
| `FACtory` | Factory reset | not implemented (use `*RST`) |

## Gaps and Choices

1. **`DATa:ENCdg RPBinary`** — unsigned binary.  Not implemented; unsigned samples
   require different decode logic.  RIBinary (signed) is the preferred choice per manual.

2. **Cursor commands** — not implemented in Phase 1.  `CURSor:VBArs:DELTa?` is
   useful for manual voltage-level readback but not needed for automated capture.

3. **`SAVe:IMAGe`** — screenshot to USB flash drive on the oscilloscope.
   Requires a USB flash drive physically inserted in the scope's front USB port.
   Not implemented in Phase 1; planned for Phase 3.

4. **`MATH:FFT:*`** — FFT of displayed waveform.  Not implemented.
   Software FFT via numpy on the captured `WaveformRecord` is the preferred approach
   for flexibility.

5. **`DATa:WIDth 2`** — 16-bit data.  Not implemented; 8-bit (1-byte) is sufficient
   for the TDS2024C's 8-bit ADC.  The oscilloscope has only 8 bits of vertical
   resolution, so `WIDth 2` just pads with zeros (manual Section 2, Waveform Data).

6. **Header ON vs OFF** — the driver forces `HEADer OFF` on connect so query
   responses are bare values (e.g. `SAMPLE`) rather than `:ACQUIRE:MODE SAMPLE`.
   This makes both scalar parsing and the positional `WFMPre?` parse unambiguous.
   Note that with `HEADer OFF` the `WFMPre?` response is a positional,
   semicolon-separated list with no field names; the parser handles both the
   positional and header-on (`KEY value`) forms.

7. **Query responses are uppercase full words.** Although set commands accept the
   SCPI mixed-case short/long form (e.g. `SAMple`), the scope echoes back the
   uppercase full word on query (`SAMPLE`, `RISE`, `NOISEREJ`, ...). Enum parsing
   is therefore case-insensitive and accepts both the full word and the short form.

8. **`LINE` trigger source locks edge coupling.** When the trigger source is
   `LINE`, `TRIGger:MAIn:EDGE:COUPling` cannot be changed. This is documented
   device behavior, not a driver limitation.
