#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Line buffer: K x K pixel neighbourhoods from a raster stream with border handling."""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import check, pixel_layout, window_layout, pixel_fields, bits_for
from litedsp.image.common import LiteDSPPixelCounter

BORDERS = ("replicate", "mirror", "zero")

# Line Buffer --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLineBuffer(LiteXModule):
    """Sliding ``kernel_size x kernel_size`` window over a raster pixel stream.

    ``kernel_size - 1`` line RAMs (``max_width`` deep) hold the previous lines; the incoming
    pixel and the RAM reads form a column that shifts into the window registers, so output beat
    k carries the neighbourhood of input pixel k (``w{row}{col}``, channels packed LSB-first,
    ``w{P}{P}`` = the pixel itself) with the same ``first`` / ``eol`` / ``last`` framing. Borders:
    ``replicate`` (edge pixel), ``mirror`` (``p[-1] = p[1]``, keeps a Bayer phase) or ``zero``;
    they are applied by muxes on the output side from the output coordinates, the learned line
    width and the frame height. ``P`` virtual beats after every line and ``P`` virtual lines
    after the frame (``sink.ready`` low, ``P = kernel_size // 2``) push the trailing outputs out,
    so the stream stays 1:1 with a throughput of ``width / (width + P)``. A line longer than
    ``max_width`` or a line length change inside a frame sets the sticky ``geometry_error``
    (framing re-synchronises on ``first``). ``latency = P * (width + P) + P + 3`` at the build
    width.
    """
    def __init__(self, data_width=8, n_channels=1, kernel_size=3, width=640, max_width=None, border="replicate",
        with_csr=True):
        check(kernel_size in (3, 5, 7), "expected kernel_size in (3, 5, 7)")
        check(border in BORDERS, f"expected border in {BORDERS}")
        if max_width is None:
            max_width = width
        check(2 <= width <= max_width, "expected 2 <= width <= max_width")
        check(width > kernel_size, "expected width > kernel_size")
        self.data_width  = data_width
        self.n_channels  = n_channels
        self.kernel_size = kernel_size
        self.width       = width
        self.max_width   = max_width
        self.border      = border
        K, P = kernel_size, kernel_size//2
        self.latency = P*(width + P) + P + 3
        self.sink   = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint(window_layout(data_width, n_channels, kernel_size))
        self.geometry_error = Signal()
        self.line_length    = Signal(bits_for(max_width))
        self.clear          = Signal()

        # # #

        CB = bits_for(max_width) + 1                                    # Coordinates (+ virtual).
        PW = n_channels*data_width
        fields = pixel_fields(n_channels)
        adv  = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)

        # Input side: real pixels, virtual columns after eol, virtual lines after last.
        # ------------------------------------------------------------------------------
        beat, real, xfer = Signal(), Signal(), Signal()
        c, y  = Signal(CB), Signal(CB)                                  # Input-side coordinates.
        W, H  = Signal(CB), Signal(CB)                                  # Learned width / height.
        vcol, vrow = Signal(max=P + 1), Signal(max=P + 1)
        self.fsm = fsm = FSM(reset_state="RUN")
        fsm.act("RUN",
            self.sink.ready.eq(adv),
            beat.eq(adv & self.sink.valid),
            real.eq(1),
            If(beat & self.sink.eol,
                NextValue(vcol, 0),
                NextState("VCOL"),
            ),
        )
        fsm.act("VCOL",                                                 # P virtual columns.
            beat.eq(adv),
            If(adv,
                If(vcol == P - 1,
                    If(vrow != 0,
                        If(vrow == P, NextValue(vrow, 0), NextState("RUN")).Else(NextValue(vrow, vrow + 1), NextValue(vcol, 0), NextState("VROW")),
                    ).Elif(y == H - 1,                                  # Just after the frame's last line.
                        NextValue(vrow, 1), NextValue(vcol, 0), NextState("VROW"),
                    ).Else(
                        NextState("RUN"),
                    ),
                ).Else(
                    NextValue(vcol, vcol + 1),
                ),
            ),
        )
        fsm.act("VROW",                                                 # A virtual line (W beats then P).
            beat.eq(adv),
            If(adv & (c == W - 1),
                NextValue(vcol, 0),
                NextState("VCOL"),
            ),
        )
        in_first = Signal()
        self.comb += [
            xfer.eq(beat & real),
            in_first.eq(real & self.sink.first),
        ]
        # Coordinates of the beat at S0: c counts real + virtual columns, y real + virtual lines.
        c0 = Signal(CB)
        self.comb += c0.eq(Mux(in_first, 0, c))
        frame_done = Signal()                                           # 'last' seen: H valid.
        self.sync += [
            If(beat,
                If(in_first,
                    c.eq(1), y.eq(0), frame_done.eq(0),
                    If(self.clear, self.geometry_error.eq(0)),
                ).Elif(real & self.sink.eol,
                    # Learn / check the line length; the virtual columns follow.
                    If(y == 0, W.eq(c0 + 1)).Elif(c0 + 1 != W, self.geometry_error.eq(1)),
                    If(c0 >= max_width - 1, self.geometry_error.eq(1)),
                    If(self.sink.last, H.eq(y + 1), frame_done.eq(1)),
                    c.eq(c0 + 1),
                ).Elif(fsm.ongoing("VCOL") & (vcol == P - 1),
                    c.eq(0), y.eq(y + 1),
                ).Else(
                    c.eq(c0 + 1),
                ),
            ),
            If(self.clear, self.geometry_error.eq(0)),
        ]
        self.comb += self.line_length.eq(W)
        # Line RAMs: RAM[k] holds line y - 1 - k at the column, read at S0, written at S1.
        rams, rps, wps = [], [], []
        for k in range(K - 1):
            m = Memory(PW, max_width)
            rp, wp = m.get_port(has_re=True), m.get_port(write_capable=True)
            self.specials += m, rp, wp
            rams.append(m); rps.append(rp); wps.append(wp)
        rd_addr = Signal(bits_for(max_width - 1))
        self.comb += rd_addr.eq(c0[:len(rd_addr)])
        for rp in rps:
            self.comb += [rp.adr.eq(rd_addr), rp.re.eq(adv)]

        # S1: the column vector (K rows) at column c1; RAM shift; window shift.
        # ---------------------------------------------------------------------
        v1, real1, first1, eol1, last1 = Signal(), Signal(), Signal(), Signal(), Signal()
        c1, y1 = Signal(CB), Signal(CB)
        x1 = Signal(PW)
        realcol1 = Signal()                                             # A real column (< W).
        self.sync += If(adv,
            v1.eq(beat), real1.eq(real & self.sink.valid), first1.eq(in_first & self.sink.valid),
            eol1.eq(real & self.sink.valid & self.sink.eol), last1.eq(real & self.sink.valid & self.sink.last),
            c1.eq(c0), y1.eq(Mux(in_first, 0, y)), x1.eq(Cat(*[getattr(self.sink, f) for f in fields])),
            # Real pixels and the virtual lines' columns (< W) shift through the RAMs so the row
            # alignment holds over the P virtual lines; the virtual columns after eol do not.
            realcol1.eq(real | fsm.ongoing("VROW")),
        )
        wr_addr = Signal(bits_for(max_width - 1))
        self.comb += wr_addr.eq(c1[:len(wr_addr)])
        col_vec = [Signal(PW, name=f"colvec{i}") for i in range(K)]     # Top (oldest) .. bottom (input).
        for i in range(K - 1):
            self.comb += col_vec[i].eq(rps[K - 2 - i].dat_r)
        self.comb += col_vec[K - 1].eq(x1)
        we = Signal()
        self.comb += we.eq(adv & v1 & realcol1)
        for k in range(K - 1):
            src = x1 if k == 0 else rps[k - 1].dat_r
            self.comb += [wps[k].adr.eq(wr_addr), wps[k].dat_w.eq(src), wps[k].we.eq(we)]
        win = [[Signal(PW, name=f"win{i}{j}") for j in range(K)] for i in range(K)]   # j = K-1 newest.
        self.sync += If(adv & v1,
            *[win[i][K - 1].eq(col_vec[i]) for i in range(K)],
            *[win[i][j].eq(win[i][j + 1]) for i in range(K) for j in range(K - 1)],
        )
        # Output coordinates of the window centre: (y1 - P, c1 - P) once the column is pushed.
        v2 = Signal()
        yo, xo = Signal((CB + 1, True)), Signal((CB + 1, True))
        yo_r, xo_r = Signal((CB + 1, True)), Signal((CB + 1, True))
        fd_r = Signal()                                                 # frame_done seen by this beat
        self.comb += [yo.eq(y1 - P), xo.eq(c1 - P)]                     # (the next frame's 'first'
        self.sync += If(adv, v2.eq(v1), yo_r.eq(yo), xo_r.eq(xo), fd_r.eq(frame_done))   # clears it early).

        # S2: border muxes and the output register.
        # -----------------------------------------
        def sel(coord, size, size_valid, i):                            # Window index for row/col i.
            target = Signal((CB + 2, True))
            zero   = Signal()
            pos    = Signal((CB + 2, True))
            beyond = Signal()
            sz     = Signal((CB + 2, True))
            self.comb += [pos.eq(coord + (i - P)), sz.eq(size), beyond.eq(size_valid & (pos > sz - 1))]
            if border == "replicate":
                self.comb += target.eq(Mux(pos < 0, 0, Mux(beyond, sz - 1, pos)))
            elif border == "mirror":
                self.comb += target.eq(Mux(pos < 0, -pos, Mux(beyond, 2*(sz - 1) - pos, pos)))
            else:
                self.comb += [target.eq(Mux(pos < 0, 0, Mux(beyond, sz - 1, pos))),
                              zero.eq((pos < 0) | beyond)]
            idx = Signal(max=K)
            d   = Signal((CB + 3, True))
            self.comb += [d.eq(target - coord + P), idx.eq(d[:len(idx)])]
            return idx, zero
        # The bottom border only applies once 'last' has fixed the height (the trailing outputs
        # come out during the virtual lines); the width is known before any output of a line.
        rowsel = [sel(yo_r, H, fd_r, i) for i in range(K)]
        colsel = [sel(xo_r, W, 1, j) for j in range(K)]
        out_ok = Signal()
        self.comb += out_ok.eq(v2 & (yo_r >= 0) & (xo_r >= 0))
        self.sync += If(adv,
            self.source.valid.eq(out_ok),
            self.source.first.eq((yo_r == 0) & (xo_r == 0)),
            self.source.eol.eq(xo_r == W - 1),
            self.source.last.eq((xo_r == W - 1) & (yo_r == H - 1)),
            *[getattr(self.source, f"w{i}{j}").eq(
                Mux(rowsel[i][1] | colsel[j][1], 0, Array([Array(win[r])[colsel[j][0]] for r in range(K)])[rowsel[i][0]]))
              for i in range(K) for j in range(K)],
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the geometry error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("geometry_error", size=1,  offset=0,  description="Sticky: line length changed or exceeded max_width."),
            CSRField("line_length",    size=16, offset=16, description="Learned line length."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("kernel_size", size=4,  offset=0, description="Window size."),
            CSRField("max_width",   size=16, offset=8, description="Line RAM depth."),
        ])
        self.comb += [
            self.clear.eq(self._control.fields.clear),
            self._status.fields.geometry_error.eq(self.geometry_error),
            self._status.fields.line_length.eq(self.line_length),
            self._config.fields.kernel_size.eq(self.kernel_size),
            self._config.fields.max_width.eq(self.max_width),
        ]
