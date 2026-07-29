# Updates, recovery, and safety

Examples use `C:\data\pnadc` as the repository path; substitute your own.

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

## Repository verification

Check downloaded originals against their recorded SHA-256:

```powershell
pnadc verify --config C:\data\pnadc\pnadc.yml
```

Files adopted from an existing repository have no recorded remote hash. Read
every ZIP member and check its CRC with:

```powershell
pnadc verify --config C:\data\pnadc\pnadc.yml --deep
```

Verification reads the entire archive and can take substantial time.
Downloaded, adopted, and unverifiable files are reported separately.

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

The next `pnadc extract` reconciles its reproducible derivatives after pruning:
extracted members whose recorded source archive no longer exists are removed.

Back up originals and the `.pnadc` manifest before broad maintenance. Ordinary
sync, metadata, and conversion commands do not delete original microdata.

## Reproducibility

For a published analysis, retain:

- `pnadc --version`
- the YAML configuration with credentials or private paths removed
- each Parquet provenance sidecar
- `metadata/catalog.json` and the referenced layout JSON
- the exact analysis variable list and deflator/design method
