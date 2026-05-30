# Notebook 08 — Stage 4: analysis audit + PASS/REVIEW/FAIL verdict

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


**Eighth and final notebook of the split.** Reads Stage 3's `enhanced.csv`
and produces the analysis-ready CSV plus a per-row **verdict**
(`analysis_audit_status` = PASS / REVIEW / FAIL) with explicit reason
codes. This is the analyst-facing decision layer — the column an
analyst filters on downstream.

---

## 1. Role in the pipeline

```text
07_stage3.ipynb
   └── <stage3_out>/data/enhanced.csv
                            │
                            ▼
                 08_stage4.ipynb            ◄── THIS NOTEBOOK
                    • re-resolve canonical aliases (defensive)
                    • coerce + standardise types
                    • missing-key + duplicate detection (strict)
                    • range checks (long-format output)
                    • strict DIC species audit (gate, not diagnostic)
                    • PASS / REVIEW / FAIL classification + reason codes
                    • write analysis_ready.csv + all audit tables
```

**End of chain.** Nothing reads Stage 4's outputs except a human analyst
(or downstream modelling code that takes `analysis_ready.csv` and
filters on `analysis_audit_status`).

---

## 2. The severity ladder

```
        +-------------------------+
FAIL    | missing_key             |  ← any required key column null
        | stage3_strict_issue     |  ← Stage 3's strict flag was True
        | strict_dic_species_fail |  ← strict DIC species-sum failed
        | strict_dic_unit_mismatch|  ← DIC species units disagree
        | unknown_solver          |  ← carbonate_solver field is missing
        | unknown_input_pair      |  ← carbon_input_pair_used is missing
        +-------------------------+
              FAIL beats REVIEW
        +-----------------------------+
REVIEW  | duplicate_complete_key      |  ← duplicate row, all keys filled
        | range_flag                  |  ← out-of-range value
        | stage3_issue                |  ← Stage 3's non-strict flag was True
        | replicate_conflict_carried  |  ← Stage 2 flagged a replicate conflict
        | strict_dic_unit_missing     |  ← DIC species units not all known
        | dic_robust_issue            |  ← Stage 3 robust DIC outlier
        | ph_diag_issue               |  ← Stage 3 pH diagnostic mismatch
        | ph_diag_robust_issue        |  ← Stage 3 robust pH diagnostic outlier
        +-----------------------------+
              REVIEW beats PASS
        +------+
PASS    | (no flags above fired)
        +------+
```

**Flags are advisory — nothing is deleted.** The full row, every original
column, every flag column, and the verdict are all written to
`analysis_ready.csv`. The downstream filter is the analyst's choice:

```python
import pandas as pd
ar = pd.read_csv("analysis_ready.csv")
# Strict: only PASS rows
clean = ar[ar["analysis_audit_status"] == "PASS"]
# Loose: PASS + REVIEW, but log what's in REVIEW
loose = ar[ar["analysis_audit_status"].isin(["PASS", "REVIEW"])]
# Diagnostic: every row, with the verdict and reasons preserved
ar.groupby("analysis_audit_status").size()
```

This taxonomy is the **PASS / WARN / FAIL "quality gate" pattern**
documented across software-quality and statistical-process literature
(NDepend, SonarQube, UN/ABS *Data Quality Manual Part B*, testRigor
*Software Quality Gates*). We use REVIEW for the middle tier because
that is what an analyst actually does: review, decide.

---

## 3. Inputs

| Item | Type | Notes |
|------|------|-------|
| `INPUT_CSV` | `.csv` | Stage 3's `enhanced.csv`. |
| `CONFIG_PATH` *(optional)* | `.json` / `.yml` / `.yaml` | Deep-merges onto `oa_stage4.STAGE4_DEFAULTS`. |

---

## 4. Outputs

```text
<OUT_DIR>/
    data/
        analysis_ready.csv              # the final deliverable
        analysis_ready.parquet
    tables/
        column_inventory.csv
        missingness_top40.csv
        canonical_presence.csv
        alias_resolution.csv
        missing_key_rows.csv
        duplicates_by_keys.csv
        range_check_summary.csv         # (if range checks enabled)
        range_flags_long.csv            # (if range checks enabled, non-empty)
        dic_species_audit.csv           # (if DIC audit enabled, non-empty)
    reports/
        report.md
    logs/
        manifest.json
        effective_config.json
```

**What's in `analysis_ready.csv`?** Every column the input had, plus:

