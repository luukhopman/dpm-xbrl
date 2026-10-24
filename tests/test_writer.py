from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import pytest

from dpmxbrl import (
    Fact,
    Report,
    ReportError,
    default_package_root,
    read_report,
    write_xbrl_csv,
    write_xbrl_xml,
)
from tests.support import (
    XML_INSTANCE,
    metadata_files,
    open_files,
    taxonomy_package,
    write_zip,
)

TYPED = {"eba_dim:qINC": "eba_typ:qCC"}


def _csv_view(report: Report) -> list[tuple[object, ...]]:
    return [
        (fact.template, fact.datapoint, fact.value, tuple(fact.keys.items()))
        for fact in report.facts
    ]


def _xml_view(report: Report) -> list[tuple[object, ...]]:
    return [
        (
            fact.concept,
            fact.value,
            dict(fact.dimensions),
            dict(fact.typed_dimensions),
            fact.unit,
            fact.decimals,
        )
        for fact in report.facts
    ]


def test_csv_round_trip(tmp_path: Path) -> None:
    files = open_files(
        **{
            "reports/c_01.00.csv": "datapoint,factValue\r\ndp1,#nil\r\ndp2,##x\r\ndp3,7\r\n"
        }
    )
    original = read_report(write_zip(tmp_path / "in.zip", files))
    target = tmp_path / "out.zip"

    write_xbrl_csv(original, target)
    again = read_report(target)

    assert _csv_view(again) == _csv_view(original)
    assert again.facts[0].value is None and again.facts[1].value == "#x"
    assert again.entry_point == original.entry_point
    assert (again.entity_scheme, again.entity_id) == (
        original.entity_scheme,
        original.entity_id,
    )
    assert again.reference_date == original.reference_date
    assert again.base_currency == original.base_currency
    assert again.parameters == original.parameters
    assert again.decimals_parameters == original.decimals_parameters
    assert again.filing_indicators == original.filing_indicators
    assert again.namespaces == original.namespaces


def test_csv_package_layout_is_deterministic(tmp_path: Path) -> None:
    report = read_report(write_zip(tmp_path / "in.zip", open_files()))
    first, second = io.BytesIO(), io.BytesIO()
    write_xbrl_csv(report, first)
    write_xbrl_csv(report, second)

    assert first.getvalue() == second.getvalue()
    with ZipFile(first) as archive:
        names = archive.namelist()
        assert names == [
            "5299000000000000000A_2024-12-31/META-INF/reportPackage.json",
            "5299000000000000000A_2024-12-31/reports/report.json",
            "5299000000000000000A_2024-12-31/reports/parameters.csv",
            "5299000000000000000A_2024-12-31/reports/FilingIndicators.csv",
            "5299000000000000000A_2024-12-31/reports/c_01.00.csv",
            "5299000000000000000A_2024-12-31/reports/c_27.00.csv",
        ]
        assert {info.date_time for info in archive.infolist()} == {
            (1980, 1, 1, 0, 0, 0)
        }
        root = "5299000000000000000A_2024-12-31/"
        package = json.loads(archive.read(root + "META-INF/reportPackage.json"))
        assert package == {
            "documentInfo": {
                "documentType": "https://xbrl.org/report-package/2023/xbrl-csv"
            }
        }
        table = archive.read(root + "reports/c_27.00.csv").decode()
        assert table.splitlines()[0] == "datapoint,factValue,c0010,c0020"
        parameters = archive.read(root + "reports/parameters.csv").decode().splitlines()
        assert parameters[:4] == [
            "name,value",
            "entityID,lei:5299000000000000000A",
            "refPeriod,2024-12-31",
            "baseCurrency,iso4217:EUR",
        ]


def test_csv_writer_rejects_facts_without_datapoint_or_template(tmp_path: Path) -> None:
    report = read_report(XML_INSTANCE.encode())
    with pytest.raises(ReportError, match="no template"):
        write_xbrl_csv(report, tmp_path / "x.zip")
    with_template = replace(
        report, facts=tuple(replace(fact, template="t") for fact in report.facts)
    )
    with pytest.raises(ReportError, match="no datapoint"):
        write_xbrl_csv(with_template, tmp_path / "x.zip")
    assert not (tmp_path / "x.zip").exists()
    bad = replace(report, facts=(Fact("1", datapoint="d", template="../x"),))
    with pytest.raises(ReportError, match="not a safe table file name"):
        write_xbrl_csv(bad, io.BytesIO())


