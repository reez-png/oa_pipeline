# oa_pipeline

Eight-notebook preprocessing pipeline for ocean-acidification carbonate
chemistry data. Reads an Excel workbook of TA / pH / temperature /
salinity / DIC measurements, applies CRM-corrected QC, harmonises
canonical column names, builds best-source analysis fields, checks
duplicates and replicates, runs carbonate-system internal-consistency
checks, and produces an analysis-ready CSV with a per-row
PASS / REVIEW / FAIL verdict.

```text
oa_prelim_data.xlsx
        │
        │ (Notebook 01 optional: HTML preview of each sheet)
        ▼
   02_ta_ph_qc          ─→  derived.csv         (CRM + pH-std corrections)
        │
        │ (Notebook 03 optional: inspect 02's outputs)
        ▼
   04_stage1a           ─→  staged.csv          (canonical schema, alias resolution)
        ▼                   analysis_ready.csv
   05_stage1b           ─→  analysis_fields.csv (best-source coalescing)
        ▼                   analysis_ready_samples.csv
   06_stage2            ─→  enhanced.csv        (duplicates + replicate harmonisation)
        ▼
   07_stage3            ─→  enhanced.csv        (DIC species-sum + pH diagnostic)
        ▼
   08_stage4            ─→  analysis_ready.csv  ◄── the final deliverable
                            + PASS / REVIEW / FAIL verdict per row
```

---

## Quick start

```bash
# 1. Set up the environment (one-time)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # editable install + tests + papermill + parquet

# 2. Build the bundled example dataset (one-time, deterministic)
python examples/make_example_data.py

# 3. Run the whole chain end-to-end on the example
./run_pipeline.sh examples/example_data.xlsx ./outputs

# 4. The final deliverable
head outputs/oa_stage4_outputs/data/analysis_ready.csv

# 5. (Optional) run the test suite — 57 tests, ~15 seconds
pytest
```

There is also a [quickstart tutorial notebook](examples/quickstart.ipynb)
that walks through the same flow interactively and shows how to trace a
flagged row back through the per-stage audit tables.

---

## Recommended on-disk layout

Three things matter about this layout and they are all easy to get wrong:

1. **Modules sit at the project root** alongside the notebooks — *not*
   in a `src/` subfolder. Notebooks `from oa_common import die` work
   without setup because the working directory is on Python's path
   automatically.
2. **`examples/` and `tests/` are real subfolders.** If you scatter
   `example_data.xlsx`, `quickstart.ipynb`, `conftest.py`, and the
   `test_*.py` files at the project root, `pytest` will skip them
   (the `pyproject.toml` says `testpaths = ["tests"]`) and the
   integration test will fail to find `examples/example_data.xlsx`.
3. **`outputs/` and `runs/` are reproducible artefacts.** They are
   `.gitignore`d and should not be synced to OneDrive — see the
   "Note for OneDrive users" below.

