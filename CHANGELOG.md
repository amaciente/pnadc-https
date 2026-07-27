# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Superseded population projections (`Projecoes_Anteriores`) are excluded by
  default. IBGE retains them so previously published figures can be
  reproduced; they are not current microdata and are 44% of the archive by
  size (15.9 GiB of 36.4 GiB). Pass `--include-superseded`, or set
  `exclude: []` in the configuration, to process them. The exclusion applies
  to cataloging and conversion as well as download, so copies already on
  disk are not silently converted.
- `exclude:` configuration key listing path fragments to ignore.
- Files already present at exactly the remote size are adopted into the sync
  manifest instead of being downloaded again. An archive whose manifest was
  lost, or was built before manifests existed, would otherwise be fetched in
  full. `sync` reports an `adopted` count.

- `tests/test_portable_metadata.py`, including a test that builds a
  repository, moves it, and checks that the catalog is byte-identical and
  still resolves without reconverting.
- CI publishes to PyPI when a GitHub Release is published, using Trusted
  Publishing, so no API token is stored in the repository. The build fails
  if the release tag disagrees with the version in the code, since a PyPI
  version number cannot be reused once uploaded.

### Fixed

- Annual dictionaries covering a span of years, named like
  `dicionario_PNADC_microdados_2012_a_2014_visita1`, were read as applying to
  2012 alone, so 2013 and 2014 microdata resolved to no dictionary and were
  never converted. The whole span is now expanded and recorded as `years` on
  each layout.
- **Derived metadata was not portable.** The configuration could always be
  moved, but the files generated beside the data could not. `catalog.json`
  recorded the absolute archive root, and provenance sidecars recorded
  absolute source, layout, and output paths, so a repository copied to
  another machine or drive described files that were no longer where it said
  they were. Every path is now relative to the repository root.
- **Stored relative paths used the host's separator.** A repository built on
  Windows recorded `originals\trimestral\...`, which is a single filename on
  Linux rather than three path components, so such a repository could not be
  read there at all. Paths in `catalog.json`, parsed layouts, provenance
  sidecars, the sync manifest, and the extraction state are now written with
  forward slashes, which both platforms accept.

### Changed

- `catalog.json` is schema version 2: the absolute `archive` key is gone,
  replaced by a `paths_relative_to` marker. Provenance is schema version 3
  and carries the same marker.
- Conversion freshness no longer depends on the package version. A dedicated
  `conversion_format_version` is compared instead, bumped only when a release
  changes what a conversion produces. Previously any release — including a
  documentation-only one — invalidated every output and forced a full
  reconversion of the archive.
- `convert_file()` accepts `root=` to record paths relative to a repository.
  Called directly without it, absolute paths are still written, since a
  standalone conversion has no repository to be relative to.
- GitHub Actions updated to `checkout@v7`, `setup-python@v7`, and
  `upload-artifact@v7`; the previous majors ran on a deprecated Node
  runtime.

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
