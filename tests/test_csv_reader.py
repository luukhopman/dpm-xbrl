from __future__ import annotations

import io
import json
import re
from datetime import date
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

from dpmxbrl import (
    Fact,
    Limits,
    ReportError,
    detect_format,
    local_name,
    read_report,
    read_xbrl_csv,
)
from tests.support import (
    ENTRY_POINT,
    LEI,
    closed_files,
    csv_text,
    open_files,
    report_json,
    write_directory,
    write_zip,
    zip_bytes,
)


def _other_warnings(report) -> list[str]:
    return [item for item in report.warnings if "could not be resolved" not in item]


def test_closed_table_zip_reads_report_and_facts(tmp_path: Path) -> None:
    path = write_zip(tmp_path / "report.zip", closed_files())

    report = read_report(path)

    assert report.format == "xbrl-csv"
    assert report.entry_point == ENTRY_POINT
    assert report.entity_scheme == LEI
    assert report.entity_id == "5299000000000000000A"
    assert report.reference_date == date(2024, 12, 31)
    assert report.base_currency == "iso4217:EUR"
    assert report.parameters["decimalsMonetary"] == "-3"
    assert report.decimals_parameters == {
        "decimalsInteger": 0,
        "decimalsMonetary": -3,
        "decimalsPercentage": 4,
        "decimalsDecimal": None,
    }
    assert report.filing_indicators == {
        "C_01.00": True,
        "C_02.00": False,
        "C_27.00": True,
    }
    assert report.namespaces["lei"] == LEI
    assert report.facts == (
        Fact(
            value="1000",
            datapoint="dp84817",
            template="c_01.00",
            location="reports/c_01.00.csv:2",
        ),
        Fact(
            value="-250.5",
            datapoint="dp84818",
            template="c_01.00",
            location="reports/c_01.00.csv:3",
        ),
    )
    assert _other_warnings(report) == []


def test_open_table_keeps_key_columns_in_header_order(tmp_path: Path) -> None:
    report = read_report(write_zip(tmp_path / "r.zip", open_files()))

    facts = report.facts_for_template("C_27.00")

    assert [fact.datapoint for fact in facts] == ["dp100", "dp101", "dp100"]
    assert list(facts[0].keys.items()) == [
        ("c0010", "cp1"),
        ("c0020", "eba_qCO:qx2000"),
    ]
    assert facts[2].keys == {"c0010": "cp2", "c0020": "eba_qCO:qx2001"}
    assert all(fact.concept is None and fact.decimals is None for fact in facts)
    assert _other_warnings(report) == []


def test_zip_bytes_directory_and_wrapped_root_agree(tmp_path: Path) -> None:
    files = open_files()
    directory = write_directory(tmp_path / "dir", files)
    from_dir = read_report(directory)
    from_bytes = read_report(zip_bytes(files))
    from_wrapped = read_report(write_zip(tmp_path / "w.zip", files, root="top/"))
    from_json = read_report(directory / "reports" / "report.json")

    assert from_dir.facts == from_bytes.facts == from_wrapped.facts
    assert from_json.facts[0].location == "c_01.00.csv:2"
    assert from_json.facts[0].value == from_dir.facts[0].value
    assert detect_format(directory) == "xbrl-csv"


