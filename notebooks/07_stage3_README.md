# Notebook 07 — Stage 3: carbonate-system integrity checks

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


Seventh notebook of the split. **First stage with scientific QC** —
not data-engineering QC. Reads Stage 2's `enhanced.csv` and runs
row-wise internal-consistency checks of the carbonate chemistry: does
DIC balance with its species (CO₂(aq) + HCO₃⁻ + CO₃²⁻)? Does observed
pH agree with CO2SYS-calculated pH within tolerance? Are the pH scales
and units self-consistent?

---

## 1. Role in the pipeline

```text
06_stage2.ipynb
   └── <stage2_out>/data/enhanced.csv
                             │
                             ▼
                  07_stage3.ipynb           ◄── THIS NOTEBOOK
                     • re-resolve canonical aliases (defensive)
                     • add helper columns (sample_month, depth_round_m, lat/lon)
                     • DIC species-sum check
                     • pH best-vs-CO2SYS diagnostic
                     • scale + unit mismatch flags
                     • per-group QC summary
                     • write enhanced.csv + mismatch tables + report
                                                  │
                                                  ▼
                                          08_stage4.ipynb
```

**What Stage 3 does NOT do.** It still doesn't rebuild any best field.
The integrity checks surface inconsistencies; the analyst decides what
to do about them. Flags are advisory, never destructive.

---

## 2. Inputs

| Item | Type | Notes |
|------|------|-------|
| `INPUT_CSV` | `.csv` | Stage 2's `enhanced.csv`. Each row is one sample + Stage 2's grouping/replicate flags. |
| `CONFIG_PATH` *(optional)* | `.json` / `.yml` / `.yaml` | Deep-merges onto `oa_stage3.STAGE3_DEFAULTS`. |

---

## 3. Outputs

```text
<OUT_DIR>/
    data/
        enhanced.csv                      # ◄── Stage 4 reads this
        enhanced.parquet
    tables/
        carbonate_integrity_flags.csv     # ID cols + every flag (compact)
        qc_summary_by_group.csv           # per-(cruise,transect,station,depth,month) counts
        dic_species_mismatches.csv        # rows that failed DIC checks
        ph_diag_mismatches.csv            # rows that failed pH diagnostics
        column_inventory.csv
        canonical_presence.csv
        alias_resolution.csv
    reports/
        report.md
    logs/
        manifest.json
        effective_config.json
```

**What's in `enhanced.csv`?** Every column the input had plus:

- Helper columns: `sample_month`, `depth_round_m`, `lat`, `lon`,
  normalised `ph_scale_*_normalized`, normalised
  `*_unit_normalized`.
- Stage 2 carry-over: `flag_stage2_replicate_conflict_carried`,
  `flag_solver_unknown`, `flag_carbon_input_pair_unknown`.
- DIC checks: `flag_dic_unit_mismatch`, `flag_dic_nonpositive`,
  `flag_co2aq_negative`, `flag_hco3_negative`, `flag_co3_negative`,
  `flag_any_negative_species`, `flag_dic_inconsistent`,
  `flag_dic_inconsistent_robust`, plus diagnostics `dic_sum_species`,
  `dic_minus_species_sum`, `dic_species_rel_diff`, `dic_tol_used`.
- pH checks: `flag_ph_best_missing_scale_context`,
  `flag_ph_co2sys_missing_scale_context`, `flag_ph_scale_mismatch`,
  `flag_ph_diag_mismatch`, `flag_ph_diag_mismatch_strict`,
  `flag_ph_diag_mismatch_robust`, plus diagnostic
  `ph_best_minus_ph_co2sys`.
- Roll-ups: `flag_any_carbonate_issue`,
  `flag_any_carbonate_issue_strict`.
- Per-group counts (joined from `qc_summary_by_group.csv`): `n_rows`,
  `n_dic_inconsistent`, `pct_dic_inconsistent`, etc.

---

## 4. How to run

### From Jupyter
1. Make sure Notebook 06 (Stage 2) has produced `enhanced.csv`.
2. Open `07_stage3.ipynb`.
3. Edit the parameters cell — at minimum, `INPUT_CSV` and `OUT_DIR`.
4. **`Kernel → Restart & Run All`.**

