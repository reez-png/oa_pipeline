# oa_pipeline

Eight notebook preprocessing pipeline for ocean acidification carbonate chemistry data.

The pipeline reads an Excel workbook containing TA, pH, temperature, salinity, DIC, and related carbonate chemistry measurements. It applies CRM corrected TA QC, pH standard correction, canonical column harmonisation, best source analysis field selection, duplicate and replicate checks, carbonate system internal consistency diagnostics, and a final per row audit verdict.

Final output:

```text
PASS / REVIEW / FAIL per row
analysis_ready.csv
```

## Pipeline flow

```text
oa_prelim_data.xlsx
        │
        │ Notebook 01 optional: Excel sheet preview
        ▼
   02_ta_ph_qc
        │
        │ derived.csv
        │ CRM TA correction and pH standard correction
        ▼
   04_stage1a
        │
        │ staged.csv
        │ canonical schema and alias resolution
        ▼
   05_stage1b
        │
        │ analysis_ready_samples.csv
        │ best source fields such as ta_best_umolkg and ph_best
        ▼
   06_stage2
        │
        │ enhanced.csv
        │ duplicate checks and replicate harmonisation
        ▼
   07_stage3
        │
        │ enhanced.csv
        │ DIC species sum and pH diagnostic checks
        ▼
   08_stage4
        │
        │ analysis_ready.csv
        │ final PASS / REVIEW / FAIL verdicts
        ▼
final analysis ready dataset
```

Notebook 03 is optional and provides a read only inspection layer for Notebook 02 outputs.

---

## Quick start

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[all]"

python examples\make_example_data.py
bash .\run_pipeline.sh examples\example_data.xlsx outputs\test_run
python -m pytest -q
```

### Windows: use Git Bash, not WSL

On Windows the runner is launched through `bash`, and **which `bash` matters**.
The desktop launcher and the recommended manual workflow both expect Git Bash
(`C:\Program Files\Git\bin\bash.exe`), not the WSL stub at
`C:\WINDOWS\system32\bash.exe`. The WSL bash causes three failures:

- it strips backslashes from paths during tokenisation, so
  `C:\Users\...\file.xlsx` arrives as `C:Users...file.xlsx` ("file not found");
- it mounts the C: drive at `/mnt/c`, not `/c`;
- it runs a Linux Python that cannot use your Windows `.venv`, so Papermill
  runs in the wrong interpreter.

Two practical rules that avoid all of this:

- **Always pass forward-slash paths**, e.g.
  `bash ./run_pipeline.sh C:/Users/you/.../data.xlsx C:/Users/you/.../out`.
  Forward-slash drive paths (`C:/Users/...`) are understood by both bash and
  Windows Python; backslash paths are not. From PowerShell, also write the
  script as `./run_pipeline.sh`, not `.\run_pipeline.sh` (bash eats the
  backslash).
- The desktop launcher auto-detects Git Bash and prefers it over the WSL
  stub, and converts all paths to the forward-slash form for you. If the
  "Environment looks good" panel shows `system32\bash.EXE` instead of
  `Git\bin\bash.exe`, install Git for Windows.

---

### Git Bash, macOS, or Linux

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[all]"

python examples/make_example_data.py
./run_pipeline.sh examples/example_data.xlsx outputs/test_run
python -m pytest -q
```

The final deliverable from the example run is:

```text
outputs/test_run/oa_stage4_outputs/data/analysis_ready.csv
```

The bundled example workbook has one sheet named `oa_data`, so Notebook 02 writes:

```text
outputs/test_run/oa_prelim_data__qc_outputs/sheet_oa_data/data/derived.csv
```

For other workbooks, Notebook 02 writes one folder per processed sheet using this pattern:

```text
outputs/<run_name>/oa_prelim_data__qc_outputs/sheet_<safe_sheet_name>/data/derived.csv
```

---

## Recommended on disk layout

This project uses a standard `src/` package layout. The notebooks are orchestration layers. Reusable logic lives in the installable `oa_pipeline` package under `src/oa_pipeline/`.

After installation with:

```bash
python -m pip install -e ".[all]"
```

