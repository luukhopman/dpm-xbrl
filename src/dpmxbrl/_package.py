"""Bounded access to report packages stored as ZIP archives or directories."""

from __future__ import annotations

import io
import os
import re
import struct
import zlib
from pathlib import Path
from types import TracebackType
from typing import IO, cast
from zipfile import (
    ZIP_BZIP2,
    ZIP_DEFLATED,
    ZIP_LZMA,
    ZIP_STORED,
    BadZipFile,
    ZipFile,
    ZipInfo,
    is_zipfile,
)

from .model import Limits, ReportError

try:
    # Intel ISA-L inflates about twice as fast as zlib (the "fast" extra).
    from isal import isal_zlib as _fast_zlib

    # isal's type stubs declare its error class as an instance.
    _FAST_ZLIB_ERRORS: tuple[type[Exception], ...] = (
        cast("type[Exception]", _fast_zlib.error),
    )
except ImportError:
    _fast_zlib = None
    _FAST_ZLIB_ERRORS = ()

_DRIVE = re.compile(r"^[A-Za-z]:")
# A ZIP local file header: signature, then the name and extra field lengths.
_LOCAL_HEADER = struct.Struct("<4s22xHH")
_LOCAL_SIGNATURE = b"PK\x03\x04"
ZIP_ERRORS: tuple[type[Exception], ...] = (
    BadZipFile,
    OSError,
    ValueError,
    EOFError,
    NotImplementedError,
    UnicodeDecodeError,
    zlib.error,
    RuntimeError,
    *_FAST_ZLIB_ERRORS,
)
"""What zipfile raises for a damaged archive or entry: a bad directory,
damaged compressed data, an unknown compression method or version, an
encrypted entry, an undecodable name or an impossible offset."""
DAMAGED_ENTRY_ERRORS = ZIP_ERRORS
_COMPRESSION_METHODS = frozenset({ZIP_STORED, ZIP_DEFLATED, ZIP_BZIP2, ZIP_LZMA})


def is_zip(source: IO[bytes] | Path) -> bool:
    """Whether the input has a ZIP directory; a damaged one is not a ZIP.

    Returns:
        bool: What ``zipfile.is_zipfile`` says, or ``False`` if it fails.
    """
    try:
        return is_zipfile(source)
    except ZIP_ERRORS:
        return False


class DamagedEntryError(ReportError):
    """A package entry whose compressed data cannot be decompressed."""

    def __init__(self, label: str, name: str, error: Exception) -> None:
        """Describe the entry and the decompression error."""
        super().__init__(f"{label}: {name} is damaged and cannot be read ({error})")


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
        source: bytes | Path | None = None,
        root: Path | None = None,
        limits: Limits,
    ) -> None:
        """Wrap a validated archive or directory listing."""
        self.label = label
        self.names = names
        self._name_set = frozenset(names)
        self._archive = archive
        self._source = source
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

    @property
    def is_archive(self) -> bool:
        """Whether the package is a ZIP archive rather than a directory."""
        return self._archive is not None

    def __contains__(self, name: object) -> bool:
        """Return whether the package holds one file name."""
        return name in self._name_set

    def open(self, name: str) -> IO[bytes]:
        """Open one package file for streaming binary reads.

        Returns:
            IO[bytes]: Binary stream positioned at the start of the file.

        Raises:
            ReportError: If the file is missing or exceeds the size limit.
            DamagedEntryError: If the entry's header cannot be read.
        """
        if name not in self._name_set:
            raise ReportError(f"{self.label}: missing file {name!r}")
        if self._archive is not None:
            try:
                return self._archive.open(name)
            except ZIP_ERRORS as error:
                raise DamagedEntryError(self.label, name, error) from error
        assert self._root is not None
        path = self._root / name
        try:
            # Checked again: the file may have changed since it was listed.
            if not path.resolve().is_relative_to(self._root.resolve()):
                raise ReportError(f"{self.label}: {name} links outside the package")
            if path.stat().st_size > self._limits.max_file_size:
                raise ReportError(
                    f"{self.label}: {name} exceeds the maximum file size of "
                    f"{self._limits.max_file_size} bytes"
                )
            return path.open("rb")
        except OSError as error:
            raise ReportError(
                f"{self.label}: {name} cannot be read ({error.strerror})"
            ) from error

    def read(self, name: str) -> bytes:
        """Read one package file completely.

        Returns:
            bytes: File content.

        Raises:
            DamagedEntryError: If the file's compressed data is damaged.
        """
        if self._archive is not None and name in self._name_set:
            try:
                data = self._inflate(self._archive.getinfo(name))
            except ZIP_ERRORS as error:
                raise DamagedEntryError(self.label, name, error) from error
            if data is not None:
                return data
        with self.open(name) as stream:
            try:
                return stream.read()
            except DAMAGED_ENTRY_ERRORS as error:
                raise DamagedEntryError(self.label, name, error) from error

    def _inflate(self, info: ZipInfo) -> bytes | None:
        """Inflate a deflated entry with ISA-L, or return ``None`` for zipfile.

        Anything unexpected (another compression method, an unusual local
        header, a size or CRC that does not match the central directory) is
        left to zipfile, which reads the entry the standard way and reports
        its errors.

        Returns:
            bytes | None: The entry's content, or ``None`` to read it with zipfile.
        """
        if _fast_zlib is None or self._source is None:
            return None
        if info.compress_type != ZIP_DEFLATED:
            return None
        with (
            io.BytesIO(self._source)
            if isinstance(self._source, bytes)
            else self._source.open("rb")
        ) as stream:
            stream.seek(info.header_offset)
            header = stream.read(_LOCAL_HEADER.size)
            if len(header) != _LOCAL_HEADER.size:
                return None
            signature, name_length, extra_length = _LOCAL_HEADER.unpack(header)
            if signature != _LOCAL_SIGNATURE:
                return None
            stream.seek(name_length + extra_length, os.SEEK_CUR)
            compressed = stream.read(info.compress_size)
        try:
            # Never produce more than the declared size, whatever the data holds.
            data = _fast_zlib.decompressobj(-15).decompress(
                compressed, info.file_size + 1
            )
        except _FAST_ZLIB_ERRORS:
            return None
        if len(data) != info.file_size or _fast_zlib.crc32(data) != info.CRC:
            return None
        return data


def open_zip_package(source: bytes | Path, *, label: str, limits: Limits) -> Package:
    """Open and validate a report package ZIP.

    Returns:
        Package: Validated package; the caller closes it.

    Raises:
        ReportError: If the archive is invalid, unsafe or over a limit.
    """
    try:
        archive = ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source)
    except ZIP_ERRORS as error:
        raise ReportError(f"{label}: not a readable ZIP archive ({error})") from error
    try:
        names = _validate_entries(archive.infolist(), label=label, limits=limits)
    except BaseException:
        archive.close()
        raise
    return Package(label, names, archive=archive, source=source, limits=limits)


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
        if info.compress_type not in _COMPRESSION_METHODS:
            raise ReportError(
                f"{label}: entry {name!r} uses unsupported compression method "
                f"{info.compress_type}"
            )
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
    for directory, subdirectories, files in os.walk(root):
        for subdirectory in subdirectories:
            # os.walk does not descend into linked directories; one that
            # leaves the package is rejected like a linked file.
            path = Path(directory) / subdirectory
            if path.is_symlink() and not path.resolve().is_relative_to(resolved_root):
                raise ReportError(f"{root}: {path} links outside the package")
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
