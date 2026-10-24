"""Conversion between XBRL-XML and xBRL-CSV through taxonomy packages."""

from __future__ import annotations

import copy
import io
import os
from collections import Counter
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import pytest

from dpmxbrl import (
    Fact,
    Report,
    ReportError,
    read_report,
    write_xbrl_csv,
    write_xbrl_xml,
)
from dpmxbrl.cli import main
from tests.support import ENTRY_POINT_XSD, metadata_files, taxonomy_package, write_zip

MET = "http://www.eba.europa.eu/xbrl/crr/dict/met"


def _positions(report: Report) -> Counter[tuple[object, ...]]:
    return Counter(
        (fact.template, fact.datapoint, tuple(sorted(fact.keys.items())), fact.value)
        for fact in report.facts
    )


def _clark(report: Report, qname: str | None) -> str | None:
    if qname is None:
        return None
    prefix, _, local = qname.partition(":")
    return f"{{{report.namespaces[prefix]}}}{local}"


def _meaning(report: Report) -> set[tuple[object, ...]]:
    def unit(fact: Fact) -> str | None:
        clark = _clark(report, fact.unit)
        return None if clark == "{http://www.xbrl.org/2003/instance}pure" else clark

    return {
        (
            _clark(report, fact.concept),
            frozenset(
                (_clark(report, d), _clark(report, m))
                for d, m in fact.dimensions.items()
            ),
            frozenset((_clark(report, d), v) for d, v in fact.typed_dimensions.items()),
            fact.value,
            unit(fact),
            fact.decimals,
        )
        for fact in report.facts
    }


@pytest.fixture
def package(tmp_path: Path) -> Path:
    return taxonomy_package(tmp_path / "taxonomy.zip", full=True)


@pytest.fixture
def csv_report(tmp_path: Path, package: Path) -> Report:
    return read_report(
        write_zip(tmp_path / "in.zip", metadata_files()), taxonomy_packages=[package]
    )


def _as_xml(report: Report, package: Path) -> Report:
    buffer = io.BytesIO()
    write_xbrl_xml(report, buffer, taxonomy_packages=[package])
    return read_report(buffer.getvalue())


def test_csv_to_xml_to_csv_round_trip(
    tmp_path: Path, package: Path, csv_report: Report
) -> None:
    xml = _as_xml(replace(csv_report, entry_point=ENTRY_POINT_XSD), package)
    assert xml.entry_point == ENTRY_POINT_XSD
    assert _meaning(xml) == _meaning(csv_report)

    target = tmp_path / "out.zip"
    assert write_xbrl_csv(xml, target, taxonomy_packages=[package]) == ()

    original = read_report(write_zip(tmp_path / "plain.zip", metadata_files()))
    written = read_report(target)
    # Read without the taxonomy, both are EBA-convention tables.
    assert _positions(written) == _positions(original)
    assert written.entry_point == csv_report.entry_point
    assert written.parameters["baseCurrency"] == "iso4217:EUR"
    assert written.decimals_parameters["decimalsMonetary"] == -3
    assert _meaning(read_report(target, taxonomy_packages=[package])) == _meaning(
        csv_report
    )


def test_xml_facts_take_the_module_prefixes_and_layout(
    tmp_path: Path, package: Path, csv_report: Report
) -> None:
    xml = _as_xml(csv_report, package)
    renamed = {
        "met": MET,
        "d": "http://www.eba.europa.eu/xbrl/crr/dict/dim",
        "co": "http://www.eba.europa.eu/xbrl/crr/dict/dom/qCO",
        "ba": "http://www.eba.europa.eu/xbrl/crr/dict/dom/BA",
    }
    inverse = {uri: prefix for prefix, uri in xml.namespaces.items()}
    swap = {inverse[uri]: prefix for prefix, uri in renamed.items() if uri in inverse}

    def rename(qname: str) -> str:
        prefix, _, local = qname.partition(":")
        return f"{swap.get(prefix, prefix)}:{local}"

    facts = tuple(
        replace(
            fact,
            concept=rename(fact.concept or ""),
            dimensions={rename(d): rename(m) for d, m in fact.dimensions.items()},
            typed_dimensions={rename(d): v for d, v in fact.typed_dimensions.items()},
        )
        for fact in xml.facts
    )
    namespaces = {
        prefix: uri for prefix, uri in xml.namespaces.items() if prefix not in swap
    } | renamed
    target = tmp_path / "out.zip"
    write_xbrl_csv(
        replace(xml, facts=facts, namespaces=namespaces),
        target,
        taxonomy_packages=[package],
    )
    with ZipFile(target) as archive:
        root = archive.namelist()[0].split("/")[0]
        table = archive.read(f"{root}/reports/c_27.00.csv").decode()
        report_json = archive.read(f"{root}/reports/report.json").decode()
    assert table.splitlines()[0] == "datapoint,factValue,c0010,c0020"
    assert "dp100,ABC,cp1,eba_qCO:qx2000" in table.splitlines()
    assert '"namespaces"' not in report_json
    assert "corep_of.json" in report_json


