from __future__ import annotations

import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from dpmxbrl import Limits, ReportError, _package
from dpmxbrl._package import open_zip_package

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