notebooks and tests import modules like this:

```python
from oa_pipeline.common import die
from oa_pipeline.stage4 import add_readiness_status
```

Recommended project structure:

```text
oa_pipeline/
│
├── README.md
├── CONTRIBUTING.md
├── DATA_DICTIONARY.md        # input contract: columns, values, units, tags
├── APP_README.md             # how to use the desktop launcher
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── run_pipeline.sh
├── oa_pipeline_app.py        # desktop GUI launcher (Tkinter)
├── oa_pipeline_app_core.py   # GUI-independent launcher logic
├── stamp_carbonate_provenance.py  # add CO2SYS provenance columns to a workbook
├── .gitignore
│
├── configs/
│   ├── crm_certified_values.yaml
│   ├── cruise_grade_thresholds.yaml
│   ├── regional.yaml
│   ├── 02_ta_ph_qc.yaml      # optional per-stage override (e.g. PH_COL, pH-std QC)
│   └── 07_stage3.yaml        # optional per-stage override (e.g. pH temp harmonization)
│
├── data/
│   ├── raw/
│   ├── interim/
│   ├── processed/
│   └── external/
│
├── examples/
│   ├── make_example_data.py
│   ├── example_data.xlsx
│   └── quickstart.ipynb
│
├── notebooks/
│   ├── 01_excel_viewer.ipynb
│   ├── 02_ta_ph_qc.ipynb
│   ├── 03_qc_output_review.ipynb
│   ├── 04_stage1a.ipynb
│   ├── 05_stage1b.ipynb
│   ├── 06_stage2.ipynb
│   ├── 07_stage3.ipynb
│   └── 08_stage4.ipynb
│
├── src/
│   └── oa_pipeline/
│       ├── __init__.py
│       ├── common.py
│       ├── inspect.py
│       ├── policy.py
│       ├── qc_ta_ph.py
│       ├── schema.py
│       ├── stage1b.py
│       ├── stage2.py
│       ├── stage3.py
│       └── stage4.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_app_core.py
│   ├── test_coalesce.py
│   ├── test_common.py
│   ├── test_inspect.py
│   ├── test_pipeline_e2e.py
│   ├── test_policy.py
│   ├── test_qc_ta_ph.py
│   ├── test_readiness.py
│   ├── test_schema.py
│   ├── test_stage1b.py
│   ├── test_stage2.py
│   ├── test_stage3.py
│   └── test_stage4.py
│
├── outputs/
└── runs/
```

### Why this layout

The `src/` layout makes the pipeline behave like a real Python package. It prevents accidental imports from the current working directory and makes notebooks, tests, and command line runs use the same package code after installation.

The `notebooks/` folder contains the eight Papermill driven workflow stages.

The `examples/` folder contains the deterministic synthetic workbook generator and the bundled example workbook used by the end to end test.

The `outputs/` and `runs/` folders are reproducible artifacts. They should be ignored by Git because they can be recreated from the input workbook, code, and configuration.

---

## Note for OneDrive users

The input workbook can live in OneDrive, but the project folder should ideally live outside OneDrive, for example:

```text
C:\Users\<you>\projects\oa_pipeline
```

The pipeline writes many small files into `outputs/` and `runs/`. OneDrive may slow down, lock files, or sync partial outputs while the pipeline is still running.

---

## The eight notebooks at a glance

Each notebook is a Papermill driven stage. The runner wires the output of one stage into the input of the next stage.

