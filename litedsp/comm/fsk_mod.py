#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""FSK / GFSK / GMSK modulator: symbols to a complex baseband through symbol hold, an optional
Gaussian pulse filter and the FM engine."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common         import check, real_layout, iq_layout
from litedsp.filter.fir     import LiteDSPFIRFilter
from litedsp.filter.design  import gaussian_coefficients
from litedsp.comm.fm_mod    import _LiteDSPAngleModulator
from litedsp.comm.design    import fsk_deviation

# FSK Modulator ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPFSKModulator(LiteXModule):
    """M-ary FSK (2^bits_per_symbol levels) at ``sps`` samples per symbol, optionally Gaussian
    filtered (``bt``, ``span`` symbols: GFSK / GMSK), then frequency modulated.

    A symbol ``s`` becomes the level ``l = 2 s - (L - 1)`` scaled to ``l * 2**(dw-1-bps)``, held
    for ``sps`` samples (the symbol sink accepts one word per ``sps`` output samples), filtered by
    a symmetric ``LiteDSPFIRFilter`` from ``gaussian_coefficients`` when ``bt`` is set, and fed to
    the FM engine (``phase_inc`` centre, ``deviation`` from ``litedsp.comm.design.fsk_deviation``:
    the reset word is ``h = 1`` for FSK and ``h = 0.5`` for GMSK-style Gaussian filtering). Rate
    ``sps`` outputs per symbol; latency ``1 + fir + 2`` (``fir = 0`` without the filter).
    """
    def __init__(self, bits_per_symbol=1, sps=4, bt=None, span=4, data_width=16, phase_bits=32,
                 lut_depth=1024,
        fir_architecture="classic", n_macs=4, with_csr=True):
        check(1 <= bits_per_symbol <= 4, "expected 1 <= bits_per_symbol <= 4")
        check(2 <= sps <= 64, "expected 2 <= sps <= 64")
        check(bt is None or 0.0 < bt <= 1.0, "expected 0 < bt <= 1")
        check(span >= 1, "expected span >= 1")
        self.bits_per_symbol = bits_per_symbol
        self.sps        = sps
        self.bt         = bt
        self.data_width = data_width
        self.phase_bits = phase_bits
        self.sink   = stream.Endpoint([("data", bits_per_symbol)])
        self.source = stream.Endpoint(iq_layout(data_width))
        self.fm = _LiteDSPAngleModulator("fm", data_width, phase_bits, lut_depth, with_csr=False)
        self.phase_inc = self.fm.phase_inc
        self.deviation = self.fm.deviation
        h = 0.5 if bt is not None else 1.0
        self.deviation.reset = fsk_deviation(h, sps, bits_per_symbol, phase_bits)
        self.taps = None
        if bt is not None:
            self.taps = gaussian_coefficients(sps, span, bt, data_width)
            self.fir = LiteDSPFIRFilter(n_taps=len(self.taps), data_width=data_width,
                                        symmetric=True,
                architecture=fir_architecture, n_macs=n_macs)
            for t, c in enumerate(self.taps):
                self.fir.coeffs[t].reset = int(c)
            fir_latency = self.fir.latency
        else:
            fir_latency = 0
        self.latency = None if fir_latency is None else 1 + fir_latency + 2

        # # #

        DW, BPS, L = data_width, bits_per_symbol, 1 << bits_per_symbol
        # Symbol hold: one word per sps samples.
        hold = stream.Endpoint(real_layout(DW))
        adv  = Signal()
        k    = Signal(max=sps)
        level = Signal((BPS + 2, True))
        x_in  = Signal((DW, True))
        held  = Signal((DW, True))
        self.comb += [
            adv.eq(hold.ready | ~hold.valid),
            self.sink.ready.eq(adv & (k == 0)),
            level.eq((self.sink.data << 1) - (L - 1)),
            x_in.eq(level << (DW - 1 - BPS)),
        ]
        xfer = Signal()
        self.comb += xfer.eq(self.sink.valid & self.sink.ready)
        self.sync += If(adv,
            If(k == 0,
                hold.valid.eq(self.sink.valid), hold.data.eq(x_in), held.eq(x_in),
                hold.first.eq(self.sink.first), hold.last.eq(0),
                If(xfer, k.eq(1 % sps)),
            ).Else(
                hold.valid.eq(1), hold.data.eq(held), hold.first.eq(0), hold.last.eq(k == sps - 1),
                If(k == sps - 1, k.eq(0)).Else(k.eq(k + 1)),
            ),
        )
        if bt is not None:
            self.comb += [hold.connect(self.fir.sink), self.fir.source.connect(self.fm.sink)]
        else:
            self.comb += hold.connect(self.fm.sink)
        self.comb += self.fm.source.connect(self.source)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        PB = self.phase_bits
        self._phase_inc = CSRStorage(PB, name="phase_inc",
                                     description="Centre phase increment per sample.")
        self._deviation = CSRStorage(PB, reset=self.deviation.reset.value, name="deviation",
            description="Phase increment at full-scale level (see fsk_deviation).")
        self._config = CSRStatus(fields=[
            CSRField("bits_per_symbol", size=3, offset=0, description="Bits per symbol."),
            CSRField("sps",             size=7, offset=4, description="Samples per symbol."),
            CSRField("gaussian",        size=1, offset=12, description="Gaussian pulse filter present."),
        ])
        self.comb += [
            self.phase_inc.eq(self._phase_inc.storage), self.deviation.eq(self._deviation.storage),
            self._config.fields.bits_per_symbol.eq(self.bits_per_symbol),
            self._config.fields.sps.eq(self.sps),
            self._config.fields.gaussian.eq(int(self.bt is not None)),
        ]
