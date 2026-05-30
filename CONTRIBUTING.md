# Contributing to oa_pipeline

Thank you for your interest in contributing to `oa_pipeline`.

This project is research software for ocean acidification and carbonate chemistry data processing. The codebase is intentionally small, modular, and audit friendly. Most contributors should be able to understand the full workflow by reading the top level `README.md`, the eight notebooks, and the package modules under `src/oa_pipeline/`.

The most important rule is simple: changes should preserve scientific traceability. If a change affects thresholds, flags, provenance, row classification, or output handoffs, update the documentation and add or update tests.

---

## Quick orientation

Start with these files and folders:

| Location | Purpose |
|---|---|
| `README.md` | Main project overview, folder layout, pipeline flow, quick start, and common edit targets. |
| `notebooks/` | The eight Papermill driven notebook stages. |
| `src/oa_pipeline/` | Reusable package code imported by notebooks and tests. |
| `tests/` | Unit tests and the Papermill end to end test. |
| `examples/make_example_data.py` | Deterministic synthetic example workbook generator. |
| `examples/example_data.xlsx` | Bundled synthetic workbook used by the quickstart and E2E test. |
| `run_pipeline.sh` | Command line runner that executes the notebook chain. |
| `oa_pipeline_app.py` / `oa_pipeline_app_core.py` | Desktop GUI launcher and its GUI-independent logic. |
| `DATA_DICTIONARY.md` | Input contract: accepted column names, values, units, dtypes, row-tagging rules. Regenerate from code if the schema changes. |
| `APP_README.md` | How to use and set up the desktop launcher. |
| `configs/` | Optional YAML, YML, or JSON configuration overrides. |
| `outputs/` | Reproducible per stage outputs. This folder should not be committed. |
| `runs/` | Papermill executed notebook copies. This folder should not be committed. |

---

## Setup for development

### Git Bash, macOS, or Linux

```bash
git clone <wherever this lives>
cd oa_pipeline

python -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[all]"

python examples/make_example_data.py --out examples/example_data.xlsx

python -m pytest -q
python -m pytest tests/test_pipeline_e2e.py -q

./run_pipeline.sh examples/example_data.xlsx outputs/test_run
```

### Windows PowerShell

```powershell
git clone <wherever this lives>
cd oa_pipeline

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[all]"

python examples\make_example_data.py --out examples\example_data.xlsx

python -m pytest -q
python -m pytest tests\test_pipeline_e2e.py -q

bash .\run_pipeline.sh examples\example_data.xlsx outputs\test_run
```

The bundled `examples/example_data.xlsx` workbook is deterministic. It contains synthetic sample rows, CRM rows, and pH standard rows that exercise the full pipeline.

---

## Current package convention

This project uses a standard `src/` package layout.

Reusable code lives here:

```text
src/oa_pipeline/
```

Notebook imports should use the installed package namespace, for example:

```python
from oa_pipeline.common import die
from oa_pipeline.stage4 import add_readiness_status
```

Do not add new top level `oa_*.py` modules. New reusable code should go into the relevant module under `src/oa_pipeline/`.

There is currently no `oa_pipeline.stage1a` module. Notebook 04 uses shared utilities from `oa_pipeline.common`, `oa_pipeline.schema`, and `oa_pipeline.policy` because Stage 1A is mostly canonicalisation, presence and range flagging, and export orchestration. Add a dedicated `stage1a.py` only if substantial reusable Stage 1A logic appears.

---

## Notebook convention

The notebooks live in:

```text
notebooks/
```

Use these paths when referring to them:

```text
notebooks/01_excel_viewer.ipynb
notebooks/02_ta_ph_qc.ipynb
notebooks/03_qc_output_review.ipynb
notebooks/04_stage1a.ipynb
notebooks/05_stage1b.ipynb
notebooks/06_stage2.ipynb
notebooks/07_stage3.ipynb
notebooks/08_stage4.ipynb
```

Each notebook should have exactly one tagged `parameters` cell. The same notebook must work in two modes:

1. interactive execution from Jupyter or VS Code
2. Papermill execution through `run_pipeline.sh`

Notebook code should orchestrate the workflow. Reusable logic should live in `src/oa_pipeline/`.

---

## Where to add things

| Adding or changing... | Goes in... |
|---|---|
| A new canonical column alias | `oa_pipeline.schema.DEFAULT_CONFIG["canonical_candidates"]` |
| A new range threshold | `oa_pipeline.policy.RangePolicy` and/or a stage specific `STAGE*_DEFAULTS["range_policy"]` |
| A new Stage 1B precedence rule | `oa_pipeline.stage1b.STAGE1B_DEFAULTS` |
| A new replicate SD threshold | `oa_pipeline.stage2.STAGE2_DEFAULTS["replicate_sd_thresholds"]` |
| A new carbonate integrity check | `oa_pipeline.stage3.carbonate_integrity_checks` or a helper in `oa_pipeline.stage3` |
| A new Stage 4 audit reason code | `oa_pipeline.stage4.add_readiness_status` |
| A new helper used by two or more stages | `oa_pipeline.common` |
| TA CRM certified values | `configs/crm_certified_values.yaml` (authoritative, NOAA OCADS-sourced; loaded by `oa_pipeline.qc_ta_ph.load_crm_certified_values`). The in-code fallback table is corrected but secondary. |
| pH standard correction logic | `oa_pipeline.qc_ta_ph` |
| Read only output inspection helpers | `oa_pipeline.inspect` |
| Tests for any of the above | `tests/test_<module_or_concept>.py` |

The top level `README.md` has a broader version of this table with more context.

---

## Style and conventions

### Keep helpers centralised

