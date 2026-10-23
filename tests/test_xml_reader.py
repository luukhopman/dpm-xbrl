from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tests.support import LEI, XML_INSTANCE
from xbrlreport import (
    Fact,
    Limits,
    ReportError,
    detect_format,
    read_report,
    read_xbrl_xml,
)

ROOT_OPEN = (
    '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:m="http://example.com/m">'
)
CONTEXT = (
    '<xbrli:context id="{id}"><xbrli:entity><xbrli:identifier scheme="{scheme}">'
    "{entity}</xbrli:identifier></xbrli:entity><xbrli:period>{period}"
    "</xbrli:period></xbrli:context>"
)


def _instance(*body: str) -> bytes:
    return (ROOT_OPEN + "".join(body) + "</xbrli:xbrl>").encode()


def _context(
    context_id: str = "c",
    *,
    scheme: str = "s",
    entity: str = "E",
    period: str = "<xbrli:instant>2024-12-31</xbrli:instant>",
) -> str:
    return CONTEXT.format(id=context_id, scheme=scheme, entity=entity, period=period)


def test_instance_with_dimensions_units_and_indicators(tmp_path: Path) -> None:
    path = tmp_path / "instance.xbrl"
    path.write_text(XML_INSTANCE)

    report = read_report(path)

    assert report.format == "xbrl-xml"
    assert report.entry_point == (
        "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.xsd"
    )
    assert (report.entity_scheme, report.entity_id) == (LEI, "5299000000000000000A")
    assert report.reference_date == date(2024, 12, 31)
    assert report.base_currency == "iso4217:EUR"
    assert report.parameters == {} and report.decimals_parameters == {}
    assert report.filing_indicators == {"C_01.00": True, "C_02.00": False}
    assert report.namespaces["eba_met"] == "http://www.eba.europa.eu/xbrl/crr/dict/met"
    assert "dom" not in report.namespaces
    assert report.warnings == ()
    assert report.facts == (
        Fact(
            value="1000",
            concept="eba_met:qABJ",
            dimensions={"eba_dim:qADT": "eba_qOR:qx2060"},
            typed_dimensions={"eba_dim:qINC": "CP-1"},
            unit="iso4217:EUR",
            decimals=-3,
            location="instance.xbrl#f1",
        ),
        Fact(
            value="0.25",
            concept="eba_met:qABK",
            unit="xbrli:pure",
            location="instance.xbrl#f2",
        ),
        Fact(
            value=None,
            concept="eba_met:qABL",
            unit="iso4217:EUR",
            location="instance.xbrl#f3",
        ),
        Fact(
            value="Text & more", concept="eba_met:qABM", location="instance.xbrl#fact4"
        ),
        Fact(
            value="1.5",
            concept="eba_met:qABN",
            unit="iso4217:EUR/xbrli:shares",
            decimals=2,
            location="instance.xbrl#f5",
        ),
    )
    assert report.facts_for_template("C_01.00") == ()


def test_bytes_input_and_detection() -> None:
    data = XML_INSTANCE.encode()
    assert detect_format(data) == "xbrl-xml"
    report = read_report(data, name="upload.xml")
    assert report.facts[0].location == "upload.xml#f1"


@pytest.mark.parametrize(
    "prolog",
    [
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>',
        '<?xml version="1.0"?>\n<!-- c --><!DOCTYPE xbrl SYSTEM "http://evil/x.dtd">',
        "﻿<!DOCTYPE x>",
    ],
)
def test_doctype_is_rejected(prolog: str) -> None:
    data = (prolog + ROOT_OPEN + "</xbrli:xbrl>").encode()
    with pytest.raises(ReportError, match="DOCTYPE and ENTITY declarations"):
        read_xbrl_xml(data)


def test_doctype_is_rejected_in_utf16(tmp_path: Path) -> None:
    path = tmp_path / "x.xbrl"
    path.write_bytes(("<!DOCTYPE x>" + ROOT_OPEN + "</xbrli:xbrl>").encode("utf-16"))
    with pytest.raises(ReportError, match="DOCTYPE"):
        read_xbrl_xml(path)


def test_multiple_periods_and_entities_break_filing_rules() -> None:
    data = _instance(
        _context("a"),
        _context(
            "b",
            entity="F",
            period="<xbrli:startDate>2024-01-01</xbrli:startDate>"
            "<xbrli:endDate>2025-06-30</xbrli:endDate>",
        ),
        '<m:x contextRef="a">1</m:x>',
        '<m:y contextRef="a">2</m:y>',
        '<m:z contextRef="b">3</m:z>',
    )
    report = read_xbrl_xml(data, name="i.xbrl")

    assert report.reference_date == date(2024, 12, 31)
    assert report.entity_id == "E"
    found = {(item.rule, item.code): item for item in report.filing}
    assert found["2.9", "multipleIdentifiers"].message == (
        "All contexts must identify the same entity; the report uses 2 (E, F)."
    )
    assert found["2.13", "multiplePeriodsUsed"].severity == "error"
    assert found["2.13", "nonInstantPeriodUsed"].examples == ("i.xbrl#b",)


