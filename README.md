# pnadc

`pnadc` maintains a local PNAD Contínua archive without requiring FTP.
It recursively lists the public IBGE directory indexes over HTTPS, downloads
only new or changed files, normalizes the IBGE fixed-width dictionaries, and
converts microdata to Parquet or CSV.

The project was created for networks where `https://ftp.ibge.gov.br` is
reachable but FTP port 21 and passive FTP ports are blocked.

**`pnadc` is derived from [`pynad`](https://pypi.org/project/pynad/), created
by [Rafael Guerreiro Osorio](https://pypi.org/project/pynad/) at
[Ipea](https://www.ipea.gov.br/).** `pynad` established the workflow this
package follows — mirroring the IBGE archive, normalizing the dictionaries,
standardizing the microdata, and reconstructing the rotating person panels —
along with the field conventions and data organization reused here. This
package reimplements that workflow over HTTPS for restricted networks; it is
a reimplementation rather than a fork, and it is released under the GPL to
match. See [Relationship to `pynad`](#relationship-to-pynad) for what differs.

Code and data are kept apart. The package is installed like any other Python
package, while the data repository it builds lives in a directory of your
choosing — created by `pnadc init` and described by a single `pnadc.yml`
whose paths are relative to itself, so the whole repository can be moved or
shared without editing anything.

## What it provides

- HTTPS synchronization of the **quarterly** and **annual** Microdados trees.
- An incremental manifest using HTTP size, ETag, and Last-Modified metadata.
- Atomic downloads (`.part` files are replaced only after a complete transfer).
- Safe, optional ZIP extraction.
- `.xls` and `.xlsx` PNADC dictionary parsing into stable JSON layouts.
- A metadata catalog linking local data archives to likely dictionaries.
- Streaming fixed-width conversion to Zstandard-compressed Parquet or CSV.
- Batch conversion, provenance sidecars, and deterministic person-panel tools.
- Python 3.10+ on Windows, macOS, and Linux.

Detailed user guides are available in the [`readme`](readme/) folder:
installation, portable configuration, CLI and Python usage, R/RStudio access,
maintenance, and compatibility/methodology.

## Install

Requires Python 3.10 or newer. Install directly from GitHub:

```
python -m pip install git+https://github.com/amaciente/pnadc.git
```

The `panel` command additionally needs `pandas`; install it with the extra if
you intend to build person panels:

```
python -m pip install "pnadc[panel] @ git+https://github.com/amaciente/pnadc.git"
```

To work on the package itself, clone it and install in editable mode:

```
git clone https://github.com/amaciente/pnadc.git
```

```
python -m pip install -e ".[all]"
```

Any environment manager works — `venv`, `conda`, `uv`, or none at all.
Activate whichever environment you want `pnadc` installed into before running
`pip`. Then confirm the installation and report which optional dependencies
are present:

```
pnadc doctor
```

If your shell reports that `pnadc` is not found, the scripts directory is not
on your `PATH`; `python -m pnadc` works identically and always resolves.

## Create a repository

A repository is just a directory. Create one anywhere you have space —
substitute your own path for the example:

```
pnadc init C:\data\pnadc
```

This creates the directory skeleton plus a `pnadc.yml` whose paths are
relative to itself. Pass that file to every later command with `--config`.

`archive` is the shared data root: `originals/` (mirrored IBGE ZIPs) and
`metadata/` (catalog and parsed dictionaries) live directly under it,
alongside `parquet/` and `csv/`. Keeping the repository outside your code
checkout keeps the large data tree separate from the small source tree.

Commands never delete IBGE-derived files during ordinary operation.
`sync --prune` is the explicit opt-in for removing local files that
disappeared upstream.

> Examples throughout this README use `C:\data\pnadc` as the repository path
> and Windows PowerShell line continuations. On macOS or Linux use a path such
> as `~/data/pnadc` and `\` for line continuations; nothing else differs.

## Recommended workflow

First inspect what IBGE currently exposes:

```powershell
pnadc -v sync --config C:\data\pnadc\pnadc.yml --survey trimestral --year 2025 --dry-run
```

Download the selected tree, generate metadata, and convert resolvable files:

```powershell
pnadc -v sync --config C:\data\pnadc\pnadc.yml --survey trimestral --year 2025
pnadc -v metadata --config C:\data\pnadc\pnadc.yml
pnadc -v convert-many --config C:\data\pnadc\pnadc.yml --survey trimestral --year 2025
```

The combined convenience command performs the same pipeline:

```powershell
pnadc -v pnadc-tudo --config C:\data\pnadc\pnadc.yml --survey trimestral --year 2025 --convert
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
pnadc convert-many --config C:\data\pnadc\pnadc.yml --survey trimestral --year 2025
pnadc convert-many --config C:\data\pnadc\pnadc.yml --survey trimestral --year 2025 --format csv
```

`--format` selects `parquet` (default) or `csv` for the whole batch. Output
lands under the repository's `parquet/` or `csv/` directory, split into
`<survey>/<year>/` subfolders — for example
`csv/trimestral/2025/PNADC_012025.csv`. Set `parquet:` or `csv:` in
`pnadc.yml` to relocate either one. `pnadc update --convert --format csv`
runs the same batch conversion as part of the combined
sync-catalog-convert pipeline.

A trailing IBGE revision date is removed from the output name, so
`PNADC_012012_20250815.zip` produces `PNADC_012012.parquet` (or `.csv`).
Each output carries a provenance sidecar named after it
(`PNADC_012012.parquet.provenance.json`) recording the source, dictionary,
record count, and conversion options. CSV can require substantially more
disk space than Parquet for the same data.

**Staying current.** Re-running batch conversion does not simply skip
outputs that already exist — it compares each one against a fingerprint of
its inputs and options, and reconverts when anything that determines the
content has changed:

- IBGE published a revised release (including under a new filename that maps
  to the same output name, such as `PNADC_012012_20260701.zip`);
- the source was replaced under its existing filename;
- the dictionary was reissued, changing column positions;
- `--columns` or `--all-string` differs from the previous run;
- the package version changed.

Outputs that are genuinely up to date are still skipped, so routine
re-synchronization remains inexpensive. Sources are compared by size and
modification time rather than by hash, because hashing every multi-hundred
megabyte archive would turn an up-to-date run into a full read of the
repository; dictionaries, being small, are compared by SHA-256.

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

`pnadc init` creates the tree below. `archive` is the shared root;
`originals/` and `metadata/` live directly under it, with `parquet/` and
`csv/` as siblings. Set `parquet:` or `csv:` in `pnadc.yml` to relocate
either one — onto a larger volume, for example. The repository is
self-contained and independent of where the package is installed:

```text
<your repository>/
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

This package exists because of `pynad`, and the credit for the approach
belongs there.

> **`pynad`** — *An application to manage Pnadc microdata and its panels*
> Rafael Guerreiro Osorio, Instituto de Pesquisa Econômica Aplicada (Ipea)
> Version 3.0.3, GPL-3.0-or-later
> <https://pypi.org/project/pynad/> — `pip install pynad`

`pynad` worked out the hard parts of treating PNAD Contínua as a maintained
local archive rather than a pile of downloaded ZIPs: which files IBGE
actually publishes and how they are organized, how to read the fixed-width
dictionaries, which conventions to use when standardizing the microdata, and
how to reconstruct the rotating five-visit person panels that IBGE
disseminates only as cross-sections. Those ideas are `pynad`'s, and this
package follows them.

**What is different here.** `pynad` discovers remote files by listing an FTP
directory before downloading over HTTPS. On networks where FTP port 21 and
the passive port range are blocked — common in corporate and government
environments — that discovery step fails and the tool cannot run. `pnadc`
performs discovery over HTTPS as well, by walking IBGE's public directory
indexes, which is the single reason this package was written.

**What is not reproduced.** The person-linkage classifier here is
deliberately simpler: it links people within a dwelling by sex and birth date
with a deterministic tiebreak, and documents that plainly. `pynad` implements
a considerably more careful seven-category historical panel classifier. **If
you need faithful panel construction, use `pynad`** — this package does not
replace it, and no comparison of the two classifiers is claimed.

This is a reimplementation, not a fork; no `pynad` source was copied. It is
released under GPL-3.0-or-later to match `pynad`'s license and to keep the
lineage explicit. Neither Rafael Osorio nor Ipea has endorsed or reviewed
this package.

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