If a helper is used in two or more places, put it in `oa_pipeline.common` or in a more specific shared module. Do not redefine the same helper in multiple notebooks.

### Flags are advisory, never destructive

No stage should silently drop rows. Add a `flag_*` column, write an audit table where appropriate, and let the analyst filter on `analysis_audit_status`.

### Preserve provenance

When a value is selected from multiple possible source columns, preserve the source. Best source fields such as `ta_best_umolkg` and `ph_best` should have source tracking where possible.

### Keep filenames stable

Use role based filenames inside stage output folders, for example:

```text
oa_stage2_outputs/data/enhanced.csv
oa_stage4_outputs/data/analysis_ready.csv
```

Do not create long filenames by accumulating every previous input stem.

### Use `python -m` for Python commands

Prefer:

```bash
python -m pytest -q
python -m pip install -e ".[all]"
python -m pip freeze
```

This helps ensure commands run in the same interpreter where the package is installed.

### Keep the CRM values file authoritative

Certified CRM Total Alkalinity values live in
`configs/crm_certified_values.yaml`, transcribed from the NOAA OCADS
Dickson batch table. Only add a batch after transcribing it from the
certificate for that specific bottle lot — never interpolate or guess.
The loader stops the run on an unknown batch by design. If you touch the
input contract (column aliases, accepted values, tag rules), also update
`DATA_DICTIONARY.md` so it stays in sync with the code.

### Cite scientific changes in documentation

Thresholds, precision targets, pH scale assumptions, DIC tolerance rules, and CRM or pH buffer values are scientific decisions. Explain the source in the relevant README or documentation, not only in code comments.

---

## Testing expectations

Run the full test suite before opening a pull request:

```bash
python -m pytest -q
```

Run targeted tests while debugging:

```bash
python -m pytest tests/test_coalesce.py -q
python -m pytest tests/test_schema.py -q
python -m pytest tests/test_readiness.py -q
python -m pytest tests/test_pipeline_e2e.py -q
python -m pytest tests/test_app_core.py -q
```

For changes affecting any of the following, always run the E2E test:

```bash
python -m pytest tests/test_pipeline_e2e.py -q
```

Run the E2E test when you change:

- stage handoffs
- output filenames
- notebook parameters
- `run_pipeline.sh`
- schema aliases that affect the example workbook
- PASS / REVIEW / FAIL logic
- Stage 3 or Stage 4 reason codes
- the example workbook generator
- config loading

The E2E test runs the full notebook chain over `examples/example_data.xlsx` with Papermill.

---

## Pull request workflow

1. Open an issue first for non trivial changes, especially changes that affect scientific thresholds, schema, row verdicts, or output contracts.
2. Keep one conceptual change per pull request.
3. Update the relevant documentation if behavior changes.
4. Add or update tests.
5. Regenerate the deterministic example workbook if needed.
6. Run the full test suite.
7. Run the full notebook chain locally.

Recommended command sequence before opening a PR:

```bash
python examples/make_example_data.py --out examples/example_data.xlsx
./run_pipeline.sh examples/example_data.xlsx outputs/test_run
python -m pytest -q
python -m pytest tests/test_pipeline_e2e.py -q
```

On Windows PowerShell, use:

```powershell
python examples\make_example_data.py --out examples\example_data.xlsx
bash .\run_pipeline.sh examples\example_data.xlsx outputs\test_run
python -m pytest -q
python -m pytest tests\test_pipeline_e2e.py -q
```

---

## Scientific changes

Threshold edits are scientific decisions, not cosmetic parameter tweaks.

Examples include:

- salinity, temperature, TA, DIC, pCO2, and omega range bounds
- replicate SD thresholds
- DIC species sum tolerance
- pH diagnostic tolerance
- pH scale acceptance rules
- Stage 4 FAIL versus REVIEW severity tiers

If you change a scientific default:

1. document the reason
2. cite the relevant source in the documentation
3. run the example pipeline
4. check PASS / REVIEW / FAIL counts
5. add or update a test that pins the new behavior

A change that silently promotes rows from REVIEW to PASS weakens QC. A change that silently promotes many rows from PASS to REVIEW or FAIL may be scientifically justified, but it must be documented.

---

## Configuration changes

The runner supports optional per stage config files through:

```bash
./run_pipeline.sh INPUT_XLSX OUTPUT_ROOT --config-dir configs
```

It looks for files such as:

```text
configs/02_ta_ph_qc.yaml
configs/04_stage1a.yaml
configs/05_stage1b.yaml
configs/06_stage2.yaml
configs/07_stage3.yaml
configs/08_stage4.yaml
```

The same files may also use `.yml` or `.json`.

If a per stage config file is absent, that stage uses built in defaults and the runner prints a warning.

Broader files such as these can be kept as templates or manually merged into per stage configs:

```text
configs/cruise_grade_thresholds.yaml
configs/regional.yaml
```

---

## Bug reports

Open an issue with:

- a minimal reproducer, ideally a small input workbook or synthetic dataframe
- the exact command that failed
- the relevant `outputs/oa_<stage>_outputs/logs/manifest.json`
- the relevant `outputs/oa_<stage>_outputs/reports/report.md`
- package versions from:

```bash
python -m pip freeze
```

The manifests record input paths, parameters, thresholds, package versions, row counts, and output paths. Most questions about why a row was flagged or skipped can be answered from those files.

---

## Code of conduct

Be kind. Assume good faith. Disagreements are expected in scientific software, especially around thresholds and QC severity. Make the reasoning explicit and keep the discussion focused on evidence, reproducibility, and auditability.

---

## License

By contributing, you agree that your contributions are licensed under the MIT License that covers the rest of the project.
