# AN008 — Chirp spread-spectrum receiver

Runnable example: [`examples/css_receiver.py`](../../examples/css_receiver.py).

## Objective and chain

Demonstrate packet acquisition and CSS/LoRa-style symbol detection at spreading factor 7:

```
noise prefix -> six repeated SF7 upchirps + payload + 1.35-bin CFO + AWGN
       -> blockwise dechirp/FFT consistency -> preamble start + coarse CFO bin
       -> LiteDSPCFOEstimator(delay=128) -> fractional CFO -> derotate
       -> dechirp -> LiteDSPFFT(N=128) -> natural-order peak bin = payload symbol
```

A cyclic shift of the chirp is a complex tone after dechirping. The receiver scans symbol-aligned
blocks for six consecutive dechirped spectra with the same peak, establishing the packet start
and integer CFO bin. The raw repeated preamble then passes through the actual
`LiteDSPCFOEstimator`: its delay-128 autocorrelation and CORDIC angle recover CFO modulo one bin.
Combining both gives the full 1.35-bin offset. After correction, the 128-point fixed-point SDF
RTL FFT supplies the processing gain and its bit-reversed output is restored to natural order.

## Golden checks

The deterministic packet contains two noise-only blocks, six preamble upchirps, and four widely
separated symbols. The script requires the exact preamble block, CFO accuracy within 0.05 bin,
exact recovery of all payload symbols, and at least 12 dB peak margin. Repeating each corrected
payload block at the RTL FFT input only removes standalone SDF pipeline-fill ambiguity; packet
acquisition and CFO estimation operate on the single received preamble.

```sh
python3 examples/css_receiver.py
python3 -m unittest test.test_examples.TestAppNoteExamples.test_css_receiver_smoke -v
```

For a fabric-only chain, use `LiteDSPChirp` as the conjugate reference and `LiteDSPMixer` for the
complex dechirp; this example already uses `LiteDSPCFOEstimator` on the repeated preamble.
Cross-links:
[`chirp`](../blocks/chirp.md), [`mixer`](../blocks/mixer.md), [`fft`](../blocks/fft.md), and
[`cfo_estimator`](../blocks/cfo_estimator.md).