| # | Notebook | Role | Reads | Writes |
|---:|---|---|---|---|
| 01 | `notebooks/01_excel_viewer.ipynb` | Optional Excel sheet preview | Input workbook | `oa_viewer_outputs/` |
| 02 | `notebooks/02_ta_ph_qc.ipynb` | TA CRM correction and pH standard correction | Input workbook | `oa_prelim_data__qc_outputs/sheet_<safe_sheet_name>/data/derived.csv` |
| 03 | `notebooks/03_qc_output_review.ipynb` | Optional read only review of Notebook 02 outputs | Notebook 02 output tree | Review tables and previews |
| 04 | `notebooks/04_stage1a.ipynb` | Canonical schema, alias resolution, range and presence flags | Notebook 02 `derived.csv` | `oa_stage1a_outputs/data/staged.csv` and `analysis_ready.csv` |
| 05 | `notebooks/05_stage1b.ipynb` | Best source coalescing | Stage 1A `staged.csv` | `oa_stage1b_outputs/data/analysis_ready_samples.csv` |
| 06 | `notebooks/06_stage2.ipynb` | Duplicate checks and replicate harmonisation | Stage 1B `analysis_ready_samples.csv` | `oa_stage2_outputs/data/enhanced.csv` |
| 07 | `notebooks/07_stage3.ipynb` | DIC species sum and pH diagnostic checks | Stage 2 `enhanced.csv` | `oa_stage3_outputs/data/enhanced.csv` |
| 08 | `notebooks/08_stage4.ipynb` | Final audit verdict layer | Stage 3 `enhanced.csv` | `oa_stage4_outputs/data/analysis_ready.csv` |

There is currently no separate `oa_pipeline.stage1a` module. Notebook 04 uses shared `oa_pipeline.schema`, `oa_pipeline.policy`, and `oa_pipeline.common` utilities directly because Stage 1A is mostly canonicalisation, range flagging, and export orchestration.

---

## Package modules at a glance

Reusable logic lives in `src/oa_pipeline/` and is imported as `oa_pipeline.<module>`.

| Module | Provides | Imported by |
|---|---|---|
| `oa_pipeline.common` | Generic helpers for paths, JSON and CSV writing, timestamps, coercion, Excel reading, missingness tables, coalescing helpers, and robust outlier flags. | All notebooks |
| `oa_pipeline.schema` | Canonical schema, alias resolution, config loading, unit and pH scale normalisation, duplicate key helpers, and canonical export ordering. | Stages 1A to 4 |
| `oa_pipeline.policy` | `RangePolicy`, range configuration, and stage range flag helpers. | Stages 1A, 1B, and 4 |
| `oa_pipeline.qc_ta_ph` | TA CRM correction, pH standard correction, QC plots, and QC markdown reports. | Notebook 02 |
| `oa_pipeline.inspect` | Read only output tree inspection helpers. | Notebook 03 |
| `oa_pipeline.stage1b` | Best source coalescing and sample ready filtering. | Notebook 05 |
| `oa_pipeline.stage2` | Duplicate detection, replicate harmonisation, replicate SD checks, and conflict annotations. | Notebook 06, reused lightly by 07 and 08 |
| `oa_pipeline.stage3` | Carbonate integrity checks: DIC species sum, pH diagnostic, scale flags, unit flags, and provenance flags. | Notebook 07 |
| `oa_pipeline.stage4` | Final audit, range checks, strict DIC audit, PASS / REVIEW / FAIL verdicts, and reason code tables. | Notebook 08 |

---

## Configuration

`run_pipeline.sh --config-dir configs` looks for optional per stage configuration files with these names:

```text
configs/02_ta_ph_qc.yaml
configs/04_stage1a.yaml
configs/05_stage1b.yaml
configs/06_stage2.yaml
configs/07_stage3.yaml
configs/08_stage4.yaml
```

The same stage files can also use `.yml` or `.json` extensions.

If a per stage file is absent, that stage uses built in defaults and the runner prints a warning.

The top-level key inside a per-stage file depends on what the stage exposes.
Stages whose notebook defines parameter globals (e.g. Stage 02) read overrides
under a `parameters:` key; stages with a thresholds block (e.g. Stage 03) read
them under `thresholds:`. Two worked examples:

```yaml
# configs/02_ta_ph_qc.yaml  — remap columns and configure pH-standard QC
parameters:
  PH_COL: ph_observed
  PH_TEMP_COL: temp_lab
  CRM_OR_SAMPLE_COL: sample_type
  ALLOW_CRM_FLAG_COL: true
  PHSTD_QC: true
  PH_BUFFER: tris
  PHSTD_TAG_PREFIX: tris
```

