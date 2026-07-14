#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, real_layout

# PSD ----------------------------------------------------------------------------------------------

class LiteDSPPSD(LiteXModule):
    """Power-spectral-density accumulator for a streaming FFT.

    Consumes the (bit-reversed, framed) output of :class:`litedsp.analysis.fft.FFT`, accumulates
    ``|X[k]|**2 = I**2 + Q**2`` per bin over ``2**avg_log2`` frames, then emits the averaged
    spectrum (``N`` values, **natural** bin order, framed with first/last). While emitting, it
    backpressures the FFT, so no samples are lost.

    ``latency`` is the FFT pipeline latency (``N-1``); the first ``latency`` samples (pipeline
    fill) are skipped so frames align.
    """
    def __init__(self, N, latency, data_width=16, avg_log2=4, with_csr=True):
        assert (N & (N - 1)) == 0
        self.N           = N
        self.bits        = N.bit_length() - 1
        self.avg_log2    = avg_log2
        self.power_width = 2*data_width + avg_log2
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(real_layout(self.power_width))

        # # #

        bits = self.bits

        # Accumulator RAM (one bin per FFT output), async read + sync write.
        # -----------------------------------------------------------------
        acc_mem = Memory(self.power_width, N)
        acc_wp  = acc_mem.get_port(write_capable=True)
        acc_rp  = acc_mem.get_port(async_read=True)
        self.specials += acc_mem, acc_wp, acc_rp

        # Instantaneous power of the current input sample.
        inst = Signal(2*data_width + 1)
        self.comb += inst.eq(self.sink.i*self.sink.i + self.sink.q*self.sink.q)

        skip_cnt  = Signal(max=max(2, latency + 1))
        sample    = Signal(bits)          # Position within the current frame.
        frame_cnt = Signal(avg_log2 + 1)  # Frames accumulated.
        read_cnt  = Signal(bits)

        # Store in natural bin order: address = bit-reversed frame position.
        bin_addr = Signal(bits)
        self.comb += bin_addr.eq(Cat(*[sample[b] for b in reversed(range(bits))]))

        accept = Signal()  # Input accepted this cycle (accumulate phase).
        self.comb += [
            acc_wp.adr.eq(bin_addr),
            # On the first frame, overwrite (clear); afterwards accumulate.
            acc_wp.dat_w.eq(Mux(frame_cnt == 0, inst, acc_rp.dat_r + inst)),
            acc_wp.we.eq(accept),
        ]

        self.fsm = fsm = FSM(reset_state="SKIP")
        fsm.act("SKIP",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                # Skip exactly `latency` fill samples (0..latency-1); the next sample is bin 0.
                If(skip_cnt == (latency - 1),
                    NextValue(skip_cnt, 0),
                    NextState("ACC"),
                ).Else(
                    NextValue(skip_cnt, skip_cnt + 1),
                )
            )
        )
        fsm.act("ACC",
            self.sink.ready.eq(1),
            accept.eq(self.sink.valid),
            If(self.sink.valid,
                If(sample == (N - 1),
                    NextValue(sample, 0),
                    If(frame_cnt == ((1 << avg_log2) - 1),
                        NextValue(frame_cnt, 0),
                        NextState("READ"),
                    ).Else(
                        NextValue(frame_cnt, frame_cnt + 1),
                    )
                ).Else(
                    NextValue(sample, sample + 1),
                )
            )
        )
        # Readout: emit the averaged spectrum in natural order (backpressures the FFT).
        self.comb += acc_rp.adr.eq(Mux(fsm.ongoing("READ"), read_cnt, bin_addr))
        fsm.act("READ",
            self.source.valid.eq(1),
            self.source.data.eq(acc_rp.dat_r >> avg_log2),
            self.source.first.eq(read_cnt == 0),
            self.source.last.eq(read_cnt == (N - 1)),
            If(self.source.ready,
                If(read_cnt == (N - 1),
                    NextValue(read_cnt, 0),
                    NextState("ACC"),
                ).Else(
                    NextValue(read_cnt, read_cnt + 1),
                )
            )
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStatus(fields=[
            CSRField("avg_log2", size=8, description="Averaging exponent (frames = 2**avg_log2)."),
        ])
        self.comb += self._control.fields.avg_log2.eq(self.avg_log2)
