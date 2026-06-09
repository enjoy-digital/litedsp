# LiteDSP Implementation Tests (ECP5 + Xilinx)

Beyond functional simulation, every block is run through real FPGA toolchains to verify it
**synthesizes & places-and-routes**, that the **portable-only** claim holds across vendors, that
it **compiles clean**, and that **resource usage matches expectations** (budget-gated).

## Toolchains & targets

| Vendor | Flow | Target |
|---|---|---|
| Lattice **ECP5** | Yosys `synth_ecp5` (OOC) + nextpnr-ecp5 + Trellis | `LFE5UM5G-85F` / CABGA381 |
| **Xilinx** 7-series | Vivado out-of-context synth + implementation | `xc7a200tsbg484-3` (the M2SDR part) |

## Running

```
python3 impl/run.py --device ecp5   --flow synth                 # all blocks, Yosys (fast)
python3 impl/run.py --device xilinx --flow synth --subset        # Vivado OOC synth (subset)
python3 impl/run.py --device ecp5   --flow pnr  --subset         # + nextpnr P&R -> fmax
python3 impl/run.py --device xilinx --flow pnr  --subset         # + Vivado impl -> fmax
python3 impl/run.py --device ecp5   --flow synth --update-budgets # refresh the baseline
```
`impl/run.py` builds each block (`impl/modules.py` registry → Verilog via `sim/verilog.py`),
parses LUT/FF/BRAM/DSP (+ fmax for P&R), and **fails** on any synth/P&R error or budget
violation (baseline in `impl/budgets.json`, ±15% tolerance). The Implementation CI workflow runs
the ECP5 Yosys synth across all blocks on every push (portability/compile-clean).

## Findings (what implementation testing caught)

- **`fft_iter` (iterative FFT) was FPGA-hostile — now fixed.** The first version used *async-read*
  RAM with 2 read + 2 write ports per butterfly; async read blocks BRAM inference and 4 ports
  exceed a BRAM's 2, so Yosys spilled the whole thing to distributed LUT-RAM: **36k LUTs, 0 BRAM**.
  Reworked to *synchronous-read* memory with a **2-phase butterfly** (one read cycle, then one
  compute+write cycle) so each I/Q sample RAM is a single true-dual-port BRAM: now **1039 LUT /
  2 BRAM / 4 DSP** on ECP5 (**236 LUT / 1 BRAM / 5 DSP** on Xilinx) — a 35× LUT reduction, and the
  "compact FFT" is finally compact. Trade-off: 2 cycles/butterfly (latency `N + N·log2(N) + N`).
  Lesson: *async-read memories never map to BRAM; large RAMs must be synchronous-read and ≤2 ports.*
- **`nco_qw` (quarter-wave NCO) trades BRAM for logic at small depths.** At `lut_depth=1024` the
  N/4+1 table (257×16) maps to ~674 LUTs instead of BRAM; the 4× ROM saving only pays off at
  larger depths / wider data. The full-LUT `NCO` (2 BRAM) is preferable for `lut_depth≤1024`.
- **fmax is dominated, as expected, by the long-combinational blocks** — IIR biquad (recursive
  feedback) and the FFT (per-stage scaled add + twiddle multiply) are the slowest; pipelined
  variants are the lever if higher fmax is needed.

## ECP5 resources (Yosys `synth_ecp5`, all blocks)

LUT = LUT4 + 2·CCU2C (carry); FF = TRELLIS_FF; BRAM = DP16KD; DSP = MULT18X18D.

| module | LUT | FF | BRAM | DSP |
|---|---|---|---|---|
| nco | 43 | 43 | 2 | 0 |
| nco_qw | 674 | 52 | 0 | 0 |
| cordic_rot | 1943 | 907 | 0 | 2 |
| cordic_vec | 1839 | 849 | 0 | 1 |
| mixer | 351 | 296 | 0 | 4 |
| fir_complex | 181 | 106 | 0 | 2 |
| fir_decimator | 471 | 104 | 0 | 2 |
| fir_interpolator | 338 | 86 | 0 | 2 |
| cic_decimator | 566 | 484 | 0 | 0 |
| cic_interpolator | 580 | 438 | 0 | 0 |
| halfband | 394 | 94 | 0 | 2 |
| iir_biquad | 1614 | 495 | 0 | 24 |
| dc_blocker | 224 | 97 | 0 | 0 |
| moving_average | 246 | 87 | 0 | 0 |
| farrow | 650 | 145 | 0 | 14 |
| gain | 59 | 33 | 0 | 2 |
| power | 0 | 0 | 0 | 0 |
| agc | 385 | 57 | 0 | 8 |
| saturate | 67 | 33 | 0 | 0 |
| rms | 1310 | 123 | 0 | 2 |
| magnitude | 157 | 18 | 0 | 0 |
| magnitude_cordic | 1618 | 601 | 0 | 1 |
| combine | 371 | 33 | 0 | 0 |
| window | 341 | 15 | 0 | 2 |
| fft | 2987 | 360 | 0 | 28 |
| fft_iter | 1039 | 87 | 2 | 4 |
| psd | 855 | 31 | 0 | 2 |
| goertzel | 1086 | 143 | 0 | 17 |
| stats | 289 | 186 | 0 | 2 |
| histogram | 389 | 22 | 0 | 0 |
| ddc | 890 | 317 | 2 | 6 |
| duc | 643 | 302 | 2 | 7 |
| channelizer | 2786 | 1086 | 6 | 24 |
| lms_equalizer | 3750 | 645 | 0 | 84 |
| timing_recovery | 883 | 182 | 0 | 16 |
| fm_demod | 1720 | 790 | 0 | 4 |
| correlator | 927 | 710 | 0 | 14 |

## Place & route — fmax (subset)

| module | ECP5 fmax (MHz) | Xilinx fmax (MHz) |
|---|---|---|
| nco | 279 | 312 |
| mixer | 321 | 266 |
| fir_complex | 214 | 139 |
| fir_decimator | 104 | 143 |
| cic_decimator | 84 | 97 |
| iir_biquad | 54 | 98 |
| fft | 67 | 86 |
| cordic_vec | 191 | 219 |
| ddc | 97 | 126 |

## Xilinx resources (Vivado implementation, subset)

| module | LUT | FF | BRAM | DSP |
|---|---|---|---|---|
| nco | 65 | 33 | 1 | 0 |
| mixer | 107 | 130 | 0 | 4 |
| fir_complex | 84 | 38 | 0 | 8 |
| fir_decimator | 184 | 78 | 0 | 2 |
| cic_decimator | 806 | 484 | 0 | 0 |
| iir_biquad | 167 | 35 | 0 | 36 |
| fft | 1475 | 367 | 0 | 35 |
| fft_iter | 236 | 29 | 1 | 5 |
| cordic_vec | 733 | 827 | 0 | 1 |
| ddc | 384 | 122 | 1 | 6 |

(Regenerate any table with `impl/run.py … --report <file>`.)
