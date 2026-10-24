"""Offline URL resolution through local XBRL taxonomy package ZIPs."""

from __future__ import annotations

import io
import os
import posixpath
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from zipfile import ZipFile

from ._package import ZIP_ERRORS, DamagedEntryError
from ._util import join_url
from ._xmlsafe import parse_catalog_rewrites, parse_entry_points, parse_schema
from .model import Limits, ReportError

_TARGET_NAMESPACE = re.compile(rb"""targetNamespace\s*=\s*["']([^"']+)["']""")
_HEAD = 8192
XBRLDT = "http://xbrl.org/2005/xbrldt"


@dataclass(slots=True)
class Schema:
    """What the checks need from one XML schema of a taxonomy package.

    Attributes:
        namespace: The schema's target namespace.
        prefix: The prefix the schema itself binds to its target namespace,
            its author's canonical prefix (``None`` if it binds none).
        elements: Global element name to its attributes, with qname values
            such as ``type`` in Clark notation and attribute names in Clark
            notation when namespaced.
        ids: Element ``id`` to element name.
        location: ``(package index, entry name)`` of the schema.
    """

    namespace: str
    prefix: str | None
    elements: dict[str, dict[str, str]] = field(default_factory=dict)
    ids: dict[str, str] = field(default_factory=dict)
    location: tuple[int, str] = (0, "")