def test_csv_writer_entity_scheme_prefixes() -> None:
    report = Report(
        format="xbrl-xml",
        entry_point=None,
        entity_scheme="http://standards.iso.org/iso/17442",
        entity_id="LEI1",
        reference_date=None,
        base_currency=None,
        parameters={},
        decimals_parameters={},
        filing_indicators={},
        facts=(Fact("", datapoint="dp1", template="t"),),
        namespaces={},
    )
    buffer = io.BytesIO()
    write_xbrl_csv(report, buffer, root="pkg")
    again = read_report(buffer.getvalue())

    assert default_package_root(report) == "LEI1"
    assert again.entity_scheme == "http://standards.iso.org/iso/17442"
    assert again.namespaces == {"lei": "http://standards.iso.org/iso/17442"}
    assert again.facts == ()
    assert [item.code for item in again.filing if item.rule == "2.19"] == ["emptyUsed"]


def test_xml_round_trip(tmp_path: Path) -> None:
    original = read_report(XML_INSTANCE.encode(), name="instance.xbrl")
    target = tmp_path / "out.xbrl"

    write_xbrl_xml(original, target, typed_domains=TYPED)
    again = read_report(target)

    assert _xml_view(again) == _xml_view(original)
    assert again.filing_indicators == original.filing_indicators
    assert again.entry_point == original.entry_point
    assert (again.entity_scheme, again.entity_id, again.reference_date) == (
        original.entity_scheme,
        original.entity_id,
        original.reference_date,
    )
    assert again.base_currency == "iso4217:EUR"
    assert again.warnings == ()
    text = target.read_text()
    assert text.count("<xbrli:context ") == 2
    assert '<xbrli:context id="c1">' in text
    assert 'find:filed="false"' in text
    assert '<eba_met:qABL contextRef="c1" unitRef="u1" xsi:nil="true"/>' in text


def test_xml_writer_errors() -> None:
    report = read_report(XML_INSTANCE.encode())
    with pytest.raises(ReportError, match="no typed domain element"):
        write_xbrl_xml(report, io.BytesIO())
    with pytest.raises(ReportError, match="requires an entity"):
        write_xbrl_xml(replace(report, entity_id=None), io.BytesIO())
    with pytest.raises(ReportError, match="requires a reference date"):
        write_xbrl_xml(replace(report, reference_date=None), io.BytesIO())
    no_concept = replace(
        report, facts=(Fact("1", datapoint="dp1", location="t.csv:2"),)
    )
    with pytest.raises(ReportError, match=r"t\.csv:2: fact has no concept"):
        write_xbrl_xml(no_concept, io.BytesIO())
    undeclared = replace(report, facts=(Fact("1", concept="zz:x"),))
    with pytest.raises(ReportError, match="'zz:x' is not a qname with a declared"):
        write_xbrl_xml(undeclared, io.BytesIO())
    bad_local = replace(report, facts=(Fact("1", concept="eba_met:a b"),))
    with pytest.raises(ReportError, match="is not a qname with a declared"):
        write_xbrl_xml(bad_local, io.BytesIO())
    control = replace(
        report, facts=(Fact("a\x01b", concept="eba_met:ei1", location="f9"),)
    )
    with pytest.raises(ReportError, match=r"f9: .* U\+0001"):
        write_xbrl_xml(control, io.BytesIO())


def test_xml_round_trip_keeps_carriage_returns() -> None:
    report = read_report(XML_INSTANCE.encode())
    text = replace(report, facts=(Fact("a\r\nb", concept="eba_met:ei1"),))
    target = io.BytesIO()
    write_xbrl_xml(text, target)
    assert read_report(target.getvalue()).facts[0].value == "a\r\nb"


def test_metadata_csv_converts_to_xml(tmp_path: Path) -> None:
    package = taxonomy_package(tmp_path / "taxonomy.zip")
    report = read_report(
        write_zip(tmp_path / "r.zip", metadata_files()), taxonomy_packages=[package]
    )
    namespaces = {**report.namespaces, "eba_typ": "http://example.com/typ"}
    buffer = io.BytesIO()

    write_xbrl_xml(
        replace(report, namespaces=namespaces),
        buffer,
        typed_domains=TYPED,
    )
    xml = read_report(buffer.getvalue())

    assert _xml_view(xml) == _xml_view(report)
    assert xml.reference_date == date(2024, 12, 31)
    assert xml.filing_indicators == report.filing_indicators