def test_a_damaged_zip_is_not_read_as_xml(tmp_path: Path) -> None:
    whole = zip_bytes(closed_files())
    truncated = tmp_path / "report.zip"
    truncated.write_bytes(whole[: len(whole) // 2])
    not_zip = tmp_path / "notes.zip"
    not_zip.write_bytes(b"hello")
    renamed = tmp_path / "report.xbrl"
    renamed.write_bytes(whole[: len(whole) // 2])

    for path in (truncated, not_zip, renamed):
        message = f"^{re.escape(path.name)} is not a readable ZIP"
        with pytest.raises(ReportError, match=message):
            detect_format(path)
    with pytest.raises(ReportError, match=r"^the report is not a readable ZIP"):
        detect_format(whole[: len(whole) // 2])


def test_directory_with_bare_report_json(tmp_path: Path) -> None:
    files = {
        name.removeprefix("reports/"): content
        for name, content in closed_files().items()
        if name.startswith("reports/")
    }
    report = read_report(write_directory(tmp_path / "bare", files))

    assert len(report.facts) == 2
    assert report.facts[0].location == "c_01.00.csv:2"


def test_missing_report_json(tmp_path: Path) -> None:
    files = closed_files(**{"reports/report.json": None})
    with pytest.raises(ReportError, match=r"no reports/report\.json"):
        read_report(write_zip(tmp_path / "r.zip", files))


def test_two_report_json_files_are_rejected() -> None:
    data = zip_bytes(closed_files(**{"reports/other.json": report_json()}))
    with pytest.raises(ReportError, match="exactly one report JSON"):
        read_report(data, name="pkg.zip")


@pytest.mark.parametrize(
    ("file", "content", "message"),
    [
        (
            "reports/c_01.00.csv",
            csv_text("dp,value", "dp1,1"),
            r"reports/c_01\.00\.csv:1: table header must contain 'datapoint'",
        ),
        (
            "reports/c_01.00.csv",
            csv_text("datapoint,factValue,datapoint", "dp1,1,x"),
            r"c_01\.00\.csv:1: duplicate table columns datapoint",
        ),
        (
            "reports/c_01.00.csv",
            csv_text("datapoint,factValue,", "dp1,1,x"),
            "empty column name",
        ),
        ("reports/c_01.00.csv", "", "no header row"),
        (
            "reports/c_01.00.csv",
            csv_text("datapoint,factValue", "dp1,1", "dp2,2,extra"),
            r"c_01\.00\.csv:3: expected 2 cells, found 3",
        ),
        (
            "reports/parameters.csv",
            csv_text("key,value", "entityID,lei:X"),
            r"reports/parameters\.csv:1: parameters header must be 'name,value'",
        ),
        (
            "reports/parameters.csv",
            csv_text("name,value", "refPeriod,31-12-2024"),
            r"parameters\.csv:2: refPeriod '31-12-2024' is not a YYYY-MM-DD date",
        ),
        (
            "reports/parameters.csv",
            csv_text("name,value", "decimalsMonetary,abc"),
            r"parameters\.csv:2: parameter decimalsMonetary",
        ),
        (
            "reports/FilingIndicators.csv",
            csv_text("template,reported", "C_01.00,true"),
            "filing indicator header must be 'templateID,reported'",
        ),
        (
            "reports/FilingIndicators.csv",
            csv_text("templateID,reported", "C_01.00,yes"),
            r"FilingIndicators\.csv:2: invalid filing indicator",
        ),
        (
            "reports/report.json",
            report_json(document_type="https://xbrl.org/2021/xbrl-json"),
            "unsupported documentType",
        ),
        ("reports/report.json", "{not json", r"reports/report\.json:1: invalid JSON"),
        ("reports/report.json", "[]", "expected a JSON object"),
        (
            "reports/report.json",
            '{"documentInfo": {}, "documentInfo": {}}',
            "duplicate JSON key",
        ),
        ("reports/report.json", "{}", "missing 'documentInfo'"),
        (
            "META-INF/reportPackage.json",
            json.dumps({"documentInfo": {"documentType": "https://example.com/x"}}),
            "unsupported report package documentType",
        ),
    ],
)
def test_malformed_input_names_file_and_line(
    tmp_path: Path, file: str, content: str, message: str
) -> None:
    path = write_zip(tmp_path / "r.zip", closed_files(**{file: content}))
    with pytest.raises(ReportError, match=message):
        read_report(path)


def test_report_package_2023_generic_type_is_accepted(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "META-INF/reportPackage.json": json.dumps(
                {
                    "documentInfo": {
                        "documentType": "https://xbrl.org/report-package/2023"
                    }
                }
            )
        }
    )
    assert len(read_report(write_zip(tmp_path / "r.zip", files)).facts) == 2


def test_draft_document_type_is_accepted_with_warning(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/report.json": report_json(
                document_type="https://xbrl.org/CR/2021-02-03/xbrl-csv"
            )
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))
    assert any("pre-recommendation" in warning for warning in report.warnings)


def test_special_values_and_escapes(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/c_01.00.csv": csv_text(
                "datapoint,factValue",
                "dp1,#nil",
                "dp2,#empty",
                "dp3,#none",
                "dp4,##hash",
                "dp5,#odd",
                "dp6,#nil",
            )
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))

    assert [(fact.datapoint, fact.value) for fact in report.facts] == [
        ("dp1", None),
        ("dp4", "#hash"),
        ("dp5", "#odd"),
        ("dp6", None),
    ]
    found = {item.code: item for item in report.filing}
    assert (found["nilUsed"].rule, found["nilUsed"].count) == ("2.19", 2)
    assert found["nilUsed"].examples == (
        "reports/c_01.00.csv:2",
        "reports/c_01.00.csv:7",
    )
    assert found["emptyUsed"].examples == ("reports/c_01.00.csv:3",)
    assert found["specialValueUsed"].rule == "xBRL-CSV 5"
    assert found["specialValueUsed"].examples == (
        "reports/c_01.00.csv:4",
        "reports/c_01.00.csv:6",
    )


def test_duplicates(tmp_path: Path) -> None:
    files = open_files(
        **{
            "reports/c_27.00.csv": csv_text(
                "datapoint,factValue,c0010",
                "dp100,A,k1",
                "dp100,A,k1",
                "dp100,B,k1",
                "dp100,A,k2",
            )
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))
    facts = report.facts_for_template("c_27.00")

    assert [(fact.value, fact.keys["c0010"]) for fact in facts] == [
        ("A", "k1"),
        ("B", "k1"),
        ("A", "k2"),
    ]
    assert any(
        "duplicate facts ignored (1 occurrence, first at reports/c_27.00.csv:3)"
        in warning
        for warning in report.warnings
    )
    assert any(
        "conflicting duplicate facts kept (1 occurrence, first at "
        "reports/c_27.00.csv:4)" in warning
        for warning in report.warnings
    )


def test_physical_line_numbers_follow_multiline_cells(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/c_01.00.csv": '\ufeffdatapoint,factValue\r\ndp1,"two\r\nlines"\r\n'
            "\r\ndp2,3\r\n"
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))

    assert [(fact.value, fact.location) for fact in report.facts] == [
        ("two\r\nlines", "reports/c_01.00.csv:2"),
        ("3", "reports/c_01.00.csv:5"),
    ]


