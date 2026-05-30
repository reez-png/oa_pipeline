# Notebook 02 — TA CRM QC and pH-standard QC

> **Module-name note (post-audit):** This README predates the packaging of the
> helpers into the installable `oa_pipeline` package. Where the text refers to
> flat module names, the real import paths are:
> `oa_common.py` → `oa_pipeline/common.py`,
> `oa_qc_ta_ph.py` → `oa_pipeline/qc_ta_ph.py`,
> `oa_schema.py` → `oa_pipeline/schema.py`,
> `oa_policy.py` → `oa_pipeline/policy.py`,
> `oa_stage1b.py`/`oa_stage2.py`/`oa_stage3.py`/`oa_stage4.py` → `oa_pipeline/stage1b.py` … `stage4.py`,
> `oa_inspect.py` → `oa_pipeline/inspect.py`.
> The notebook code cells already use the correct `from oa_pipeline.<module> import ...` form.


Second notebook of the split. **This one matters most** because its
`derived.csv` is the file Stage 1A actually reads — get this right and the
rest of the chain has clean inputs to work from.

---

## 1. Role in the pipeline

```text
oa_prelim_data.xlsx
   │
   ├── 01_excel_viewer.ipynb       (optional inspection)
   │
   └── 02_ta_ph_qc.ipynb           ◄── THIS NOTEBOOK
           │
           ├─ TA CRM (Certified Reference Material) detection + SOP-driven correction
           ├─ pH-standard (TRIS / AMP / BIS) detection + buffer-table-based correction
           ├─ Per-sheet QC tables, JPEG plots, markdown reports
           │
           └─ sheet_<x>/data/derived.csv
                                │
                                ▼
                       04_stage1a.ipynb  →  05_stage1b → ... → 08_stage4
```

For each sheet:

1. **TA CRM QC.** Rows whose sample tag begins with `CRM_TAG_PREFIX` (default
   `"RM"`) are treated as CRM measurements. The notebook compares
   `certified − measured` Total Alkalinity against the SOP thresholds and
   chooses one of four statuses:
   `NO_ADJUST` (within noise floor), `ADJUST` (apply the mean offset),
   `FAIL` (offset exceeds reject threshold), `INSUFFICIENT_DATA` (too few
   non-outlier CRMs). Outliers within the CRM batch are flagged using the
   robust median-absolute-deviation rule from Iglewicz & Hoaglin (1993).
2. **pH-standard QC.** Rows whose tag begins with `PHSTD_TAG_PREFIX`
   (default `"tris"`) are treated as pH-buffer measurements. Their
   expected pH is linearly interpolated from the buffer's table
   (TRIS / AMP / BIS from the Dickson SOP — *Guide to Best Practices for
   Ocean CO2 Measurements*, PICES Spec. Pub. 3, 2007) at the measured
   temperature, and the residual `expected − measured` is classified as
   `OK` / `WARN` / `FAIL`.
3. **Derived CSV.** The QC-corrected sheet, with new columns
   `ta_corrected_umolkg`, `ph_corrected_from_phstd`, `ta_qc_status`,
   `phstd_status`, etc. **This is what Stage 1A reads.**

---

## 2. Inputs

| Item        | Type   | Notes |
|-------------|--------|-------|
| `XLSX_PATH` | `.xlsx` | Source workbook. Each sheet must contain the columns named by `TA_COL`, `PH_COL`, `PH_TEMP_COL`, `SAMPLE_TAG_COL`, and optionally `CRM_OR_SAMPLE_COL`. |

The notebook does **not** assume the workbook came from notebook 01. The two
notebooks operate on the same `.xlsx` but write to different output roots
(`...__viewer_outputs` vs `...__qc_outputs`).

---

## 3. Outputs