```text
oa_pipeline/                          ← project root, what you cd into
│
├── README.md                          ← this file
├── CONTRIBUTING.md                    ← contributor orientation
├── LICENSE                            ← MIT
├── pyproject.toml                     ← packaging + pytest config
├── requirements.txt                   ← Python deps (pinned lower bounds)
├── run_pipeline.sh                    ← one-command runner
├── .gitignore
│
├── 01_excel_viewer.ipynb              ← the eight notebooks
├── 01_excel_viewer.README.md             (READMEs sit next to their notebook
├── 02_ta_ph_qc.ipynb                      so you can edit them side-by-side)
├── 02_ta_ph_qc.README.md
├── 03_qc_output_review.ipynb
├── 03_qc_output_review.README.md
├── 04_stage1a.ipynb
├── 04_stage1a.README.md
├── 05_stage1b.ipynb
├── 05_stage1b.README.md
├── 06_stage2.ipynb
├── 06_stage2.README.md
├── 07_stage3.ipynb
├── 07_stage3.README.md
├── 08_stage4.ipynb
├── 08_stage4.README.md
│
├── oa_common.py                       ← shared modules (imported by notebooks)
├── oa_inspect.py                          Python finds them automatically
├── oa_policy.py                           because they sit at the project root
├── oa_qc_ta_ph.py                         next to the notebooks.
├── oa_schema.py
├── oa_stage1b.py
├── oa_stage2.py
├── oa_stage3.py
├── oa_stage4.py
│
├── examples/                          ← bundled synthetic dataset + tutorial
│   ├── make_example_data.py              deterministic generator (fixed seed)
│   ├── example_data.xlsx                 27-row dataset: 20 samples + 4 CRMs +
│   │                                     3 pH standards, four sample rows
│   │                                     deliberately broken so the pipeline
│   │                                     has known issues to flag
│   └── quickstart.ipynb                  17-cell tutorial that runs the chain
│                                         on the example data
│
├── tests/                             ← pytest suite, 57 tests, ~15s end-to-end
│   ├── __init__.py                       marker file so pytest treats this as a package
│   ├── conftest.py                       shared fixtures
│   ├── test_coalesce.py                  Stage 1B best-source picker
│   ├── test_schema.py                    alias resolution + duplicate-key bug
│   ├── test_readiness.py                 Stage 4 PASS/REVIEW/FAIL classifier
│   └── test_pipeline_e2e.py              full chain on example_data.xlsx
│
├── configs/                           ← (optional) YAML / JSON config overrides
│   ├── 04_stage1a.yaml                    one file per stage, named after the
│   ├── 06_stage2.yaml                     notebook; the runner picks them up
│   └── 08_stage4.yaml                     with `--config-dir configs/`
│
├── data/                              ← (optional) input data; can live anywhere
│   └── oa_prelim_data.xlsx
│
├── outputs/                           ← per-stage output trees (gitignore this)
│   ├── oa_prelim_data__qc_outputs/        from Notebook 02
│   │   └── sheet_0/
│   │       ├── data/derived.csv           ◄── Stage 1A reads this
│   │       ├── tables/...
│   │       ├── reports/...
│   │       └── logs/...
│   ├── oa_stage1a_outputs/                from Notebook 04
│   │   ├── data/staged.csv                ◄── Stage 1B reads this
│   │   ├── data/analysis_ready.csv
│   │   └── ...
│   ├── oa_stage1b_outputs/                from Notebook 05
│   ├── oa_stage2_outputs/                 from Notebook 06
│   ├── oa_stage3_outputs/                 from Notebook 07
│   └── oa_stage4_outputs/                 from Notebook 08
│       ├── data/
│       │   └── analysis_ready.csv         ◄── the final deliverable
│       ├── tables/
│       │   ├── range_flags_long.csv
│       │   ├── dic_species_audit.csv
│       │   └── ...
│       ├── reports/report.md
│       └── logs/manifest.json
│
└── runs/                              ← papermill-executed notebooks (gitignore this)
    └── 2026-05-16T12-24-19Z/              one folder per pipeline run, timestamped
        ├── 02_ta_ph_qc.run.ipynb          fully-executed copy of each notebook,
        ├── 04_stage1a.run.ipynb           with cell outputs preserved for the audit
        └── ...
```

### Why this layout

- **Modules sit at the project root** rather than in a `src/` subfolder.
  Python's default `sys.path` includes the working directory, so notebooks
  just `from oa_common import die` with no setup. The `src/` convention is
  for installable packages; this is a pipeline that runs in place.
- **READMEs sit next to their notebook.** Open the .ipynb in Jupyter, open
  the .md in any editor, edit them side by side. Stashing docs in a `docs/`
  folder makes editing harder and provides no benefit when you have eight
  README files.
- **`outputs/` and `runs/` are gitignored.** Pipeline output is reproducible
  from input + code + config; checking it into git creates a noisy diff and
  bloats history. Add this to `.gitignore`:
  ```
  outputs/
  runs/
  .venv/
  __pycache__/
  ```
- **`configs/` is a convention, not a requirement.** Most users won't need
  it. When you do (e.g. cruise-grade SD thresholds, regional range
  bounds), one YAML per stage with a fixed name keeps the runner simple.

### Note for OneDrive users