- Helper columns from `coerce_and_standardize`: `year`,
  re-derived `sample_month`, `lat`, `lon`, normalised
  `ph_scale_*_normalized`, normalised `*_unit_normalized`.
- DIC audit flags: `flag_dic_species_audit_strict`,
  `flag_dic_species_unit_mismatch_audit`,
  `flag_dic_species_unit_missing_audit`.
- `range_flag_count` (number of range violations on the row).
- Eleven `flag_audit_*` columns (the audit-side mirror of Stage 3's
  flags + the new Stage 4 checks).
- `analysis_audit_reason_fail`, `analysis_audit_reason_review`,
  `analysis_audit_reason_codes` (string columns, semicolon-joined).
- **`analysis_audit_status`** — the verdict column.

---

## 5. How to run

### From Jupyter
1. Make sure Notebook 07 (Stage 3) has produced `enhanced.csv`.
2. Open `08_stage4.ipynb`.
3. Edit the parameters cell — at minimum, `INPUT_CSV` and `OUT_DIR`.
4. **`Kernel → Restart & Run All`.**

### From the command line (Papermill)

```bash
papermill 08_stage4.ipynb runs/08_stage4.run.ipynb \
    -p INPUT_CSV  "/path/to/oa_stage3_outputs/data/enhanced.csv" \
    -p OUT_DIR    "/path/to/oa_stage4_outputs" \
    -p NO_RANGE_CHECKS False \
    -p NO_DIC_SPECIES_CHECK False
```

### Dependencies

`pandas` (required), `pyarrow` / `fastparquet` (optional), `pyyaml`
(optional), `tabulate` (optional).

---

## 6. Parameters

### I/O
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `INPUT_CSV` | str | new Stage 3 short path | Stage 3's `enhanced.csv`. |
| `OUT_DIR` | str | `oa_stage4_outputs` next to OneDrive workbook | Output root. |
| `CONFIG_PATH` | str / None | None | Optional override file. |

### Stage 4 behaviour
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `NO_RANGE_CHECKS` | bool | False | Skip range checks entirely. |
| `NO_DIC_SPECIES_CHECK` | bool | False | Skip the strict DIC audit. |
| `NO_PARQUET` | bool | False | Skip Parquet writes (CSV only). |
| `DRY_RUN` | bool | False | Plan everything, write nothing. |

### Important config keys (override via `CONFIG_PATH`)

- `duplicate_keys` — list of columns whose tuple identifies a duplicate.
  Stage 4's check is stricter than Stage 2's: every key must be
  non-null AND values must collide.
- `range_policy` — wider bounds than Stage 1A/1B (physically plausible
  vs typical seawater); the unified `oa_policy.RangePolicy` holds all
  fields, this stage's config populates the relevant ones.
- `dic_species_audit.abs_tol_umolkg` (default `5.0`) — tighter than
  Stage 3's `dic_abs_tol = 10.0`. This is a gate, not a diagnostic.
- `dic_species_audit.require_matching_units` (default `True`) — if
  the four species columns don't all share an allow-listed unit, the
  check is skipped and a unit-flag fires instead.
- `unit_equivalents` — allow-list of strings treated as equivalent
  to "umol/kg" for the strict audit (e.g. `UMOL/KG`, `UMOLKG`,
  `MICROMOL/KG`).

---

## 7. What changed vs. the original monolithic notebook

