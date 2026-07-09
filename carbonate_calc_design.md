# Bringing the carbonate calculation into the pipeline — design & reasoning

This document explains, in detail, how the pipeline will compute the carbonate
system internally with **PyCO2SYS**, why each configuration choice is made, and
how it maps to your existing CO2SYS-for-Excel settings. The goal is that a
reviewer (or future-you) can read this and be convinced every number is defensible.

---

## 1. Why do this at all — the problem we are fixing

Right now the workflow is split:

1. You compute TA in an alkalinity spreadsheet (from titration).
2. You paste **raw** TA + measured pH into the **CO2SYS Excel** workbook, which
   computes DIC, pCO2, Omega_ar, Omega_ca, etc.
3. The pipeline ingests that already-computed chemistry and **then** computes the
   reference-material (RM) correction to TA, producing `ta_corrected_umolkg`.

The defect: the RM correction is computed **after** the chemistry, so the
chemistry (Omega_ar, DIC, pCO2) is based on **raw** TA, while `ta_best_umolkg`
in the final table is the **corrected** TA. The alkalinity and the carbonate
parameters next to it are therefore internally inconsistent. Confirmed on
J1-C1-N6: `ta_best_umolkg` = 2163.83 (corrected) but `omega_ar` = 3.02 was
computed from raw TA = 2173.60.

The GOA-ON Cookbook is explicit that TA should be **RM-corrected before it enters
CO2SYS** ("Measured value ... corrected using reference materials"). So the fix
is to make the correction happen upstream of the calculation, and to do the
calculation **inside the pipeline** so the two can never drift apart again.

### New order of operations

1. Ingest raw measured TA and measured pH (+ salinity, temperatures, pressure).
2. **RM-correct TA** (and, where applicable, tris-correct pH) — the pipeline
   already computes these corrections; we now apply them *before* the chemistry.
3. **Compute the carbonate system with PyCO2SYS** from corrected TA + pH.
4. Everything downstream (QC, Omega vs stress thresholds, plots) uses these
   internally-computed, correction-consistent values.

This also makes the pipeline genuinely reproducible end-to-end: no manual Excel
step, no copy-paste, and the exact constants are pinned in code.

---

## 2. The input pair — TA and pH (par types 1 and 3)

PyCO2SYS solves the system from any two known parameters. You measured **total
alkalinity** and **spectrophotometric pH**, so:

- `par1 = TA_corrected`, `par1_type = 1`  (type 1 = total alkalinity, umol/kg)
- `par2 = pH_measured`,  `par2_type = 3`  (type 3 = pH)

This matches your Excel workbook's "input pair = TA, pH" exactly. We do **not**
input DIC — DIC becomes an *output*, calculated by the solver, which is what you
want (and is why DIC appeared as a formula-derived column earlier).

Reasoning for using measured pH as the second parameter rather than measured DIC:
you have high-quality spectrophotometric pH, and TA+pH is the pair your lab and
the cookbook use. Keeping the same pair means the internal calculation is
directly comparable to your prior Excel results (a validation opportunity — see
section 7).

---

## 3. pH scale — Total scale (`opt_pH_scale = 1`)

Your spectrophotometric pH is reported on the **total scale** (this is standard
for m-cresol purple spectrophotometric pH, and matches your workbook's
"pH scale = total"). So:

- `opt_pH_scale = 1`  (1 = Total scale)

Why this matters: the pH scale defines what "pH" numerically means (which proton
species are counted). If we told PyCO2SYS the pH was on the free or seawater
scale when it is actually total, every derived quantity would be biased. Total
scale is both your measurement convention and the PyCO2SYS default, but we set it
explicitly so it is never ambiguous.

---

## 4. Carbonic acid constants K1, K2 — Lueker et al. 2000 (`opt_k_carbonic = 10`)

This is the single most important choice, and it is pinned to your existing work
and your research memory (CO2SYS configuration pinned to Lueker et al. 2000
K1/K2). In PyCO2SYS:

- `opt_k_carbonic = 10`  ->  **LDK00 = Lueker, Dickson & Keeling (2000)**

Reasoning:
- Lueker 2000 is the GOA-ON Cookbook's recommended parameterisation and the
  community default for open-ocean / shelf seawater in the valid range
  (2-35 degC, salinity 19-43, total scale, real seawater). Your Gulf of Guinea
  shelf samples (T ~17-30 degC, S ~32-38) sit inside this range.
