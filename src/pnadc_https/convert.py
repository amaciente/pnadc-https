"""Streaming conversion from IBGE fixed-width text to CSV or Parquet."""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterable, Iterator
from zipfile import ZipFile

from ._version import __version__
from .config import Settings
from .layouts import Layout, Variable, load_layout
from .utils import atomic_json, ensure_within, load_json, portable_path, sha256_file

LOG = logging.getLogger(__name__)

# Bumped when the meaning of a provenance record changes.
PROVENANCE_SCHEMA_VERSION = 3

# Bumped only when a release changes the *content* a conversion produces, so
# that existing outputs are rebuilt. Deliberately separate from the package
# version: tying freshness to every release would rebuild an entire archive
# after a documentation-only patch, which for PNADC means hours of work and
# tens of gigabytes rewritten for no change in the data.
CONVERSION_FORMAT_VERSION = 1


def conversion_fingerprint(
    source: Path,
    layout_path: Path,
    columns: Iterable[str] | None,
    all_string: bool,
    output_format: str,
) -> dict[str, object]:
    """Describe everything that determines the content of a converted file.

    An existing output is only current if its recorded fingerprint matches
    the one computed now. The source is identified by size and modification
    time rather than a hash: conversion inputs are hundreds of megabytes
    each, and hashing every one would turn an up-to-date `convert-many` from
    a no-op into a full read of the archive. The dictionary is hashed because
    it is small and a silent revision there changes every column position.
    """
    stat = source.stat()
    return {
        "source_name": source.name,
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "layout_sha256": sha256_file(layout_path),
        "columns": sorted(name.lower() for name in columns) if columns is not None else None,
        # CSV is written as raw text, so all_string cannot change its content;
        # including it would reconvert an identical file when the flag flips.
        "all_string": all_string if output_format != "csv" else None,
        "output_format": output_format,
        "conversion_format_version": CONVERSION_FORMAT_VERSION,
    }


