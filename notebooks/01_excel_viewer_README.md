# Notebook 01 — Excel Workbook Viewer

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


First notebook of the eight-step OA preprocessing pipeline that was previously
glued into a single `.ipynb`. This document explains **what this notebook does,
where it sits in the chain, how to run it, and why every design choice was
made the way it was**.

---

## 1. Role in the pipeline

`01_excel_viewer.ipynb` is a **first-pass inspection** of the source Excel
workbook. It does not feed Stage 1A. The data that feeds Stage 1A is the
`derived.csv` written by Notebook 02 (TA CRM / pH-standard QC).

Use this notebook when you want to:

- Confirm the workbook opens and pandas can parse every sheet.
- See each sheet's column list and row count at a glance.
- Get a static, scrollable HTML view of each sheet you can open in any
  browser (useful when Excel isn't available or you want to share a snapshot).
- Keep a versionable raw CSV alongside the original `.xlsx` so future runs
  can diff against a baseline.

```text
oa_prelim_data.xlsx
   │
   ├── 01_excel_viewer.ipynb  ← THIS NOTEBOOK (optional, inspection-only)
   │       └── raw CSV + HTML per sheet
   │
   └── 02_ta_ph_qc.ipynb      (next notebook, on the critical path)
           └── derived CSV  ──►  03 / 04 / ... / 08
```

Notebooks 02 → 08 are still to be split; this README will be cross-referenced
by them as they land.

---

## 2. Inputs

| Item        | Type   | Notes |
|-------------|--------|-------|
| `XLSX_PATH` | `.xlsx` file | The source workbook. Default points at the original OneDrive location. Must end in `.xlsx`. |

---

## 3. Outputs

```text
<OUT_DIR  or  <workbook_stem>__viewer_outputs>/
    sheet_<safe_sheet>/
        data/
            raw.csv             # exact contents of the sheet, columns trimmed
        tables/
            table.html          # scrollable single-page HTML view
    logs/
        manifest.json           # provenance: input, params, outputs, versions
```

`<safe_sheet>` is the sheet name with spaces, slashes, backslashes and colons
replaced by underscores so it is safe on Windows paths.

**Things deliberately *not* in output filenames:**

- The workbook stem (e.g. `oa_prelim_data__`). It is already in the *parent*
  folder name; repeating it inside every file is redundant noise.
- Any "stage" tag. There are no downstream stages from this notebook, and
  even if there were, the role indicator belongs in the *folder* (`data/`,
  `tables/`, `logs/`), not the filename.

This is the same convention used by mature scientific calibration pipelines
such as JWST, where one short product-type suffix per file is preferred over
accumulated stage tags
([JWST file-naming reference](https://jwst-pipeline.readthedocs.io/en/latest/jwst/data_products/file_naming.html)).
Palantir's pipeline-building best-practices guide makes the same point:
prefer descriptive names, avoid abbreviation accumulation, and put the
distinctive part of the name first
([Palantir docs](https://www.palantir.com/docs/foundry/building-pipelines/development-best-practices)).

---

## 4. How to run

### From Jupyter
1. Open `01_excel_viewer.ipynb`.
2. Edit the `Parameters` cell (XLSX_PATH at minimum).
3. **`Kernel → Restart & Run All`.**

Always restart-and-run-all; never trust outputs from a notebook that has been
poked at out of order. Ian Rose's notebook best-practices guide phrases this
as "restart and run all, or it didn't happen"
([source](https://ian-r-rose.github.io/best-practices/notebooks.html)).
Pimentel et al.'s 2019 empirical study of 1.16 M public notebooks (summarised
in the [TDS reproducibility article](https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/))
identified out-of-order execution as one of the dominant causes of notebooks
failing to reproduce.

### From the command line (Papermill)

The first code cell is tagged `parameters`. Papermill will inject overrides
immediately after it:

```bash
papermill 01_excel_viewer.ipynb runs/01_excel_viewer.run.ipynb \
    -p XLSX_PATH "C:/path/to/your.xlsx" \
    -p SHEET "all" \
    -p HTML_MAX_ROWS 1000
```

This is the standard pattern documented by the Papermill project
([nteract/papermill](https://github.com/nteract/papermill)) and recommended
by *"Ten Simple Rules for Reproducible Research in Jupyter Notebooks"*
([PLOS Computational Biology, 2019](https://arxiv.org/pdf/1810.08055)) for
turning notebooks into pipeline components.

### Dependencies
`pandas`, `openpyxl`. The notebook runs `%pip install openpyxl` itself the
first time it executes; everything else is in standard Anaconda.

---

## 5. Parameters

| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `XLSX_PATH` | `str` | OneDrive path | Source workbook. Must exist and end in `.xlsx`. |
| `OUT_DIR` | `str` or `None` | `None` | Where to write outputs. `None` → `<workbook>__viewer_outputs/` next to the workbook. |
| `SHEET` | `str` | `"0"` | `"0"` = first sheet, `"Foo"` = named sheet, `"all"` = every sheet. |
| `PREVIEW_ROWS` | `int` | `15` | Rows in the console quick-summary. |
| `HTML_MAX_ROWS` | `int` or `None` | `None` | Rows in the HTML table. `None` = all rows. |
| `OPEN_HTML` | `bool` | `False` | Open each HTML in the default browser after writing. |
| `WRITE_RAW_CSV` | `bool` | `True` | Also write `raw.csv` alongside the HTML. |

---

## 6. What changed vs. the original monolithic notebook

| # | Change | Why |
|---|--------|-----|
| 1 | Lives in its own `.ipynb` instead of being cells 0–19 of a 254-cell file | A notebook should be one linear story, restartable end-to-end. Ten Simple Rules, Rule 5. |
| 2 | Single `parameters`-tagged cell at the top | Papermill convention; lets the notebook run unattended from CI / a Makefile. |
| 3 | Utility functions imported from `oa_common.py` instead of being copy-pasted | Pimentel et al. found only ~10 % of public notebooks modularize this way; Ten Simple Rules Rule 7 says move shared code to modules. |
| 4 | `%pip install openpyxl` runs once, not twice | The original had it in both this section *and* Notebook 2. Removed the duplicate. |
| 5 | Output filenames are short (`raw.csv`, `table.html`) | Identity lives in the *folder*, not repeated in every filename. JWST / Palantir naming guidance. |
| 6 | New `logs/manifest.json` written per run | Provenance (input path, parameters, outputs, package versions) belongs in a side-channel log, not in filenames. Ten Simple Rules Rule 8. |
| 7 | Path validation happens *before* any work | Fail fast with a clear `die(...)` message rather than crashing mid-loop. LA notebook best-practices guide. |
| 8 | Workbook stem dropped from filenames | Stops the "filename grows by one stage tag per step" antipattern that the downstream stages were causing. |

---

## 7. Reasoning, citation-by-citation

If you want the design conversation behind each rule, the sources I leaned on
are:

1. **Rule et al. (2019), *Ten Simple Rules for Reproducible Research in
   Jupyter Notebooks*** — PLOS Computational Biology / arXiv 1810.08055.
   Strongest single reference for pipeline-friendly notebook structure
   (Rule 4: modularize; Rule 5: parameterize; Rule 7: build a pipeline;
   Rule 8: record provenance).
   <https://arxiv.org/pdf/1810.08055>

2. **Pimentel, J. F. et al. (2019), *A Large-Scale Study about Quality and
   Reproducibility of Jupyter Notebooks*.** Found, among other things, that
   only ~10 % of analysed public notebooks imported from local modules, and
   that lack of modularization correlated with reproducibility failures.
   Summarised in Towards Data Science:
   <https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/>

3. **Papermill (nteract).** The canonical tool for running parameterised
   notebooks as pipeline stages. The `parameters` cell tag and command-line
   `-p NAME value` interface used in §4 above come straight from its docs.
   <https://github.com/nteract/papermill>

4. **Ian Rose, *Working with Jupyter notebooks* (Los Angeles best-practices
   guide).** Source of the "restart and run all, or it didn't happen" rule,
   and of the recommendation to avoid hard-coded absolute paths.
   <https://ian-r-rose.github.io/best-practices/notebooks.html>

5. **Russ Poldrack, *Best practices for using Jupyter notebooks* (Better Code,
   Better Science, Ch. 6.6).** Reinforces the batch-execution rule: outputs
   are only trustworthy when the notebook was run end-to-end by
   `nbconvert` / Papermill.
   <https://russpoldrack.substack.com/p/best-practices-for-using-jupyter>

6. **JWST Calibration Pipeline file-naming reference.** Real-world scientific
   pipeline that uses short product-type suffixes rather than accumulated
   stage tags. The naming pattern in §3 above mirrors theirs.
   <https://jwst-pipeline.readthedocs.io/en/latest/jwst/data_products/file_naming.html>

7. **Palantir Foundry, *Building pipelines — development best practices*.**
   Naming-convention guidance: descriptive names, distinctive part first,
   avoid cryptic abbreviations.
   <https://www.palantir.com/docs/foundry/building-pipelines/development-best-practices>

---

## 8. Known limitations / things to revisit later

- **No version pin** on `pandas` / `openpyxl` yet. Ten Simple Rules Rule 6
  recommends pinning. When notebook 02 lands, we should add a
  `requirements.txt` and the notebooks should warn (not crash) if versions
  drift.
- **No automated test.** A small `tests/test_smoke.py` that runs this
  notebook against a fixture workbook via Papermill and asserts the
  expected output tree would catch regressions during the rest of the
  split. Worth adding once 02 and 03 are in.
- **Sheet names with non-ASCII characters** are passed through unchanged.
  If the workbook ever uses, say, Cyrillic sheet names, the folder name
  will contain Unicode. Usually fine on modern Windows; flag if it bites.
