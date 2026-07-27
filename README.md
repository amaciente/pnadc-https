# pnadc

`pnadc` maintains a local PNAD Contínua archive without requiring FTP.
It recursively lists the public IBGE directory indexes over HTTPS, downloads
only new or changed files, normalizes the IBGE fixed-width dictionaries, and
converts microdata to Parquet or CSV.

The project was created for networks where `https://ftp.ibge.gov.br` is
reachable but FTP port 21 and passive FTP ports are blocked.

The code lives here, at `C:\projects\pnadc`. Generated data is kept separately
at `C:\data\pnadc`, as configured in `config.yml`: `archive: C:\data\pnadc`
is the shared root under which `originals\` and `metadata\` live, and
`parquet:`/`csv:` point at their own sibling folders there.

## What it provides

- HTTPS synchronization of the **quarterly** and **annual** Microdados trees.
- An incremental manifest using HTTP size, ETag, and Last-Modified metadata.
- Atomic downloads (`.part` files are replaced only after a complete transfer).
- Safe, optional ZIP extraction.
- `.xls` and `.xlsx` PNADC dictionary parsing into stable JSON layouts.
- A metadata catalog linking local data archives to likely dictionaries.
- Streaming fixed-width conversion to Zstandard-compressed Parquet or CSV.
- Batch conversion, provenance sidecars, and deterministic person-panel tools.
- Python 3.12 and Windows/PowerShell support.

Detailed user guides are available in the [`readme`](readme/) folder:
installation, portable configuration, CLI and Python usage, R/RStudio access,
maintenance, and compatibility/methodology.

## Install

Activate the environment where the program should live, then install the
project in editable mode:

```powershell
conda activate base-ds
cd C:\projects\pnadc
python -m pip install -e .
pnadc doctor
```

If `conda` is not initialized in the current PowerShell, use Miniforge's
environment Python directly:

```powershell
& "$env:LOCALAPPDATA\miniforge3\envs\base-ds\python.exe" -m pip install -e .
```

`pandas` is needed only for the `panel` command. Install it if the doctor
reports it missing:

```powershell
python -m pip install -e ".[panel]"
```

## Configure

Copy the example and edit the paths if desired:

```powershell
Copy-Item config.example.yml config.yml
pnadc doctor --config config.yml --network
```

`archive` is the shared data root — `originals\` (mirrored IBGE ZIPs) and
`metadata\` (catalog and parsed dictionaries) live directly under it, and
`parquet`/`csv` default to sibling folders under the same root unless you
override them, as this config does. All of it resolves to `C:\data\pnadc`,
deliberately outside this code checkout, so the (large) data tree stays
separate from the (small) source tree. The source code never deletes
remote-derived files during an ordinary sync. `--prune` is the explicit
opt-in for removing local files that disappeared from IBGE.

## Recommended workflow

First inspect what IBGE currently exposes:

```powershell
pnadc -v sync --config config.yml --survey trimestral --year 2025 --dry-run
```

Download the selected tree, generate metadata, and convert resolvable files:

```powershell
pnadc -v sync --config config.yml --survey trimestral --year 2025
pnadc -v metadata --config config.yml
pnadc -v convert-many --config config.yml --survey trimestral --year 2025
```

The combined convenience command performs the same pipeline:

```powershell
pnadc -v pnadc-tudo --config config.yml --survey trimestral --year 2025 --convert
```

Year selection limits downloads, but the HTML directory tree must still be
listed to discover matching files.

## Commands

### Synchronize the original IBGE archive

```powershell
pnadc sync --survey both
pnadc sync --survey anual --year 2023 --year 2024
pnadc sync --survey trimestral --year 2025 --quarter 1 --quarter 2
pnadc sync --survey trimestral --dry-run
```

Existing files are skipped when the local size and recorded HTTP metadata still
match. Interrupted transfers remain as `.part` files and are never mistaken for
finished downloads.

`--prune` cannot be combined with `--year` or `--quarter`: a period-filtered
remote view is partial and therefore cannot safely prove that other local
periods were removed upstream.

### Extract ZIP files

Extraction is optional because conversion reads a text member directly from a
ZIP. It is useful for inspecting original documents:

```powershell
pnadc extract
pnadc extract --force
```

### Parse one dictionary

```powershell
pnadc layout .\dictionary.xls .\layout.json
pnadc layout .\Dicionario_e_input.zip .\layout.json --member dicionario_PNADC_microdados_trimestral.xls
```

### Build metadata and inventory

```powershell
pnadc metadata
```

This creates `metadata\catalog.json` and normalized layouts below
`metadata\layouts`. A catalog entry with `layout: null` needs manual
review; batch conversion reports it as unresolved rather than guessing.

`Anual/Microdados` is actually two unrelated IBGE products sharing one URL
tree: `Visita\Visita_1`..`Visita_5` (annual per-interview data) and
`Trimestre\Trimestre_1`..`Trimestre_4` (annual per-topic supplements), each
with its own dictionaries. Cataloging detects which one a file belongs to
from its path and only matches dictionaries within the same one, so a
Visita dictionary can never be paired with Trimestre data or vice versa.

### Convert one file

```powershell
pnadc convert `
  .\originals\trimestral\2025\PNADC_012025.zip `
  .\metadata\layouts\trimestral-dicionario-pnadc-microdados-trimestral.json `
  .\parquet\trimestral\2025\PNADC_012025.parquet
```