The original workbook lives in OneDrive. **Put the *project* somewhere
else** — a local SSD path like `~/projects/oa_pipeline/`. The pipeline
writes thousands of small files into `outputs/` and `runs/`; OneDrive
will try to sync each one and you'll either run out of throughput or hit
the file-count cap. The xlsx itself can stay in OneDrive — the runner
just reads it, it never writes back.

---

## The eight notebooks at a glance

Each notebook is a self-contained Papermill-driven stage. Restart-and-run-all
on any one works; the chain is glued together by deterministic output paths.

| # | Notebook | Role | Reads | Writes |
|--:|----------|------|-------|--------|
| 01 | `01_excel_viewer.ipynb` | **Optional.** Sheet-by-sheet HTML preview. No downstream consumer. | `<INPUT_XLSX>` | `oa_viewer_outputs/sheet_<x>/{data,tables}/` |
| 02 | `02_ta_ph_qc.ipynb` | **Critical path start.** TA CRM correction + pH-standard correction with Dickson SOP buffer tables. | `<INPUT_XLSX>` | `oa_prelim_data__qc_outputs/sheet_<x>/data/derived.csv` |
| 03 | `03_qc_output_review.ipynb` | **Optional.** Read-only inspector for Stage 02's outputs. No downstream consumer. | Stage 02 output tree | `oa_qc_review_outputs/` |
| 04 | `04_stage1a.ipynb` | Canonical schema, alias resolution, range / presence / duplicate flags. | `<qc>/sheet_<x>/data/derived.csv` | `oa_stage1a_outputs/data/{staged.csv, analysis_ready.csv}` |
| 05 | `05_stage1b.ipynb` | **Best-source coalescing.** Builds `ta_best_umolkg`, `ph_best`, etc., with per-row source tracking. | `<stage1a>/data/staged.csv` | `oa_stage1b_outputs/data/analysis_ready_samples.csv` |
| 06 | `06_stage2.ipynb` | **Cross-row aggregation.** Duplicate detection + replicate harmonisation with GOA-ON SD thresholds. | `<stage1b>/data/analysis_ready_samples.csv` | `oa_stage2_outputs/data/enhanced.csv` |
| 07 | `07_stage3.ipynb` | **Scientific QC.** DIC species-sum check + pH best-vs-CO2SYS diagnostic. | `<stage2>/data/enhanced.csv` | `oa_stage3_outputs/data/enhanced.csv` |
| 08 | `08_stage4.ipynb` | **Verdict layer.** PASS / REVIEW / FAIL classification with reason codes. | `<stage3>/data/enhanced.csv` | `oa_stage4_outputs/data/analysis_ready.csv` |

Each notebook's own `.README.md` has the detailed design rationale,
citations, and known limitations. Read them when you want to know
*why* a stage does what it does.

---

## The nine modules at a glance

Shared logic lives in modules so it can be defined once and imported
everywhere. The original monolithic notebook redefined many of these
helpers per-stage with subtly divergent versions — the audit identified
that as the dominant reproducibility hazard (per Pimentel et al. 2019).

