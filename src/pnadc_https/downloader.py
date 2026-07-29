"""Incremental HTTPS mirroring of IBGE directory listings."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from zipfile import BadZipFile, ZipFile

from .config import Settings
from .utils import atomic_json, ensure_within, human_size, load_json, sha256_stream

LOG = logging.getLogger(__name__)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


@dataclass(frozen=True, slots=True)
class RemoteFile:
    survey: str
    path: str
    url: str
    size: int | None
    etag: str | None
    last_modified: str | None

    @property
    def key(self) -> str:
        return f"{self.survey}/{self.path}"


@dataclass(slots=True)
class SyncResult:
    discovered: int = 0
    downloaded: int = 0
    unchanged: int = 0
    adopted: int = 0
    pruned: int = 0
    bytes_downloaded: int = 0


class HttpClient:
    """Configured requests session with retry/backoff."""

    def __init__(self, settings: Settings) -> None:
        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("requests is required for synchronization") from exc
        retry = Retry(
            total=settings.network.retries,
            connect=settings.network.retries,
            read=settings.network.retries,
            status=settings.network.retries,
            backoff_factor=0.75,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET", "HEAD")),
        )
        self.session = requests.Session()
        self.session.headers["User-Agent"] = settings.network.user_agent
        adapter = HTTPAdapter(max_retries=retry, pool_connections=settings.network.workers)
        self.session.mount("https://", adapter)
        self.timeout = (
            settings.network.connect_timeout,
            settings.network.read_timeout,
        )

    def get_text(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def metadata(self, url: str) -> tuple[int | None, str | None, str | None]:
        response = self.session.head(url, allow_redirects=True, timeout=self.timeout)
        if response.status_code in (403, 405) or response.status_code >= 500:
            response.close()
            response = self.session.get(url, stream=True, timeout=self.timeout)
        response.raise_for_status()
        raw_size = response.headers.get("Content-Length")
        size = int(raw_size) if raw_size and raw_size.isdigit() else None
        result = (size, response.headers.get("ETag"), response.headers.get("Last-Modified"))
        response.close()
        return result

    def download(self, remote: RemoteFile, target: Path, chunk_size: int) -> tuple[int, str]:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        downloaded = 0
        with self.session.get(remote.url, stream=True, timeout=self.timeout) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    stream.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
        if remote.size is not None and downloaded != remote.size:
            temporary.unlink(missing_ok=True)
            raise IOError(
                f"Incomplete download for {remote.url}: expected {remote.size}, got {downloaded}"
            )
        os.replace(temporary, target)
        return downloaded, digest.hexdigest()


def _canonical_directory(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _child_url(root: str, current: str, href: str) -> str | None:
    if href.startswith(("?", "#")):
        return None
    candidate = urljoin(current, href)
    root_parts = urlsplit(root)
    parts = urlsplit(candidate)
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    if parts.scheme != "https" or parts.netloc != root_parts.netloc:
        return None
    decoded = unquote(parts.path)
    if not decoded.startswith(unquote(root_parts.path)):
        return None
    # urljoin resolves "../" but not its encoded form, so "..%2F..%2Fx" arrives
    # here still looking contained and only decodes to a traversal later, when
    # the local path is derived. ensure_within would catch it at that point,
    # but by aborting the whole synchronization rather than ignoring one bad
    # link. Reject it here instead.
    if ".." in PurePosixPath(decoded).parts:
        return None
    if clean == current or clean.rstrip("/") == root.rstrip("/"):
        return None
    return clean


def _period_year(relative: str) -> int | None:
    """Return the survey reference year, never a later revision date."""
    path = PurePosixPath(relative)
    for part in path.parts[:-1]:
        if re.fullmatch(r"20\d{2}", part):
            return int(part)
    match = re.search(
        r"pnadc_(?:0?[1-4])?(20\d{2})(?:_|\.|$)",
        path.name,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def _period_quarter(relative: str) -> int | None:
    """Return the quarterly release number from a PNADC filename."""
    match = re.search(
        r"pnadc_0?([1-4])(20\d{2})(?:_|\.|$)",
        PurePosixPath(relative).name,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def crawl_files(client: HttpClient, survey: str, base_url: str) -> list[tuple[str, str]]:
    """Recursively enumerate files exposed by an Apache-style HTML index."""
    root = _canonical_directory(base_url)
    pending = [root]
    visited: set[str] = set()
    found: dict[str, str] = {}
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        LOG.info("Listing %s", current)
        parser = LinkParser()
        parser.feed(client.get_text(current))
        for href in parser.links:
            child = _child_url(root, current, href)
            if not child:
                continue
            if urlsplit(child).path.endswith("/") or href.endswith("/"):
                directory = _canonical_directory(child)
                if directory not in visited:
                    pending.append(directory)
                continue
            relative = unquote(urlsplit(child).path[len(urlsplit(root).path) :])
            relative = str(PurePosixPath(relative))
            if relative not in ("", "."):
                found[relative] = child
    return sorted(found.items())


def discover_remote_files(
    settings: Settings,
    surveys: Iterable[str],
    years: set[int] | None = None,
    quarters: set[int] | None = None,
) -> list[RemoteFile]:
    client = HttpClient(settings)
    candidates: list[tuple[str, str, str]] = []
    for survey in surveys:
        if survey not in settings.base_urls:
            raise ValueError(f"Unknown survey: {survey}")
        for relative, url in crawl_files(client, survey, settings.base_urls[survey]):
            if settings.is_excluded(relative):
                continue
            lowered = relative.lower()
            shared_document = any(token in lowered for token in ("document", "dicion", "input", "layout"))
            if years and not shared_document and _period_year(relative) not in years:
                continue
            if quarters and survey == "trimestral" and not shared_document and _period_quarter(relative) not in quarters:
                continue
            candidates.append((survey, relative, url))

    remotes: list[RemoteFile] = []
    with ThreadPoolExecutor(max_workers=settings.network.workers) as pool:
        futures = {
            pool.submit(client.metadata, url): (survey, relative, url)
            for survey, relative, url in candidates
        }
        for future in as_completed(futures):
            survey, relative, url = futures[future]
            size, etag, modified = future.result()
            remotes.append(RemoteFile(survey, relative, url, size, etag, modified))
    return sorted(remotes, key=lambda item: item.key)


def _is_readable(local: Path) -> bool:
    """Cheap structural check before adopting a file we did not download.

    Reading a ZIP's central directory catches truncation and corruption
    without reading the payload, which for this archive would mean tens of
    gigabytes. It does not verify contents against IBGE — only `pnadc verify`
    does that, by checking every member's CRC.
    """
    if local.suffix.lower() != ".zip":
        return True
    try:
        with ZipFile(local) as archive:
            archive.namelist()
        return True
    except (BadZipFile, OSError) as exc:
        LOG.warning("Not adopting %s; it is not a readable ZIP (%s)", local.name, exc)
        return False


def _is_current(remote: RemoteFile, local: Path, old: dict[str, object] | None) -> bool:
    if not local.is_file() or old is None:
        return False
    if remote.size is not None and local.stat().st_size != remote.size:
        return False
    if old.get("url") != remote.url:
        return False
    for field in ("etag", "last_modified", "size"):
        current_value = getattr(remote, field)
        if current_value is not None and old.get(field) != current_value:
            return False
    return True


@dataclass(slots=True)
class VerifyResult:
    checked: int = 0
    ok: int = 0
    failed: list[str] = field(default_factory=list)
    unverifiable: int = 0


def verify_archive(settings: Settings, deep: bool = False) -> VerifyResult:
    """Check mirrored files against what the manifest recorded.

    Files this package downloaded carry a SHA-256 taken from the bytes as they
    arrived, so they can be checked exactly. Adopted files were never read in
    full and have no recorded hash; for those, ``deep`` runs a CRC check of
    every ZIP member, which is the strongest guarantee available without
    re-downloading, since IBGE publishes no checksums.
    """
    manifest = load_json(settings.manifest_path, {"files": {}})
    result = VerifyResult()
    for key, entry in sorted(manifest.get("files", {}).items()):
        result.checked += 1
        try:
            local = ensure_within(
                settings.archive / Path(str(entry.get("local", ""))),
                settings.archive,
            )
        except ValueError:
            result.failed.append(f"{key}: manifest path escapes the repository")
            continue
        if not local.is_file():
            result.failed.append(f"{key}: missing")
            continue
        size = entry.get("size")
        if size is not None and local.stat().st_size != size:
            result.failed.append(f"{key}: size {local.stat().st_size} != recorded {size}")
            continue
        recorded_hash = entry.get("sha256")
        if recorded_hash:
            with local.open("rb") as stream:
                if sha256_stream(stream) != recorded_hash:
                    result.failed.append(f"{key}: sha256 mismatch")
                    continue
            result.ok += 1
        elif deep and local.suffix.lower() == ".zip":
            try:
                with ZipFile(local) as archive:
                    bad = archive.testzip()
                if bad is not None:
                    result.failed.append(f"{key}: CRC failure in member {bad}")
                    continue
            except (BadZipFile, OSError) as exc:
                result.failed.append(f"{key}: unreadable ZIP ({exc})")
                continue
            result.ok += 1
        else:
            result.unverifiable += 1
    return result


def sync_archive(
    settings: Settings,
    surveys: Iterable[str] = ("trimestral", "anual"),
    years: set[int] | None = None,
    dry_run: bool = False,
    prune: bool = False,
    quarters: set[int] | None = None,
) -> SyncResult:
    """Synchronize selected remote trees into ``archive/originals``."""
    surveys = tuple(surveys)
    if prune and (years or quarters):
        raise ValueError("--prune cannot be combined with period filters because the remote view is partial")
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    old_manifest = load_json(settings.manifest_path, {"version": 1, "files": {}})
    old_files: dict[str, dict[str, object]] = old_manifest.get("files", {})
    remotes = discover_remote_files(settings, surveys, years, quarters)
    result = SyncResult(discovered=len(remotes))
    current_keys = {remote.key for remote in remotes}
    new_files = dict(old_files)
    downloads: list[tuple[RemoteFile, Path]] = []

    for remote in remotes:
        local = ensure_within(settings.originals / remote.survey / Path(remote.path), settings.originals)
        recorded = old_files.get(remote.key)
        if _is_current(remote, local, recorded):
            result.unchanged += 1
            continue
        # A file already on disk at exactly the remote size is adopted into the
        # manifest rather than fetched again. Without this, an archive whose
        # manifest was lost — deleted, or never written by an older version —
        # would be downloaded from scratch, which for PNADC means tens of
        # gigabytes to arrive at bytes already present.
        if recorded is None and remote.size is not None and local.is_file():
            if local.stat().st_size == remote.size and _is_readable(local):
                entry = asdict(remote)
                entry.update(
                    {
                        "local": local.relative_to(settings.archive).as_posix(),
                        "sha256": None,
                        "adopted": True,
                    }
                )
                new_files[remote.key] = entry
                result.adopted += 1
                LOG.info("Adopted existing %s (%s)", remote.key, human_size(remote.size))
                continue
        downloads.append((remote, local))
        LOG.info("Will download %s (%s)", remote.key, human_size(remote.size))

    selected_prefixes = tuple(f"{survey}/" for survey in surveys)
    stale = [
        key for key in old_files
        if key.startswith(selected_prefixes) and key not in current_keys
    ]
    if prune:
        for key in stale:
            local = ensure_within(settings.originals / Path(key), settings.originals)
            LOG.info("Will prune %s", local)
            if not dry_run:
                local.unlink(missing_ok=True)
                new_files.pop(key, None)
            result.pruned += 1

    if dry_run:
        return result

    client = HttpClient(settings)
    failures: list[tuple[RemoteFile, Exception]] = []
    with ThreadPoolExecutor(max_workers=settings.network.workers) as pool:
        futures = {
            pool.submit(client.download, remote, local, settings.network.chunk_size): (remote, local)
            for remote, local in downloads
        }
        for future in as_completed(futures):
            remote, local = futures[future]
            try:
                count, digest = future.result()
            except Exception as exc:
                failures.append((remote, exc))
                LOG.error("Could not download %s: %s", remote.key, exc)
                continue
            result.downloaded += 1
            result.bytes_downloaded += count
            entry = asdict(remote)
            entry.update(
                {"local": local.relative_to(settings.archive).as_posix(), "sha256": digest}
            )
            new_files[remote.key] = entry
            LOG.info("Downloaded %s", remote.key)

    atomic_json(settings.manifest_path, {"version": 1, "files": new_files})
    if failures:
        names = ", ".join(remote.key for remote, _ in failures[:3])
        if len(failures) > 3:
            names += f", and {len(failures) - 3} more"
        raise RuntimeError(
            f"{len(failures)} download(s) failed after successful files were recorded: {names}"
        ) from failures[0][1]
    return result
