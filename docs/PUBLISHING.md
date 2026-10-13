# Preparing the public GitHub repository

Public destination: [aalto-ema/chromakit](https://github.com/aalto-ema/chromakit),
under the user-selected MIT license. The user authorized creating this public
repository and pushing the prepared project on 2026-10-13. There was no local Git
history before this first publication. No tagged release or package upload is
included; the checklist below also applies to future publication work.

## Prepared files

- README with fresh-checkout macOS/Windows setup, implemented features and limits.
- MIT LICENSE and matching package metadata; copyright notice names ChromaKit contributors.
- Contributor and security-reporting guidance, bug/feature forms and PR template.
- GitHub CI for tests/lint on Linux, macOS and Windows and source/wheel build checks.
- Commit-pinned checkout/Python setup actions and read-only workflow permissions.
- Monthly dependency/action update proposals through Dependabot.
- Ignore rules for environments, caches, local agent/editor config, credentials,
  experimental data, screenshots and analysis outputs; cross-platform text settings.
- Synthetic examples with documented origin and overlap truth parameters.

The repository MIT license covers ChromaKit source and included synthetic examples.
Dependencies retain their own licenses; the current wheel does not bundle them.
Standalone app packaging and dependency-redistribution review remain future work.

## Before the first push

1. Choose the GitHub account/organization and repository name. The initial destination is `aalto-ema/chromakit`; package metadata and README
   contain its actual URLs. Maintainer handles/contact details are not invented.
2. Review the publication candidate: only source, tests, documentation, synthetic
   examples and configuration should be staged. Keep lab files/images under ignored
   `data/`, outputs under `outputs/` or `exports/`, and confidential data outside the
   checkout when possible. `.gitignore` does not remove files already committed.
3. Run the checks in CONTRIBUTING.md and build the distributions:

   ```sh
   python -m build
   python scripts/check_distributions.py dist
   ```

   Use an empty build-output folder if older artifacts are present. This script checks
   archive contents/metadata, not the behavior of the scientific application.
4. After initializing Git, inspect `git status --short`, `git diff --cached --stat`
   and `git diff --cached` before the initial commit. Check staged files for private
   paths, sample identifiers and credentials. Review any history imported from another
   checkout separately. Do not push the local `.venv` or build outputs.
5. Create the public repository and push the reviewed commit when ready. This is a
   separate action from preparing files. Add the real repository URLs to package
   metadata/README after the destination is known.
6. Enable private vulnerability reporting in repository settings, consistent with
   SECURITY.md. Confirm the repository's Actions and Dependabot settings, then wait
   for the first hosted CI run. Local checks cannot certify hosted Windows/Linux jobs.
7. Configure branch protection against the actual passing CI check names. Review
   dependence updates and numerical results before merging them.

## Release scope

Version 0.1.0 is an early development version, not a validated instrument-specific
release. Changes are recorded under Unreleased in CHANGELOG.md. Native Windows
and real vendor-format validation remain outstanding. Saving/reopening projects,
figure exports and built-in image extraction are not implemented. Do not advertise
those planned capabilities as available, or publish screenshots containing lab data.

For a later tagged release, repeat checks in a fresh environment, install the built
wheel independently of the checkout, smoke-test the launcher/entry point, update the
changelog and validate relevant native UI workflows. This repository does not contain
a package-upload or release-publishing workflow.

Action references: [actions/checkout](https://github.com/actions/checkout),
[actions/setup-python](https://github.com/actions/setup-python).
License text: [MIT license](https://choosealicense.com/licenses/mit/).
