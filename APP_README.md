# Desktop App — running the pipeline without a terminal

`oa_pipeline_app.py` is a point-and-click launcher for people who would rather
not use a shell. It runs the **same** `run_pipeline.sh` as the command line, so
the results are identical — it just adds a file picker, an output-folder picker,
a progress log, and a verdict summary at the end.

## What it does

1. You pick your input `.xlsx` workbook.
2. You pick an output folder.
3. You click **Run pipeline**.
4. It executes notebooks 02 → 04 → 05 → 06 → 07 → 08 and shows progress live.
5. When finished it prints the final verdict counts (PASS / REVIEW / FAIL) and
   the path to `analysis_ready.csv`.

Optional checkboxes: skip Parquet (CSV only), include the viewer (NB 01) and
review (NB 03) notebooks, or do a **dry run** (shows the steps, writes nothing).

## Requirements (one-time setup)

The launcher window itself needs only standard Python — **Tkinter ships with
the official python.org installer** on Windows and macOS. On some minimal Linux
installs you may need: `sudo apt install python3-tk`.

The pipeline it runs needs the project installed once:

```bash
pip install -e ".[all]"
python -m pip install ipykernel
python -m ipykernel install --user --name python3
```

On Windows the pipeline runner needs **Git Bash** (install Git for Windows). The
app finds it automatically.

The app checks all of this on launch and tells you exactly what is missing in
the log, rather than failing with a traceback.

## How to start it

Put the file in the project root (the folder with `run_pipeline.sh`,
`notebooks/`, `src/oa_pipeline/`), then:

- **Windows:** double-click `oa_pipeline_app.py`, or run `python oa_pipeline_app.py`
- **macOS:** `python3 oa_pipeline_app.py`
- **Linux:** `python3 oa_pipeline_app.py`

It pre-fills the bundled `examples/example_data.xlsx` so you can do a first test
run immediately and confirm the four expected outcomes (S005 REVIEW; S007, S010,
S015 FAIL).

## Files

- `oa_pipeline_app.py` — the window (Tkinter). Run this.
- `oa_pipeline_app_core.py` — the logic (project discovery, command building,
  environment checks, verdict summary). No GUI dependency, unit-tested in
  `tests/test_app_core.py`.

## Before a real run

Read `DATA_DICTIONARY.md`. The single most common mistake is tagging CRM or
pH-standard rows incorrectly — the pipeline detects them by the `sample_tag`
prefix (`RM…`, `tris…`), not only by the `sample_type` column. The dictionary
spells out exactly what column names, values, units, and tags the pipeline
expects.
