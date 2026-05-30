# Notebook 03 — QC Output Review

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


Third notebook of the split. **Optional, read-only.** Walks a QC output
folder, builds an inventory, previews CSVs, displays figures inline. It
produces nothing that downstream stages consume — its only "output" is what
you see on screen.

---

## 1. Role in the pipeline

```text
Notebook 02 (or any stage that follows the same layout)
   │
   └──►  oa_prelim_data__qc_outputs/
            sheet_<x>/
                data/   derived.csv          ◄── what Stage 1A actually reads
                qc/     ta_crm_qc.csv  ta_corrections.csv  phstd_qc_<buf>.csv  ...
                figures/    rm_ta_diff_qc.jpeg  phstd_diff_qc_<buf>.jpeg
                reports/    ta_crm_report.md   phstd_report_<buf>.md
                tables/     table.html
            logs/
                manifest.json
                                │
                                ▼
                  03_qc_output_review.ipynb   ◄── THIS NOTEBOOK
                  • build inventory (DataFrame)
                  • optional keyword filter
                  • preview head of every matching CSV
                  • show every matching JPEG/PNG inline
```

Use this notebook between Stage 02 and Stage 1A (notebook 04) to verify
the QC outputs *look right* before passing them on. It is equally useful
later as a generic inspector of any stage's output folder.

---

## 2. Inputs

| Item | Type | Notes |
|------|------|-------|
| `OUTPUT_ROOT` | folder | Any directory produced by an OA pipeline stage. Default = the path Notebook 02 writes to. |

---

## 3. Outputs

**None on disk.** Everything is rendered into the notebook:

- An inventory `DataFrame` (in memory) with one row per file.
- Console previews of CSV heads.
- Inline matplotlib figures.

