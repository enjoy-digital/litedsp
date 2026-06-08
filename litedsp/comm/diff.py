#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Differential symbol encoder / decoder (modulo-M), e.g. for DBPSK/DQPSK."""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

# Differential Encoder -----------------------------------------------------------------------------

@ResetInserter()
class DifferentialEncoder(LiteXModule):
    """``out[n] = (in[n] + out[n-1]) mod M`` (symbol indices)."""
    def __init__(self, modulus=4, with_csr=True):
        bits = (modulus - 1).bit_length()
        self.modulus = modulus
        self.latency = 1
        self.sink   = stream.Endpoint([("data", bits)])
        self.source = stream.Endpoint([("data", bits)])

        # # #

        adv  = Signal()
        xfer = Signal()
        acc  = Signal(bits + 1)
        nxt  = Signal(bits + 1)
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
            nxt.eq(acc + self.sink.data),
        ]
        wrapped = Signal(bits)
        self.comb += wrapped.eq(Mux(nxt >= modulus, nxt - modulus, nxt))
        self.sync += If(xfer, acc.eq(wrapped))
        self.sync += If(adv, self.source.data.eq(wrapped), self.source.valid.eq(self.sink.valid))

# Differential Decoder -----------------------------------------------------------------------------

@ResetInserter()
class DifferentialDecoder(LiteXModule):
    """``out[n] = (in[n] - in[n-1]) mod M`` (inverse of the encoder)."""
    def __init__(self, modulus=4, with_csr=True):
        bits = (modulus - 1).bit_length()
        self.modulus = modulus
        self.latency = 1
        self.sink   = stream.Endpoint([("data", bits)])
        self.source = stream.Endpoint([("data", bits)])

        # # #

        adv  = Signal()
        xfer = Signal()
        prev = Signal(bits)
        diff = Signal((bits + 1, True))
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
            diff.eq(self.sink.data - prev),
        ]
        wrapped = Signal(bits)
        self.comb += wrapped.eq(Mux(diff < 0, diff + modulus, diff))
        self.sync += If(xfer, prev.eq(self.sink.data))
        self.sync += If(adv, self.source.data.eq(wrapped), self.source.valid.eq(self.sink.valid))
