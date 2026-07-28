# Repository configuration

Create a new local repository in any directory you have space in:

```powershell
pnadc init C:\data\pnadc
```

On macOS or Linux, pass a path such as `~/data/pnadc` instead.

This creates `pnadc.yml` and empty repository directories. It refuses to
replace an existing `pnadc.yml`.

> **Example paths.** These guides use `C:\data\pnadc` throughout as the
> repository location and PowerShell backtick line continuations. Substitute
> your own path; on macOS or Linux use `\` for continuations. Nothing else
> about the commands changes between platforms.

## Portable configuration

Paths are resolved relative to the YAML file:

```yaml
archive: .
parquet: parquet
csv: csv
network:
  connect_timeout: 20
  read_timeout: 120
  retries: 4
  workers: 4
  chunk_size: 1048576
  user_agent: pnadc/0.4.0
```

This lets the whole repository move to another drive or machine unchanged.
Absolute paths are also accepted when outputs need separate disks.

## Directory layout

```text
pnadc-data/
├── pnadc.yml
├── .pnadc/                 # HTTP manifest and internal state
├── originals/              # unchanged IBGE downloads
│   ├── anual/
│   └── trimestral/
├── metadata/
│   ├── catalog.json
│   └── layouts/
├── parquet/
│   ├── anual/
│   └── trimestral/<year>/
└── csv/
```

`archive` owns `originals`, `.pnadc`, and `metadata`. `parquet` and `csv` can
be relocated independently.

## Storage choices

Parquet with Zstandard compression is the recommended canonical derived
format. It preserves numeric types, supports column projection, and is
efficient in both Python and R. CSV is intended for interchange and can be
much larger.

Use `--all-string` for Parquet only when exact source text and leading zeros
matter more than numeric types. Prefer the default standardized schema for
statistical work.