def test_unmapped_facts_raise_or_are_returned(
    tmp_path: Path, package: Path, csv_report: Report
) -> None:
    xml = _as_xml(csv_report, package)
    stray = Fact("1", concept="eba_met:mi53", unit="iso4217:EUR", location="x#f9")
    usd = replace(xml.facts[0], unit="iso4217:USD", location="x#f10")
    report = replace(xml, facts=(*xml.facts, stray, usd))

    with pytest.raises(ReportError, match="2 facts cannot be written") as caught:
        write_xbrl_csv(report, tmp_path / "a.zip", taxonomy_packages=[package])
    assert caught.value.problems == (
        "x#f9: no data point of corep_of.json has concept eba_met:mi53 with these "
        "dimensions",
        "x#f10: its unit iso4217:USD differs from baseCurrency iso4217:EUR, which "
        "the other facts use",
    )
    assert not (tmp_path / "a.zip").exists()
    restored = copy.deepcopy(caught.value)
    assert restored.problems == caught.value.problems

    skipped = write_xbrl_csv(
        report, tmp_path / "b.zip", taxonomy_packages=[package], strict=False
    )
    assert [fact.location for fact, _ in skipped] == ["x#f9", "x#f10"]
    assert len(read_report(tmp_path / "b.zip").facts) == len(xml.facts)


def test_decimals_parameters_take_the_lowest_decimals(
    tmp_path: Path, package: Path, csv_report: Report
) -> None:
    xml = _as_xml(csv_report, package)
    facts = tuple(
        replace(fact, decimals=-4) if fact.concept == "eba_met:mi1" else fact
        for fact in xml.facts
    )
    target = tmp_path / "out.zip"
    write_xbrl_csv(replace(xml, facts=facts), target, taxonomy_packages=[package])
    assert read_report(target).decimals_parameters["decimalsMonetary"] == -4


def test_conversion_needs_the_module(
    tmp_path: Path, package: Path, csv_report: Report
) -> None:
    xml = _as_xml(csv_report, package)
    with pytest.raises(ReportError, match="no xBRL-CSV entry point"):
        write_xbrl_csv(
            replace(xml, entry_point="http://example.com/mod/x.xsd"),
            tmp_path / "a.zip",
            taxonomy_packages=[package],
        )
    with pytest.raises(ReportError, match="names no entry point"):
        write_xbrl_csv(
            replace(xml, entry_point=None),
            tmp_path / "a.zip",
            taxonomy_packages=[package],
        )
    with pytest.raises(ReportError, match="taxonomy packages place facts by concept"):
        write_xbrl_csv(xml, tmp_path / "a.zip")


def test_xml_writer_takes_typed_domains_from_the_taxonomy(
    package: Path, csv_report: Report
) -> None:
    buffer = io.BytesIO()
    write_xbrl_xml(csv_report, buffer, taxonomy_packages=[package])
    text = buffer.getvalue().decode()
    assert "<eba_typ:CC>cp1</eba_typ:CC>" in text
    assert 'xmlns:eba_typ="http://www.eba.europa.eu/xbrl/crr/dict/typ"' in text
    # Only used prefixes are declared.
    assert "xmlns:lei=" not in text
    assert (
        read_report(buffer.getvalue()).filing == read_report(buffer.getvalue()).filing
    )
    assert not any(item.rule == "3.4" for item in read_report(buffer.getvalue()).filing)
    with pytest.raises(ReportError, match="taxonomy packages can give it"):
        write_xbrl_xml(csv_report, io.BytesIO())


