# Implementation roadmap

Implemented: source-checkout launcher, reviewed text imports, baseline correction,
measured peak integration, constrained deconvolution, portable project save/reopen,
publication figure/result export, compound labels, calibrated image recovery,
external-standard linear calibration, reviewed text batches and compound libraries.
See [WORKFLOWS.md](WORKFLOWS.md) for exact supported behavior and validation limits.

## Next validation and refinements
- Native Windows visual/interaction validation and representative permitted lab fixtures.
- Vendor exchange/native format adapters with exact CDS versions and fixture evidence.
- Image deskew/perspective/log axes, difficult crossings, multi-trace tracing and OCR review.
- Label collision avoidance and richer presentation presets; compound matching review refinements.
- Expanded calibration QC, internal standards, uncertainty/LOD/LOQ with named validated methods.
- Standalone reusable batch recipes, sample-role/standard metadata and unattended processing.
- Project recovery/large-history performance and later version migration fixtures.
- Standalone desktop packaging, dependency license notices and release documentation.

Do not advertise these later refinements as implemented or infer chemical identity
from mathematical fits/retention windows. Existing CI and known-truth tests support
research development, not regulatory certification or universal instrument validation.
