# Notebook 06 — Stage 2: replicate harmonisation and duplicate checks

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


Sixth notebook of the split. **First stage that operates across rows.**
Reads Stage 1B's `analysis_ready_samples.csv`, adds two grouping keys,
detects duplicates, and computes per-replicate-group means + standard
deviations. Flags rows whose group has a conflict in metadata / QC /
provenance / source or whose metric SD exceeds the GOA-ON "weather"
precision threshold.

---

## 1. Role in the pipeline

```text
05_stage1b.ipynb
   └── <stage1b_out>/data/analysis_ready_samples.csv
                                │
                                ▼
                  06_stage2.ipynb            ◄── THIS NOTEBOOK
                     • re-resolve canonical aliases (defensive)
                     • add sample_month, depth_round_m
                     • duplicate detection (per-row + per-group summary)
                     • replicate harmonisation (means + SDs)
                     • conflict + SD-threshold flags
                     • write enhanced.csv (rows + flags) +
                       per-group tables (replicate means, conflicts, ...)
                                                  │
                                                  ▼
                                       07_stage3.ipynb → 08_stage4
```

**What Stage 2 does NOT do.** It does not rebuild `ph_best`,
`ph_co2sys`, `ta_best_umolkg`, `pco2_best_uatm`, or `dic_best_umol_kg`.
Those are Stage 1B's job and are preserved unchanged. Stage 2 only
*aggregates* and *flags*; it never silently overwrites values. The
analyst sees every disagreement and decides.

---

## 2. Inputs

| Item | Type | Notes |
|------|------|-------|
| `INPUT_CSV` | `.csv` | Stage 1B's `analysis_ready_samples.csv` (sample-only subset). Each row is one chemistry measurement at a (station, depth, date). |
| `CONFIG_PATH` *(optional)* | `.json` / `.yml` / `.yaml` | Deep-merges onto `oa_stage2.STAGE2_DEFAULTS`. |

---

## 3. Outputs

```text
<OUT_DIR>/
    data/
        enhanced.csv               # ◄── Stage 3 reads this
        enhanced.parquet
    tables/
        column_inventory.csv       # full per-column inventory
        canonical_presence.csv     # required+expected fields presence
        duplicate_rows.csv         # every row in a duplicate group
        duplicate_summary.csv      # one row per duplicate group, with min/max/range
        replicate_means_sd.csv     # per-replicate-group aggregates
        replicate_consistency.csv  # per-(group,conflicting-field)
        replicate_disagreement.csv # per-(group,metric) with SD > threshold
    reports/
        report.md
    logs/
        manifest.json
        effective_config.json
```

**What's in `enhanced.csv`?** Every column the input had plus:

- `sample_month` and `depth_round_m` (grouping helpers).
- `flag_duplicate`, `duplicate_group_size` (duplicate annotations).
- `replicate_group_n`, `flag_has_replicates`.
- Five per-class conflict flags: `flag_replicate_metadata_conflict`,
  `flag_replicate_provenance_conflict`, `flag_replicate_qc_conflict`,
  `flag_replicate_source_conflict`, `flag_replicate_other_conflict`.
- A roll-up `flag_replicate_any_conflict`.
- `flag_replicate_sd_exceeded` — True if any metric's SD across the
  row's replicate group exceeded the threshold.
- `source_file_stage2` and `stage2_processed_utc` provenance.

---

## 4. How to run

### From Jupyter
1. Make sure Notebook 05 (Stage 1B) has produced `analysis_ready_samples.csv`.
2. Open `06_stage2.ipynb`.
3. Edit the parameters cell — at minimum, `INPUT_CSV` and `OUT_DIR`.
4. **`Kernel → Restart & Run All`.**

### From the command line (Papermill)

```bash
papermill 06_stage2.ipynb runs/06_stage2.run.ipynb \
    -p INPUT_CSV  "/path/to/oa_stage1b_outputs/data/analysis_ready_samples.csv" \
    -p OUT_DIR    "/path/to/oa_stage2_outputs" \
    -p DEPTH_ROUND_DECIMALS 0
```

### Dependencies

`pandas` (required), `pyarrow` or `fastparquet` (optional, for Parquet),
`pyyaml` (optional, for YAML configs), `tabulate` (optional, for nicer
markdown tables).

---

## 5. Parameters

### I/O
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `INPUT_CSV` | str | new Stage 1B short path | Stage 1B's `analysis_ready_samples.csv`. |
| `OUT_DIR` | str | `oa_stage2_outputs` next to OneDrive workbook | Output root. |
| `CONFIG_PATH` | str / None | None | Optional override file. |

