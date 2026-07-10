# Duplicate-based precision assessment — methods

Draft methods text documenting how measurement precision is assessed from
duplicate samples, following the GOA-ON Ocean Acidification Cookbook (Data
QA/QC Guidelines) and Dickson et al. (2007), SOP 22 and 23. Adapt wording to the
thesis or target journal. Values in the worked example are specific to the
P4506 April cruise dataset.

---

## Precision statistic

Measurement precision was assessed from duplicate samples using the standard
estimator recommended by the Cookbook and by Dickson et al. (2007):

    precision = 2.2 x (SD / sqrt(n))

where SD is the pooled standard deviation of the duplicate pairs and n is the
number of pairs. The factor 2.2 corresponds to a two-sided coverage of the
duplicate distribution (SOP 22/23). For paired duplicates, each pair contributes
one degree of freedom; the pooled standard deviation is computed as the
root-mean-square of the within-pair standard deviations,

    SD_pooled = sqrt( mean( s_i^2 ) ),

with s_i the standard deviation of pair i. Precision was computed independently
for total alkalinity (TA), pH, and dissolved inorganic carbon (DIC).

## Duplicate type — field vs analytical

Two kinds of duplicates are distinguished because they quantify different
sources of variability:

- **Field duplicates** — two samples collected from the same site and depth on
  the same sampling occasion. These capture *total* measurement uncertainty:
  fine-scale spatial or temporal heterogeneity at the site, plus sample handling
  and preservation, plus analytical error. Field duplicates were the design used
  in this study.
- **Analytical duplicates** — a single sample split and analysed twice. These
  capture *analytical* error only (instrument and operator).

Because field duplicates additionally include environmental and handling
variability, their spread is expected to exceed that of analytical duplicates,
and the two are reported separately rather than pooled. The processing software
records which duplicate type each precision estimate represents so that the
figure is interpreted against the correct source of variability.

## Quality tier

Data quality was assessed against the **weather-quality** tolerance, appropriate
to the study objective of mapping the current state of the carbonate system
(Newton et al. 2015). Weather-quality tolerances used were 10 umol/kg for TA and
DIC and 0.02 for pH. The stricter **climate-quality** tolerances (approximately
1 umol/kg for TA, 2 umol/kg for DIC, 0.005 for pH), appropriate to long-term
trend detection, are reported for reference but were not adopted as the
acceptance criterion for this study.

## Duplicate pairing and control charts

Duplicate members were paired by a shared sample identifier and distinguished by
a replicate label (a/b). For each pair the absolute difference between members
was computed and plotted on a control chart against the weather-quality
tolerance, following the Cookbook's field-duplicate control-chart approach. This
provides a per-pair visual check of reproducibility across the sampling
programme and highlights individual pairs with anomalously large differences for
follow-up against field and bench records.

## Worked example and caveats (P4506 April cruise)

For the April cruise, precision was estimated from n = 10 field-duplicate pairs.
The pooled field-duplicate precision exceeded the weather-quality tolerance for
TA, pH and DIC, driven by a small number of pairs with large within-pair
differences (the largest TA difference was approximately 178 umol/kg), while
other pairs agreed closely (differences below 10 umol/kg). Two caveats apply and
are stated explicitly:

1. The number of pairs (n = 10) is at the lower end of what the Cookbook
   recommends for a robust precision estimate, so the figures are treated as
   indicative rather than definitive.
2. The pooled precision is sensitive to a few high-difference pairs. Because
   these are *field* duplicates, a large difference may reflect genuine
   small-scale heterogeneity at the site rather than analytical error; the
   anomalous pairs were flagged for review against field and laboratory records
   to distinguish real heterogeneity from sampling or handling artefacts before
   the affected sites are interpreted.

This precision assessment complements the accuracy assessment based on certified
reference materials (reference-material-corrected alkalinity with batch
acceptance limits), together providing the accuracy-and-precision QA/QC basis
recommended by the Cookbook.

## References

- Dickson, A.G., Sabine, C.L., Christian, J.R. (Eds.) (2007). Guide to Best
  Practices for Ocean CO2 Measurements. PICES Special Publication 3 (SOP 22, 23).
- Newton, J.A., Feely, R.A., Jewett, E.B., Williamson, P., Mathis, J. (2015).
  Global Ocean Acidification Observing Network: Requirements and Governance Plan.
- GOA-ON Ocean Acidification Cookbook, Data QA/QC Guidelines
  (oceanacidificationcookbook.org), updated September 2024.

(Confirm each citation against the source before submission.)