class TaxonomyPackages:
    """Resolve absolute URLs to files inside taxonomy package ZIPs.

    Each package's ``META-INF/catalog.xml`` (optionally below one top-level
    folder) supplies ``rewriteURI``/``rewriteSystem`` prefixes; the longest
    matching start string across all packages wins.
    """

    def __init__(
        self,
        paths: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
        *,
        limits: Limits,
    ) -> None:
        """Open every package and read its catalog.

        ``paths`` is one package path or a sequence of them.

        Raises:
            ReportError: If a package is not a readable ZIP or has no catalog.
        """
        self._limits = limits
        self._archives: list[ZipFile] = []
        self._labels: list[str] = []
        self._total = 0
        self._rewrites: list[tuple[str, int, str]] = []
        self._entry_points: set[str] = set()
        self._schema_files: dict[str, list[tuple[int, str]]] | None = None
        self._schemas: dict[tuple[int, str], Schema | None] = {}
        try:
            for path in [paths] if isinstance(paths, str | os.PathLike) else paths:
                self._add(Path(path).expanduser())
        except BaseException:
            self.close()
            raise
        self._rewrites.sort(key=lambda item: len(item[0]), reverse=True)

    def _add(self, path: Path) -> None:
        label = str(path)
        try:
            archive = ZipFile(path)
        except ZIP_ERRORS as error:
            raise ReportError(
                f"{label}: not a readable taxonomy package ZIP ({error})"
            ) from error
        self._archives.append(archive)
        self._labels.append(label)
        self._check_entries(archive, label)
        if self._catalogs(archive):
            self._add_catalogs(archive, label)
            return
        # The EBA publishes its packages as ZIPs inside one ZIP.
        inner = [
            info
            for info in archive.infolist()
            if "/" not in info.filename.rstrip("/")
            and info.filename.casefold().endswith(".zip")
        ]
        if not inner:
            raise ReportError(f"{label}: taxonomy package has no META-INF/catalog.xml")
        total = sum(info.file_size for info in inner)
        if total > self._limits.max_total_size:
            raise ReportError(
                f"{label}: inner taxonomy packages exceed the maximum total size "
                f"of {self._limits.max_total_size} bytes"
            )
        for info in inner:
            inner_label = f"{label}!{info.filename}"
            data = self._read(archive, info.filename, label)
            try:
                nested = ZipFile(io.BytesIO(data))
            except ZIP_ERRORS as error:
                raise ReportError(
                    f"{inner_label}: not a readable taxonomy package ZIP ({error})"
                ) from error
            self._archives.append(nested)
            self._labels.append(inner_label)
            self._check_entries(nested, inner_label)
            if not self._catalogs(nested):
                raise ReportError(
                    f"{inner_label}: taxonomy package has no META-INF/catalog.xml"
                )
            self._add_catalogs(nested, inner_label)

    @staticmethod
    def _catalogs(archive: ZipFile) -> list[str]:
        return [
            name
            for name in archive.namelist()
            if name.count("/") <= 2 and name.casefold().endswith("meta-inf/catalog.xml")
        ]

    def _add_catalogs(self, archive: ZipFile, label: str) -> None:
        index = len(self._archives) - 1
        for catalog in self._catalogs(archive):
            base = posixpath.dirname(catalog)
            data = self._read(archive, catalog, label)
            for start, prefix in parse_catalog_rewrites(data, f"{label}!{catalog}"):
                target = prefix
                if "://" not in prefix:
                    target = posixpath.join(base, prefix)
                self._rewrites.append((start, index, target))
            metadata = posixpath.join(base, "taxonomyPackage.xml")
            if metadata in archive.NameToInfo:
                self._entry_points.update(
                    parse_entry_points(
                        self._read(archive, metadata, label), f"{label}!{metadata}"
                    )
                )

    def _check_entries(self, archive: ZipFile, label: str) -> None:
        count = len(archive.infolist())
        if count > self._limits.max_taxonomy_entries:
            raise ReportError(
                f"{label}: {count} ZIP entries exceed the limit of "
                f"{self._limits.max_taxonomy_entries} for a taxonomy package"
            )

    def _count(self, size: int, label: str) -> None:
        """Add bytes read from the packages to the total, within the limit.

        Raises:
            ReportError: If the bytes read exceed ``Limits.max_total_size``.
        """
        self._total += size
        if self._total > self._limits.max_total_size:
            raise ReportError(
                f"{label}: files read from the taxonomy packages exceed the "
                f"total size limit of {self._limits.max_total_size} bytes"
            )

    def _read(self, archive: ZipFile, name: str, label: str) -> bytes:
        info = archive.getinfo(name)
        if info.file_size > self._limits.max_file_size:
            raise ReportError(
                f"{label}: {name} exceeds the maximum file size of "
                f"{self._limits.max_file_size} bytes"
            )
        self._count(info.file_size, label)
        try:
            return archive.read(info)
        except ZIP_ERRORS as error:
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
                return self._read(archive, member, self._labels[index])
            except KeyError:
                continue
        return None

    @property
    def entry_points(self) -> frozenset[str]:
        """The entry point URLs that the packages' ``taxonomyPackage.xml`` list.

        Returns:
            frozenset[str]: Absolute entry point document URLs.
        """
        return frozenset(self._entry_points)

    def _index_schemas(self) -> dict[str, list[tuple[int, str]]]:
        """Map each target namespace to the package schemas declaring it.

        Only the start of each ``.xsd`` entry is read.

        Returns:
            dict: Namespace URI to ``(package index, entry name)`` pairs.
        """
        if self._schema_files is None:
            self._schema_files = {}
            for index, archive in enumerate(self._archives):
                for info in archive.infolist():
                    if not info.filename.endswith(".xsd") or info.is_dir():
                        continue
                    self._count(min(info.file_size, _HEAD), self._labels[index])
                    try:
                        with archive.open(info) as stream:
                            head = stream.read(_HEAD)
                    except ZIP_ERRORS:
                        continue
                    match = _TARGET_NAMESPACE.search(head)
                    if match:
                        namespace = match.group(1).decode("utf-8", "replace")
                        self._schema_files.setdefault(namespace, []).append(
                            (index, info.filename)
                        )
        return self._schema_files

    def _schema_at(self, location: tuple[int, str]) -> Schema | None:
        if location not in self._schemas:
            index, name = location
            archive = self._archives[index]
            try:
                data = self._read(archive, name, self._labels[index])
            except KeyError:
                self._schemas[location] = None
                return None
            parsed = parse_schema(data, f"{self._labels[index]}!{name}")
            schema = Schema(
                namespace=parsed.namespace,
                prefix=parsed.prefix,
                elements=parsed.elements,
                ids=parsed.ids,
                location=location,
            )
            self._schemas[location] = schema
        return self._schemas[location]

    def schemas(self, namespace: str) -> list[Schema]:
        """Return the package schemas whose target namespace is ``namespace``.

        Returns:
            list[Schema]: Parsed schemas, in package order.
        """
        return [
            schema
            for location in self._index_schemas().get(namespace, [])
            if (schema := self._schema_at(location)) is not None
        ]

    def element(self, clark: str) -> tuple[Schema, dict[str, str]] | None:
        """Find the global element declaration of a Clark-notation name.

        Returns:
            tuple | None: The schema and the element's attributes, or
            ``None`` when no package schema declares it.
        """
        namespace, _, local = clark[1:].partition("}")
        for schema in self.schemas(namespace):
            attributes = schema.elements.get(local)
            if attributes is not None:
                return schema, attributes
        return None

    def typed_domain(self, dimension: str) -> tuple[str, str | None] | None:
        """Return the typed domain element of a typed dimension.

        The dimension's ``xbrldt:typedDomainRef`` names the element by
        ``schema#id``, relative to the dimension's schema.

        Args:
            dimension: The typed dimension in Clark notation.

        Returns:
            tuple | None: The domain element in Clark notation and the
            canonical prefix of its namespace, or ``None`` if the dimension
            or its domain is not in the packages.
        """
        found = self.element(dimension)
        reference = found[1].get(f"{{{XBRLDT}}}typedDomainRef") if found else None
        if found is None or not reference:
            return None
        schema = found[0]
        href, _, fragment = reference.partition("#")
        index, name = schema.location
        if "://" in href:
            target = None
            for start, archive_index, prefix in self._rewrites:
                if href.startswith(start) and "://" not in prefix:
                    target = (
                        archive_index,
                        posixpath.normpath(prefix + href[len(start) :]),
                    )
                    break
        elif href:
            joined = join_url(name, href)
            target = None if joined is None else (index, posixpath.normpath(joined))
        else:
            target = schema.location
        domain = self._schema_at(target) if target else None
        local = domain.ids.get(fragment) if domain else None
        if domain is None or local is None:
            return None
        return f"{{{domain.namespace}}}{local}", domain.prefix

    def close(self) -> None:
        """Close every opened package."""
        for archive in self._archives:
            archive.close()
        self._archives.clear()
