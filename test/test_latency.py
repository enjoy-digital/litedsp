#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Latency-contract verification: measured cycle latency == declared ``self.latency``.

The flow auto-delay-balancer (litedsp/flow/glue.py) equalizes reconvergent branches using
``self.latency``, so a wrong declaration silently misaligns joined streams. Under free flow
(no stalls), output sample ``k`` of a fixed-latency in-line block must emerge exactly
``latency`` cycles after input sample ``k`` was accepted; this test measures that delta for
every eligible palette block and pins it to the declaration.

Rate changers, transforms and adaptive blocks are excluded here (their latency/alignment is
pinned by their golden-model tests); the meta-test (test/test_registry_meta.py) guarantees
every block is classified.
"""

import random
import unittest

from migen import run_simulation, passive

from litedsp.flow import registry as flow_registry
from litedsp.flow.metadata import _accepts_with_csr

from test.registry import VSPEC

# Blocks excluded from the generic cycle-latency check (layout/rate/semantic reasons; each
# has its latency pinned by its own golden-model test instead).
EXCLUDED = {
    "pixel_from_video", "pixel_to_video", "line_buffer", "kernel_2d", "kernel_5x5", "gaussian_blur", "sharpen", "laplacian", "sobel", "rank_filter", "erode", "dilate", "debayer", "downscaler", "crop", "pixel_histogram", "fsk_modulator", "manchester_encoder", "manchester_decoder", "hamming_encoder", "hamming_decoder", "hdlc_framer", "hdlc_deframer", "bch_encoder", "bch_decoder",
    "cordic_rot", "cordic_vec", "hilbert", "fm_demod", "am_demod", "phase_detect", "slicer",
    "symbol_mapper", "correlator", "carrier_loop", "scrambler", "descrambler", "conv_encoder",
    "viterbi_decoder", "crc", "diff_encoder", "diff_decoder", "stats", "fft", "fft_iter",
    "parallel_fft",  # Transform (like fft); latency pinned cycle-exact in test_fft_parallel.
    "window", "magnitude", "magnitude_cordic", "log2", "log_power", "envelope", "channel_mux",
    "channel_demux", "tdm_mux", "tdm_demux", "combine", "split", "framer", "deframer", "mixer", "equalizer", "farrow",
    "derotator", "ddc", "duc", "channelizer", "pfb_channelizer", "decimator", "interpolator", "fir_decimator",
    "fir_interpolator", "cic_decimator", "cic_interpolator", "halfband_dec", "halfband_int",
    "pulse_shaper", "downsampler", "upsampler", "iq_pack", "iq_unpack", "energy_detector",
    "cp_remove",  # Rate changer (drops the cyclic prefix); alignment pinned in test_ofdm.
    "bitstream_decimator",  # Rate changer (runtime rate); pinned in test_bitstream.
    "stereo_matrix",        # Serial two-beat engine; cycles_per_frame pinned in test_audio_level.
    "exp2",                 # Unsigned in/out widths differ; latency pinned in test_logdb.
    "compressor", "limiter", "noise_gate",   # Serial engine; cycles_per_sample pinned in test_dynamics.
    "delay_line", "chorus", "lfo", "reverb", # Serial engines / source; pinned in test_effects.
    "sigma_delta_mod", "sigma_delta_dac", "pdm_rx",   # Rate changer / pin-level sink and source.
    "i2s_rx", "i2s_tx",                                # Pin-level serial audio.
    "range_gate",                                      # Rate changer (gated pulses).
}

def _build(spec):
    kwargs = dict(spec.kwargs)
    if _accepts_with_csr(spec.cls):
        kwargs["with_csr"] = False
    return spec.cls(**kwargs)

def payload_fields(endpoint):
    """``[(name, signed)]`` of an endpoint's payload (unsigned fields are stream tags)."""
    out = []
    for name, shape, *_ in endpoint.description.payload_layout:
        out.append((name, isinstance(shape, tuple) and shape[1]))
    return out

def measure_cycle_latency(dut, fields, n=48):
    """Cycle delta between acceptance of input k and emergence of output k (free flow).

    ``fields`` lists ``(name, signed)``: signed payload fields get random samples, unsigned
    tags (e.g. the TDM ``channel``) cycle 0, 1, 0, 1, ... so tagged engines see legal frames.
    """
    in_cycles, out_cycles = [], []
    prng = random.Random(3)

    def stimulus(k):
        return [getattr(dut.sink, f).eq(prng.randint(-1000, 1000) if signed else k % 2)
                for f, signed in fields]

    @passive
    def driver():
        cycle = 0
        fed   = 0
        yield dut.sink.valid.eq(1)
        for stmt in stimulus(0):
            yield stmt
        while True:
            yield
            if (yield dut.sink.ready) and fed < n:
                in_cycles.append(cycle)
                fed += 1
                for stmt in stimulus(fed):
                    yield stmt
            cycle += 1

    def capture():
        cycle = 0
        yield dut.source.ready.eq(1)
        while len(out_cycles) < n - 4:
            yield
            if (yield dut.source.valid):
                out_cycles.append(cycle)
            cycle += 1

    run_simulation(dut, [driver(), capture()])
    # Steady-state delta (skip warm-up), must be constant for a fixed-latency block.
    deltas = {out_cycles[k] - in_cycles[k] for k in range(8, len(out_cycles) - 1)}
    return deltas

class TestLatency(unittest.TestCase):
    def test_declared_latency_matches_measured(self):
        palette = flow_registry.registry()
        checked = 0
        for key, v in sorted(VSPEC.items()):
            if v["latency"] != "check" or key in EXCLUDED or key not in palette:
                continue
            spec = palette[key]
            if len(spec.sinks) != 1 or len(spec.sources) != 1:
                continue
            layouts = {spec.port("sink").layout, spec.port("source").layout}
            if len(layouts) != 1 or layouts.pop() not in ("iq", "real", "tdm"):
                continue
            with self.subTest(block=key):
                dut = _build(spec)
                if dut.latency == 0:
                    continue  # Combinational passthrough; nothing to measure.
                deltas = measure_cycle_latency(dut, payload_fields(dut.sink))
                self.assertEqual(len(deltas), 1,
                    f"{key}: latency not constant under free flow: {sorted(deltas)}")
                self.assertEqual(deltas.pop(), dut.latency,
                    f"{key}: measured cycle latency != declared self.latency ({dut.latency})")
                checked += 1
        self.assertGreaterEqual(checked, 10, f"latency check covered too few blocks ({checked})")

if __name__ == "__main__":
    unittest.main()