- It is also the PyCO2SYS default, but we set `10` explicitly so the choice is
  self-documenting and cannot silently change if the library default ever moves.
  (Note: the library did briefly change defaults and then *reverted* to 10 for
  consistency with the best-practice guide — pinning protects us from that.)
- This is the same K1/K2 set your Excel workbook used, so internal results should
  match your prior Excel numbers to rounding (validation check in section 7).

---

## 5. Bisulfate (KSO4) and borate:salinity — Dickson + Lee (`opt_k_bisulfate = 1`, `opt_total_borate = 2`)

Your Excel settings were: KSO4 = Dickson; total boron = Lee et al. 2010. In
PyCO2SYS these are two separate options:

- `opt_k_bisulfate = 1`  ->  **D90a = Dickson (1990)** bisulfate dissociation.
- `opt_total_borate = 2`  ->  **LKB10 = Lee et al. (2010)** boron:salinity ratio.

Reasoning:
- **Dickson (1990) KSO4** is the standard, cookbook-recommended bisulfate
  constant; option `1` is D90a, which is Dickson 1990. (Do not confuse with the
  MATLAB-style combined `KSO4CONSTANTS` codes — in the modern `pyco2.sys`
  interface these are split into `opt_k_bisulfate` and `opt_total_borate`, which
  is cleaner and less error-prone.)
- **Lee et al. (2010) total borate** (`opt_total_borate = 2`, LKB10) is the
  current best-practice boron:salinity relationship and what your workbook used.
  The older Uppström 1974 (`1`, the PyCO2SYS default) is superseded for this
  work, so we must set `2` explicitly — this is a case where the default is NOT
  what we want, so pinning is essential.

The bisulfate and borate choices have only a small effect on final numbers, but
they affect pH-scale conversions of the constants, so matching your Excel setup
keeps the internal results directly comparable.

---

## 6. Hydrogen fluoride (KF) — Perez & Fraga 1987 (`opt_k_fluoride = 2`)

Your Excel settings used KF = Perez & Fraga 1987. In PyCO2SYS:

- `opt_k_fluoride = 2`  ->  **PF87 = Perez & Fraga (1987)**

Reasoning: option `1` is Dickson & Riley 1979 (the PyCO2SYS default); option `2`
is Perez & Fraga 1987, which is what your workbook used and what the cookbook's
default configuration specifies. Again the default is not what we want, so we set
`2` explicitly. The KF choice has a very small effect on results but we match it
for exact comparability.

---

## 7. Temperatures — the input/output convention (this is the subtle one)

This is where the earlier Stage 3 pH work and the cookbook all converge. PyCO2SYS
distinguishes **input conditions** (where the parameters were *measured*) from
**output conditions** (where you want the *results* reported):

- `temperature = temp_lab`      (the lab temperature at which pH was measured)
- `temperature_out = temp_insitu` (the in-situ temperature the sample experienced)
- `pressure = 0`                (samples measured at the surface in the lab, ~0 dbar)
- `pressure_out = pressure_insitu_dbar`  (in-situ pressure at collection depth)

Reasoning, straight from the cookbook and confirmed by our Stage 3 analysis:
- **pH is strongly temperature-dependent** (~ -0.016 pH/degC). It must be entered
  at the temperature it was *measured* (lab temp), because that is the condition
  under which the number is valid.
- TA is essentially temperature-independent (it is a conservative quantity), so
  its input temperature does not matter much — but we still pair it with the same
  input temperature for consistency.
- The **output** condition is in-situ temperature and pressure, because the
  saturation states (Omega_ar, Omega_ca) and pCO2 you care about biologically are
  the ones the organism actually experiences at depth. So we read the `_out`
  results (`saturation_aragonite_out`, `pCO2_out`, etc.).
- This is exactly the Tinput = lab / Toutput = in-situ convention your Excel
  workbook used, and it is why the measured-vs-calculated pH offset we found in
  Stage 3 was purely temperature — the calculated pH was the measured pH
  re-expressed at in-situ temperature. Computing internally with this convention
  makes that relationship exact and self-consistent.