```yaml
# configs/07_stage3.yaml  — harmonize pH temperature in the diagnostic
thresholds:
  ph_diag_harmonize_temperature: true
  ph_diag_temp_sensitivity: -0.0165
```

Only keys that already exist as stage globals/thresholds are applied; unknown
keys are ignored with a warning.

Broader reference files such as these can be used as templates or merged manually into per stage config files:

```text
configs/cruise_grade_thresholds.yaml
configs/regional.yaml
```

---

## Preparing your input workbook

Before running on real data, read [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md).
It documents the full input contract directly from the code: accepted
column-header spellings (the alias map), accepted values for pH scales and
units, expected data types, plausible-range bounds, and the required
columns.

The most common and most costly mistake it prevents: **CRM and pH-standard
rows are detected by their `sample_tag` prefix (`RM...`, `tris...`), not
primarily by the `sample_type` column.** A row labelled `crm` in the
`sample_type` column but named `Batch213_1` is treated as an ordinary
sample by default, which silently corrupts the TA correction and the QC
plots. Tag CRM rows `RM<batch>_<n>` (e.g. `RM213_1`) and standards
`tris_*`.

## Three ways to run

### Full command line run

```bash
./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT
```

Useful options:

```bash
./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT --dry-run
./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT --sheet 0
./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT --config-dir configs
./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT --include-viewer --include-review
./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT --start-from 06
```

Partial reruns require the earlier stage outputs to already exist inside the same `OUTPUT_ROOT`.

### Desktop app (no terminal)

For users who would rather not use a shell, a point-and-click launcher is
included. From the project root:

```bash
python oa_pipeline_app.py
```