| Module | Provides | Imported by |
|--------|----------|-------------|
| `oa_common.py` | Generic helpers: `die`, `utc_stamp`, `write_json`, `write_text`, `ensure_dir`, `coerce_numeric`, `coerce_datetime`, `make_missingness_table`, `write_csv_and_parquet`, `md_table_from_df`, `first_existing`, `existing_columns`, `coalesce_numeric_series`, `coalesce_string_series`, `safe_str_series`, `safe_upper`, `robust_outlier_flags`, `read_excel_sheets`, ... | **All notebooks** |
| `oa_schema.py` | `DEFAULT_CONFIG` (canonical schema), `load_config` (JSON/YAML merge), `apply_canonical_schema`, `normalize_ph_scale`, `normalize_ta_units`, `normalize_carbonate_unit`, `choose_duplicate_keys`, `add_duplicate_flags`, `build_canonical_export`, ... | Stages 1A, 1B, 2, 3, 4 |
| `oa_policy.py` | `RangePolicy` dataclass (**unified** — single home for sal/ta/ph/depth/lat/lon AND temp/dic/pco2/omega), `policy_from_config`, `add_stage_range_flags` | Stages 1A, 4 |
| `oa_qc_ta_ph.py` | The QC math: TA CRM correction, pH-standard correction with TRIS / AMP / BIS Dickson SOP buffer tables, per-row status assignment, QC plot generation, markdown QC report writer | Notebook 02 only |
| `oa_inspect.py` | Read-only output-tree inspection helpers: `list_output_files`, `filter_inventory`, `preview_csv_table`, `show_image` | Notebook 03 only |
| `oa_stage1b.py` | Stage 1B's best-source coalescing: `STAGE1B_DEFAULTS`, `add_best_analysis_fields`, `classify_rows_sample`, `add_provenance_fields`, `validate_ta_units`, `analysis_ready_subset` | Notebook 05 only |
| `oa_stage2.py` | Stage 2's replicate harmonisation: `STAGE2_DEFAULTS`, `materialize_canonical_aliases`, `make_column_inventory`, `add_time_and_depth_keys`, `duplicate_check`, `replicate_harmonise`, `add_conflict_annotations`, `ensure_stage2_dirs` | Notebooks 06, 07, 08 (06 for the substantive logic; 07/08 reuse the small alias / presence / inventory helpers) |
| `oa_stage3.py` | Stage 3's carbonate-integrity checks: `STAGE3_DEFAULTS`, `CarbonateIntegrityThresholds`, `add_canonical_helper_columns`, `carbonate_integrity_checks`, `build_qc_summary` | Notebook 07 only |
| `oa_stage4.py` | Stage 4's audit + verdict: `STAGE4_DEFAULTS`, `DicSpeciesAudit`, `coerce_and_standardize`, `missing_key_rows`, `detect_duplicates`, `run_range_checks`, `dic_species_audit`, `add_readiness_status`, `reason_count_table` | Notebook 08 only |

---

## "I want to change X — which file do I edit?"

| Change | Edit |
|--------|------|
| **Default ranges** (salinity, TA, pH, temperature, DIC, pCO₂, Ω bounds) | `oa_policy.py` `RangePolicy` defaults, *or* `oa_schema.DEFAULT_CONFIG["range_policy"]`, *or* `oa_stage4.STAGE4_DEFAULTS["range_policy"]` (Stage 4 uses *wider* "physically plausible" bounds; Stages 1A/1B use *tighter* "typical seawater" bounds). For a one-off run, set `CONFIG_PATH` instead. |
| **Add a new column alias** (e.g. workbook has `Salinité` for `salinity`) | `oa_schema.DEFAULT_CONFIG["canonical_candidates"]["salinity"]` — append the new name. Every stage's alias map pulls from here. |
| **Stage 1B precedence order** (which column wins when both `ta_corrected_umolkg` and `ta_umol_kg` exist) | `oa_stage1b.STAGE1B_DEFAULTS["ta_precedence"]` (or `ph_precedence`, `pco2_precedence`, `dic_precedence`). |
| **GOA-ON SD thresholds** (replicate disagreement, default pH ± 0.02 / TA ± 10) | `oa_stage2.STAGE2_DEFAULTS["replicate_sd_thresholds"]`. Tighten to GOA-ON "climate" (~ pH ± 0.003 / TA ± 2) for cruise-grade datasets. |
| **DIC species-sum tolerance** (Stage 3 diagnostic vs Stage 4 strict gate) | `oa_stage3.STAGE3_DEFAULTS["thresholds"]["dic_abs_tol"]` (default 10) for the diagnostic; `oa_stage4.STAGE4_DEFAULTS["dic_species_audit"]["abs_tol_umolkg"]` (default 5) for the gate. |
| **pH diagnostic tolerance** (observed vs calculated) | `oa_stage3.STAGE3_DEFAULTS["thresholds"]["ph_diag_tol"]` (default 0.10; tighten to 0.02 for cruise-grade). |
| **TA CRM certified value** (when you receive a new CRM batch) | `oa_qc_ta_ph.CRM_CERTIFIED_TA` — add the new batch ID and its umol/kg value. |
| **pH-standard buffer expected values** (TRIS / AMP / BIS) | `oa_qc_ta_ph.PH_STD_TABLES` — these are from Dickson SOP and shouldn't change without a literature reason. |
| **Sheet-naming for Notebook 02** | Pass `--sheet N` to `run_pipeline.sh` (Notebook 02 reads the indicated sheet; downstream stages see only its `derived.csv`). |
| **What's in the analysis-ready output** | `oa_schema.DEFAULT_CONFIG["canonical_export_order"]` — controls Stage 1A's column ordering. |
| **PASS / REVIEW / FAIL severity tiers** | `oa_stage4.add_readiness_status` — `fail_def` and `review_def` lists encode the ladder. **Edit with care:** loosening these silently promotes rows from FAIL → REVIEW or REVIEW → PASS. |
| **Output filenames** | Each notebook's "Prepare output paths" cell. Stable names ([JWST convention](https://jwst-pipeline.readthedocs.io/): identity in folder, role in filename) — don't change them unless you also update the next stage's `INPUT_CSV` default. |
| **Re-run from a specific stage** | `./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT --start-from 06` |

