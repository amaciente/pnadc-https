# Compatibility and methodology

## `pynad`

`pnadc` follows the same broad local-repository workflow as `pynad` 3.0.3:
obtain PNAD Contínua originals, interpret IBGE fixed-width layouts, create
analysis-ready files, and support longitudinal person linkage.

This implementation is not a byte-for-byte fork. Its deliberate differences
are:

- HTTPS directory discovery, suitable for networks that block FTP
- incremental manifests and atomic `.part` downloads
- Parquet as the recommended standardized format
- JSON layouts, catalogs, and per-file provenance
- explicit, portable repository configuration
- a simpler documented panel-linkage rule

Keep `pynad` when exact reproduction of its seven-category historical panel
classifier is a requirement.

## Official `PNADcIBGE` R package

The package adopts two useful interface principles:

- select variables before materializing data (`--columns` / `columns=`)
- preserve the variables needed for later design-aware analysis

There are two important boundaries:

1. `PNADcIBGE::pnadc_deflator()` applies official period-specific deflators.
   `pnadc` does not silently deflate income; users must apply and document the
   matching IBGE deflator.
2. `PNADcIBGE::pnadc_design()` creates an R survey design. `pnadc` creates
   transportable data files and preserves design variables, but it does not
   claim that ordinary dataframe calculations produce correct standard errors.

## Standardization contract

- Variable names are normalized to lowercase.
- Field positions and widths come from the cataloged IBGE dictionary.
- Numeric storage is inferred from documented field shape; `--all-string`
  provides a textual alternative.
- Output names remove trailing IBGE revision dates, while provenance retains
  the exact source archive.
- Annual `Visita` and `Trimestre` products are cataloged separately so their
  dictionaries are never mixed.

Always inspect the provenance sidecar and catalog when a variable definition
changes across years.

