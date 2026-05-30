# OA Pipeline — Input Data Dictionary

This document describes **what your input Excel workbook must contain** so the
pipeline tags rows correctly and the QC steps (TA CRM correction, pH-standard
correction, the QC plots) operate on the right data.

Everything here is taken directly from the current code — the alias map in
`src/oa_pipeline/schema.py`, the detection logic in
`src/oa_pipeline/qc_ta_ph.py`, the range bounds in `DEFAULT_CONFIG`, and the
certified-value file `configs/crm_certified_values.yaml`. If the code changes,
regenerate this document rather than editing it by hand.

---

## 1. The single most important rule: how rows are classified

This is the thing that most often goes wrong, and it is exactly the concern
that prompted this document. There are **two independent mechanisms**, and they
are not interchangeable.

### CRM rows (for TA correction)

A row is treated as a **CRM** (Certified Reference Material) when its
`sample_tag` **starts with the CRM tag prefix**, which defaults to `RM`
(matched case-insensitively, so `RM213_1`, `rm213_1` both work).

- The `crm_or_sample` / `sample_type` column value of `crm` is, by default,
  **only a secondary cross-check** — it is consulted *only if* you run
  Notebook 02 with `ALLOW_CRM_FLAG_COL = True` (the default is `False`).
- **Practical consequence:** if you label a row `crm` in the `crm_or_sample`
  column but name it `Batch213_1` (no `RM` prefix), the pipeline will **not**
  treat it as a CRM by default. It will fall through and be treated like an
  ordinary row. Always give CRM rows an `RM...`-style tag.

### pH-standard rows (for pH correction)

A row is treated as a **pH buffer standard** when its `sample_tag`
**starts with the pH-standard tag prefix**, which defaults to `tris`
(case-insensitive). Change it to `amp` or `bis` via `PHSTD_TAG_PREFIX` when you
run a different buffer.

### Sample rows (what ends up in the final analysis table)

A row is treated as a real **sample** when the `crm_or_sample` /
`sample_type` column equals `sample` (case-insensitive). Only sample rows
appear in the Stage 4 `analysis_ready.csv`; CRM and standard rows are used for
QC and then excluded.

### Recommended tagging convention

| Row kind | `sample_tag` should look like | `crm_or_sample` / `sample_type` |
|---|---|---|
| Sample | `S001`, `OA-2024-001`, anything **not** starting with `RM`/`tris` | `sample` |
| CRM (TA) | **`RM<batch>_<n>`**, e.g. `RM213_1` | `crm` |
| pH standard | **`tris_1`**, `tris_2` (or `amp_*`, `bis_*`) | `std` |

Tagging both consistently (correct prefix **and** correct column value) is the
safest practice: the prefix drives detection, and the column value drives the
sample subset and the optional cross-check.

---

## 2. Column names — canonical names and accepted aliases

The pipeline resolves your workbook's column headers to **canonical** names
using the alias map below. You may use **any** of the listed spellings; the
first match wins. Headers are whitespace-trimmed before matching.

> If two of your columns both resolve to the same canonical name with
> conflicting values, the pipeline stops with an error rather than guessing.

### Identity & station

| Canonical name | Accepted header spellings (aliases) |
|---|---|
| `record_id` | `record_id`, `sample_tag` |
| `sample_id` | `sample_id` |
| `cruise_id` | `cruise_id`, `Cruise`, `cruise` |
| `transect_id` | `transect_id`, `Transect`, `transect` |
| `station_id` | `station_id`, `Station`, `station` |
| `depth_m` | `depth_m`, `Depth`, `depth` |
| `sample_type` | `sample_type`, `crm_or_sample` |
| `collection_mode` | `collection_mode`, `mode_of_collection` |
| `replicate_id` | `replicate_id`, `replicate` |
| `sample_date` | `sample_date` |
| `latitude_deg` | `latitude_deg`, `latitude`, `lattitude`, `lat` |
| `longitude_deg` | `longitude_deg`, `longitude`, `lon`, `long` |

(`lattitude` — the common misspelling — is intentionally accepted.)

### Hydrography

| Canonical name | Accepted header spellings |
|---|---|
| `temperature_measurement_c` | `temperature_measurement_c`, `temp_measurement_c`, `temp_lab`, `temperature_lab_c` |
| `temperature_insitu_c` | `temperature_insitu_c`, `temperature_output_c`, `temp_output_c`, `temp_insitu`, `temperature_insitu` |
| `salinity` | `salinity`, `Salinity`, `sal` |
| `pressure_measurement_dbar` | `pressure_measurement_dbar`, `pressure_lab_dbar`, `sample_pressure_dbar` |
| `pressure_output_dbar` | `pressure_output_dbar`, `pressure_insitu_dbar`, `pressure_calc_dbar` |

