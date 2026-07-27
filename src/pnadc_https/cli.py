"""Command-line interface."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import load_settings
from .convert import convert_catalog, convert_file
from .downloader import sync_archive
from .extract import extract_archive
from .layouts import load_layout, write_layout
from .metadata import generate_metadata
from .panel import build_panel
from .repository import init_repository
from .utils import human_size


def _years(values: list[int] | None) -> set[int] | None:
    return set(values) if values else None


def _settings(args: argparse.Namespace):
    settings = load_settings(args.config, args.archive)
    if getattr(args, "include_superseded", False):
        settings.exclude = ()
    return settings


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="YAML configuration file")
    parser.add_argument("--archive", type=Path, help="Override archive directory")
    parser.add_argument(
        "--include-superseded",
        action="store_true",
        help=(
            "also process Projecoes_Anteriores, the superseded population "
            "projections IBGE retains for reproducing previously published "
            "figures; excluded by default because they are not current "
            "microdata and account for most of the archive by size"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pnadc",
        description="Mirror and process IBGE PNAD Continua microdata over HTTPS.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a local PNADC repository skeleton")
    init.add_argument("path", nargs="?", type=Path, default=Path.cwd())

    sync = sub.add_parser("sync", help="incrementally mirror IBGE files over HTTPS")
    _add_common(sync)
    sync.add_argument("--survey", choices=("trimestral", "anual", "both"), default="both")
    sync.add_argument("--year", type=int, action="append", help="survey reference year; repeatable")
    sync.add_argument("--quarter", type=int, choices=(1, 2, 3, 4), action="append", help="quarterly release; repeatable")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--prune", action="store_true", help="remove local files no longer present remotely")

    extract = sub.add_parser("extract", help="safely extract mirrored ZIP files")
    _add_common(extract)
    extract.add_argument("--force", action="store_true")

    layout = sub.add_parser("layout", help="convert one IBGE dictionary to normalized JSON")
    layout.add_argument("input", type=Path)
    layout.add_argument("output", type=Path)
    layout.add_argument("--member", help="dictionary member inside a ZIP")

    metadata = sub.add_parser("metadata", aliases=["metadados"], help="generate layout files and a catalog")
    _add_common(metadata)
    metadata.add_argument("--force", action="store_true")

    convert = sub.add_parser("convert", aliases=["microdados"], help="convert one fixed-width data file")
    convert.add_argument("input", type=Path)
    convert.add_argument("layout", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument("--member", help="data member inside a ZIP")
    convert.add_argument("--layout-member", help="dictionary member inside a ZIP")
    convert.add_argument("--encoding", default="utf-8")
    convert.add_argument("--chunk-rows", type=int, default=50_000)
    convert.add_argument("--all-string", action="store_true", help="store every Parquet field as text")
    convert.add_argument("--columns", action="append", help="keep only this layout variable (repeatable); default keeps all")
    convert.add_argument("--force", action="store_true")

    many = sub.add_parser("convert-many", help="convert all resolvable files to Parquet or CSV")
    _add_common(many)
    many.add_argument("--format", choices=("parquet", "csv"), default="parquet", help="batch output format")
    many.add_argument("--survey", choices=("trimestral", "anual"))
    many.add_argument("--year", type=int, action="append")
    many.add_argument("--quarter", type=int, choices=(1, 2, 3, 4), action="append")
    many.add_argument("--all-string", action="store_true", help="store every Parquet field as text (ignored for --format csv)")
    many.add_argument("--columns", action="append", help="keep only this layout variable (repeatable); default keeps all")
    many.add_argument("--force", action="store_true")

    panel = sub.add_parser("panel", aliases=["painel-mnt"], help="build a longitudinal panel from quarterly Parquet files")
    panel.add_argument("inputs", nargs="+", type=Path)
    panel.add_argument("--output", type=Path, required=True)
    panel.add_argument("--panel-id", required=True, help="first-wave period, for example 20121")
    panel.add_argument("--wide", action="store_true")
    panel.add_argument("--force", action="store_true")

    update = sub.add_parser("update", aliases=["pnadc-tudo"], help="sync, catalog, and optionally convert")
    _add_common(update)
    update.add_argument("--survey", choices=("trimestral", "anual", "both"), default="both")
    update.add_argument("--year", type=int, action="append")
    update.add_argument("--quarter", type=int, choices=(1, 2, 3, 4), action="append")
    update.add_argument("--convert", action="store_true", help="also create data outputs")
    update.add_argument("--format", choices=("parquet", "csv"), default="parquet", help="output format used when --convert is set")
    update.add_argument("--all-string", action="store_true", help="store every Parquet field as text (ignored for --format csv)")
    update.add_argument("--columns", action="append", help="keep only this layout variable (repeatable); default keeps all")

    doctor = sub.add_parser("doctor", help="report interpreter and dependency readiness")
    _add_common(doctor)
    doctor.add_argument("--network", action="store_true", help="also test configured HTTPS endpoints")
    return parser


def _survey_names(value: str) -> tuple[str, ...]:
    return ("trimestral", "anual") if value == "both" else (value,)


def _doctor(args: argparse.Namespace) -> int:
    settings = _settings(args)
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Archive: {settings.archive}")
    status = 0
    for package in ("requests", "yaml", "pyarrow", "xlrd", "openpyxl", "pandas"):
        present = importlib.util.find_spec(package) is not None
        print(f"{package}: {'ok' if present else 'missing'}")
        if package != "pandas" and not present:
            status = 1
    print(f"Free space: {human_size(shutil.disk_usage(settings.archive.parent).free)}")
    if args.network:
        try:
            import requests

            for name, url in settings.base_urls.items():
                response = requests.get(url, timeout=(settings.network.connect_timeout, settings.network.read_timeout))
                print(f"HTTPS {name}: {response.status_code}")
                response.raise_for_status()
        except Exception as exc:
            print(f"HTTPS: failed ({exc})")
            status = 1
    return status


def run(args: argparse.Namespace) -> int:
    if args.command == "init":
        path = init_repository(args.path)
        print(f"Initialized repository: {path.parent}")
        print(f"Configuration: {path}")
    elif args.command == "sync":
        if args.quarter and args.survey != "trimestral":
            raise ValueError("--quarter requires --survey trimestral")
        settings = _settings(args)
        result = sync_archive(
            settings,
            surveys=_survey_names(args.survey),
            years=_years(args.year),
            dry_run=args.dry_run,
            prune=args.prune,
            quarters=_years(args.quarter),
        )
        print(
            f"Discovered {result.discovered}; downloaded {result.downloaded}; "
            f"unchanged {result.unchanged}; adopted {result.adopted}; "
            f"pruned {result.pruned}; "
            f"transferred {human_size(result.bytes_downloaded)}."
        )
    elif args.command == "extract":
        processed, skipped = extract_archive(_settings(args), args.force)
        print(f"Extracted {processed} archives; skipped {skipped} unchanged archives.")
    elif args.command == "layout":
        parsed = load_layout(args.input, args.member)
        write_layout(parsed, args.output)
        print(f"Wrote {len(parsed.variables)} variables to {args.output.resolve()}.")
    elif args.command in ("metadata", "metadados"):
        catalog = generate_metadata(_settings(args), args.force)
        print(f"Cataloged {len(catalog['layouts'])} layouts and {len(catalog['microdata'])} data archives.")
    elif args.command in ("convert", "microdados"):
        result = convert_file(
            args.input, args.layout, args.output, args.member, args.layout_member,
            args.encoding, args.chunk_rows, args.all_string, args.force,
            columns=args.columns,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "convert-many":
        if args.quarter and args.survey != "trimestral":
            raise ValueError("--quarter requires --survey trimestral")
        converted, skipped, unresolved = convert_catalog(
            _settings(args),
            output_format=args.format,
            scope=args.survey,
            years=_years(args.year),
            force=args.force,
            all_string=args.all_string,
            quarters=_years(args.quarter),
            columns=args.columns,
        )
        print(f"Converted {converted}; skipped {skipped}; unresolved layouts {unresolved}.")
    elif args.command in ("panel", "painel-mnt"):
        result = build_panel(args.inputs, args.output, args.panel_id, args.wide, args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command in ("update", "pnadc-tudo"):
        if args.quarter and args.survey != "trimestral":
            raise ValueError("--quarter requires --survey trimestral")
        settings = _settings(args)
        sync_result = sync_archive(
            settings,
            surveys=_survey_names(args.survey),
            years=_years(args.year),
            quarters=_years(args.quarter),
        )
        catalog = generate_metadata(settings)
        print(f"Sync downloaded {sync_result.downloaded}; catalog has {len(catalog['microdata'])} data archives.")
        if args.convert:
            converted, skipped, unresolved = convert_catalog(
                settings,
                output_format=args.format,
                scope=None if args.survey == "both" else args.survey,
                years=_years(args.year),
                force=False,
                all_string=args.all_string,
                quarters=_years(args.quarter),
                columns=args.columns,
            )
            print(f"Converted {converted}; skipped {skipped}; unresolved layouts {unresolved}.")
    elif args.command == "doctor":
        return _doctor(args)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = logging.WARNING if args.verbose == 0 else logging.INFO if args.verbose == 1 else logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.verbose >= 2:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1