---

## How to inspect a run

Every stage produces the same four kinds of output:

```
oa_<stage>_outputs/
    data/          ← the row-level CSV (+ Parquet) that the next stage reads
    tables/        ← per-cut summary tables (column inventory, presence, mismatches)
    reports/       ← report.md (human-readable, includes thresholds + flag counts)
    logs/          ← manifest.json (machine-readable provenance)
                     effective_config.json (full config that was applied)
```

When something looks wrong:

1. **Look at the manifest** of the suspect stage:
   `outputs/oa_<stage>_outputs/logs/manifest.json` — it has the input path,
   row counts at each step, flag counts, parquet status, and package
   versions. Almost every "why did this stage flag/skip/fail?" question is
   answered here.
2. **Look at the report** for context: `outputs/oa_<stage>_outputs/reports/report.md`
   has the thresholds in use and a summary of every flag class.
3. **Look at the executed notebook**: `runs/<timestamp>/<stage>.run.ipynb`
   has the full cell outputs (including any displayed dataframes) as
   they ran.
4. **Drill into the row-level data**: load the stage's `data/<role>.csv`
   into pandas / a notebook and filter on the flag columns.

For Stage 4 specifically — the final deliverable — the most useful entry
points are:

- `outputs/oa_stage4_outputs/tables/range_flags_long.csv` — one row per
  range violation, with the offending value, variable, and row IDs.
- `outputs/oa_stage4_outputs/tables/dic_species_audit.csv` — every row's
  computed `DIC - sum(species)` residual, the tolerance used, and the
  three audit flags.
- `outputs/oa_stage4_outputs/logs/manifest.json` — `status_PASS`,
  `status_REVIEW`, `status_FAIL` counts plus a histogram of reason codes.

---

## Two ways to run

### From the command line (recommended for full runs)

```bash
./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT [options]
```

The runner papermills each notebook in turn, wiring each stage's input
to the previous stage's output. See `run_pipeline.sh --help` for all
options (sheet number, optional stages, partial re-runs, config dir,
dry-run).

### From Jupyter (for interactive editing)

