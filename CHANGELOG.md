# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-07-27

### Fixed

- **Standardized output could silently remain stale.** Batch conversion
  skipped any existing output without checking whether it was still current.
  Because a trailing IBGE revision date is stripped from the output name,
  `PNADC_012012_20250815.zip` and `PNADC_012012_20260701.zip` both produce
  `PNADC_012012.parquet`, so a corrected release was skipped and the previous
  revision's data was kept with no warning. Conversion now records a
  fingerprint of its inputs and options, and reconverts whenever the source
  changes (including replacement under the same filename), the dictionary
  changes, `--columns` or `--all-string` changes, or the package version
  changes. Up-to-date outputs are still skipped, so routine re-runs stay
  cheap.
- **Revised IBGE dictionaries were not reparsed.** A parsed layout was reused
  whenever its JSON file existed, so a re-issued dictionary left the stale
  layout in place and every subsequent conversion used the wrong column
  positions. Layouts now record the dictionary's SHA-256 and are reparsed
  when it changes. `Repository.update()` therefore picks up revised
  dictionaries without needing an explicit force flag.
- Test suite failed on Windows CI runners. `tempfile` can return an 8.3 short
  path (`RUNNER~1`) that `init_repository` resolves to its long form, which a
  repository test compared without resolving.

### Changed

- Provenance sidecars are named after the output rather than the source
  (`PNADC_012012.parquet.provenance.json`), so each output has exactly one
  record. Sidecars written by earlier versions are still read, so an existing
  archive is not reconverted in full on upgrade.
- Provenance `schema_version` is now 2 and carries a `fingerprint` block.

### Added

- `tests/test_update_paths.py` covering the maintenance scenarios: unchanged
  inputs, a revised release mapping to an existing output name, replacement
  under the same filename, a revised dictionary, changed column selection,
  changed `--all-string`, and independent tracking of CSV and Parquet.

## [0.2.0] - 2026-07-27

### Added

- `pnadc init` creates a portable repository skeleton with a configuration
  whose paths are relative to itself, so a repository can live anywhere.
- `Repository` class providing a stable Python API (`sync`, `catalog`,
  `standardize`, `update`) over the same operations as the CLI.
- CSV as a batch output format: `--format csv` on `convert-many` and
  `update`, written to the configured `csv` directory.
- `--columns` on `convert`, `convert-many`, and `update` keeps only the named
  layout variables, cutting conversion time and output size for wide
  quarterly layouts.
- Guides under `readme/` covering installation, configuration, usage,
  Python/R access, maintenance, and compatibility.

### Fixed

- `Anual/Microdados` is two unrelated IBGE products sharing one URL tree
  (`Visita` per-interview data and `Trimestre` per-topic supplements). They
  are now detected separately, so a dictionary from one can no longer be
  matched to microdata from the other.
- `parquet_dir` and `csv_dir` default to directories under the archive root
  rather than beside it, matching the documented repository layout.

### Changed

- Renamed the distribution from `pnadc-https` to `pnadc`.
- `archive` is the shared repository root; `originals/` and `metadata/` live
  directly under it, alongside `parquet/` and `csv/`.

## [0.1.0]

### Added

- Initial release: HTTPS synchronization of the IBGE PNAD Contínua quarterly
  and annual Microdados trees, incremental manifest, safe ZIP extraction,
  `.xls`/`.xlsx` dictionary parsing, metadata catalog, streaming fixed-width
  conversion to Parquet, and person-panel construction.

[Unreleased]: https://github.com/amaciente/pnadc-https/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/amaciente/pnadc-https/releases/tag/v0.3.0
[0.2.0]: https://github.com/amaciente/pnadc-https/releases/tag/v0.2.0
