from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from dpmxbrl import Limits, ReportError, _package, read_report
from dpmxbrl._package import open_zip_package
from tests.support import write_zip

pytest.importorskip("isal")

# Repetitive enough to compress, varied enough to span several deflate blocks.
_CONTENT = "".join(
    f"dp{index * 7919 % 1_000_003},{index},{index * 1.5}\n" for index in range(20_000)
).encode()


def _zip(*, prefix: bytes = b"", method: int = ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    buffer.write(prefix)
    with ZipFile(buffer, "w", method) as archive:
        archive.writestr("report/reports/t.csv", _CONTENT)
        archive.writestr("report/META-INF/reportPackage.json", b"{}")
    return buffer.getvalue()


def _read(source: bytes | Path, name: str = "report/reports/t.csv") -> bytes:
    with open_zip_package(source, label="t.zip", limits=Limits()) as package:
        return package.read(name)


@pytest.fixture
def without_isal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_package, "_fast_zlib", None)


@pytest.mark.parametrize("method", [ZIP_DEFLATED, ZIP_STORED])
@pytest.mark.parametrize("prefix", [b"", b"self-extractor stub"])
def test_isal_reads_what_zipfile_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: int,
    prefix: bytes,
) -> None:
    data = _zip(prefix=prefix, method=method)
    path = tmp_path / "t.zip"
    path.write_bytes(data)
    inflated = [_read(data), _read(path)]
    monkeypatch.setattr(_package, "_fast_zlib", None)
    assert inflated == [_CONTENT, _CONTENT] == [_read(data), _read(path)]


def test_isal_inflates_deflated_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    inflate = _package.Package._inflate

    def counted(self: _package.Package, info: object) -> bytes | None:
        result = inflate(self, info)  # ty: ignore[invalid-argument-type]
        calls.append(result is not None)
        return result

    monkeypatch.setattr(_package.Package, "_inflate", counted)
    assert _read(_zip()) == _CONTENT
    assert calls == [True]


def _corrupt_member(data: bytes) -> bytes:
    damaged = bytearray(data)
    start = damaged.find(b"PK\x03\x04") + 30 + len("report/reports/t.csv")
    damaged[start + 200] ^= 0xFF
    return bytes(damaged)


@pytest.mark.parametrize("fast", [True, False])
def test_corrupt_entries_fail_as_zipfile_fails_them(
    request: pytest.FixtureRequest, fast: bool
) -> None:
    if not fast:
        request.getfixturevalue("without_isal")
    with pytest.raises(ReportError, match=r"t\.zip: report/reports/t\.csv is damaged"):
        _read(_corrupt_member(_zip()))


def test_entries_are_never_inflated_past_their_declared_size() -> None:
    data = _zip()
    with open_zip_package(data, label="t.zip", limits=Limits()) as package:
        assert package._archive is not None
        info = package._archive.getinfo("report/reports/t.csv")
        info.file_size = 1_000
        assert package._inflate(info) is None
        with pytest.raises(ReportError, match="is damaged"):
            package.read("report/reports/t.csv")


def _patch_central_directory(data: bytes, offset: int, value: bytes) -> bytes:
    """Overwrite a field of every central directory header of a ZIP."""
    patched = bytearray(data)
    position = patched.find(b"PK\x01\x02")
    while position >= 0:
        patched[position + offset : position + offset + len(value)] = value
        position = patched.find(b"PK\x01\x02", position + 4)
    return bytes(patched)


def test_unreadable_zip_entries_raise_report_error(tmp_path: Path) -> None:
    from tests.support import closed_files, zip_bytes

    # Version needed to extract 9.9: zipfile raises NotImplementedError.
    data = _patch_central_directory(
        zip_bytes(closed_files(), root="report/"), 6, b"\x63\x00"
    )
    with pytest.raises(ReportError, match=r"zip file version 9\.9"):
        read_report(data)
    # A local header offset past the end: zipfile seeks out of range.
    data = _patch_central_directory(
        zip_bytes(closed_files(), root="report/"), 42, b"\xff\xff\xff\x7f"
    )
    with pytest.raises(ReportError):
        read_report(data)


def test_unreadable_taxonomy_zip_raises_report_error(tmp_path: Path) -> None:
    from tests.support import metadata_files, taxonomy_package

    report = write_zip(tmp_path / "r.zip", metadata_files())
    package = taxonomy_package(tmp_path / "t.zip", full=True)
    damaged = tmp_path / "damaged.zip"
    damaged.write_bytes(_patch_central_directory(package.read_bytes(), 6, b"\x63\x00"))
    with pytest.raises(ReportError, match=r"zip file version 9\.9"):
        read_report(report, taxonomy_packages=[damaged])
    outer = tmp_path / "outer.zip"
    with ZipFile(outer, "w") as archive:
        archive.writestr("inner.zip", damaged.read_bytes())
    with pytest.raises(ReportError, match=r"outer\.zip!inner\.zip"):
        read_report(report, taxonomy_packages=[outer])


def test_taxonomy_zips_are_limited(tmp_path: Path) -> None:
    from tests.support import metadata_files, taxonomy_package

    report = write_zip(tmp_path / "r.zip", metadata_files())
    package = taxonomy_package(tmp_path / "t.zip", full=True)
    with pytest.raises(ReportError, match="ZIP entries exceed the limit of 3"):
        read_report(
            report,
            taxonomy_packages=[package],
            limits=Limits(max_taxonomy_entries=3),
        )
    with pytest.raises(ReportError, match="files read from the taxonomy packages"):
        read_report(
            report,
            taxonomy_packages=[package],
            limits=Limits(max_total_size=5_000),
        )
