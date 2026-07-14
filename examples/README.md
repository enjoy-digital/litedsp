# LiteDSP Examples

Each script assembles real LiteDSP blocks into a chain and runs it (NumPy stimulus + the
`test/common.py` stream simulator), printing a result and asserting a golden property. Run any
with `python3 examples/<name>.py`.

| Example | Chain | Demonstrates |
|---|---|---|
| `ddc_chain.py` | NCO → Mixer(down) → FIR → Downsampler | Digital down-conversion, tone rejection |
| `duc_chain.py` | Interpolator → NCO → Mixer(up) | Digital up-conversion |
| `fm_receiver.py` | FMDemod → FIR decimator | FM discriminator + audio decimation |
| `qpsk_rx.py` | RRC matched filter → TimingRecovery → Slicer | Symbol timing recovery, QPSK demod (SER 0) |
| `spectrum_analyzer.py` | Window → FFT → PSD | Averaged power spectrum |
| `wideband_rx.py` | DDC → StreamFIFO → StreamFramer → IQPack | Capture front-end: elastic buffering, framing (→ AXI-Stream `tlast`), packing narrow I/Q into wide bus words |
| `loopback_ber.py` | PatternSource(PRBS) → Split → {Delay \| StreamFIFO} → ErrorCounter | Self-checking BER/integrity harness from the bring-up blocks |
| `integrated_ip.py` | DCBlocker → Gain → Framer, AXI-Stream ports | Preview of the integratable IP target: AXI-Stream data ports + aggregated CSR register map (`get_csrs()`) + generated Verilog |

`wideband_rx`, `loopback_ber`, and `integrated_ip` exercise the chain-glue / bus-I/O / measurement
blocks (FIFO, pack, pattern source, error counter, framer) and preview the flow-graph → AXI IP-core
direction (see `litedsp/flow/` and `doc/flow.md`).

## Standalone core configs

YAML configurations for the standalone core generator (`litedsp_gen`), producing a Verilog core
with AXI-Stream data ports + AXI-Lite control port and the `csr.csv`/`csr.json`/`csr.h` register
map artifacts:

| Config | Chain | Generate |
|---|---|---|
| `ddc_core.yml` | NCO → Mixer(down) → FIR → Downsampler | `litedsp_gen examples/ddc_core.yml` |
| `spectrum_core.yml` | Window(hann) → FFT → PSD | `litedsp_gen examples/spectrum_core.yml` |
