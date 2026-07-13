# Setup guide — installing the OA pipeline and Alka on a fresh Windows machine

This guide takes you from a computer with nothing installed to a working
pipeline you can run through Alka. It assumes no programming experience. Follow
the steps in order; each ends with a **check** so you know it worked before
moving on.

Estimated time: 30–45 minutes, most of it downloads.

> Windows is assumed (it is what most users have). Notes for macOS/Linux are at
> the end.

---

## What you are installing, and why

Four things, each with a job:

1. **Python 3.11** — the language the pipeline is written in.
2. **Git** — to download the project and get updates.
3. **Git Bash** — a small terminal that can run the pipeline's script
   (`run_pipeline.sh`). It comes bundled with Git, so installing Git gives you
   both.
4. **The project itself** — the pipeline code and Alka.

You do not need to understand the code. You need these four present and working.

---

## Step 1 — Install Python 3.11

1. Go to https://www.python.org/downloads/windows/
2. Download the **Windows installer (64-bit)** for the latest **3.11.x** release.
   (Use 3.11 specifically — the project is built and tested against it.)
3. Run the installer. **IMPORTANT:** on the first screen, tick
   **"Add python.exe to PATH"** (a checkbox at the bottom). This matters — if you
   miss it, later steps fail.
4. Click **Install Now** and let it finish.

**Check:** open a new PowerShell window (press Start, type *PowerShell*, Enter)
and run:
```
python --version
```
You should see `Python 3.11.x`. If you see an error or a different version, the
PATH box was probably missed — re-run the installer and tick it.

---

## Step 2 — Install Git (includes Git Bash)

1. Go to https://git-scm.com/download/win and let the download start.
2. Run the installer. The defaults are fine — keep clicking **Next** until
   **Install**. (You do not need to change any options.)
3. Finish.

**Check:** in PowerShell, run:
```
git --version
```
You should see a version number. This also means **Git Bash** is now installed —
the pipeline needs it, and it is now present.

---

## Step 3 — Download the project

1. Choose a folder for your projects, e.g. `C:\Users\<you>\Projects`. In
   PowerShell:
```
cd $HOME
mkdir Projects
cd Projects
```
2. Download (clone) the repository:
```
git clone https://github.com/reez-png/oa_pipeline.git
cd oa_pipeline
```

**Check:** run `dir`. You should see folders like `src`, `notebooks`, `configs`,
and files like `run_pipeline.sh` and `requirements.txt`.

---

## Step 4 — Create an isolated environment and install

An isolated environment (a "virtual environment", `.venv`) keeps this project's
packages separate from the rest of your computer. Create it and install the
project into it.

```
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The last step downloads and installs everything (pandas, PyCO2SYS, matplotlib,
Jupyter, and the pipeline itself). It can take several minutes.

> If `Activate.ps1` gives a "running scripts is disabled" error, run this once,
> then retry the activate line:
> ```
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

**Check:** with the environment active (your prompt shows `(.venv)`), run:
```
python -c "import oa_pipeline, PyCO2SYS, pandas; print('install OK')"
```
You should see `install OK`.

---

## Step 5 — Launch Alka

```
python -m oa_pipeline.alka.app
```

The **Alka** window should open, and the log area should say
*"Environment looks good."*

**Check:** you see the Alka window with Data / Options sections and a
*Run pipeline* button. If it says there is an environment problem (e.g. "bash
not found"), see Troubleshooting below.

---

## Step 6 — Run it once on the example data

1. In Alka, click **Browse…** next to *Input workbook* and choose a workbook to
   process (e.g. your cruise file, or a provided example).
2. Click **Browse…** next to *Output folder* and choose where results go
   (e.g. make a folder called `output`).
3. Leave **Compute carbonate chemistry internally** ticked.
4. Click **Run pipeline.**

**Check:** the log streams progress, and when it finishes you see a **Results**
panel with PASS / REVIEW / FAIL counts and a precision summary. That means the
whole chain works.

You are now set up. From here, see **ALKA_README.md** for day-to-day use.

---

## Getting updates later

When the project is updated, get the latest version with:
```
cd $HOME\Projects\oa_pipeline
git pull
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

---

## Troubleshooting

- **`python` not recognised** — Python's PATH box was missed in Step 1. Re-run
  the Python installer and tick *"Add python.exe to PATH"*.
- **`Activate.ps1` is blocked** — run the `Set-ExecutionPolicy` line in Step 4,
  then retry.
- **Alka says "bash not found"** — Git (and Git Bash) is not installed or not on
  PATH. Reinstall Git (Step 2) and relaunch PowerShell.
- **"Jupyter is not installed" when opening figures** — run
  `python -m pip install jupyterlab` with the environment active.
- **The Alka window looks cut off** — it scrolls; use the scrollbar or mouse
  wheel.
- **Something else** — the log area shows the error text. Copy it when asking for
  help; it usually names the missing piece.

---

## macOS / Linux notes

The same four ingredients apply, with platform differences:

- **Python 3.11:** install via python.org, Homebrew (`brew install python@3.11`),
  or your package manager.
- **Git / bash:** macOS and Linux already have bash; install Git via Homebrew
  (`brew install git`) or your package manager.
- **Environment:** create and activate with
  `python3 -m venv .venv && source .venv/bin/activate`.
- **Everything else** (clone, `pip install -r requirements.txt`,
  `python -m oa_pipeline.alka.app`) is the same.
