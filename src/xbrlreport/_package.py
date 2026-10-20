"""Bounded access to report packages stored as ZIP archives or directories."""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from types import TracebackType
from typing import IO
from zipfile import BadZipFile, ZipFile, ZipInfo

from .model import Limits, ReportError

_DRIVE = re.compile(r"^[A-Za-z]:")


def check_member_name(name: str, label: str) -> None:
    """Reject absolute or parent-relative archive member names.

    Raises:
        ReportError: If the member could escape the package root.
    """
    if not name or name.startswith(("/", "\\")) or _DRIVE.match(name):
        raise ReportError(f"{label}: unsafe absolute entry {name!r}")
    if any(part == ".." for part in re.split(r"[\\/]", name)):
        raise ReportError(f"{label}: unsafe parent-relative entry {name!r}")


class Package:
    """Read-only file set of one report package."""

    def __init__(
        self,
        label: str,
        names: tuple[str, ...],
        *,
        archive: ZipFile | None = None,
        root: Path | None = None,
        limits: Limits,
    ) -> None:
        """Wrap a validated archive or directory listing."""
        self.label = label
        self.names = names
        self._name_set = frozenset(names)
        self._archive = archive
        self._root = root
        self._limits = limits

    def __enter__(self) -> Package:
        """Return the package for use as a context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the underlying archive."""
        self.close()

    def close(self) -> None:
        """Close the underlying archive, if any."""
        if self._archive is not None:
            self._archive.close()

    def __contains__(self, name: object) -> bool:
        """Return whether the package holds one file name."""
        return name in self._name_set

    def open(self, name: str) -> IO[bytes]:
        """Open one package file for streaming binary reads.

        Returns:
            IO[bytes]: Binary stream positioned at the start of the file.

        Raises:
            ReportError: If the file is missing or exceeds the size limit.
        """
        if name not in self._name_set:
            raise ReportError(f"{self.label}: missing file {name!r}")
        if self._archive is not None:
            return self._archive.open(name)
        assert self._root is not None
        path = self._root / name
        if path.stat().st_size > self._limits.max_file_size:
            raise ReportError(
                f"{self.label}: {name} exceeds the maximum file size of "
                f"{self._limits.max_file_size} bytes"
            )
        return path.open("rb")

    def read(self, name: str) -> bytes:
        """Read one package file completely.

        Returns:
            bytes: File content.
        """
        with self.open(name) as stream:
            return stream.read()


def open_zip_package(source: bytes | Path, *, label: str, limits: Limits) -> Package:
    """Open and validate a report package ZIP.

    Returns:
        Package: Validated package; the caller closes it.

    Raises:
        ReportError: If the archive is invalid, unsafe or over a limit.
    """
    try:
        archive = ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source)
    except (BadZipFile, OSError) as error:
        raise ReportError(f"{label}: not a readable ZIP archive ({error})") from error
    try:
        names = _validate_entries(archive.infolist(), label=label, limits=limits)
    except BaseException:
        archive.close()
        raise
    return Package(label, names, archive=archive, limits=limits)


def _validate_entries(
    infos: list[ZipInfo], *, label: str, limits: Limits
) -> tuple[str, ...]:
    if len(infos) > limits.max_zip_entries:
        raise ReportError(
            f"{label}: {len(infos)} ZIP entries exceed the limit of "
            f"{limits.max_zip_entries}"
        )
    seen: set[str] = set()
    names: list[str] = []
    total = 0
    for info in infos:
        name = info.filename
        check_member_name(name, label)
        if info.flag_bits & 0x1:
            raise ReportError(f"{label}: encrypted entry {name!r} is not supported")
        key = name.rstrip("/")
        if key in seen:
            raise ReportError(f"{label}: duplicate entry {name!r}")
        seen.add(key)
        if info.is_dir():
            continue
        if info.file_size > limits.max_file_size:
            raise ReportError(
                f"{label}: entry {name!r} exceeds the maximum file size of "
                f"{limits.max_file_size} bytes"
            )
        total += info.file_size
        if total > limits.max_total_size:
            raise ReportError(
                f"{label}: uncompressed size exceeds the limit of "
                f"{limits.max_total_size} bytes"
            )
        names.append(name)
    return tuple(names)


def open_directory_package(root: Path, *, limits: Limits) -> Package:
    """List a report package directory without following external links.

    Returns:
        Package: Package over the directory files.

    Raises:
        ReportError: If the directory is over a limit or links outside itself.
    """
    resolved_root = root.resolve()
    names: list[str] = []
    total = 0
    for directory, _, files in os.walk(root):
        for file_name in files:
            path = Path(directory) / file_name
            if not path.resolve().is_relative_to(resolved_root):
                raise ReportError(f"{root}: {path} links outside the package")
            if not path.is_file():
                continue
            names.append(path.relative_to(root).as_posix())
            if len(names) > limits.max_zip_entries:
                raise ReportError(
                    f"{root}: more than {limits.max_zip_entries} files in the package"
                )
            size = path.stat().st_size
            if size > limits.max_file_size:
                raise ReportError(
                    f"{root}: {names[-1]} exceeds the maximum file size of "
                    f"{limits.max_file_size} bytes"
                )
            total += size
            if total > limits.max_total_size:
                raise ReportError(
                    f"{root}: total size exceeds the limit of "
                    f"{limits.max_total_size} bytes"
                )
    return Package(str(root), tuple(sorted(names)), root=root, limits=limits)