def test_tuples_and_stray_elements_warn_and_precision_breaks_a_rule() -> None:
    data = _instance(
        _context(),
        '<m:tuple><m:inner contextRef="c">1</m:inner></m:tuple>',
        "<m:stray/>",
        '<m:p contextRef="c" precision="3">1</m:p>',
    )
    report = read_xbrl_xml(data, name="i.xbrl")

    assert [fact.concept for fact in report.facts] == ["m:p"]
    warnings = "\n".join(report.warnings)
    assert "tuples are not supported" in warnings
    assert "elements without contextRef skipped" in warnings
    precision = next(item for item in report.filing if item.rule == "2.17")
    assert (precision.code, precision.count) == ("precisionUsed", 1)
    assert precision.examples == ("i.xbrl#fact1",)


def test_nested_prefix_declarations_are_normalized() -> None:
    data = _instance(
        '<xbrli:context id="c" xmlns:other="http://example.com/m" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'xmlns:new="http://example.com/new"><xbrli:entity>'
        '<xbrli:identifier scheme="s">E</xbrli:identifier></xbrli:entity>'
        "<xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>"
        '<xbrli:scenario><xbrldi:explicitMember dimension="other:d">new:v'
        "</xbrldi:explicitMember></xbrli:scenario></xbrli:context>",
        '<q:x xmlns:q="http://example.com/m" contextRef="c">1</q:x>',
    )
    report = read_xbrl_xml(data)

    assert report.facts[0].concept == "m:x"
    assert report.facts[0].dimensions == {"m:d": "new:v"}
    assert report.namespaces["new"] == "http://example.com/new"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (['<m:x contextRef="nope">1</m:x>'], "undefined context 'nope'"),
        ([_context(), '<m:x contextRef="c" unitRef="u">1</m:x>'], "undefined unit"),
        (
            [_context(), '<m:x contextRef="c" decimals="two">1</m:x>'],
            "invalid decimals",
        ),
        (
            [_context(period="<xbrli:instant>soon</xbrli:instant>")],
            "invalid period 'soon'",
        ),
        (['<xbrli:unit id="u"/>'], "unit u has no measure"),
        (
            ['<xbrli:unit id="u"><xbrli:measure>zz:EUR</xbrli:measure></xbrli:unit>'],
            "invalid QName 'zz:EUR'",
        ),
    ],
)
def test_invalid_instances(body: list[str], message: str) -> None:
    with pytest.raises(ReportError, match=message):
        read_xbrl_xml(_instance(*body))


def test_malformed_xml_reports_position() -> None:
    with pytest.raises(ReportError, match=r"bad\.xbrl:1:\d+: malformed XML"):
        read_xbrl_xml(ROOT_OPEN.encode() + b"<m:x>", name="bad.xbrl")


def test_root_must_be_xbrl() -> None:
    with pytest.raises(ReportError, match="root element must be xbrli:xbrl"):
        read_xbrl_xml(b"<html/>")


def test_typed_member_needs_one_child() -> None:
    context = _context().replace(
        "</xbrli:context>",
        '<xbrli:scenario xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'
        '<xbrldi:typedMember dimension="m:d"/></xbrli:scenario></xbrli:context>',
    )
    with pytest.raises(ReportError, match="must have one child element"):
        read_xbrl_xml(_instance(context))


def test_xml_limits(tmp_path: Path) -> None:
    data = _instance(
        _context(), '<m:x contextRef="c">1</m:x>', '<m:y contextRef="c">2</m:y>'
    )
    with pytest.raises(ReportError, match="limit of 1 facts"):
        read_xbrl_xml(data, limits=Limits(max_facts=1))
    with pytest.raises(ReportError, match="maximum file size"):
        read_xbrl_xml(data, limits=Limits(max_file_size=10))
    path = tmp_path / "i.xbrl"
    path.write_bytes(data)
    with pytest.raises(ReportError, match="maximum file size"):
        read_xbrl_xml(path, limits=Limits(max_file_size=10))
    with pytest.raises(ReportError, match="no such file"):
        read_xbrl_xml(tmp_path / "missing.xbrl")


def test_contexts_without_facts_still_give_entity_and_period() -> None:
    report = read_xbrl_xml(_instance(_context()))
    assert (report.entity_id, report.reference_date) == ("E", date(2024, 12, 31))
    assert report.base_currency is None