### From the command line (Papermill)

```bash
papermill 07_stage3.ipynb runs/07_stage3.run.ipynb \
    -p INPUT_CSV  "/path/to/oa_stage2_outputs/data/enhanced.csv" \
    -p OUT_DIR    "/path/to/oa_stage3_outputs" \
    -p CONFIG_PATH "/path/to/tight_thresholds.yaml"
```

### Dependencies

`pandas` (required), `pyarrow`/`fastparquet` (optional), `pyyaml`
(optional), `tabulate` (optional).

---

## 5. Parameters

### I/O
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `INPUT_CSV` | str | new Stage 2 short path | Stage 2's `enhanced.csv`. |
| `OUT_DIR` | str | `oa_stage3_outputs` next to OneDrive workbook | Output root. |
| `CONFIG_PATH` | str / None | None | Optional override file. |

### Stage 3 behaviour
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `DEPTH_ROUND_DECIMALS` | int | 1 | Rounding for `depth_round_m` if it isn't already in the input. |
| `NO_PARQUET` | bool | False | Skip Parquet writes. |
| `DRY_RUN` | bool | False | Plan everything, write nothing. |

### Important config keys (override via `CONFIG_PATH`)

- `thresholds.dic_abs_tol` (default `10.0` µmol/kg) — absolute floor
  for the DIC species-sum check. Matches GOA-ON "weather" precision.
- `thresholds.dic_rel_tol` (default `0.010`) — relative ceiling
  (1 % of DIC). The check uses `max(abs_tol, |DIC|*rel_tol)`.
- `thresholds.ph_diag_tol` (default `0.10`) — maximum
  `|ph_best - ph_co2sys|`. Intentionally loose; tighten to `0.02`
  for cruise-grade datasets (matches GOA-ON "weather" pH precision).
- `thresholds.dic_mad_k`, `thresholds.ph_mad_k` (default `3.5`) — MAD
  multipliers for the robust-outlier variants.
- `qc_group_keys` — the grouping columns for the per-group summary.

---

## 6. What changed vs. the original monolithic notebook

