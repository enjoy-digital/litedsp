# Sources of the manual's facts

Every number and name in the manual is taken from the repository at the documented revision. This
file records where each chapter's facts come from, so that a reviewer can re-check them and a
maintainer knows what to update when the code changes.

| Chapter / section | Sources |
|---|---|
| Front matter, `VOCABULARY.md` | `doc/manual/metadata.yaml`, `litedsp/flow/registry.py`, `bench/spectrum.py` |
| 1 Introduction | `README.md`, `setup.py`, `LICENSE`, `CONTRIBUTORS`, `doc/blocks/index.md`, `litedsp/flow/registry.py`, `impl/budgets.json`, `sim/cosim_specs.py`, `test/`, `bench/spectrum.py`, `bench/stream.py` (commits `e1ca48c`, `2e20532`), `litedsp/software/{dpd,cli}.py` |
| 2 Sampled signals and fixed point | `doc/fixed_point.md`, `litedsp/common.py`, `test/common.py`, `char/metrics.py`, `litedsp/level/gain.py`, `litedsp/audio/eq.py`, `litedsp/*/*_parallel.py`, `litedsp/stream/adapt.py`, `README.md` |
| 3 Streams, latency and rates | `doc/interfaces.md`, `doc/wavedrom/*.json`, `litedsp/common.py`, `litedsp/stream/{split,delay}.py`, `litedsp/flow/{builder,glue}.py`, `litedsp/rate/*.py`, `litedsp/filter/{cic,fir_poly,halfband,resampler,arb_resampler}.py`, `test/common.py`, `test/test_metadata_policy.py`, `AGENTS.md` |
| 4 Digital filters | `litedsp/filter/*.py` (FIR, polyphase, half-band, CIC, bitstream, biquad, moving average, DC blocker, Hilbert, Farrow, `design.py`), `litedsp/audio/eq.py`, `char/specs.py`, `char/results.json` |
| 5 Oscillators, mixers and the FFT | `litedsp/generation/{nco,cordic,source}.py`, `litedsp/mixing/{mixer,ddc,duc,channelizer,pfb_channelizer}.py`, `litedsp/analysis/{fft,fft_iter,fft_parallel,reorder,window,psd,welch,goertzel}.py`, `char/specs.py`, `char/results.json`, `test/test_ddc_duc.py` |
| 6 Digital communications | `litedsp/comm/*.py`, `litedsp/comm/design.py`, `litedsp/filter/design.py` (RRC and Gaussian taps) |
| 7 Block contract | `doc/interfaces.md`, `CONTRIBUTING.md`, `AGENTS.md`, `litedsp/common.py`, `litedsp/control.py`, `litedsp/level/gain.py`, `litedsp/filter/fir.py`, `litedsp/mixing/ddc.py`, `litedsp/*/*_parallel.py`, `litedsp/stream/adapt.py`, `litedsp/flow/{registry,metadata,builder,glue}.py`, `test/test_metadata_policy.py`, `test/test_bypass.py`, `tools/check_style.py` |
| 8 Generation, mixing and correction | `litedsp/generation/*.py`, `litedsp/mixing/*.py`, `litedsp/correction/*.py`, `litedsp/software/drivers.py` (NCO, mixer drivers), `test/test_ddc_duc.py`, `test/test_parallel.py`, `char/specs.py`, `char/results.json`, `doc/timing_architecture.md` (PFB channel transform) |
| 9 Filters and rate change | `litedsp/filter/*.py`, `litedsp/rate/*.py`, `litedsp/software/drivers.py` (FIR driver), `char/results.json`, `impl/budgets.json`, `doc/timing_architecture.md` (CIC, FIR decimator, DUC, half-band, farm, LMS) |
| 10 Level control and analysis | `litedsp/level/*.py`, `litedsp/analysis/*.py`, `litedsp/software/dpd.py`, `litedsp/flow/registry.py`, `test/registry.py`, `doc/timing_architecture.md` (AGC, FFT), `impl/budgets.json`, `char/results.json`, `doc/blocks/index.md` |
| 11 Communications blocks | `litedsp/comm/*.py`, `litedsp/flow/registry.py`, `doc/timing_architecture.md` (Viterbi, frame sync, RS, QPSK carrier, LDPC), `impl/budgets.json`, `impl/modules.py`, `examples/qpsk_receiver_core.yml`, `doc/blocks/index.md` |
| 12 Stream utilities and host links | `doc/timestamps.md`, `litedsp/stream/*.py`, `litedsp/frontend/{converter,packet,udp}.py`, `litedsp/software/drivers.py`, `test/test_timestamp.py`, `bench/{spectrum,stream,test_stream}.py`, LiteX `litex/soc/cores/dma.py`, LiteDRAM `litedram/frontend/dma.py` |
| 13 Flow, generator, GUI and host software | `doc/flow.md`, `litedsp/flow/{metadata,registry,netlist,builder,glue,ipcore,vivado,generate,docgen}.py`, `litedsp/gen.py`, `litedsp/gui/{app,live}.py`, `litedsp/software/{drivers,cli}.py`, `test/test_flow.py`, `test/test_gui.py` |
| 14 Getting started | `setup.py`, `.github/workflows/ci.yml`, `examples/ddc_chain.py`, `examples/ddc_core.yml`, `test/test_nco.py`, `test/common.py`, `litedsp/gen.py` |
| 15 Integration | `doc/litex_integration.md`, `litedsp/mixing/ddc.py`, `litedsp/flow/builder.py`, `litedsp/frontend/{converter,packet,udp}.py`, `litedsp/stream/{dma,adapt,capture,csr_io}.py`, `litedsp/generation/nco.py`, `litedsp/software/drivers.py` |
| 16 Examples | `examples/README.md`, `examples/*.py`, `doc/app_notes/an001`, `an002`, `an003`, `an005` to `an008`, `an013` (`*.md`, `img/*.png`), `test/test_examples.py` |
| 17 Benches | `bench/{spectrum,stream,test_spectrum,test_stream}.py`, `.github/workflows/bench.yml`, commits `e1ca48c`, `2e20532` |
| 18 Verification | `test/common.py`, `test/registry.py`, `test/test_{registry_meta,metadata_policy,latency,bypass,width_sweep,hypothesis,agc}.py`, `sim/{run_blocks,run_lint,run_coverage,verilator,cosim_specs}.py`, `sim/coverage_waivers.json`, `formal/`, `doc/formal.md`, `char/{specs,budgets,run_char}.py`, `impl/{run,modules}.py`, `doc/implementation.md`, `doc/characterization.md`, `.github/workflows/{ci,impl,impl-xilinx,nightly,bench}.yml`, `CONTRIBUTING.md` |
| 19 Debugging | `AGENTS.md`, `litedsp/stream/capture.py`, `litedsp/analysis/measure.py`, `test/common.py`, `sim/{run_lint,run_blocks}.py`, `test/test_metadata_policy.py` |
| 20 Application families | `litedsp/flow/registry.py`, `litedsp/common.py`, `litedsp/{motor,audio,radar,image}/` |
| 21 Motor control primer | `litedsp/motor/*.py` (docstrings, per-unit scaling in `__init__.py`), `doc/motor_control.md` |
| 22 Audio primer | `litedsp/audio/*.py`, `litedsp/audio/design.py`, `litedsp/software/drivers.py` (loudness driver), `doc/audio.md` |
| 23 Radar and sonar primer | `litedsp/radar/{design,waveform,compress,mti,cfar,track}.py` |
| 24 Image primer | `litedsp/common.py` (pixel, window, video layouts), `litedsp/image/{design,linebuffer,debayer}.py` |
| 25 Motor control blocks | `doc/motor_control.md`, `litedsp/motor/*.py`, `litedsp/software/drivers.py`, `doc/app_notes/an009_foc_pmsm.md`, `examples/foc_pmsm.py` |
| 26 Audio blocks | `doc/audio.md`, `litedsp/audio/*.py`, `litedsp/software/drivers.py`, `doc/app_notes/an010_audio_processor.md`, `examples/audio_processor.py`, `test/test_{dither,audio_eq,dynamics,pdm,meter}.py` |
| 27 Radar and sonar blocks | `doc/radar.md`, `litedsp/radar/*.py`, `litedsp/common.py` (cell, target, track layouts), `litedsp/flow/registry.py`, `litedsp/software/drivers.py` (radar drivers), `doc/app_notes/an004_chirp_radar.md`, `doc/app_notes/an011_pulse_doppler_radar.md`, `examples/{chirp_radar,pulse_doppler_radar}.py`, `test/test_{pulse_compressor,doppler}.py`, `impl/budgets.json` |
| 28 Image and video blocks | `doc/image.md`, `litedsp/image/*.py`, `litedsp/common.py` (pixel layouts), `litedsp/flow/{registry,glue}.py`, `litedsp/software/drivers.py` (image drivers), `doc/app_notes/an012_image_pipeline.md`, `examples/image_pipeline.py`, `examples/image_core.yml`, `sim/coverage_waivers.json` |
| 29 Using the application families | `examples/{foc,audio,image}_core.yml`, `litedsp/gen.py`, `litedsp/software/drivers.py` (`Driver`, `discover`), `test/test_examples.py`, `examples/*.py` |
| A Registers | generated by `doc/manual/registers.py` (`--check` in CI, job `docs`) from `litedsp/flow/{registry,metadata}.py` |
| B Build options | `litedsp/gen.py`, `litedsp/flow/{netlist,generate,docgen}.py`, `litedsp/software/cli.py`, `bench/*.py`; block parameter tables generated by `doc/manual/build_options.py` (`--check` in CI) from `litedsp/flow/{registry,metadata}.py` |
| C Glossary | the sources of the chapters each entry links |
| D Performance | `impl/budgets.json`, `impl/modules.py`, `char/results.json`, `char/budgets.json`, `char/specs.py`, `doc/timing_architecture.md` (summary table, classic values), `impl/budgets.py` (85 % floor, 15 % resource tolerance), `.github/workflows/{impl,nightly}.yml` (gates), `doc/implementation.md`, `doc/characterization.md`; tables generated by `doc/manual/performance.py` (`--check` in CI) |

The three appendix generators (`registers.py`, `build_options.py`, `performance.py`, all in
`doc/manual/`) are pure Python: they read the block registry and the recorded JSON results and
need no FPGA toolchain. Regenerate them after a change of the registry, of `impl/budgets.json` or of
`char/results.json`, and commit the appendices; the `docs` job of `.github/workflows/ci.yml` fails
when one is stale. The kit's `tools/csr_doc.py` is not used: LiteDSP blocks have no fixed SoC to
elaborate, so the register appendix comes from the registry reflection instead.
