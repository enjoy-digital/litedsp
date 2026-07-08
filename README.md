                          __   _ __      ___  _______
                         / /  (_) /____ / _ \/ __/ _ \
                        / /__/ / __/ -_) // /\ \/ ___/
                       /____/_/\__/\__/____/___/_/
                       Portable RF DSP blocks for LiteX

[> Intro
--------

LiteDSP is a toolbox of portable, well-tested RF/DSP building blocks for FPGA, written in
Migen/LiteX and following the LiteX coding style. Every block is pure HDL (no vendor IP), so
it simulates end-to-end and runs on any FPGA, and every block shares one standardized
streaming + control interface so blocks compose by `connect()`.

It is meant both as a ready-to-use library for RF processing on FPGA (mixers, NCO, filters,
rate conversion, gain/AGC, power, corrections, analysis) and as a clean base to customize
from for client-specific requirements.

[> Design principles
--------------------

- **Portable-only**: pure Migen/LiteX, fully simulatable, FPGA-vendor agnostic.
- **Standardized interfaces**: LiteX `stream.Endpoint` streaming with full valid/ready
  backpressure; the `with_csr=True` / `add_csr()` control pattern everywhere; uniform
  `bypass`; each block exposes its `latency`. See `doc/interfaces.md`.
- **Fixed-point rigor**: parameterized Qm.n format (default Q1.15 / 16-bit), shared
  `Round` / `Saturate` / `Scale` helpers used at every downsizing point. See
  `doc/fixed_point.md`.
- **Tested**: each block has a NumPy golden reference model; simulation output is compared
  bit-exact or against an SNR threshold, run under `unittest` and CI.

[> Layout
---------

- `litedsp/`           : the toolbox (generation, mixing, filter, rate, level, correction,
                         analysis, stream) + `flow/` (block-graph → Verilog/CSR/AXI IP generator)
                         + `gui/` (DearPyGui flow-graph editor, GNU-Radio-Companion style)
                         + `gen.py` (standalone core generator, YAML → Verilog + CSR map).
- `test/`              : golden-model harness, NumPy reference models, per-block tests.
- `examples/`          : assembled chains (DDC, DUC, repeater).
- `doc/`               : architecture, interface contract, fixed-point conventions, flow tooling.

[> Modules
----------

- **generation/** : `NCO` (DDS), `CORDIC`, `Chirp` (linear FM), `NoiseSource` (AWGN), `Replay`,
                     `PatternSource` (const/counter/PRBS/impulse test patterns).
- **mixing/**     : `Mixer` (complex, runtime up/down), `DDC`, `DUC`.
- **filter/**     : `FIRFilter`/`FIRFilterComplex` (direct & symmetric), `FIRDecimator`/
                     `FIRInterpolator` (polyphase, single-MAC), `CICDecimator`/`CICInterpolator`,
                     `HalfbandDecimator`/`HalfbandInterpolator`, `IIRBiquad`/`IIRBiquadCascade`
                     (DF2T), `DCBlocker`, `MovingAverage`, `Hilbert`, `PulseShaper` (RRC),
                     `FarrowInterpolator`, `RationalResampler`, `ArbResampler`, `Notch`,
                     `CombFilter`, `Allpass`, `design.py` (coefficients).
- **rate/**       : `Downsampler`, `Upsampler` (naive), `Decimator`, `Interpolator` (CIC/FIR).
- **level/**      : `Gain`, `Power`, `Saturate`, `Clipper`, `EnvelopeDetector`, `Squelch`,
                     `AGC`, `RMS`, `Log2`/`LogPower` (dB).
- **correction/** : `DCOffset`, `IQBalance`, `Derotator` (CFO).
- **comm/**       : `FMDemod`, `AMDemod`, `PhaseDetect`, `Slicer`, `SymbolMapper`,
                     `DifferentialEncoder`/`Decoder`, `Scrambler`/`Descrambler`, `CRC`,
                     `ConvEncoder`, `Correlator`, `PLL`/`Costas`, `TimingRecovery` (M&M).
- **stream/**     : `Combine`, `Split`, `Delay`, `ChannelMux`/`ChannelDemux`,
                     `Conjugate`/`SwapIQ`/`Negate`, offset-binary converters,
                     `IQClockDomainCrossing`, `SkidBuffer`, `Capture` (scope), `StreamFIFO`
                     (elastic buffer), `IQPack`/`IQUnpack` (wide-bus packing),
                     `CSRSource`/`CSRSink`/`NullSink` (bus-driven I/O),
                     `StreamFramer`/`StreamDeframer` (first/last ↔ AXI-Stream `tlast`).
- **analysis/**   : `Window`, `FFT` (radix-2 SDF, `inverse=`), `FFTIter`, `PSD`, `WelchPSD`,
                     `Magnitude` (approx/CORDIC), `Goertzel`, `Stats`, `Histogram`, `PeakBin`,
                     `EnergyDetector`, `FrequencyEstimator`, `ErrorCounter` (SER/BER loopback).
- **numeric/control** : `ISqrt`, `PILoop`.
- **examples/**   : `ddc_chain.py`, `duc_chain.py`, `spectrum_analyzer.py`, `fm_receiver.py`
                     (FM demod + audio decimation), `qpsk_rx.py` (matched filter -> timing
                     recovery -> slicer, recovers QPSK at SER 0), `wideband_rx.py` (DDC -> FIFO ->
                     framer -> wide-word pack), `loopback_ber.py` (PRBS self-check), `integrated_ip.py`
                     (AXI-Stream + aggregated CSR map preview). See `examples/README.md`.
- **sim/**        : Verilator (real HDL) co-simulation of blocks vs the NumPy models
                     (`python3 sim/run_nco.py`, `sim/run_fir.py`).
- **impl/**       : FPGA implementation tests — Yosys/nextpnr (ECP5) + Vivado (xc7a200t)
                     synth/P&R with resource + fmax budgets (`python3 impl/run.py`). See
                     `doc/implementation.md`.
- **flow/**       : assemble blocks into a chain from a JSON netlist and generate the chain
                     Verilog + CSR register map + an AXI-Stream/AXI-Lite IP core (`litedsp_flow
                     flow.json`). A DearPyGui editor (`litedsp/gui/`, `litedsp_gui`) produces/
                     consumes the netlist. See `doc/flow.md`.
- **gen.py**      : standalone core generator in the LiteX-ecosystem style: `litedsp_gen
                     config.yml` turns a YAML flow description into a Verilog core (AXI-Stream
                     data + AXI-Lite control) + `csr.csv`/`csr.json`/`csr.h` register map.

[> Tests
--------

```
python3 -m unittest discover -s test -v
```

[> License
----------

LiteDSP is released under the BSD-2-Clause license. See `LICENSE`.
