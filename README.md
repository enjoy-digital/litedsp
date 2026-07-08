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

[> Blocks
---------

| Category        | Blocks                                                                      |
|-----------------|-----------------------------------------------------------------------------|
| `generation/`   | `NCO` (DDS), `CORDIC`, `Chirp` (linear FM), `NoiseSource` (AWGN), `Replay` (RAM AWG), `PatternSource` (const/counter/PRBS/impulse) |
| `mixing/`       | `Mixer` (complex, runtime up/down), `DDC`, `DUC`, `Channelizer`               |
| `filter/`       | `FIRFilter`/`FIRFilterComplex` (direct & symmetric), `FIRDecimator`/`FIRInterpolator` (polyphase), `CICDecimator`/`CICInterpolator` (+ runtime-rate), `HalfbandDecimator`/`HalfbandInterpolator`, `IIRBiquad`/`IIRBiquadCascade` (DF2T), `DCBlocker`, `MovingAverage`, `Hilbert`, `PulseShaper` (RRC), `FarrowInterpolator`, `RationalResampler`, `ArbResampler`, `Notch`, `CombFilter`, `Allpass`, `LMSEqualizer` (delayed LMS), `design.py` (coefficients) |
| `rate/`         | `Downsampler`, `Upsampler` (naive), `Decimator`, `Interpolator` (CIC/FIR), `Dropper` |
| `level/`        | `Gain`, `Power`, `Saturate`, `Clipper`, `EnvelopeDetector`, `Squelch`, `AGC`, `RMS`, `Log2`/`LogPower` (dB) |
| `correction/`   | `DCOffset`, `IQBalance`, `Derotator` (CFO)                                    |
| `comm/`         | `FMDemod`, `AMDemod`, `PhaseDetect`, `Slicer`, `SymbolMapper`, `DifferentialEncoder`/`Decoder`, `Scrambler`/`Descrambler`, `CRC`, `ConvEncoder`, `ViterbiDecoder` (hard-decision), `Correlator`, `PLL`/`Costas`, `TimingRecovery` (M&M or Gardner TED), `CPInsert`/`CPRemove` (OFDM cyclic prefix) |
| `analysis/`     | `Window`, `FFT` (radix-2 SDF, `inverse=`), `FFTIter`, `PSD`, `WelchPSD`, `Magnitude` (approx/CORDIC), `Goertzel`, `Stats`, `Histogram`, `PeakBin`, `EnergyDetector`, `FrequencyEstimator`, `ErrorCounter` (SER/BER) |
| `stream/`       | `Combine`, `Split`, `Delay`, `ChannelMux`/`ChannelDemux`, `Conjugate`/`SwapIQ`/`Negate`/`IQAdd`, offset-binary converters, `IQClockDomainCrossing`, `SkidBuffer`, `StreamFIFO`, `IQPack`/`IQUnpack`, `Capture` (scope, CSR or memory-mapped readout), `CSRSource`/`CSRSink`/`CSRReader`/`NullSink`, `StreamFramer`/`StreamDeframer` (`tlast`), `DMACapture`/`DMAReplay` (Wishbone or LiteDRAM DMA) |
| `frontend/`     | `ADCInterface`/`DACInterface` (raw converter words), `IQPacketizer`/`IQDepacketizer` (framed host-link words, LitePCIe-ready), `UDPIQStreamer`/`UDPIQReceiver` (I/Q packets over LiteEth UDP) |
| parallel (*)    | `ParallelNCO`, `ParallelMixer`, `ParallelFIRFilter`/`ParallelFIRFilterComplex`, `ParallelCICDecimator`, `ParallelDDC` composite + `IQSerialToParallel`/`IQParallelToSerial` adapters |
| misc            | `ISqrt` (`numeric.py`), `PILoop` (`control.py`)                               |

(*) Multi-sample-per-cycle datapaths (N samples/clk for rates above the fabric clock, e.g. a
gigasample RX front-end), bit-identical to their serial counterparts. The parallel variants
live next to their serial versions (`generation/nco_parallel.py`, ...).

Per-block FPGA resource/fmax numbers (ECP5 + Artix-7): see `doc/resources.md`.

[> Tooling
----------

| Tool               | What it does                                                       | Run |
|--------------------|--------------------------------------------------------------------|-----|
| Flow (`flow/`)     | JSON netlist → chain Verilog + CSR map + AXI-Stream/AXI-Lite IP core | `litedsp_flow flow.json` |
| GUI (`gui/`)       | DearPyGui node editor for flow netlists (GNU-Radio-Companion style), with **live mode**: connect to a running SoC and tune NCOs/gains/FIR taps, watch the PSD | `litedsp_gui` |
| Generator (`gen.py`) | Standalone core in the LiteX-ecosystem style: YAML → Verilog core + `csr.csv`/`csr.json`/`csr.h` | `litedsp_gen config.yml` |
| Software (`software/`) | Host-side drivers over `litex_server`: tune in Hz, reload taps, drain captures to NumPy, run DMA windows; register-map auto-discovery | `litedsp_cli info` |
| Examples (`examples/`) | Assembled chains: DDC/DUC, spectrum analyzer, FM receiver, QPSK RX, wideband RX, PRBS loopback BER, AXI IP preview | `python3 examples/fm_receiver.py` |
| Tests (`test/`)    | Golden-model harness: NumPy reference models, bit-exact/SNR checks under randomized backpressure | `python3 -m unittest discover -s test` |
| Sim (`sim/`)       | Verilator (real HDL) co-simulation vs the NumPy models + full-registry lint sweep | `python3 sim/run_blocks.py` |
| Impl (`impl/`)     | Yosys/nextpnr (ECP5) + Vivado (Artix-7) synth/P&R gated on resource + fmax budgets | `python3 impl/run.py --device ecp5` |
| Bench (`bench/`)   | Hardware proof points on litex-boards targets (Arty, Colorlight 5A-75B): CSR-controlled spectrum bench, Etherbone + UDP I/Q streaming bench | `python3 bench/spectrum.py --board=arty --build` |

[> Documentation
----------------

| Document                  | Content                                                    |
|---------------------------|------------------------------------------------------------|
| `doc/interfaces.md`       | The block contract: streaming, control, conventions checklist |
| `doc/fixed_point.md`      | Qm.n conventions, rounding/saturation rules                 |
| `doc/litex_integration.md`| Using blocks/chains in a LiteX SoC and in non-LiteX flows   |
| `doc/flow.md`             | Netlist format, flow/GUI usage, IP core generation          |
| `doc/resources.md`        | Per-block LUT/FF/BRAM/DSP + fmax table (generated)          |
| `doc/implementation.md`   | The impl/ flows and budget gating                           |
| `CONTRIBUTING.md`         | New-block checklist, tests, commit conventions              |

[> Tests
--------

```
python3 -m unittest discover -s test -v
```

[> License
----------

LiteDSP is released under the BSD-2-Clause license. See `LICENSE`.
