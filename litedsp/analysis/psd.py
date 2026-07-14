#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, real_layout

PSD_MODE_LINEAR = 0  # Sum 2**avg_log2 frames, emit sum >> avg_log2 (restarts every spectrum).
PSD_MODE_EXP    = 1  # Leaky integrator: acc += (inst - acc) >> avg_log2 (persists).
PSD_MODE_MAX    = 2  # Max-hold: acc = max(acc, inst) per bin (persists).
PSD_MODE_MIN    = 3  # Min-hold: acc = min(acc, inst) per bin (persists).

# PSD ----------------------------------------------------------------------------------------------

class LiteDSPPSD(LiteXModule):
    """Power-spectral-density accumulator for a streaming FFT.

    Consumes the (bit-reversed, framed) output of :class:`litedsp.analysis.fft.FFT`, combines
    ``|X[k]|**2 = I**2 + Q**2`` per bin over ``2**avg_log2`` frames, then emits the resulting
    spectrum (``N`` values, **natural** bin order, framed with first/last). While emitting, it
    backpressures the FFT, so no samples are lost.

    The per-bin combining is runtime-selectable (``mode`` Signal / CSR field):

    - ``PSD_MODE_LINEAR`` (0, default): sum ``2**avg_log2`` frames, emit ``sum >> avg_log2``;
      the accumulator restarts on each spectrum (today's averaged PSD).
    - ``PSD_MODE_EXP`` (1): exponential/leaky average ``acc += (inst - acc) >> avg_log2``;
      the accumulator persists across spectra (continuously tracking display trace).
    - ``PSD_MODE_MAX`` (2): per-bin max-hold (captures transients; persists until cleared).
    - ``PSD_MODE_MIN`` (3): per-bin min-hold (noise-floor trace; persists until cleared).

    A ``clear`` pulse (Signal / CSR field) restarts the combining: the next frame boundary
    re-initializes the accumulator (overwrite instead of combine), so max/min/exponential
    traces can be reset at runtime. Spectra are emitted every ``2**avg_log2`` frames in all
    modes; the emission cadence is not affected by ``clear``.

    ``fft_latency`` is the upstream FFT pipeline latency (default ``N-1``, matching
    :class:`litedsp.analysis.fft.LiteDSPFFT`); the first ``fft_latency`` samples (pipeline
    fill) are skipped so frames align.

    Parameters
    ----------
    fft_latency : int
        Upstream FFT pipeline latency in cycles; that many initial fill samples are discarded
        so bin 0 aligns with frame start. Defaults to N-1 (LiteDSPFFT).
    avg_log2 : int
        Frames per emitted spectrum, as a power of two (``2**avg_log2``); in linear mode each
        step adds one bit to the accumulator RAM and output width (power_width), in
        exponential mode it sets the leak time-constant.
    """
    def __init__(self, N=64, fft_latency=None, data_width=16, avg_log2=4, with_csr=True):
        check(N >= 2 and (N & (N - 1)) == 0, "N must be a power of two >= 2.")
        latency = (N - 1) if fft_latency is None else fft_latency  # Upstream FFT fill to skip.
        self.N           = N
        self.bits        = N.bit_length() - 1
        self.avg_log2    = avg_log2
        self.power_width = 2*data_width + avg_log2
        self.latency     = None  # Variable (frame-accumulating: emits after 2**avg_log2 frames).
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(real_layout(self.power_width))
        self.mode   = Signal(2)  # Combining mode (PSD_MODE_*).
        self.clear  = Signal()   # Pulse: restart combining at the next frame boundary.

        # # #

        bits = self.bits

        # Accumulator RAM (one bin per FFT output), async read + sync write.
        # ------------------------------------------------------------------
        acc_mem = Memory(self.power_width, N)
        acc_wp  = acc_mem.get_port(write_capable=True)
        acc_rp  = acc_mem.get_port(async_read=True)
        self.specials += acc_mem, acc_wp, acc_rp

        # Instantaneous power of the current input sample.
        inst = Signal(2*data_width + 1)
        self.comb += inst.eq(self.sink.i*self.sink.i + self.sink.q*self.sink.q)

        skip_cnt  = Signal(max=max(2, latency + 1))  # FFT pipeline-fill samples discarded.
        sample    = Signal(bits)                     # Position within the current frame.
        frame_cnt = Signal(avg_log2 + 1)             # Frames accumulated.
        read_cnt  = Signal(bits)                     # Readout bin index.

        # Store in natural bin order: address = bit-reversed frame position.
        bin_addr = Signal(bits)
        self.comb += bin_addr.eq(Cat(*[sample[b] for b in reversed(range(bits))]))

        # Per-bin combining (mode-selected), sign-extended for the leaky difference.
        # --------------------------------------------------------------------------
        inst_s = Signal((self.power_width + 1, True))
        acc_s  = Signal((self.power_width + 1, True))
        leak   = Signal((self.power_width + 2, True))
        self.comb += [
            inst_s.eq(inst),
            acc_s.eq(acc_rp.dat_r),
            leak.eq(acc_s + ((inst_s - acc_s) >> avg_log2)),
        ]
        acc_next = Signal(self.power_width)
        self.comb += Case(self.mode, {
            PSD_MODE_LINEAR: acc_next.eq(acc_rp.dat_r + inst),
            PSD_MODE_EXP:    acc_next.eq(leak),
            PSD_MODE_MAX:    acc_next.eq(Mux(inst > acc_rp.dat_r, inst, acc_rp.dat_r)),
            PSD_MODE_MIN:    acc_next.eq(Mux(inst < acc_rp.dat_r, inst, acc_rp.dat_r)),
        })

        # Clear/initialization: the first frame after reset or a clear pulse overwrites the
        # accumulator; linear mode additionally restarts on each spectrum (frame_cnt == 0).
        # A clear is latched and applied at the next frame boundary so every bin of a frame
        # sees a consistent state.
        # -----------------------------------------------------------------------------------
        accept        = Signal()          # Input accepted this cycle (accumulate phase).
        frame_done    = Signal()          # Last sample of a frame accepted this cycle.
        first_frame   = Signal(reset=1)   # Current frame re-initializes the accumulator.
        clear_pending = Signal()
        init          = Signal()          # Overwrite (initialize) instead of combine.
        self.comb += [
            frame_done.eq(accept & (sample == (N - 1))),
            init.eq(first_frame | ((self.mode == PSD_MODE_LINEAR) & (frame_cnt == 0))),
            acc_wp.adr.eq(bin_addr),
            acc_wp.dat_w.eq(Mux(init, inst, acc_next)),
            acc_wp.we.eq(accept),
        ]
        self.sync += [
            If(frame_done,
                first_frame.eq(clear_pending),
                clear_pending.eq(0),
            ),
            If(self.clear,
                clear_pending.eq(1),
            ),
        ]

        self.fsm = fsm = FSM(reset_state="SKIP" if latency else "ACC")
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
        # Readout: emit the spectrum in natural order (backpressures the FFT). Linear mode
        # rescales the frame sum to an average; the other modes emit the accumulator as-is.
        self.comb += acc_rp.adr.eq(Mux(fsm.ongoing("READ"), read_cnt, bin_addr))
        fsm.act("READ",
            self.source.valid.eq(1),
            self.source.data.eq(Mux(self.mode == PSD_MODE_LINEAR,
                acc_rp.dat_r >> avg_log2,
                acc_rp.dat_r)),
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
        self._control = CSRStorage(fields=[
            CSRField("mode",  size=2, offset=0, values=[
                ("``0b00``", "Linear average (sum 2**avg_log2 frames, emit sum >> avg_log2)."),
                ("``0b01``", "Exponential average (acc += (inst - acc) >> avg_log2, persists)."),
                ("``0b10``", "Max-hold (per-bin peak, persists until cleared)."),
                ("``0b11``", "Min-hold (per-bin floor, persists until cleared)."),
            ], description="Per-bin combining mode."),
            CSRField("clear", size=1, offset=8, pulse=True,
                description="Restart combining: re-initialize the accumulator at the next frame boundary."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("avg_log2", size=8, description="Averaging exponent (frames = 2**avg_log2)."),
        ])
        self.comb += [
            self.mode.eq( self._control.fields.mode),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.avg_log2.eq(self.avg_log2),
        ]