Parquet uses numeric types inferred from IBGE field widths, matching the main
`pynad` convention. Use `--all-string` when exact textual codes and leading
zeros are more important than numeric storage. Pass a `.csv` output path
instead of `.parquet` to write delimited text; `--all-string` and
`--chunk-rows` are ignored for CSV since it is written as raw text a row at a
time.

Add `--columns NAME` (repeatable) to keep only the named layout variables
instead of every column — PNADC quarterly layouts run to a few hundred
variables, so selecting up front cuts conversion time and output size the
same way the R `PNADcIBGE` package's `vars=` argument does:

```powershell
pnadc convert .\originals\trimestral\2025\PNADC_012025.zip `
  .\metadata\layouts\trimestral-dicionario-pnadc-microdados-trimestral.json `
  .\parquet\trimestral\2025\PNADC_012025.parquet `
  --columns uf --columns v1008 --columns vd4002
```

An unknown column name raises immediately rather than writing a partial file.

### Convert many files at once

```powershell
pnadc convert-many --config config.yml --survey trimestral --year 2025
pnadc convert-many --config config.yml --survey trimestral --year 2025 --format csv
```

`--format` selects `parquet` (default) or `csv` for the whole batch. Parquet
lands under the configured `parquet` directory (default
`C:\data\pnadc\parquet`); CSV lands under the configured `csv` directory
(default `C:\data\pnadc\csv`), each split into `<survey>/<year>/...`
subfolders, for example `C:\data\pnadc\csv\trimestral\2025\PNADC_012025.csv`.
Set `csv:` in `config.yml` to relocate it, the same way `parquet:` relocates
Parquet output. `pnadc update --convert --format csv` runs the same batch
conversion as part of the combined sync-catalog-convert pipeline.

A trailing IBGE revision date is removed from the output name, so
`PNADC_012012_20250815.zip` produces `PNADC_012012.parquet` (or `.csv`). The
neighboring provenance file retains the original source stem
(`PNADC_012012_20250815.parquet.provenance.json`) and records the source,
dictionary, record count, and conversion options. CSV can require
substantially more disk space than Parquet for the same data.

### Build a person panel

Pass consecutive quarterly Parquet files, beginning with the panel's first
visit:

```powershell
pnadc panel `
  .\2012Q1.parquet .\2012Q2.parquet .\2012Q3.parquet .\2012Q4.parquet .\2013Q1.parquet `
  --panel-id 20121 `
  --output .\parquet\panels\panel-20121.parquet
```

