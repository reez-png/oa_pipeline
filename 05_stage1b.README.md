# Notebook 05 — Stage 1B: best-source analysis fields

Fifth notebook of the split. Reads Stage 1A's `staged.csv`, picks the
**best available value per row** for each chemistry variable, records
*which source* each value came from, classifies sample vs CRM vs
standard rows, and produces the `analysis_ready_samples.csv` that Stage 2
reads.

---

## 1. Role in the pipeline

```text
04_stage1a.ipynb
   └── <stage1a_out>/data/staged.csv
                       │
                       ▼
          05_stage1b.ipynb            ◄── THIS NOTEBOOK
            • coalesce TA / pH / pCO2 / DIC across precedence lists
            • record per-row provenance (which column won)
            • normalise QC status, TA units, pH scale
            • classify is_sample_row
            • two analysis gates: safe_for_analysis_qc / _strict
            • write analysis_fields.csv (everything) +
              analysis_ready_samples.csv (sample-only subset)
                                  │
                                  ▼
                       06_stage2.ipynb → ... → 08_stage4
```

**Reads `staged.csv`, not `analysis_ready.csv`.** Stage 1A produces both:
`staged.csv` is the wider debug frame (original columns *plus* canonical
copies); `analysis_ready.csv` is the same rows in canonical export
order. Stage 1B needs access to the original alias columns
(`ta_corrected_umolkg` from Notebook 02 is in `ta_precedence`), so the
wider staged frame is the right input.

---

## 2. Inputs

| Item | Type | Notes |
|------|------|-------|
| `INPUT_CSV` | `.csv` | `staged.csv` written by Stage 1A. Each row is one sample / CRM / standard. |
| `CONFIG_PATH` *(optional)* | `.json` / `.yml` / `.yaml` | Deep-merges onto the union of `oa_schema.DEFAULT_CONFIG` and `oa_stage1b.STAGE1B_DEFAULTS`. |

---

## 3. Outputs

```text
<OUT_DIR>/
    data/
        analysis_fields.csv             # all rows + best fields + flags
        analysis_fields.parquet
        analysis_ready_samples.csv      # ◄── Stage 2 reads this
        analysis_ready_samples.parquet
    reports/
        report.md
    logs/
        manifest.json
        effective_config.json           # union(DEFAULT_CONFIG, STAGE1B_DEFAULTS) ∘ override
        missingness.csv
```

**What's in `analysis_fields.csv`?** Everything from `staged.csv` plus
the Stage 1B additions: for each variable family, a `*_best` value
column and a `*_source` provenance column; for TA units and pH scales,
a `_normalized` column and a `_source` column; per-variable `*_role`
flags ("measured" / "derived" / NA); a `is_sample_row` boolean;
provenance defaults (`carbonate_solver`, `carbon_input_pair_used`,
`preferred_*_for_analysis`); new range / scale / presence flags
computed on the **best** fields.

**What's in `analysis_ready_samples.csv`?** The same columns, filtered to
`is_sample_row == True`, plus the two analysis-gate booleans
(`safe_for_analysis_qc`, `safe_for_analysis_strict`) and two diagnostic
columns (`phstd_fail_diagnostic`, `ph_best_from_corrected`). **This is
what Stage 2 reads.**

---

## 4. How to run

### From Jupyter
1. Make sure Notebook 04 (Stage 1A) has produced `staged.csv`.
2. Open `05_stage1b.ipynb`.
3. Edit the parameters cell — at minimum, `INPUT_CSV` and `OUT_DIR`.
4. **`Kernel → Restart & Run All`.**

### From the command line (Papermill)

```bash
papermill 05_stage1b.ipynb runs/05_stage1b.run.ipynb \
    -p INPUT_CSV  "/path/to/oa_stage1a_outputs/data/staged.csv" \
    -p OUT_DIR    "/path/to/oa_stage1b_outputs" \
    -p CONFIG_PATH "/path/to/regional_config.yaml"
```

### Dependencies

`pandas` (required), `pyarrow` *or* `fastparquet` (optional, for
Parquet), `pyyaml` (optional, for YAML configs), `tabulate` (optional,
for nicer markdown tables).

---

## 5. Parameters

### I/O
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `INPUT_CSV` | str | new Stage 1A short path | Stage 1A's `staged.csv`. |
| `OUT_DIR` | str | `oa_stage1b_outputs` next to OneDrive workbook | Output root. |
| `CONFIG_PATH` | str / None | None | Optional override file. |

