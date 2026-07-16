# LiteDSP Implementation Tests (ECP5 + Xilinx)

Beyond functional simulation, every implementation-registry configuration is run through real
FPGA toolchains to verify it **synthesizes**, that the **portable-only** claim holds across
vendors, and that **resource usage matches expectations**. Representative configurations also
run through place-and-route and are gated on fmax.

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

`impl/run.py` builds each configuration (`impl/modules.py` registry → generated Verilog), parses
LUT/FF/BRAM/DSP usage plus P&R timing, and fails on implementation errors or budget violations.
Resource results may exceed their checked-in baseline by 15%; the fmax floor is set to 85% of the
baseline P&R result. Both the raw measurement (`fmax_mhz`) and its regression floor
(`fmax_min`) are retained in `impl/budgets.json`. The CAD suite used by budgeted CI is pinned in
the workflows.

## Findings (what implementation testing caught)

- **`fft_iter` (iterative FFT) was FPGA-hostile — now fixed.** The first version used *async-read*
  RAM with 2 read + 2 write ports per butterfly; async read blocks BRAM inference and 4 ports
  exceed a BRAM's 2, so Yosys spilled the whole thing to distributed LUT-RAM: **36k LUTs, 0 BRAM**.
  Reworked to *synchronous-read* memory with a **2-phase butterfly** (one read cycle, then one
  compute+write cycle) so each I/Q sample RAM is a single true-dual-port BRAM. Lesson:
  *async-read memories never map to BRAM; large RAMs must be synchronous-read and ≤2 ports.*
- **`nco_qw` (quarter-wave NCO) trades BRAM for logic at small depths.** At `lut_depth=1024` the
  N/4+1 table maps to LUTs; the full-LUT `LiteDSPNCO` is preferable at small table depths.
- **`lms_equalizer` over-provisioned its weight width.** Bounding stable O(1) weights to an
  18-bit Q format lets each weight/sample product use one DSP instead of sign-extending into
  multiple multipliers. Lesson: *size operands to their value range, not accumulator width.*
- **Large unrolled blocks carry intentional throughput costs.** The CORDIC family sustains one
  sample per cycle; SDF FFT storage maps differently on ECP5 and Xilinx. Folded alternatives are
  explicit area/throughput trade-offs rather than free optimizations.
- **`rms` used an unrolled square root despite its low output rate.** Reusing one iterative
  square-root stage substantially reduced Xilinx LUT use. Lesson: *match unrolling to throughput.*
- **fmax is dominated by long combinational and feedback paths.** Feed-forward blocks can often
  accept latency-only retiming; recursive blocks require an architecture-specific change so the
  numerical recurrence is preserved.

## Current results

The generated [`resources.md`](resources.md) table is the single source of current resource and
timing budgets. Each device cell carries its own LUT/FF/BRAM/DSP counts and fmax regression floor,
avoiding stale duplicated tables and accidental mixing of ECP5 and Xilinx timing. Per-block
datasheets present the same data from `impl/budgets.json`.

The fmax value is a **gate floor**, not the raw measured maximum. Implementation runs print their
current raw result; updating a P&R budget records 85% of that result as margin for seed/tool noise.