| # | Change | Why |
|---|--------|-----|
| 1 | Lives in its own `.ipynb` (cells 209–253 of the original). | Restart-and-run-all atomicity. |
| 2 | `cfg = SimpleNamespace(...)` → tagged `parameters` cell. | Papermill convention. |
| 3 | **Default `INPUT_CSV` fixed** — sixth and final audit-flagged path bug. The original pointed at `oa_stage3_outputs\stage3_enhanced.csv` (flat with `stage3_` prefix); refactored Stage 3 writes `<stage3_out>/data/enhanced.csv`. | All six original-audit path bugs (Stages 1A/1B/2/3/4 + Stage 2→3) now structurally fixed. |
| 4 | All Stage 4 logic moved to `oa_stage4.py`: the dataclasses, the four checks, the readiness classifier, the reason-code histogram. | Ten Simple Rules R4. The original cell 226 alone (the readiness classifier) is 4.8 kB. The notebook is now ~300 lines of orchestration; the module is the unit of test/version. |
| 5 | **`RangePolicy` is imported, not redefined** — the original's third stage redefinition with *different fields* than Stages 1A/1B. The unified `oa_policy.RangePolicy` now holds every field every stage needs (`sal`/`ta`/`ph`/`depth`/`lat`/`lon` from Stages 1A/1B, plus `temp`/`dic`/`pco2`/`omega` from Stage 4). Each stage's config block populates only the fields it uses. | This was the most concerning audit finding: silent-overwrite bug across three stages of one kernel. The unified dataclass fixes it by construction — there's nowhere for divergent fields to live. |
| 6 | Eleven generic helpers deleted and imported from `oa_common.py` / `oa_schema.py` / `oa_stage2.py`. | `die`, `utc_stamp`, `write_json`, `write_text`, `deep_update`, `load_config`, `ensure_dirs`, `_safe_str`, `normalize_unit_text`, `normalize_scale_text`, `resolve_first`, `materialize_canonical_aliases`, `ensure_required_columns`, `make_presence_table`, `make_column_inventory`. Pimentel et al. (2019) call out exactly this redefinition pattern as the dominant reproducibility hazard. |
| 7 | `normalize_unit_text` and `normalize_scale_text` deleted; the notebook now uses `normalize_carbonate_unit` and `normalize_ph_scale` from `oa_schema.py`. | Same case-divergence fix we applied in Stage 3: the original's Stage 4 normalisers produced UPPERCASE pH scales (`"TOTAL"`) while Stages 1A/1B produced lowercase. Now all stages produce the same canonical form. |
| 8 | `write_report` is now inline. | The original had three `write_report` functions (Stages 2, 3, 4) with different signatures in one notebook — silent-overwrite hazard. |
| 9 | Output filenames are short. Final deliverable is `analysis_ready.csv` (no `<long_stem>__analysis_ready_stage4.csv`). | JWST-style. Matches the user-facing name we introduced in Stage 1A's `analysis_ready.csv` — same naming choice both ends of the pipeline. |
| 10 | **One real bug fix in `oa_stage4.add_readiness_status`.** The original wrote `pd.to_numeric(out.get("range_flag_count"), errors="coerce").fillna(0)`. When the column was absent, `.get(...)` returned None, `pd.to_numeric(None)` returned a scalar `np.float64(nan)`, and `.fillna(0)` then crashed with `AttributeError`. Discovered while smoke-testing — the synthetic dataset never produced range flags, so the column was never created. The fix is a guarded conditional that produces a constant-zero Series instead. | Real bug, exposed only when a stage produces zero output (which the original's authors never tested for). |

---

## 8. Reasoning, citation-by-citation

### Quality-gate taxonomy

1. **NDepend, *Quality Gates and Build Failure***. The PASS / WARN /
   FAIL three-tier verdict pattern. "A Quality Gate can be seen as a
   PASS/FAIL criterion for software quality... red / yellow / green
   icons show Quality Gates status: fail / warn / pass." Stage 4's
   `analysis_audit_status` is the data-pipeline analogue.
   <https://www.ndepend.com/docs/quality-gates>

2. **UN/ABS (Australian Bureau of Statistics) Data Quality Manual,
   *Part B — Quality Gates in the Statistical Process***. The same
   pattern applied to statistical data products: "Actions associated
   with quality measures need to take into account the severity of
   the result on the end product or other quality measures and gates,
   in particular, if the threshold or tolerance levels are not met."
   The closest reference to what Stage 4 does — same concept, same
   problem domain.
   <https://unstats.un.org/unsd/methodology/dataquality/references/Australia_Part_B_Quality_Gates_in_the_statistical_process2.pdf>

3. **testRigor, *Software Quality Gates: What They Are & Why They
   Matter***. Confirms the canonical three-tier vocabulary: "Pass: all
   gate metrics are met... Warning: may not be met... Fail: must be
   resolved before production can proceed." We use REVIEW rather than
   WARN for the middle tier because that's what an analyst does.
   <https://testrigor.com/blog/software-quality-gates/>

### Carbonate-system science

4. **Newton et al. (2015), GOA-ON Plan**. "Weather" precision objectives
   (pH ± 0.02, TA ± 10 µmol/kg) again — Stage 4's `dic_species_audit`
   defaults to **tighter** (5 µmol/kg absolute) because it's a gate,
   not a diagnostic.
   <https://www.goa-on.org/documents/general/GOA-ON_plan_print.pdf>

5. **Millero (1993)** and **Wikipedia, *Dissolved inorganic carbon***.
   Same internal-consistency basis as Stage 3, but Stage 4 also requires
   matching units before attempting the check — silently comparing a
   `mmol/L` DIC to `µmol/kg` species would be worse than no check at all.

### Refactoring rationale

6. **Rule et al. (2019), Ten Simple Rules for Reproducible Research in
   Jupyter Notebooks** — R4 (modularize → `oa_stage4.py`),
   R5 (parameterize → `parameters` cell), R8 (provenance →
   `manifest.json` + reason-code histogram).
   <https://arxiv.org/pdf/1810.08055>

7. **Pimentel et al. (2019)**. The third redefinition of `RangePolicy`
   (with different fields again) was exactly the pattern this paper
   warns about; the unified `oa_policy.RangePolicy` removes it
   structurally.
   <https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/>

8. **Papermill** — `parameters`-tagged cell.
   <https://github.com/nteract/papermill>

9. **JWST input/output conventions**. "Use `output_dir` to place the
   results in a different directory instead of using `output_file` to
   rename." Why `OUT_DIR` is flat and the final deliverable is
   `analysis_ready.csv` (no stem accumulation).
   <https://jwst-pipeline.readthedocs.io/en/latest/jwst/user_documentation/input_output_file_conventions.html>

### Pipeline ethics

10. **DEV Community, *Why Binary CI/CD Quality Gates Fail at Scale***.
    The case for a three-tier verdict over PASS/FAIL: "This mirrors how
    release decisions are actually made by senior engineers — but in
    an automated, explainable way." The same logic applies to data
    pipelines: a binary "this row is bad" verdict throws away too much
    information; PASS/REVIEW/FAIL with reason codes lets the analyst
    decide.
    <https://dev.to/gaya3bollineni/why-binary-cicd-quality-gates-fail-at-scale-and-a-risk-based-alternative-1jf2>

---

## 9. Verification (smoke test)

End-to-end test in the sandbox against the actual `enhanced.csv`
Notebook 07 produced. Result:

```
Rows loaded         : 6
Columns             : 213 -> 232 (after Stage 4 additions)

Missing-key rows    : 6   (synthetic data has NaN sample_id/station_id/sample_date)
Duplicate rows      : 0   (with strict null-rejecting check; the
                           Stage 2 advisory had flagged them all, which
                           is the expected divergence)
Range variables     : 9 checked, 0 flagged
DIC strict failures : 0   (synthetic data has all-NaN DIC species)

Final verdicts:
  PASS   : 0
  REVIEW : 0
  FAIL   : 6  (every row -- correct)

Reason codes (per row, joined by ";"):
  missing_key
  replicate_conflict_carried
  stage3_issue
  stage3_strict_issue
```

The synthetic data correctly produces six FAIL rows. Each FAIL row
carries **four reason codes** explaining the tier: missing metadata
*and* unresolved Stage 3 issues *and* a Stage 2 replicate conflict.
An analyst looking at this output knows immediately the dataset needs
metadata cleanup before any analysis.

**Full pipeline chain verified:** Notebook 02 → 04 → 05 → 06 → 07 → 08
holds end-to-end with no manual path edits at the default parameters.

---

## 10. Known limitations / things to revisit later

- **`detect_duplicates` is strict by design.** A row with any null in
  a key column never gets the `duplicate_complete_key` flag (it gets
  `missing_key` instead). The Stage 2 advisory duplicate flag is the
  loose counterpart for rows that *look* like duplicates even with
  missing keys.
- **The unit-equivalents allowlist is hand-maintained.** New unit
  strings ("µmol·kg⁻¹" with a Unicode middle dot, etc.) need to be
  added to `unit_equivalents` or normalised to one of the existing
  entries by `normalize_carbonate_unit`. Worth a small test against
  a real dataset of typographical variants.
- **No verdict-stability check across runs.** Re-running Stage 4 on
  the same input should be deterministic, but we don't have a regression
  test that asserts it. Worth adding once the chain is stable on real
  data.
- **`status_REVIEW` is the most decision-loaded tier.** It's the one
  whose contents change when you change config thresholds. Treat
  threshold edits as scientific decisions, not parameter tweaks —
  loosening `dic_abs_tol` from 10 to 50 µmol/kg silently promotes
  rows from REVIEW to PASS.
- **No version pinning yet.** The next deliverable (when ready) is a
  top-level `README.md` tying the 8 notebooks together, a
  `requirements.txt`, and a Makefile/papermill-runner script.
