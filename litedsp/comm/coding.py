#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Bit-stream coding blocks: multiplicative scrambler/descrambler, CRC, convolutional encoder."""

from functools import reduce
from operator  import xor

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

# Helpers ------------------------------------------------------------------------------------------

def _parity(bits):
    return reduce(xor, bits) if bits else 0

# Multiplicative Scrambler / Descrambler -----------------------------------------------------------

@ResetInserter()
class LiteDSPScrambler(LiteXModule):
    """Self-synchronizing multiplicative scrambler ``y = x ^ y[-t1] ^ y[-t2] ...`` (bit-serial)."""
    def __init__(self, taps=(18, 23), with_csr=True):
        length = max(taps)
        self.taps = taps
        self.latency = 1
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])

        # # #

        # Handshake.
        # ----------
        adv  = Signal()        # Output slot free or being consumed.
        xfer = Signal()        # Input bit accepted this cycle.
        reg  = Signal(length)  # Last max(taps) scrambled bits (state).
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        y = Signal()
        self.comb += y.eq(self.sink.data ^ _parity([reg[t - 1] for t in taps]))
        self.sync += If(xfer, reg.eq(Cat(y, reg[:-1])))        # Feed scrambled bit back.
        self.sync += If(adv, self.source.data.eq(y), self.source.valid.eq(self.sink.valid))

@ResetInserter()
class LiteDSPDescrambler(LiteXModule):
    """Inverse of :class:`LiteDSPScrambler` ``x = y ^ y[-t1] ^ y[-t2] ...`` (self-synchronizing)."""
    def __init__(self, taps=(18, 23), with_csr=True):
        length = max(taps)
        self.taps = taps
        self.latency = 1
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])

        # # #

        # Handshake.
        # ----------
        adv  = Signal()        # Output slot free or being consumed.
        xfer = Signal()        # Input bit accepted this cycle.
        reg  = Signal(length)  # Last max(taps) received bits (state).
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        x = Signal()
        self.comb += x.eq(self.sink.data ^ _parity([reg[t - 1] for t in taps]))
        self.sync += If(xfer, reg.eq(Cat(self.sink.data, reg[:-1])))   # Feed received bit.
        self.sync += If(adv, self.source.data.eq(x), self.source.valid.eq(self.sink.valid))

# CRC ----------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCRC(LiteXModule):
    """Bit-serial MSB-first CRC; passes ``data`` through and updates the ``crc`` register.

    ``clear`` re-initializes the register to ``init``. Defaults: CRC-16-CCITT
    (poly 0x1021, init 0xFFFF).
    """
    def __init__(self, width=16, poly=0x1021, init=0xFFFF, with_csr=True):
        self.width = width
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])
        self.clear  = Signal()
        self.crc    = Signal(width, reset=init)

        # # #

        # Handshake.
        # ----------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        # MSB-first LFSR step: shift left, XOR the polynomial when (crc MSB ^ data) is set.
        fb  = Signal()
        nxt = Signal(width)
        self.comb += [
            fb.eq(self.crc[width - 1] ^ self.sink.data),
            nxt.eq(Mux(fb, (Cat(0, self.crc[:width-1]) ^ poly), Cat(0, self.crc[:width-1]))),
        ]
        self.sync += [
            If(self.clear, self.crc.eq(init)).Elif(xfer, self.crc.eq(nxt)),
        ]
        self.sync += If(adv, self.source.data.eq(self.sink.data), self.source.valid.eq(self.sink.valid))  # Data passes through (1-cycle latency).

# Convolutional Encoder ----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPConvEncoder(LiteXModule):
    """Rate-1/2 convolutional encoder (default K=7, G=[0o171, 0o133]).

    One input bit -> two coded bits on ``source.data`` (``[g1 | g0]``).
    """
    def __init__(self, constraint=7, polys=(0o171, 0o133), with_csr=True):
        self.constraint = constraint
        self.polys = polys
        self.latency = 1
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", len(polys))])

        # # #

        # Handshake.
        # ----------
        adv  = Signal()                # Output slot free or being consumed.
        xfer = Signal()                # Input bit accepted this cycle.
        reg  = Signal(constraint - 1)  # Encoder state: last K-1 input bits.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        full = Cat(self.sink.data, reg)                    # [x[n], x[n-1], ..., x[n-K+1]].
        outs = []
        for g in polys:
            bits = [full[b] for b in range(constraint) if (g >> b) & 1]  # Taps selected by generator g.
            o = Signal()
            self.comb += o.eq(_parity(bits))
            outs.append(o)
        self.sync += If(xfer, reg.eq(Cat(self.sink.data, reg[:-1])))
        self.sync += If(adv, self.source.data.eq(Cat(*outs)), self.source.valid.eq(self.sink.valid))
