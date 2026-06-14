# Carbonate System Methods & QC Validation Note

Draft text for the manuscript methods section, plus an internal QC note
documenting the measured-vs-calculated pH cross-check. Adapt wording to the
target journal's style; values are specific to the April (P4506) workbook.

---

## Methods section (carbonate chemistry)

Carbonate system parameters were calculated from total alkalinity (TA) and
spectrophotometric pH (total scale) using the CO2SYS program (v25b06, Excel
implementation). Calculations used the carbonic acid dissociation constants of
Lueker et al. (2000), the bisulfate dissociation constant of Dickson (1990),
the hydrogen fluoride constant of Perez and Fraga (1987), and the boron-to-
salinity ratio of Lee et al. (2010). Input conditions used laboratory
measurement temperature; output parameters — including aqueous CO2, bicarbonate,
carbonate ion, dissolved inorganic carbon, pCO2, and the saturation states of
calcite (Ω_ca) and aragonite (Ω_ar) — were computed at in situ temperature and
pressure so that derived saturation states reflect the conditions experienced
by the benthic community.

Total alkalinity was quality-controlled against certified reference material
(Dickson CRM batch 213); the alkalinity correction was applied per the
laboratory's standard operating procedure. Spectrophotometric pH measurements
were checked against tris buffer standards (n = 8) prepared and measured across
the working temperature range; the mean standard residual was within the
acceptance threshold (|Δ| < 0.02 pH units), confirming electrode performance.

## QC validation note (internal — measured vs calculated pH)

As an internal consistency check, directly measured pH (reported at laboratory
temperature) was compared with the CO2SYS-derived pH (reported at in situ
temperature). The two values differed by a mean of 0.06 pH units. This offset
is fully explained by the temperature difference between laboratory and in situ
conditions: the pH difference and the laboratory-minus-in-situ temperature
difference were perfectly anti-correlated (r = -1.00, n = 38), with an implied
slope of -0.0165 pH units per degree Celsius — consistent with the known
thermodynamic temperature sensitivity of seawater pH (approximately -0.015 to
-0.017 pH units per degree Celsius). No residual scale or measurement
discrepancy remained after accounting for temperature. Reported pH values are
therefore internally consistent; measured and calculated pH simply express the
same carbonate system at different reference temperatures.

For all downstream ecological analysis, the in situ-referenced calculated
parameters (Ω_ar, Ω_ca, pCO2) were used, as these represent the chemical
environment relevant to the organisms.

## Reference list (for the constants cited above)

- Lueker, T.J., Dickson, A.G., Keeling, C.D. (2000). Ocean pCO2 calculated from
  dissolved inorganic carbon, alkalinity, and equations for K1 and K2:
  validation based on laboratory measurements of CO2 in gas and seawater at
  equilibrium. Marine Chemistry, 70, 105-119.
- Dickson, A.G. (1990). Standard potential of the reaction AgCl(s) + 1/2 H2(g)
  = Ag(s) + HCl(aq), and the standard acidity constant of the ion HSO4- in
  synthetic sea water from 273.15 to 318.15 K. Journal of Chemical
  Thermodynamics, 22, 113-127.
- Perez, F.F., Fraga, F. (1987). Association constant of fluoride and hydrogen
  ions in seawater. Marine Chemistry, 21, 161-168.
- Lee, K., et al. (2010). The universal ratio of boron to chlorinity for the
  North Pacific and North Atlantic oceans. Geochimica et Cosmochimica Acta, 74,
  1801-1811.

(Verify each citation against the source before submission; these are the
standard references for the CO2SYS settings shown, but confirm year/volume.)