### Carbonate chemistry

| Canonical name | Accepted header spellings |
|---|---|
| `ta_umol_kg` | `ta_umol_kg`, `ta_umolkg`, `ta_corrected_umolkg`, `ta_corrected`, `ta`, `TA` |
| `ph_observed` | `ph_observed`, `ph_corrected_from_phstd`, `pH_corrected_from_std`, `pH_lab`, `ph_lab`, `pH`, `ph` |
| `ph_calculated` | `ph_calculated`, `pH_calc`, `ph_calc` |
| `dic_calculated_umol_kg` | `dic_calculated_umol_kg`, `dic_measured_umol_kg`, `dic_umol_kg`, `dic_umolkg`, `dic_calc`, `DIC`, `dic` |
| `pco2_calc_uatm` | `pco2_calc_uatm`, `pco2_uatm`, `pCO2`, `pco2` |
| `co2aq_calc_umol_kg` | `co2aq_calc_umol_kg`, `co2aq_umol_kg`, `co2aq_umolkg`, `co2_aq_umol_kg`, `aqueous_co2_umol_kg` |
| `hco3_calc_umol_kg` | `hco3_calc_umol_kg`, `hco3_umol_kg`, `hco3_umolkg`, `bicarbonate_umol_kg` |
| `co3_calc_umol_kg` | `co3_calc_umol_kg`, `co3_umol_kg`, `co3_umolkg`, `carbonate_umol_kg` |
| `omega_calcite_calc` | `omega_calcite_calc`, `omega_ca` |
| `omega_aragonite_calc` | `omega_aragonite_calc`, `omega_ar` |
| `revelle_factor_calc` | `revelle_factor_calc`, `revelle_factor` |

> **Note on the carbonate species:** plain `CO2`, `HCO3`, `CO3` are **not**
> accepted as aliases — only the explicit `*_calc_umol_kg` / `*_umol_kg`
> spellings. This is deliberate: a bare `CO2` column is ambiguous (gas vs
> aqueous) and would silently corrupt the DIC species-sum check.

### Nutrients

| Canonical name | Accepted header spellings |
|---|---|
| `oxygen_umol_l` | `oxygen_umol_l`, `o2_umol/L`, `o2_umol_l`, `oxygen` |
| `nitrate_nitrite_umol_l` | `nitrate_nitrite_umol_l`, `no3_no2 uM/L`, `no3_no2_umol_l`, `nitrate_nitrite` |
| `phosphate_umol_l` | `phosphate_umol_l`, `po4 uM/L`, `po4_umol_l`, `phosphate` |
| `silicate_umol_l` | `silicate_umol_l`, `sio3 uM/L`, `sio3_umol_l`, `silicate` |
| `chlorophyll` | `chlorophyll`, `chl`, `chla`, `chlor_a` |

(per-kg variants `*_umol_kg` are also accepted; see the schema for the full list.)

### Units, scales, QC status columns

| Canonical name | Accepted header spellings |
|---|---|
| `ta_units` | `ta_units`, `ta_unit`, `TA_unit`, `TA_units`, `ta_corrected_unit`, `ta_corrected_units` |
| `ph_scale_observed` | `ph_scale_observed`, `pH_scale_observed`, `ph_scale`, `pH_scale` |
| `ph_scale_calculated` | `ph_scale_calculated`, `pH_scale_calc`, `ph_calc_scale`, `pH_calc_scale` |
| `ta_qc_status` | `ta_qc_status`, `TA_qc_status`, `ta_status` |
| `ph_qc_status` | `ph_qc_status`, `pH_qc_status`, `ph_status` |
| `phstd_status` | `phstd_status`, `pHstd_status`, `ph_std_status` |

---

## 3. Accepted *values* (not just column names)

### pH scale labels

The pipeline normalises pH-scale text to one of four canonical values. Accepted
input spellings (case-insensitive) and what they become:

| You may write | Normalises to |
|---|---|
| `total`, `TOTAL`, `tot`, `total scale`, `ph_total` | `total` |
| `seawater`, `SWS`, `sws`, `ph_sws` | `seawater` |
| `free`, `free scale`, `ph_free` | `free` |
| `nbs`, `NBS` | `nbs` |

**Important:** the pipeline's default accepted scale is **`total`** only
(`accepted_ph_scales = ["total"]`). Rows on another scale are flagged unless you
configure otherwise. Single letters like `t` or `f` are treated as ambiguous and
**not** auto-mapped — spell the scale out.

### TA and carbonate-species units

All of these normalise to the single canonical unit **`umol kg-1`**:

