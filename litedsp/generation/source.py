#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Signal sources: linear-FM chirp, AWGN noise, and a RAM replay (AWG)."""

import math

from functools import reduce

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout

# Chirp (Linear FM) --------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPChirp(LiteXModule):
    """Linear-FM (chirp) I/Q generator: the instantaneous frequency ramps by ``rate`` per sample.

    A phase accumulator driven by a frequency accumulator (``freq += rate``; ``phase += freq``)
    feeding cos/sin ROMs. Useful for radar and calibration sweeps.

    Parameters
    ----------
    lut_depth : int
        Cos/sin lookup ROM depth (power of two); sets the phase-quantization spur floor.
    """
    def __init__(self, phase_bits=32, data_width=16, lut_depth=1024, with_csr=True):
        self.phase_bits = phase_bits
        self.source = stream.Endpoint(iq_layout(data_width))
        self.start  = Signal(phase_bits)             # Initial frequency word.
        self.rate   = Signal((phase_bits, True))     # Frequency increment per sample.

        # # #

        # Cos/Sin ROMs.
        # -------------
        addr_bits = int(math.log2(lut_depth))
        scale     = (1 << (data_width - 1)) - 1
        cos = Memory(data_width, lut_depth, init=[int(round(math.cos(2*math.pi*n/lut_depth)*scale)) & ((1 << data_width)-1) for n in range(lut_depth)])
        sin = Memory(data_width, lut_depth, init=[int(round(math.sin(2*math.pi*n/lut_depth)*scale)) & ((1 << data_width)-1) for n in range(lut_depth)])
        crp, srp = cos.get_port(async_read=True), sin.get_port(async_read=True)  # Async read: output follows the phase register.
        self.specials += cos, sin, crp, srp

        # Frequency/Phase Accumulators.
        # -----------------------------
        phase = Signal(phase_bits)   # Phase accumulator (phase += freq).
        freq  = Signal(phase_bits)   # Frequency accumulator (freq += rate).
        ce    = Signal()             # Advance when output can accept a new sample.
        valid = Signal()             # Free-running: stays asserted after the first sample.
        self.comb += ce.eq(self.source.ready | ~self.source.valid)
        self.sync += If(ce,
            freq.eq(Mux(valid, freq + self.rate, self.start)),  # Frequency ramps from `start`.
            phase.eq(phase + freq),
            valid.eq(1),
        )

        # Output.
        # -------
        self.comb += [
            crp.adr.eq(phase[phase_bits - addr_bits:]),
            srp.adr.eq(phase[phase_bits - addr_bits:]),
            self.source.valid.eq(valid),
            self.source.i.eq(crp.dat_r),
            self.source.q.eq(srp.dat_r),
        ]

        # CSR.
        # ----
        if with_csr:
            self._start = CSRStorage(phase_bits, description="Chirp start frequency word.")
            self._rate  = CSRStorage(phase_bits, description="Chirp frequency rate per sample.")
            self.comb += [self.start.eq(self._start.storage), self.rate.eq(self._rate.storage)]

# AWGN Noise ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPNoiseSource(LiteXModule):
    """Approximate-Gaussian (AWGN) complex noise via summed xorshift32 streams (CLT).

    ``n_sum`` independent xorshift32 PRNGs per axis; their signed top bits are summed and scaled
    so the output approaches a normal distribution (Irwin-Hall). For BER/AWGN testbenches.

    Parameters
    ----------
    n_sum : int
        Independent xorshift32 streams summed per axis (>= 1); larger values make the
        distribution more Gaussian at the cost of one 32-bit PRNG each (registers + XORs).
    seed : int
        Base seed from which every PRNG's initial state is derived; the noise sequence is
        deterministic and reproducible for a given seed.
    """
    def __init__(self, data_width=16, n_sum=16, shift=2, seed=0x1234567, with_csr=True):
        check(n_sum >= 1, "expected n_sum >= 1")
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Handshake.
        # ----------
        ce = Signal()
        self.comb += ce.eq(self.source.ready | ~self.source.valid)

        # Xorshift32 Sum.
        # ---------------
        # Sum n_sum independent xorshift32 streams for one axis; the Irwin-Hall
        # sum approaches a Gaussian as n_sum grows.
        def axis(base):
            acc = Signal((data_width + n_sum.bit_length() + 1, True))  # Headroom for the n_sum-term sum.
            terms = []
            for k in range(n_sum):
                x  = Signal(32, reset=(seed + base*0x9E3779B1 + k*0x85EBCA77) & 0xffffffff | 1)
                a  = Signal(32)
                b  = Signal(32)
                nx = Signal(32)
                self.comb += [a.eq(x ^ (x << 13)), b.eq(a ^ (a >> 17)), nx.eq(b ^ (b << 5))]
                self.sync += If(ce, x.eq(nx))
                s = Signal((data_width, True))
                self.comb += s.eq(x[32 - data_width:])     # Top bits as a signed sample.
                terms.append(s)
            self.comb += acc.eq(reduce(lambda p, q: p + q, terms))
            return acc

        # Output.
        # -------
        out_i = Signal((data_width, True))
        out_q = Signal((data_width, True))
        self.comb += [out_i.eq(axis(0) >> shift), out_q.eq(axis(1) >> shift)]  # Shift sets the output amplitude (sigma).
        self.sync += If(ce,
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            self.source.valid.eq(1),
        )

# RAM Replay (AWG) ---------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPReplay(LiteXModule):
    """Replay a preloaded I/Q waveform from RAM, looping. ``samples`` is a list of (i, q)."""
    def __init__(self, samples, data_width=16, with_csr=True):
        n = len(samples)
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Memory.
        # -------
        # One word per sample: Q packed in the high half, I in the low half.
        mask = (1 << data_width) - 1
        mem  = Memory(2*data_width, n, init=[((q & mask) << data_width) | (i & mask) for (i, q) in samples])
        rp   = mem.get_port(async_read=True)
        self.specials += mem, rp

        # Output.
        # -------
        addr = Signal(max=n)
        self.comb += [
            rp.adr.eq(addr),
            self.source.valid.eq(1),                 # Always valid: asynchronous RAM read.
            self.source.i.eq(rp.dat_r[:data_width]),
            self.source.q.eq(rp.dat_r[data_width:]),
            self.source.first.eq(addr == 0),
            self.source.last.eq(addr == (n - 1)),
        ]
        # Advance/wrap the address on each transfer (valid is constant, so ready == transfer).
        self.sync += If(self.source.ready,
            If(addr == (n - 1), addr.eq(0)).Else(addr.eq(addr + 1)),
        )
