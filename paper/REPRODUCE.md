# Reproducing the NDT WCET paper

This guide takes you from a checkout to the numbers, tables, and PDF of the
paper (`main.pdf`). The experiments have **different hardware requirements**, so
they are split into tiers. Pick the highest tier your hardware allows — every
tier below it still holds, because higher tiers only *regenerate* the frozen
inputs that lower tiers consume.

| Tier | What it reproduces | Requires | Entry point |
|------|--------------------|----------|-------------|
| **T0** | `main.pdf` from the committed tables | any machine + `latexmk` | `scripts/reproduce.sh --pdf` |
| **T1** | `tables/*.tex` from the frozen `data/*.json` (+ claim/SHA verification) | any machine + `python3` | `scripts/reproduce.sh` |
| **T2** | `data/wcet*.json` from a fresh WCET campaign | the benchmark host (Ryzen 5900HX, isolated core) | `wcet_campaign.py` → `integrate_campaign.py` |
| T3 | stack-replay + real-frame timing | benchmark host + ROS bag + PCD map | `bench/run_stack_replay.sh` (pointer only) |
| T4 | Raspberry Pi 4 (no_std) serial timing | a physical Raspberry Pi 4 | `awkernel/Makefile` (pointer only) |

This document covers **T0–T2** in full; T3/T4 are cross-repo and hardware-bound,
so they are linked, not duplicated, at the end.

Unless noted, commands are run from the paper directory:

```sh
cd /autoware_workspace/paper
```

## Prerequisites

- **T0**: `latexmk` + a TeX distribution (`pdflatex`, `bibtex`).
- **T1**: `python3` ≥ 3.10, standard library only (`scripts/*.py` import nothing external).
- **T2**: the containerized build environment (`bootstrap.sh` + `build.sh`, see the
  top-level `README.md`), plus the specific host below.

What is **frozen and committed** (so T0/T1 need no benchmark run):
`data/*.json`, `data/raspi4_timing.txt` (+ `*_meta.json`), and the generated
`tables/*.tex`. What is **not committed** (regenerated in T2+): the
`campaign_runs/` trees, which live under the `autoware_core` fork on the
benchmark host.

---

## T0 — Build the PDF from committed artifacts

Fully offline; uses the committed `tables/*.tex` as-is.

```sh
make                      # regenerate tables (T1) then build main.pdf
# or, PDF only, trusting the committed tables:
scripts/reproduce.sh --pdf
```

Output: `main.pdf`.

## T1 — Regenerate the tables and verify the claims

`scripts/gen_tables.py` and `scripts/evt.py` render every `tables/*.tex` from the
frozen `data/`. They are not blind formatters: they **re-verify each numeric
claim**, check the raspi4 serial-log SHA-256 against its provenance sidecar, and
fail if any measurement no longer supports a stated claim.

```sh
scripts/reproduce.sh          # regenerate tables, assert no drift, then build main.pdf
scripts/reproduce.sh --tables # stop after the table regeneration + drift check
```

The driver additionally asserts that the regenerated `tables/` **match the
committed copy** (a git drift check): if they differ, the committed paper no
longer follows from its committed data, and the script exits non-zero with the
diff. `make tables` runs the same two generators without the drift guard.

## T2 — Re-run the WCET campaign

This regenerates the pooled timing inputs (`data/wcet.json`, `wcet_cold.json`,
`wcet_corunner.json`, `wcet_psweep.json`) that T1 consumes. It must run on the
**benchmark host** — the paper's snapshot is a three-boot campaign on a Ryzen
5900HX with the `performance` governor and an isolated benchmark core. The
authoritative step-by-step runbook is
[`bench/CAMPAIGN.md`](../src/core/autoware_core/localization/autoware_ndt_scan_matcher/bench/CAMPAIGN.md);
this section is the paper-side summary.

Path shorthand for this section:

```sh
WS=/autoware_workspace
BENCH="$WS/src/core/autoware_core/localization/autoware_ndt_scan_matcher/bench"
```

**1. Prepare the host** (governor + core isolation; needs privileges):

```sh
sudo "$WS/cpu_conf.sh"        # performance governor, pin 3.2 GHz, offline the SMT sibling of cpu2
# ... run the campaign ...
sudo "$WS/cpu_conf_restore.sh"  # restore afterwards
```

