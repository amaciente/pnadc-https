"""Build a reproducible catalog linking original data and dictionaries."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .config import Settings
from .layouts import Layout, load_layout, write_layout
from .utils import atomic_json, load_json, portable_path, sha256_file

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class DictionarySource:
    path: Path
    member: str | None
    scope: str
    year: int | None
    anual_kind: str | None = None
    years: frozenset[int] = frozenset()


def _scope(path: Path) -> str:
    lowered = "/".join(path.parts).lower()
    if "trimestral" in lowered:
        return "trimestral"
    if "anual" in lowered:
        return "anual"
    return "unknown"


def _anual_kind(path: Path) -> str | None:
    """Distinguish IBGE's two incompatible products under ``Anual/Microdados``.

    ``Visita/Visita_1``..``Visita_5`` (annual per-interview data) and
    ``Trimestre/Trimestre_1``..``Trimestre_4`` (annual per-topic supplements)
    are separate surveys with unrelated dictionaries that merely share the
    same "anual" URL tree. A dictionary from one must never be matched to
    data from the other.
    """
    lowered = "/".join(path.parts).lower()
    if "visita" in lowered:
        return "visita"
    if "trimestre" in lowered:
        return "trimestre"
    return None


def _year(text: str) -> int | None:
    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", text)
    return int(match.group(1)) if match else None


def _covered_years(text: str) -> set[int]:
    """Return every survey year a dictionary applies to.

    IBGE publishes some annual dictionaries for a span of years rather than
    one, naming them like ``dicionario_PNADC_microdados_2012_a_2014_visita1``.
    Reading only the first year would leave 2013 and 2014 microdata with no
    dictionary at all, so the whole span is expanded.
    """
    span = re.search(r"(?<!\d)(20\d{2})_a_(20\d{2})(?!\d)", text, flags=re.IGNORECASE)
    if span:
        first, last = int(span.group(1)), int(span.group(2))
        if first <= last:
            return set(range(first, last + 1))
    single = _year(text)
    return {single} if single is not None else set()


def _slug(source: DictionarySource) -> str:
    member = Path(source.member).stem if source.member else source.path.stem
    cleaned = re.sub(r"[^a-z0-9]+", "-", member.lower()).strip("-")
    prefix = source.scope
    if source.anual_kind:
        prefix += f"-{source.anual_kind}"
    if source.year:
        prefix += f"-{source.year}"
    return f"{prefix}-{cleaned}"


def _dictionary_sources(settings: Settings) -> list[DictionarySource]:
    found: list[DictionarySource] = []
    for path in sorted(settings.originals.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        relative = path.relative_to(settings.originals)
        # Excluded trees are ignored even when already on disk, so that a
        # previously downloaded copy is not silently cataloged and converted.
        if settings.is_excluded(relative.as_posix()):
            continue
        scope = _scope(relative)
        kind = _anual_kind(relative)
        if suffix in (".xls", ".xlsx") and any(
            token in path.name.lower() for token in ("dicion", "input", "layout")
        ):
            found.append(
                DictionarySource(
                    path, None, scope, _year(path.name), kind,
                    frozenset(_covered_years(path.name)),
                )
            )
        elif suffix == ".zip" and any(
            token in path.name.lower() for token in ("dicion", "input", "document")
        ):
            try:
                with ZipFile(path) as archive:
                    for member in archive.namelist():
                        if member.lower().endswith((".xls", ".xlsx")) and any(
                            token in Path(member).name.lower() for token in ("dicion", "input", "layout")
                        ):
                            found.append(
                                DictionarySource(
                                    path, member, scope,
                                    _year(member) or _year(path.name), kind,
                                    frozenset(
                                        _covered_years(member) or _covered_years(path.name)
                                    ),
                                )
                            )
            except BadZipFile:
                LOG.warning("Skipping invalid ZIP while cataloging dictionaries: %s", path)
    unique: dict[tuple[Path, str | None], DictionarySource] = {
        (item.path, item.member): item for item in found
    }
    return list(unique.values())


def _microdata_sources(settings: Settings) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(settings.originals.rglob("*.zip")):
        if settings.is_excluded(path.relative_to(settings.originals).as_posix()):
            continue
        try:
            with ZipFile(path) as archive:
                members = [
                    name for name in archive.namelist()
                    if not name.endswith("/") and name.lower().endswith((".txt", ".dat"))
                ]
        except BadZipFile:
            LOG.warning("Skipping invalid ZIP while cataloging microdata: %s", path)
            continue
        if not members:
            continue
        relative = path.relative_to(settings.archive)
        text = f"{relative.as_posix()} {' '.join(members)}"
        period = _year(text)
        quarter_match = re.search(r"(?:^|[_./-])([1-4])(?:tri|t)?[_./-]?(20\d{2})", text.lower())
        if not quarter_match:
            quarter_match = re.search(r"(?:^|[_./-])(20\d{2})[_./-]?([1-4])(?:t|tri)?", text.lower())
            quarter = int(quarter_match.group(2)) if quarter_match else None
        else:
            quarter = int(quarter_match.group(1))
        if quarter is None:
            compact_quarter = re.search(r"(?:^|[_./-])0?([1-4])(20\d{2})(?:[_./-]|$)", text.lower())
            quarter = int(compact_quarter.group(1)) if compact_quarter else None
        records.append(
            {
                "source": relative.as_posix(),
                "member": members[0] if len(members) == 1 else None,
                "members": members,
                "scope": _scope(relative),
                "anual_kind": _anual_kind(relative),
                "year": period,
                "quarter": quarter,
                "size": path.stat().st_size,
            }
        )
    return records


def _layout_score(data: dict[str, object], layout: dict[str, object]) -> int:
    score = 0
    if data["scope"] == layout["scope"]:
        score += 100
    if data.get("year") and data.get("year") == layout.get("year"):
        score += 30
    elif data.get("year") and data.get("year") in set(layout.get("years") or ()):
        score += 25  # covered by a multi-year dictionary, but less specific
    elif layout.get("year") is None:
        score += 10
    data_parent = Path(str(data["source"])).parent.parts
    layout_parent = Path(str(layout["source"])).parent.parts
    score += sum(1 for left, right in zip(data_parent, layout_parent) if left == right)
    return score


def _choose_layout(data: dict[str, object], layouts: list[dict[str, object]]) -> dict[str, object] | None:
    same_scope = [item for item in layouts if item.get("scope") == data.get("scope")]
    if data.get("scope") == "anual":
        kind = data.get("anual_kind")
        if kind is not None:
            # Visita and Trimestre are separate surveys with unrelated
            # dictionaries; never let one satisfy the other. Only narrow
            # down when we can positively identify both sides, so unusual
            # layouts (for example Projecoes_Anteriores) still fall back
            # to the permissive match below instead of resolving to nothing.
            same_kind = [item for item in same_scope if item.get("anual_kind") == kind]
            if same_kind:
                same_scope = same_kind
        if data.get("year"):
            # A dictionary may cover a span of years, so match against the
            # whole span rather than only the first year in its filename.
            exact = [
                item
                for item in same_scope
                if data.get("year") in set(item.get("years") or ())
                or item.get("year") == data.get("year")
            ]
            generic = [item for item in same_scope if item.get("year") is None]
            candidates = exact or generic
        else:
            candidates = same_scope
    else:
        candidates = same_scope
    if not candidates:
        return None
    return max(candidates, key=lambda item: _layout_score(data, item))


def _layout_is_current(target: Path, dictionary_sha256: str) -> bool:
    """Report whether a parsed layout still matches its source dictionary.

    A layout written before hashes were recorded has no ``dictionary_sha256``
    and cannot prove it is current, so it is reparsed once.
    """
    existing = load_json(target, None)
    if not isinstance(existing, dict):
        return False
    recorded = (existing.get("source") or {}).get("dictionary_sha256")
    return recorded == dictionary_sha256


def generate_metadata(settings: Settings, force: bool = False) -> dict[str, object]:
    """Parse all local dictionaries and inventory all local microdata archives."""
    layouts_dir = settings.metadata_dir / "layouts"
    layouts_dir.mkdir(parents=True, exist_ok=True)
    layout_records: list[dict[str, object]] = []
    used_names: set[str] = set()
    for source in _dictionary_sources(settings):
        slug = _slug(source)
        base_slug = slug
        counter = 2
        while slug in used_names:
            slug = f"{base_slug}-{counter}"
            counter += 1
        used_names.add(slug)
        target = layouts_dir / f"{slug}.json"
        # A dictionary that IBGE revised in place must not keep its old parsed
        # layout. Compare the dictionary's hash with the one recorded in the
        # existing layout, and reparse whenever it differs or is absent.
        dictionary_sha256 = sha256_file(source.path)
        if force or not _layout_is_current(target, dictionary_sha256):
            layout: Layout = load_layout(source.path, source.member)
            layout.source.update(
                {
                    "archive_path": portable_path(source.path, settings.archive),
                    "archive_member": source.member or "",
                    "dictionary_sha256": dictionary_sha256,
                }
            )
            # load_layout records the absolute path it was read from, which is
            # machine-specific; archive_path above replaces it.
            layout.source.pop("path", None)
            write_layout(layout, target)
            LOG.info("Parsed dictionary %s", source.path.name)
        layout_records.append(
            {
                "id": slug,
                "scope": source.scope,
                "anual_kind": source.anual_kind,
                "year": source.year,
                "years": sorted(source.years),
                "source": portable_path(source.path, settings.archive),
                "member": source.member,
                "layout": portable_path(target, settings.archive),
            }
        )
        LOG.info("Cataloged layout %s", slug)

    microdata = _microdata_sources(settings)
    for data in microdata:
        choice = _choose_layout(data, layout_records)
        data["layout"] = choice["layout"] if choice else None
        data["layout_id"] = choice["id"] if choice else None

    catalog: dict[str, object] = {
        "schema_version": 2,
        # Every path below is relative to the repository root and uses forward
        # slashes, so the catalog stays valid when the repository is moved or
        # read on another operating system. The root itself is deliberately
        # not recorded: it is machine-specific and comes from the
        # configuration at read time.
        "paths_relative_to": "repository root",
        "layouts": layout_records,
        "microdata": microdata,
    }
    atomic_json(settings.metadata_dir / "catalog.json", catalog)
    return catalog
