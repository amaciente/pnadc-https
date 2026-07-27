# Updates, recovery, and safety

## Routine update

Start narrow and inspect:

```powershell
pnadc sync --config C:\data\pnadc\pnadc.yml `
  --survey trimestral --year 2026 --dry-run
```

Then run:

```powershell
pnadc update --config C:\data\pnadc\pnadc.yml `
  --survey trimestral --year 2026 --convert
```

Downloads are incremental. The manifest records HTTP size, ETag, and
Last-Modified metadata. Complete unchanged files are skipped.

## Interrupted downloads

An incomplete transfer remains as a `.part` file and is never accepted as an
original. Re-run the same sync command. Do not rename `.part` files manually.

## Rebuilding derived outputs

Original ZIP files are the preservation layer. Layout JSON, catalog entries,
Parquet, and CSV are reproducible derivatives. To intentionally replace a
derived conversion after a parser or dictionary change, rerun the relevant
command with `--force`. Keep the adjacent provenance JSON with the output.

## Pruning

`sync --prune` is the only operation that removes mirrored files no longer
listed by IBGE. It cannot be combined with year or quarter filters because a
partial remote view cannot prove that other files disappeared.

Back up originals and the `.pnadc` manifest before broad maintenance. Ordinary
sync, metadata, and conversion commands do not delete original microdata.

## Reproducibility

For a published analysis, retain:

- `pnadc --version`
- the YAML configuration with credentials or private paths removed
- each Parquet provenance sidecar
- `metadata/catalog.json` and the referenced layout JSON
- the exact analysis variable list and deflator/design method