### Stage 1B behaviour
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `NO_PARQUET` | bool | False | Skip Parquet writes (CSV-only). |
| `DRY_RUN` | bool | False | Plan everything, write nothing. |
| `PRINT_COLUMNS` | bool | False | Console previews instead of `display()`. |

### Important config keys (override via `CONFIG_PATH`)

- `ta_precedence`, `ph_precedence`, `ph_co2sys_candidates`,
  `pco2_precedence`, `dic_precedence` — precedence lists for the
  best-source coalescing.
- `analysis_policy.phstd_fail_blocks_corrected_ph` — default False; if
  True, rows whose `ph_best` came from a pH-std-corrected source AND
  whose `phstd_status` was FAIL are excluded from `safe_for_analysis_qc`.
- `analysis_policy.require_pressure_for_strict` — default False; if
  True, missing `pressure_output_dbar` blocks `safe_for_analysis_strict`.

---

## 6. What changed vs. the original monolithic notebook

| # | Change | Why |
|---|--------|-----|
| 1 | Lives in its own `.ipynb` instead of being cells 103–132 of a 254-cell monolith | Restart-and-run-all atomicity. |
| 2 | `cfg = SimpleNamespace(...)` → tagged `parameters` cell | Papermill convention; lets the notebook run unattended from CI / a Makefile. |
| 3 | **Default `INPUT_CSV` fixed.** The original had a literal placeholder `your_stage1a_staged.csv` that no Stage 1A run ever produced — Stage 1B would die immediately on a clean install | Now points at the new short Stage 1A output `staged.csv`. This was bug #1 in the original audit. |
| 4 | All Stage 1B logic moved to `oa_stage1b.py`: best-source coalescing, status normalisation, provenance fields, presence/range/scale flags, analysis-ready subset | Ten Simple Rules R4 (modularize). The notebook is now ~ 200 lines of orchestration, not ~ 800 lines of logic-plus-glue. |
| 5 | `RangePolicy` and `policy_from_config` deleted from the notebook — imported from `oa_policy.py` | This was bug #4 in the original audit: the dataclass was being redefined in Stages 1A, 1B, and 4 with different fields. Single source of truth fixes it. |
| 6 | `normalize_ta_units`, `normalize_ph_scale` deleted from the notebook — imported from `oa_schema.py` | Identical copy-paste of Stage 1A's versions. |
| 7 | `coalesce_numeric_series`, `coalesce_string_series`, `existing_columns`, `value_counts_frame`, `safe_upper`, typed-empty-Series helpers moved to `oa_common.py` | They are generic SQL-COALESCE-with-provenance helpers, not Stage 1B-specific. Promoted to common so any later stage can use them. |
| 8 | `die`, `utc_stamp`, `write_text`, `write_json`, `ensure_dir`, `sanitize_name`, `deep_update`, `load_config`, `coerce_numeric`, `coerce_datetime`, `percent_missing`, `make_missingness_table`, `first_existing`, `write_csv_and_parquet`, `md_table_from_df`, `build_flag_summary` all imported (not redefined) | These were defined in `oa_common.py` already; the original notebook redefined every one of them at the top of Stage 1B. |
| 9 | Output filenames short and descriptive (`analysis_fields.csv`, `analysis_ready_samples.csv`, `report.md`) | JWST-style "identity in folder, role in filename". Same convention as Notebooks 02 / 04. |
| 10 | Nested `<stem>/` output subfolder removed | `OUT_DIR` is now flat. The original buried output under `oa_stage1b_outputs/<stem>/...` with `<stem>` already accumulated from Stage 1A → stems > 100 characters. |
| 11 | Provenance-defaults overwrite documented | Stage 1B's `provenance_defaults` deliberately *overwrite* Stage 1A's for the same column names (because by Stage 1B the preferred fields are the `_best` ones). The README and the module docstring both call this out so it's not surprising. |
| 12 | `safe_for_analysis_qc` / `safe_for_analysis_strict` semantics documented | The two-gate design is the original's; the README spells out what each gate excludes and the optional policy switches (`phstd_fail_blocks_corrected_ph`, `require_pressure_for_strict`). |

---

## 7. Reasoning, citation-by-citation

1. **SQL `COALESCE(...)` and the PySpark `coalesce` operation.** The
   `coalesce_numeric_series` / `coalesce_string_series` helpers are
   the data-engineering "first non-null wins" pattern, used everywhere
   from Snowflake to PySpark. PySpark's documentation describes the
   operation as: *"It allows data engineers to define a clear order of
   precedence for data sources, ensuring that the final output column
   contains the best available value for every record."*
   Our addition is the **per-row source-tracking layer** — pandas'
   `combine_first` does the value-level coalesce but does not record
   provenance.
   <https://spark.apache.org/docs/latest/api/python/reference/api/pyspark.sql.functions.coalesce.html>