| # | Change | Why |
|---|--------|-----|
| 1 | Lives in its own `.ipynb` (cells 169–208 of the original). | Restart-and-run-all atomicity. |
| 2 | `cfg = SimpleNamespace(...)` → tagged `parameters` cell. | Papermill convention. |
| 3 | **Default `INPUT_CSV` fixed.** The original pointed at `oa_stage2_outputs\stage2_enhanced.csv` (flat path with `stage2_` prefix); the refactored Stage 2 writes to `<stage2_out>/data/enhanced.csv`. | Fifth audit-flagged path bug fixed (after Stage 1A, 1B, 2). |
| 4 | All Stage 3 logic moved to `oa_stage3.py`: `CarbonateIntegrityThresholds`, `add_canonical_helper_columns`, `carbonate_integrity_checks`, `build_qc_summary`. | Ten Simple Rules R4. The original's cell 184 (carbonate-integrity check) is 12.7 kB; alongside the helper, threshold, summary, and report cells, the Stage 3 notebook was ~ 800 lines of mixed logic-and-glue. Now ~ 250 lines of orchestration. |
| 5 | Eleven helpers deleted from the notebook and imported from `oa_common.py` and `oa_stage2.py`. | The same `die` / `utc_stamp` / `write_json` / `deep_update` / `load_config` / `ensure_dirs` / `make_column_inventory` / `make_presence_table` / `materialize_canonical_aliases` redefinition pattern we cleaned up in every prior stage. |
| 6 | **`normalize_scale_text` and `normalize_unit_text` deleted from the notebook**, replaced by `normalize_ph_scale` (from `oa_schema.py`, lowercase canonical) and the new `normalize_carbonate_unit` (also in `oa_schema.py`, uppercase + ASCII-folded). | The original Stage 3's `normalize_scale_text` produced uppercase output (`"TOTAL"`); Stages 1A/1B's `normalize_ph_scale` produced lowercase (`"total"`). If both ran in one kernel, the case differed — silent inconsistency that broke nothing inside Stage 3 but would have confused any downstream consumer comparing across stages. Fix: one normaliser, one case (lowercase, matching the earlier stages). |
| 7 | **`robust_outlier_flags` deleted from the notebook** and imported from `oa_common.py`. | This was the *fourth* place in the original where the same MAD function was defined (after Stage 1A, Stage 2's earlier code, and the QC stage). Pimentel et al. (2019) call out exactly this kind of in-notebook redefinition as the dominant reproducibility hazard. |
| 8 | **`first_existing` extended in `oa_common.py`** to try alphanumeric-canonical matches (`"ph_co2sys"` → `"pH co2 sys"`). | Stage 3's `_canon` helper did this canonicalisation locally. Promoting it to `oa_common` means every stage gets the more-forgiving matching. No backwards-compatibility risk: finds more, never fewer. |
| 9 | `write_report` is now inline in the notebook (not a separate function). | The original had three `write_report` functions, one in each of Stages 2, 3, 4, with different signatures. Inlining the per-stage markdown removes the silent-overwrite hazard. |
| 10 | Output filenames are short: `enhanced.csv`, `carbonate_integrity_flags.csv`, etc. | JWST-style; same convention as Stages 02 / 04 / 05 / 06. |
| 11 | **Audit fix N-6:** the notebook now calls `assert_ph_scale_consistency(...)` (from `oa_pipeline.schema`) on the `accepted_ph_scales` it reads, checking it against the schema default before any pH integrity check runs. | The accepted-pH-scale invariant was previously declared independently in the schema, `cruise_grade_thresholds.yaml`, and `regional.yaml`, kept aligned only by hand-maintained "sync" comments. Mixing pH scales without a documented conversion corrupts carbonate-system calculations (Moras et al. 2023). The check turns that comment-only contract into an enforced guard that stops the run on disagreement. |

---

## 7. Reasoning, citation-by-citation

### Carbonate-system science

1. **Murray, *Ocean Carbonate Chemistry*** and **Wikipedia, "Dissolved
   inorganic carbon"**. The defining identity used by the DIC
   species-sum check:
   `DIC = [CO2(aq)] + [HCO3-] + [CO3(2-)]`. If all four are reported,
   they must balance.
   <https://en.wikipedia.org/wiki/Dissolved_inorganic_carbon>

2. **Millero, F. J. (1993), *The internal consistency of CO2
   measurements in the equatorial Pacific*, Mar. Chem. 44, 269–280**.
   Foundational reference for the pH-best-vs-calculated and DIC-species-sum
   internal-consistency tests. Stage 3 is implementing exactly this idea,
   row-by-row, with configurable thresholds.

3. **Bargrizan, S., Smernik, R. J., Mosley, L. M. (2020), *Constraining
   the carbonate system in soils via testing the internal consistency
   of pH, pCO2 and alkalinity measurements*, Geochem Trans 21**.
   Same concept, applied to soils — confirms that the
   internal-consistency approach is the standard cross-validation tool
   across the carbonate-system literature.
   <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7178931/>

4. **OCADS NDP-090 — Total Alkalinity Measurements**. Real-world
   example using `max(abs_tol, rel_tol * |DIC|)` as the inconsistency
   threshold. The defaults (10 µmol/kg / 1 %) come from this lineage.
   <https://www.ncei.noaa.gov/access/ocean-carbon-acidification-data-system/oceans/ndp_090/talk090.html>

5. **OCADS CO2SYS reference**. Source of the warning that four pH
   scales (total, seawater, free, NBS) are in active use and that
   comparing across scales without checking produces spurious
   mismatches. The reason `flag_ph_diag_mismatch_strict` requires
   matching scales before flagging the diagnostic.
   <https://www.ncei.noaa.gov/access/ocean-carbon-acidification-data-system/oceans/CO2SYS/co2rprt.html>

6. **Newton, J. A. et al. (2015), GOA-ON Plan**. "Weather" precision
   objectives (pH ± 0.02, TA ± 10 µmol/kg) underpin the default
   thresholds. Stage 3 inherits these from Stage 2's
   `replicate_sd_thresholds` and uses them here as integrity-check
   tolerances.
   <https://www.goa-on.org/documents/general/GOA-ON_plan_print.pdf>

7. **Iglewicz & Hoaglin (1993), *How to Detect and Handle Outliers***.
   The MAD-based robust-outlier rule used by the `*_robust` variants of
   the DIC and pH checks. Imported once from `oa_common.py` instead of
   being redefined here for the fourth time.

### Refactoring rationale

8. **Rule et al. (2019), Ten Simple Rules for Reproducible Research in
   Jupyter Notebooks** — R4 (modularize → `oa_stage3.py`),
   R5 (parameterize → `parameters` cell), R8 (provenance →
   `manifest.json` + `effective_config.json` + per-table audit CSVs).
   <https://arxiv.org/pdf/1810.08055>

9. **Pimentel et al. (2019)**. Empirical motivation for not redefining
   the eleven helpers, the MAD function, and the unit/scale
   normalisers per stage.
   <https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/>

10. **Papermill** — the `parameters`-tagged cell convention.
    <https://github.com/nteract/papermill>

11. **JWST input/output conventions**. "Use `output_dir` to place the
    results in a different directory instead of using `output_file` to
    rename." Why `OUT_DIR` is flat with short filenames.
    <https://jwst-pipeline.readthedocs.io/en/latest/jwst/user_documentation/input_output_file_conventions.html>

---

## 8. Verification (smoke test)

End-to-end test in the sandbox against the actual `enhanced.csv`
Notebook 06 produced. Result:

```
Rows loaded         : 6
Columns             : 147 -> 149 (after Stage 3 additions, plus per-group
                                  counts merged from qc_summary)

DIC columns present : True (all four NaN in this dataset)
DIC checkable rows  : 0   (no row has all four DIC species)
DIC inconsistent    : 0

pH columns present  : True
pH checkable rows   : 0   (ph_co2sys is NaN for every row)
pH diagnostic mism. : 0

Flag rows surfaced  : 6 (every row, via `flag_ph_best_missing_scale_context`
                         and the Stage 2 replicate-conflict carry-over)
```

This is **exactly the behaviour we want** for the test data: the rows
have observed pH but no documented pH scale (`ph_scale_observed_normalized`
is NaN), so Stage 3 correctly says "you can't trust these pH values as
total / free / seawater / NBS without a scale label." Adding the scale
to a real dataset would silence the flag.

The chain integrity holds end-to-end: Notebook 02 → 04 → 05 → 06 → 07
with no manual path edits.

---

## 9. Known limitations / things to revisit later

- **The `_dic_block` / `_ph_block` helpers in `oa_stage3.py` are
  private but lengthy.** They could be split into smaller pieces
  (e.g. one function per flag) but that adds more imports and surface
  area without obvious clarity gain. Worth revisiting if the threshold
  logic grows.
- **No Bayesian / propagated-uncertainty version of the DIC check.**
  The current check treats the tolerance as a hard cliff. A more
  principled version would propagate the measurement uncertainties on
  TA, DIC, pH and use `PyCO2SYS.uncertainty` to compute a per-row
  expected residual. Future work; mention in Stage 4's plan.
- **The `qc_summary_by_group` merge can collide.** If `qc_df` has a
  column name that already exists in `df` (e.g. `n_rows` if Stage 2
  produced one), the merge uses `suffixes=("", "_grp")`. The original
  used the same approach. Worth a targeted test if any column name
  ever overlaps.
- **`flag_ph_best_missing_scale_context` is the *only* flag that fired
  on the smoke-test data.** A real dataset with populated scale columns
  would exercise the threshold and robust variants. Worth re-running
  this README's verification section against a real dataset before
  trusting the threshold defaults.
- **No version pinning yet.** A `requirements.txt` with pinned
  `pandas`, `pyarrow`, `pyyaml`, `tabulate` will land with Notebook 08.
