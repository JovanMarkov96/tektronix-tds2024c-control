"""Example: connect to a TDS2024C, read identity, then disconnect."""

from tektronix_tds2024c import TDS2024C, find_first_tds2024c, TDS2024CConnectionError

resource = find_first_tds2024c()
if resource is None:
    print("No TDS2024C found on USB. Check the connection and USB driver.")
    raise SystemExit(1)

print(f"Found: {resource}")

with TDS2024C(resource) as osc:
    idn = osc.identify()
    print(f"Identity: {idn}")
    passed = osc.self_test()
    print(f"Self-test: {'PASS' if passed else 'FAIL'}")