### Stage 2 behaviour
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `DEPTH_ROUND_DECIMALS` | int | 1 | Rounding for `depth_round_m`. 1 dp ≈ 10 cm bins; 0 dp ≈ 1 m bins. |
| `NO_PARQUET` | bool | False | Skip Parquet writes. |
| `DRY_RUN` | bool | False | Plan everything, write nothing. |

### Important config keys (override via `CONFIG_PATH`)

- `duplicate_keys` — list of columns whose tuple identifies a duplicate.
- `replicate_group_keys` — list of columns whose tuple identifies a
  replicate group (typically larger time-window than `duplicate_keys`).
- `replicate_mean_vars` — numeric columns to compute means + SDs for.
- `replicate_sd_thresholds` — per-metric thresholds for the
  `flag_replicate_sd_exceeded` flag. Defaults match the **GOA-ON
  "weather" precision objectives** (Newton et al. 2015, "Global Ocean
  Acidification Observing Network Requirements and Governance Plan"):
  pH ± 0.02, TA ± 10 µmol/kg. Tighten for ocean-climate-grade studies,
  loosen for community-science / coastal-deployment use.
- `replicate_conflict_field_classes` — bucket-name -> [columns]. Drives
  which `flag_replicate_*_conflict` fires.

---

## 6. What changed vs. the original monolithic notebook

| # | Change | Why |
|---|--------|-----|
| 1 | Lives in its own `.ipynb` (cells 133–168 of the original) | Restart-and-run-all atomicity. |
| 2 | `cfg = SimpleNamespace(...)` → tagged `parameters` cell | Papermill convention. |
| 3 | **Default `INPUT_CSV` fixed.** The original had `oa_stage1b_outputs\analysis_ready_samples.csv` (flat path) but the refactored Stage 1B writes to `<stage1b_out>/data/analysis_ready_samples.csv` (with `data/` subfolder) | Same audit-bug class we fixed in every stage so far: each downstream `cfg.input_csv` was hardcoded to a clean filename that the previous stage never actually produced. |
| 4 | All Stage 2 logic moved to `oa_stage2.py`: replicate harmonisation, duplicate check, grouping helpers, conflict pivots, presence inventory | Ten Simple Rules R4 (modularize). The original cell 146 was 7 kB of replicate logic; the cell 148 report-writer alone is 2.7 kB. Notebook is now ~ 250 lines of orchestration, not ~ 700 lines of logic. |
| 5 | Eleven helpers deleted from the notebook (imported from `oa_common`) | `die`, `utc_stamp`, `write_json`, `write_text`, `deep_update`, `load_config`, `normalize_columns`, `first_existing_col`, `make_column_inventory`-like helpers. The original notebook redefined every one of them at the top of Stage 2 — the largest single duplication block in the audit. |
| 6 | `write_report` is now inline in the notebook | The original defined a `write_report` function. Three different stages of the original notebook had three different functions also called `write_report`, with different signatures. They couldn't be merged (the report content differs per stage), but having three same-named functions was a silent-overwrite hazard when the cells were run in one kernel. Inlining the report markdown removes the name collision while keeping the per-stage content. |
| 7 | Output filenames are short and descriptive: `enhanced.csv`, `column_inventory.csv`, `replicate_consistency.csv`, etc. | JWST-style "identity in folder, role in filename". The original named every output `<long_input_stem>__stage2_enhanced.csv` etc., which accumulates stems from prior stages and produces overlong paths. |
| 8 | `flag_*` columns initialised cleanly as boolean dtype | The original mixed Python `False` with pandas `Series(False, dtype="boolean")` and relied on `.fillna(False).astype("boolean")` to recover. Same behaviour, less confusing. |
| 9 | SD-threshold defaults explicitly grounded in GOA-ON (§7 below) | The values 0.02 / 10.0 were correct in the original but unexplained. The README and module docstring now cite the source. |

---

## 7. Reasoning, citation-by-citation

1. **Newton, J. A. et al. (2015), *Global Ocean Acidification Observing
   Network Requirements and Governance Plan***. The source of the
   "weather" precision objectives (pH ± 0.02, TA ± 10 µmol/kg) used as
   the default SD thresholds in `replicate_sd_thresholds`. The plan
   defines two precision tiers — "weather" (suitable for
   short-term/coastal change detection) and "climate" (~ pH ± 0.003,
   TA ± 2 µmol/kg, suitable for decadal trend detection). We default
   to "weather" because that is what most discrete-sample workflows
   target; the climate tier should be configured explicitly when the
   dataset supports it.
   <https://www.goa-on.org/documents/general/GOA-ON_plan_print.pdf>

2. **DOE (1994), *Handbook of Methods for the Analysis of the Various
   Parameters of the Carbon Dioxide System in Sea Water*, SOP 23
   ("Estimation of the precision of an analytical method using duplicate
   determinations")**. The "use the standard deviation of replicate
   measurements as the estimate of precision" approach used by
   `replicate_harmonise`. The function uses `ddof=1` (sample SD,
   Bessel's correction) for the same reason SOP 23 does:
   replicates are samples from the population of possible measurements,
   not the population itself.

3. **OCADS NDP-090 — Total Alkalinity Measurements**. Concrete real-world
   example of the same approach. Reports a measurement repeatability of
   1.06 µmol/kg over 89 duplicate pairs using DOE 1994 SOP 23. The
   GOA-ON "weather" 10 µmol/kg ceiling we apply here is therefore a
   loose threshold by ship-laboratory standards — appropriate for
   workflows that include shore-lab or community-science data, and
   tightenable via config for cruise-grade datasets.
   <https://www.ncei.noaa.gov/access/ocean-carbon-acidification-data-system/oceans/ndp_090/talk090.html>

4. **Rule et al. (2019), Ten Simple Rules for Reproducible Research in
   Jupyter Notebooks**. R4 → `oa_stage2.py`; R5 → `parameters` cell;
   R8 → manifest + effective_config + per-table audit CSVs.
   <https://arxiv.org/pdf/1810.08055>

5. **Pimentel et al. (2019)**. Empirical motivation for moving the
   eleven redefined helpers out of the notebook and importing from
   `oa_common.py`.
   <https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/>

6. **Papermill** — the `parameters`-tagged cell convention.
   <https://github.com/nteract/papermill>

7. **JWST input/output conventions**. "Use `output_dir` to place the
   results in a different directory instead of using `output_file` to
   rename." Why output filenames are short and `OUT_DIR` is flat.
   <https://jwst-pipeline.readthedocs.io/en/latest/jwst/user_documentation/input_output_file_conventions.html>

---

## 8. Verification (smoke test)

End-to-end test in the sandbox against the actual
`analysis_ready_samples.csv` Notebook 05 produced. Result:

```
Rows loaded         : 6
Columns             : 134 -> 147 (after Stage 2 additions)

Duplicate keys used : ['sample_id','replicate_id','sample_date','station_id','depth_m']
Duplicate rows      : 6  (all rows; synthetic data has NaN/NaT
                          for sample_id/station_id/sample_date, so they
                          all match each other -- correct behaviour)
Duplicate groups    : 1

Replicate group keys: ['cruise_id','transect_id','station_id','depth_round_m','sample_date']
Numeric mean vars   : 15
Replicate groups    : 1
Consistency conflicts: 1
SD threshold failures: 1
  (TA spread 2282-2332 umol/kg has SD ~18 > threshold 10 -> correctly
   flagged via flag_replicate_sd_exceeded)
```

Chain integrity: Notebook 02 → 04 → 05 → 06 holds end-to-end with no
manual path edits. The synthetic data's NaN-on-metadata behaviour is
exactly what we'd want Stage 2 to surface: it tells the analyst
"these 6 rows look identical on every key column and disagree by
> 10 µmol/kg in TA — investigate". Stage 2 is advisory, never
destructive.

---

## 9. Known limitations / things to revisit later

- **Pivot edge case.** `add_conflict_annotations` calls
  `consistency_df.pivot_table(...)` with `index=keys_used`. If
  `keys_used` has length 1 (rare in practice — `replicate_group_keys`
  has five entries by default), the pivot reshape is slightly
  different. The current code handles it through the `_new` column
  suffix-and-merge pattern, but the path is not exercised by the
  smoke test. Worth a targeted test if you ever run with
  `replicate_group_keys = ["station_id"]` only.
- **`make_column_inventory` overlaps with `make_missingness_table`.**
  The Stage 2 version adds `n_unique_nonnull` and `example_nonnull`,
  which the `oa_common` version doesn't. They could be merged once a
  later stage wants the richer inventory; for now, Stage 2 has its
  own.
- **`replicate_mean_vars` is a *whitelist*.** Adding a new numeric
  field to Stage 1B and expecting Stage 2 to aggregate it requires
  updating `STAGE2_DEFAULTS["replicate_mean_vars"]` or supplying a
  config override. Intentional: silent inclusion of every numeric
  column would aggregate things you don't want aggregated (e.g. an
  index column).
- **The first-value rule for non-numeric columns** picks whichever
  row sorts first in the group's natural order. For metadata that
  *should* be identical across a replicate group, the consistency
  table will surface any disagreement; for free-text fields, it
  might be worth recording multiple values. Future work.
- **No version pinning yet.** A `requirements.txt` will land with the
  later notebooks.
