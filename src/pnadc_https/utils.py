"""Small shared helpers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, BinaryIO


def ensure_within(path: Path, root: Path) -> Path:
    """Resolve *path* and reject path traversal outside *root*."""
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"Path escapes target directory: {path}")
    return resolved


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def sha256_stream(stream: BinaryIO, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file's contents. Intended for small inputs such as dictionaries."""
    with path.open("rb") as stream:
        return sha256_stream(stream, chunk_size)


def portable_path(path: Path, root: Path | None) -> str:
    """Render *path* for storage in a metadata file.

    Paths inside *root* are written relative to it and with forward slashes,
    so that a repository stays valid when it is moved, copied to another
    machine, or read on a different operating system. A Windows-style
    relative path is not portable: ``originals\\trimestral\\x.zip`` is a
    single filename on Linux, not three path components.

    Paths outside *root* — an output directory on another volume, for
    example — cannot be expressed relatively and are kept absolute.
    """
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


def human_size(size: int | None) -> str:
    if size is None:
        return "unknown"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"
