from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support import (
    CSV_DOCUMENT_TYPE,
    ENTRY_POINT,
    TAB_BASE,
    catalog_xml,
    closed_files,
    closed_template_json,
    csv_text,
    metadata_files,
    module_json,
    open_template_json,
    report_json,
    taxonomy_package,
    write_directory,
    write_zip,
)
from xbrlreport import Fact, Limits, ReportError, read_report


def test_taxonomy_package_resolves_property_groups(tmp_path: Path) -> None:
    package = taxonomy_package(tmp_path / "taxonomy.zip")
    report = read_report(
        write_zip(tmp_path / "r.zip", metadata_files()), taxonomy_packages=[package]
    )

    assert report.warnings == (
        "reports/c_01.00.csv: '#nil' fact values read as nil facts "
        "(1 occurrence, first at reports/c_01.00.csv:4)",
    )
    assert report.namespaces["eba_met"] == "http://www.eba.europa.eu/xbrl/crr/dict/met"
    assert report.facts_for_template("c_01.00") == (
        Fact(
            value="1000",
            concept="eba_met:mi53",
            datapoint="dp84817",
            template="c_01.00",
            dimensions={"eba_dim:BAS": "eba_BA:x6"},
            unit="iso4217:EUR",
            decimals=-3,
            location="reports/c_01.00.csv:2",
        ),
        Fact(
            value="0.1234",
            concept="eba_met:pi1",
            datapoint="dp84818",
            template="c_01.00",
            unit="xbrli:pure",
            decimals=4,
            location="reports/c_01.00.csv:3",
        ),
        Fact(
            value=None,
            concept="eba_met:ei2",
            datapoint="dp84820",
            template="c_01.00",
            location="reports/c_01.00.csv:4",
        ),
    )


def test_open_table_column_references(tmp_path: Path) -> None:
    package = taxonomy_package(tmp_path / "taxonomy.zip")
    report = read_report(
        write_zip(tmp_path / "r.zip", metadata_files()), taxonomy_packages=[package]
    )
    facts = report.facts_for_template("c_27.00")

    assert facts[0] == Fact(
        value="ABC",
        concept="eba_met:qNCO",
        datapoint="dp100",
        template="c_27.00",
        dimensions={"eba_dim:qCO": "eba_qCO:qx2000"},
        typed_dimensions={"eba_dim:qINC": "cp1"},
        keys={"c0010": "cp1", "c0020": "eba_qCO:qx2000"},
        location="reports/c_27.00.csv:2",
    )
    assert (facts[1].unit, facts[1].decimals) == ("iso4217:EUR", -3)
    assert facts[2].dimensions == {"eba_dim:qCO": "eba_qCO:qx2001"}
    assert facts[2].typed_dimensions == {"eba_dim:qINC": "cp2"}


def test_metadata_resolver_is_used_before_packages(tmp_path: Path) -> None:
    documents = {
        ENTRY_POINT: module_json(),
        TAB_BASE + "c_01.00/c_01.00.json": closed_template_json(),
        TAB_BASE + "c_27.00/c_27.00.json": open_template_json(),
    }
    requested: list[str] = []

    def resolver(url: str) -> bytes | None:
        requested.append(url)
        content = documents.get(url)
        return content.encode() if content is not None else None

    report = read_report(
        write_directory(tmp_path / "d", metadata_files()), metadata_resolver=resolver
    )

    assert requested == list(documents)
    assert all(fact.concept for fact in report.facts)


def test_partially_resolved_metadata_falls_back_per_table(tmp_path: Path) -> None:
    documents = {
        ENTRY_POINT: module_json(),
        TAB_BASE + "c_01.00/c_01.00.json": closed_template_json(),
    }
    report = read_report(
        write_zip(tmp_path / "r.zip", metadata_files()),
        metadata_resolver=lambda url: (
            documents[url].encode() if url in documents else None
        ),
    )

    assert report.facts_for_template("c_01.00")[0].concept == "eba_met:mi53"
    open_fact = report.facts_for_template("c_27.00")[0]
    assert open_fact.concept is None
    assert open_fact.keys == {"c0010": "cp1", "c0020": "eba_qCO:qx2000"}
    unresolved = [item for item in report.warnings if "could not be resolved" in item]
    assert len(unresolved) == 1
    assert "c_27.00.json" in unresolved[0]


def _inline_template(**template: object) -> str:
    base = {
        "columns": {
            "key": {},
            "datapoint": {
                "propertyGroups": {
                    "dp1": {
                        "decimals": "$decimalsMonetary",
                        "dimensions": {
                            "concept": "eba:m1",
                            "eba:dim": "$key",
                            "eba:lit": "$$literal",
                            "eba:gone": "#none",
                            "eba:missing": "$noSuchThing",
                        },
                    },
                    "dp2": {
                        "decimals": "$badDecimals",
                        "dimensions": {"concept": "eba:m2"},
                    },
                }
            },
            "factValue": {"propertiesFrom": ["datapoint"]},
        },
    }
    base.update(template)
    return report_json(
        extends=[],
        tableTemplates={"t1": base},
        parameters={"badDecimals": "x"},
    )