def test_xml_writer_writes_repeated_facts_once_and_pure_units(
    csv_report: Report, package: Path
) -> None:
    fact = Fact("0.5", concept="eba_met:pi1", decimals=4)
    report = replace(csv_report, facts=(fact, replace(fact, location="again")))
    buffer = io.BytesIO()
    write_xbrl_xml(report, buffer, taxonomy_packages=[package])
    (written,) = read_report(buffer.getvalue()).facts
    assert written.unit == "xbrli:pure"
    assert written.decimals == 4


def _findings(report: Report) -> dict[tuple[str, str], tuple[str, ...]]:
    found: dict[tuple[str, str], tuple[str, ...]] = {}
    for item in report.filing:
        found[item.rule, item.code] = (
            *found.get((item.rule, item.code), ()),
            *item.examples,
        )
    return found


def test_taxonomy_checks_on_csv(tmp_path: Path) -> None:
    package = taxonomy_package(tmp_path / "t.zip", full=True, valid_from="2025-03-31")
    files = metadata_files()
    files["reports/c_01.00.csv"] = (
        "datapoint,factValue\r\ndp84817,1000\r\ndp84818,93.1\r\n"
    )
    files["reports/notes.txt"] = "x"
    files["reports/c_99.00.csv"] = "datapoint,factValue\r\n"
    report = read_report(
        write_zip(tmp_path / "r.zip", files), taxonomy_packages=[package]
    )
    found = _findings(report)
    assert found["1.5", "inappropriateTaxonomyRef"] == ("reports/report.json",)
    assert found["1.6.3", "invalidFilingIndicatorValue"] == (
        "reports/report.json: C_02.00",
    )
    assert found["3.2", "useDecimalFractions"] == ("reports/c_01.00.csv:3",)
    assert sorted(found["Package", "unexpectedFile"]) == [
        "reports/c_99.00.csv",
        "reports/notes.txt",
    ]
    assert ("3.5", "notRecommendedNamespacePrefix") not in found


def test_extraneous_files_without_taxonomy(tmp_path: Path) -> None:
    files = metadata_files()
    files["META-INF/catalog.xml"] = "<catalog/>"
    report = read_report(write_zip(tmp_path / "r.zip", files))
    assert _findings(report)["Package", "unexpectedFile"] == ("META-INF/catalog.xml",)
    assert ("Package", "unexpectedFile") not in _findings(
        read_report(write_zip(tmp_path / "s.zip", metadata_files()))
    )


def test_taxonomy_checks_on_xml(
    tmp_path: Path, package: Path, csv_report: Report
) -> None:
    xml = _as_xml(replace(csv_report, entry_point=ENTRY_POINT_XSD), package)
    buffer = io.BytesIO()
    write_xbrl_xml(xml, buffer, taxonomy_packages=[package])
    text = buffer.getvalue().replace(b"eba_met", b"m")
    found = _findings(read_report(text, name="r.xbrl", taxonomy_packages=[package]))
    assert found["3.5", "notRecommendedNamespacePrefix"] == (
        f"r.xbrl: m for {MET} (expected eba_met)",
    )
    assert ("1.5", "inappropriateSchemaRef") not in found

    unknown = text.replace(b"corep_of.xsd", b"other.xsd")
    found = _findings(read_report(unknown, name="r.xbrl", taxonomy_packages=[package]))
    assert found["1.5", "inappropriateSchemaRef"] == ("r.xbrl",)
    # The XML missing a filing indicator for C_27.00 is not flagged twice.
    assert (
        read_report(text, taxonomy_packages=[package]).facts == read_report(text).facts
    )


def test_missing_filing_indicators(tmp_path: Path, package: Path) -> None:
    files = metadata_files()
    files["reports/FilingIndicators.csv"] = "templateID,reported\r\nC_01.00,true\r\n"
    report = read_report(
        write_zip(tmp_path / "r.zip", files), taxonomy_packages=[package]
    )
    (finding,) = [item for item in report.filing if item.rule == "1.6"]
    assert finding.code == "missingFilingIndicators"
    assert finding.examples == ("reports/report.json: C_27.00",)