`umol/kg`, `UMOLKG`, `umolkg-1`, `µmol/kg`, `μmol/kg`, `micromol/kg`,
`umol kg-1`, `umol kg⁻¹`, and similar spacing/symbol variants.

Anything else (e.g. `mg/L`) is **passed through unchanged** and will raise a
unit-mismatch review flag downstream — which is the intended behaviour, not a
bug. Convert to µmol/kg before loading if you want a clean pass.

### sample_type / crm_or_sample values

| Value | Meaning |
|---|---|
| `sample` | a real sample — included in final analysis table |
| `crm` | certified reference material — used for TA correction, excluded from final |
| `std` | pH buffer standard — used for pH correction, excluded from final |

(matched case-insensitively. Remember §1: for CRM and std rows, the **tag
prefix** is what actually drives detection by default.)

---

## 4. Expected data types

| Column group | Type | Notes |
|---|---|---|
| `*_id`, `sample_tag`, `*_status`, `*_units`, `ph_scale_*`, `sample_type` | text | leave blank cells empty, not `"NA"`/`"none"` |
| `sample_date` | date / datetime | Excel date or ISO `YYYY-MM-DD`; parsed to UTC |
| `depth_m`, `latitude_deg`, `longitude_deg`, `pressure_*` | number | decimal degrees for lat/lon |
| `salinity`, `temperature_*` | number | salinity on PSS-78; °C |
| `ta_umol_kg`, `dic_*`, `co2aq_*`, `hco3_*`, `co3_*`, `pco2_*` | number | µmol/kg (pCO₂ in µatm) |
| `ph_observed`, `ph_calculated` | number | on the scale named in `ph_scale_*` |
| `omega_*`, `revelle_factor_*` | number | dimensionless |

Blank Excel cells, and the strings `""`, `" "` (whitespace), are all treated as
**missing**. Do not type `NA`, `N/A`, `none`, or `null` as placeholders — those
become literal text and will not be recognised as missing.

---

## 5. Plausible-range bounds (out-of-range flags)

Values outside these bounds are **flagged** (not deleted) and contribute to the
Stage 4 `range_flag` REVIEW reason. Defaults from `DEFAULT_CONFIG.range_policy`:

| Variable | Min | Max |
|---|---|---|
| Salinity | 0.0 | 42.0 |
| TA (µmol/kg) | 1000.0 | 3000.0 |
| pH | 7.0 | 9.0 |
| Depth (m) | 0.0 | 12000.0 |
| Latitude (°) | −90.0 | 90.0 |
| Longitude (°) | −180.0 | 180.0 |

Stage-level checks (`RangePolicy`) add more: temperature −2 to 40 °C, DIC 0–3500,
pCO₂ 0–10000 µatm, Ω 0–20. Override any of these via a stage config file.

---

## 6. Minimum required columns

The schema marks these groups as required (resolved via the aliases in §2):

- **identity:** `record_id`, `sample_id`, `sample_date`
- **station:** `cruise_id`, `transect_id`, `station_id`, `depth_m`, `latitude_deg`, `longitude_deg`
- **hydrography:** `temperature_insitu_c`, `salinity`
- **carbonate minimum (for TA + pH):** `ta_umol_kg`, `ph_observed`

A workbook missing items from the carbonate minimum can still run, but those
rows will not be analysis-ready.

---

## 7. CRM batches currently certified in the project

`configs/crm_certified_values.yaml` currently contains certified TA values for
Dickson CRM batches (transcribed from the NOAA OCADS Dickson batch table):

`180, 195, 200, 205, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220,
221, 222, 223, 224, 225`

Set `CRM_BATCH` in Notebook 02 to the batch your `RM` rows correspond to. If the
batch is not in the file, the pipeline **stops with a clear error** rather than
guessing — add your batch (with its certificate value and source) to the YAML
first. Always confirm the value against the certificate for **your** bottle lot.

---

## 8. Quick pre-flight checklist

- [ ] CRM rows tagged `RM<batch>_<n>` (e.g. `RM213_1`) **and** `crm` in `sample_type`.
- [ ] pH-standard rows tagged `tris_*` (or `amp_*`/`bis_*`) **and** `std` in `sample_type`.
- [ ] Sample rows have `sample` in `sample_type`.
- [ ] `CRM_BATCH` matches a batch present in `configs/crm_certified_values.yaml`.
- [ ] pH scale spelled out (`total`, not `t`); units in µmol/kg where applicable.
- [ ] Missing data left as blank cells, not `"NA"`/`"none"`.
- [ ] Dates as real dates or ISO `YYYY-MM-DD`.
- [ ] Column headers match an accepted spelling in §2 (or add your spelling to the schema config).
