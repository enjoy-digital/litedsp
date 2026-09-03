#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Python drivers for LiteDSP blocks over a litex_server bridge (RemoteClient).

Each driver binds to the CSRs of one block instance at a register-name prefix (the block's
attribute path in the SoC, e.g. ``nco``, ``ddc_nco``, ``dma_writer``)::

    from litex import RemoteClient
    from litedsp.software.drivers import NCODriver, CaptureDriver, CSRReaderDriver

    bus = RemoteClient(); bus.open()
    nco = NCODriver(bus, "nco", clk_freq=100e6)
    nco.set_frequency(1e6)

``discover()`` scans a register map and instantiates a driver for every block it recognizes —
this is what the CLI and the GUI live mode build on. Drivers only touch ``bus.regs.<name>``
read()/write(), so any bus object with that shape works (including mocks in tests).
"""

import math
import time

# Helpers ------------------------------------------------------------------------------------------

def phase_inc_from_freq(freq, clk_freq, phase_bits=32):
    """Frequency (Hz, may be negative) -> NCO phase increment word."""
    return int(round(freq/clk_freq * 2**phase_bits)) & (2**phase_bits - 1)

def freq_from_phase_inc(inc, clk_freq, phase_bits=32):
    """NCO phase increment word -> frequency in Hz (signed: upper half maps to negative)."""
    if inc >= 2**(phase_bits - 1):
        inc -= 2**phase_bits
    return inc*clk_freq / 2**phase_bits

def to_signed(value, width=16):
    return value - (1 << width) if value & (1 << (width - 1)) else value

# Driver base --------------------------------------------------------------------------------------

class Driver:
    """Bind ``<prefix>_<reg>`` CSRs as attributes for each name in ``regs``."""
    regs = ()

    def __init__(self, bus, prefix, clk_freq=None):
        self.bus      = bus
        self.prefix   = prefix
        self.clk_freq = clk_freq
        for r in self.regs:
            setattr(self, r, getattr(bus.regs, f"{prefix}_{r}"))

    @classmethod
    def present(cls, bus, prefix):
        return all(hasattr(bus.regs, f"{prefix}_{r}") for r in cls.regs)

    def __repr__(self):
        return f"{type(self).__name__}('{self.prefix}')"

# Block drivers ------------------------------------------------------------------------------------

class NCODriver(Driver):
    """NCO / DDS: tune in Hz (also matches the NCO inside DDC/DUC at their prefixes)."""
    regs       = ("phase_inc",)
    phase_bits = 32

    def set_frequency(self, freq):
        assert self.clk_freq is not None, "clk_freq required to tune in Hz"
        self.phase_inc.write(phase_inc_from_freq(freq, self.clk_freq, self.phase_bits))

    def get_frequency(self):
        return freq_from_phase_inc(self.phase_inc.read(), self.clk_freq, self.phase_bits)

class FMModulatorDriver(NCODriver):
    """FM modulator: carrier in Hz (NCODriver) plus the peak deviation in Hz."""
    regs = ("phase_inc", "deviation")

    def set_deviation(self, freq):
        assert self.clk_freq is not None, "clk_freq required"
        self.deviation.write(phase_inc_from_freq(freq, self.clk_freq, self.phase_bits))

class PhaseModulatorDriver(NCODriver):
    """PM modulator: carrier in Hz plus the peak phase deviation in radians."""
    regs = ("phase_inc", "deviation")

    def set_deviation(self, radians):
        import math
        self.deviation.write(int(round(radians/(2*math.pi)*(1 << self.phase_bits))) & ((1 << self.phase_bits) - 1))

class AMModulatorDriver(NCODriver):
    """AM modulator: modulation index 0.0 .. 1.0 (and the carrier in Hz for the NCO variant)."""
    regs = ("index", "phase_inc")

    def set_index(self, index, data_width=16):
        self.index.write(max(0, min((1 << (data_width - 1)), int(round(float(index)*(1 << (data_width - 1)))))))

class CaptureDriver(Driver):
    """Scope-like Capture block: trigger and status."""
    regs = ("threshold", "force", "status")

    def set_threshold(self, level):
        self.threshold.write(level & 0xFFFF)

    def trigger(self):
        self.force.write(0)
        self.force.write(1)
        self.force.write(0)

    @property
    def armed(self):
        return bool(self.status.read() & 0b01)

    @property
    def done(self):
        return bool(self.status.read() & 0b10)

class CSRReaderDriver(Driver):
    """Bus-paced buffer readout: drain n samples to a list of complex I/Q."""
    regs       = ("data", "valid", "pop")
    data_width = 16

    def read_samples(self, n, timeout=10.0):
        samples = []
        deadline = time.monotonic() + timeout
        while len(samples) < n:
            if not self.valid.read():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"only {len(samples)}/{n} samples available")
                continue
            word = self.data.read()
            mask = (1 << self.data_width) - 1
            samples.append(complex(to_signed(word & mask, self.data_width),
                                   to_signed((word >> 16) & mask, self.data_width)))
            self.pop.write(1)
        return samples

class CaptureMemoryReader:
    """Drain a Capture buffer through its memory-mapped Wishbone window.

    The fast readout path: one bus word per sample (burstable over Etherbone) instead of
    CSRReader's read/check/pop sequence. ``region`` is the SoC memory-region name the window
    was added under (convention: ``<capture_name>_mem``).
    """
    def __init__(self, bus, region="capture_mem", data_width=16):
        self.bus        = bus
        self.region     = region
        self.data_width = data_width
        r = getattr(bus.mems, region)
        self.base, self.size = r.base, r.size

    @classmethod
    def present(cls, bus, region="capture_mem"):
        return hasattr(getattr(bus, "mems", None), region)

    def read_samples(self, n):
        assert n*4 <= self.size, f"capture window holds {self.size//4} samples"
        mask  = (1 << self.data_width) - 1
        words = self.bus.read(self.base, n)
        return [complex(to_signed(w & mask, self.data_width),
                        to_signed((w >> self.data_width) & mask, self.data_width))
                for w in words]

class DMADriver(Driver):
    """LiteX DMA register set (DMACapture's ``<name>_writer`` / DMAReplay's ``<name>_reader``)."""
    regs = ("base", "length", "enable", "done", "loop", "offset")

    def run(self, base, length, loop=False):
        self.enable.write(0)
        self.base.write(base)
        self.length.write(length)
        self.loop.write(int(loop))
        self.enable.write(1)

    def stop(self):
        self.enable.write(0)

    def wait_done(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not self.done.read():
            if time.monotonic() > deadline:
                raise TimeoutError("DMA transfer did not complete")

class SquelchDriver(Driver):
    """Squelch gate: hysteresis thresholds + open status."""
    regs = ("open_threshold", "close_threshold", "status")

    def set_thresholds(self, open_threshold, close_threshold):
        self.open_threshold.write(open_threshold)
        self.close_threshold.write(close_threshold)

    @property
    def open(self):
        return bool(self.status.read() & 0b1)

class AGCDriver(Driver):
    """AGC loop: target level + current gain readback."""
    regs = ("target", "gain")

    def set_target(self, target):
        self.target.write(target)

    def get_gain(self):
        return self.gain.read()

class FramerDriver(Driver):
    """StreamFramer: packet/frame length in samples."""
    regs = ("length",)

    def set_length(self, length):
        self.length.write(length)

class TimeCoreDriver(Driver):
    """TimeCore: read (latched, atomic) / set the sample-time counter, read the PPS latch."""
    regs = ("set_time", "latch", "time", "pps_time")

    def read_time(self):
        """Atomic multi-word read: latch the count, then read the frozen value."""
        self.latch.write(1)
        return self.time.read()

    def set(self, value):
        """Set the time counter (loaded on write of the last CSR word)."""
        self.set_time.write(value)

    def read_pps_time(self):
        """count at the last PPS rising edge (stable between PPS pulses)."""
        return self.pps_time.read()

class FrameSyncDriver(Driver):
    """Frame sync: normalized detection threshold, first-tag offset, detection counter."""
    regs           = ("threshold", "offset", "control", "count")
    threshold_frac = 14

    def set_threshold(self, normalized, offset=0):
        """Set the detection threshold (float, 1.0 = perfect correlation) and `first` offset."""
        self.threshold.write(int(round(normalized * (1 << self.threshold_frac))))
        self.offset.write(offset)

    def detections(self, clear=False):
        """Read the detection counter (optionally clearing it)."""
        n = self.count.read()
        if clear:
            self.control.write(0b1)
        return n

class GainDriver(Driver):
    """Gain block: linear gain (Q2.(N-2) mantissa + shift), bypass, saturation flag."""
    regs       = ("gain", "control", "status")
    data_width = 16

    def set_gain(self, linear, shift=0, bypass=False):
        """Set a linear gain factor (float, 1.0 = unity) with an extra ``>> shift``."""
        mantissa = int(round(linear * (1 << (self.data_width - 2))))
        self.gain.write(mantissa & ((1 << self.data_width) - 1))
        self.control.write((shift & 0b11) | (int(bypass) << 2))

    @property
    def saturated(self):
        return bool(self.status.read() & 0b1)

    def clear_saturation(self):
        self.control.write(self.control.read() | (1 << 3))   # clear_sat is a pulse field.

class MixerDriver(Driver):
    """Complex mixer: runtime up/down mode + bypass. (Heuristic signature: a lone 'control'.)"""
    regs = ("control",)

    def set_mode(self, mode):
        assert mode in ("down", "up")
        v = self.control.read()
        self.control.write((v & ~0b1) | (0 if mode == "down" else 1))

    def set_bypass(self, bypass):
        v = self.control.read()
        self.control.write((v & ~(0b11 << 8)) | ((bypass & 0b11) << 8))

class PLLDriver(Driver):
    """Carrier loop / PLL: recovered-frequency readback (PI integrator, phase units)."""
    regs = ("frequency",)

    def get_frequency_raw(self):
        return self.frequency.read()

class FIRDriver(Driver):
    """FIR filter with CSR-reloadable coefficients (``coeff_0`` ... ``coeff_{n-1}``)."""
    regs       = ("coeff_0",)
    data_width = 16

    def __init__(self, bus, prefix, clk_freq=None):
        super().__init__(bus, prefix, clk_freq)
        self.coeffs = []
        while hasattr(bus.regs, f"{prefix}_coeff_{len(self.coeffs)}"):
            self.coeffs.append(getattr(bus.regs, f"{prefix}_coeff_{len(self.coeffs)}"))

    @property
    def n_taps(self):
        return len(self.coeffs)

    def load(self, taps):
        """Load integer (or float, scaled to Q1.(N-1)) coefficients."""
        assert len(taps) == self.n_taps, f"expected {self.n_taps} taps"
        mask = (1 << self.data_width) - 1
        for csr, t in zip(self.coeffs, taps):
            if isinstance(t, float):
                t = int(round(t * (1 << (self.data_width - 1))))
            csr.write(t & mask)

    def _design_taps(self, n_taps):
        """Resolve a design tap count: explicit, or the block's ``coeff_<k>`` CSR scan.

        The FIR gateware exposes one ``coeff_<k>`` CSR per tap and no config register
        (only the polyphase FIRs have one, behind a different reload interface), so the
        scan count *is* the hardware tap count.
        """
        if n_taps is None:
            n_taps = self.n_taps
        if not n_taps:
            raise ValueError(f"'{self.prefix}': tap count not discoverable "
                             f"(no coeff_<k> CSRs found); pass n_taps explicitly")
        return n_taps

    def set_lowpass(self, cutoff, n_taps=None, data_width=16):
        """Design and load a windowed-sinc low-pass; ``cutoff`` normalized (0..0.5).

        Taps come from :func:`litedsp.filter.design.firwin_lowpass` (already quantized
        integers) and are programmed through :meth:`load`. ``n_taps`` defaults to the
        block's tap count (discovered from its ``coeff_<k>`` CSRs)::

            fir = FIRDriver(bus, "fir")
            fir.set_lowpass(0.125)   # fs/8 cutoff, all hardware taps.
        """
        from litedsp.filter.design import firwin_lowpass  # Lazy: pulls in numpy.
        self.load(firwin_lowpass(self._design_taps(n_taps), cutoff, data_width=data_width))

    def set_remez(self, f_pass, f_stop, n_taps=None, data_width=16):
        """Design and load an equiripple (Parks-McClellan) low-pass; edges normalized (0..0.5).

        Taps come from :func:`litedsp.filter.design.remez_lowpass` (``data_width`` is passed
        so quantized integers come back) and are programmed through :meth:`load`. ``n_taps``
        defaults to the block's tap count (discovered from its ``coeff_<k>`` CSRs)::

            fir = FIRDriver(bus, "fir")
            fir.set_remez(0.10, 0.15)   # Pass to 0.10 fs, stop from 0.15 fs.
        """
        from litedsp.filter.design import remez_lowpass  # Lazy: pulls in numpy.
        self.load(remez_lowpass(self._design_taps(n_taps), f_pass, f_stop,
                                data_width=data_width))

class DPDDriver(Driver):
    """DPD actuator: program the per-tap complex-gain LUTs (host-side adaptation target).

    ``load()`` takes the integer LUTs a :class:`litedsp.software.dpd.DPDAdapter` fits
    (``adapter.program(driver)`` is the usual entry point); float/complex entries are
    quantized to Q2.frac on the way in.
    """
    regs = ("config", "lut_tap", "lut_reset", "lut", "bypass")

    @property
    def n_taps(self):
        return self.config.read() & 0xFF

    @property
    def lut_depth(self):
        return (self.config.read() >> 8) & 0xFFFF

    @property
    def coeff_frac(self):
        return (self.config.read() >> 24) & 0xFF

    def load_lut(self, tap, entries, coeff_frac=None):
        """Program one tap's LUT sequentially.

        ``entries`` is either an ``(i, q)`` pair of integer arrays (signed Q2.frac, the
        adapter's native format) or a sequence of complex/float gains (1.0 = unity),
        quantized here. ``coeff_frac`` defaults to the hardware's ``config.frac``.
        """
        if coeff_frac is None:
            coeff_frac = self.coeff_frac
        width = coeff_frac + 2
        mask  = (1 << width) - 1
        if isinstance(entries, tuple) and len(entries) == 2:
            pairs = list(zip(entries[0], entries[1]))
        else:
            scale = 1 << coeff_frac
            lo, hi = -(2*scale), 2*scale - 1
            pairs = [(max(lo, min(hi, int(round(complex(e).real*scale)))),
                      max(lo, min(hi, int(round(complex(e).imag*scale))))) for e in entries]
        self.lut_tap.write(tap)
        self.lut_reset.write(1)                       # Entry pointer back to 0 (write strobes).
        for gi, gq in pairs:
            self.lut.write(((int(gq) & mask) << width) | (int(gi) & mask))

    def load(self, luts, coeff_frac=None):
        """Program all taps (``luts`` = one entry set per tap, see :meth:`load_lut`)."""
        for tap, entries in enumerate(luts):
            self.load_lut(tap, entries, coeff_frac=coeff_frac)

    def identity(self, coeff_frac=None):
        """Restore the reset LUTs (tap 0 = 1.0 + 0j, memory taps = 0): exact passthrough."""
        if coeff_frac is None:
            coeff_frac = self.coeff_frac
        n, depth = self.n_taps, self.lut_depth
        self.load([[(1.0 if m == 0 else 0.0)]*depth for m in range(n)], coeff_frac=coeff_frac)

    def set_bypass(self, bypass):
        self.bypass.write(int(bypass))

# Generic Reflected Driver ---------------------------------------------------------------------------

def make_driver(spec):
    """Build a driver class from a :class:`~litedsp.flow.metadata.BlockSpec` (CSR reflection).

    One attribute per CSR (the raw ``bus.regs`` object), plus ``set_<csr>_<field>()`` /
    ``get_<csr>_<field>()`` accessors for every named :class:`CSRField` (read-modify-write with
    the reflected mask/offset). Covers every CSR-bearing block; the handwritten drivers above
    add unit math (Hz tuning, tap design/reload, capture drain) on top.
    """
    csr_specs = list(spec.csrs)

    class GenericDriver(Driver):
        regs = tuple(c.name for c in csr_specs)

        def __repr__(self):
            return f"GenericDriver('{self.prefix}', block='{spec.key}')"

    for c in csr_specs:
        for fld in c.fields:
            mask = ((1 << fld.size) - 1) << fld.offset

            def _set(self, value, _csr=c.name, _mask=mask, _off=fld.offset):
                reg = getattr(self, _csr)
                reg.write((reg.read() & ~_mask) | ((value << _off) & _mask))

            def _get(self, _csr=c.name, _mask=mask, _off=fld.offset):
                return (getattr(self, _csr).read() & _mask) >> _off

            _set.__doc__ = fld.description or f"Set {c.name}.{fld.name}."
            _get.__doc__ = fld.description or f"Get {c.name}.{fld.name}."
            setattr(GenericDriver, f"set_{c.name}_{fld.name}", _set)
            setattr(GenericDriver, f"get_{c.name}_{fld.name}", _get)

    GenericDriver.__name__     = f"{spec.cls.__name__}Driver"
    GenericDriver.__qualname__ = GenericDriver.__name__
    GenericDriver.__doc__      = (spec.doc or spec.key) + " (generic reflected driver)."
    return GenericDriver

# Motor control ------------------------------------------------------------------------------------

class FOCDriver(Driver):
    """FOC current controller: per-unit setpoints/gains/limit, bring-up vector, mode, status."""
    regs       = ("dq_setpoint_d", "dq_setpoint_q", "dq_kp_d", "dq_ki_d", "dq_kp_q", "dq_ki_q",
                  "dq_limit", "dq_voltage_d", "dq_voltage_q", "dq_control", "dq_status")
    data_width = 16
    gain_frac  = 12

    def _pu(self, x):
        fs = (1 << (self.data_width - 1)) - 1
        return int(round(max(-1.0, min(1.0, x))*fs)) & ((1 << self.data_width) - 1)

    def _gain(self, g):
        return int(round(g*(1 << self.gain_frac))) & 0xFFFF

    def set_setpoints(self, i_d, i_q):
        """Current setpoints in per-unit (1.0 = base current)."""
        self.dq_setpoint_d.write(self._pu(i_d))
        self.dq_setpoint_q.write(self._pu(i_q))

    def set_gains(self, kp, ki, axis="dq"):
        """PI gains (float, 1.0 = 2**gain_frac) for the d, q or both axes."""
        if "d" in axis:
            self.dq_kp_d.write(self._gain(kp)); self.dq_ki_d.write(self._gain(ki))
        if "q" in axis:
            self.dq_kp_q.write(self._gain(kp)); self.dq_ki_q.write(self._gain(ki))

    def set_limit(self, v_max):
        """Voltage magnitude limit per axis (per-unit of V_dc/2)."""
        self.dq_limit.write(self._pu(abs(v_max)))

    def set_open_loop(self, enable, v_d=0.0, v_q=0.0):
        """Bring-up mode: apply the (v_d, v_q) vector directly, integrators held at zero."""
        self.dq_voltage_d.write(self._pu(v_d))
        self.dq_voltage_q.write(self._pu(v_q))
        self.dq_control.write((self.dq_control.read() & ~0b1) | int(bool(enable)))

    def clear(self):
        self.dq_control.write(self.dq_control.read() | (1 << 1) | (1 << 2))   # Pulse fields.

    @property
    def saturated(self):
        return self.dq_status.read() & 0b11

class PWMDriver(Driver):
    """Three-phase PWM: frequency / dead time in seconds, enable, fault handling, trigger."""
    regs = ("period", "dead_time", "control", "trigger", "status")

    def set_frequency(self, f_pwm):
        """PWM frequency in Hz (carrier half period = clk / (2 f_pwm) cycles)."""
        assert self.clk_freq is not None, "clk_freq required to set the frequency in Hz"
        self.period.write(int(round(self.clk_freq/(2*f_pwm))))

    def set_dead_time(self, seconds):
        assert self.clk_freq is not None, "clk_freq required to set the dead time in seconds"
        self.dead_time.write(int(round(seconds*self.clk_freq)))

    def enable(self, on=True):
        self.control.write((self.control.read() & ~0b1) | int(bool(on)))

    def clear_fault(self):
        self.control.write(self.control.read() | (1 << 1))

    def set_trigger(self, count, direction=0):
        """ADC trigger point: carrier value and slope (0: down/valley, 1: up/peak)."""
        self.trigger.write((count & 0xFFFF) | ((direction & 1) << 16))

    @property
    def fault(self):
        return bool(self.status.read() & 0b1)

class QuadratureDecoderDriver(Driver):
    """Incremental encoder: geometry setup and position / speed readback."""
    regs = ("counts_per_rev", "pole_pairs", "angle_scale", "angle_offset", "window", "control",
            "position", "speed", "status")
    angle_width, scale_frac = 16, 16

    def configure(self, counts_per_rev, pole_pairs, window_cycles=1 << 16, invert=False,
        index_enable=True):
        self.counts_per_rev.write(counts_per_rev)
        self.pole_pairs.write(pole_pairs)
        self.angle_scale.write(round((1 << (self.angle_width + self.scale_frac))/counts_per_rev))
        self.window.write(window_cycles)
        self.control.write(int(invert) | (int(index_enable) << 1))
        self._cpr, self._window = counts_per_rev, window_cycles

    def get_position(self):
        return self.position.read()

    def get_speed_rpm(self):
        """Mechanical speed in rpm from the windowed count (needs clk_freq and configure())."""
        assert self.clk_freq is not None, "clk_freq required for rpm"
        counts = to_signed(self.speed.read(), 16)
        return counts/self._cpr*(self.clk_freq/self._window)*60.0

class AngleTrackerDriver(Driver):
    """Angle tracker: loop shifts from a bandwidth in samples, offset, speed readback."""
    regs = ("gains", "angle_offset", "speed", "error")

    def set_offset_degrees(self, degrees, angle_width=16):
        """Alignment / lag-compensation offset added to the tracked angle."""
        self.angle_offset.write(int(round(degrees/360.0*(1 << angle_width))) & ((1 << angle_width) - 1))

    def set_bandwidth(self, samples):
        """Set kp/ki shifts for a lock time of ~samples (kp = log2(samples/6)/2, ki = kp + ...)."""
        import math
        ki_minus_kp = max(1, min(15, int(round(math.log2(max(6, samples)/6)))))
        kp = max(1, min(15, 3))
        self.gains.write(kp | ((kp + ki_minus_kp) << 8))

    def get_speed_raw(self):
        return self.speed.read()

# Audio drivers ------------------------------------------------------------------------------------

class VolumeDriver(Driver):
    """Per-channel gain in dB (unsigned Q5.gain_frac), faded mute mask, ramp enable."""
    regs      = ("gain0", "control", "status")
    gain_frac = 19                                   # 24-bit build (gain_frac = data_width - 5).

    def set_db(self, channel, db):
        """Gain of ``channel`` in dB (clamped to the +30 dB register range)."""
        value = int(round(10**(db/20)*(1 << self.gain_frac)))
        value = max(0, min((1 << (self.gain_frac + 5)) - 1, value))
        getattr(self.bus.regs, f"{self.prefix}_gain{channel}").write(value)

    def mute(self, mask):
        """Mute mask (bit c fades channel c to silence)."""
        self.control.write((self.control.read() & ~0xFF) | (int(mask) & 0xFF))

    def set_ramp(self, enable):
        self.control.write((self.control.read() & ~(1 << 8)) | (int(bool(enable)) << 8))

class StereoMatrixDriver(Driver):
    """2x2 mix matrix in floats (signed Q3.15): M/S encode/decode, pan, width, swap, mono."""
    regs        = ("a", "b", "c", "d", "control", "status")
    coeff_width = 18
    coeff_frac  = 15

    def _q(self, x):
        lim = (1 << (self.coeff_width - 1)) - 1
        return int(round(max(-lim, min(lim, x*(1 << self.coeff_frac))))) & ((1 << self.coeff_width) - 1)

    def set_matrix(self, a, b, c, d):
        """``L' = a L + b R``, ``R' = c L + d R``."""
        self.a.write(self._q(a)); self.b.write(self._q(b))
        self.c.write(self._q(c)); self.d.write(self._q(d))

    def ms_encode(self):
        self.set_matrix(0.5, 0.5, 0.5, -0.5)

    def ms_decode(self):
        self.set_matrix(1.0, 1.0, 1.0, -1.0)

    def pan(self, position):
        """Constant-power pan of a mono (L = R) source, ``position`` -1 (left) .. +1 (right)."""
        from litedsp.audio.design import pan_matrix
        self.set_matrix(*pan_matrix(position))

    def width(self, w):
        """Stereo width: 0 = mono, 1 = unchanged, > 1 = wider (mid/side scaling)."""
        self.set_matrix((1 + w)/2, (1 - w)/2, (1 - w)/2, (1 + w)/2)

    def swap(self):
        self.set_matrix(0.0, 1.0, 1.0, 0.0)

    def mono(self):
        self.set_matrix(0.5, 0.5, 0.5, 0.5)

class CompressorDriver(Driver):
    """Dynamics processor (compressor / limiter / gate presets) in dB and milliseconds."""
    regs = ("threshold", "slope_above", "slope_below", "attack", "release", "gr_max", "makeup",
            "control", "status", "config")

    def set_threshold_db(self, db):
        from litedsp.audio.design import log2_from_db
        self.threshold.write(log2_from_db(db, 8) & 0xFFFF)

    def set_ratio(self, ratio):
        """Compression ratio above the threshold (1.0 = off, inf = limiter)."""
        self.slope_above.write(int(round((1.0 - 1.0/ratio)*65536)))

    def set_expansion(self, ratio):
        """Expansion ratio below the threshold (1.0 = off; a gate uses e.g. 8)."""
        self.slope_below.write(int(round((ratio - 1.0)*65536)))

    def set_attack_ms(self, ms, sample_rate=48000):
        from litedsp.audio.design import time_constant_coeff
        self.attack.write(65535 if ms <= 0 else time_constant_coeff(ms, sample_rate, 16))

    def set_release_ms(self, ms, sample_rate=48000):
        from litedsp.audio.design import time_constant_coeff
        self.release.write(65535 if ms <= 0 else time_constant_coeff(ms, sample_rate, 16))

    def set_makeup_db(self, db):
        from litedsp.audio.design import log2_from_db
        self.makeup.write(log2_from_db(db, 8) & 0xFFFF)

    def set_max_reduction_db(self, db):
        from litedsp.audio.design import log2_from_db
        self.gr_max.write(log2_from_db(abs(db), 8) & 0x7FFF)

    def set_detector(self, rms=False, rms_shift=6, stereo_link=False):
        v = self.control.read() & ~0x1FF
        self.control.write(v | int(bool(rms)) | ((rms_shift & 0xF) << 4) | (int(bool(stereo_link)) << 8))

    def set_bypass(self, bypass):
        self.control.write((self.control.read() & ~(1 << 9)) | (int(bool(bypass)) << 9))

    @property
    def gain_reduction_db(self):
        """Current gain reduction in dB (Q7.8 log2 units)."""
        return (self.status.read() & 0x7FFF)/256*20*math.log10(2)

class AudioEQDriver(Driver):
    """Parametric EQ: RBJ band design in Hz/dB/Q, quantized to the block's coefficient format,
    loaded into the shadow set and committed atomically."""
    regs = ("config", "coeff_index", "coeff_value", "band_enable", "control", "status")

    def __init__(self, bus, prefix, clk_freq=None):
        super().__init__(bus, prefix, clk_freq)
        cfg = self.config.read()
        self.n_bands     = cfg & 0xFF
        self.n_channels  = (cfg >> 8) & 0xFF
        self.coeff_width = (cfg >> 16) & 0xFF
        self.frac_bits   = (cfg >> 24) & 0xFF

    def set_band(self, band, kind, f0, gain_db=0.0, q=0.7071, sample_rate=48000):
        """Design one RBJ section (``lowpass``, ``highpass``, ``bandpass``, ``notch``,
        ``allpass``, ``peaking``, ``lowshelf``, ``highshelf``) into the shadow set."""
        from litedsp.audio.design  import rbj_biquad
        from litedsp.filter.design import biquad_sos_quantize
        row = rbj_biquad(kind, f0, gain_db, q, sample_rate=sample_rate)
        (sec,), _ = biquad_sos_quantize([row], self.coeff_width, self.frac_bits)
        mask = (1 << self.coeff_width) - 1
        self.coeff_index.write(8*band)
        for k in ("b0", "b1", "b2", "a1", "a2"):
            self.coeff_value.write(sec[k] & mask)             # Auto-incrementing index.

    def set_bands(self, bands, sample_rate=48000):
        """``bands`` = list of ``(kind, f0, gain_db, q)``; loads them all, then commits."""
        for band, (kind, f0, gain_db, q) in enumerate(bands):
            self.set_band(band, kind, f0, gain_db, q, sample_rate)
        self.commit()

    def commit(self):
        self.control.write(self.control.read() | 1)

    def enable_band(self, band, enable=True):
        mask = self.band_enable.read()
        self.band_enable.write((mask | (1 << band)) if enable else (mask & ~(1 << band)))

    def set_bypass(self, bypass):
        self.control.write((self.control.read() & ~(1 << 1)) | (int(bool(bypass)) << 1))

class LFODriver(NCODriver):
    """Low-frequency oscillator: frequency in Hz at the audio sample rate (``clk_freq``),
    shape and amplitude."""
    regs   = ("phase_inc", "control", "amplitude")
    SHAPES = ("sine", "triangle", "saw", "square")

    def set_shape(self, shape):
        self.control.write((self.control.read() & ~0b11) | self.SHAPES.index(shape))

    def set_amplitude(self, amplitude):
        """Amplitude 0..1 (signed Q1.15)."""
        self.amplitude.write(int(round(max(-1.0, min(1.0, amplitude))*32767)) & 0xFFFF)

class PeakMeterDriver(Driver):
    """Peak / hold / clip meter read-back in dBFS."""
    regs       = ("control", "decay_shift", "clip_threshold", "clip", "peak0", "hold0",
                  "clip_count0", "peak_log20")
    data_width = 24

    def _reg(self, name, channel):
        return getattr(self.bus.regs, f"{self.prefix}_{name}{channel}")

    def _dbfs(self, raw):
        return -200.0 if raw == 0 else 20*math.log10(raw/(1 << (self.data_width - 1)))

    def read_dbfs(self, channel):
        """Decaying peak in dBFS from the block's log2 scan (Q(int).8)."""
        l = self._reg("peak_log2", channel).read()
        return -200.0 if l == 0 else 20*math.log10(2)*(l/256 - (self.data_width - 1))

    def read_peak(self, channel):
        return self._dbfs(self._reg("peak", channel).read())

    def read_hold(self, channel):
        return self._dbfs(self._reg("hold", channel).read())

    def clip_counts(self, n_channels):
        return [self._reg("clip_count", c).read() for c in range(n_channels)]

    def set_decay(self, shift):
        self.decay_shift.write(int(shift))

    def clear(self):
        self.control.write(1)

class LoudnessDriver(Driver):
    """ITU-R BS.1770 loudness from the block's K-weighted hop sums: momentary (400 ms),
    short-term (3 s) and gated integrated loudness in LKFS."""
    regs = ("control", "status", "sum_sq", "hop_count", "config")

    def __init__(self, bus, prefix, clk_freq=None):
        super().__init__(bus, prefix, clk_freq)
        cfg = self.config.read()
        self.n_channels  = cfg & 0xF
        self.data_width  = (cfg >> 4) & 0x3F
        self.hop_samples = (cfg >> 10) & 0x1FFFFF
        self.hops        = []

    def read_hop(self):
        """Poll: append the latest hop sum when a new one was latched; returns the hop count."""
        count = self.hop_count.read()
        if count != len(self.hops):
            self.hops.append(self.sum_sq.read())
        return count

    def _lkfs(self, mean_sq):
        fs2 = float(1 << (2*(self.data_width - 1)))
        return -0.691 + 10*math.log10(max(mean_sq, 1e-30)/(self.hop_samples*fs2))

    def hop_lkfs(self, sum_sq):
        return self._lkfs(sum_sq)

    def momentary(self, sample_rate=48000):
        """Loudness of the last 400 ms (the last ``0.4*fs/hop`` hops)."""
        n = max(1, int(round(0.4*sample_rate/self.hop_samples)))
        return self._lkfs(sum(self.hops[-n:])/max(1, len(self.hops[-n:])))

    def short_term(self, sample_rate=48000):
        n = max(1, int(round(3.0*sample_rate/self.hop_samples)))
        return self._lkfs(sum(self.hops[-n:])/max(1, len(self.hops[-n:])))

    def integrated(self, sample_rate=48000):
        """Gated integrated loudness (BS.1770-4: absolute gate -70 LKFS, relative gate -10 LU)
        over 400 ms blocks with 75 % overlap built from the hop sums."""
        n = max(1, int(round(0.4*sample_rate/self.hop_samples)))
        step = max(1, n//4)
        blocks = [sum(self.hops[k:k + n])/n for k in range(0, max(1, len(self.hops) - n + 1), step)
                  if len(self.hops[k:k + n]) == n]
        if not blocks and self.hops:                          # Shorter than one block: use it all.
            blocks = [sum(self.hops)/len(self.hops)]
        if not blocks:
            return -200.0
        abs_gated = [b for b in blocks if self._lkfs(b) > -70.0]
        if not abs_gated:
            return -200.0
        rel = self._lkfs(sum(abs_gated)/len(abs_gated)) - 10.0
        gated = [b for b in abs_gated if self._lkfs(b) > rel] or abs_gated
        return self._lkfs(sum(gated)/len(gated))

    def clear(self):
        self.hops = []
        self.control.write(1)

# Radar drivers ------------------------------------------------------------------------------------

class RangeGateDriver(Driver):
    """PRI / gate timing in seconds (``clk_freq`` = the sample rate) and CPI control."""
    regs = ("pri", "gate", "pulse", "control", "status", "pulse_count")

    def set_pri(self, seconds):
        assert self.clk_freq is not None, "clk_freq (sample rate) required"
        self.pri.write(int(round(seconds*self.clk_freq)))

    def set_gate(self, start_bins, length_bins):
        self.gate.write((int(start_bins) & 0xFFFFFF) | (int(length_bins) << 24))

    def set_pulse(self, width_bins, n_pulses):
        self.pulse.write((int(width_bins) & 0xFFFFFF) | (int(n_pulses) << 24))

    def start(self):
        self.control.write(1)                                  # enable.

    def stop(self):
        self.control.write(0)

    def trigger(self):
        self.control.write((1 << 1) | (1 << 2))                # single + trigger pulse.

    @property
    def running(self):
        return self.status.read() & 1

class CFARDriver(Driver):
    """CFAR threshold factor from a false-alarm probability, statistic mode and detection count."""
    regs = ("alpha", "control", "config", "detections", "threshold_min")

    def set_floor(self, threshold):
        self.threshold_min.write(int(threshold))

    @property
    def n_training(self):
        cfg = self.config.read()
        return (cfg & 0xFFFF) if (cfg >> 24) & 1 else 2*(cfg & 0xFF)   # 2-D box count / 1-D 2T.

    @property
    def frac_bits(self):
        return (self.config.read() >> 16) & 0xFF

    def set_alpha(self, alpha):
        self.alpha.write(int(round(float(alpha)*(1 << self.frac_bits))))

    def set_pfa(self, pfa, domain="power", n_train_cells=None):
        from litedsp.radar.design import cfar_alpha
        if n_train_cells is None:
            n_train_cells = self.n_training
        self.alpha.write(cfar_alpha(pfa, n_train_cells, domain, frac_bits=self.frac_bits))

    def set_mode(self, mode):
        self.control.write({"ca": 0, "go": 1, "so": 2}[mode] if isinstance(mode, str) else int(mode))

    @property
    def detection_count(self):
        return self.detections.read()

class OSCFARDriver(CFARDriver):
    """Ordered-statistic CFAR: the CA driver plus the rank."""
    def set_rank(self, rank):
        self.control.write(int(rank))

    def set_pfa(self, pfa, domain="power", n_train_cells=None):
        raise NotImplementedError("OS-CFAR alpha depends on the rank: use set_alpha")

class ClutterMapDriver(Driver):
    """Clutter map: threshold factor, floor and learning control."""
    regs = ("alpha", "threshold_min", "control", "config", "detections", "scans")

    @property
    def frac_bits(self):
        return (self.config.read() >> 24) & 0xFF

    def set_alpha(self, alpha):
        self.alpha.write(int(round(float(alpha)*(1 << self.frac_bits))))

    def set_floor(self, threshold):
        self.threshold_min.write(int(threshold))

    def set_learning(self, learn_all=False, freeze=False):
        self.control.write(int(bool(learn_all)) | (int(bool(freeze)) << 1))

    def clear(self):
        self.control.write(self.control.read() | (1 << 2))

    @property
    def detection_count(self):
        return self.detections.read()

class TargetListDriver(Driver):
    """Read back the last sealed target list as bin-unit dicts."""
    regs = ("config", "control", "status", "index", "range", "doppler", "data", "count", "cpi_count", "dropped")

    @property
    def frac_bits(self):
        return (self.config.read() >> 16) & 0xF

    def read_targets(self):
        scale = float(1 << self.frac_bits)
        out   = []
        for i in range(self.count.read()):
            self.index.write(i)
            out.append({"range": self.range.read()/scale, "doppler": self.doppler.read()/scale,
                        "data": self.data.read()})
        return out

    @property
    def overflow(self):
        return self.status.read() & 1

    def clear(self):
        self.control.write(1)

class TrackerDriver(Driver):
    """Alpha-beta tracker gains, gates and confirmation rules in bin units."""
    regs = ("gains", "gates", "control", "status", "config", "dropped", "cpi_count")

    @property
    def _fracs(self):
        cfg = self.config.read()
        return (cfg >> 8) & 0xF, (cfg >> 16) & 0xF                    # (frac_bits, gain_frac).

    def set_gains(self, alpha, beta):
        _, gf = self._fracs
        a = max(0, min((1 << gf), int(round(alpha*(1 << gf)))))
        b = max(0, min((1 << gf), int(round(beta*(1 << gf)))))
        self.gains.write(a | (b << 16))

    def set_tracking_index(self, lam):
        from litedsp.radar.design import alpha_beta_from_index
        self.set_gains(*alpha_beta_from_index(lam))

    def set_gates(self, range_bins, doppler_bins):
        f, _ = self._fracs
        self.gates.write(int(round(range_bins*(1 << f))) | (int(round(doppler_bins*(1 << f))) << 16))

    def set_confirm(self, confirm_hits, max_misses, emit_tentative=False):
        self.control.write((int(confirm_hits) & 0xF) | ((int(max_misses) & 0xF) << 4) | (int(bool(emit_tentative)) << 8))

    def clear(self):
        self.control.write(self.control.read() | (1 << 9))

    @property
    def active(self):
        return self.status.read() & 0x1F

    @property
    def confirmed(self):
        return (self.status.read() >> 8) & 0x1F

class KalmanTrackerDriver(TrackerDriver):
    """Kalman tracker: the tracker driver with process / measurement noise instead of gains."""
    regs = TrackerDriver.regs + ("noise", "p_vel0", "cov", "cov_status")

    def set_noise(self, q_bins2, r_bins2):
        _, cf = self._fracs
        q = max(0, min(0xFFFF, int(round(q_bins2*(1 << cf)))))
        r = max(1, min(0xFFFF, int(round(r_bins2*(1 << cf)))))
        self.noise.write(q | (r << 16))

    def set_tracking_index(self, lam, r_bins2=0.5):
        self.set_noise(lam*lam*r_bins2, r_bins2)

    def set_gains(self, alpha, beta):
        raise NotImplementedError("Kalman gains follow from set_noise / set_tracking_index")

    @property
    def cov_sat(self):
        return self.cov_status.read() & 1

    def clear_cov_sat(self):
        self.cov.write(1)

class BeamformerDriver(Driver):
    """Load steering weights (host maths in ``litedsp.radar.design``) and commit them atomically."""
    regs = ("weight_index", "weight", "control", "status", "config")

    @property
    def geometry(self):
        cfg = self.config.read()
        return cfg & 0x1F, (cfg >> 8) & 0xF, (cfg >> 16) & 0x1F         # (n_elements, n_beams, weight_frac).

    def set_weights(self, beam, real, imag):
        n, _, _ = self.geometry
        for e, (re, im) in enumerate(zip(real, imag)):
            self.weight_index.write(beam*n + e)
            self.weight.write((int(re) & 0xFFFF) | ((int(im) & 0xFFFF) << 16))

    def set_steering(self, beam, angle_deg, d_over_lambda=0.5, taper="rect"):
        from litedsp.radar.design import steering_weights
        n, _, wf = self.geometry
        self.set_weights(beam, *steering_weights(n, angle_deg, d_over_lambda, taper, weight_frac=wf))

    def commit(self):
        self.control.write(1)

    @property
    def saturated(self):
        return (self.status.read() >> 1) & 1

class TVGDriver(Driver):
    """Time-varying gain law in dB (spreading loss per decade, absorption per bin, offset)."""
    regs = ("g0", "k_log", "k_lin", "control", "status", "config")

    @property
    def gain_frac(self):
        return self.config.read() & 0xF

    def set_law(self, db_per_decade=40.0, alpha_db_per_bin=0.0, g0_db=0.0):
        from litedsp.radar.design import tvg_coefficients
        g0, k_log, k_lin = tvg_coefficients(db_per_decade, alpha_db_per_bin, g0_db, gain_frac=self.gain_frac)
        mask = 0xFFFFFFFF
        self.g0.write(g0 & mask); self.k_log.write(k_log & mask); self.k_lin.write(k_lin & mask)

    def set_bypass(self, bypass=True):
        self.control.write(int(bool(bypass)))

    @property
    def saturated(self):
        return self.status.read() & 1

class PulseGeneratorDriver(Driver):
    """Chirp pulse train in physical units (``clk_freq`` = the sample rate)."""
    regs = ("start", "rate", "timing", "pri", "control", "status", "pulse_count")

    def set_waveform(self, bandwidth_hz, pulse_s, pri_s, n_pulses=16, phase_bits=32):
        from litedsp.radar.waveform import chirp_words
        assert self.clk_freq is not None, "clk_freq (sample rate) required"
        pulse_len = int(round(pulse_s*self.clk_freq))
        pri       = int(round(pri_s*self.clk_freq))
        start, rate = chirp_words(bandwidth_hz/self.clk_freq, pulse_len, phase_bits)
        self.start.write(start); self.rate.write(rate)
        self.timing.write((pulse_len & 0xFFFF) | ((int(n_pulses) & 0xFFFF) << 16))
        self.pri.write(pri)

    def start_train(self):
        self.control.write(1)

    def stop(self):
        self.control.write(0)

    def single(self):
        self.control.write((1 << 1) | (1 << 2))

    @property
    def running(self):
        return self.status.read() & 1

class PixelPatternDriver(Driver):
    """Test-pattern source: mode, geometry, constant colour, one-shot / continuous."""
    regs  = ("control", "geometry", "const", "status", "frames")
    MODES = ("const", "ramp", "bars", "checker", "counter", "bayer")

    def set_mode(self, mode, enable=None):
        m = self.MODES.index(mode) if isinstance(mode, str) else int(mode)
        cur = self.control.read()
        en  = (cur & 1) if enable is None else int(bool(enable))
        self.control.write(en | (m << 4))

    def set_geometry(self, width, height):
        self.geometry.write((int(width) & 0xFFFF) | (int(height) << 16))

    def set_const(self, r, g=None, b=None):
        g = r if g is None else g
        b = r if b is None else b
        self.const.write((int(r) & 0xFF) | ((int(g) & 0xFF) << 8) | ((int(b) & 0xFF) << 16))

    def trigger(self):
        self.control.write((self.control.read() & ~1) | (1 << 1))

    def start(self):
        self.control.write(self.control.read() | 1)

    def stop(self):
        self.control.write(self.control.read() & ~1)

class ImageKernelDriver(Driver):
    """2-D kernel coefficients (row-major), presets, shift / offset and frame-atomic commit."""
    regs = ("coeff_index", "coeff_value", "shift_offset", "control", "status", "config")

    @property
    def geometry(self):
        cfg = self.config.read()
        return cfg & 0xF, (cfg >> 8) & 0x1F                           # (kernel_size, coeff_width).

    def set_coefficients(self, coefficients, shift=None, offset=None):
        K, cw = self.geometry
        assert len(coefficients) == K*K, f"expected {K*K} coefficients"
        self.coeff_index.write(0)
        for c in coefficients:
            self.coeff_value.write(int(c) & ((1 << cw) - 1))
        if shift is not None or offset is not None:
            cur = self.shift_offset.read()
            sh  = (cur & 0xF) if shift is None else int(shift)
            off = ((cur >> 8) & 0x1FF) if offset is None else (int(offset) & 0x1FF)
            self.shift_offset.write(sh | (off << 8))

    def set_preset(self, name, data_width=8):
        from litedsp.image.design import kernel_preset
        coefficients, shift, offset = kernel_preset(name, self.geometry[0], data_width)
        self.set_coefficients(coefficients, shift, offset)

    def commit(self, now=False):
        self.control.write((self.control.read() & 0b100) | (1 << (1 if now else 0)))

    def set_bypass(self, bypass=True):
        self.control.write((self.control.read() & ~0b100) | (int(bool(bypass)) << 2))

    @property
    def saturated(self):
        return (self.status.read() >> 1) & 1

class RankFilterDriver(Driver):
    """3x3 rank filter: median / erode / dilate or an explicit rank."""
    regs  = ("control", "status")
    MODES = {"erode": 0, "median": 4, "dilate": 8}

    def set_mode(self, mode):
        rank = self.MODES[mode] if isinstance(mode, str) else int(mode)
        self.control.write((self.control.read() & ~0xF) | (rank & 0xF))

    def set_bypass(self, bypass=True):
        self.control.write((self.control.read() & ~(1 << 4)) | (int(bool(bypass)) << 4))

class ThresholdDriver(Driver):
    """Threshold levels (hysteresis) and inversion."""
    regs = ("levels", "control", "bypass")

    def set_levels(self, high, low=None):
        low = high if low is None else low
        assert 0 <= low <= high, "expected 0 <= low <= high"
        self.levels.write((int(high) & 0xFFFF) | (int(low) << 16))

    def set_invert(self, invert=True):
        self.control.write(int(bool(invert)))

class PixelGainDriver(Driver):
    """Per-channel gain / offset: white balance, brightness and contrast in code units."""
    regs = ("gain0", "gain1", "gain2", "control", "status")

    def __init__(self, bus, name, clk_freq=None, gain_frac=8, data_width=8):
        Driver.__init__(self, bus, name, clk_freq)
        self.gain_frac, self.data_width = gain_frac, data_width

    def set_gains(self, gains, offsets=(0, 0, 0)):
        for c, (g, o) in enumerate(zip(gains, offsets)):
            word = max(0, min((1 << (self.gain_frac + 4)) - 1, int(round(g*(1 << self.gain_frac)))))
            getattr(self, f"gain{c}").write(word | ((int(round(o)) & ((1 << (self.data_width + 1)) - 1)) << 16))

    def set_brightness_contrast(self, brightness=0.0, contrast=1.0):
        """``y = contrast * (x - mid) + mid + brightness * full`` on every channel."""
        full = (1 << self.data_width) - 1
        mid  = full/2
        off  = mid - contrast*mid + brightness*full
        self.set_gains((contrast,)*3, (off,)*3)

    def set_white_balance(self, r_gain, b_gain, g_gain=1.0):
        self.set_gains((r_gain, g_gain, b_gain))

    def gray_world(self, means):
        """Gains that equalise the channel means (``means`` = (r, g, b))."""
        g = float(means[1])
        self.set_white_balance(g/max(float(means[0]), 1e-9), g/max(float(means[2]), 1e-9))

class PixelLUTDriver(Driver):
    """Tone-curve tables: gamma, contrast, histogram equalisation, or a raw table."""
    regs = ("lut_addr", "lut_data", "bypass")

    def load(self, table, channel=3):
        self.lut_addr.write(0)
        for v in table:
            self.lut_data.write((int(v) & 0xFFFF) | ((int(channel) & 3) << 16))

    def set_gamma(self, gamma=2.2, data_width=8, channel=3):
        from litedsp.image.design import gamma_table
        self.load(gamma_table(gamma, data_width), channel)

    def equalize(self, histogram, data_width=8, channel=3):
        from litedsp.image.design import equalize_table
        self.load(equalize_table(histogram, data_width), channel)

class ColorDriver(Driver):
    """Colour matrix presets / raw matrices with the frame-atomic commit."""
    regs = ("coeff_index", "coeff_value", "control", "status", "config")

    def set_matrix(self, coefficients, in_offsets=(0, 0, 0), out_offsets=(0, 0, 0)):
        entries = list(coefficients)
        self.coeff_index.write(0)
        for v in entries:
            self.coeff_value.write(int(v) & 0xFFFF)
        self.coeff_index.write(9)
        for v in in_offsets:
            self.coeff_value.write(int(v) & 0xFFFF)
        self.coeff_index.write(12)
        for v in out_offsets:
            self.coeff_value.write(int(v) & 0xFFFF)

    def set_preset(self, name, data_width=8):
        from litedsp.image.design import color_preset
        cf = (self.config.read() >> 8) & 0x1F
        self.set_matrix(*color_preset(name, data_width, cf))

    def commit(self, now=False):
        self.control.write(1 << (1 if now else 0))

    @property
    def saturated(self):
        return (self.status.read() >> 1) & 1

class CropDriver(Driver):
    """Region of interest, applied at the next frame."""
    regs = ("origin", "size", "control", "status")

    def set_roi(self, x0, y0, width, height):
        self.origin.write((int(x0) & 0xFFFF) | (int(y0) << 16))
        self.size.write((int(width) & 0xFFFF) | (int(height) << 16))
        self.control.write(1)

class PixelStatsDriver(Driver):
    """Frame statistics readback for exposure / white-balance loops."""
    regs = ("control", "zone_size", "sum", "minmax", "count", "zone_index", "zone_sum")

    def read_frame(self):
        mm = self.minmax.read()
        count = self.count.read()
        s = self.sum.read()
        return dict(sum=s, min=mm & 0xFFFF, max=(mm >> 16) & 0xFFFF, count=count, mean=(s/count if count else 0.0))

    def zones(self, n):
        out = []
        for k in range(n*n):
            self.zone_index.write(k)
            out.append(self.zone_sum.read())
        return out

    def exposure_error(self, target, data_width=8):
        """Log2 ratio of the target mean to the frame mean (positive = under-exposed)."""
        import math
        mean = self.read_frame()["mean"]
        return math.log2(target/max(mean, 1e-9))

class AlphaBlendDriver(Driver):
    """Blend factor 0.0 .. 1.0 (256 = 1.0)."""
    regs = ("alpha",)

    def set_alpha(self, alpha):
        self.alpha.write(max(0, min(256, int(round(float(alpha)*256)))))

class BoxOverlayDriver(Driver):
    """Box table (x0, y0, x1, y1, colour, enable) with a frame-atomic commit."""
    regs = ("box_index", "box_origin", "box_corner", "box_color", "control", "status")

    def set_boxes(self, boxes, n_channels=3, data_width=8):
        for k, (x0, y0, x1, y1, color, enable) in enumerate(boxes):
            packed = int(color) if n_channels == 1 else sum(int(v) << (i*data_width) for i, v in enumerate(color))
            self.box_index.write(k)
            self.box_origin.write((int(x0) & 0xFFFF) | (int(y0) << 16))
            self.box_corner.write((int(x1) & 0xFFFF) | (int(y1) << 16))
            self.box_color.write((packed & 0x7FFFFFFF) | (int(bool(enable)) << 31))
        return self

    def commit(self):
        self.control.write((self.control.read() & ~1) | 1)

    def set_thickness(self, thickness):
        self.control.write((self.control.read() & ~0xF0) | ((int(thickness) & 0xF) << 4))

# Registry-key -> handwritten driver (preferred over the generic one in manifest discovery).
TYPED = {
    "nco":      NCODriver,
    "fm_modulator": FMModulatorDriver, "pm_modulator": PhaseModulatorDriver, "am_modulator": AMModulatorDriver,
    "capture":  CaptureDriver,
    "csr_sink": CSRReaderDriver,
    "squelch":  SquelchDriver,
    "agc":      AGCDriver,
    "framer":   FramerDriver,
    "frame_sync": FrameSyncDriver,
    "fir_real": FIRDriver, "fir_complex": FIRDriver,
    "fir_decimator": FIRDriver, "fir_interpolator": FIRDriver,
    "gain":     GainDriver,
    "mixer":    MixerDriver,
    "carrier_loop": PLLDriver,
    "dpd":      DPDDriver,
    "foc":      FOCDriver,
    "pwm":      PWMDriver,
    "quadrature_decoder": QuadratureDecoderDriver,
    "angle_tracker": AngleTrackerDriver,
    "volume":        VolumeDriver,
    "stereo_matrix": StereoMatrixDriver,
    "compressor":    CompressorDriver, "limiter": CompressorDriver, "noise_gate": CompressorDriver,
    "audio_eq":      AudioEQDriver,
    "lfo":           LFODriver,
    "peak_meter":    PeakMeterDriver,
    "loudness":      LoudnessDriver,
    "range_gate":    RangeGateDriver,
    "pulse_generator": PulseGeneratorDriver,
    "pixel_pattern": PixelPatternDriver,
    "kernel_2d":     ImageKernelDriver, "kernel_5x5": ImageKernelDriver, "gaussian_blur": ImageKernelDriver,
    "sharpen":       ImageKernelDriver, "laplacian": ImageKernelDriver,
    "rank_filter":   RankFilterDriver, "erode": RankFilterDriver, "dilate": RankFilterDriver,
    "threshold":     ThresholdDriver,
    "pixel_gain":    PixelGainDriver,
    "pixel_lut":     PixelLUTDriver, "gamma": PixelLUTDriver,
    "color_matrix":  ColorDriver, "rgb_to_ycbcr": ColorDriver, "ycbcr_to_rgb": ColorDriver, "rgb_to_gray": ColorDriver,
    "crop":          CropDriver,
    "pixel_stats":   PixelStatsDriver,
    "alpha_blend":   AlphaBlendDriver, "mask_blend": AlphaBlendDriver,
    "box_overlay":   BoxOverlayDriver,
    "ca_cfar":       CFARDriver,
    "cfar_2d":       CFARDriver,
    "os_cfar":       OSCFARDriver,
    "clutter_map":   ClutterMapDriver,
    "target_list":   TargetListDriver,
    "alpha_beta_tracker": TrackerDriver,
    "kalman_tracker": KalmanTrackerDriver,
    "beamformer":    BeamformerDriver,
    "tvg":           TVGDriver,
}

# Discovery ----------------------------------------------------------------------------------------

DRIVERS = [NCODriver, FMModulatorDriver, PhaseModulatorDriver, AMModulatorDriver, CaptureDriver, CSRReaderDriver, DMADriver, SquelchDriver, AGCDriver,
           FramerDriver, FrameSyncDriver, FIRDriver, GainDriver, MixerDriver, PLLDriver,
           TimeCoreDriver, DPDDriver, FOCDriver, PWMDriver, QuadratureDecoderDriver,
           AngleTrackerDriver, VolumeDriver, StereoMatrixDriver, CompressorDriver, AudioEQDriver,
           LFODriver, PeakMeterDriver, LoudnessDriver, RangeGateDriver, CFARDriver, OSCFARDriver, ClutterMapDriver, TargetListDriver, TrackerDriver, KalmanTrackerDriver, BeamformerDriver, TVGDriver, PulseGeneratorDriver, PixelPatternDriver, ImageKernelDriver, RankFilterDriver, ThresholdDriver,
           PixelGainDriver, PixelLUTDriver, ColorDriver, CropDriver, PixelStatsDriver, AlphaBlendDriver,
           BoxOverlayDriver]

def _reg_names(bus):
    return [k for k, v in vars(bus.regs).items() if hasattr(v, "read")]

def discover(bus, clk_freq=None, manifest=None):
    """Return ``{prefix: driver}`` for every block found on the bus.

    With ``manifest`` (a ``{instance_prefix: registry_key}`` dict, or a path to the
    ``blocks.json`` the flow IP generator emits next to ``csr.csv``), discovery is exact:
    every listed instance gets its typed driver (TYPED) or a generic reflected one
    (:func:`make_driver`). Without a manifest, falls back to register-signature scanning;
    when several signatures match a prefix, the most specific (most registers) wins.
    """
    if manifest is not None:
        import json
        if isinstance(manifest, str):
            with open(manifest, encoding="utf-8") as fp:
                manifest = json.load(fp)
        from litedsp.flow import registry as flow_registry
        specs = flow_registry.registry()
        found = {}
        for prefix, key in manifest.items():
            candidates = []
            if key in TYPED:
                candidates.append(TYPED[key])
            if key in specs:
                candidates.append(make_driver(specs[key]))  # Generic reflected fallback.
            for cls in candidates:
                if cls.regs and cls.present(bus, prefix):
                    found[prefix] = cls(bus, prefix, clk_freq=clk_freq)
                    break
        return found
    names = _reg_names(bus)
    found = {}
    for cls in sorted(DRIVERS, key=lambda c: len(c.regs)):
        key = cls.regs[0]
        for name in names:
            if not name.endswith(f"_{key}"):
                continue
            prefix = name[:-len(key) - 1]
            if cls.present(bus, prefix):
                found[prefix] = cls(bus, prefix, clk_freq=clk_freq)
    return found
