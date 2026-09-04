#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""HDLC framing on bit streams: flags, bit stuffing and the X.25 FCS."""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common      import check
from litedsp.comm.design import HDLC_FLAG

FCS_RESIDUE = 0xF0B8                                                  # X.25 CRC over payload + FCS.

def _fcs_step(crc, bit):
    """One X.25 CRC-16 step (reflected 0x8408) as a Migen expression."""
    mix = crc[0] ^ bit
    return Mux(mix, (crc >> 1) ^ 0x8408, crc >> 1)

FLAG_BITS = [(HDLC_FLAG >> i) & 1 for i in range(8)]

# HDLC Framer --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPHDLCFramer(LiteXModule):
    """Payload bits (LSB first, framed by ``last``) to an HDLC bit stream: ``preamble`` opening
    flags, the bit-stuffed payload and its X.25 FCS (16 bits, inverted, LSB first), a closing
    flag; ``first`` marks the first flag bit, ``last`` the closing flag's last bit. The source
    idles between frames. ``latency = None``."""
    def __init__(self, preamble=1, with_csr=True):
        check(1 <= preamble <= 16, "expected 1 <= preamble <= 16")
        self.preamble = preamble
        self.latency  = None
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])
        self.frames = Signal(32)

        # # #

        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        bitc  = Signal(4)
        flags = Signal(max=preamble + 1)
        crc   = Signal(16, reset=0xFFFF)
        ones  = Signal(3)
        fcs   = Signal(16)
        self.comb += fcs.eq(~crc)
        stuff = Signal()
        self.comb += stuff.eq(ones == 5)
        flag_bit = Signal()
        self.comb += flag_bit.eq(Array([C(b, 1) for b in FLAG_BITS])[bitc[:3]])
        fcs_bit = Signal()
        self.comb += fcs_bit.eq(Array([fcs[i] for i in range(16)])[bitc])
        out_bit, emit = Signal(), Signal()
        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(self.sink.valid,
                NextValue(bitc, 0), NextValue(flags, 0), NextValue(crc, 0xFFFF), NextValue(ones, 0),
                NextState("FLAGS"),
            ),
        )
        fsm.act("FLAGS",
            emit.eq(1), out_bit.eq(flag_bit),
            If(adv,
                If(bitc == 7,
                    NextValue(bitc, 0),
                    If(flags == preamble - 1, NextValue(flags, 0), NextState("PAYLOAD")).Else(
                        NextValue(flags, flags + 1)),
                ).Else(
                    NextValue(bitc, bitc + 1),
                ),
            ),
        )
        fsm.act("PAYLOAD",
            If(stuff,
                emit.eq(1), out_bit.eq(0),
                If(adv, NextValue(ones, 0)),
            ).Else(
                emit.eq(self.sink.valid), out_bit.eq(self.sink.data),
                self.sink.ready.eq(adv),
                If(adv & self.sink.valid,
                    NextValue(crc, _fcs_step(crc, self.sink.data)),
                    NextValue(ones, Mux(self.sink.data, ones + 1, 0)),
                    If(self.sink.last, NextValue(bitc, 0), NextState("FCS")),
                ),
            ),
        )
        fsm.act("FCS",
            emit.eq(1),
            If(stuff,
                out_bit.eq(0),
                If(adv, NextValue(ones, 0)),
            ).Else(
                out_bit.eq(fcs_bit),
                If(adv,
                    NextValue(ones, Mux(fcs_bit, ones + 1, 0)),
                    If(bitc == 15, NextValue(bitc, 0), NextState("CLOSE")).Else(
                        NextValue(bitc, bitc + 1)),
                ),
            ),
        )
        fsm.act("CLOSE",
            emit.eq(1), out_bit.eq(flag_bit),
            If(adv,
                If(bitc == 7, NextValue(bitc, 0), NextValue(self.frames, self.frames + 1),
                   NextState("IDLE")).Else(NextValue(bitc, bitc + 1)),
            ),
        )
        self.sync += If(adv,
            self.source.valid.eq(emit), self.source.data.eq(out_bit),
            self.source.first.eq(fsm.ongoing("FLAGS") & (flags == 0) & (bitc == 0)),
            self.source.last.eq(fsm.ongoing("CLOSE") & (bitc == 7)),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._frames = CSRStatus(32, name="frames", description="Frames sent.")
        self.comb += self._frames.status.eq(self.frames)

# HDLC Deframer ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPHDLCDeframer(LiteXModule):
    """HDLC bit stream to payload bits: flag detection, unstuffing, the X.25 FCS check.

    Accepted bits (payload + FCS + the closing flag's first seven bits, stuffed zeros dropped)
    enter a 24-bit pending register; a bit leaves once 24 newer ones have arrived, so the FCS
    and flag-prefix bits never leave and the closing flag releases the last payload bit with
    ``last`` and the FCS verdict ``fcs_ok`` on it (the CRC runs seven bits behind the newest,
    covering exactly payload + FCS). Frames without payload (idle flags) are ignored, an abort
    (seven ones) drops the frame.
    Status: ``fcs_ok`` (last frame), ``frames``, ``fcs_errors``, ``aborts``, sticky
    ``fcs_error``, ``clear``. ``latency = None``."""
    def __init__(self, with_csr=True):
        self.latency = None
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1), ("fcs_ok", 1)])
        self.fcs_ok     = Signal()
        self.fcs_error  = Signal()
        self.frames     = Signal(32)
        self.fcs_errors = Signal(32)
        self.aborts     = Signal(32)
        self.clear      = Signal()

        # # #

        adv, xfer = Signal(), Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv),
                      xfer.eq(self.sink.valid & adv)]
        d = self.sink.data
        hist = Signal(7)                                        # Previous 7 line bits (oldest LSB).
        ones = Signal(3)
        flag_now, abort_now, stuffed = Signal(), Signal(), Signal()
        self.comb += [
            flag_now.eq(Cat(hist, d) == HDLC_FLAG),
            abort_now.eq((ones == 6) & d),
            stuffed.eq((ones == 5) & ~d),
        ]
        # The closing flag's first seven bits are only recognised as a flag when its last bit
        # arrives: accepted bits sit in a 24-bit register (16 FCS + 7 flag-prefix bits withheld,
        # the next is the last payload bit) and the CRC runs seven bits behind the newest one,
        # so at the flag it has consumed exactly payload + FCS.
        PEND = 24
        in_frame = Signal()
        crc      = Signal(16, reset=0xFFFF)
        pending  = Signal(PEND)
        count    = Signal(16)
        fcs_good = Signal()
        self.comb += fcs_good.eq(crc == FCS_RESIDUE)
        data_bit = Signal()
        emit     = Signal()
        lag_bit  = Signal()
        self.comb += [
            data_bit.eq(in_frame & ~flag_now & ~abort_now & ~stuffed),
            emit.eq(xfer & (count >= PEND) & (data_bit | (flag_now & in_frame))),
            lag_bit.eq(pending[PEND - 7]),                              # Seven behind the newest.
        ]
        self.sync += [
            If(xfer,
                hist.eq(Cat(hist[1:], d)),
                ones.eq(Mux(d, ones + 1, 0)),
                If(flag_now,
                    If(in_frame & (count >= PEND),
                        self.frames.eq(self.frames + 1),
                        self.fcs_ok.eq(fcs_good),
                        If(~fcs_good, self.fcs_error.eq(1),
                           self.fcs_errors.eq(self.fcs_errors + 1)),
                    ),
                    in_frame.eq(1), crc.eq(0xFFFF), count.eq(0),
                ).Elif(abort_now,
                    If(in_frame & (count != 0), self.aborts.eq(self.aborts + 1)),
                    in_frame.eq(0), count.eq(0),
                ).Elif(data_bit,
                    If(count >= 7, crc.eq(_fcs_step(crc, lag_bit))),
                    pending.eq(Cat(pending[1:], d)),
                    If(count != 0xFFFF, count.eq(count + 1)),
                ),
            ),
            If(self.clear, self.fcs_error.eq(0)),
            If(adv,
                self.source.valid.eq(emit),
                self.source.data.eq(pending[0]),
                self.source.first.eq(emit & (count == PEND) & data_bit),
                self.source.last.eq(emit & flag_now),
                self.source.fcs_ok.eq(emit & flag_now & fcs_good),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[CSRField("clear", size=1, offset=0, pulse=True, description="Clear the FCS error flag.")])
        self._status  = CSRStatus(fields=[
            CSRField("fcs_ok",    size=1, offset=0, description="The last frame's FCS matched."),
            CSRField("fcs_error", size=1, offset=1, description="Sticky: a frame failed its FCS."),
        ])
        self._frames     = CSRStatus(32, name="frames", description="Frames received.")
        self._fcs_errors = CSRStatus(32, name="fcs_errors", description="FCS failures.")
        self._aborts     = CSRStatus(32, name="aborts", description="Aborted frames.")
        self.comb += [
            self.clear.eq(self._control.fields.clear),
            self._status.fields.fcs_ok.eq(self.fcs_ok),
            self._status.fields.fcs_error.eq(self.fcs_error),
            self._frames.status.eq(self.frames), self._fcs_errors.status.eq(self.fcs_errors),
            self._aborts.status.eq(self.aborts),
        ]
