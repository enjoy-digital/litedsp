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
python3 impl/run.py --device ecp5   --flow pnr  --stress --pnr-timeout 5400 # capacity-cliff routes
python3 impl/run.py --device ecp5   --flow pnr  --stability --repeat 3 --target-gate # route medians
python3 impl/run.py --device ecp5   --flow pnr  --subset --closed-target-gate # one-pass CI gate
python3 impl/run.py --device xilinx --flow pnr  --subset         # + Vivado impl -> fmax
python3 impl/run.py --device ecp5   --flow pnr  --target-closed --target-gate # strict targets
python3 impl/run.py --device xilinx --flow pnr  --target-closed --target-gate # strict Artix targets
python3 impl/run.py --device xilinx_au --flow pnr --target-closed --target-gate # strict AU+ targets
python3 impl/run.py --device ecp5 --flow pnr --module fft_interleaved_x2 --repeat 3 --pnr-timeout 1800
python3 impl/run.py --device xilinx --flow pnr --module fft_parallel_native_x2 --strategies all
python3 impl/run.py --device ecp5   --flow synth --update-budgets # refresh the baseline
```

`impl/run.py` builds each configuration (`impl/modules.py` registry → generated Verilog), parses
LUT/FF/BRAM/DSP usage plus P&R timing, and fails on implementation errors or budget violations.
Each Vivado P&R directory retains `timing_summary.rpt` and the ten worst paths in
`timing_paths.rpt` so a missed target can be traced to an architectural path rather than treated
as unexplained seed noise.
The `ddc_ip` and `qpsk_receiver_ip` configurations are complete generated integration sentinels.
The former covers an NCO/mixer/FIR/decimator datapath; the latter covers QPSK carrier recovery,
adaptive symbol timing, and hard decisions. Both include AXI-Stream ingress/egress, the
AXI-Lite-to-CSR bridge, and all block CSR banks, and are synthesized and routed together rather
than testing only isolated DSP blocks.
Resource results may exceed their checked-in baseline by 15%; independent `synth` and `pnr`
resource dictionaries prevent pre-optimization synthesis utilization from overwriting post-route
utilization. The fmax floor is set to 85% of the baseline P&R result. Both the raw measurement
(`fmax_mhz`) and its regression floor (`fmax_min`) are retained in `impl/budgets.json`. A flat
P&R-preferred compatibility summary continues to feed generated docs and GUI badges. An optional `fmax_target` is a separate
engineering objective: misses are reported but only fail a run when `--target-gate` is selected.
`--closed-target-gate` applies that strict policy only to `TARGET_CLOSED`, allowing one P&R subset
run to keep objectives under development advisory without rerouting the reviewed blocks.
For route-sensitive investigations, `--seeds` or `--repeat` synthesizes once and runs bounded
nextpnr variants. On Xilinx, `--strategies all` synthesizes once and independently runs Vivado's
default, Explore, and high-net-delay/HigherDelayCost timing algorithms. Both retain per-run timing
reports and report worst/median/best fmax; budget updates use the median completed route.
`--pnr-timeout` bounds each nextpnr/Vivado invocation so a capacity-cliff design cannot stall a
nightly job indefinitely.
The native x4 FFT and z-parallel LDPC decoder remain in `PNR_STRESS`, outside the bounded
push/PR subset. Both close 100 MHz and are also gated across three ECP5 seeds in the
route-sensitive stability set; their Xilinx strategy sweeps remain in the stress selection. The FFT's ready-cut x2
configuration has robust margin in the regular strict subset, while the compact serial LDPC
decoder remains its regular strict implementation sentinel.
The classic serial FFT and the older split/folded parallel FFT configurations are retained as
compatibility and comparison points, so they carry measured regression floors but no 100 MHz
engineering objective. The folded/interleaved serial variants and native vector FFTs are the
reviewed timing-oriented architectures; only their targets participate in closure tracking.
The route-sensitive target-closed DPD, native P=4 FFT, and z-parallel LDPC configurations are collected in
`PNR_STABILITY`. Push/PR CI routes each across seeds 0, 1 and 2 on an independent runner and gates
its median, avoiding single-placement noise while preserving the strict 100 MHz objective. The
two-sample pipelined AGC has enough margin to remain in the regular single-route subset.
Independent modules can be built with `--jobs N`; results are collected in registry order and a
single process updates the budget file after every worker completes. The default remains one job
so CI runners with a single Vivado license are unchanged.
Refreshing measured budgets preserves these manually reviewed targets. The CAD suite used by
budgeted CI is pinned in the workflows. `TARGET_CLOSED` is the small reviewed subset that has
already achieved its objective; CI gates those blocks strictly while targets
for architecture work in progress remain advisory. `.github/workflows/impl-xilinx.yml` provides
equivalent strict Artix-7 and Artix UltraScale+ jobs on a self-hosted runner labelled `vivado`;
both also sweep the native x2/x4 FFTs across three timing strategies. The complete generated `ddc_ip`
integration sentinel is already in the strict target set, so it is not routed a second time.
Implementation jobs retain synthesis logs, route logs, and detailed timing reports as artifacts,
including on failure; the nightly ECP5 job additionally repeats the closest closed targets across
three nextpnr routes.
ECP5 baselines are calibrated against that pinned hosted toolchain. In particular, the staged CIC
interpolator's route-sensitive ready chain uses the 184.7 MHz hosted result (a local three-seed
168.4/184.8/240.5 MHz spread), and pipelined CFR uses its 106.3 MHz hosted result. Their separate
100 MHz engineering targets remain strict even where the 85% regression floor is lower.
When a new device profile is first characterized, it inherits the module's reviewed engineering
target from an existing profile; its measured resource baseline and 85% timing floor remain fully
device-specific.

The QPSK receiver sentinel selects an explicit four-sample delayed carrier-loop architecture.
Registered NCO operands, mixer products, and detector error cut the former one-cycle
NCO-LUT/multiply/detector/PI arc while an accepted-sample error queue preserves deterministic
behavior through bubbles and backpressure. Three-route/strategy medians are 108.8 MHz on ECP5,
128.1 MHz on Artix-7, and 234.2 MHz on Artix UltraScale+, so the complete generated receiver now
carries the same strict 100 MHz objective on all three profiles. The one-sample classic loop
remains the API default; latency, area, and acquisition measurements are published in
[`timing_architecture.md`](timing_architecture.md).

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
- **The FIR decimator needs a register before, not only after, its multiplier.** Registering the
  asynchronous history/coefficient operands adds one drain clock, maps the DDC histories into
  block RAM, and raises the three-route ECP5 medians from 103.5 to 184.9 MHz for the standalone
  FIR sentinel and from 93.6 to 151.4 MHz for the DDC. Artix-7 and Artix UltraScale+ DDC routes
  reach 156.4 and 331.7 MHz; the classic API schedule remains available.
- **Registering the resampler-farm RAM boundary improves both timing and mapping.** Operand and
  product registers split the banked history lookup, multiply, and accumulator feedback. The
  ECP5 implementation rises from 86.3 to a 152.8 MHz three-route median and maps its histories
  into two BRAMs, at the cost of two drain clocks per decimated output.
- **Frame-sync retiming must include the matched filter on Xilinx.** Splitting raw-power/energy
  and normalized-threshold products raises ECP5 timing, but Artix-7 remains limited by a flattened
  DSP48 FIR cascade. Registering all matched-filter reduction levels as part of the same explicit
  option yields a 132.2 MHz ECP5 median and 147.5 MHz Artix-7 result at five samples of latency.
- **Serial FEC still needs scheduled arithmetic boundaries.** Registering GF multiplier operands,
  splitting Chien reductions, and staging the shared inverse/Forney result raises the RS(255,223)
  decoder from 86.5 MHz to a 124.3 MHz ECP5 three-route median. Worst-case decoding grows from
  2249 to 3126 clocks; the correction algorithm and output/status behavior remain bit-exact.
- **Carrier recovery needs sample-domain delayed feedback, not clock-domain retiming.** The QPSK
  receiver's four-sample loop queues completed detector errors until the corresponding accepted
  sample distance has elapsed, so stalls cannot alter its trajectory. The complete generated core
  rises from 41.7/65.8/126.4 MHz to 108.8/128.1/234.2 MHz on ECP5/Artix-7/Artix UltraScale+ while
  retaining one sample/clock throughput; output latency rises from one to three clocks.
- **fmax is dominated by long combinational and feedback paths.** Feed-forward blocks can often
  accept latency-only retiming; recursive blocks require an architecture-specific change so the
  numerical recurrence is preserved. Folded/registered options now close the reviewed Viterbi,
  serial/parallel CIC, AGC, and iterative-FFT configurations at 100 MHz while preserving their
  original compatibility modes. The folded streaming SDF FFT now also closes at half-rate, and
  its two-context interleaved composition closes at one aggregate sample per clock. Native P-wide
  FFTs now use an explicit hazard-bypassed recurrence pipeline: this materially improves timing
  while preserving full lane rate; P=2 closes 100 MHz on all three profiles. The
  reviewed options, trade-offs and acceptance criteria are tracked in
  [`timing_architecture.md`](timing_architecture.md).
- **Vector SDF needs an explicit recurrence pipeline.** A shared P-wide feedback memory enables
  sustained P=2/P=4 operation. Registering its lane differences and required product bits,
  bypassing same-address feedback hazards, and cutting the cascade ready path raises P=2 from
  63.0 to a 122.8 MHz ECP5 median and from 82.4 to 111.4 MHz on Artix-7. The cost is 144 rather
  than 137 clocks of frame latency plus one beat of stall-only skid storage; full lane rate is
  unchanged. P=4 remains a separately reported capacity-stress configuration.
- **The scalable PFB needs both algorithmic and timing architecture changes.** Replacing the
  M² direct DFT with a time-multiplexed radix-2 transform makes M>=16 practical, but its first
  memory-read/multiply schedule reached only 74.6 MHz. Registering read/difference, multiply,
  and the two single-port writes raises the M=16/T=8 median to 113.2 MHz while retaining the
  O(M log M) schedule and bit-exact per-rank rounding model. The 2x-oversampled mode advances
  by M/2 inputs and applies the required alternating odd-bin correction; its separate sentinel
  routes at 105.2/129.2/227.7 MHz on ECP5/Artix-7/Artix UltraScale+.

## Current results

The generated [`resources.md`](resources.md) table is the single source of current resource and
timing budgets. Each device cell carries its own LUT/FF/BRAM/DSP counts and fmax regression floor,
avoiding stale duplicated tables and accidental mixing of ECP5 and Xilinx timing. Per-block
datasheets present the same data from `impl/budgets.json`.

The Artix UltraScale+ profile has a complete baseline on `xcau20p-ffvb676-2-e`: all 93 registry
configurations pass out-of-context synthesis; 38 bounded representative configurations form the
regular P&R subset, two route-sensitive configurations form the stability set, and two wide
capacity/timing configurations form the stress set (native P=4 belongs to both latter views).
All 41 distinct configurations pass place-and-route. The 30 reviewed
timing architectures close their 100 MHz targets on this
profile. The complete generated `ddc_ip` sentinel also routes on every family; its raw results
are 107.6 MHz on ECP5, 121.2 MHz on Artix-7, and 274.7 MHz on Artix UltraScale+. It is now part
of the strict 100 MHz target set. Relative to the classic reduction, ECP5 moves from 6461 LUT /
4338 FF / 70 DSP to 4800 / 6866 / 70; Artix-7 moves from 649 LUT / 1986 FF / 70 DSP to 1009 /
1802 / 100. The additional state and Xilinx DSP48 adders are the published cost of eliminating
the long combinational cascade while retaining runtime coefficient control and full throughput.

The fmax value is a **gate floor**, not the raw measured maximum. Implementation runs print their
current raw result; updating a P&R budget records 85% of that result as margin for seed/tool noise.
