# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/amaciente/pnadc/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/amaciente/pnadc/releases/tag/v0.2.0
