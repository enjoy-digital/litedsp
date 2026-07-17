# LiteDSP Implementation Tests (ECP5 + Xilinx)

Beyond functional simulation, every implementation-registry configuration is run through real
FPGA toolchains to verify it **synthesizes**, that the **portable-only** claim holds across
vendors, and that **resource usage matches expectations**. Representative configurations also
run through place-and-route and are gated on fmax.

## Toolchains & targets

| Vendor | Reference toolchain | Flow | Target |
|---|---|---|---|
| Lattice **ECP5** | OSS CAD Suite `2025-06-25` (Yosys 0.54+23, nextpnr 0.8-35) | Yosys `synth_ecp5` (OOC) + nextpnr-ecp5 + Trellis | `LFE5UM5G-85F` / CABGA381 |
| **Xilinx** 7-series | Vivado 2025.2 | Vivado out-of-context synth + implementation | `xc7a200tsbg484-3` |
| **Xilinx Artix UltraScale+** | Vivado 2025.2 | Vivado out-of-context synth + implementation | `xcau20p-ffvb676-2-e` |

## Running

```
python3 impl/run.py --device ecp5   --flow synth                 # all blocks, Yosys (fast)
python3 impl/run.py --device xilinx --flow synth --subset        # Vivado OOC synth (subset)
python3 impl/run.py --device xilinx_au --flow synth              # Artix UltraScale+ OOC synth
python3 impl/run.py --device xilinx_au --flow synth --jobs 2     # two licensed Vivado workers
python3 impl/run.py --device ecp5   --flow pnr  --subset         # + nextpnr P&R -> fmax
python3 impl/run.py --device xilinx --flow pnr  --subset         # + Vivado impl -> fmax
python3 impl/run.py --device ecp5   --flow pnr  --target-closed --target-gate # strict targets
python3 impl/run.py --device xilinx --flow pnr  --target-closed --target-gate # strict Artix targets
python3 impl/run.py --device xilinx_au --flow pnr --target-closed --target-gate # strict AU+ targets
python3 impl/run.py --device ecp5 --flow pnr --module fft_interleaved_x2 --repeat 3 --pnr-timeout 1800
python3 impl/run.py --device ecp5   --flow synth --update-budgets # refresh the baseline
```

`impl/run.py` builds each configuration (`impl/modules.py` registry → generated Verilog), parses
LUT/FF/BRAM/DSP usage plus P&R timing, and fails on implementation errors or budget violations.
Each Vivado P&R directory retains `timing_summary.rpt` and the ten worst paths in
`timing_paths.rpt` so a missed target can be traced to an architectural path rather than treated
as unexplained seed noise.
The `ddc_ip` configuration is a complete generated integration sentinel: NCO/mixer/FIR/decimator
datapath, AXI-Stream ingress/egress, AXI-Lite-to-CSR bridge, and all block CSR banks are synthesized
and routed together rather than testing only isolated DSP blocks.
Resource results may exceed their checked-in baseline by 15%; independent `synth` and `pnr`
resource dictionaries prevent pre-optimization synthesis utilization from overwriting post-route
utilization. The fmax floor is set to 85% of the baseline P&R result. Both the raw measurement
(`fmax_mhz`) and its regression floor (`fmax_min`) are retained in `impl/budgets.json`. A flat
P&R-preferred compatibility summary continues to feed generated docs and GUI badges. An optional `fmax_target` is a separate
engineering objective: misses are reported but only fail a run when `--target-gate` is selected.
For route-sensitive investigations, `--seeds` or `--repeat` synthesizes once and runs bounded
nextpnr variants, retaining per-seed logs and reporting worst/median/best fmax. Budget updates
use the median completed route. `--pnr-timeout` bounds each nextpnr/Vivado invocation so a
capacity-cliff design cannot stall a nightly job indefinitely.
Independent modules can be built with `--jobs N`; results are collected in registry order and a
single process updates the budget file after every worker completes. The default remains one job
so CI runners with a single Vivado license are unchanged.
Refreshing measured budgets preserves these manually reviewed targets. The CAD suite used by
budgeted CI is pinned in the workflows. `TARGET_CLOSED` is the small reviewed subset that has
already achieved its objective; CI reruns those blocks with strict target gating while targets
for architecture work in progress remain advisory. `.github/workflows/impl-xilinx.yml` provides
equivalent strict Artix-7 and Artix UltraScale+ jobs on a self-hosted runner labelled `vivado`;
both also route the complete generated `ddc_ip` integration sentinel.
When a new device profile is first characterized, it inherits the module's reviewed engineering
target from an existing profile; its measured resource baseline and 85% timing floor remain fully
device-specific.

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
- **Latency-only retiming cleared two feed-forward timing paths.** Registering Farrow coefficient
  formation and each Horner multiply/add boundary raised its ECP5 result from 67.2 to 125.1 MHz
  (latency 3 to 7 cycles). Registering the window multiplier outputs before rescaling raised that
  block from 89.9 to 117.6 MHz (latency 1 to 2 cycles). Both remain one sample per clock and
  bit-exact under backpressure.
