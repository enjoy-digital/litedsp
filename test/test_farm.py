#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Multi-channel resampler-farm signoff (litedsp/rate/farm.py).

verify-tier: model

One time-shared serial-MAC polyphase decimating FIR serving n channels: every channel must
behave bit-exactly like its own FIRDecimator (farm_model = per-channel fir_decimator_model on
the demuxed streams) under randomized stalls/backpressure, channels must be fully isolated
(banked history), and the channel-tagged output must compose with LiteDSPChannelDemux as
documented.
"""

import random
import unittest

import numpy as np

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.rate.farm     import LiteDSPResamplerFarm
from litedsp.stream.route  import LiteDSPChannelDemux

from test.common import stream_driver, stream_capture, column, to_signed
from test.models import farm_model

def _run_farm(dut, chan_samples, n_out, sink_throttle=0.2, ready_rate=0.7):
    """Drive one sample list per channel, capture the channel-tagged output stream."""
    cap = []
    run_simulation(dut, [
        *[stream_driver(dut.sinks[k], chan_samples[k], ["i", "q"], seed=10 + k,
            throttle=sink_throttle) for k in range(len(chan_samples))],
        stream_capture(dut.source, cap, n_out, ["i", "q", "channel"], ready_rate=ready_rate),
    ])
    return cap

def _split(cap, n_channels):
    """Demux a captured channel-tagged stream into per-channel (i, q) signed arrays."""
    out = []
    for k in range(n_channels):
        i = to_signed(np.array([s["i"] for s in cap if s["channel"] == k], np.int64), 16)
        q = to_signed(np.array([s["q"] for s in cap if s["channel"] == k], np.int64), 16)
        out.append((i, q))
    return out

class TestResamplerFarm(unittest.TestCase):
    def test_bit_exact_per_channel(self):
        # verify-tier: model — every channel bit-exact vs its own fir_decimator_model
        # (farm_model) under randomized per-sink stalls and output backpressure.
        for architecture in ("classic", "pipelined"):
            for n_channels, n_taps, R in [(4, 16, 4), (2, 32, 8), (3, 8, 2)]:
                with self.subTest(architecture=architecture, n_channels=n_channels,
                    n_taps=n_taps, decimation=R):
                    prng   = random.Random(n_channels*100 + n_taps)
                    coeffs = [prng.randint(-(1 << 13), (1 << 13)) for _ in range(n_taps)]
                    n      = 32*R
                    xs     = [([prng.randint(-30000, 30000) for _ in range(n)],
                               [prng.randint(-30000, 30000) for _ in range(n)])
                              for _ in range(n_channels)]
                    dut = LiteDSPResamplerFarm(n_channels=n_channels, n_taps=n_taps, decimation=R,
                        data_width=16, coefficients=coeffs, with_csr=False,
                        architecture=architecture)
                    pipeline = 2*int(architecture == "pipelined")
                    self.assertEqual(dut.cycles_per_output, R + n_taps + 2 + pipeline)
                    self.assertEqual(dut.latency, n_taps + pipeline)
                    cap = _run_farm(dut,
                        [[{"i": i[j], "q": q[j]} for j in range(n)] for (i, q) in xs],
                        n_channels*(n//R))
                    ref = farm_model(xs, coeffs, R)
                    for k, (got_i, got_q) in enumerate(_split(cap, n_channels)):
                        self.assertEqual(len(got_i), n//R, f"ch{k}: wrong output count")
                        self.assertTrue(np.array_equal(got_i, ref[k][0]), f"ch{k}: I diverges")
                        self.assertTrue(np.array_equal(got_q, ref[k][1]), f"ch{k}: Q diverges")

    def test_channel_isolation(self):
        # verify-tier: model — an impulse on channel 0 must appear only in channel 0's output
        # (banked history: no leakage through the shared MAC/coefficient path).
        n_channels, n_taps, R = 4, 16, 4
        prng   = random.Random(5)
        coeffs = [prng.randint(-(1 << 13), (1 << 13)) for _ in range(n_taps)]
        n      = 24*R
        xs     = [([32767] + [0]*(n - 1) if k == 0 else [0]*n, [0]*n)
                  for k in range(n_channels)]
        dut = LiteDSPResamplerFarm(n_channels=n_channels, n_taps=n_taps, decimation=R,
            data_width=16, coefficients=coeffs, with_csr=False, architecture="pipelined")
        cap = _run_farm(dut, [[{"i": i[j], "q": q[j]} for j in range(n)] for (i, q) in xs],
            n_channels*(n//R))
        ref = farm_model(xs, coeffs, R)
        chans = _split(cap, n_channels)
        self.assertTrue(np.array_equal(chans[0][0], ref[0][0]))    # Impulse response on ch0.
        self.assertGreater(np.abs(chans[0][0]).max(), 0)
        for k in range(1, n_channels):                             # Silence everywhere else.
            self.assertTrue(np.all(chans[k][0] == 0), f"ch{k}: I leaked from ch0")
            self.assertTrue(np.all(chans[k][1] == 0), f"ch{k}: Q leaked from ch0")

    def test_channel_demux_composition(self):
        # verify-tier: model — the documented ChannelDemux composition: source -> demux.sink
        # with demux.sel driven by the channel tag fans back out to per-channel streams.
        n_channels, n_taps, R = 4, 8, 2
        prng   = random.Random(9)
        coeffs = [prng.randint(-(1 << 13), (1 << 13)) for _ in range(n_taps)]
        n      = 32*R

        class Dut(LiteXModule):
            def __init__(self):
                self.farm  = farm  = LiteDSPResamplerFarm(n_channels=n_channels, n_taps=n_taps,
                    decimation=R, data_width=16, coefficients=coeffs, with_csr=False,
                    architecture="pipelined")
                self.demux = demux = LiteDSPChannelDemux(n=n_channels, data_width=16,
                    with_csr=False)
                self.comb += [
                    farm.source.connect(demux.sink, omit={"channel"}),
                    demux.sel.eq(farm.source.channel),
                ]

        xs  = [([prng.randint(-30000, 30000) for _ in range(n)],
                [prng.randint(-30000, 30000) for _ in range(n)]) for _ in range(n_channels)]
        dut  = Dut()
        caps = [[] for _ in range(n_channels)]
        run_simulation(dut, [
            *[stream_driver(dut.farm.sinks[k], [{"i": xs[k][0][j], "q": xs[k][1][j]}
                for j in range(n)], ["i", "q"], seed=20 + k, throttle=0.1)
              for k in range(n_channels)],
            *[stream_capture(dut.demux.sources[k], caps[k], n//R, ["i", "q"], seed=30 + k,
                ready_rate=1.0) for k in range(n_channels)],
        ])
        ref = farm_model(xs, coeffs, R)
        for k in range(n_channels):
            self.assertTrue(np.array_equal(column(caps[k], "i", 16), ref[k][0]), f"ch{k}: I")
            self.assertTrue(np.array_equal(column(caps[k], "q", 16), ref[k][1]), f"ch{k}: Q")

    def test_registry_integration(self):
        # Palette/VSPEC/impl integration: reflected ports (n sinks + 1 channel-tagged source),
        # declared latency, verification row and implementation-flow factory all present.
        from litedsp.flow import registry as flow_registry
        from impl.modules import REGISTRY as IMPL_REGISTRY
        from test.registry import VSPEC
        spec = flow_registry.get("resampler_farm")
        self.assertEqual(len(spec.sinks), 4)
        self.assertEqual(len(spec.sources), 1)
        self.assertEqual(spec.port("source").layout, "iq")
        self.assertEqual(spec.latency, 32)                         # n_taps (default kwargs).
        architecture = next(p for p in spec.params if p.name == "architecture")
        self.assertEqual(architecture.choices, ["classic", "pipelined"])
        self.assertEqual(VSPEC["resampler_farm"]["model"], "farm_model")
        self.assertIn("resampler_farm", IMPL_REGISTRY)

if __name__ == "__main__":
    unittest.main()
