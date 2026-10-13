# Import capabilities and validation matrix

The generic text importer is implemented. Initial vendors are Thermo Scientific and Agilent;
initial detectors are HPLC RID, UV, and pulsed amperometric PAD. Acquisition/CDS
software and file versions matter as much as the hardware brand.

| Input | Priority | Status / evidence needed |
| --- | --- | --- |
| CSV, TSV, TXT sampled time/signal | First slice | Implemented; explicit mapping, headers, units, locale/encoding controls; synthetic fixtures tested |
| PNG/JPEG/TIFF chromatogram pictures | Early single-trace phase | Planned; calibrated image recovery, not a native reader |
| AIA/ANDI netCDF, commonly `.cdf` | Early exchange adapter | Planned; schema sniffing and representative raw-data fixtures |
| Thermo Chromeleon ASCII/raw-data export | Initial vendor route | Planned; actual lab CDS version and example exports needed |
| Agilent OpenLab CSV/AIA raw-data export | Initial vendor route | Planned; exact export options and sample fixtures needed |
| Thermo proprietary native containers | Investigation | Extensions/versions unknown; do not promise parsing |
| Agilent proprietary native files/folders | Investigation | Extensions/versions unknown; do not promise parsing |
| PDF pages containing chromatogram images | Later candidate | Decide raster/vector extraction and page selection |
| mzML / MS-specific formats | Deferred | Not part of initial HPLC detector scope |

## Evidence and limits
[Agilent OpenLab 2.8 AIA help](https://openlab.help.agilent.com/2.8/en/mergedProjects/DataAnalysis/11015796363-1-54043206835275531-7.htm)
documents netCDF raw-data export. The
[OpenLab 3.0 installation guide](https://www.agilent.com/cs/library/usermanuals/public/CDS_v3.0_ClientAICGuide_en.pdf)
lists CSV raw-data export as well. These establish possible exchange routes, not
that ChromaKit supports the files or that the user's installation offers them.

[Thermo's Chromeleon 6.80 manual](https://documents.thermofisher.com/TFS-Assets/CMD/manuals/Man-Chromeleon-680-EN.pdf)
documents AIA and ASCII raw-data export. This is historical evidence; verify the
lab's current Chromeleon version before prescribing an export workflow. Some AIA
exports contain peak tables without sampled points; validate required content.

## Adapter acceptance
Record exact source software/version, detector/channel, anonymized fixture/license,
sniffing rules, supported metadata, units, and known limitations. Compare imported
sample counts, times, signals, and units with an independent vendor export/reference.
Test malformed/truncated inputs, locale variants, multi-channel files, and missing
metadata. Report partial support explicitly. Folder-based inputs need a clear
import entry point; compressed archives need safe extraction and size limits.

Native readers must be evaluated for documentation, licensing, platform constraints,
and maintainability. Prefer reliable exchange data while native support is developed.
Never treat a vendor report containing only peak areas as a full chromatogram.

## Generic text reader v2
Validated against synthetic comma/tab/semicolon/pipe/whitespace fixtures, optional
headers, additional columns, decimals, UTF BOMs, and explicitly chosen legacy encodings.
Imports one selected time/signal pair at a time. Preserves original coordinates,
normalizes known times to seconds internally, and records source hash and mapping.
Rejects malformed selected samples and unordered times without repair. Supports
up to 64 MiB/1,000,000 rows. These tests do not establish vendor-specific support.

Explicit Missing signal → Omit with gaps supports blank/NaN/NA/N/A signal entries.
All times are validated before omission; finite samples are preserved without
interpolation, internal missing runs split plotting/analysis, and missing endpoints
truncate the available trace. Source hash, original row count, policy and omitted
physical lines are retained. Infinity and malformed numeric text remain errors.
Auto headers recognize a leading commented time-column header with matching width,
including underscore time/unit names; generic comments remain comments. Pixel
visibility/interpolation flag columns remain in the source and are not automatically
used as quality masks. Digitized coordinate calibration must be reviewed by the user.
