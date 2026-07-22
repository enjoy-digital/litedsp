# AN008 — Chirp spread-spectrum receiver

Runnable example: [`examples/css_receiver.py`](../../examples/css_receiver.py).

## Objective and chain

Demonstrate the core CSS/LoRa-style symbol detector at spreading factor 7:

```
SF7 upchirp(symbol) + fractional-bin CFO + AWGN
       -> multiply by conjugate reference chirp (dechirp) -> LiteDSPFFT(N=128)
       -> natural-order peak bin = symbol
```

A cyclic shift of the chirp is a complex tone after dechirping. The 128-point coherent FFT
provides processing gain, so the peak remains detectable when individual time samples are below
the noise. The example uses the actual fixed-point radix-2 SDF RTL FFT and explicitly converts
its bit-reversed output to natural bin order.

## Golden checks

Four widely separated symbols are generated independently with deterministic AWGN and 0.12-bin
CFO. Every FFT peak must equal the transmitted symbol and exceed the second-largest bin by at
least 12 dB. Repeating the identical input frame only removes pipeline-fill ambiguity from this
standalone smoke; a packet receiver would use a preamble detector to establish frame boundaries.

```sh
python3 examples/css_receiver.py
python3 -m unittest test.test_examples.TestAppNoteExamples.test_css_receiver_smoke -v
```

For a fabric-only chain, use `LiteDSPChirp` as the conjugate reference, `LiteDSPMixer` for the
complex dechirp and `LiteDSPCFOEstimator` on repeated preamble chirps. Cross-links:
[`chirp`](../blocks/chirp.md), [`mixer`](../blocks/mixer.md), [`fft`](../blocks/fft.md), and
[`cfo_estimator`](../blocks/cfo_estimator.md).
