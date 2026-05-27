from __future__ import annotations

import pyvisa

# Tektronix USB vendor ID
_TEK_VID = "0x0699"


def list_tektronix_resources(visa_library: str = "") -> list[str]:
    """Return VISA resource strings for connected Tektronix USB instruments.

    Filters by Tektronix VID ``0x0699``.  The product ID is intentionally not
    filtered — TDS2000B-family PIDs vary by model and firmware (the TDS2024C
    used to validate this driver enumerates as ``0x03A6``), and a too-narrow
    PID list silently hides working instruments.  Confirm the exact model with
    ``*IDN?`` after connecting.

    Parameters
    ----------
    visa_library:
        Path to a VISA shared library, or ``""`` for the pyvisa default backend.
    """
    try:
        rm = (pyvisa.ResourceManager(visa_library)
              if visa_library else pyvisa.ResourceManager())
    except Exception as exc:
        raise RuntimeError(f"Cannot open VISA resource manager: {exc}") from exc

    try:
        all_usb = list(rm.list_resources("USB?*INSTR"))
    except Exception:
        all_usb = []
    finally:
        try:
            rm.close()
        except Exception:
            pass

    return sorted(r for r in all_usb if _TEK_VID.upper() in r.upper())


# Backwards-friendly alias — this driver targets the TDS2024C specifically.
list_tds2024c_resources = list_tektronix_resources


def find_first_tds2024c(visa_library: str = "") -> str | None:
    """Return the first Tektronix USB resource string found, or ``None``."""
    results = list_tektronix_resources(visa_library)
    return results[0] if results else None