**Which results we take:** the `_out` variants for the reported saturation states
and pCO2 (in-situ conditions), i.e. `saturation_aragonite_out`,
`saturation_calcite_out`, `pCO2_out`, `HCO3_out`, `CO3_out`, `CO2_out`,
`revelle_factor_out`. DIC is scale/temperature-independent as a total, so `dic`
is taken directly. We record BOTH input- and output-condition pH for the QC
cross-check.

---

## 8. Nutrients — silicate and phosphate (small but worth including)

TA has small contributions from silicate and phosphate. If you have nutrient
data (the prelim sheet has `sio3` and `po4` for some samples), we pass them:

- `total_silicate = sio3_uM`   (umol/kg; convert from uM if needed)
- `total_phosphate = po4_uM`

Reasoning: including nutrients removes a small bias in the alkalinity budget.
Where nutrients are missing, they default to zero, which is the same assumption
your Excel workbook made if you left them blank. So including them can only
improve accuracy, and never makes things worse. We will flag rows where nutrients
were assumed zero, for transparency.

NOTE on units: PyCO2SYS wants umol/kg. Your nutrient columns are labelled uM
(umol/L). At seawater density ~1.025 kg/L the difference is ~2.5%, which is
negligible for the tiny nutrient-alkalinity term, but we will convert properly
(divide by density) rather than ignore it.

---

## 9. Other settings — left at documented defaults

- `opt_buffers_mode = 1` (automatic differentiation; most accurate; gives the
  Revelle factor and buffer factors). Default and recommended.
- `opt_gas_constant = 3` (2018 CODATA). Default; negligible effect; the Excel
  workbook used an older R, but the difference is far below measurement noise.
  If you want *exact* Excel reproduction we can set `opt_gas_constant = 1`
  (DOEv2, pre-July-2020 CO2SYS). We will note this in the validation.
- `opt_pressured_kCO2 = 0` (no hydrostatic pressure correction to CO2 solubility;
  default; matches Excel).

---

## 10. Validation plan — prove the internal calc matches Excel

Before trusting the internal numbers, we validate against your existing Excel
output on the SAME (raw) TA, so any difference is purely solver-vs-solver, not
the correction:

1. Run PyCO2SYS on **raw** TA + pH with the settings above.
2. Compare its Omega_ar, DIC, pCO2 to your Excel workbook's values row-by-row.
3. Expect agreement to ~3-4 significant figures (tiny differences from gas
   constant / rounding are acceptable; large differences mean a setting is wrong).
4. Only once that matches do we switch the input to **corrected** TA and
   regenerate the final chemistry.

This two-step (match-then-correct) is the honest way to introduce the change: it
separates "did we reproduce the solver correctly?" from "what does the correction
do?", so we can attribute every difference to the right cause.

---

## 11. What changes in the final data

- `omega_ar`, `omega_ca`, `pco2`, `dic`, `hco3`, `co3`, `co2`, `revelle` will be
  recomputed from **corrected** TA, at **in-situ** output conditions.
- They will now be **consistent** with `ta_best_umolkg` (the corrected TA).
- Magnitude of change: the RM correction here is -9.77 umol/kg on ~2170 (~0.45%),
  which shifts Omega_ar by ~ -0.01 to -0.02. Small, but now correct and
  internally consistent.
- Provenance columns record: solver = PyCO2SYS vX.Y, the exact opt_* settings,
  the input pair, the temperature convention, and that TA was RM-corrected before
  calculation.

---

## 12. The separate, louder caveat — this RM batch is out of control

Independent of the software: 3 of your 7 batch-213 RMs exceed +/-20 umol/kg
(+50.5, -46.6, -53.9), spanning >100 umol/kg, with a kept-RM sd of ~10.4. The
cookbook says a difference > +/-20 means "re-evaluate your methods", not
"correct through it". So:

- The -9.77 correction rests on only 4 RMs that themselves scatter by ~+/-10.
- The pipeline should (and will be made to) raise a **batch-quality flag** when
  too many RMs are rejected, rather than silently correcting.
- This is a lab/method issue to raise with your supervisor: the TA for this batch
  is lower-confidence, and the correction is uncertain. The internal recalculation
  makes the data self-consistent, but it cannot fix an out-of-control RM batch.
  Document this honestly in the methods.