- **Runtime-programmable FIR reductions must be structurally pipelined.** Vivado flattened the
  complete DDC IP's 33-tap expression into a 32-DSP cascade with 68 logic levels. The explicit
  `architecture="pipelined"` FIR registers all six balanced reduction levels and uses a common
  elastic enable, preserving bit-exact one-sample-per-clock operation under backpressure. FIR
  latency rises from 3 to 9 clocks; the generated IP now closes 100 MHz on all reference parts.
- **The DUC polyphase MAC benefits from a deliberate drain cycle.** A sequential coefficient
  pointer and registered product separate asynchronous coefficient selection and multiplication
  from accumulator feedback. The L=8/65-tap configuration rises from 74.3 to 107.1 MHz on ECP5;
  `cycles_per_output` rises from 11 to 12 and the classic API mode remains available.
- **Registering the resampler-farm RAM boundary improves both timing and mapping.** Operand and
  product registers split the banked history lookup, multiply, and accumulator feedback. The
  ECP5 implementation rises from 86.3 to a 152.8 MHz three-route median and maps its histories
  into two BRAMs, at the cost of two drain clocks per decimated output.
- **Frame-sync retiming must include the matched filter on Xilinx.** Splitting raw-power/energy
  and normalized-threshold products raises ECP5 timing, but Artix-7 remains limited by a flattened
  DSP48 FIR cascade. Registering all matched-filter reduction levels as part of the same explicit
  option yields a 132.2 MHz ECP5 median and 147.5 MHz Artix-7 result at five samples of latency.
- **fmax is dominated by long combinational and feedback paths.** Feed-forward blocks can often
  accept latency-only retiming; recursive blocks require an architecture-specific change so the
  numerical recurrence is preserved. Folded/registered options now close the reviewed Viterbi,
  serial/parallel CIC, AGC, and iterative-FFT configurations at 100 MHz while preserving their
  original compatibility modes. The folded streaming SDF FFT now also closes at half-rate, and
  its two-context interleaved composition closes at one aggregate sample per clock. Native P-wide
  FFTs now use an explicit hazard-bypassed recurrence pipeline: this materially improves P=2
  timing while preserving full lane rate, but does not close 100 MHz on ECP5 or Artix-7. The
  reviewed options, trade-offs and acceptance criteria are tracked in
  [`timing_architecture.md`](timing_architecture.md).
- **Vector SDF needs an explicit recurrence pipeline.** A shared P-wide feedback memory enables
  sustained P=2/P=4 operation. Registering its lane differences and four real twiddle products,
  then bypassing same-address feedback hazards, raises P=2 from 63.0 to a 77.7 MHz ECP5 median
  and from 82.4 to 97.7 MHz on Artix-7. The cost is 143 rather than 137 clocks of frame latency
  and additional pipeline state; P=4 similarly moves from 61.2 to 67.8 MHz on ECP5. Their
  100 MHz objectives remain distinct from their regression floors.
- **The scalable PFB needs both algorithmic and timing architecture changes.** Replacing the
  M² direct DFT with a time-multiplexed radix-2 transform makes M>=16 practical, but its first
  memory-read/multiply schedule reached only 74.6 MHz. Registering read/difference, multiply,
  and the two single-port writes raises the M=16/T=8 median to 113.2 MHz while retaining the
  O(M log M) schedule and bit-exact per-rank rounding model.

## Current results

The generated [`resources.md`](resources.md) table is the single source of current resource and
timing budgets. Each device cell carries its own LUT/FF/BRAM/DSP counts and fmax regression floor,
avoiding stale duplicated tables and accidental mixing of ECP5 and Xilinx timing. Per-block
datasheets present the same data from `impl/budgets.json`.

The Artix UltraScale+ profile has a complete baseline on `xcau20p-ffvb676-2-e`: all 87 registry
configurations pass out-of-context synthesis and all 38 representative configurations pass
place-and-route. The 23 reviewed timing architectures close their 100 MHz targets on this
profile. The complete generated `ddc_ip` sentinel also routes on every family; its raw results
are 107.6 MHz on ECP5, 121.2 MHz on Artix-7, and 274.7 MHz on Artix UltraScale+. It is now part
of the strict 100 MHz target set. Relative to the classic reduction, ECP5 moves from 6461 LUT /
4338 FF / 70 DSP to 4800 / 6866 / 70; Artix-7 moves from 649 LUT / 1986 FF / 70 DSP to 1009 /
1802 / 100. The additional state and Xilinx DSP48 adders are the published cost of eliminating
the long combinational cascade while retaining runtime coefficient control and full throughput.

The fmax value is a **gate floor**, not the raw measured maximum. Implementation runs print their
current raw result; updating a P&R budget records 85% of that result as margin for seed/tool noise.
