"""Safe, incremental ZIP extraction."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .config import Settings
from .utils import atomic_json, ensure_within, load_json

LOG = logging.getLogger(__name__)


def _source_fingerprint(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def extract_zip(source: Path, target: Path, force: bool = False) -> list[Path]:
    """Extract one ZIP without permitting absolute or parent-traversal paths."""
    extracted: list[Path] = []
    target.mkdir(parents=True, exist_ok=True)
    try:
        archive = ZipFile(source)
    except BadZipFile as exc:
        raise ValueError(f"Not a valid ZIP archive: {source}") from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = Path(info.filename.replace("\\", "/"))
            if member.is_absolute() or ".." in member.parts:
                raise ValueError(f"Unsafe ZIP member in {source}: {info.filename}")
            destination = ensure_within(target / member, target)
            if destination.exists() and not force:
                extracted.append(destination)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".part")
            with archive.open(info) as src, temporary.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
            os.replace(temporary, destination)
            extracted.append(destination)
    return extracted


def extract_archive(settings: Settings, force: bool = False) -> tuple[int, int]:
    """Extract every mirrored ZIP into a parallel ``extracted`` tree."""
    state_path = settings.state_dir / "extracted.json"
    state: dict[str, dict[str, object]] = load_json(state_path, {"files": {}})
    records = state.setdefault("files", {})
    processed = skipped = 0
    for source in sorted(settings.originals.rglob("*.zip")):
        relative = source.relative_to(settings.originals)
        key = relative.as_posix()
        fingerprint = _source_fingerprint(source)
        if not force and records.get(key, {}).get("source") == fingerprint:
            skipped += 1
            continue
        target = settings.archive / "extracted" / relative.with_suffix("")
        outputs = extract_zip(source, target, force=force)
        records[key] = {
            "source": fingerprint,
            "outputs": [str(path.relative_to(settings.archive)) for path in outputs],
        }
        processed += 1
        LOG.info("Extracted %s", relative)
    atomic_json(state_path, state)
    return processed, skipped