def test_eba_entity_prefixes_resolve_without_a_namespace(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/parameters.csv": csv_text(
                "name,value", "entityID,rs:ABC.CON", "refPeriod,2025-03-31"
            ),
            "reports/FilingIndicators.csv": None,
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))

    assert (report.entity_scheme, report.entity_id) == (
        "https://eurofiling.info/eu/rs",
        "ABC.CON",
    )
    assert report.base_currency is None
    assert report.filing_indicators == {}
    missing = next(item for item in report.filing if item.rule == "1.6")
    assert (missing.code, missing.severity) == ("missingFilingIndicators", "error")


def test_missing_parameters_file_breaks_a_filing_rule(tmp_path: Path) -> None:
    files = closed_files(**{"reports/parameters.csv": None})
    report = read_report(write_zip(tmp_path / "r.zip", files))

    assert report.entity_id is None and report.reference_date is None
    codes = {(item.rule, item.code) for item in report.filing}
    assert ("Package", "missingParametersFile") in codes
    assert ("2.8", "missingIdentifier") in codes


def test_inline_tables_mapping_sets_template(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/report.json": report_json(
                tables={"main": {"template": "c_01.00.a", "url": "c_01.00.csv"}}
            )
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))
    assert {fact.template for fact in report.facts} == {"c_01.00.a"}


def test_unresolved_extends_gives_one_warning(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/report.json": report_json(
                extends=[ENTRY_POINT, "http://example.com/a.json"]
            )
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))

    assert len(report.warnings) == 1
    assert ENTRY_POINT in report.warnings[0]
    assert "2 extended metadata documents could not be resolved" in report.warnings[0]


