#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.comm.coding  import LiteDSPConvEncoder
from litedsp.comm.viterbi import LiteDSPViterbiDecoder

from test.common import stream_driver, stream_capture

# Python reference encoder (mirrors LiteDSPConvEncoder) ----------------------------------------------

def conv_encode(bits, constraint=7, polys=(0o171, 0o133)):
    reg, out = 0, []
    for b in bits:
        full = b | (reg << 1)
        sym  = 0
        for k, g in enumerate(polys):
            sym |= (bin(g & full).count("1") & 1) << k
        out.append(sym)
        reg = full & ((1 << (constraint - 1)) - 1)
    return out

# Viterbi --------------------------------------------------------------------------------------------

class TestViterbi(unittest.TestCase):
    def _decode(self, symbols, n_bits, **kwargs):
        dut = LiteDSPViterbiDecoder(with_csr=False, **kwargs)
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": s} for s in symbols], ("data",), throttle=0.2),
            stream_capture(dut.source, cap, n_bits, ("data",), ready_rate=0.7),
        ])
        return [c["data"] for c in cap]

    def test_encoder_chain_clean(self):
        # HW encoder -> HW decoder recovers the message exactly.
        prng = random.Random(1)
        bits = [prng.randint(0, 1) for _ in range(400)]

        class Chain(LiteXModule):
            def __init__(self):
                self.enc = LiteDSPConvEncoder(with_csr=False)
                self.dec = LiteDSPViterbiDecoder(with_csr=False)
                self.sink, self.source = self.enc.sink, self.dec.source
                self.comb += self.enc.source.connect(self.dec.sink)

        dut = Chain()
        n_out = len(bits) - dut.dec.traceback - 4
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for b in bits], ("data",), throttle=0.2),
            stream_capture(dut.source, cap, n_out, ("data",), ready_rate=0.7),
        ])
        self.assertEqual([c["data"] for c in cap], bits[:n_out])

    def test_corrects_sparse_errors(self):
        # Flip well-separated coded bits: the decoder must still recover the message.
        prng = random.Random(2)
        bits = [prng.randint(0, 1) for _ in range(400)]
        syms = conv_encode(bits)
        for pos in range(40, len(syms) - 60, 45):          # 1 flipped bit every 45 symbols.
            syms[pos] ^= 1 << prng.randint(0, 1)
        n_out = 400 - 56 - 4
        decoded = self._decode(syms, n_out)
        self.assertEqual(decoded, bits[:n_out])

    def test_uncoded_reference_model(self):
        # Sanity: the Python reference encoder matches the HW encoder.
        prng = random.Random(3)
        bits = [prng.randint(0, 1) for _ in range(64)]
        enc  = LiteDSPConvEncoder(with_csr=False)
        cap  = []
        run_simulation(enc, [
            stream_driver(enc.sink, [{"data": b} for b in bits], ("data",), throttle=0.1),
            stream_capture(enc.source, cap, len(bits), ("data",), ready_rate=0.9),
        ])
        self.assertEqual([c["data"] for c in cap], conv_encode(bits))

if __name__ == "__main__":
    unittest.main()
