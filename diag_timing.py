"""Benchmark individual SCPI operations to find the bottleneck."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from tektronix_tds2024c.discovery import list_tds2024c_resources
from tektronix_tds2024c.instrument import TDS2024C
from tektronix_tds2024c.models import Channel

resources = list_tds2024c_resources()
if not resources:
    print("No device"); sys.exit(1)

osc = TDS2024C(resources[0])
osc.connect()
osc.prepare_waveform_transfer()

def T(label, fn):
    t0 = time.perf_counter()
    result = fn()
    dt = (time.perf_counter() - t0) * 1000
    print(f"  {dt:7.1f} ms  {label}")
    return result

print("\n--- Single-query latencies ---")
T("*IDN?",                lambda: osc.identify())
T("CH1:SCAle?",           lambda: osc._query("CH1:SCAle?"))
T("CH1:POSition?",        lambda: osc._query("CH1:POSition?"))
T("CH1:COUPling?",        lambda: osc._query("CH1:COUPling?"))
T("SELect:CH1?",          lambda: osc._query("SELect:CH1?"))
T("TRIGger:MAIn:LEVel?",  lambda: osc._query("TRIGger:MAIn:LEVel?"))
T("TRIGger:MAIn:EDGE:SOUrce?", lambda: osc._query("TRIGger:MAIn:EDGE:SOUrce?"))
T("TRIGger:MAIn:EDGE:SLOpe?",  lambda: osc._query("TRIGger:MAIn:EDGE:SLOpe?"))
T("TRIGger:MAIn:MODe?",   lambda: osc._query("TRIGger:MAIn:MODe?"))
T("TRIGger:STATE?",       lambda: osc._query("TRIGger:STATE?"))
T("HORizontal:SCAle?",    lambda: osc._query("HORizontal:SCAle?"))

print("\n--- WFMPre? (preamble) ---")
T("WFMPre? cold (CH1, cache miss)", lambda: (
    osc.invalidate_preamble_cache(),
    osc._query("DATa:SOUrce CH1; WFMPre?")
))
T("WFMPre? cold (CH2, cache miss)", lambda: (
    osc.invalidate_preamble_cache(),
    osc._query("DATa:SOUrce CH2; WFMPre?")
))

print("\n--- CURVe? (waveform data) ---")
osc.prepare_waveform_transfer()   # re-warm after the manual queries above

# Warm preamble cache first
_ = osc.read_waveform(Channel.CH1)
_ = osc.read_waveform(Channel.CH2)

T("read_waveform CH1 (cache warm)", lambda: osc.read_waveform(Channel.CH1))
T("read_waveform CH2 (cache warm)", lambda: osc.read_waveform(Channel.CH2))

print("\n--- Full 2-channel free-run frame ---")
t0 = time.perf_counter()
for _ in range(5):
    _ = osc.read_waveform(Channel.CH1)
    _ = osc.read_waveform(Channel.CH2)
dt = (time.perf_counter() - t0) / 5 * 1000
print(f"  {dt:7.1f} ms  average per 2-channel frame (5 reps)")
print(f"  {1000/dt:7.1f} fps  theoretical max with 2 channels")

print("\n--- Full settings snapshot (what polls every 3 s) ---")
t0 = time.perf_counter()
osc.get_time_scale()
for ch in list(Channel.analog()):
    osc.get_channel_scale(ch)
    osc.get_channel_position(ch)
    osc.get_channel_coupling(ch)
    osc.get_channel_display(ch)
osc.get_trigger_level()
osc.get_trigger_source()
osc.get_trigger_slope()
try: osc.get_trigger_mode()
except: pass
try: osc.get_trigger_coupling()
except: pass
osc.get_trigger_state()
dt_snap = (time.perf_counter() - t0) * 1000
print(f"  {dt_snap:7.1f} ms  total for _build_state_snapshot() [{int(dt_snap/1000*10)/10} s]")

osc.disconnect()
print("\nDone.")
