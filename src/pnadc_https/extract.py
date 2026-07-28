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
        if settings.is_excluded(key):
            continue
        fingerprint = _source_fingerprint(source)
        previous = records.get(key, {})
        if not force and previous.get("source") == fingerprint:
            skipped += 1
            continue
        target = settings.archive / "extracted" / relative.with_suffix("")
        # Reaching this point means the archive is new, changed, or a rebuild
        # was demanded, so its members are always rewritten. Extracting with
        # force=False here would keep the previous revision's files while
        # recording the new fingerprint, leaving the repository permanently
        # convinced that stale content is current.
        outputs = extract_zip(source, target, force=True)
        current = [path.relative_to(settings.archive).as_posix() for path in outputs]
        # Members dropped from the new revision would otherwise survive
        # indefinitely alongside the files that replaced them.
        for stale in set(previous.get("outputs") or ()) - set(current):
            obsolete = settings.archive / Path(stale)
            try:
                ensure_within(obsolete, settings.archive / "extracted").unlink(missing_ok=True)
                LOG.info("Removed extracted member no longer in %s: %s", relative, stale)
            except ValueError:
                LOG.warning("Refusing to remove path outside the archive: %s", stale)
        records[key] = {"source": fingerprint, "outputs": current}
        processed += 1
        LOG.info("Extracted %s", relative)
    atomic_json(state_path, state)
    return processed, skipped