`--output` is always explicit; panels have no configured default location.
Placing them under `parquet\panels\` is just a convention, since they are
Parquet files derived from the converted quarterly data.

The command filters wave `n` to `v1016 == n`, links people within
`upa`/`v1008` using sex and birth date, and disambiguates duplicate signatures
by the within-wave `v2003` order. `--wide` emits one row per linked person with
wave-suffixed variables.

Panel construction loads the selected waves into memory. Build one panel at a
time and ensure the machine has enough RAM for the chosen files.

## Storage layout

With the default `config.yml`, `archive` (`C:\data\pnadc`) is the shared root;
`originals\` and `metadata\` live directly under it, and `parquet\`/`csv\` are
sibling folders under the same root (override `parquet:`/`csv:` in
`config.yml` to relocate them independently, as this project already does).
None of this lives inside the code checkout at `C:\projects\pnadc`:

```text
C:\data\pnadc\
├── .pnadc\                  (sync bookkeeping: manifest.json)
├── originals\
│   ├── anual\
│   └── trimestral\
├── extracted\               (only present after `pnadc extract`)
├── metadata\
│   ├── catalog.json
│   └── layouts\
├── parquet\
│   ├── anual\
│   ├── panels\              (optional; see `pnadc panel --output`)
│   └── trimestral\
│       └── 2012\
│           ├── PNADC_012012.parquet
│           └── PNADC_012012_20250815.parquet.provenance.json
├── csv\
│   ├── anual\
│   └── trimestral\
│       └── 2012\
│           ├── PNADC_012012.csv
│           └── PNADC_012012_20250815.csv.provenance.json
└── analytical\               (a separate downstream project; pnadc never writes here)
```

## Relationship to `pynad`

This is a clean HTTPS-first implementation informed by the workflow and public
data conventions of Rafael Guerreiro Osorio's GPL-licensed `pynad` 3.0.3. It is
not a byte-for-byte fork. Downloading, dictionary parsing, CSV/Parquet
conversion, metadata inventory, and panel construction are available, but the
person-linkage classifier is intentionally simpler and explicitly documented
above. Keep `pynad` if exact reproduction of its seven-category historical
panel classifier is required.

The replacement fixes the corporate-network failure point in `pynad`: remote
file discovery is HTTPS-only, not an FTP directory listing followed by HTTPS
downloads.

## Relationship to R's `PNADcIBGE`

IBGE's own R package (`get_pnadc`, `read_pnadc`, `pnadc_labeller`,
`pnadc_deflator`, `pnadc_design`) covers the same download-and-read ground
plus two things `pnadc` deliberately leaves to downstream analysis:

- **Income deflators.** `pnadc_deflator()` joins IBGE's published deflator
  tables onto the microdata so income variables are comparable across
  quarters/years. This tool does not fetch or join deflators; if your
  analysis compares income over time, get the deflator file for the matching
  period from IBGE's `Documentacao` folder and join it yourself (by year and
  quarter, and additionally by UF for annual data) before deflating.
- **Sample design / variance estimation.** `pnadc_design()` builds a
  `survey`/`svyrep` design object so standard errors account for PNADC's
  stratified multistage cluster sample. This tool's Parquet/CSV output keeps
  the design variables (`upa`, weights such as `v1028`) intact, but computing
  a naive weighted mean without a proper design object (e.g. via `samplics`
  in Python, or `survey`/`srvyr` if you use R downstream) will understate
  variance. This matters for the `analytical\` project, not for `pnadc`
  itself.

Both are realistic follow-ups but need validating against IBGE's actual
deflator file layout before automating — ask if you'd like either built out.

## Storage and safety

PNAD Contínua archives are large. Run `pnadc doctor` before a broad sync and use
`--year` to constrain downloads. CSV can require substantially more space than
Parquet. Commands never commit, upload, or transmit local microdata elsewhere.

## Development checks

```powershell
python -m unittest discover -s tests -v
python -m pnadc --help
```
