from __future__ import annotations

import json
from pathlib import Path

import pytest

from dpmxbrl import read_report
from dpmxbrl.cli import main
from tests.support import XML_INSTANCE, open_files, write_zip


def test_inspect_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_zip(tmp_path / "r.zip", open_files())

    assert main(["inspect", str(path)]) == 0
    output = capsys.readouterr().out

    assert "Format:            xbrl-csv" in output
    assert (
        "Entity:            5299000000000000000A (http://standards.iso.org/iso/17442)"
        in output
    )
    assert "Reference date:    2024-12-31" in output
    assert "Filing indicators: 2 reported of 3" in output
    assert "Facts:             5" in output
    assert "  c_01.00  2\n  c_27.00  3\n" in output
    assert "Warnings: 1\n  - reports/report.json: 1 extended metadata" in output


def test_inspect_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "i.xbrl"
    path.write_text(XML_INSTANCE)

    assert main(["inspect", str(path), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["schema_version"] == 1

    assert summary["format"] == "xbrl-xml"
    assert summary["reference_date"] == "2024-12-31"
    assert summary["filing_indicators"] == {
        "reported": 1,
        "total": 2,
        "templates": {"C_01.00": True, "C_02.00": False},
    }
    assert summary["facts_per_template"] == {"(none)": 5}
    assert summary["warnings"] == []
    nil = next(item for item in summary["filing_rules"] if item["code"] == "nilUsed")
    assert nil == {
        "rule": "2.19",
        "title": "Nil and empty values",
        "code": "nilUsed",
        "severity": "error",
        "message": "Facts must not be nil (xsi:nil); leave out a fact that is not "
        "reported.",
        "count": 1,
        "examples": ["i.xbrl#f3"],
    }


def test_convert(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = write_zip(tmp_path / "r.zip", open_files())
    target = tmp_path / "copy.zip"
    assert main(["convert", str(source), str(target), "--root", "pkg"]) == 0
    assert "warning: reports/report.json" in capsys.readouterr().err
    assert len(read_report(target).facts) == 5

    instance = tmp_path / "i.xbrl"
    instance.write_text(XML_INSTANCE)
    out = tmp_path / "o.xml"
    arguments = ["convert", str(instance), str(out)]
    assert main([*arguments, "--typed-domain", "eba_dim:qINC=eba_typ:qCC"]) == 0
    assert len(read_report(out).facts) == 5


@pytest.mark.parametrize(
    "arguments",
    [
        ["convert", "{zip}", "{tmp}/x.txt"],
        ["convert", "{zip}", "{tmp}/x.xbrl"],
        ["convert", "{xml}", "{tmp}/x.xbrl", "--typed-domain", "nonsense"],
        ["inspect", "{tmp}/missing.zip"],
    ],
)
def test_errors_exit_with_status_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> None:
    source = write_zip(tmp_path / "r.zip", open_files())
    instance = tmp_path / "i.xbrl"
    instance.write_text(XML_INSTANCE)
    values = {"zip": str(source), "xml": str(instance), "tmp": str(tmp_path)}

    assert main([argument.format(**values) for argument in arguments]) == 1
    assert "error: " in capsys.readouterr().err


def test_inspect_fails_on_broken_filing_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "instance.xbrl"
    path.write_text(XML_INSTANCE)
    assert {item.severity for item in read_report(path).filing} == {
        "error",
        "warning",
    }
    assert main(["inspect", str(path)]) == 0
    assert main(["inspect", str(path), "--fail-on", "warning"]) == 2
    assert main(["inspect", str(path), "--fail-on", "error"]) == 2
    output = capsys.readouterr().out
    assert "(none)" not in output


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("dpm-xbrl ")


def test_inspect_columnar_counts_like_read_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("polars")
    path = write_zip(tmp_path / "r.zip", open_files())
    assert main(["inspect", str(path), "--json"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert main(["inspect", str(path), "--json", "--columnar"]) == 0
    columnar = json.loads(capsys.readouterr().out)
    for field in ("fact_count", "facts_per_template", "reference_date", "entity_id"):
        assert columnar[field] == full[field]


def test_cli_limits_are_applied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_zip(tmp_path / "r.zip", open_files())
    assert main(["inspect", str(path), "--max-facts", "2"]) == 1
    assert "exceeds the limit of 2 facts" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["inspect", str(path), "--max-facts", "0"])
