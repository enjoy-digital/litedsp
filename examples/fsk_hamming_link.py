#!/usr/bin/env python3
#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""AN013 - FSK + Hamming + HDLC link: text over a noisy GFSK channel.

  text -> bits -> HDLCFramer -> HammingEncoder(7,4) -> FSKModulator(GFSK, 8 sps) -> AWGN (NumPy)
       -> FMDemod -> integrate-and-dump + slicer (NumPy) -> HammingDecoder -> HDLCDeframer -> text

Gates: the transmitted waveform equals the composed models; at a clean operating point the FCS
checks and the text round-trips; one flipped bit per codeword is corrected everywhere; two flips
in one codeword are flagged uncorrectable and fail the FCS; the model BER curve (Eb/N0 6..11 dB,
raw vs coded) plus one RTL point within 3x of the model.

Run: ``python3 examples/fsk_hamming_link.py [--plot-dir DIR]``; prints PASS.
"""

import os
import sys
import math
import argparse

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from migen import *

from litex.gen import *

from litedsp.comm.hdlc     import LiteDSPHDLCFramer, LiteDSPHDLCDeframer
from litedsp.comm.hamming  import LiteDSPHammingEncoder, LiteDSPHammingDecoder
from litedsp.comm.fsk_mod  import LiteDSPFSKModulator
from litedsp.comm.fm_demod import LiteDSPFMDemod
from litedsp.comm.design   import fsk_deviation
from litedsp.filter.design import gaussian_coefficients

from test.models import (hdlc_frame_model, hamming_encode_model, fsk_modulator_model,
                         hamming_decode_model, hdlc_deframe_model)

SPS, BT = 8, 0.5
MESSAGE = b"LiteDSP AN013: GFSK link with Hamming(7,4) FEC and HDLC framing, 64 bytes of text!!"[
    :64]

def text_bits(msg):
    return [(b >> i) & 1 for b in msg for i in range(8)]

def bits_text(bits):
    out = bytearray()
    for k in range(0, len(bits) - 7, 8):
        out.append(sum(int(bits[k + i]) << i for i in range(8)))
    return bytes(out)

# Simulation helpers -------------------------------------------------------------------------------

def run_chain(top, beats, in_fields, out_fields, n_out, done=None, max_cycles=60000):
    out = []
    @passive
    def capture():
        yield top.source.ready.eq(1)
        while True:
            if (yield top.source.valid):
                beat = {}
                for f in out_fields:
                    beat[f] = (yield getattr(top.source, f))
                out.append(beat)
            yield
    def driver():
        for b in beats:
            for f in in_fields:
                yield getattr(top.sink, f).eq(int(b.get(f, 0)))
            yield top.sink.valid.eq(1)
            yield
            while not (yield top.sink.ready):
                yield
            yield top.sink.valid.eq(0)
        for _ in range(max_cycles):
            if (done(out) if done else len(out) >= n_out):
                return
            yield
        raise RuntimeError("simulation did not complete")
    run_simulation(top, [driver(), capture()])
    return out

class TX(LiteXModule):
    def __init__(self):
        self.framer = LiteDSPHDLCFramer(preamble=2, with_csr=False)
        self.fec    = LiteDSPHammingEncoder(m=3, with_csr=False)
        self.mod    = LiteDSPFSKModulator(sps=SPS, bt=BT, with_csr=False)
        self.mod.deviation.reset = fsk_deviation(1.0, SPS)
        self.sink, self.source = self.framer.sink, self.mod.source
        self.comb += [self.framer.source.connect(self.fec.sink),
                      self.fec.source.connect(self.mod.sink)]

class RX(LiteXModule):
    def __init__(self):
        self.fec = LiteDSPHammingDecoder(m=3, with_csr=False)
        self.deframer = LiteDSPHDLCDeframer(with_csr=False)
        self.sink, self.source = self.fec.sink, self.deframer.source
        self.comb += self.fec.source.connect(self.deframer.sink)

def tx_model(payload_bits):
    frame, _, _ = hdlc_frame_model([payload_bits], 2)
    frame = frame.tolist()
    frame += [0]*((-len(frame)) % 4)                                    # Pad to whole codewords.
    coded, _, _ = hamming_encode_model(frame, 3)
    coded = coded.tolist()
    i, q = fsk_modulator_model(coded, 1, SPS, gaussian_coefficients(SPS, 4, BT, 16),
                               fsk_deviation(1.0, SPS), 0)
    return frame, coded, i, q

def demod_slice(y, n_bits, ref_bits=None):
    """Integrate-and-dump on the demodulated frequency: symbol timing is acquired on the first
    64 bits (the HDLC flags act as a preamble) by picking the offset whose decisions match them
    best, then one decision per SPS samples (the middle 3/4 of the symbol)."""
    y = np.asarray(y, float)
    best, best_score = 0, -1
    for off in range(0, 3*SPS):
        seg = y[off:off + n_bits*SPS]
        if len(seg) < n_bits*SPS:
            break
        sums = seg.reshape(n_bits, SPS)[:, SPS//8:SPS - SPS//8].sum(axis=1)
        bits = [int(v > 0) for v in sums]
        score = sum(int(a == b) for a, b in zip(bits[:64], (ref_bits or bits)[:64]))
        if score > best_score:
            best, best_score = off, score
            best_bits = bits
    return best_bits

def channel(i, q, ebn0_db, rng):
    """AWGN for a given Eb/N0 (Eb = SPS samples of energy) then a pre-detection boxcar of SPS
    samples (a matched-bandwidth filter that keeps the discriminator above threshold), scaled to
    the 16-bit range."""
    z = np.asarray(i, float) + 1j*np.asarray(q, float)
    es = np.mean(np.abs(z)**2)
    eb = es*SPS
    n0 = eb/10**(ebn0_db/10)
    sigma = math.sqrt(n0/2)
    z = z + rng.normal(0, sigma, len(z)) + 1j*rng.normal(0, sigma, len(z))
    z = np.convolve(z, np.ones(SPS)/SPS)[:len(z)]
    return np.clip(np.round(z.real), -32768, 32767), np.clip(np.round(z.imag), -32768, 32767)

def model_link(coded, i, q, ebn0_db, rng):
    """Model receiver: FM discriminator (angle difference) + slicer, then the Hamming decode."""
    ci, cq = channel(i, q, ebn0_db, rng)
    z = ci + 1j*cq
    disc = np.angle(z[1:]*np.conj(z[:-1]))
    disc = np.concatenate([[0.0], disc])
    rx = demod_slice(disc, len(coded), coded)
    raw_errors = sum(int(a != b) for a, b in zip(rx, coded))
    dec, _ = hamming_decode_model(rx, 3)
    return rx, raw_errors, dec.tolist()

# Passes -------------------------------------------------------------------------------------------

def pass_tx(payload_bits):
    frame, coded, ri, rq = tx_model(payload_bits)
    top = TX()
    beats = [{"data": b, "first": int(k == 0), "last": int(k == len(payload_bits) - 1)} for k,
             b in enumerate(payload_bits)]
    n = len(coded)*SPS
    out = run_chain(top, beats, ["data", "first", "last"], ["i", "q"], n,
                    done=lambda o: len(o) >= n)
    def signed(v): return v - 65536 if v >= 32768 else v
    gi = [signed(o["i"]) for o in out[:n]]; gq = [signed(o["q"]) for o in out[:n]]
    ok = gi == ri.tolist() and gq == rq.tolist()
    print(f"[tx] {len(payload_bits)} payload bits -> {len(frame)} framed -> {len(coded)} coded "
          f"bits -> {n} I/Q samples; bit-exact vs the models: {ok}")
    return ok, dict(frame=frame, coded=coded, i=ri, q=rq)

def pass_rx(coded, rx_bits, label, expect_text, expect_unc, expect_fcs_ok):
    top = RX()
    beats = [{"data": b} for b in rx_bits]
    def done(o):
        return any(x["last"] for x in o) or len(o) >= 4000
    out = run_chain(top, beats + [{"data": (0x7E >> i) & 1} for i in range(8)]*3, ["data"],
                    ["data", "first", "last", "fcs_ok"], 0, done=done)
    payload = [o["data"] for o in out]
    fcs_ok  = int(out[-1]["fcs_ok"]) if out and out[-1]["last"] else 0
    text = bits_text(payload)
    ok = (text == expect_text) == expect_fcs_ok and fcs_ok == expect_fcs_ok
    print(f"[rx {label}] fcs_ok {fcs_ok}, text {'matches' if text == expect_text else 'differs'}")
    return ok, dict(text=text, fcs_ok=fcs_ok)

def main():
    parser = argparse.ArgumentParser(description="AN013 FSK + Hamming + HDLC link.")
    parser.add_argument("--plot-dir", default=None, help="Save the BER figure here (matplotlib optional).")
    args = parser.parse_args()
    rng = np.random.default_rng(13)
    payload = text_bits(MESSAGE)
    ok, tx = pass_tx(payload)
    coded = tx["coded"]
    # Clean point.
    good, r = pass_rx(coded, list(coded), "clean", MESSAGE, 0, 1)
    ok &= good
    # One flipped bit per codeword: all corrected.
    one = list(coded)
    for b in range(len(one)//7):
        one[b*7 + (b % 7)] ^= 1
    good, r = pass_rx(coded, one, "1 error / codeword", MESSAGE, 0, 1)
    ok &= good
    # Two flips in one codeword: uncorrectable, FCS fails.
    two = list(coded)
    two[3*7 + 1] ^= 1; two[3*7 + 4] ^= 1
    good, r = pass_rx(coded, two, "2 errors in a codeword", MESSAGE, 1, 0)
    ok &= good
    # Model BER curve and one RTL point.
    ebn0 = [6, 7, 8, 9, 10, 11]
    raw_ber, coded_ber = [], []
    for e in ebn0:
        raw_e, cod_e, n_bits = 0, 0, 0
        for _ in range(6):
            rx, raw_err, dec = model_link(coded, np.concatenate([tx["i"], np.zeros(4*SPS)]),
                                          np.concatenate([tx["q"], np.zeros(4*SPS)]), e, rng)
            raw_e += raw_err; n_bits += len(coded)
            cod_e += sum(int(a != b) for a, b in zip(dec, tx["frame"]))
        raw_ber.append(raw_e/n_bits); coded_ber.append(cod_e/(n_bits*4/7))
    print("[ber] Eb/N0 dB " + " ".join(f"{e:>5}" for e in ebn0))
    print("[ber] raw      " + " ".join(f"{b:5.3f}" for b in raw_ber))
    print("[ber] coded    " + " ".join(f"{b:5.3f}" for b in coded_ber))
    # RTL point at 8 dB: demodulate through LiteDSPFMDemod, decode through the RTL FEC.
    ci, cq = channel(np.concatenate([tx["i"], np.zeros(4*SPS)]),
                     np.concatenate([tx["q"], np.zeros(4*SPS)]), 8, np.random.default_rng(21))
    demod = LiteDSPFMDemod(with_csr=False)
    beats = [{"i": int(a), "q": int(b)} for a, b in zip(ci, cq)]
    class D(LiteXModule):
        def __init__(self):
            self.d = demod
            self.sink, self.source = demod.sink, demod.source
    out = run_chain(D(), beats, ["i", "q"], ["data"], len(beats))
    y = [o["data"] - 65536 if o["data"] >= 32768 else o["data"] for o in out]
    rx_rtl = demod_slice(y, len(coded), coded)
    raw_rtl = sum(int(a != b) for a, b in zip(rx_rtl, coded))/len(coded)
    model_raw = raw_ber[ebn0.index(8)]
    ratio = raw_rtl/max(model_raw, 1e-6)
    ok &= (raw_rtl == 0 and model_raw < 0.01) or (1/3 <= ratio <= 3)
    print(f"[rtl] raw BER at 8 dB {raw_rtl:.4f} (model {model_raw:.4f})")
    if args.plot_dir:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            os.makedirs(args.plot_dir, exist_ok=True)
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.semilogy(ebn0, np.maximum(raw_ber, 1e-5), "o-", label="raw (model)")
            ax.semilogy(ebn0, np.maximum(coded_ber, 1e-5), "s-", label="Hamming(7,4) (model)")
            ax.semilogy([8], [max(raw_rtl, 1e-5)], "r*", ms=12, label="raw (RTL demod)")
            ax.set(xlabel="Eb/N0 (dB)", ylabel="BER",
                   title="GFSK (BT 0.5, h = 1) link"); ax.grid(True, which="both"); ax.legend()
            fig.tight_layout(); path = os.path.join(
                args.plot_dir, "an013_fsk_hamming_link.png"); fig.savefig(path, dpi=110)
            print(f"  plot -> {path}")
        except ImportError:
            print("[plot] matplotlib not installed, skipping the figure")
    print("  PASS: waveform bit-exact, FEC and framing gates met" if ok else "  FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
