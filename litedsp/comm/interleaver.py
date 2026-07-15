#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Block (matrix) interleaver / deinterleaver: rows x cols symbol transpose with ping-pong RAM.

The classic burst-spreading interleaver of concatenated FEC chains (CCSDS 131.0-B telemetry,
DVB-T outer interleaving is the convolutional variant): symbols are written into a rows x cols
matrix row-wise and read out column-wise (the deinterleaver applies the inverse permutation).
Adjacent channel symbols then come from different rows, so a channel error burst of B symbols
is spread across the rows with at most ``ceil(B/rows)`` errors each.

CCSDS convention (interleaving depth I = ``rows``): the interleaver operates on *bytes*,
BETWEEN the two code layers — TX: RS(255, 223) encoder -> interleaver -> convolutional K=7
encoder; RX: Viterbi decoder -> deinterleaver -> RS decoder. Each row is one RS codeword
(``cols`` = 255, the codeword length), written row-wise in the order a single time-shared RS
encoder emits the I codewords; the column-wise read is the channel order. Viterbi decoder
errors are bursty (a wrong path survives ~ a traceback of symbols), so without interleaving
one burst lands in a single codeword and quickly exceeds t = 16 correctable bytes; spread
across I codewords, bursts of up to ~I*t bytes are corrected (I = 5 -> 80 bytes). CCSDS
allows I in {1, 2, 3, 4, 5, 8} (I = 1 = no interleaving).

Both blocks buffer whole blocks in a ping-pong RAM (2 x rows*cols symbols): the writer fills
one bank while the reader drains the other, so back-to-back blocks stream without gaps
(1 symbol/cycle steady-state, 1:1 rate). Block boundaries are counted from reset (sink
``first``/``last`` ignored, like the RS codec); each output block is framed with
``first``/``last``. Latency is variable (``latency = None``): a block must be fully written
before its first symbol is read.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check

# Helpers --------------------------------------------------------------------------------------------

def _check_geometry(rows, cols, width):
    check(rows >= 1, "expected rows >= 1 (CCSDS interleaving depth I)")
    check(cols >= 1, "expected cols >= 1")
    check(rows <= 255 and cols <= 65535, "expected rows <= 255 and cols <= 65535 (CSR field widths)")
    check(rows*cols >= 2, "expected a block of at least 2 symbols")
    check(width >= 1, "expected width >= 1")

class _LiteDSPBlockPermuter(LiteXModule):
    """Shared rows x cols block-transpose engine (see module docstring).

    Sequential (arrival-order) write into the active ping-pong bank; transpose read from the
    other bank as an incremental stride walk — element k+1 of the output sits ``stride``
    addresses after element k, wrapping to the next transpose row (``a - rows*cols + 1``) —
    with ``stride = cols`` (interleave: column-wise read of a row-wise write) or
    ``stride = rows`` (deinterleave: the inverse permutation).
    """
    def __init__(self, rows, cols, width, stride):
        _check_geometry(rows, cols, width)
        n = rows*cols
        self.rows    = rows
        self.cols    = cols
        self.width   = width
        self.latency = None  # Variable/framed: an n-symbol block fills before it drains.
        self.sink   = stream.Endpoint([("data", width)])
        self.source = stream.Endpoint([("data", width)])

        # # #

        # Ping-pong block RAM: bank b at addresses [b*n, (b+1)*n). The writer fills one bank
        # while the reader drains the other, so streaming continues across back-to-back blocks.
        # ---------------------------------------------------------------------------------------
        mem = Memory(width, 2*n)
        wp  = mem.get_port(write_capable=True)
        rp  = mem.get_port(has_re=True)  # re gates dat_r so a held output survives stalls.
        self.specials += mem, wp, rp

        self.filled = filled = Signal(max=3)  # Fully written, not yet fully read banks (0..2).
        w_inc = Signal()                      # Write side completes its bank this cycle.
        r_dec = Signal()                      # Read side completes its bank this cycle.
        self.sync += filled.eq(filled + w_inc - r_dec)

        # Write side: arrival-order fill of the active bank (stalls only when both banks hold
        # undrained blocks).
        # ---------------------------------------------------------------------------------------
        w_bank = Signal()
        w_cnt  = Signal(max=n)
        self.comb += [
            self.sink.ready.eq(filled != 2),
            wp.adr.eq(w_cnt + Mux(w_bank, n, 0)),
            wp.dat_w.eq(self.sink.data),
            wp.we.eq(self.sink.valid & self.sink.ready),
            w_inc.eq(wp.we & (w_cnt == n - 1)),
        ]
        self.sync += If(wp.we,
            If(w_cnt == n - 1,
                w_cnt.eq(0),
                w_bank.eq(~w_bank),
            ).Else(w_cnt.eq(w_cnt + 1)),
        )

        # Read side: transpose stride walk + 2-stage output pipeline (RAM address -> registered
        # dat_r -> output register), advanced only when the output register is free/consumed.
        # ---------------------------------------------------------------------------------------
        r_bank = Signal()
        r_cnt  = Signal(max=n)               # Beat within the block (first/last framing).
        r_addr = Signal(max=n)               # Permuted address of the current beat.
        r_nxt  = Signal(max=n + stride + 1)  # r_addr + stride, before the transpose-row wrap.
        ce     = Signal()                    # Output register free or being consumed.
        issue  = Signal()                    # A read is issued this cycle (bank available).
        s1_valid = Signal()                  # Stage 1: dat_r holds a valid symbol.
        s1_first = Signal()
        s1_last  = Signal()
        self.comb += [
            ce.eq(self.source.ready | ~self.source.valid),
            issue.eq(filled != 0),
            rp.adr.eq(r_addr + Mux(r_bank, n, 0)),
            rp.re.eq(ce),
            r_nxt.eq(r_addr + stride),
            r_dec.eq(ce & issue & (r_cnt == n - 1)),
        ]
        self.sync += If(ce,
            # Stage 2: output register (data aligned with the valid/first/last captured at issue).
            self.source.valid.eq(s1_valid),
            self.source.first.eq(s1_first),
            self.source.last.eq(s1_last),
            self.source.data.eq(rp.dat_r),
            # Stage 1: issue the next address (or a bubble while waiting for a full bank).
            s1_valid.eq(issue),
            s1_first.eq(r_cnt == 0),
            s1_last.eq(r_cnt == n - 1),
            If(issue,
                If(r_cnt == n - 1,
                    r_cnt.eq(0),
                    r_addr.eq(0),
                    r_bank.eq(~r_bank),
                ).Else(
                    r_cnt.eq(r_cnt + 1),
                    # Stride walk: wrap to the next transpose row past the block end.
                    If(r_nxt >= n, r_addr.eq(r_nxt - n + 1)).Else(r_addr.eq(r_nxt)),
                ),
            ),
        )

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("rows",  size=8,  description="Matrix rows (CCSDS interleaving depth I)."),
            CSRField("cols",  size=16, description="Matrix columns (RS codeword length for CCSDS)."),
            CSRField("width", size=8,  description="Symbol width in bits."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("filled", size=2, description="Ping-pong banks holding a complete undrained block (0-2)."),
        ])
        self.comb += [
            self._config.fields.rows.eq(self.rows),
            self._config.fields.cols.eq(self.cols),
            self._config.fields.width.eq(self.width),
            self._status.fields.filled.eq(self.filled),
        ]

