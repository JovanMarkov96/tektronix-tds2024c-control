"""Quick diagnostic — verify scope connection and waveform decode."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from tektronix_tds2024c.discovery import list_tds2024c_resources
from tektronix_tds2024c.instrument import TDS2024C
from tektronix_tds2024c.models import Channel
import numpy as np

resources = list_tds2024c_resources()
print("Devices found:", resources)
if not resources:
    print("No device — aborting")
    sys.exit(1)

osc = TDS2024C(resources[0])
osc.connect()
print("IDN:", osc.identify().strip())
osc.prepare_waveform_transfer()

for ch in [Channel.CH1, Channel.CH2]:
    on    = osc.get_channel_display(ch)
    scale = osc.get_channel_scale(ch)
    pos   = osc.get_channel_position(ch)
    coup  = osc.get_channel_coupling(ch).value
    print("")
    print(ch.value + ": on=" + str(on) + "  scale=" + str(round(scale*1000)) + "mV/div  pos=" + str(round(pos,2)) + "div  coup=" + coup)
    if on:
        rec  = osc.read_waveform(ch)
        pre  = rec.preamble
        print("  preamble: ymult=" + str(pre.y_mult) + "  yzero=" + str(pre.y_zero) + "  yoff=" + str(pre.y_off))
        print("  decoded:  v_min=" + str(round(rec.v.min(),4)) + "V  v_max=" + str(round(rec.v.max(),4)) + "V  pkpk=" + str(round(rec.v_pkpk,4)) + "V  mean=" + str(round(rec.v_mean,4)) + "V")
        expected_max = 4 * scale * 2.5
        ok = rec.v_pkpk < expected_max
        print("  sanity (pkpk < " + str(round(expected_max,3)) + "V): " + ("OK" if ok else "*** WRONG ***"))

print("")
print("--- Trigger ---")
print("  source=" + osc.get_trigger_source().value + "  level=" + str(round(osc.get_trigger_level(),4)) + "V")
print("  slope=" + osc.get_trigger_slope().value + "  mode=" + osc.get_trigger_mode().value + "  state=" + osc.get_trigger_state())
t_div = osc.get_time_scale()
if t_div >= 1e-3:
    t_str = str(round(t_div*1e3,3)) + "ms"
elif t_div >= 1e-6:
    t_str = str(round(t_div*1e6,3)) + "us"
else:
    t_str = str(round(t_div*1e9,3)) + "ns"
print("  time/div=" + t_str)

osc.disconnect()
print("")
print("Done.")