def test_inline_templates_and_reference_edge_cases(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/report.json": _inline_template(dimensions={"eba:tpl": "eba:v"}),
            "reports/c_01.00.csv": None,
            "reports/t1.csv": csv_text(
                "datapoint,factValue,key,extra",
                "dp1,5,eba:member,x",
                "dp2,6,,y",
                "dp9,7,,z",
                "dp1,8,,w",
            ),
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))
    facts = report.facts

    assert facts[0].concept == "eba:m1"
    assert facts[0].decimals == -3
    assert facts[0].dimensions == {"eba:tpl": "eba:v", "eba:dim": "eba:member"}
    assert facts[0].typed_dimensions == {"eba:lit": "$literal"}
    assert facts[0].keys == {"key": "eba:member", "extra": "x"}
    assert facts[1].decimals is None
    assert facts[2].concept is None
    assert facts[2].datapoint == "dp9"
    assert "eba:dim" not in facts[3].dimensions
    warnings = "\n".join(report.warnings)
    assert "column 'extra' is not defined" in warnings
    assert "unresolved reference '$noSuchThing' ignored" in warnings
    assert "invalid decimals 'x' ignored" in warnings
    assert "unknown property group values (1 occurrence" in warnings


def test_template_decimals_and_report_dimensions(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/report.json": report_json(
                extends=[],
                dimensions={"eba:rep": "eba:r"},
                tableTemplates={
                    "c_01.00": {
                        "decimals": 2,
                        "columns": {
                            "datapoint": {},
                            "factValue": {"dimensions": {"concept": "eba:c"}},
                        },
                    }
                },
            )
        }
    )
    report = read_report(write_zip(tmp_path / "r.zip", files))

    assert report.facts[0].concept == "eba:c"
    assert report.facts[0].decimals == 2
    assert report.facts[0].dimensions == {"eba:rep": "eba:r"}
    assert report.facts[0].datapoint == "dp84817"


def test_extends_cycles_and_diamonds_are_safe(tmp_path: Path) -> None:
    def document(extends: list[str], **extra: object) -> bytes:
        return json.dumps(
            {
                "documentInfo": {"documentType": CSV_DOCUMENT_TYPE, "extends": extends},
                **extra,
            }
        ).encode()

    documents = {
        "http://x/a.json": document(["b.json", "c.json"]),
        "http://x/b.json": document(["c.json", "a.json"]),
        "http://x/c.json": document([], parameters={"fromC": "1"}),
    }
    files = closed_files(
        **{"reports/report.json": report_json(extends=["http://x/a.json"])}
    )
    report = read_report(
        write_zip(tmp_path / "r.zip", files), metadata_resolver=documents.get
    )

    assert report.parameters["fromC"] == "1"
    assert any("ignored cyclic extends" in warning for warning in report.warnings)


def test_extends_depth_limit(tmp_path: Path) -> None:
    def document(index: int) -> bytes:
        return json.dumps(
            {
                "documentInfo": {
                    "documentType": CSV_DOCUMENT_TYPE,
                    "extends": [f"d{index + 1}.json"],
                }
            }
        ).encode()

    files = closed_files(
        **{"reports/report.json": report_json(extends=["http://x/d0.json"])}
    )
    with pytest.raises(ReportError, match="extends chain exceeds the maximum depth"):
        read_report(
            write_zip(tmp_path / "r.zip", files),
            metadata_resolver=lambda url: document(int(url[10:-5])),
            limits=Limits(max_extends_depth=3),
        )


def test_package_local_extends(tmp_path: Path) -> None:
    files = closed_files(
        **{
            "reports/report.json": report_json(extends=["meta/module.json"]),
            "reports/meta/module.json": json.dumps(
                {
                    "documentInfo": {"documentType": CSV_DOCUMENT_TYPE},
                    "tableTemplates": {
                        "c_01.00": {
                            "columns": {
                                "datapoint": {},
                                "factValue": {"dimensions": {"concept": "eba:local"}},
                            }
                        }
                    },
                }
            ),
        }
    )
    report = read_report(write_directory(tmp_path / "d", files))
    assert {fact.concept for fact in report.facts} == {"eba:local"}


def test_catalog_with_entity_declaration_is_rejected(tmp_path: Path) -> None:
    catalog = (
        '<?xml version="1.0"?><!DOCTYPE catalog [<!ENTITY x "y">]>'
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog"/>'
    )
    package = write_zip(tmp_path / "t.zip", {"META-INF/catalog.xml": catalog}, root="")
    with pytest.raises(ReportError, match="ENTITY declarations are not allowed"):
        read_report(
            write_zip(tmp_path / "r.zip", closed_files()), taxonomy_packages=[package]
        )


def test_taxonomy_package_errors(tmp_path: Path) -> None:
    report = write_zip(tmp_path / "r.zip", closed_files())
    no_catalog = write_zip(tmp_path / "t.zip", {"x.json": "{}"}, root="")
    with pytest.raises(ReportError, match=r"has no META-INF/catalog\.xml"):
        read_report(report, taxonomy_packages=[no_catalog])
    with pytest.raises(ReportError, match="not a readable taxonomy package"):
        read_report(report, taxonomy_packages=[tmp_path / "missing.zip"])
    escaping = write_zip(
        tmp_path / "e.zip",
        {"META-INF/catalog.xml": catalog_xml({"http://www.eba.europa.eu/": "../../"})},
        root="",
    )
    result = read_report(report, taxonomy_packages=[escaping])
    assert any("could not be resolved" in warning for warning in result.warnings)