def _revision_key(name: str) -> str:
    """Return the trailing IBGE revision date, or empty when there is none."""
    match = re.search(r"_(20\d{6})$", Path(name).stem, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _preferred_revisions(
    records: Iterable[dict[str, object]],
    output_format: str,
    settings: "Settings | None" = None,
) -> list[dict[str, object]]:
    """Keep one catalog record per output file: the newest revision.

    ``PNADC_012012_20250815.zip`` and ``PNADC_012012_20260701.zip`` both
    produce ``PNADC_012012.parquet``. Synchronization does not delete a
    superseded revision — only ``--prune`` does, and it is opt-in — so both
    can sit on disk. Converting each in turn would write the file twice,
    report two conversions for one output, and leave whichever happened to
    run last, which is not necessarily the newer data.
    """
    flat = settings is not None and settings.output_layout == "flat"
    chosen: dict[tuple, dict[str, object]] = {}
    for record in records:
        source = Path(str(record.get("source", "")))
        # Group by the output that would be written, which is what can
        # collide, and which differs between the two layouts.
        if flat:
            key = (pynad_output_stem(source.name, record.get("scope")), output_format)
        else:
            key = (
                record.get("scope"),
                source.parent.as_posix(),
                simplified_output_stem(source.stem),
                output_format,
            )
        best = chosen.get(key)
        if best is None:
            chosen[key] = record
            continue
        # Prefer the later revision date; fall back to the longer name so a
        # dated release beats an undated one rather than depending on order.
        current_key = (_revision_key(source.name), source.name)
        best_source = Path(str(best.get("source", "")))
        best_key = (_revision_key(best_source.name), best_source.name)
        if current_key > best_key:
            chosen[key] = record
            LOG.info(
                "Superseding %s with %s for one output", best_source.name, source.name
            )
        else:
            LOG.info("Ignoring superseded revision %s", source.name)
    return list(chosen.values())


def _recorded_provenance(
    provenance_path: Path, legacy_path: Path
) -> dict[str, object] | None:
    """Load an output's provenance, tolerating the pre-0.3 naming scheme.

    Before 0.3.0 the sidecar was named after the source rather than the
    output. Falling back to that name keeps an existing archive from being
    reconverted in full the first time it is used with this version.
    """
    current = load_json(provenance_path, None)
    if current is not None:
        return current
    return load_json(legacy_path, None)


def _is_current(recorded: dict[str, object] | None, expected: dict[str, object]) -> bool:
    """Compare a stored fingerprint with the expected one."""
    if not isinstance(recorded, dict):
        return False
    fingerprint = recorded.get("fingerprint")
    if not isinstance(fingerprint, dict):
        # Written before fingerprints existed. Such a record cannot prove the
        # output is current: it predates the recording of the dictionary hash,
        # the column selection, and the output format, any of which may have
        # changed. Accept it only for a plain, whole-file Parquet conversion of
        # the same source, which is what earlier versions could produce; every
        # other case is reconverted once to establish a real fingerprint.
        if recorded.get("source_name") != expected["source_name"]:
            return False
        if expected["columns"] is not None or expected["output_format"] != "parquet":
            return False
        return bool(recorded.get("all_string")) == bool(expected["all_string"])
    return all(fingerprint.get(key) == value for key, value in expected.items())


def simplified_output_stem(source_stem: str) -> str:
    """Remove a trailing IBGE revision date from a converted data filename."""
    return re.sub(r"_20\d{6}$", "", source_stem, flags=re.IGNORECASE)


def pynad_output_stem(source_name: str, scope: str | None) -> str:
    """Name an output the way `pynad` does, for a single flat directory.

    `pynad` keeps every converted file in one folder, named so that the
    survey, period, and edition are all in the filename and sort sensibly:

        PNADC_012012_20250815.zip     -> pnadc.microdados.trimestral.2012.1
        PNADC_2012_visita1_...zip     -> pnadc.microdados.anual.visita1.2012
        PNADC_2023_trimestre1.zip     -> pnadc.microdados.anual.trimestre1.2023

    Falling back to the plain stem keeps an unrecognised filename usable
    rather than silently mangled.
    """
    stem = simplified_output_stem(Path(source_name).stem)
    survey = "anual" if scope == "anual" else "trimestral"
    quarterly = re.fullmatch(r"PNADC_(0?[1-4])(20\d{2})", stem, flags=re.IGNORECASE)
    if quarterly:
        quarter, year = quarterly.group(1).lstrip("0"), quarterly.group(2)
        return f"pnadc.microdados.trimestral.{year}.{quarter}"
    annual = re.fullmatch(
        r"PNADC_(20\d{2})_(visita\d|trimestre\d)", stem, flags=re.IGNORECASE
    )
    if annual:
        return f"pnadc.microdados.anual.{annual.group(2).lower()}.{annual.group(1)}"
    return f"pnadc.microdados.{survey}.{stem.lower()}"


def output_location(
    record: dict[str, object],
    source: Path,
    settings: Settings,
    output_root: Path,
    output_format: str,
) -> tuple[Path, str]:
    """Return the directory and stem for a converted file."""
    scope = str(record.get("scope") or "unknown")
    if settings.output_layout == "flat":
        # One directory for everything, as `pynad` does: simple to glob, and
        # the period is carried by the filename rather than the path.
        return output_root, pynad_output_stem(source.name, record.get("scope"))
    source_root = settings.originals / scope
    try:
        source_parent = source.relative_to(source_root).parent
    except ValueError:
        source_parent = Path()
    return output_root / scope / source_parent, simplified_output_stem(source.stem)


@contextmanager
def open_fixed_width(
    source: str | Path,
    member: str | None = None,
    encoding: str = "utf-8",
) -> Iterator[IO[str]]:
    path = Path(source)
    if path.suffix.lower() != ".zip":
        with path.open("r", encoding=encoding, errors="strict", newline="") as stream:
            yield stream
        return
    archive = ZipFile(path)
    try:
        if member is None:
            candidates = [
                name for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith((".txt", ".dat"))
            ]
            if len(candidates) != 1:
                raise ValueError("Specify --member; the ZIP does not contain exactly one text data file")
            member = candidates[0]
        binary = archive.open(member)
        import io

        text = io.TextIOWrapper(binary, encoding=encoding, errors="strict", newline="")
        try:
            yield text
        finally:
            text.close()
    finally:
        archive.close()


def _raw_fields(line: str, layout: Layout) -> list[str]:
    """Slice a fixed-width record into trimmed field values.

    Whitespace is stripped, then a field consisting only of dots is treated as
    missing. Stripping dots indiscriminately would turn a value like ".5" into
    "5". PNADC writes its width-15 weights as "000126.89953875", so no real
    value is affected today, but the distinction costs nothing to keep right.
    """
    values: list[str] = []
    for var in layout.variables:
        value = line[var.start - 1 : var.end].strip()
        if value and not value.strip("."):
            value = ""  # a dot-filled field is a missing-value sentinel
        values.append(value)
    return values


def normalize_columns(columns: Iterable[str] | None) -> tuple[str, ...] | None:
    """Freeze a column selection so it can be iterated more than once.

    The selection is used to pick variables, to build the fingerprint, and to
    record provenance. A generator would be exhausted by the first of those,
    silently producing a different selection from the one requested.
    """
    if columns is None:
        return None
    frozen = tuple(columns)
    if not frozen:
        raise ValueError("--columns was given no names; omit it to keep every column")
    return frozen


def _select_variables(layout: Layout, columns: Iterable[str] | None) -> list[Variable]:
    """Resolve the layout variables to keep in the output, in layout order.

    Selecting a subset up front (rather than after conversion) matters for
    PNADC: quarterly microdata layouts run to several hundred variables, so
    keeping only what an analysis needs cuts conversion time and output size
    proportionally, the same role ``vars=`` plays in the R PNADcIBGE package.
    """
    if columns is None:
        return layout.variables
    requested = {name.lower() for name in columns}
    by_name = {variable.name: variable for variable in layout.variables}
    missing = sorted(requested - by_name.keys())
    if missing:
        raise ValueError(f"Unknown column(s) for this layout: {', '.join(missing)}")
    return [variable for variable in layout.variables if variable.name in requested]


def _parse_value(value: str, variable: Variable, all_string: bool) -> str | int | float | None:
    if value == "":
        return None
    if all_string or variable.storage_type == "string":
        return value
    try:
        if variable.storage_type == "float64":
            return float(value.replace(",", "."))
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {variable.storage_type} value for {variable.name}: {value!r}") from exc


def _arrow_type(variable: Variable, all_string: bool):
    import pyarrow as pa

    if all_string:
        return pa.string()
    return {
        "int8": pa.int8(),
        "int16": pa.int16(),
        "int32": pa.int32(),
        "int64": pa.int64(),
        "float64": pa.float64(),
        "string": pa.string(),
    }[variable.storage_type]


def _write_csv(stream: IO[str], layout: Layout, variables: list[Variable], indices: list[int], temporary: Path) -> int:
    rows = 0
    with temporary.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow([variable.name for variable in variables])
        for line in stream:
            raw = _raw_fields(line, layout)
            writer.writerow([raw[index] for index in indices])
            rows += 1
    return rows


def _write_parquet(
    stream: IO[str],
    layout: Layout,
    variables: list[Variable],
    indices: list[int],
    temporary: Path,
    chunk_rows: int,
    all_string: bool,
) -> int:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pyarrow is required for Parquet output") from exc
    schema = pa.schema([(var.name, _arrow_type(var, all_string)) for var in variables])
    writer = pq.ParquetWriter(temporary, schema=schema, compression="zstd")
    total = 0
    columns: list[list[object]] = [[] for _ in variables]
    try:
        for line in stream:
            raw = _raw_fields(line, layout)
            for column, index, variable in zip(columns, indices, variables):
                column.append(_parse_value(raw[index], variable, all_string))
            total += 1
            if len(columns[0]) >= chunk_rows:
                writer.write_table(pa.Table.from_arrays([pa.array(values, type=field.type) for values, field in zip(columns, schema)], schema=schema))
                columns = [[] for _ in variables]
        if columns and columns[0]:
            writer.write_table(pa.Table.from_arrays([pa.array(values, type=field.type) for values, field in zip(columns, schema)], schema=schema))
    finally:
        writer.close()
    return total


def convert_file(
    source: str | Path,
    layout_path: str | Path,
    output: str | Path,
    member: str | None = None,
    layout_member: str | None = None,
    encoding: str = "utf-8",
    chunk_rows: int = 50_000,
    all_string: bool = False,
    force: bool = False,
    provenance_path: str | Path | None = None,
    columns: Iterable[str] | None = None,
    root: str | Path | None = None,
) -> dict[str, object]:
    source_path = Path(source).resolve()
    layout_file = Path(layout_path).resolve()
    target = Path(output).resolve()
    if target.exists() and not force:
        raise FileExistsError(f"Output already exists; pass --force to replace it: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    temporary.unlink(missing_ok=True)
    columns = normalize_columns(columns)
    layout = load_layout(layout_file, layout_member)
    variables = _select_variables(layout, columns)
    name_to_index = {variable.name: index for index, variable in enumerate(layout.variables)}
    indices = [name_to_index[variable.name] for variable in variables]
    with open_fixed_width(source_path, member, encoding) as stream:
        if target.suffix.lower() == ".csv":
            rows = _write_csv(stream, layout, variables, indices, temporary)
        elif target.suffix.lower() in (".parquet", ".pq"):
            rows = _write_parquet(stream, layout, variables, indices, temporary, max(1, chunk_rows), all_string)
        else:
            raise ValueError("Output extension must be .csv or .parquet")
    os.replace(temporary, target)
    output_format = "csv" if target.suffix.lower() == ".csv" else "parquet"
    # Paths are stored relative to the repository root where possible, so the
    # record stays valid if the repository is moved or read elsewhere.
    repository = Path(root).resolve() if root is not None else None
    provenance: dict[str, object] = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "paths_relative_to": "repository root" if repository is not None else None,
        "source": portable_path(source_path, repository),
        "source_name": source_path.name,
        "source_member": member,
        "layout": portable_path(layout_file, repository),
        "layout_member": layout_member,
        "output": portable_path(target, repository),
        "output_name": target.name,
        "rows": rows,
        "columns": len(variables),
        "variables": [variable.name for variable in variables] if columns is not None else None,
        "all_string": all_string,
        # Used by convert_catalog to decide whether this output is still current.
        "fingerprint": conversion_fingerprint(
            source_path, layout_file, columns, all_string, output_format
        ),
    }
    provenance_target = (
        Path(provenance_path).resolve()
        if provenance_path is not None
        else target.with_suffix(target.suffix + ".provenance.json")
    )
    atomic_json(provenance_target, provenance)
    return provenance


def convert_catalog(
    settings: Settings,
    output_format: str = "parquet",
    scope: str | None = None,
    years: set[int] | None = None,
    force: bool = False,
    all_string: bool = False,
    quarters: set[int] | None = None,
    columns: Iterable[str] | None = None,
) -> tuple[int, int, int]:
    if output_format not in ("parquet", "csv"):
        raise ValueError("output_format must be 'parquet' or 'csv'")
    columns = normalize_columns(columns)
    output_root = settings.parquet_dir if output_format == "parquet" else settings.csv_dir
    catalog_path = settings.metadata_dir / "catalog.json"
    catalog = load_json(catalog_path, None)
    if catalog is None:
        raise FileNotFoundError("Metadata catalog not found; run `pnadc metadata` first")
    converted = skipped = unresolved = 0
    for record in _preferred_revisions(catalog.get("microdata", []), output_format, settings):
        if scope and record.get("scope") != scope:
            continue
        if years and record.get("year") not in years:
            continue
        if quarters and record.get("scope") == "trimestral" and record.get("quarter") not in quarters:
            continue
        layout_relative = record.get("layout")
        if not layout_relative:
            unresolved += 1
            LOG.warning("No layout resolved for %s", record["source"])
            continue
        if record.get("member") is None and len(record.get("members") or ()) > 1:
            # Which member to convert is ambiguous. Report it like any other
            # unresolved record instead of raising, which would abandon every
            # remaining file in the batch over one archive.
            unresolved += 1
            LOG.warning(
                "%s holds %d text members; convert it individually with --member",
                record["source"],
                len(record["members"]),
            )
            continue
        source = ensure_within(settings.archive / Path(record["source"]), settings.archive)
        layout_path = ensure_within(settings.archive / Path(layout_relative), settings.archive)
        target_dir, target_stem = output_location(
            record, source, settings, output_root, output_format
        )
        target = target_dir / f"{target_stem}.{output_format}"
        # Named after the output, not the source: IBGE revisions differ only
        # by a filename suffix that simplified_output_stem removes, so several
        # sources map to one output. Keying provenance to the source would
        # leave the previous revision's record unexaminable and let a stale
        # output survive a genuine update.
        provenance_path = target_dir / f"{target.name}.provenance.json"
        expected = conversion_fingerprint(
            source, layout_path, columns, all_string, output_format
        )
        legacy_provenance = target_dir / f"{source.stem}.{output_format}.provenance.json"
        if target.exists() and not force:
            recorded = _recorded_provenance(provenance_path, legacy_provenance)
            if _is_current(recorded, expected):
                skipped += 1
                continue
            LOG.info("Reconverting %s; its inputs or options changed", target.name)
        convert_file(
            source,
            layout_path,
            target,
            member=record.get("member"),
            force=True,
            all_string=all_string,
            provenance_path=provenance_path,
            columns=columns,
            root=settings.archive,
        )
        converted += 1
        LOG.info("Converted %s", source)
    return converted, skipped, unresolved
