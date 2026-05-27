"""Example: run AUTOSet and print the resulting vertical/horizontal settings."""

from tektronix_tds2024c import TDS2024C, find_first_tds2024c, Channel

resource = find_first_tds2024c()
if resource is None:
    print("No TDS2024C found.")
    raise SystemExit(1)

with TDS2024C(resource) as osc:
    print("Running AUTOSet...")
    osc.autoset()
    print("Done.")

    print(f"\nTime scale : {osc.get_time_scale():.3e} s/div")
    print(f"Record len : {osc.get_record_length()} pts")
    for ch in Channel.analog():
        if osc.get_channel_display(ch):
            scale = osc.get_channel_scale(ch)
            coup  = osc.get_channel_coupling(ch)
            print(f"  {ch.value}: {scale:.3f} V/div  {coup.value}")
