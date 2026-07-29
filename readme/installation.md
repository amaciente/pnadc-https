# Installation

## Requirements

- Python 3.10 or newer (64-bit recommended)
- Enough disk space for original ZIP files plus derived outputs
- HTTPS access to `ftp.ibge.gov.br`

Parquet conversion is included in the base installation. The optional
five-wave panel builder additionally uses pandas.

## Install from GitHub

The quickest route, into whichever environment is currently active:

```powershell
python -m pip install git+https://github.com/amaciente/pnadc-https.git
```

## Install from a local clone

Create an isolated environment first if you prefer one:

```powershell
git clone https://github.com/amaciente/pnadc-https.git
cd pnadc-https
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

On macOS or Linux, activate with `source .venv/bin/activate` instead.

For development, install in editable mode with tests:

```powershell
python -m pip install -e ".[dev,panel]"
python -m pytest
```

Conda users can replace the `venv` commands with:

```powershell
conda create -n pnadc python=3.12 -y
conda activate pnadc
python -m pip install .
```

## Install a built wheel on another machine

On the source machine:

```powershell
python -m pip install build
python -m build
```

Copy the `.whl` file from `dist\` to the other machine, then install it by
name (the filename carries the version, for example `pnadc_https-0.4.0-py3-none-any.whl`):

```powershell
python -m pip install .\dist\pnadc_https-*.whl
pnadc --version
```

This is useful for machines with no direct access to GitHub.

The wheel contains code, not microdata. Create or copy a data repository
separately.

## Verify the environment

```powershell
pnadc doctor --config C:\data\pnadc\pnadc.yml
pnadc --help
```

Add `--network` to test the official IBGE HTTPS endpoints. A network failure
does not invalidate an already-downloaded local repository.