Pick the input workbook, pick an output folder, click **Run pipeline**, and
watch progress; it prints the final PASS / REVIEW / FAIL counts when done.
There is also an optional "Use config folder" control: tick it to pass a
`--config-dir` (it defaults to the project's `configs/` folder) so per-stage
config files are applied. It runs the same `run_pipeline.sh`, so results are
identical. The launcher window needs only standard-library Tkinter (bundled
with the python.org installer). See [`APP_README.md`](APP_README.md) for setup
details.

### Interactive notebook run

Open a notebook in Jupyter Lab or VS Code, edit its `parameters` cell, then use `Restart Kernel and Run All`.

The notebooks are designed so the same file can be run interactively or driven by Papermill.

---

## How to inspect a run

Every major stage writes the same four kinds of output:

```text
oa_<stage>_outputs/
    data/       row level CSV and optional Parquet files
    tables/     audit tables and summary tables
    reports/    report.md
    logs/       manifest.json and effective_config.json
```

When something looks wrong, check these in order:

1. `logs/manifest.json`
2. `reports/report.md`
3. `runs/<timestamp>/<stage>.run.ipynb`
4. the row level CSV in `data/`

For Stage 4, the most useful files are:

```text
outputs/<run>/oa_stage4_outputs/data/analysis_ready.csv
outputs/<run>/oa_stage4_outputs/tables/range_flags_long.csv
outputs/<run>/oa_stage4_outputs/tables/dic_species_audit.csv
outputs/<run>/oa_stage4_outputs/logs/manifest.json
```

---

## Interpreting PASS / REVIEW / FAIL

REVIEW is informational, not a defect. It means a check could not be fully
verified or a soft threshold was crossed, and the analyst should look. FAIL is
reserved for severe issues (missing keys, missing required analysis fields,
strict DIC closure failure or unit mismatch, and unknown carbonate solver /
input pair). The `analysis_audit_reason_codes` column lists why each row landed
where it did; a frequency count of those codes is the fastest way to read a run.

Two common, benign REVIEW patterns worth recognising:

**Measured vs calculated pH differ by a roughly constant offset.** If directly
measured pH (reported at laboratory temperature) is compared with CO2SYS-derived
pH (reported at in situ temperature), the two differ by the temperature effect
on pH (~ -0.016 pH units per degree Celsius). This is not a data error: the two
pH values describe the same water at different reference temperatures. A quick
check is to correlate the pH difference against the lab-minus-in-situ
temperature difference — a strong negative correlation with a slope near
-0.016/degC confirms it. Use the in situ-referenced calculated parameters
(Omega_ar, Omega_ca, pCO2) for ecological analysis, since those represent the
conditions organisms experience. Confirm the CO2SYS output temperature (`Tout`)
was set to in situ when generating saturation states.

To stop this temperature offset from generating spurious pH-diagnostic flags,
Stage 3 has an opt-in temperature harmonization: set
`ph_diag_harmonize_temperature: true` (under `thresholds`) in
`configs/07_stage3.yaml`. When enabled, Stage 3 brings the measured pH to the
in situ reference using a linear pH temperature-sensitivity approximation
(`ph_diag_temp_sensitivity`, default -0.0165 /degC) before computing the
diagnostic difference, so the check tests genuine agreement rather than the
temperature reference difference. It is off by default (preserving prior
behaviour), is a QC screen only (the adjusted value is never written back as a
reported pH), and records both the raw difference (`ph_best_minus_ph_co2sys`)
and the harmonized one (`ph_best_minus_ph_co2sys_temp_harmonized`), plus
`ph_diag_harmonize_temperature_applied` to mark which rows used it.

**`strict_dic_values_missing` on rows that have DIC.** The strict DIC
species-closure audit requires all four of DIC, CO2aq, HCO3, and CO3 to be
present on a row. If any one is absent the row is flagged as not-checkable
(REVIEW), even though the others are present. This does not indicate bad data;
it means the closure check could not run for that row.

The replicate flags (`replicate_conflict_carried`, `stage3_issue` on `(R)`
rows) are genuine replicate-agreement signals and are worth inspecting on their
merits.

---

### It does not delete rows

Every stage is additive. It adds columns, flags, summaries, and reports. The analyst decides whether to filter PASS only, include REVIEW rows, or inspect FAIL rows.

### It does not rebuild best fields after Stage 1B

Fields such as `ta_best_umolkg`, `ph_best`, `ph_co2sys`, `pco2_best_uatm`, and `dic_best_umol_kg` are finalised by Stage 1B and carried through later stages. Stages 2, 3, and 4 audit them, but do not recompute them.

### It does not run PyCO2SYS internally

Calculated carbonate fields such as `ph_co2sys`, `pco2_best_uatm`, `dic_best_umol_kg`, and carbonate species columns are expected to already be present in the input workbook or generated upstream.

The pipeline audits those fields and requires provenance columns such as:

```text
carbonate_solver
carbon_input_pair_used
```

when calculated carbonate outputs are present.

### It does not choose carbonate constants for the analyst

Solver choice and constants should be documented upstream. The pipeline records and audits that provenance, but does not decide it.

#### Stamping provenance for externally computed chemistry (often required)

If your workbook's carbonate chemistry was computed in an external tool (e.g.
the CO2SYS Excel workbook) and does not carry the provenance columns the audit
expects, Stage 4 marks **every** sample row FAIL with `unknown_solver` and
`unknown_input_pair` (both are FAIL-severity). In that situation stamping the
provenance is **a required step to get a usable run**, not an optional polish:
without it the final table is entirely FAIL. The audit only checks that these
fields are **non-empty** — it does not validate against a fixed vocabulary — so
recording accurate values clears the flags and documents your method.

The helper script `stamp_carbonate_provenance.py` writes a NEW workbook
(`<name>_provenance.xlsx`) next to the original, with the provenance columns
filled on sample rows (std/crm reference rows are left blank):

```bash
python stamp_carbonate_provenance.py path/to/oa_data_apr.xlsx
# -> writes path/to/oa_data_apr_provenance.xlsx
# then run the pipeline against the _provenance.xlsx file
```

It stamps: `carbonate_solver`, `carbon_input_pair_used`, `dic_unit_normalized`,
the three species unit columns (`co2aq_/hco3_/co3_unit_normalized`),
`carbonate_constants`, `carbonate_ph_scale`, and `carbonate_output_temperature`.
**Edit the `PROVENANCE` dict at the top of the script to match how your
chemistry was actually computed before running it** — stamping a false
provenance is worse than none.

Two important notes:

