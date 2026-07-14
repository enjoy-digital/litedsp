# Contributing to LiteDSP

LiteDSP follows the LiteX ecosystem conventions — the
[LiteX coding style](https://github.com/enjoy-digital/litex/blob/master/doc/coding_style.md)
plus the interface contract in `doc/interfaces.md`. This file is the short version.

## Adding a new block

Every block obeys the same streaming + control contract (details and rationale in
`doc/interfaces.md`):

1. BSD-2-Clause header; imports grouped Migen → `litex.gen` → CSR/stream → `litedsp`.
2. `@ResetInserter()` `LiteXModule` (or `stream.PipelinedActor` only for *stateless* maps).
   Public hardware classes carry the `LiteDSP` prefix (`LiteDSPNCO`, `LiteDSPFIRFilter`, ...),
   like `LiteEthMAC`/`LiteDRAMDMAReader` in the other LiteX cores. Non-hardware helpers
   (data descriptors like `Qmn`, flow netlist/metadata classes, GUI classes, host-side
   drivers in `litedsp/software/`) stay unprefixed, as do functions (`iq_layout`, `rounded`).
3. Declare endpoints (`sink`/`source`, layouts from `litedsp.common`), plain control Signals,
   and `self.latency` (a number, or an explicit `None` for data-dependent blocks); then the
   `# # #` separator; then the hardware. Re-export the class from the subpackage `__init__.py`.
   Parameter vocabulary (enforced by `test/test_metadata_policy.py`): `decimation`/
   `interpolation` for rate factors (never `R`/`L`/`factor`), `n_stages`/`diff_delay` for CIC,
   `n_taps` + `coefficients` for FIR, `sections` for SOS lists, `polynomial` for LFSR taps,
   `N` only as a transform size. Every parameter has a default; validate with
   `litedsp.common.check(cond, msg)` (raises `ValueError`), not `assert`. Layout-preserving
   in-line blocks add `litedsp.common.add_bypass(self)` + `add_bypass_csr(self)`.
4. Full `valid`/`ready` backpressure — never drop or duplicate samples under stalls. Stateful
   blocks use an elastic pipeline (see `litedsp/filter/fir.py`).
5. Round + saturate at every downsizing point via `litedsp.common` (`rounded`/`saturated`/
   `scaled`) — never raw truncation or wrap.
6. `if with_csr: self.add_csr()` at the end; CSRs use named, documented `CSRField`s and align
   per the LiteX style. Trigger-type blocks may also offer `with_irq=True` / `add_irq()`
   (LiteX `EventManager`).
7. Add a NumPy golden model in `test/models.py` and a test in `test/test_<block>.py`:
   bit-exact where the arithmetic is deterministic, SNR-thresholded where rounding differs,
   always under randomized backpressure (`test/common.py`).
8. Consider registering the block in `litedsp/flow/registry.py` (flow/GUI availability) and,
   if runtime-controllable, a driver in `litedsp/software/drivers.py`.

## Running the tests

```bash
python3 -m unittest discover -s test -v      # Golden-model + integration tests.
python3 sim/run_nco.py                       # Verilator co-simulation (needs verilator).
python3 impl/run.py --device ecp5            # Resource/fmax sweep (needs yosys/nextpnr).
```

CI runs the unittest suite (with Verilator), a Yosys/ECP5 synthesis of every block, and
elaborates the `bench/` SoCs; keep all three green.

## Commits / PRs

- Small, focused commits in the LiteX style: `module: summary` subject, body explaining why.
- Match the surrounding code (alignment, naming, comment density); preserve public names.
- Update `CHANGELOG.md` for user-visible changes, and `doc/resources.md`
  (`python3 impl/report.py`) when a sweep changes the budgets.

## Releases

- Versioning follows the LiteX ecosystem calendar convention (`YYYY.MM`), kept in sync in
  `setup.py` and `litedsp/__init__.py`.
- Pushing a `v<version>` tag (or manually dispatching the `PyPI` workflow) builds and publishes
  to PyPI via trusted publishing (`.github/workflows/pypi.yml`).
