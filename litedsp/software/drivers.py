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

# Registry-key -> handwritten driver (preferred over the generic one in manifest discovery).
TYPED = {
    "nco":      NCODriver,
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
}

# Discovery ----------------------------------------------------------------------------------------

DRIVERS = [NCODriver, CaptureDriver, CSRReaderDriver, DMADriver, SquelchDriver, AGCDriver,
           FramerDriver, FrameSyncDriver, FIRDriver, GainDriver, MixerDriver, PLLDriver,
           TimeCoreDriver]

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
