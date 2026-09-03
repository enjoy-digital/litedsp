#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Corner turn: fast-time pulses (range bins) to slow-time columns (pulses per range bin)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common           import check, iq_layout
from litedsp.comm.interleaver import _LiteDSPBlockPermuter

# Corner Turn --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCornerTurn(LiteXModule):
    """Transpose a CPI of ``n_pulses`` framed pulses (``n_range_bins`` beats each) into
    ``n_range_bins`` slow-time columns of ``n_pulses`` beats (the input of the Doppler
    processor).

    The block-transpose engine of the interleavers (``rows = n_pulses``, ``cols = n_range_bins``,
    ping-pong RAM of two CPIs) is fed in arrival order, so throughput is one sample per cycle
    once the first CPI has filled; the output is framed per column (``first`` on pulse 0,
    ``last`` on pulse ``n_pulses - 1``). Input framing is checked against the arrival position:
    a misplaced ``first`` or ``last`` sets the sticky ``frame_error`` (``clear`` resets it) — the
    transpose itself counts from reset. ``latency = None`` (a CPI is buffered).
    """
    def __init__(self, n_range_bins=64, n_pulses=16, data_width=16, with_csr=True):
        check(n_range_bins >= 2 and n_pulses >= 2, "expected n_range_bins >= 2 and n_pulses >= 2")
        self.n_range_bins = n_range_bins
        self.n_pulses     = n_pulses
        self.data_width   = data_width
        self.latency      = None
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.clear       = Signal()
        self.frame_error = Signal()
        self.permuter = perm = _LiteDSPBlockPermuter(rows=n_pulses, cols=n_range_bins,
            width=2*data_width, stride=n_range_bins)
        self.filled = perm.filled

        # # #

        # Arrival-order fill with input framing monitor.
        # ----------------------------------------------
        xfer_in = Signal()
        pos     = Signal(max=n_range_bins*n_pulses)
        col     = Signal(max=n_range_bins)
        self.comb += [
            perm.sink.valid.eq(self.sink.valid),
            perm.sink.data.eq(Cat(self.sink.i, self.sink.q)),
            self.sink.ready.eq(perm.sink.ready),
            xfer_in.eq(self.sink.valid & self.sink.ready),
        ]
        self.sync += [
            If(xfer_in,
                If(col == n_range_bins - 1, col.eq(0)).Else(col.eq(col + 1)),
                If(self.clear,
                    self.frame_error.eq(0),
                ).Elif((self.sink.first != (col == 0)) | (self.sink.last != (col == n_range_bins - 1)),
                    self.frame_error.eq(1),
                ),
            ).Elif(self.clear,
                self.frame_error.eq(0),
            ),
        ]

        # Column-framed transpose output.
        # -------------------------------
        xfer_out = Signal()
        row      = Signal(max=n_pulses)
        self.comb += [
            self.source.valid.eq(perm.source.valid),
            perm.source.ready.eq(self.source.ready),
            self.source.i.eq(perm.source.data[:data_width]),
            self.source.q.eq(perm.source.data[data_width:]),
            self.source.first.eq(row == 0),
            self.source.last.eq(row == n_pulses - 1),
            xfer_out.eq(self.source.valid & self.source.ready),
        ]
        self.sync += If(xfer_out,
            If(row == n_pulses - 1, row.eq(0)).Else(row.eq(row + 1)),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n_range_bins", size=16, offset=0,  description="Range bins per pulse."),
            CSRField("n_pulses",     size=16, offset=16, description="Pulses per CPI."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the frame error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("frame_error", size=1, offset=0, description="Sticky: input framing did not match the CPI geometry."),
            CSRField("filled",      size=2, offset=8, description="CPIs buffered (0..2)."),
        ])
        self.comb += [
            self._config.fields.n_range_bins.eq(self.n_range_bins),
            self._config.fields.n_pulses.eq(self.n_pulses),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.frame_error.eq(self.frame_error),
            self._status.fields.filled.eq(self.filled),
        ]
