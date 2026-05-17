# Contributing to oa_pipeline

Thanks for your interest in contributing. This pipeline is research
software — the code is small enough that any contributor can read it
end-to-end in an afternoon. Most of what follows is about *where to
look*, not about ceremony.

## Quick orientation

- **Top-level [README.md](README.md)** — what the pipeline does, the
  recommended folder layout, the eight-notebook chain at a glance, and
  the **"I want to change X — which file do I edit?"** lookup table.
  Start here.
- **Per-stage `<NN>_<name>.README.md`** — design rationale, citations,
  and "what changed vs. the original" tables for each notebook. Open
  the README next to its notebook when you want to know *why* a stage
  does what it does.
- **`tests/`** — a small pytest suite covering the load-bearing
  functions. Run with `pytest`.

## Setup for development

```bash
git clone <wherever this lives>
cd oa_pipeline

# Editable install with all optional deps + pytest
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Run the tests
pytest

# Run the full pipeline end-to-end on the example dataset
./run_pipeline.sh examples/example_dataset.xlsx outputs/
```

The `examples/example_dataset.xlsx` is a small synthetic workbook with
samples, CRMs, and pH standards covering the chain — runnable in
seconds.

## Where to add things

| Adding... | Goes in... |
|-----------|------------|
| A new canonical column alias | `oa_schema.DEFAULT_CONFIG["canonical_candidates"]` |
| A new range threshold | `oa_policy.RangePolicy` (defaults) and/or a stage-specific `STAGE*_DEFAULTS["range_policy"]` |
| A new stage-1B precedence rule | `oa_stage1b.STAGE1B_DEFAULTS` |
| A new replicate SD threshold | `oa_stage2.STAGE2_DEFAULTS["replicate_sd_thresholds"]` |
| A new carbonate-integrity check | `oa_stage3.carbonate_integrity_checks` (or new function in `oa_stage3`) |
| A new audit reason code | `oa_stage4.add_readiness_status` — extend `fail_def` or `review_def` |
| A new helper used by 2+ stages | `oa_common.py` |
| Tests for any of the above | `tests/test_<module_or_concept>.py` |

The top-level README has a fuller version of this table with examples.

## Style and conventions

- **Modules at the project root, no `src/`.** Top-level `oa_*.py` files;
  notebooks import them with `from oa_common import die`. Don't move
  modules into a subdirectory without coordinating with the EOI/VISS
  framing (the EOI explicitly positions a proper namespace package as
  phase 2 work).
- **No per-notebook redefinitions.** If a helper is used in two places,
  it belongs in `oa_common.py`. The original 254-cell monolith
  redefined the same helper in every section with subtly divergent
  versions — fixing that was the primary refactor and we should not
  drift back.
- **Flags are advisory, never destructive.** No stage should drop or
  overwrite rows. Add a `flag_*` column, write a long-format audit
  table, and let the analyst filter on `analysis_audit_status`.
- **Single tagged `parameters` cell per notebook.** Use the existing
  cells as templates. Defaults should point at the canonical output
  path of the previous stage.
- **Filename convention**: identity in folder, role in filename
  (`oa_stage<N>_outputs/data/enhanced.csv`, not
  `<input_stem>__stage<N>__enhanced.csv`). The JWST input/output
  convention.
- **Cite in the README, not in the code.** Per-stage `.README.md`
  carries the citations; module docstrings note the *concept* and
  point at the README.

## Pull-request workflow

1. **Open an issue first** for non-trivial changes (new stage, new
   threshold, schema change). The pipeline has scientific
   implications; agreeing on the design before the code is faster than
   reviewing a PR.
2. **One change per PR.** Easier to review, easier to revert.
3. **Update the relevant README.** If you change behaviour, update
   `<stage>.README.md` §6 ("What changed") and the top-level lookup
   table.
4. **Add or update a test.** Even one test that pins the new behaviour
   is enough — see `tests/` for examples.
5. **Run the full chain locally** (`./run_pipeline.sh examples/example_dataset.xlsx outputs/`)
   before opening the PR.

## Scientific changes

Threshold edits (range bounds, SD thresholds, DIC tolerances, pH
diagnostic tolerance) are scientific decisions, not parameter tweaks.
If you change a default in `STAGE*_DEFAULTS` or `RangePolicy`:

- Note the source in the README (which paper / GOA-ON tier / SOP
  recommends the new value).
- Run the smoke-test chain on the example dataset and check the
  PASS/REVIEW/FAIL counts. A change that silently promotes rows from
  REVIEW to PASS is a downgrade in QC strictness; a change that
  silently does the opposite is a downgrade in inclusiveness.
- Add a test that pins the new threshold value, so future-you can see
  the deliberate choice in the diff.

## Bug reports

Open an issue with:

- A minimal reproducer (input file or synthetic data + the command
  that failed).
- The `outputs/oa_<stage>_outputs/logs/manifest.json` of the suspect
  stage.
- The package versions: `pip freeze`.

The manifests record the input path, parameters, thresholds, package
versions, and row counts at each step — most "why did this flag/skip"
questions are answerable from them.

## Code of conduct

Be kind. Assume good faith. The pipeline is small enough that we can
afford to disagree well.

## License

By contributing you agree your contributions are licensed under the
[MIT License](LICENSE) that covers the rest of the project.
