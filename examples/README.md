# Synthetic examples

`synthetic_uv.csv` is generated mathematically, not experimental data. It contains
2,401 evenly spaced observations over 20 minutes, five Gaussian components, a
sloping offset, and small deterministic sinusoidal variation. Use it to explore
importing/plotting; it does not validate a vendor format or chemical identification.

Import it through the app, confirm Time (min) and UV (mAU), and select UV as the
detector if desired. Comment lines are ignored and disclosed in the import preview.


`synthetic_overlaps.csv` contains 741 samples from 10.5–14.2 minutes and separate
synthetic red/blue signal columns in mAU. Each channel sums three normalized
Gaussian/EMG components, a linear baseline and deterministic small oscillations.
`synthetic_overlaps.truth.json` records the formulas and full component parameters.
Choose one signal column per import and review baseline correction before fitting.
These demonstrate broad shoulders, tails and a late bump; they do not identify
compounds or reproduce quantitative experimental observations from images.

All included examples are mathematically generated and distributed under the
repository MIT license. No user-supplied chromatograms, digitized traces, instrument
screenshots or other private laboratory data are included.
