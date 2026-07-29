# CLI and Python API

Examples use `C:\data\pnadc` as the repository path and PowerShell line
continuations; substitute your own path, and see
[configuration](configuration.md) for the platform note.

## Recommended update workflow

Preview a narrow synchronization:

```powershell
pnadc -v sync --config C:\data\pnadc\pnadc.yml `
  --survey trimestral --year 2025 --dry-run
```

Download, catalog, and convert:

```powershell
pnadc -v sync --config C:\data\pnadc\pnadc.yml `
  --survey trimestral --year 2025
pnadc -v metadata --config C:\data\pnadc\pnadc.yml
pnadc -v convert-many --config C:\data\pnadc\pnadc.yml `
  --survey trimestral --year 2025
```

The combined form is:

```powershell
pnadc -v update --config C:\data\pnadc\pnadc.yml `
  --survey trimestral --year 2025 --convert
```

Repeat `--year`, `--quarter`, or `--columns` to select multiple values.
Column projection occurs during fixed-width parsing, which reduces memory and
output size:

```powershell
pnadc convert-many --config C:\data\pnadc\pnadc.yml `
  --survey trimestral --year 2025 `
  --columns ano --columns trimestre --columns uf `
  --columns upa --columns estrato --columns v1028 --columns vd4002
```

Unknown columns fail immediately. Existing outputs are skipped unless
`--force` is explicitly supplied to the conversion command.

Set `output_layout: flat` in `pnadc.yml` to write one directory of
`pynad`-style names instead of the default survey/year tree. If the files will
feed `pynad`'s panel stage, also set `parquet: microdados/parquet`; see the
[configuration guide](configuration.md).

## Python API

```python
from pnadc_https import Repository

repo = Repository(r"C:\data\pnadc\pnadc.yml")

preview = repo.sync(
    surveys=["trimestral"],
    years=[2025],
    dry_run=True,
)

repo.sync(surveys=["trimestral"], years=[2025])
repo.catalog()
converted, skipped, unresolved = repo.standardize(
    survey="trimestral",
    years=[2025],
    output_format="parquet",
)
```

Or run the complete pipeline:

```python
result = repo.update(
    surveys=["trimestral"],
    years=[2025],
    convert=True,
)
```

Verify mirrored originals through the Python API:

```python
verification = repo.verify(deep=True)
if verification.failed:
    raise RuntimeError(verification.failed)
```

For large files, read only needed columns:

```python
import pyarrow.dataset as ds

data = ds.dataset(
    r"C:\data\pnadc\parquet\trimestral",
    format="parquet",
)
table = data.to_table(columns=["ano", "trimestre", "uf", "v1028", "vd4002"])
```

## Panels

Install `pnadc-https[panel]`, then pass two to five consecutive quarterly files:

```powershell
pnadc panel 2012Q1.parquet 2012Q2.parquet 2012Q3.parquet `
  --panel-id 20121 --output panel-20121.parquet
```

The deterministic linkage uses dwelling, sex, reported birth date, and a
within-wave duplicate rank. Inputs must include `ano`, `trimestre`, `v1016`,
and the linkage variables; their chronology is validated against `--panel-id`.
See the compatibility guide before treating it as an exact reproduction of
`pynad`'s historical classifier.

