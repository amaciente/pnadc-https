"""High-level Python API for a local PNAD Continua repository."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .config import DEFAULT_USER_AGENT, Settings, load_settings
from .convert import convert_catalog
from .downloader import SyncResult, sync_archive
from .metadata import generate_metadata

REPOSITORY_DIRECTORIES = (
    "originals/anual",
    "originals/trimestral",
    "metadata/layouts",
    "parquet",
    "csv",
    ".pnadc",
)


def init_repository(path: str | Path) -> Path:
    """Create an empty repository skeleton and return its configuration path.

    The generated ``pnadc.yml`` uses paths relative to itself, so the whole
    directory can be moved or shared without editing the configuration. An
    existing configuration is never overwritten.
    """
    root = Path(path).resolve()
    config_path = root / "pnadc.yml"
    if config_path.exists():
        raise FileExistsError(f"Configuration already exists: {config_path}")
    for relative in REPOSITORY_DIRECTORIES:
        (root / relative).mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "# Paths are resolved relative to this configuration file.\n"
        "archive: .\n"
        "parquet: parquet\n"
        "csv: csv\n"
        "network:\n"
        "  connect_timeout: 20\n"
        "  read_timeout: 120\n"
        "  retries: 4\n"
        "  workers: 4\n"
        "  chunk_size: 1048576\n"
        f"  user_agent: {DEFAULT_USER_AGENT}\n",
        encoding="utf-8",
        newline="\n",
    )
    return config_path


class Repository:
    """Configure and operate a PNAD Continua repository.

    Parameters are identical to :func:`pnadc.load_settings`.  The class is a
    thin, stable façade over the lower-level modules used by the CLI.
    """

    def __init__(
        self,
        config: str | Path | None = None,
        *,
        archive: str | Path | None = None,
        include_superseded: bool = False,
    ) -> None:
        self.settings: Settings = load_settings(config, archive)
        if include_superseded:
            # Process Projecoes_Anteriores too; see config.DEFAULT_EXCLUDE.
            self.settings.exclude = ()

    def sync(
        self,
        *,
        surveys: Iterable[str] = ("trimestral", "anual"),
        years: Iterable[int] | None = None,
        quarters: Iterable[int] | None = None,
        dry_run: bool = False,
        prune: bool = False,
    ) -> SyncResult:
        """Discover and incrementally download original IBGE files."""
        return sync_archive(
            self.settings,
            surveys=tuple(surveys),
            years=set(years) if years is not None else None,
            quarters=set(quarters) if quarters is not None else None,
            dry_run=dry_run,
            prune=prune,
        )

    def catalog(self, *, force: bool = False) -> dict[str, object]:
        """Parse dictionaries and rebuild the local metadata catalog."""
        return generate_metadata(self.settings, force=force)

    def standardize(
        self,
        *,
        output_format: str = "parquet",
        survey: str | None = None,
        years: Iterable[int] | None = None,
        quarters: Iterable[int] | None = None,
        columns: Iterable[str] | None = None,
        all_string: bool = False,
        force: bool = False,
    ) -> tuple[int, int, int]:
        """Convert cataloged fixed-width files to standardized outputs."""
        return convert_catalog(
            self.settings,
            output_format=output_format,
            scope=survey,
            years=set(years) if years is not None else None,
            quarters=set(quarters) if quarters is not None else None,
            columns=columns,
            all_string=all_string,
            force=force,
        )

    def update(
        self,
        *,
        surveys: Iterable[str] = ("trimestral", "anual"),
        years: Iterable[int] | None = None,
        quarters: Iterable[int] | None = None,
        convert: bool = True,
        output_format: str = "parquet",
        columns: Iterable[str] | None = None,
    ) -> dict[str, object]:
        """Synchronize, catalog, and optionally standardize in one call."""
        survey_names = tuple(surveys)
        year_set = set(years) if years is not None else None
        quarter_set = set(quarters) if quarters is not None else None
        synced = sync_archive(
            self.settings,
            surveys=survey_names,
            years=year_set,
            quarters=quarter_set,
        )
        catalog = generate_metadata(self.settings)
        result: dict[str, object] = {
            "sync": synced,
            "cataloged": len(catalog.get("microdata", [])),
        }
        if convert:
            scope = survey_names[0] if len(survey_names) == 1 else None
            result["conversion"] = convert_catalog(
                self.settings,
                output_format=output_format,
                scope=scope,
                years=year_set,
                quarters=quarter_set,
                columns=columns,
            )
        return result