**2. Build the benchmark binary** (Rust engine + replay + bench, tracing OFF —
the pooler rejects trace-enabled binaries):

```sh
cd "$WS"
source /opt/ros/humble/setup.bash
colcon build --packages-select autoware_ndt_scan_matcher \
  --cmake-args -DCMAKE_BUILD_TYPE=Release \
               -DNDT_USE_RUST=ON -DNDT_BUILD_BENCH=ON -DNDT_BUILD_TRACED=OFF
```

**3. Run the campaign for three distinct boots.** The frozen primary campaign is
`plan/campaign_config_unified_bounded.json` (`integrate_campaign.py`'s default).
Per boot `N` (1, 2, 3), from `$BENCH` (see `CAMPAIGN.md` for `prepare`/`status`):

```sh
cd "$BENCH"
CFG="$WS/plan/campaign_config_unified_bounded.json"
python3 wcet_campaign.py --config "$CFG" verify-env
for S in warm cold corunner:membw corunner:llc corunner:fp; do
  python3 wcet_campaign.py --config "$CFG" run --session "$N" --series "$S" --resume
done
python3 wcet_campaign.py --config "$CFG" merge --session "$N"
```

Each session records the kernel boot ID and refuses to continue across a reboot,
which is what makes "three distinct boots" enforceable rather than advisory.

**4. Run the capacity P-sweep** (separate config, warm-only):

```sh
python3 wcet_campaign.py --config "$BENCH/campaign_config_psweep.json" run  ...  # per CAMPAIGN.md
```

**5. Pool the sessions into `data/`.** Validate first, then write:

```sh
cd "$WS"
python3 paper/scripts/integrate_campaign.py --check-only   # validate provenance only
python3 paper/scripts/integrate_campaign.py                # refresh data/wcet*.json

# P-sweep pooled separately:
python3 paper/scripts/integrate_campaign.py \
  --runs-dir "$BENCH/campaign_runs/psweep_3x100_bounded" \
  --config   "$BENCH/campaign_config_psweep.json" \
  --warm-output-name wcet_psweep.json --warm-only
```

Pooling **rejects** trace-enabled binaries, reused boot IDs, campaign-identity
drift, and any cell whose environment sidecar recorded a measurement problem —
so a run that survives the pooler is provenance-clean by construction.

**6. Rebuild** the tables and PDF from the refreshed data:

```sh
cd "$WS/paper" && scripts/reproduce.sh
```

---

## T3 / T4 — hardware-bound experiments (pointers)

These live in other repos and need dedicated hardware; they refresh only their
own committed inputs (`data/stack_replay.json` / `data/realdata.json` and
`data/raspi4_timing.txt`). Run them from their own runbooks:

- **T3 — stack replay & real-frame timing** (needs a ROS bag at
  `~/autoware_ista_data/loc_bag` and a PCD map): `bench/run_stack_replay.sh`
  builds the C++ and Rust stacks (`install_stack_cpp/`, `install_stack_rust/`),
  runs the `cpp1 rust1 rust2 cpp2` sequence, and calls `analyze_stack_replay.py`.
  Real-frame timing is merged into `data/realdata.json` by `bench/wcet_realdata.py`.
  The production-guess control replay (`data/realdata_prodprior.json`,
  iteration/counter quantities only — no timing discipline required) replays the
  archived capture directly; see the paper `README.md` data-pipeline step 3.
- **T4 — Raspberry Pi 4 (no_std)**: build the on-target harness with
  `make aarch64 BSP=raspi4 RELEASE=1 FEATURES=ndt` in `awkernel/`, flash
  `kernel8.img`, and capture the UART serial log. The frozen log and its
  provenance are `data/raspi4_timing.txt` + `data/raspi4_timing_meta.json`;
  `gen_tables.py` verifies the log SHA-256 and engine commit during T1.

## Provenance notes

- The host snapshot is the 2026-07-20/2026-07-21 three-boot campaign (Ryzen
  5900HX, performance governor, isolated benchmark core).
- The raspi4 artifact is frozen: `data/raspi4_timing_meta.json` pins the target,
  engine commit, exact build command, and SHA-256 of both `kernel8.img` and the
  serial log.
- Because T1 verifies claims and hashes, a green `scripts/reproduce.sh` run is
  itself evidence that the committed paper is internally consistent with its
  committed data.
