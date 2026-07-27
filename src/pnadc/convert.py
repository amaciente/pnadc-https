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

from .config import Settings
from .layouts import Layout, Variable, load_layout
from .utils import atomic_json, ensure_within, load_json

LOG = logging.getLogger(__name__)


def simplified_output_stem(source_stem: str) -> str:
    """Remove a trailing IBGE revision date from a converted data filename."""
    return re.sub(r"_20\d{6}$", "", source_stem, flags=re.IGNORECASE)


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
    return [line[var.start - 1 : var.end].strip(" .\r\n") for var in layout.variables]


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
) -> dict[str, object]:
    source_path = Path(source).resolve()
    layout_file = Path(layout_path).resolve()
    target = Path(output).resolve()
    if target.exists() and not force:
        raise FileExistsError(f"Output already exists; pass --force to replace it: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    temporary.unlink(missing_ok=True)
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
    provenance: dict[str, object] = {
        "schema_version": 1,
        "source": str(source_path),
        "source_name": source_path.name,
        "source_member": member,
        "layout": str(layout_file),
        "layout_member": layout_member,
        "output": str(target),
        "output_name": target.name,
        "rows": rows,
        "columns": len(variables),
        "variables": [variable.name for variable in variables] if columns is not None else None,
        "all_string": all_string,
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
    output_root = settings.parquet_dir if output_format == "parquet" else settings.csv_dir
    catalog_path = settings.metadata_dir / "catalog.json"
    catalog = load_json(catalog_path, None)
    if catalog is None:
        raise FileNotFoundError("Metadata catalog not found; run `pnadc metadata` first")
    converted = skipped = unresolved = 0
    for record in catalog.get("microdata", []):
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
        source = ensure_within(settings.archive / Path(record["source"]), settings.archive)
        layout_path = ensure_within(settings.archive / Path(layout_relative), settings.archive)
        source_root = settings.originals / str(record.get("scope") or "unknown")
        try:
            source_parent = source.relative_to(source_root).parent
        except ValueError:
            source_parent = Path()
        target_dir = output_root / str(record.get("scope") or "unknown") / source_parent
        target = target_dir / f"{simplified_output_stem(source.stem)}.{output_format}"
        provenance_path = target_dir / f"{source.stem}.{output_format}.provenance.json"
        if target.exists() and not force:
            skipped += 1
            continue
        convert_file(
            source,
            layout_path,
            target,
            member=record.get("member"),
            force=force,
            all_string=all_string,
            provenance_path=provenance_path,
            columns=columns,
        )
        converted += 1
        LOG.info("Converted %s", source)
    return converted, skipped, unresolved