```text
<OUT_DIR  or  <workbook_stem>__qc_outputs>/
    sheet_<safe_sheet>/
        data/
            derived.csv                 # ◄── Stage 1A reads this
        qc/
            ta_crm_qc.csv               # per-CRM-row diff + outlier flags
            ta_corrections.csv          # mean correction (per group or overall)
            phstd_qc_<buffer>.csv       # per-standard residuals
            phstd_corrections_<buffer>.csv
        figures/
            rm_ta_diff_qc.jpeg
            phstd_diff_qc_<buffer>.jpeg
        reports/
            ta_crm_report.md
            phstd_report_<buffer>.md
        tables/
            table.html                  # scrollable view of the derived sheet
    logs/
        manifest.json                   # provenance: inputs, params, outputs, versions
```

**Naming choices, and why**

- Filenames are short. The sheet identity is in the parent folder
  (`sheet_<safe_sheet>/`), the file role is in the filename
  (`derived.csv`, `ta_crm_qc.csv`).
- The pH-buffer infix (`tris`, `amp`, `bis`) is kept. It is meaningful
  variant info — if you run with TRIS today and AMP tomorrow, both should
  coexist. This is the same logic as JWST's optical-element suffix
  ([JWST file-naming reference](https://jwst-pipeline.readthedocs.io/en/latest/jwst/data_products/file_naming.html)).
- The workbook stem is **not** in any filename. The grandparent folder
  already says `oa_prelim_data__qc_outputs/`, so repeating it is noise.
- No "stage 02" / "stage2" tag anywhere. The folder hierarchy is the
  stage indicator. Palantir's pipeline guide explicitly recommends this:
  "Choose descriptive names…Avoid using abbreviations…Cryptic names that
  simply increment a number will make it more difficult to read"
  ([source](https://www.palantir.com/docs/foundry/building-pipelines/development-best-practices)).

---

## 4. How to run

### From Jupyter
1. Open `02_ta_ph_qc.ipynb`.
2. Edit the `parameters` cell — at minimum, `XLSX_PATH`. If the workbook
   uses different column names, change `TA_COL`, `PH_COL`, etc.
3. **`Kernel → Restart & Run All`.**

### From the command line (Papermill)

```bash
papermill 02_ta_ph_qc.ipynb runs/02_ta_ph_qc.run.ipynb \
    -p XLSX_PATH "C:/path/to/your.xlsx" \
    -p SHEET "all" \
    -p PH_BUFFER "amp" \
    -p PHSTD_TAG_PREFIX "amp"
```

The first code cell is tagged `parameters` so Papermill injects overrides
immediately after it ([Papermill docs](https://github.com/nteract/papermill)).

### Dependencies

`pandas`, `openpyxl`, `matplotlib`. The notebook runs the `%pip install`
itself.

---

## 5. Parameters (selected; full list in the parameters cell)

### I/O
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `XLSX_PATH` | str | OneDrive path | Source workbook (.xlsx) |
| `OUT_DIR` | str or None | None | None → `<workbook>__qc_outputs/` |
| `SHEET` | str | `"0"` | `"0"`, sheet name, or `"all"` |

### Column names expected in each sheet
| Name | Default |
|------|---------|
| `TA_COL` | `"ta"` |
| `PH_COL` | `"pH_lab"` |
| `PH_TEMP_COL` | `"temp_lab"` |
| `SAMPLE_TAG_COL` | `"sample_tag"` |
| `CRM_OR_SAMPLE_COL` | `"crm_or_sample"` |

### TA CRM QC
| Name | Default | Meaning |
|------|---------|---------|
| `CRM_CORRECT_TA` | True | Master switch for TA QC |
| `CRM_BATCH` | `"213"` | Must exist in `configs/crm_certified_values.yaml` (or the corrected in-code fallback in `oa_pipeline/qc_ta_ph.py`). |
| `CRM_VALUES_CONFIG` | `"configs/crm_certified_values.yaml"` | **Audit fix N-1.** Path to the authoritative certified CRM values, transcribed from the NOAA OCADS Dickson batch table. `None` → use the corrected in-code fallback. |
| `CRM_TA_OVERRIDE` | None | Numeric value to override the certified TA |
| `CRM_TAG_PREFIX` | `"RM"` | CRM tag prefix |
| `MIN_CRM_N` | 2 | Minimum non-outlier CRMs needed to compute a correction |
| `TA_MAD_K` | 3.5 | Outlier rule: distance > k·1.4826·MAD |
| `TA_MAX_ABS_DIFF` | 20.0 | Also flag if `|diff| > this`; 0 disables |
| `TA_NO_ADJUST` | 2.0 | Noise floor (µmol/kg) |
| `TA_REJECT` | 20.0 | Reject threshold (µmol/kg) |
| `CORRECT_CRM_TOO` | False | Apply correction to CRM rows as well |
| `GROUP_BY` | None | Column to group corrections by, or None for one overall offset |

### pH standard QC
| Name | Default | Meaning |
|------|---------|---------|
| `PHSTD_QC` | True | Master switch |
| `PH_BUFFER` | `"tris"` | `"tris"` / `"amp"` / `"bis"` |
| `PHSTD_TAG_PREFIX` | `"tris"` | Tag prefix that identifies standard rows |
| `PHSTD_CORRECT_SAMPLES` | False | Whether to write corrected pH to samples |
| `MIN_PHSTD_N` | 2 | Minimum non-outlier standards |
| `PH_OK` | 0.02 | Status OK if `|mean diff|` ≤ this |
| `PH_WARN` | 0.05 | Status WARN if `|mean diff|` ≤ this, else FAIL |

---

## 6. What changed vs. the original monolithic notebook

| # | Change | Why |
|---|--------|-----|
| 1 | All TA + pH QC functions moved to `oa_qc_ta_ph.py` | Ten Simple Rules R4 + R7: notebook = story, module = reusable code. ~400 lines of QC math do not belong inline. |
| 2 | `cfg = SimpleNamespace(...)` replaced with a tagged `parameters` cell using uppercase constants | Papermill convention; lets the notebook run unattended from CI / a Makefile. |
| 3 | Single `%pip install` instead of one per major section | The original had it in both notebook 01 and notebook 02. Removed the duplicate. |
| 4 | Output filenames are short and descriptive (`derived.csv`, `ta_crm_qc.csv`) | The audit you ran identified accumulated stage tags / workbook stems as the problem. Sheet identity lives in the folder; file role lives in the filename. |
| 5 | New `logs/manifest.json` per run | Provenance (input path, parameters, outputs, package versions) belongs in a side-channel log, not in filenames. Ten Simple Rules R8. |
| 6 | **Audit fix N-1 (critical):** certified CRM Total Alkalinity values moved to the versioned `configs/crm_certified_values.yaml`, transcribed from the authoritative NOAA OCADS Dickson batch table. The previous hardcoded table had **7 of 8 values fabricated** (wrong by up to ~50 µmol/kg, vs a ~1–2 µmol/kg tolerance), which silently biased every corrected TA. `CRM_BATCH` is now loaded via `load_crm_certified_values(CRM_VALUES_CONFIG)` and passed to `apply_ta_crm_correction(crm_values=...)`. Unknown batches now stop the run with an instructive error instead of guessing. `PH_STD_TABLES` still lives in `qc_ta_ph.py`. |
| 7 | `robust_outlier_flags` and `build_corrections_table` moved to `oa_common.py` | Stage 3 of the original notebook redefined `robust_outlier_flags`. Moving it to `oa_common` now prevents that divergence. |
| 8 | `matplotlib` imported lazily inside plot functions | Same as the original — preserves the ability to run on headless / CI nodes without matplotlib. |
| 9 | Plot annotation logic hardened | The original fell back to a literal string `"sample_tag"` when the column was missing — which would then `die()` inside `resolve_col`. Now the plot is skipped cleanly if the tag column is absent. |

---

## 7. Reasoning, citation-by-citation

1. **Rule et al. (2019), *Ten Simple Rules for Reproducible Research in
   Jupyter Notebooks***. Rule 4 (modularize) and Rule 7 (build a pipeline)
   justify pulling the QC out of the notebook; Rule 5 (parameterize) is
   why the parameters cell exists; Rule 8 (record provenance) is why
   `manifest.json` exists.
   <https://arxiv.org/pdf/1810.08055>

2. **Pimentel et al. (2019), *A Large-Scale Study about Quality and
   Reproducibility of Jupyter Notebooks***. Empirical evidence that
   ~10 % of public notebooks import from local modules, and that lack of
   modularization correlates with reproducibility failure. The motivation
   for `oa_common.py` and `oa_qc_ta_ph.py`. Summary in TDS:
   <https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/>

3. **Papermill (nteract).** Source of the `parameters`-tagged cell
   convention used in the parameters block.
   <https://github.com/nteract/papermill>

4. **Iglewicz & Hoaglin (1993), *How to Detect and Handle Outliers*,
   ASQC vol. 16.** Origin of the modified-z / MAD outlier rule
   (`|x − median| > k · 1.4826 · MAD`) used by `robust_outlier_flags`.

5. **Dickson, Sabine & Christian (eds.) (2007), *Guide to Best Practices
   for Ocean CO₂ Measurements***, PICES Special Publication 3 / IOCCP
   Report 8. Source of the TRIS, AMP, BIS buffer tables that live in
   `PH_STD_TABLES`. SOP threshold conventions for TA CRM correction
   trace back to the same document.

6. **JWST Calibration Pipeline file-naming reference.** Real scientific
   pipeline that uses one descriptive suffix per product type rather than
   accumulating stage tags. Our `derived.csv` / `ta_crm_qc.csv` naming
   follows this style.
   <https://jwst-pipeline.readthedocs.io/en/latest/jwst/data_products/file_naming.html>

7. **Palantir Foundry, *Building pipelines — development best practices*.**
   "Descriptive names, distinctive part first, avoid cryptic abbreviations."
   <https://www.palantir.com/docs/foundry/building-pipelines/development-best-practices>

8. **Ian Rose, *Working with Jupyter notebooks* (LA best-practices guide)**
   and **Russ Poldrack, *Better Code, Better Science*.** Both reinforce
   "Restart & Run All — or it didn't happen" and the recommendation to
   parameterize notebooks so a runner / CI step can execute them
   non-interactively.
   <https://ian-r-rose.github.io/best-practices/notebooks.html>
   <https://russpoldrack.substack.com/p/best-practices-for-using-jupyter>

---

## 8. Downstream impact (what changes for Stage 1A)

The original `cfg.input_csv` for Stage 1A was:

```
…\oa_prelim_data__qc_outputs\sheet_0\data\oa_prelim_data__0__derived.csv
```

With Notebook 02 refactored, the file is now:

```
…\oa_prelim_data__qc_outputs\sheet_0\data\derived.csv
```

When we refactor Stage 1A (next), its `parameters` cell will default to the
new clean path. **If you've already run the original monolithic notebook
once, the old long-named CSV will still be there and Stage 1A will need
its parameter pointed at the new short-named one.** The cleanest thing is
to delete the old `oa_prelim_data__qc_outputs/` folder once and re-run
Notebook 02 to repopulate it.

---

## 9. Known limitations / things to revisit later

- **Reference tables are inline in `oa_qc_ta_ph.py`.** If the chemist
  bookkeeping for CRMs grows beyond a handful of batches, move
  `CRM_CERTIFIED_TA` to a config file — **done** (audit fix N-1):
  certified values now live in `configs/crm_certified_values.yaml`,
  sourced from the NOAA OCADS Dickson batch table. Always confirm the
  value against the actual certificate PDF for your bottle lot. Same
  for `PH_STD_TABLES` if more buffers are added.
- **No version pinning yet.** A `requirements.txt` with pinned
  `pandas`, `openpyxl`, `matplotlib` versions will land alongside the
  notebook 03 split — at that point we will have enough notebooks for
  pinning to matter.
- **`GROUP_BY` is not wired through to the plots.** If you set
  `GROUP_BY="analysis_date"`, you get per-group corrections in the CSV
  but the plot still shows the overall scatter. Fine for now; surfacing
  per-group plots is a future enhancement.
- **Pipeline run-through.** End-to-end test of notebooks 01 → 08 should
  land once 03 is in. For now, notebook 02 has been smoke-tested
  end-to-end against a synthetic 14-row workbook in the sandbox and
  produces a clean 10-file output tree plus a complete manifest.
