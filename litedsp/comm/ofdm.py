#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""OFDM cyclic-prefix insertion/removal.

``LiteDSPCPInsert`` buffers one ``fft_size`` symbol and emits it with its last ``cp_len`` samples
prepended (TX side, between the IFFT and the DAC front-end); the input is stalled while a
symbol drains, so upstream backpressure does the rate expansion. ``LiteDSPCPRemove`` is the RX
counterpart: drop ``cp_len`` samples, pass ``fft_size`` (framed with ``first``/``last`` for the
FFT). Symbol boundaries are counted from the first sample after reset — align upstream (frame
detector / ``first`` markers) before these blocks.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# CP Insert ----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCPInsert(LiteXModule):
    """Insert a cyclic prefix: N-sample symbols in, (CP + N)-sample symbols out."""
    def __init__(self, fft_size=64, cp_len=16, data_width=16, with_csr=True):
        assert 0 < cp_len < fft_size
        self.fft_size = fft_size
        self.cp_len   = cp_len
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Memory.
        # -------
        mem = Memory(2*data_width, fft_size)    # One I/Q symbol buffer ({q, i} packed).
        wp  = mem.get_port(write_capable=True)  # Fill port (FILL state).
        rp  = mem.get_port(async_read=True)     # Emit port (async read: data valid in the same EMIT cycle).
        self.specials += mem, wp, rp

        # Signals.
        # --------
        wptr    = Signal(max=fft_size)           # Fill position.
        rptr    = Signal(max=fft_size)           # Emit position (starts in the tail, wraps to 0).
        out_cnt = Signal(max=fft_size + cp_len)  # Emitted samples in the current CP + N symbol.

        # Datapath.
        # ---------
        self.comb += [
            wp.adr.eq(wptr),
            wp.dat_w.eq(Cat(self.sink.i[:data_width], self.sink.q[:data_width])),
            rp.adr.eq(rptr),
            self.source.i.eq(rp.dat_r[:data_width]),
            self.source.q.eq(rp.dat_r[data_width:]),
        ]

        # FSM.
        # ----
        self.fsm = fsm = FSM(reset_state="FILL")
        fsm.act("FILL",  # Buffer one full N-sample symbol; input flows freely.
            self.sink.ready.eq(1),
            wp.we.eq(self.sink.valid),
            If(self.sink.valid,
                If(wptr == (fft_size - 1),
                    NextValue(wptr, 0),
                    NextValue(rptr, fft_size - cp_len),   # Start with the tail (the prefix).
                    NextValue(out_cnt, 0),
                    NextState("EMIT"),
                ).Else(
                    NextValue(wptr, wptr + 1),
                )
            )
        )
        fsm.act("EMIT",  # Stream CP + N samples; input stalled (upstream backpressure does the rate expansion).
            self.source.valid.eq(1),
            self.source.first.eq(out_cnt == 0),
            self.source.last.eq(out_cnt == (fft_size + cp_len - 1)),
            If(self.source.ready,
                If(out_cnt == (fft_size + cp_len - 1),
                    NextState("FILL"),
                ).Else(
                    NextValue(out_cnt, out_cnt + 1),
                    # Prefix wraps from the tail into the symbol proper.
                    If(rptr == (fft_size - 1), NextValue(rptr, 0)).Else(NextValue(rptr, rptr + 1)),
                )
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("fft_size", size=16, description="Symbol length N."),
            CSRField("cp_len",   size=16, description="Cyclic-prefix length."),
        ])
        self.comb += [
            self._config.fields.fft_size.eq(self.fft_size),
            self._config.fields.cp_len.eq(self.cp_len),
        ]

# CP Remove ----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCPRemove(LiteXModule):
    """Remove a cyclic prefix: (CP + N)-sample symbols in, framed N-sample symbols out."""
    def __init__(self, fft_size=64, cp_len=16, data_width=16, with_csr=True):
        assert 0 < cp_len < fft_size
        self.fft_size = fft_size
        self.cp_len   = cp_len
        self.latency  = 0  # Combinational pass-through on kept samples.
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Datapath.
        # ---------
        cnt      = Signal(max=fft_size + cp_len)  # Position within the CP + N symbol.
        in_cp    = Signal()                       # Current sample is prefix (dropped).
        xfer     = Signal()                       # Input sample accepted this cycle.
        self.comb += [
            in_cp.eq(cnt < cp_len),
            self.source.valid.eq(self.sink.valid & ~in_cp),
            self.sink.ready.eq(Mux(in_cp, 1, self.source.ready)),  # Drop the prefix freely.
            xfer.eq(self.sink.valid & self.sink.ready),
            self.source.i.eq(self.sink.i),
            self.source.q.eq(self.sink.q),
            self.source.first.eq(cnt == cp_len),
            self.source.last.eq(cnt == (fft_size + cp_len - 1)),
        ]
        self.sync += If(xfer,
            If(cnt == (fft_size + cp_len - 1), cnt.eq(0)).Else(cnt.eq(cnt + 1)),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("fft_size", size=16, description="Symbol length N."),
            CSRField("cp_len",   size=16, description="Cyclic-prefix length."),
        ])
        self.comb += [
            self._config.fields.fft_size.eq(self.fft_size),
            self._config.fields.cp_len.eq(self.cp_len),
        ]
