# Notebook 04 — Stage 1A: canonical schema and presence flags

Fourth notebook of the split. **First transformation stage on the
canonical-data critical path.** Reads `derived.csv` from Notebook 02,
resolves aliases to canonical column names, normalises unit and pH-scale
strings, flags out-of-range / missing / duplicate rows, and writes the
`analysis_ready.csv` that Stage 1B will read.

---

## 1. Role in the pipeline

```text
02_ta_ph_qc.ipynb
   └── <qc_out>/sheet_<x>/data/derived.csv
                              │
                              ▼
                  04_stage1a.ipynb            ◄── THIS NOTEBOOK
                     • alias resolution (canonical schema)
                     • normalise TA units + pH scale
                     • range / presence / duplicate flags
                     • staged.csv + analysis_ready.csv (+ Parquet)
                                                  │
                                                  ▼
                                       05_stage1b.ipynb → ... → 08_stage4
```

The original monolithic Stage 1A had two structural problems:

1. Its input path was hard-coded to a name (`<stem>__0__derived.csv`)
   that Notebook 02 no longer produces. That's the renamed file from
   the new Notebook 02 layout; we point `INPUT_CSV` at the new short
   path.
2. Its output filenames *also* accumulated the input stem
   (`<stem>__stage1a_staged.csv`), which is where the
   filename-explosion bug starts. We cut that here.

---

## 2. Inputs

| Item | Type | Notes |
|------|------|-------|
| `INPUT_CSV` | `.csv` | Output of Notebook 02. Each row is one sample / standard / CRM. |
| `CONFIG_PATH` *(optional)* | `.json` / `.yml` / `.yaml` | Override file. Deep-merges onto `oa_schema.DEFAULT_CONFIG`. Use to add new aliases or change range bounds without editing code. |

---

## 3. Outputs

```text
<OUT_DIR>/
    data/
        staged.csv              # every input col + canonical cols + flags
        staged.parquet
        analysis_ready.csv      # ◄── Stage 1B reads this
        analysis_ready.parquet
    reports/
        report.md
    logs/
        manifest.json
        effective_config.json   # DEFAULT_CONFIG deep-merged with CONFIG_PATH
        rename_audit.csv        # what alias resolved to what canonical col
        canonical_inventory.csv # which canonical cols are present / missing
        missingness.csv         # per-column missingness inventory
```

**Naming choices, and why** — same as Notebooks 01 / 02:

- Filenames are short, descriptive, role-based (`staged.csv`,
  `analysis_ready.csv`, `report.md`).
- Identity lives in the **parent folder** (`<OUT_DIR>/data/`,
  `<OUT_DIR>/logs/`), not repeated in every filename.