# Block Interleaver ----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPBlockInterleaver(_LiteDSPBlockPermuter):
    """TX block interleaver: rows x cols symbols in row-wise, out column-wise.

    One rows*cols-symbol block is written in arrival order (row-wise: for CCSDS, ``rows`` = I
    consecutive RS codewords of ``cols`` = 255 bytes each) and read out column-wise (byte 0 of
    every codeword, then byte 1, ...), so adjacent channel symbols come from different
    codewords and a downstream error burst is spread across all of them (see the module
    docstring for the CCSDS RS -> interleaver -> convolutional-encoder placement). Ping-pong
    buffered: back-to-back blocks stream at 1 symbol/cycle. Block boundaries are counted from
    reset (sink ``first``/``last`` ignored); output blocks are framed with ``first``/``last``.

    Parameters
    ----------
    rows : int
        Matrix rows = interleaving depth I (CCSDS: I in {1, 2, 3, 4, 5, 8}; default 5, one
        row per RS codeword).
    cols : int
        Matrix columns = symbols per row (default 255, the RS(255, k) codeword length).
    width : int
        Symbol width in bits (default 8: byte interleaving over RS symbols).
    """
    def __init__(self, rows=5, cols=255, width=8, with_csr=True):
        _LiteDSPBlockPermuter.__init__(self, rows, cols, width, stride=cols)
        if with_csr:
            self.add_csr()

# Block Deinterleaver --------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPBlockDeinterleaver(_LiteDSPBlockPermuter):
    """RX block deinterleaver: the exact inverse of :class:`LiteDSPBlockInterleaver`.

    One rows*cols-symbol block is written in arrival (channel) order — column-wise in matrix
    terms — and read out row-wise, restoring the original order (for CCSDS: ``rows`` = I
    consecutive RS codewords, ready for a time-shared RS decoder; see the module docstring for
    the Viterbi -> deinterleaver -> RS-decoder placement). Ping-pong buffered: back-to-back
    blocks stream at 1 symbol/cycle. Block boundaries are counted from reset (sink
    ``first``/``last`` ignored); output blocks are framed with ``first``/``last``.

    Parameters
    ----------
    rows : int
        Matrix rows = interleaving depth I, matching the transmitter's (default 5).
    cols : int
        Matrix columns = symbols per row (default 255, the RS(255, k) codeword length).
    width : int
        Symbol width in bits (default 8: byte interleaving over RS symbols).
    """
    def __init__(self, rows=5, cols=255, width=8, with_csr=True):
        _LiteDSPBlockPermuter.__init__(self, rows, cols, width, stride=rows)
        if with_csr:
            self.add_csr()