def test_structural_problems_are_collected(tmp_path: Path) -> None:
    files = metadata_files()
    files["reports/c_01.00.csv"] = "datapoint,factValue\r\ndp1,1,x\r\ndp2,2\r\ndp3\r\n"
    files["reports/c_27.00.csv"] = 'datapoint,factValue\r\ndp1,"a"b\r\n'
    files["reports/c_28.00.csv"] = "datapoint,datapoint\r\n"
    with pytest.raises(ReportError) as caught:
        read_report(write_zip(tmp_path / "r.zip", files))
    assert str(caught.value) == (
        "reports/c_01.00.csv:2: expected 2 cells, found 3 (and 3 more problems)"
    )
    assert caught.value.problems == (
        "reports/c_01.00.csv:2: expected 2 cells, found 3",
        "reports/c_01.00.csv:4: expected 2 cells, found 1",
        "reports/c_27.00.csv:2: ',' expected after '\"'",
        "reports/c_28.00.csv:1: duplicate table columns datapoint",
    )


def test_cli_converts_xml_to_csv(
    tmp_path: Path,
    package: Path,
    csv_report: Report,
    capsys: pytest.CaptureFixture[str],
) -> None:
    xml_path = tmp_path / "in.xbrl"
    write_xbrl_xml(csv_report, xml_path, taxonomy_packages=[package])
    data = xml_path.read_bytes().replace(b"</xbrli:xbrl>", b"")
    data += (
        b'<eba_met:mi53 contextRef="c1" unitRef="u1" decimals="0">5</eba_met:mi53>'
        b"</xbrli:xbrl>"
    )
    xml_path.write_bytes(data)
    out = tmp_path / "out.zip"
    arguments = ["convert", str(xml_path), str(out), "--taxonomy-package", str(package)]
    assert main(arguments) == 1
    assert "cannot be written as xBRL-CSV" in capsys.readouterr().err
    assert main([*arguments, "--skip-unmapped"]) == 0
    assert "1 fact left out" in capsys.readouterr().err
    assert len(read_report(out).facts) == len(csv_report.facts)

    back = tmp_path / "back.xbrl"
    assert (
        main(["convert", str(out), str(back), "--taxonomy-package", str(package)]) == 0
    )


# Real EBA taxonomy and samples, when available -------------------------------------

_TAXONOMY = os.environ.get("DPM_XBRL_EBA_TAXONOMY")
_SAMPLES = os.environ.get("DPM_XBRL_EBA_SAMPLES")


@pytest.mark.skipif(
    not (_TAXONOMY and _SAMPLES),
    reason="set DPM_XBRL_EBA_TAXONOMY (folder with the EBA 4.2 dictionary and "
    "frameworks packages) and DPM_XBRL_EBA_SAMPLES (folder with EBA-COREP_OF.xbrl "
    "and EBA-COREP_OF.csv.zip)",
)
@pytest.mark.parametrize("sample", ["EBA-COREP_OF", "EBA-FINREP9"])
def test_official_samples_convert_like_the_eba_packages(
    tmp_path: Path, sample: str
) -> None:
    packages = sorted(Path(str(_TAXONOMY)).glob("EBA_XBRL_*_[DR]*.zip"))
    samples = Path(str(_SAMPLES))
    xml = read_report(samples / f"{sample}.xbrl")
    target = tmp_path / "out.zip"
    assert write_xbrl_csv(xml, target, taxonomy_packages=packages) == ()
    ours, eba = read_report(target), read_report(samples / f"{sample}.csv.zip")
    # The EBA generated each sample's values separately: compare the cells.
    assert {(f.template, f.datapoint) for f in ours.facts} == {
        (f.template, f.datapoint) for f in eba.facts
    }
    # Key columns: the EBA orders most by header code, but not all.
    assert {(f.template, frozenset(f.keys)) for f in ours.facts} == {
        (f.template, frozenset(f.keys)) for f in eba.facts
    }
    assert _meaning(xml) == _meaning(read_report(target, taxonomy_packages=packages))
