"""Offline URL resolution through local XBRL taxonomy package ZIPs."""

from __future__ import annotations

import posixpath
from collections.abc import Sequence
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from ._package import DAMAGED_ENTRY_ERRORS, DamagedEntryError
from ._xmlsafe import parse_catalog_rewrites
from .model import Limits, ReportError


class TaxonomyPackages:
    """Resolve absolute URLs to files inside taxonomy package ZIPs.

    Each package's ``META-INF/catalog.xml`` (optionally below one top-level
    folder) supplies ``rewriteURI``/``rewriteSystem`` prefixes; the longest
    matching start string across all packages wins.
    """

    def __init__(self, paths: Sequence[str | Path], *, limits: Limits) -> None:
        """Open every package and read its catalog.

        Raises:
            ReportError: If a package is not a readable ZIP or has no catalog.
        """
        self._limits = limits
        self._archives: list[ZipFile] = []
        self._rewrites: list[tuple[str, int, str]] = []
        try:
            for path in paths:
                self._add(Path(path).expanduser())
        except BaseException:
            self.close()
            raise
        self._rewrites.sort(key=lambda item: len(item[0]), reverse=True)

    def _add(self, path: Path) -> None:
        label = str(path)
        try:
            archive = ZipFile(path)
        except (BadZipFile, OSError) as error:
            raise ReportError(
                f"{label}: not a readable taxonomy package ZIP ({error})"
            ) from error
        self._archives.append(archive)
        index = len(self._archives) - 1
        catalogs = [
            name
            for name in archive.namelist()
            if name.count("/") <= 2 and name.casefold().endswith("meta-inf/catalog.xml")
        ]
        if not catalogs:
            raise ReportError(f"{label}: taxonomy package has no META-INF/catalog.xml")
        for catalog in catalogs:
            base = posixpath.dirname(catalog)
            data = self._read(archive, catalog, label)
            for start, prefix in parse_catalog_rewrites(data, f"{label}!{catalog}"):
                target = prefix
                if "://" not in prefix:
                    target = posixpath.join(base, prefix)
                self._rewrites.append((start, index, target))

    def _read(self, archive: ZipFile, name: str, label: str) -> bytes:
        info = archive.getinfo(name)
        if info.file_size > self._limits.max_file_size:
            raise ReportError(
                f"{label}: {name} exceeds the maximum file size of "
                f"{self._limits.max_file_size} bytes"
            )
        try:
            return archive.read(info)
        except (*DAMAGED_ENTRY_ERRORS, RuntimeError) as error:
            # RuntimeError: an encrypted entry.
            raise DamagedEntryError(label, name, error) from error

    def resolve(self, url: str) -> bytes | None:
        """Return the package file mapped to one absolute URL.

        Returns:
            bytes | None: File content, or ``None`` when no package maps it.
        """
        for start, index, target in self._rewrites:
            if not url.startswith(start) or "://" in target:
                continue
            member = posixpath.normpath(target + url[len(start) :])
            if member.startswith(("../", "/")):
                continue
            archive = self._archives[index]
            try:
                return self._read(archive, member, archive.filename or "")
            except KeyError:
                continue
        return None

    def close(self) -> None:
        """Close every opened package."""
        for archive in self._archives:
            archive.close()
        self._archives.clear()
