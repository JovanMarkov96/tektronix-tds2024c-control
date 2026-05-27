from __future__ import annotations

import time
from typing import Optional, Union

import numpy as np
import pyvisa

from .errors import (
    TDS2024CConnectionError,
    TDS2024CMeasurementError,
    TDS2024CTimeoutError,
)
from .models import (
    AcqMode,
    AcqStopAfter,
    BandwidthLimit,
    Channel,
    Coupling,
    MEAS_NO_VALUE,
    MeasType,
    TriggerCoupling,
    TriggerMode,
    TriggerSlope,
    TriggerSource,
    TriggerType,
    WfmEncoding,
    WfmWidth,
)
from .waveform import WaveformPreamble, WaveformRecord

# Full record length for the TDS2024C
_RECORD_LENGTH = 2500
_DEFAULT_TIMEOUT_MS = 10_000


class TDS2024C:
    """Driver for the Tektronix TDS2024C Digital Storage Oscilloscope.

    Communicates over USB (USBTMC, USB488 subclass) via pyvisa.  The TDS2000B
    family is USB-only — RS-232/GPIB are not available without an adapter.

    Example
    -------
    ::

        with TDS2024C("USB0::0x0699::0x03A6::C046053::INSTR") as osc:
            osc.autoset()
            rec = osc.capture_waveform(Channel.CH1)
            print(rec.v_pkpk)
    """

    def __init__(self, resource: str, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
        self._resource = resource
        self._timeout_ms = timeout_ms
        self._rm: Optional[pyvisa.ResourceManager] = None
        self._inst: Optional[pyvisa.resources.MessageBasedResource] = None
        self._wfm_encoding: WfmEncoding = WfmEncoding.RIBINARY
        # Per-channel preamble cache. WFMPre? takes ~1 s on TDS2000B firmware,
        # but the preamble (scaling, time base) only changes when the user
        # touches V/div, time/div, position, probe, etc. — so cache it and
        # invalidate from those setters.
        self._preamble_cache: dict[Channel, WaveformPreamble] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the VISA session and configure communication defaults."""
        try:
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self._resource)
            self._inst.timeout = self._timeout_ms
            # USBTMC: messages are LF-terminated; binary reads use the IEEE
            # block-header byte count, so the LF terminator does not corrupt them.
            self._inst.read_termination = "\n"
            self._inst.write_termination = "\n"
        except pyvisa.VisaIOError as exc:
            raise TDS2024CConnectionError(
                f"Cannot open {self._resource}: {exc}"
            ) from exc

        # Bare values in query responses (no ":CMD:HEAD value" prefix) so both
        # scalar parsing and positional WFMPre? parsing are unambiguous.
        self._write("HEADer OFF")
        # Drop any stale power-on / error events from a previous session.
        self.clear_status()

    def disconnect(self) -> None:
        """Close the VISA session (best effort, never raises)."""
        for closer in (self._inst, self._rm):
            try:
                if closer is not None:
                    closer.close()
            except Exception:
                pass
        self._inst = None
        self._rm = None

    def __enter__(self) -> "TDS2024C":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    @property
    def connected(self) -> bool:
        return self._inst is not None

    # ── Identity / IEEE 488.2 ──────────────────────────────────────────────────

    def identify(self) -> str:
        return self._query("*IDN?")

    def reset(self) -> None:
        """``*RST`` factory reset, then wait for completion."""
        self._write("*RST")
        self._wait_opc()

    def clear_status(self) -> None:
        self._write("*CLS")

    def self_test(self) -> bool:
        """``*TST?`` — True when the scope reports pass (0)."""
        return self._query("*TST?").strip() == "0"

    # ── Acquisition ────────────────────────────────────────────────────────────

    def invalidate_preamble_cache(self, ch: Optional[Channel] = None) -> None:
        """Drop the cached WFMPre? response.  Called automatically by setters
        that change scaling; call explicitly to force a fresh fetch on the next
        :meth:`read_waveform`.

        Parameters
        ----------
        ch: if ``None``, clears the entire cache (e.g. time base changed);
            otherwise clears only the entry for that channel.
        """
        if ch is None:
            self._preamble_cache.clear()
        else:
            self._preamble_cache.pop(ch, None)

    def set_acq_mode(self, mode: AcqMode) -> None:
        # PEAK changes PT_FMT (Y→ENV) and doubles point count — invalidate all.
        self.invalidate_preamble_cache()
        self._write(f"ACQuire:MODe {mode.value}")

    def get_acq_mode(self) -> AcqMode:
        return AcqMode(self._query("ACQuire:MODe?"))

    def set_acq_numavg(self, n: int) -> None:
        """Number of averages (TDS2000B accepts 4, 16, 64, 128; clamped by scope)."""
        self._write(f"ACQuire:NUMAVg {int(n)}")

    def get_acq_numavg(self) -> int:
        return int(self._query("ACQuire:NUMAVg?"))

    def get_acq_count(self) -> int:
        """``ACQuire:NUMACq?`` — number of acquisitions since last start."""
        return int(self._query("ACQuire:NUMACq?"))

    def get_acq_stopafter(self) -> AcqStopAfter:
        return AcqStopAfter(self._query("ACQuire:STOPAfter?"))

    def is_running(self) -> bool:
        """``ACQuire:STATE?`` — True when acquisition is running (returns 1/0)."""
        return self._query("ACQuire:STATE?").strip() in ("1", "RUN")

    def acq_run(self) -> None:
        """Start free-running acquisition."""
        self._write(f"ACQuire:STOPAfter {AcqStopAfter.RUNSTOP.value}")
        self._write("ACQuire:STATE RUN")

    def acq_stop(self) -> None:
        self._write("ACQuire:STATE STOP")

    def acq_single(self) -> None:
        """Arm a single-sequence acquisition and start it (non-blocking).

        The acquisition completes when a trigger occurs.  In NORMAL trigger
        mode that requires a qualifying signal; call :meth:`force_trigger` or
        use :meth:`single_acquisition` with ``force=True`` to complete without
        one.
        """
        self._write("ACQuire:STATE STOP")
        self._write(f"ACQuire:STOPAfter {AcqStopAfter.SEQUENCE.value}")
        self._write("ACQuire:STATE RUN")

    def single_acquisition(self, force: bool = False, timeout_s: float = 10.0) -> None:
        """Arm one acquisition and block until it completes.

        Parameters
        ----------
        force:
            When True, immediately force a trigger so the frame completes even
            with no qualifying signal present — useful for snapshotting a
            quiescent input on demand.  When False, waits for a real (or AUTO)
            trigger and raises :class:`TDS2024CTimeoutError` if none arrives.
        timeout_s:
            Maximum time to wait for completion.
        """
        self.acq_single()
        if force:
            self.force_trigger()
        self.wait_acq_complete(timeout_s=timeout_s)

    def is_busy(self) -> bool:
        return self._query("BUSY?").strip() == "1"

    def wait_acq_complete(self, timeout_s: float = 10.0, poll_s: float = 0.02) -> None:
        """Block until ``BUSY?`` reports idle (single-shot complete) or timeout.

        Note: in NORMAL trigger mode a single acquisition only completes once a
        real trigger event occurs, so this will time out if no qualifying signal
        is present.  Use AUTO trigger mode for a guaranteed completion.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._query("BUSY?").strip() == "0":
                return
            time.sleep(poll_s)
        raise TDS2024CTimeoutError(
            f"Acquisition did not complete within {timeout_s:.1f} s"
        )

    # ── Vertical (Channel) ─────────────────────────────────────────────────────

    def set_channel_scale(self, ch: Channel, v_per_div: float) -> None:
        self.invalidate_preamble_cache(ch)
        self._write(f"{ch.value}:SCAle {v_per_div:.6E}")

    def get_channel_scale(self, ch: Channel) -> float:
        return float(self._query(f"{ch.value}:SCAle?"))

    def set_channel_position(self, ch: Channel, divs: float) -> None:
        self.invalidate_preamble_cache(ch)
        self._write(f"{ch.value}:POSition {divs:.4f}")

    def get_channel_position(self, ch: Channel) -> float:
        return float(self._query(f"{ch.value}:POSition?"))

    def set_channel_coupling(self, ch: Channel, coupling: Coupling) -> None:
        self._write(f"{ch.value}:COUPling {coupling.value}")

    def get_channel_coupling(self, ch: Channel) -> Coupling:
        return Coupling(self._query(f"{ch.value}:COUPling?"))

    def set_channel_bw_limit(self, ch: Channel, limit: BandwidthLimit) -> None:
        self._write(f"{ch.value}:BANdwidth {limit.value}")

    def get_channel_bw_limit(self, ch: Channel) -> BandwidthLimit:
        return BandwidthLimit(self._query(f"{ch.value}:BANdwidth?"))

    def set_channel_probe(self, ch: Channel, attenuation: float) -> None:
        self.invalidate_preamble_cache(ch)
        self._write(f"{ch.value}:PROBe {attenuation:g}")

    def get_channel_probe(self, ch: Channel) -> float:
        return float(self._query(f"{ch.value}:PROBe?"))

    def set_channel_display(self, ch: Channel, on: bool) -> None:
        self._write(f"SELect:{ch.value} {'ON' if on else 'OFF'}")

    def get_channel_display(self, ch: Channel) -> bool:
        return self._query(f"SELect:{ch.value}?").strip() == "1"

    # ── Horizontal ─────────────────────────────────────────────────────────────

    def set_time_scale(self, s_per_div: float) -> None:
        self.invalidate_preamble_cache()   # XINcr affects every channel
        self._write(f"HORizontal:MAIn:SCAle {s_per_div:.6E}")

    def get_time_scale(self) -> float:
        return float(self._query("HORizontal:MAIn:SCAle?"))

    def set_time_position(self, seconds: float) -> None:
        self.invalidate_preamble_cache()
        self._write(f"HORizontal:MAIn:POSition {seconds:.6E}")

    def get_time_position(self) -> float:
        return float(self._query("HORizontal:MAIn:POSition?"))

    def get_record_length(self) -> int:
        return int(self._query("HORizontal:RECOrdlength?"))

    # ── Trigger ────────────────────────────────────────────────────────────────

    def set_trigger_type(self, t: TriggerType) -> None:
        self._write(f"TRIGger:MAIn:TYPe {t.value}")

    def get_trigger_type(self) -> TriggerType:
        return TriggerType(self._query("TRIGger:MAIn:TYPe?"))

    def set_trigger_source(self, source: Union[TriggerSource, Channel]) -> None:
        self._write(f"TRIGger:MAIn:EDGE:SOUrce {source.value}")

    def get_trigger_source(self) -> TriggerSource:
        return TriggerSource(self._query("TRIGger:MAIn:EDGE:SOUrce?"))

    def set_trigger_level(self, volts: float) -> None:
        self._write(f"TRIGger:MAIn:LEVel {volts:.6E}")

    def get_trigger_level(self) -> float:
        return float(self._query("TRIGger:MAIn:LEVel?"))

    def set_trigger_to_50pct(self) -> None:
        """Set trigger level to 50% of the signal (``TRIGger:MAIn SETLevel``)."""
        self._write("TRIGger:MAIn SETLevel")

    def set_trigger_slope(self, slope: TriggerSlope) -> None:
        self._write(f"TRIGger:MAIn:EDGE:SLOpe {slope.value}")

    def get_trigger_slope(self) -> TriggerSlope:
        return TriggerSlope(self._query("TRIGger:MAIn:EDGE:SLOpe?"))

    def set_trigger_coupling(self, coupling: Union[TriggerCoupling, Coupling]) -> None:
        self._write(f"TRIGger:MAIn:EDGE:COUPling {coupling.value}")

    def get_trigger_coupling(self) -> TriggerCoupling:
        return TriggerCoupling(self._query("TRIGger:MAIn:EDGE:COUPling?"))

    def set_trigger_mode(self, mode: TriggerMode) -> None:
        self._write(f"TRIGger:MAIn:MODe {mode.value}")

    def get_trigger_mode(self) -> TriggerMode:
        return TriggerMode(self._query("TRIGger:MAIn:MODe?"))

    def force_trigger(self) -> None:
        self._write("TRIGger FORCe")

    def get_trigger_state(self) -> str:
        """Trigger state string: ARMED / AUTO / READY / SAVE / TRIGGER."""
        return self._query("TRIGger:STATe?").strip().upper()

    # ── Measurement ────────────────────────────────────────────────────────────

    def set_immed_source(self, ch: Channel) -> None:
        self._write(f"MEASUrement:IMMed:SOUrce1 {ch.value}")

    def set_immed_type(self, mtype: MeasType) -> None:
        self._write(f"MEASUrement:IMMed:TYPe {mtype.value}")

    def get_immed_value(self) -> float:
        return float(self._query("MEASUrement:IMMed:VALue?"))

    def get_immed_units(self) -> str:
        return self._query("MEASUrement:IMMed:UNIts?").strip().strip('"')

    def measure(self, ch: Channel, mtype: MeasType) -> float:
        """Set source + type, then return the immediate measurement value.

        Raises
        ------
        TDS2024CMeasurementError
            When the scope returns the no-value sentinel (~9.91e37): no signal
            or the measurement is invalid for the current waveform.
        """
        self.set_immed_source(ch)
        self.set_immed_type(mtype)
        value = self.get_immed_value()
        if abs(value) >= 9.8e37:
            raise TDS2024CMeasurementError(
                f"No valid {mtype.value} on {ch.value} (scope returned {value:.3e})"
            )
        return value

    # ── Waveform capture ───────────────────────────────────────────────────────

    def set_waveform_source(self, ch: Channel) -> None:
        self._write(f"DATa:SOUrce {ch.value}")

    def set_waveform_encoding(self, enc: WfmEncoding) -> None:
        self.invalidate_preamble_cache()
        self._write(f"DATa:ENCdg {enc.value}")

    def set_waveform_width(self, width: WfmWidth) -> None:
        self.invalidate_preamble_cache()
        self._write(f"DATa:WIDth {int(width.value)}")

    def set_waveform_start(self, point: int) -> None:
        self.invalidate_preamble_cache()
        self._write(f"DATa:STARt {int(point)}")

    def set_waveform_stop(self, point: int) -> None:
        self.invalidate_preamble_cache()
        self._write(f"DATa:STOP {int(point)}")

    def get_waveform_preamble(self) -> WaveformPreamble:
        return WaveformPreamble.from_response(self._query("WFMPre?"))

    def get_curve_raw(self) -> bytes:
        """Send ``CURVe?`` and return the raw IEEE block (binary).

        Fallback path.  Disables the read terminator during the raw read so an
        embedded ``0x0A`` data byte cannot truncate the transfer.
        """
        self._require_connection()
        self._write("CURVe?")
        old_term = self._inst.read_termination
        self._inst.read_termination = None
        try:
            return self._inst.read_raw()
        finally:
            self._inst.read_termination = old_term

    def prepare_waveform_transfer(
        self,
        encoding: WfmEncoding = WfmEncoding.RIBINARY,
        width: WfmWidth = WfmWidth.ONE_BYTE,
        start: int = 1,
        stop: int = _RECORD_LENGTH,
    ) -> None:
        """Configure the static data-transfer parameters once.

        Encoding / width / start / stop almost never change between captures,
        so setting them a single time (rather than on every capture) removes
        four command round-trips per frame.  This matters a lot for fast
        repeated capture (live streaming): pair this with :meth:`read_waveform`.
        """
        self._require_connection()
        self.set_waveform_encoding(encoding)
        self.set_waveform_width(width)
        self.set_waveform_start(start)
        self.set_waveform_stop(stop)
        self._wfm_encoding = encoding

    def read_waveform(self, ch: Channel, refresh_preamble: bool = False) -> WaveformRecord:
        """Read one waveform using the format set by :meth:`prepare_waveform_transfer`.

        Uses a cached preamble when available — ``WFMPre?`` on TDS2000B firmware
        takes ~1 s, but the preamble only changes when scaling/timebase/probe
        changes, and those setters invalidate the cache automatically.  Pass
        ``refresh_preamble=True`` to force a fresh fetch (e.g. after the user
        adjusts the scope's front-panel knobs out-of-band).

        Sends ``DATa:SOUrce`` + (cached or one-time ``WFMPre?``) + ``CURVe?``.
        """
        self._require_connection()
        self.set_waveform_source(ch)
        preamble = None if refresh_preamble else self._preamble_cache.get(ch)
        if preamble is None:
            preamble = self.get_waveform_preamble()
            self._preamble_cache[ch] = preamble
        encoding = self._wfm_encoding

        if encoding == WfmEncoding.ASCII:
            return WaveformRecord.from_preamble_and_ascii(
                ch, preamble, self._query("CURVe?")
            )

        # datatype 'b' = signed byte (RIBinary); 'B' = unsigned (RPBinary)
        datatype = "B" if encoding == WfmEncoding.RPBINARY else "b"
        try:
            samples = self._inst.query_binary_values(
                "CURVe?",
                datatype=datatype,
                is_big_endian=preamble.is_big_endian,
                container=np.array,
            )
        except pyvisa.VisaIOError as exc:
            raise TDS2024CConnectionError(f"CURVe? transfer failed: {exc}") from exc
        return WaveformRecord.from_preamble_and_samples(ch, preamble, samples)

    def capture_waveform(
        self,
        ch: Channel,
        encoding: WfmEncoding = WfmEncoding.RIBINARY,
        start: int = 1,
        stop: int = _RECORD_LENGTH,
    ) -> WaveformRecord:
        """Capture and decode a waveform from ``ch`` (one-shot: configure + read).

        For repeated capture of the same format, call
        :meth:`prepare_waveform_transfer` once then :meth:`read_waveform` per frame.
        """
        self.prepare_waveform_transfer(encoding=encoding, start=start, stop=stop)
        return self.read_waveform(ch)

    def capture_displayed_channels(
        self,
        encoding: WfmEncoding = WfmEncoding.RIBINARY,
    ) -> dict[Channel, WaveformRecord]:
        """Capture every analog channel currently shown on screen."""
        records: dict[Channel, WaveformRecord] = {}
        for ch in Channel.analog():
            try:
                if self.get_channel_display(ch):
                    records[ch] = self.capture_waveform(ch, encoding)
            except Exception:
                continue
        return records

    # ── Miscellaneous ──────────────────────────────────────────────────────────

    def autoset(self) -> None:
        """``AUTOSet EXECUTE``, then wait for completion."""
        self._write("AUTOSet EXECUTE")
        self._wait_opc(timeout_s=10.0)

    def lock_front_panel(self) -> None:
        self._write("LOCk ALL")

    def unlock_front_panel(self) -> None:
        self._write("UNLock ALL")

    def set_header(self, on: bool) -> None:
        self._write(f"HEADer {'ON' if on else 'OFF'}")

    def get_event(self) -> tuple[int, str]:
        """Return ``(code, message)`` for the oldest event in the queue."""
        code = int(self._query("EVENT?").strip())
        msg = self._query("EVMsg?").strip().strip('"')
        return code, msg

    def drain_event_queue(self, max_events: int = 20) -> list[tuple[int, str]]:
        """Read and return all pending events as ``(code, message)`` tuples."""
        events: list[tuple[int, str]] = []
        for _ in range(max_events):
            try:
                qty = int(self._query("EVQty?").strip())
            except (ValueError, TDS2024CConnectionError):
                break
            if qty <= 0:
                break
            events.append(self.get_event())
        return events

    # ── Low-level helpers ──────────────────────────────────────────────────────

    def _require_connection(self) -> None:
        if self._inst is None:
            raise TDS2024CConnectionError("Not connected — call connect() first")

    def _write(self, cmd: str) -> None:
        self._require_connection()
        try:
            self._inst.write(cmd)
        except pyvisa.VisaIOError as exc:
            raise TDS2024CConnectionError(f"Write failed ({cmd!r}): {exc}") from exc

    def _query(self, cmd: str) -> str:
        self._require_connection()
        try:
            return self._inst.query(cmd)
        except pyvisa.VisaIOError as exc:
            if exc.error_code == pyvisa.constants.StatusCode.error_timeout:
                raise TDS2024CTimeoutError(f"Query timed out ({cmd!r})") from exc
            raise TDS2024CConnectionError(f"Query failed ({cmd!r}): {exc}") from exc

    def _wait_opc(self, timeout_s: float = 10.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if self._query("*OPC?").strip() == "1":
                    return
            except TDS2024CTimeoutError:
                pass
            time.sleep(0.05)
        raise TDS2024CTimeoutError(f"*OPC? did not return 1 within {timeout_s:.1f} s")