def _raw_zip(entries: list[tuple[str | ZipInfo, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("bad_name", "message"),
    [
        ("../evil.csv", "unsafe parent-relative entry"),
        ("reports/../../evil.csv", "unsafe parent-relative entry"),
        ("/etc/evil.csv", "unsafe absolute entry"),
        ("C:/evil.csv", "unsafe absolute entry"),
        ("reports\\..\\evil.csv", "unsafe parent-relative entry"),
    ],
)
def test_zip_slip_entries_are_rejected(bad_name: str, message: str) -> None:
    entries = [
        (name, content.encode() if isinstance(content, str) else content)
        for name, content in closed_files().items()
    ]
    info = ZipInfo("placeholder")
    info.filename = bad_name
    data = _raw_zip([*entries, (info, b"x")])
    with pytest.raises(ReportError, match=message):
        read_report(data, name="evil.zip")


def test_duplicate_zip_entries_are_rejected() -> None:
    import warnings

    entries = [(name, b"x") for name in ("reports/report.json", "reports/report.json")]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = _raw_zip(list(entries))
    with pytest.raises(ReportError, match="duplicate entry"):
        read_report(data)


def test_encrypted_zip_entries_are_rejected() -> None:
    data = bytearray(_raw_zip([("reports/report.json", b"{}")]))
    # Set the encryption flag in the local header and the central directory.
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = data.find(signature)
        data[position + offset] |= 0x1
    with pytest.raises(ReportError, match="encrypted entry"):
        read_report(bytes(data))


@pytest.mark.parametrize("damaged", ["reports/report.json", "reports/parameters.csv"])
def test_damaged_zip_entries_are_reported(damaged: str) -> None:
    data = bytearray(zip_bytes(closed_files()))
    # Flip a byte inside the entry's compressed data, after its local header.
    position = data.find(damaged.encode()) + len(damaged)
    data[position + 4] ^= 0xFF
    with pytest.raises(ReportError, match=f"{damaged} is damaged and cannot be read"):
        read_report(bytes(data), name="pkg.zip")


def test_limits_are_enforced(tmp_path: Path) -> None:
    path = write_zip(tmp_path / "r.zip", open_files())
    with pytest.raises(ReportError, match="ZIP entries exceed the limit of 3"):
        read_report(path, limits=Limits(max_zip_entries=3))
    with pytest.raises(ReportError, match="maximum file size"):
        read_report(path, limits=Limits(max_file_size=100))
    with pytest.raises(ReportError, match="uncompressed size exceeds"):
        read_report(path, limits=Limits(max_total_size=500))
    with pytest.raises(ReportError, match=r"c_27\.00\.csv:2: report exceeds the limit"):
        read_report(path, limits=Limits(max_facts=2))
    directory = write_directory(tmp_path / "d", open_files())
    with pytest.raises(ReportError, match="maximum file size"):
        read_report(directory, limits=Limits(max_file_size=100))


def test_non_zip_bytes_and_missing_paths(tmp_path: Path) -> None:
    with pytest.raises(ReportError, match="not a readable ZIP"):
        read_xbrl_csv(b"not a zip", name="x.zip")
    with pytest.raises(ReportError, match="no such file"):
        read_report(tmp_path / "missing.zip")
    text_file = tmp_path / "notes.txt"
    text_file.write_text("hello")
    with pytest.raises(ReportError, match="not an xBRL-CSV report package"):
        read_xbrl_csv(text_file)


def test_invalid_utf8_names_the_file(tmp_path: Path) -> None:
    files = closed_files(
        **{"reports/c_01.00.csv": b"datapoint,factValue\r\ndp1,\xff\r\n"}
    )
    with pytest.raises(ReportError, match=r"c_01\.00\.csv: not valid UTF-8"):
        read_report(write_zip(tmp_path / "r.zip", files))


def test_local_name() -> None:
    assert local_name("eba_met:qABJ") == "qABJ"
    assert local_name("{http://x}y") == "y"
    assert local_name("plain") == "plain"