- The script reads the workbook with pandas and writes static values. This is
  deliberate: a plain openpyxl round-trip would blank any **formula-defined**
  column (e.g. a `dic` column carried as an Excel formula), because formulas
  have no cached value to preserve. Reading the computed values first avoids
  that. The script prints a `carried dic/ta/ph_observed` line on each run so
  you can confirm no value column was lost.
- Feed the resulting `_provenance.xlsx` to the pipeline (update the workbook
  path in the launcher or the command line). The original is left untouched.

After stamping, re-run; the `unknown_solver` / `unknown_input_pair` FAILs clear
and rows move to PASS or REVIEW.

---

## Testing

Run the test suite using the same Python interpreter where the package was installed:

```bash
python -m pytest -q
```

The suite includes unit tests for schema resolution, coalescing, readiness classification, and a full Papermill end to end test over the bundled example workbook.

At the latest checkpoint, after the data-integrity audit and the addition
of the input data dictionary and the desktop launcher, the test suite
reported:

```text
221 passed
```

This includes the schema/coalesce/readiness/QC unit tests, the Papermill
end-to-end tests over the bundled example workbook, and 14 tests for the
desktop launcher logic (`tests/test_app_core.py`) covering Windows path
conversion, Git Bash preference, and the optional `--config-dir` wiring.

Use these targeted commands while debugging:

```bash
python -m pytest tests/test_coalesce.py -q
python -m pytest tests/test_schema.py -q
python -m pytest tests/test_readiness.py -q
python -m pytest tests/test_pipeline_e2e.py -q
```

The end to end test is skipped if Papermill is not installed. The unit tests do not require Papermill.

---

## Bundled example dataset

The bundled example dataset is generated by:

```bash
python examples/make_example_data.py
```

It creates:

```text
examples/example_data.xlsx
```

with 27 rows:

```text
20 sample rows
4 CRM rows
3 TRIS pH standard rows
```

The sample sheet is named:

```text
oa_data
```

The example has four deliberately injected sample row issues with known expected Stage 4 outcomes:

| Row | Injected issue | Expected status | Expected reason code |
|---|---|---|---|
| S005 | salinity = 50, above `sal_max = 42` | REVIEW | `range_flag` |
| S007 | missing `sample_id` | FAIL | `missing_key` |
| S010 | DIC species sum broken by 200 µmol/kg | FAIL | `strict_dic_species_fail` |
| S015 | negative HCO3, physically impossible | FAIL | `strict_dic_species_fail` |

The integration test asserts that these rows produce the expected status and reason code.

---

## Common edit targets

| Change | Edit |
|---|---|
| Add a workbook column alias | `oa_pipeline.schema.DEFAULT_CONFIG["canonical_candidates"]` |
| Change Stage 1B best source precedence | `oa_pipeline.stage1b.STAGE1B_DEFAULTS` |
| Change replicate SD thresholds | `oa_pipeline.stage2.STAGE2_DEFAULTS` |
| Change Stage 3 DIC or pH diagnostic tolerance | `oa_pipeline.stage3.STAGE3_DEFAULTS["thresholds"]` |
| Change Stage 4 strict DIC audit tolerance | `oa_pipeline.stage4.STAGE4_DEFAULTS["dic_species_audit"]` |
| Change Stage 4 PASS / REVIEW / FAIL severity | `oa_pipeline.stage4.add_readiness_status` |
| Add a new CRM certified TA value | `configs/crm_certified_values.yaml` (authoritative, NOAA-sourced). The in-code fallback in `oa_pipeline.qc_ta_ph` is corrected but secondary. |
| Change output wiring | `run_pipeline.sh` and the relevant notebook parameters cell |

---

## Status

The current package layout is:

```text
src/oa_pipeline/
notebooks/
tests/
examples/
configs/
outputs/
runs/
```

The pipeline has a deterministic example workbook, unit tests for load bearing functions, and an end to end Papermill test that verifies the full notebook chain.

For a real dataset, the first files to inspect are the per stage `manifest.json` files. They record the input path, row counts, flag counts, config source, package versions, and output paths used for the run.