2. **Row-level data lineage.** The `*_source` columns are a row-level
   provenance trail — the same pattern Coalesce-the-platform and dbt
   use to make column-level lineage auditable (Coalesce: *"This
   traceability is crucial. If you notice an error in a report, you
   need to know where that data came from"*). For our purposes the
   value is concrete: a downstream report can say "67 % of the analysis
   used pH from `pH_lab`, 33 % from `ph_corrected_from_phstd`" without
   anyone re-running anything.
   <https://coalesce.io/data-insights/what-is-data-lineage/>

3. **Rule et al. (2019), Ten Simple Rules for Reproducible Research in
   Jupyter Notebooks.** R4 (modularize) → `oa_stage1b.py`;
   R5 (parameterize) → `parameters` cell; R8 (provenance) →
   `manifest.json` + `effective_config.json` + per-row `_source` cols.
   <https://arxiv.org/pdf/1810.08055>

4. **Pimentel et al. (2019).** Empirical motivation for not redefining
   `RangePolicy` / `normalize_ta_units` / `die` / etc. once per stage.
   <https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/>

5. **Papermill** — `parameters` cell tag.
   <https://github.com/nteract/papermill>

6. **JWST input/output conventions.** "Use `output_dir` to place the
   results in a different directory instead of using `output_file` to
   rename." Why `OUT_DIR` is flat with no nested `<stem>/`.
   <https://jwst-pipeline.readthedocs.io/en/latest/jwst/user_documentation/input_output_file_conventions.html>

7. **Palantir Foundry, *Building pipelines***. Descriptive names; why
   `analysis_ready_samples.csv` instead of the original
   `<stem>__analysis_ready_samples.csv`.
   <https://www.palantir.com/docs/foundry/building-pipelines/development-best-practices>

---

## 8. Verification (smoke test)

End-to-end test in the sandbox against the actual `staged.csv`
Notebook 04 produced. Result:

```
Source CSV       : <…>/test_stage1a_out/data/staged.csv
Rows             : 14
Columns          : 94 → 132 (after Stage 1B's additions)

Sample rows (is_sample_row=True) : 6
Analysis-ready                   : 6
  safe_for_analysis_qc           : 6  (no FAILs in any QC column)
  safe_for_analysis_strict       : 0  (synthetic data lacks
                                       pH-scale / TA-units / pressure,
                                       which the strict gate requires)

TA precedence used : ['ta_umol_kg', 'ta_corrected_umolkg', 'ta']
pH precedence used : ['ph_observed', 'ph_corrected_from_phstd', 'pH_lab']

ta_best_source: ta_umol_kg (Stage 1A already promoted ta_corrected_umolkg)
ph_best_source: pH_lab     (synthetic dataset only has pH_lab, not ph_observed)

preferred_ta_for_analysis → "ta_best_umolkg"   (overwritten Stage 1A's "ta_umol_kg")
preferred_ph_for_analysis → "ph_best"          (overwritten Stage 1A's "ph_observed")
```

Chain integrity: Notebook 02 → Notebook 04 → Notebook 05 with no manual
path edits. Each stage's output is the next stage's input at the
default parameters.

---

## 9. Known limitations / things to revisit later

- **The provenance-defaults overwrite is permanent.** Once Stage 1B
  rewrites `preferred_ta_for_analysis` to `"ta_best_umolkg"`, the
  Stage 1A pointer to `"ta_umol_kg"` is gone from the frame. That's
  intentional, but it means re-running Stage 1B with a different
  config does not "undo" a previous run — the inputs are read fresh
  from `staged.csv`. Acceptable, but worth noting.
- **`ph_best_from_corrected` is computed from `ph_best_source`.** If
  someone adds a new pH-std-corrected source to the precedence list,
  they also need to add the same name to
  `analysis_policy.corrected_ph_source_names` or the diagnostic
  becomes incomplete. The default list catches the two names Notebook 02
  produces today.
- **No tests for the precedence resolution itself.** A small
  `tests/test_stage1b.py` that builds a frame where row 1 has only
  `ta_corrected_umolkg`, row 2 has only `ta_umol_kg`, and asserts
  `ta_best_umolkg` + `ta_best_source` per row would catch regressions.
  Worth adding once Stages 06–08 are in.
- **No automated comparison of `ph_best` vs `ph_co2sys`.** A natural
  follow-up audit: when both are present, how often do they disagree?
  Could land as part of Stage 4.
- **No version pinning yet.** A `requirements.txt` will land with the
  later notebooks.
