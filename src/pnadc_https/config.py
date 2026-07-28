"""Configuration loading and archive path conventions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._version import __version__

DEFAULT_USER_AGENT = f"pnadc/{__version__}"

DEFAULT_URLS = {
    "trimestral": (
        "https://ftp.ibge.gov.br/Trabalho_e_Rendimento/"
        "Pesquisa_Nacional_por_Amostra_de_Domicilios_continua/"
        "Trimestral/Microdados/"
    ),
    "anual": (
        "https://ftp.ibge.gov.br/Trabalho_e_Rendimento/"
        "Pesquisa_Nacional_por_Amostra_de_Domicilios_continua/"
        "Anual/Microdados/"
    ),
}


@dataclass(slots=True)
class NetworkSettings:
    connect_timeout: float = 20.0
    read_timeout: float = 120.0
    retries: int = 4
    workers: int = 4
    chunk_size: int = 1024 * 1024
    user_agent: str = DEFAULT_USER_AGENT


# Parts of the IBGE tree that are excluded unless asked for. Projecoes_Anteriores
# holds population projections superseded by later revisions; IBGE keeps them so
# previously published figures can be reproduced. They are not the current
# microdata, and they are 44% of the archive by size, so a repository that mirrors
# them by default costs far more to build than it is worth to most users.
DEFAULT_EXCLUDE = ("Projecoes_Anteriores",)


@dataclass(slots=True)
class Settings:
    archive: Path = Path("archive")
    parquet: Path | None = None
    csv: Path | None = None
    base_urls: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_URLS))
    network: NetworkSettings = field(default_factory=NetworkSettings)
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE

    def is_excluded(self, relative: str) -> bool:
        """Report whether a repository-relative path is excluded."""
        lowered = relative.replace("\\", "/").lower()
        return any(token.lower() in lowered for token in self.exclude)

    def including_superseded(self) -> tuple[str, ...]:
        """Return the exclusions with only the superseded-projection default removed.

        Dropping every exclusion would silently discard whatever the user
        configured for their own reasons, so only the entries this package
        adds by default are taken out.
        """
        return tuple(token for token in self.exclude if token not in DEFAULT_EXCLUDE)

    @property
    def originals(self) -> Path:
        return self.archive / "originals"

    @property
    def state_dir(self) -> Path:
        return self.archive / ".pnadc"

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.json"

    @property
    def metadata_dir(self) -> Path:
        return self.archive / "metadata"

    @property
    def parquet_dir(self) -> Path:
        return self.parquet if self.parquet is not None else self.archive / "parquet"

    @property
    def csv_dir(self) -> Path:
        return self.csv if self.csv is not None else self.archive / "csv"


def _merge_settings(raw: dict[str, Any], base: Path) -> Settings:
    archive = Path(raw.get("archive", "archive"))
    if not archive.is_absolute():
        archive = (base / archive).resolve()
    parquet_raw = raw.get("parquet")
    parquet = Path(parquet_raw) if parquet_raw is not None else None
    if parquet is not None and not parquet.is_absolute():
        parquet = (base / parquet).resolve()
    csv_raw = raw.get("csv")
    csv = Path(csv_raw) if csv_raw is not None else None
    if csv is not None and not csv.is_absolute():
        csv = (base / csv).resolve()
    urls = dict(DEFAULT_URLS)
    urls.update(raw.get("base_urls") or {})
    # An explicit empty list in the configuration means "exclude nothing", which
    # is different from the key being absent.
    raw_exclude = raw.get("exclude", None)
    if raw_exclude is None:
        exclude = DEFAULT_EXCLUDE
    elif isinstance(raw_exclude, (str, bytes)) or not isinstance(raw_exclude, (list, tuple)):
        # A bare string iterates character by character, which would silently
        # exclude almost everything: "exclude: Projecoes_Anteriores" would
        # match any path containing "r". Refuse it rather than obey it.
        raise ValueError(
            "exclude must be a YAML list of path fragments, for example:\n"
            "  exclude:\n"
            "    - Projecoes_Anteriores\n"
            f"got {type(raw_exclude).__name__}: {raw_exclude!r}"
        )
    else:
        exclude = tuple(str(item) for item in raw_exclude)
    network_raw = raw.get("network") or {}
    network = NetworkSettings(
        connect_timeout=float(network_raw.get("connect_timeout", 20)),
        read_timeout=float(network_raw.get("read_timeout", 120)),
        retries=int(network_raw.get("retries", 4)),
        workers=max(1, int(network_raw.get("workers", 4))),
        chunk_size=max(64 * 1024, int(network_raw.get("chunk_size", 1024 * 1024))),
        user_agent=str(network_raw.get("user_agent", DEFAULT_USER_AGENT)),
    )
    return Settings(
        archive=archive,
        parquet=parquet,
        csv=csv,
        base_urls=urls,
        network=network,
        exclude=exclude,
    )


def load_settings(config: str | Path | None = None, archive: str | Path | None = None) -> Settings:
    """Load YAML settings; CLI archive overrides the configured archive."""
    raw: dict[str, Any] = {}
    base = Path.cwd()
    if config:
        config_path = Path(config).resolve()
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise RuntimeError("PyYAML is required to read configuration files") from exc
        with config_path.open("r", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream)
        if loaded is not None and not isinstance(loaded, dict):
            raise ValueError("The configuration root must be a YAML mapping")
        raw = loaded or {}
        base = config_path.parent
    settings = _merge_settings(raw, base)
    if archive is not None:
        settings.archive = Path(archive).resolve()
    return settings
