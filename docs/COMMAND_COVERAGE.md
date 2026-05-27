# Command Coverage — Tektronix TDS2024C Driver

Status labels: **Implemented** | **Planned** | **Not applicable**

## Acquisition

| Command | Status | Method |
|---|---|---|
| `ACQuire:MODe` | Implemented | `set_acq_mode` / `get_acq_mode` |
| `ACQuire:NUMAVg` | Implemented | `set_acq_numavg` / `get_acq_numavg` |
| `ACQuire:NUMACq?` | Implemented | `get_acq_count` |
| `ACQuire:STATE` | Implemented | `acq_run` / `acq_stop` / `acq_single` / `single_acquisition` |
| `ACQuire:STATE?` | Implemented | `is_running` |
| `ACQuire:STOPAfter` | Implemented | `acq_run` / `acq_single` / `get_acq_stopafter` |
| `BUSY?` | Implemented | `is_busy` / `wait_acq_complete` |

## Vertical

| Command | Status | Method |
|---|---|---|
| `CH<x>:SCAle` | Implemented | `set_channel_scale` / `get_channel_scale` |
| `CH<x>:POSition` | Implemented | `set_channel_position` / `get_channel_position` |
| `CH<x>:COUPling` | Implemented | `set_channel_coupling` / `get_channel_coupling` |
| `CH<x>:BANdwidth` | Implemented | `set_channel_bw_limit` / `get_channel_bw_limit` |
| `CH<x>:PROBe` | Implemented | `set_channel_probe` / `get_channel_probe` |
| `CH<x>:INVert` | Planned | — |
| `CH<x>:YUNit` | Planned | — |
| `SELect:<wfm>` | Implemented | `set_channel_display` / `get_channel_display` |

## Horizontal

| Command | Status | Method |
|---|---|---|
| `HORizontal:MAIn:SCAle` | Implemented | `set_time_scale` / `get_time_scale` |
| `HORizontal:MAIn:POSition` | Implemented | `set_time_position` / `get_time_position` |
| `HORizontal:RECOrdlength?` | Implemented | `get_record_length` |
| `HORizontal:VIEW` | Planned | — |
| `HORizontal:DELay:*` | Planned | — |

## Trigger

| Command | Status | Method |
|---|---|---|
| `TRIGger:MAIn:TYPe` | Implemented | `set_trigger_type` / `get_trigger_type` |
| `TRIGger:MAIn:LEVel` | Implemented | `set_trigger_level` / `get_trigger_level` |
| `TRIGger:MAIn:MODe` | Implemented | `set_trigger_mode` / `get_trigger_mode` |
| `TRIGger:MAIn:EDGE:SOUrce` | Implemented | `set_trigger_source` / `get_trigger_source` |
| `TRIGger:MAIn:EDGE:SLOpe` | Implemented | `set_trigger_slope` / `get_trigger_slope` |
| `TRIGger:MAIn:EDGE:COUPling` | Implemented | `set_trigger_coupling` / `get_trigger_coupling` (returns `TriggerCoupling`) |
| `TRIGger:MAIn SETLevel` | Implemented | `set_trigger_to_50pct` |
| `TRIGger:MAIn:HOLDOff:VALue` | Planned | — |
| `TRIGger:MAIn:FREQuency?` | Planned | — |
| `TRIGger:MAIn:PULse:*` | Planned | — |
| `TRIGger:STATe?` | Implemented | `get_trigger_state` |
| `TRIGger FORCe` | Implemented | `force_trigger` |

## Measurement

| Command | Status | Method |
|---|---|---|
| `MEASUrement:IMMed:SOUrce1` | Implemented | `set_immed_source` |
| `MEASUrement:IMMed:TYPe` | Implemented | `set_immed_type` |
| `MEASUrement:IMMed:VALue?` | Implemented | `get_immed_value` / `measure` |
| `MEASUrement:IMMed:UNIts?` | Implemented | `get_immed_units` |
| `MEASUrement:MEAS<x>:TYPe` | Planned | — |
| `MEASUrement:MEAS<x>:SOUrce` | Planned | — |
| `MEASUrement:MEAS<x>:VALue?` | Planned | — |
| `MEASUrement:MEAS<x>:UNIts?` | Planned | — |

## Waveform

| Command | Status | Method |
|---|---|---|
| `DATa:SOUrce` | Implemented | `set_waveform_source` |
| `DATa:ENCdg` | Implemented | `set_waveform_encoding` |
| `DATa:WIDth` | Implemented | `set_waveform_width` |
| `DATa:STARt` | Implemented | `set_waveform_start` |
| `DATa:STOP` | Implemented | `set_waveform_stop` |
| `WFMPre?` | Implemented | `get_waveform_preamble` |
| `CURVe?` | Implemented | `get_curve_raw` / `capture_waveform` |
| `DATa:DESTination` | Planned | — |
| `WAVFrm?` | Planned | — |

## Cursor

| Command | Status | Method |
|---|---|---|
| `CURSor:FUNCtion` | Planned | — |
| `CURSor:VBArs:POSITION<x>` | Planned | — |
| `CURSor:VBArs:DELTa?` | Planned | — |
| `CURSor:HBArs:*` | Planned | — |

## Display

| Command | Status | Method |
|---|---|---|
| `DISplay:STYle` | Planned | — |
| `DISplay:PERSistence` | Planned | — |
| `DISplay:CONTRast` | Planned | — |

## Save / Recall

| Command | Status | Method |
|---|---|---|
| `SAVe:SETUp` | Planned | — |
| `RECAll:SETUp` | Planned | — |
| `SAVe:WAVEform` | Planned | — |
| `SAVe:IMAGe` | Planned | — |

## Math

| Command | Status | Method |
|---|---|---|
| `MATH:DEFine` | Planned | — |
| `MATH:FFT:*` | Planned | — |

## Status / Events

| Command | Status | Method |
|---|---|---|
| `*IDN?` | Implemented | `identify` |
| `*RST` | Implemented | `reset` |
| `*CLS` | Implemented | `clear_status` |
| `*TST?` | Implemented | `self_test` |
| `*OPC?` | Implemented (internal) | `_wait_opc` |
| `EVENT?` | Implemented | `get_event` |
| `EVMsg?` | Implemented | `get_event` |
| `EVQty?` | Implemented | `drain_event_queue` |
| `*ESR?` | Planned | — |
| `*STB?` | Planned | — |
| `*SRE` | Planned | — |
| `DESE` | Planned | — |

## Miscellaneous

| Command | Status | Method |
|---|---|---|
| `AUTOSet EXECUTE` | Implemented | `autoset` |
| `LOCk ALL` | Implemented | `lock_front_panel` |
| `UNLock ALL` | Implemented | `unlock_front_panel` |
| `HEADer` | Implemented | `set_header` |
| `AUTORanGe:STATE` | Planned | — |
| `DATE` | Not applicable (TDS2000B only, not needed) | — |
| `TIME` | Not applicable | — |
| `FILESystem:*` | Not applicable (requires USB flash in scope) | — |
| RS-232 commands | Not applicable (TDS2000B has no RS-232) | — |
| PictBridge commands | Not applicable | — |