- **No nested `<stem>/` folder.** The original buried everything under
  `oa_stage1a_outputs/<input-stem>/...` so long input filenames
  produced long output paths. Now `<OUT_DIR>` is a flat root and the
  user picks it per run. This is the same separation-by-directory
  pattern that the JWST pipeline explicitly recommends: "use
  `output_dir` to place the results in a different directory instead
  of using `output_file` to rename"
  ([JWST input/output conventions](https://jwst-pipeline.readthedocs.io/en/latest/jwst/user_documentation/input_output_file_conventions.html)).
- **`analysis_ready` instead of `canonical`** for the user-facing
  filename. "Canonical" is technically accurate but tells the reader
  nothing about what to *do* with it. The Palantir Foundry pipeline
  guide phrases this as "Choose descriptive names…distinctive part
  first"
  ([source](https://www.palantir.com/docs/foundry/building-pipelines/development-best-practices)).
  Internally the code still uses the term "canonical" (it refers to
  the schema), only the filename changes.

---

## 4. How to run

### From Jupyter
1. Make sure Notebook 02 has produced `derived.csv` for the sheet you
   care about.
2. Open `04_stage1a.ipynb`.
3. Edit the parameters cell — at minimum, `INPUT_CSV` and `OUT_DIR`.
4. **`Kernel → Restart & Run All`.**

### From the command line (Papermill)

```bash
papermill 04_stage1a.ipynb runs/04_stage1a.run.ipynb \
    -p INPUT_CSV  "/path/to/<qc_out>/sheet_0/data/derived.csv" \
    -p OUT_DIR    "/path/to/oa_stage1a_outputs" \
    -p NO_PARQUET True
```

### Dependencies

`pandas` (required), `pyarrow` *or* `fastparquet` (optional, for Parquet),
`pyyaml` (optional, for YAML configs), `tabulate` (optional, for nicer
markdown tables — without it the report falls back to code blocks).

---

## 5. Parameters

### I/O
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `INPUT_CSV` | str | new Notebook 02 short path | The QC-corrected derived CSV. |
| `OUT_DIR` | str | `oa_stage1a_outputs` next to OneDrive workbook | Output root. |
| `CONFIG_PATH` | str / None | None | Optional .json/.yml/.yaml that deep-merges onto `DEFAULT_CONFIG`. |

### Stage 1A behaviour
| Name | Type | Default | Meaning |
|------|------|---------|---------|
| `DUPLICATE_KEYS` | str / None | None | Comma-separated override (e.g. `"sample_id,replicate_id,sample_date"`). Otherwise auto-chosen by `oa_schema.choose_duplicate_keys`. |
| `PRESERVE_ORIGINAL_COLUMNS` | bool | True | Copy aliases into canonical cols *and* keep originals. False = rename in place. |
| `NO_PARQUET` | bool | False | Skip Parquet writes (CSV-only). |
| `DRY_RUN` | bool | False | Plan everything, write nothing. |
| `PRINT_COLUMNS` | bool | False | Console previews instead of `display()`. |

---

## 6. What changed vs. the original monolithic notebook

| # | Change | Why |
|---|--------|-----|
| 1 | Lives in its own `.ipynb` instead of being cells 73–102 of a 254-cell monolith | Restart-and-run-all atomicity. |
| 2 | `cfg = SimpleNamespace(...)` → tagged `parameters` cell | Papermill convention. |
| 3 | All canonical-schema machinery moved to `oa_schema.py` | Centralised schema. Stages 1B / 2 / 3 / 4 all need the same names; defining them once means a new alias is a one-line edit in one file. The "canonical data model" pattern from enterprise integration ([reference](https://agility-at-scale.com/ai/architecture/canonical-data-model/)) and the Avro Schema-Resolution/Aliases convention ([Avro spec](https://avro.apache.org/docs/1.11.1/specification/)) treat aliases as the right way to handle column renames. |
| 4 | `RangePolicy` moved to `oa_policy.py` | The original notebook defined this dataclass **three times**, with **different fields each time** (Stages 1A, 1B, 4). That's a literal silent-overwrite bug — whichever cell ran last wins. Single-source-of-truth fixes it by construction. |
| 5 | Shared helpers (`die`, `utc_stamp`, `ensure_dir`, `sanitize_name`, `write_json`, `coerce_numeric`, `coerce_datetime`, `percent_missing`, `make_missingness_table`, `write_csv_and_parquet`, `md_table_from_df`, `first_existing`, `build_flag_summary`, `deep_update`) moved to `oa_common.py` | Pimentel et al. (2019): ~10 % public-notebook modularization rate ↔ low reproducibility. Single source of truth, no per-notebook redefinition. |
| 6 | **Bug fix** in `choose_duplicate_keys`: a candidate set is now "usable" only if every column exists **AND** has at least one non-NA value | The original chose the first set where all columns existed in `df`. But `apply_canonical_schema` creates every canonical column (NA-filled if no alias resolved), so the existence test was trivially true. Result: `[sample_id, replicate_id, sample_date, station_id]` was always chosen, all four NA, and pandas `duplicated(keep=False)` then flagged **every row** as a duplicate because all-NA tuples compare equal. End-to-end test confirms the fix correctly falls through to `[record_id]` for Notebook 02's output. |
| 7 | `fix_lattitude` flag removed | The misspelling `lattitude` is already an alias in `canonical_candidates["latitude_deg"]`. The flag was a separate, less-general mechanism that fired before alias resolution and risked column collisions. Dropping it relies on the canonical alias list, which is the proper home for this kind of mapping. |
| 8 | Output filenames are short (`staged.csv`, `analysis_ready.csv`, `report.md`) | JWST-style "identity in folder, role in filename". Stops the stem accumulation that the audit identified. |
| 9 | Nested `<stem>/` output subfolder removed | "Separate runs by directory, not filename" — explicit JWST recommendation. Users pick `OUT_DIR` per run; no automatic deep nesting. |
| 10 | Manifest records `parquet_written` per file and the error (if any) | Same as the original. Parquet failure is logged, not crashing. |
| 11 | `pyarrow` and `pyyaml` are optional | Missing them produces a clear `die(...)` with install instructions (for YAML) or a captured Parquet error in the manifest. |

---

## 7. Reasoning, citation-by-citation

1. **Avro Schema Resolution and Aliases** (Apache Avro spec). The reason
   we model `canonical_candidates` as `canonical_name -> [aliases]`. Avro
   treats column renames as a forward/backward-compatibility problem and
   solves it with explicit aliases; we do the same.
   <https://avro.apache.org/docs/1.11.1/specification/>

2. **Canonical Data Model (enterprise integration pattern)** — one
   schema, many sources, mappings recorded explicitly. The
   "Canonical Transform" stage is exactly what `apply_canonical_schema`
   implements.
   <https://agility-at-scale.com/ai/architecture/canonical-data-model/>

3. **Rule et al. (2019), Ten Simple Rules for Reproducible Research in
   Jupyter Notebooks**. R4 (modularize) → `oa_schema.py` / `oa_policy.py`
   extracted; R5 (parameterize) → `parameters` cell; R8 (record
   provenance) → manifest / rename audit / effective config.
   <https://arxiv.org/pdf/1810.08055>

4. **Pimentel, J. F. et al. (2019)**. Public-notebook modularization
   rate motivates extracting `oa_schema.py` and `oa_policy.py` *now*
   rather than later.
   <https://towardsdatascience.com/best-practices-for-writing-reproducible-and-maintainable-jupyter-notebooks-49fcc984ea68/>

5. **Papermill** — the `parameters`-tagged cell convention.
   <https://github.com/nteract/papermill>

6. **JWST input/output conventions**. Source of "separate runs by
   directory, not filename". The reason we removed the per-input nested
   subfolder.
   <https://jwst-pipeline.readthedocs.io/en/latest/jwst/user_documentation/input_output_file_conventions.html>

7. **Palantir Foundry, *Building pipelines***. "Descriptive names,
   distinctive part first, avoid cryptic abbreviations." Why
   `analysis_ready.csv` instead of `canonical.csv`.
   <https://www.palantir.com/docs/foundry/building-pipelines/development-best-practices>

8. **Ian Rose, *Working with Jupyter notebooks*** and **Russ Poldrack,
   *Better Code, Better Science***. Restart-and-run-all.
   <https://ian-r-rose.github.io/best-practices/notebooks.html>

---

## 8. Verification (smoke test)

End-to-end test in the sandbox against the real `derived.csv` Notebook 02
produced earlier. Result:

```
Source CSV       : <…>/test_qc_out2/sheet_0/data/derived.csv
Rows             : 14
Columns          : 25
Canonical actions: 7  (sample_tag→record_id, crm_or_sample→sample_type,
                       temp_lab→temperature_measurement_c,
                       ta_corrected_umolkg→ta_umol_kg,
                       ph_corrected_from_phstd→ph_observed,
                       ta_qc_status / phstd_status already present)
Duplicate keys   : ['record_id']    (correctly chosen)
Duplicates       : 0
Output cols total: 92
Output files     : 8 (CSV + Parquet missing because pyarrow not installed
                       — logged in manifest as expected)
```

The chain holds: Notebook 02 → derived.csv → Notebook 04 →
analysis_ready.csv with no manual path edits. Stage 1B (next) will
default to `<OUT_DIR>/data/analysis_ready.csv`.

---

## 9. Known limitations / things to revisit later

- **Parquet not exercised** in the sandbox test because `pyarrow` isn't
  installed in the test environment. On the real OneDrive setup it
  will be — the manifest's `parquet_errors` will be `None` and the
  `.parquet` files will appear next to the `.csv` files.
- **No automated round-trip test** that reads `analysis_ready.csv` back
  and re-asserts the canonical column order. Worth adding after Stage 1B
  lands so we have a real consumer.
- **`PRESERVE_ORIGINAL_COLUMNS=True` keeps the input columns alongside**
  the canonical copies. That's friendly for debugging but doubles the
  width of `staged.csv`. Set it to False once the alias resolutions
  are stable in your workbook.
- **`fix_lattitude=True` removed**: if your workbook depends on the
  misspelling alias and you also have a real `latitude` column that
  should *not* be overridden, the alias resolver will pick whichever
  appears first in `canonical_candidates["latitude_deg"]`. The audit
  CSV will show which one was used, so it's transparent rather than
  silent.
- **No version pinning yet.** A `requirements.txt` will land when more
  notebooks are in.
