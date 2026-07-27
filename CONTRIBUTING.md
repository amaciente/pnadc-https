# Contributing

Thanks for your interest in `pnadc-https`. Bug reports, documentation fixes, and
pull requests are welcome.

## Reporting problems

Open an issue at <https://github.com/amaciente/pnadc-https/issues>. For a failing
command, please include:

- the exact command you ran, with `-v` or `-vv` added;
- the output of `pnadc doctor --config <your config> --network`;
- your operating system and the output of `python --version`.

**Never attach microdata files or their contents.** File names, the
`metadata/catalog.json` entry, and the error message are enough to diagnose
almost every problem.

## Development setup

```powershell
git clone https://github.com/amaciente/pnadc-https.git
cd pnadc-https
python -m pip install -e ".[all]"
pnadc doctor
```

Run the tests before opening a pull request:

```powershell
python -m unittest discover -s tests -v
```

The suite runs offline. It builds synthetic dictionaries and fixed-width
files in a temporary directory and never contacts IBGE, so it is safe and
fast to run repeatedly.

## Project layout

- `src/pnadc_https/` — the package. `config.py` resolves settings and paths,
  `downloader.py` mirrors IBGE over HTTPS, `layouts.py` parses dictionaries,
  `metadata.py` builds the catalog, `convert.py` writes Parquet/CSV,
  `panel.py` builds person panels, `repository.py` is the public Python API,
  and `cli.py` wires it all to the command line.
- `tests/` — `unittest` tests, one module per source module.
- `readme/` — user guides referenced from `README.md`.

## Conventions

- Target Python 3.10 and newer; the package depends only on `requests`,
  `PyYAML`, `pyarrow`, `xlrd`, and `openpyxl`, with `pandas` optional for
  the `panel` command. Please discuss new dependencies in an issue first.
- Writes go through the atomic helpers in `utils.py`: write to a `.part`
  file, then `os.replace`. An interrupted run must never leave a truncated
  file that looks complete.
- Paths derived from remote or archive input pass through
  `utils.ensure_within` so they cannot escape the repository root.
- No command may delete IBGE-derived files during ordinary operation.
  Deletion is opt-in through `sync --prune`.
- Add a test with any behaviour change, and a `CHANGELOG.md` entry under
  `## [Unreleased]`.

## Scope

This project maintains a local, standardized copy of PNAD Contínua and stops
there. It deliberately does not apply income deflators or build complex
survey design objects — those belong in the analysis step, where the choices
are the analyst's to make. See the compatibility notes in `readme/` for
details.