Open any notebook in Jupyter Lab / VS Code, edit the **parameters cell**
(it's tagged `parameters` — the first code cell with paths and flags),
then `Kernel → Restart & Run All`. Each notebook has sensible defaults
that match the canonical output paths, so if you've run an earlier stage
its output is where the next stage expects to find it.

The parameters cell is also what Papermill overrides — same notebook,
two driving styles.

---

## What this pipeline does NOT do

A few intentional non-features, called out so they don't surprise you:

- **It does not delete rows.** Every stage is additive (new columns,
  flags, summaries) or aggregating (replicate means in a *separate*
  table). The full row-level data with every flag preserved arrives in
  `oa_stage4_outputs/data/analysis_ready.csv` and the analyst filters
  there.
- **It does not rebuild best fields after Stage 1B.** `ta_best_umolkg`,
  `ph_best`, `ph_co2sys`, `pco2_best_uatm`, `dic_best_umol_kg` are
  finalised by Stage 1B and carried through unchanged. Stages 2, 3, 4
  audit them; they don't recompute them.
- **It does not call PyCO2SYS.** The carbonate-system *calculated*
  values (`ph_co2sys`, `omega_aragonite_calc`, etc.) are expected to be
  already present in the input workbook (typically produced by an
  external CO2SYS run). The pipeline's job is to validate them, not
  produce them.
- **It does not pick which CO2SYS solver / constants to use.** That
  decision is recorded in `carbonate_solver` and `carbon_input_pair_used`
  columns and surfaced by Stage 4 as `flag_solver_unknown` /
  `flag_carbon_input_pair_unknown` if absent. The choice is the
  analyst's, not the pipeline's.

## Testing

A small pytest suite under `tests/` covers the load-bearing functions
plus the full pipeline end-to-end on the bundled example dataset.

```bash
pip install -e ".[dev]"
pytest                                # 57 tests, ~15s
pytest tests/test_coalesce.py -v      # just the unit tests on one file
pytest tests/test_pipeline_e2e.py     # just the integration test
```

| File | What it covers |
|------|----------------|
| `tests/test_coalesce.py` | Stage 1B's best-source picker (`coalesce_numeric_series`, `coalesce_string_series`) including the per-row source-tracking, NA handling, and string-vs-numeric coercion. |
| `tests/test_schema.py` | Canonical alias resolution, the duplicate-key chooser (with a regression test for the all-NA-tuples bug we caught), and the pH-scale / unit normalisers (including a regression for the silent UPPERCASE-vs-lowercase divergence between Stage 3 and Stages 1A/1B). |
| `tests/test_readiness.py` | Stage 4's PASS/REVIEW/FAIL classifier — every reason code, the FAIL-beats-REVIEW precedence, and the `range_flag_count`-absent regression. |
| `tests/test_pipeline_e2e.py` | Runs the full eight-notebook chain on `examples/example_data.xlsx` via papermill and asserts the verdict distribution, the four broken rows produce their expected reason codes, and every stage writes its manifest. |

The end-to-end test is skipped if `papermill` is not installed. The unit
tests run without it.

---

### Carbonate-system science

- **Dickson, A. G., Sabine, C. L., Christian, J. R. (Eds.) (2007),
  *Guide to Best Practices for Ocean CO₂ Measurements***. PICES Special
  Publication 3. The source of the TRIS / AMP / BIS buffer-value tables
  and the CRM correction protocol in Notebook 02.
- **DOE (1994), *Handbook of Methods for the Analysis of the Various
  Parameters of the Carbon Dioxide System in Sea Water***, SOP 23. The
  "use the SD of replicate measurements as the precision estimate"
  approach used by Stage 2.
- **Newton, J. A. et al. (2015), *GOA-ON Requirements and Governance
  Plan***. Source of the "weather" (pH ± 0.02 / TA ± 10 µmol/kg) and
  "climate" (~ pH ± 0.003 / TA ± 2 µmol/kg) precision objectives that
  underpin Stage 2's SD thresholds and Stage 3/4's tolerances.
- **Millero, F. J. (1993)**, *Mar. Chem.* **44**, 269–280. The
  internal-consistency framework Stage 3 implements row-by-row.
- **OCADS NDP-090 — Total Alkalinity Measurements**. Real-world example
  of `max(abs_tol, rel_tol * |DIC|)` as the integrity threshold.
- **Iglewicz, B., Hoaglin, D. C. (1993)**. The MAD-based robust-outlier
  rule used by Stage 2's `replicate_outlier_flags` and Stage 3's robust
  DIC and pH variants.

### Data engineering

- **Apache Avro Specification — *Schema Resolution and Aliases***. The
  reason `canonical_candidates` is modelled as `name -> [aliases]`.
- **PySpark `coalesce` function documentation**. The
  COALESCE-with-row-level-provenance pattern Stage 1B implements via
  `coalesce_numeric_series` / `coalesce_string_series`.
- **Coalesce.io, *What is Data Lineage?***. Motivates the per-row
  `*_source` columns that record which column won each best-source pick.
- **JWST input/output conventions**. Source of "use `output_dir` to
  place results in a different directory instead of using `output_file`
  to rename" — why output filenames are short and `OUT_DIR` is flat.
- **Palantir Foundry, *Building pipelines***. Descriptive names,
  distinctive part first.
- **NDepend, *Quality Gates*** and **UN/ABS *Data Quality Manual
  Part B***. The PASS / WARN / FAIL three-tier verdict pattern Stage 4
  implements (with REVIEW substituted for WARN).

### Software engineering

- **Rule, A. et al. (2019)**, *Ten Simple Rules for Reproducible
  Research in Jupyter Notebooks*, arXiv:1810.08055. The structural
  rules followed by the refactor: modularize (R4), parameterize (R5),
  record provenance (R8).
- **Pimentel, J. F. et al. (2019)**, *A Large-Scale Study about Quality
  and Reproducibility of Jupyter Notebooks*. The empirical evidence
  that per-notebook helper redefinition is the dominant reproducibility
  hazard.
- **Papermill** (nteract). The `parameters`-tagged cell convention and
  the runner script that drives the pipeline.
- **Ian Rose, *Working with Jupyter notebooks***. Restart-and-run-all
  as the unit of reproducibility.
- **Russ Poldrack, *Better Code, Better Science***. Same.

---

## Audit history

The original monolithic notebook had eight major issues that this
refactor addresses structurally. They are described in the per-stage
READMEs (each has a §6 "What changed vs. the original" table). In
summary:

1. **Six input-path bugs** across Stages 1A / 1B / 2 / 3 / 4 — each
   stage's hardcoded `input_csv` pointed at a filename the previous
   stage never produced.
2. **`RangePolicy` redefined three times** with *different fields* in
   Stages 1A, 1B, and 4 — a silent-overwrite bug when run in one
   kernel. Fixed by unifying in `oa_policy.py`.
3. **`write_report` defined three times** with different signatures in
   Stages 2, 3, 4 — name collision. Fixed by inlining the per-stage
   markdown in each notebook.
4. **Filename-stem accumulation**:
   `oa_prelim_data__0__derived__stage1a_staged__analysis_ready_samples__stage2_enhanced__stage3_enhanced__analysis_ready_stage4.csv`
   over six stages. Fixed by short role-based filenames + identity-in-folder.
5. **The duplicate-key NA bug in Stage 1A**: `choose_duplicate_keys`
   originally checked only "column exists in df", but
   `apply_canonical_schema` creates every canonical column (NA-filled
   if no alias resolved), so the existence test was trivially true and
   every row got flagged. Fixed: require "column exists AND has at
   least one non-NA value".
6. **The `fix_lattitude` flag** in Stage 1A — redundant with the
   alias list and ordered wrong. Removed.
7. **Case-divergence in pH scale strings**: Stage 3's
   `normalize_scale_text` produced uppercase, Stages 1A/1B's
   `normalize_ph_scale` produced lowercase. If joined, the values
   wouldn't match. Fixed: one normaliser, lowercase, in `oa_schema.py`.
8. **`range_flag_count` AttributeError in Stage 4**: the original's
   `pd.to_numeric(df.get("range_flag_count"), ...).fillna(0)` crashed
   when the column was absent. Discovered during smoke-test; fixed
   with a guarded conditional.

Plus dozens of duplicated helpers (`die`, `utc_stamp`, `coerce_numeric`,
`robust_outlier_flags`, ...) — these are now all in `oa_common.py`,
defined once, imported everywhere.

---

## Status

**57 tests pass** in ~15 seconds: 47 unit tests on the load-bearing
functions (`coalesce_numeric_series`, `apply_canonical_schema`,
`choose_duplicate_keys`, `add_readiness_status`, the normalisers) and
10 integration tests that drive the full eight-notebook chain on the
bundled example dataset and assert the verdict distribution.

The example dataset has four deliberately-broken rows with known
expected verdicts:

| Row | Injected issue | Expected reason code |
|------|----------------|---------------------|
| S005 | salinity = 50 (above sal_max = 42) | `range_flag` |
| S007 | dropped `sample_id` | `missing_key` |
| S010 | DIC species sum off by 200 µmol/kg | `strict_dic_species_fail` |
| S015 | negative HCO₃ (physically impossible) | `strict_dic_species_fail` |

The integration test asserts each of these four rows produces its
expected reason code and is not classified as PASS.

For a real dataset, the first thing to check is the per-stage `manifest.json`
files — they're machine-readable and record everything that was applied.