Why no `manifest.json` here, when Notebooks 01 and 02 both wrote one:
those notebooks produce artifacts that *downstream* stages consume, and
provenance for those artifacts has to live somewhere (Rule 8 of "Ten
Simple Rules for Reproducible Research in Jupyter Notebooks"). Notebook
03 produces no artifacts — writing a manifest would be ceremony without
purpose. The rule applies to outputs that feed something else.

---

## 4. How to run

### From Jupyter
1. Make sure Notebook 02 (or whichever stage you want to inspect) has
   already produced an output folder.
2. Open `03_qc_output_review.ipynb`.
3. Set `OUTPUT_ROOT` in the parameters cell. Optionally set
   `KEYWORD_FILTER` (e.g. `"phstd"` to look only at pH-standard outputs).
4. **`Kernel → Restart & Run All`.**

### From the command line (Papermill)

```bash
papermill 03_qc_output_review.ipynb runs/03_qc_review.run.ipynb \
    -p OUTPUT_ROOT "/path/to/oa_prelim_data__qc_outputs" \
    -p KEYWORD_FILTER "phstd"
```

The executed copy at `runs/03_qc_review.run.ipynb` will contain all the
inline figures and CSV previews, so a non-interactive run still produces
a useful artifact for a review meeting.

### Dependencies

`pandas` and `matplotlib`. `matplotlib` is imported **lazily** inside
`show_image`, so a quick inventory + CSV-only run works in an environment
where `matplotlib` is not installed.

---

## 5. Parameters

| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `OUTPUT_ROOT` | str | path next to OneDrive workbook | Folder to scan. |
| `KEYWORD_FILTER` | str / None | None | Case-insensitive substring; matched against both filename and relative path, so `"sheet_0"` catches every file under that sheet. |
| `CSV_PREVIEW_ROWS` | int | 10 | Rows shown per CSV. The file is streamed (`pd.read_csv(..., nrows=N)`), not read fully and trimmed. |
| `SHOW_ALL_CSV_TABLES` | bool | True | Bulk CSV preview on/off. |
| `SHOW_ALL_FIGURES` | bool | True | Bulk figure display on/off. |
| `SINGLE_CSV_TO_PREVIEW` | str / None | None | One specific CSV's full path, if you want it. |
| `SINGLE_IMAGE_TO_PREVIEW` | str / None | None | One specific image's full path, if you want it. |

---

## 6. What changed vs. the original monolithic notebook

| # | Change | Why |
|---|--------|-----|
| 1 | Lives in its own `.ipynb` (cells 48–72 of the original) | Restart-and-run-all atomicity. |
| 2 | Inspection helpers moved to a new `oa_inspect.py` module | The Pimentel et al. (2019) finding (~10 % modularization rate in public notebooks) and Rule 4 ("Modularize your code") both push toward extraction. Crucially, these helpers are not shared by any other stage, so they go in `oa_inspect.py`, **not** `oa_common.py`. Promote to `oa_common` only when the second caller appears. |
| 3 | `FileNotFoundError` replaced with `die(...)` for the missing-folder case | Failure mode now matches every other notebook in the refactor: a clear named exit instead of a stack trace. |
| 4 | `pd.read_csv(..., nrows=N)` instead of reading the whole file and `.head(N)` | Avoids parsing a 100k-row QC table just to throw most of it away. The difference is invisible at our current 14-row test scale but very visible on real data. |
| 5 | Tagged `parameters` cell | Papermill convention, same as Notebooks 01 / 02. |
| 6 | Inventory table shows `relative_path` first | Display-friendly on narrow notebook viewports; full path is still in the dataframe for copy-paste. |
| 7 | `matplotlib` imported lazily inside `show_image` | A user running only the CSV inventory path does not need matplotlib at all. |
| 8 | Per-file `try/except` around CSV read and image display | One malformed file no longer kills the loop — it logs a "Reason: ..." line and moves on. |
| 9 | No `%pip install` cell | The original did not have one either, and we should not silently introduce package installs in a read-only inspector. |
| 10 | No `manifest.json` written | This notebook has no downstream consumers (justified in §3). |

---

## 7. Reasoning, citation-by-citation

1. **Rule et al. (2019), *Ten Simple Rules for Reproducible Research in
   Jupyter Notebooks***. Rule 4 (modularize) → `oa_inspect.py`.
   Rule 5 (parameterize) → tagged `parameters` cell. Rule 8 (record
   provenance) is consciously **not applied here** — the rule is about
   outputs that feed other stages, of which this notebook has none.
   <https://arxiv.org/pdf/1810.08055>

2. **Pimentel, J. F. et al. (2019), *A Large-Scale Study about Quality and
   Reproducibility of Jupyter Notebooks***. Empirical motivation for
   extracting helpers into modules.
   <https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/>

3. **Papermill (nteract).** The `parameters` cell tag is its convention.
   <https://github.com/nteract/papermill>

4. **Martin Fowler, *Refactoring* (2nd ed., 2018) — the "Rule of Three".**
   The rule of thumb that says you should *not* generalize on the first
   call. The first time you write something, write it inline. The second
   time, you may grumble but write it again. The third time, refactor. We
   applied a slightly stricter version here: inspection helpers live in
   `oa_inspect.py` rather than being promoted to `oa_common.py` because
   only one notebook currently needs them.

5. **JWST file-naming reference.** Still relevant because Notebook 03
   *displays* files written by Notebook 02, and Notebook 02 follows the
   "short descriptive suffix, identity in the parent folder" convention
   that JWST uses. The inventory view confirms it: `derived.csv` is
   recognizable as the data product for Stage 1A specifically because
   `sheet_<x>/data/` carries the role-and-sheet identity.
   <https://jwst-pipeline.readthedocs.io/en/latest/jwst/data_products/file_naming.html>

6. **Ian Rose, *Working with Jupyter notebooks***. Restart-and-run-all,
   same rule as before.
   <https://ian-r-rose.github.io/best-practices/notebooks.html>

---

## 8. Verification (smoke test)

Smoke-tested in the sandbox against the actual output tree Notebook 02
produced (synthetic 14-row workbook). Result:

```
Files (total) : 11
Files (match) : 11
CSV files     : 5
Image files   : 2
derived.csv (for Stage 1A): sheet_0/data/derived.csv
Filter "phstd" -> 4 matching files
  sheet_0/figures/phstd_diff_qc_tris.jpeg
  sheet_0/qc/phstd_corrections_tris.csv
  sheet_0/qc/phstd_qc_tris.csv
  sheet_0/reports/phstd_report_tris.md
```

This confirms two things that matter:

- The pipeline chain holds: a file written by Notebook 02 is found by
  Notebook 03 at the expected short path (`sheet_0/data/derived.csv`),
  not the old long-named one.
- The keyword filter works on both names and paths, which is what makes
  `"sheet_0"`-style filters useful.

---

## 9. Known limitations / things to revisit later

- **No "diff vs last run" feature.** Useful for catching regressions after
  re-running Notebook 02 with different parameters, but real scope creep;
  if needed, it should be its own notebook (`03b_compare_runs.ipynb`) or
  a hash-based check inside the manifests.
- **No file content search.** Only filename / relative path are scanned.
  Adding a `--grep` option that reads the head of each CSV would be cheap
  but is not a current need.
- **`matplotlib` figures pile up.** Each `show_image` call creates a new
  figure; long inventories generate many. If this becomes a problem, add
  `plt.close('all')` between iterations.
- **No version pinning yet.** Same as Notebooks 01 / 02. A
  `requirements.txt` will land when more notebooks are in.
