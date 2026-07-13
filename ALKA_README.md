# Alka — quick start

Alka is a simple graphical launcher for the OA carbonate-chemistry pipeline. It
lets you run the full processing workflow, compute the carbonate system from
reference-material-corrected alkalinity, and see the quality-control results —
without editing config files or using the command line.

If you can pick a file and click a button, you can use Alka.

---

## What Alka does

1. You choose an input workbook (`.xlsx`) and an output folder.
2. You tick **Compute carbonate chemistry internally** (recommended) — this runs
   the pipeline's own PyCO2SYS calculation from RM-corrected total alkalinity, so
   the reported DIC / Ω / pCO₂ are consistent with the corrected TA.
3. You click **Run pipeline**.
4. When it finishes, Alka shows:
   - the **verdict counts** (PASS / REVIEW / FAIL) for the run;
   - a **duplicate-precision** summary (TA / pH / DIC) with the workings and a
     per-pair breakdown;
   - buttons to **open the output folder** and **open a figures notebook**
     pointed at this run's results.

The heavy lifting is done by the same, tested pipeline used on the command line —
Alka is a friendly front end, not a separate implementation.

---

## Requirements

- **Python 3.11** with the project installed (see the main project README).
- **Git Bash** (Windows) — the pipeline runs through `run_pipeline.sh`.
- For the "Open figures notebook" button: **JupyterLab**
  (`pip install jupyterlab`).

If you installed the project with `pip install -r requirements.txt`, these are
already in place.

---

## Launching Alka

From the project root, in your activated environment:

```
python -m oa_pipeline.alka.app
```

The Alka window opens. (On Windows, use the `.venv` Python, e.g.
`.venv\Scripts\python.exe -m oa_pipeline.alka.app`.)

---

## Using it, step by step

1. **Data → Input workbook:** click *Browse…* and pick your `.xlsx`
   (e.g. the cruise workbook, or a prepared provenance file).
2. **Data → Output folder:** click *Browse…* and pick where results should go
   (e.g. `data/processed`).
3. **Options → Compute carbonate chemistry internally:** leave this ticked
   unless you are deliberately supplying externally-computed chemistry.
4. **Advanced options** (optional): sheet index, skip-Parquet, include the
   viewer/review notebooks, or a dry run. Most users never need these.
5. Click **Run pipeline.** Progress streams in the log area.
6. When it finishes, read the **Results** panel:
   - **Verdicts** — how many sample rows passed, need review, or failed.
   - **Duplicate precision** — measurement reproducibility vs the
     weather-quality tolerance, with a *Show duplicate pairs* button revealing
     the per-pair differences behind the summary.
   - Hover the **ⓘ** next to "Duplicate precision" for an explanation of how the
     numbers are derived.
7. Use **Open output folder** to find `analysis_ready.csv` and the per-stage
   reports, or **Open figures notebook** to explore plots for this run.

---

## Understanding the results

- **Verdicts** come from the pipeline's audit of each sample row.
- **Duplicate precision** uses the GOA-ON Cookbook statistic
  (precision = 2.2 × SD/√n). "Above tolerance" is a data-quality finding to
  review, not a pipeline error — see `duplicate_pairs_panel_explained.md` and
  `duplicate_precision_methods.md` for the full explanation.
- The **carbonate calculation** settings (Lueker 2000; Dickson KSO₄; Lee 2010
  borate; Perez & Fraga KF; total pH scale) are pinned and validated against the
  reference CO2SYS-Excel workbook — see `carbonate_calc_design.md`.

---

## Troubleshooting

- **"bash not found"** — install Git Bash (Windows) and relaunch.
- **"Jupyter is not installed"** when clicking *Open figures notebook* — run
  `pip install jupyterlab`, or open the prepared notebook manually (Alka saves a
  copy named `figures_<timestamp>.ipynb` in your output folder).
- **The window looks cut off** — the whole window scrolls; use the scrollbar or
  mouse wheel to reach the results and log.
- **A run fails** — the log shows the error. Because the pipeline is the same one
  used on the command line, any command-line troubleshooting applies here too.

---

## For developers

Alka is a small, modular Tkinter package under `src/oa_pipeline/alka/`:

- `app.py` — assembles the window and wires the Run button (thin).
- `state.py` — all settings in one dataclass (no scattered globals).
- `config_writer.py` — turns GUI choices into pipeline config files.
- `runner.py` — adapter over the existing pipeline core; runs it in a thread.
- `results.py` — reads verdicts and precision from the run output.
- `panels/` — one file per UI section (input, options, results).
- `tooltip.py`, `scrollable.py`, `open_folder.py`, `figures.py` — small helpers.

Each piece has a single responsibility so problems are easy to localise. The
pipeline itself is never modified by Alka — it is reused as-is.
