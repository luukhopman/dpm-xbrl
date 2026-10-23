from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from tests.support import csv_text, open_files, report_json, write_zip
from xbrlreport import Report, read_report
from xbrlreport.filing import (
    RULE_TITLES,
    FilingLog,
    check_file_name,
    check_subject,
    sort_findings,
)


def _lei(prefix: str) -> str:
    """Complete an 18-character LEI prefix with its ISO 7064 check digits."""
    number = int("".join(str(int(character, 36)) for character in prefix + "00"))
    return f"{prefix}{98 - number % 97:02d}"


LEI = _lei("529900T8BM49AURSDO")
RS = "https://eurofiling.info/eu/rs"
LEI_SCHEME = "http://standards.iso.org/iso/17442"
XSD = "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.xsd"
NAME = f"{LEI}.CON_FR_COREP040000_COREPOF_2024-12-31_20250101000000000"

CONTEXT = (
    '<xbrli:context id="{id}"><xbrli:entity>'
    '<xbrli:identifier scheme="{scheme}">{entity}</xbrli:identifier>{segment}'
    "</xbrli:entity><xbrli:period>{period}</xbrli:period>{scenario}"
    "</xbrli:context>"
)


def _context(
    context_id: str,
    *,
    entity: str = f"{LEI}.CON",
    period: str = "<xbrli:instant>2024-12-31</xbrli:instant>",
    scenario: str = "",
    segment: str = "",
) -> str:
    return CONTEXT.format(
        id=context_id,
        scheme=RS,
        entity=entity,
        period=period,
        segment=segment,
        scenario=scenario and f"<xbrli:scenario>{scenario}</xbrli:scenario>",
    )


DENOMINATED = (
    '<xbrldi:explicitMember dimension="eba_dim:CCA">eba_CA:x1</xbrldi:explicitMember>'
    '<xbrldi:explicitMember dimension="eba_dim:CUS">eba_CU:USD</xbrldi:explicitMember>'
)
CLEAN_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:link="http://www.xbrl.org/2003/linkbase" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" '
    'xmlns:find="http://www.eurofiling.info/xbrl/ext/filing-indicators" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:eba_dim="http://www.eba.europa.eu/xbrl/crr/dict/dim" '
    'xmlns:eba_CA="http://www.eba.europa.eu/xbrl/crr/dict/dom/CA" '
    'xmlns:eba_CU="http://www.eba.europa.eu/xbrl/crr/dict/dom/CU" '
    'xmlns:eba_met="http://www.eba.europa.eu/xbrl/crr/dict/met">'
    f'<link:schemaRef xlink:type="simple" xlink:href="{XSD}"/>'
    + _context("c1")
    + _context("c2", scenario=DENOMINATED)
    + '<xbrli:unit id="EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>'
    '<xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
    '<xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>'
    "<find:fIndicators>"
    '<find:filingIndicator contextRef="c1">C_01.00</find:filingIndicator>'
    '<find:filingIndicator contextRef="c1" find:filed="false">C_02.00'
    "</find:filingIndicator></find:fIndicators>"
    '<eba_met:mi1 contextRef="c1" unitRef="EUR" decimals="-3">1000</eba_met:mi1>'
    '<eba_met:mi2 contextRef="c2" unitRef="USD" decimals="0">5</eba_met:mi2>'
    '<eba_met:pi1 contextRef="c1" unitRef="pure" decimals="4">0.25</eba_met:pi1>'
    '<eba_met:si1 contextRef="c1">Text</eba_met:si1>'
    "</xbrli:xbrl>"
)
CLOSE = "</xbrli:xbrl>"


def _read_xml(text: str, name: str = f"{NAME}.xbrl") -> set[tuple[str, str]]:
    report = read_report(text.encode(), name=name)
    return {(item.rule, item.code) for item in report.filing}


def _insert(text: str) -> Callable[[str], str]:
    return lambda xml: xml.replace(CLOSE, text + CLOSE)


def _swap(old: str, new: str) -> Callable[[str], str]:
    def swap(xml: str) -> str:
        assert old in xml
        return xml.replace(old, new, 1)

    return swap


def test_a_compliant_instance_breaks_no_filing_rule() -> None:
    report = read_report(CLEAN_XML.encode(), name=f"{NAME}.xbrl")
    assert report.filing == ()


XML_CASES: list[tuple[str, Callable[[str], str], tuple[str, str]]] = [
    (
        "other encoding",
        _swap('encoding="UTF-8"', 'encoding="ISO-8859-1"'),
        ("1.4", "encodingNotUtf8"),
    ),
    (
        "standalone declaration",
        _swap('encoding="UTF-8"?>', 'encoding="UTF-8" standalone="yes"?>'),
        ("1.13", "standaloneDocumentDeclarationUsed"),
    ),
    (
        "schema location",
        _swap(
            "<xbrli:xbrl ",
            '<xbrli:xbrl xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="a b" ',
        ),
        ("1.14", "schemaLocationAttributeUsed"),
    ),
    (
        "XInclude",
        _insert('<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="x"/>'),
        ("1.15", "xIncludeUsed"),
    ),
    (
        "xml:base",
        _swap("<xbrli:xbrl ", '<xbrli:xbrl xml:base="http://x/" '),
        ("2.1", "xmlBaseUsed"),
    ),
    (
        "linkbase reference",
        _insert('<link:linkbaseRef xlink:type="simple" xlink:href="x.xml"/>'),
        ("2.4", "linkbaseRefUsed"),
    ),
    (
        "footnote",
        _insert('<link:footnoteLink xlink:type="extended"/>'),
        ("2.25", "xbrlFootnotesAreIgnored"),
    ),
    (
        "two schema references",
        _swap("<xbrli:context", f'<link:schemaRef xlink:href="{XSD}"/><xbrli:context'),
        ("2.3", "multipleSchemaRefs"),
    ),
    (
        "relative schema reference",
        _swap(XSD, "corep_of.xsd"),
        ("2.2", "inappropriateSchemaRef"),
    ),
    (
        "no schema reference",
        _swap(f'<link:schemaRef xlink:type="simple" xlink:href="{XSD}"/>', ""),
        ("1.5", "inappropriateSchemaRef"),
    ),
    (
        "no filing indicators",
        _swap(
            '<find:filingIndicator contextRef="c1">C_01.00</find:filingIndicator>'
            '<find:filingIndicator contextRef="c1" find:filed="false">C_02.00'
            "</find:filingIndicator>",
            "",
        ),
        ("1.6", "missingFilingIndicators"),
    ),
    (
        "repeated filing indicator",
        _swap(
            "</find:fIndicators>",
            '<find:filingIndicator contextRef="c1">C_01.00</find:filingIndicator>'
            "</find:fIndicators>",
        ),
        ("1.6.1", "duplicateFilingIndicator"),
    ),
    (
        "filing indicator with a scenario",
        _swap(
            '<find:filingIndicator contextRef="c1">C_01.00',
            '<find:filingIndicator contextRef="c2">C_01.00',
        ),
        ("1.6", "invalidContextForFilingIndicator"),
    ),
    (
        "segment",
        _swap(
            _context("c1"),
            _context(
                "c1",
                segment="<xbrli:segment><xbrldi:explicitMember "
                'dimension="eba_dim:CCA">eba_CA:x1</xbrldi:explicitMember>'
                "</xbrli:segment>",
            ),
        ),
        ("2.14", "segmentUsed"),
    ),
    (
        "scenario content",
        _swap(DENOMINATED, DENOMINATED + "<eba_met:note>x</eba_met:note>"),
        ("2.15", "scenarioContainsNonDimensionContent"),
    ),
    (
        "forever",
        _swap(_context("c1"), _context("c1", period="<xbrli:forever/>")),
        ("2.11", "foreverUsed"),
    ),
    (
        "duration",
        _swap(
            _context("c1"),
            _context(
                "c1",
                period="<xbrli:startDate>2024-01-01</xbrli:startDate>"
                "<xbrli:endDate>2024-12-31</xbrli:endDate>",
            ),
        ),
        ("2.13", "nonInstantPeriodUsed"),
    ),
    (
        "time zone",
        _swap(">2024-12-31</xbrli:instant>", ">2024-12-31Z</xbrli:instant>"),
        ("2.10", "periodWithTimezone"),
    ),
    (
        "time",
        _swap(">2024-12-31</xbrli:instant>", ">2024-12-31T00:00:00</xbrli:instant>"),
        ("2.10", "periodWithTimeContent"),
    ),
    (
        "second reference date",
        _swap(
            "<xbrli:unit ",
            _context("c3", period="<xbrli:instant>2025-03-31</xbrli:instant>")
            + "<xbrli:unit ",
        ),
        ("2.13", "multiplePeriodsUsed"),
    ),
    (
        "second entity",
        _swap("<xbrli:unit ", _context("c3", entity=f"{LEI}.IND") + "<xbrli:unit "),
        ("2.9", "multipleIdentifiers"),
    ),
    (
        "nil fact",
        _insert(
            '<eba_met:mi3 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'contextRef="c1" unitRef="EUR" xsi:nil="true"/>'
        ),
        ("2.19", "nilUsed"),
    ),
    (
        "empty text",
        _insert('<eba_met:si2 contextRef="c1"></eba_met:si2>'),
        ("2.19", "emptyUsed"),
    ),
    (
        "spaces around text",
        _swap(">Text<", "> Text <"),
        ("3.11", "leadingOrTrailingSpacesInText"),
    ),
    (
        "no decimals",
        _swap(' decimals="4">0.25', ">0.25"),
        ("2.18", "missingDecimalsAttribute"),
    ),
    ("precision", _swap('decimals="4"', 'precision="4"'), ("2.17", "precisionUsed")),
    (
        "repeated fact",
        _insert(
            '<eba_met:mi1 contextRef="c1" unitRef="EUR" decimals="-3">1000</eba_met:mi1>'
        ),
        ("2.16", "duplicateFactXBRL-XML"),
    ),
    (
        "fact in a second unit",
        _insert(
            '<eba_met:mi1 contextRef="c1" unitRef="USD" decimals="-3">9</eba_met:mi1>'
        ),
        ("2.16.1", "factsDifferingOnlyByUnit"),
    ),
    (
        "non-monetary unit other than pure",
        _swap(
            "<xbrli:measure>xbrli:pure</xbrli:measure>",
            "<xbrli:measure>eba_met:shares</xbrli:measure>",
        ),
        ("3.2", "pureUnitNotUsedForMonetaryValue"),
    ),
    (
        "second reporting currency",
        _insert(
            '<eba_met:mi3 contextRef="c1" unitRef="USD" decimals="0">7</eba_met:mi3>'
        ),
        ("3.1", "multipleReportingCurrencies"),
    ),
    (
        "currency unlike its dimension",
        _swap('contextRef="c2" unitRef="USD"', 'contextRef="c2" unitRef="EUR"'),
        ("3.1", "inconsistentCurrencyUnitAndDimension"),
    ),
    (
        "unused context",
        _swap("<xbrli:unit ", _context("c3") + "<xbrli:unit "),
        ("2.7", "unusedContext"),
    ),
    (
        "duplicate context",
        _insert(
            _context("c3")
            + '<eba_met:mi4 contextRef="c3" unitRef="EUR" decimals="0">1</eba_met:mi4>'
        ),
        ("2.7", "duplicateContext"),
    ),
    (
        "unused unit",
        _insert(
            '<xbrli:unit id="GBP"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>'
        ),
        ("2.22", "unusedUnit"),
    ),
    (
        "duplicate unit",
        _insert(
            '<xbrli:unit id="EUR2"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>'
            '<eba_met:mi4 contextRef="c1" unitRef="EUR2" decimals="0">1</eba_met:mi4>'
        ),
        ("2.21", "duplicateUnit"),
    ),
    (
        "namespace declared on a fact",
        _insert('<q:si9 xmlns:q="http://q" contextRef="c1">x</q:si9>'),
        ("3.9", "unexpectedNamespaceDeclarations"),
    ),
    (
        "two prefixes for one namespace",
        _swap(
            "<xbrli:xbrl ",
            '<xbrli:xbrl xmlns:met="http://www.eba.europa.eu/xbrl/crr/dict/met" ',
        ),
        ("3.10", "multiplePrefixForNamespace"),
    ),
    (
        "unused prefix",
        _swap("<xbrli:xbrl ", '<xbrli:xbrl xmlns:unused="http://unused" '),
        ("3.4", "unusedNamespacePrefix"),
    ),
    (
        "lower-case subject",
        _swap(f">{LEI}.CON<", f">{LEI.lower()}.con<"),
        ("3.6", "reportingSubjectNotUppercase"),
    ),
]


@pytest.mark.parametrize(
    ("change", "expected"),
    [pytest.param(change, expected, id=label) for label, change, expected in XML_CASES],
)
def test_each_xml_filing_rule_is_detected(
    change: Callable[[str], str], expected: tuple[str, str]
) -> None:
    assert expected in _read_xml(change(CLEAN_XML))


def test_enumerated_fact_values_count_as_namespace_use() -> None:
    xml = CLEAN_XML.replace(
        "<xbrli:xbrl ",
        '<xbrli:xbrl xmlns:eba_ZZ="http://www.eba.europa.eu/xbrl/crr/dict/dom/ZZ" ',
    ).replace(CLOSE, '<eba_met:ei1 contextRef="c1">eba_ZZ:x840</eba_met:ei1>' + CLOSE)
    assert ("3.4", "unusedNamespacePrefix") not in _read_xml(xml)


def test_findings_count_repeats_and_keep_five_examples() -> None:
    facts = "".join(
        f'<eba_met:n{index} xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'id="n{index}" contextRef="c1" unitRef="EUR" xsi:nil="true"/>'
        for index in range(7)
    )
    report = read_report(
        CLEAN_XML.replace(CLOSE, facts + CLOSE).encode(), name="i.xbrl"
    )
    nil = next(item for item in report.filing if item.code == "nilUsed")
    assert nil.count == 7
    assert nil.examples == tuple(f"i.xbrl#n{index}" for index in range(5))
    assert nil.severity == "error" and RULE_TITLES[nil.rule] == "Nil and empty values"


# xBRL-CSV ------------------------------------------------------------------------


def _clean_csv(**overrides: str | None) -> dict[str, str | bytes]:
    return open_files(
        **{
            "reports/parameters.csv": csv_text(
                "name,value",
                f"entityID,rs:{LEI}.CON",
                "refPeriod,2024-12-31",
                "baseCurrency,iso4217:EUR",
                "decimalsMonetary,-3",
            ),
            "reports/FilingIndicators.csv": csv_text(
                "templateID,reported", "C_01.00,true", "C_27.00,true", "C_02.00,false"
            ),
            **overrides,
        }
    )


def _read_csv(
    tmp_path: Path, files: dict[str, str | bytes], *, name: str = NAME, root: str = NAME
) -> set[tuple[str, str]]:
    path = write_zip(tmp_path / f"{name}.zip", files, root=f"{root}/" if root else "")
    return {(item.rule, item.code) for item in read_report(path).filing}


def test_a_compliant_package_breaks_no_filing_rule(tmp_path: Path) -> None:
    assert _read_csv(tmp_path, _clean_csv()) == set()


CSV_CASES: list[tuple[str, dict[str, str | None], tuple[str, str]]] = [
    (
        "no report package file",
        {"META-INF/reportPackage.json": None},
        ("Package", "missingReportPackageJson"),
    ),
    (
        "taxonomy in documentInfo",
        {
            "reports/report.json": report_json().replace(
                '"documentInfo": {', '"documentInfo": {"taxonomy": ["x.xsd"], ', 1
            )
        },
        ("1.5", "multipleTaxonomyRefs"),
    ),
    (
        "two entry points",
        {
            "reports/report.json": report_json(
                extends=[
                    "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json",
                    "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_lr.json",
                ]
            )
        },
        ("2.3", "multipleTaxonomyRefs"),
    ),
    (
        "relative entry point",
        {"reports/report.json": report_json(extends=["corep_of.json"])},
        ("2.2", "inappropriateTaxonomyRef"),
    ),
    (
        "basic-format reference date",
        {
            "reports/parameters.csv": csv_text(
                "name,value", f"entityID,rs:{LEI}.CON", "refPeriod,20241231"
            )
        },
        ("2.10", "periodWithTimezone"),
    ),
    (
        "no reference date",
        {"reports/parameters.csv": csv_text("name,value", f"entityID,rs:{LEI}.CON")},
        ("Package", "missingReferencePeriod"),
    ),
    (
        "repeated filing indicator",
        {
            "reports/FilingIndicators.csv": csv_text(
                "templateID,reported", "C_01.00,true", "C_27.00,true", "C_01.00,true"
            )
        },
        ("1.6.1", "duplicateFilingIndicator"),
    ),
    (
        "table of a template not reported",
        {
            "reports/FilingIndicators.csv": csv_text(
                "templateID,reported", "C_01.00,true", "C_27.00,false"
            )
        },
        ("xBRL-CSV 6", "tableForNegativeFilingIndicator"),
    ),
    (
        "decimals suffix",
        {"reports/c_01.00.csv": csv_text("datapoint,factValue", "dp1,78920030d-4")},
        ("xBRL-CSV 1", "decimalsSuffixUsed"),
    ),
    (
        "spaces around a value",
        {"reports/c_01.00.csv": csv_text("datapoint,factValue", "dp1, text")},
        ("3.11", "leadingOrTrailingSpacesInText"),
    ),
    (
        "#none value",
        {"reports/c_01.00.csv": csv_text("datapoint,factValue", "dp1,#none")},
        ("xBRL-CSV 5", "specialValueUsed"),
    ),
    (
        "special key value",
        {
            "reports/c_27.00.csv": csv_text(
                "datapoint,factValue,c0010,c0020", "dp100,ABC,#empty,eba_qCO:qx2000"
            )
        },
        ("xBRL-CSV 5", "specialKeyValueUsed"),
    ),
]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [pytest.param(change, expected, id=label) for label, change, expected in CSV_CASES],
)
def test_each_csv_filing_rule_is_detected(
    tmp_path: Path, overrides: dict[str, str | None], expected: tuple[str, str]
) -> None:
    assert expected in _read_csv(tmp_path, _clean_csv(**overrides))


def test_the_root_folder_is_named_as_the_file(tmp_path: Path) -> None:
    assert _read_csv(tmp_path, _clean_csv(), root="report") == {
        ("File naming", "invalidRootFolder")
    }


# Reporting subject and file name ------------------------------------------------


def _report(
    scheme: str | None,
    identifier: str | None,
    *,
    reference: date = date(2024, 12, 31),
    entry_point: str = XSD,
) -> Report:
    return Report(
        format="xbrl-xml",
        entry_point=entry_point,
        entity_scheme=scheme,
        entity_id=identifier,
        reference_date=reference,
        base_currency=None,
        parameters={},
        decimals_parameters={},
        filing_indicators={},
        facts=(),
        namespaces={},
    )


def _subject(report: Report) -> set[tuple[str, str, str]]:
    log = FilingLog()
    check_subject(report, log)
    return {(item.rule, item.code, item.severity) for item in log.result()}


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        pytest.param(_report(RS, f"{LEI}.CON"), set(), id="suffix with rs"),
        pytest.param(
            _report(LEI_SCHEME, LEI, reference=date(2021, 12, 31)),
            set(),
            id="bare LEI before 2022",
        ),
        pytest.param(
            _report(
                LEI_SCHEME, LEI, entry_point=XSD.replace("corep_of", "corep_of_con")
            ),
            set(),
            id="bare LEI for a _con module",
        ),
        pytest.param(
            _report(RS, "LEIIDENTIFIERABCDEFG-TOKENABC.IND"),
            set(),
            id="MiCA issuer and token",
        ),
        pytest.param(_report(RS, "IT000.MEMSTAAGGALL"), set(), id="aggregate"),
        pytest.param(
            _report(LEI_SCHEME, LEI),
            {("3.6", "missingReportingSubjectSuffix", "warning")},
            id="bare LEI after 2022",
        ),
        pytest.param(
            _report(RS, f"{LEI}.CON", reference=date(2021, 12, 31)),
            {("3.6", "unexpectedReportingSubjectSuffix", "warning")},
            id="suffix before 2022",
        ),
        pytest.param(
            _report(LEI_SCHEME, f"{LEI}.CON"),
            {("3.6", "inappropriateScheme", "error")},
            id="suffix with the LEI scheme",
        ),
        pytest.param(
            _report(RS, LEI),
            {("3.6", "inappropriateScheme", "error")},
            id="rs without a suffix",
        ),
        pytest.param(
            _report(
                "http://standard.iso.org/iso/17442", LEI, reference=date(2021, 1, 1)
            ),
            {("3.6", "incorrectLeiScheme", "warning")},
            id="historic LEI scheme spelling",
        ),
        pytest.param(
            _report(RS, "DUMMYLEI123456789012.CON"),
            {("2.8", "unacceptableIdentifier", "error")},
            id="LEI with wrong check digits",
        ),
        pytest.param(
            _report(RS, f"{LEI.lower()}.CON"),
            {("3.6", "reportingSubjectNotUppercase", "error")},
            id="lower case",
        ),
        pytest.param(
            _report("http://example.com/ids", "ABC"),
            {("2.8", "inappropriateScheme", "warning")},
            id="other scheme",
        ),
        pytest.param(
            _report(None, None),
            {("2.8", "missingIdentifier", "error")},
            id="no subject",
        ),
    ],
)
def test_reporting_subject(report: Report, expected: set[tuple[str, str, str]]) -> None:
    assert _subject(report) == expected


def test_lei_check_digits_follow_iso_7064() -> None:
    # Published LEIs: a valid one and the same with its check digits changed.
    assert (
        _subject(
            _report(LEI_SCHEME, "5493001KJTIIGC8Y1R12", reference=date(2020, 1, 1))
        )
        == set()
    )
    assert ("2.8", "unacceptableIdentifier", "error") in _subject(
        _report(LEI_SCHEME, "5493001KJTIIGC8Y1R13", reference=date(2020, 1, 1))
    )


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        (f"{NAME}.zip", None),
        ("report.zip", "does not follow"),
        (
            f"{LEI}.IND_FR_COREP040000_COREPOF_2024-12-31_20250101000000000.zip",
            "reporting subject",
        ),
        (
            f"{LEI}.CON_France_COREP040000_COREPOF_2024-12-31_20250101000000000.zip",
            "country",
        ),
        (f"{LEI}.CON_FR_COREP4_COREPOF_2024-12-31_20250101000000000.zip", "six-digit"),
        (
            f"{LEI}.CON_FR_COREP040000_COREPLR_2024-12-31_20250101000000000.zip",
            "module COREPLR",
        ),
        (
            f"{LEI}.CON_FR_COREP040000_COREPOF_2025-03-31_20250101000000000.zip",
            "reference date",
        ),
        (f"{LEI}.CON_FR_COREP040000_COREPOF_2024-12-31_2025.zip", "timestamp"),
    ],
)
def test_file_name(name: str, problem: str | None) -> None:
    log = FilingLog()
    check_file_name(name, _report(RS, f"{LEI}.CON"), log)
    messages = [item.message for item in log.result()]
    if problem is None:
        assert messages == []
    else:
        assert len(messages) == 1 and problem in messages[0], messages


def test_findings_sort_in_document_order() -> None:
    log = FilingLog()
    for rule in ["File naming", "xBRL-CSV 5", "3.1", "2.16.1", "2.16", "1.10", "1.6"]:
        log.add(rule, "x", "error", "m")
    assert [item.rule for item in sort_findings(log.result())] == [
        "1.6",
        "1.10",
        "2.16",
        "2.16.1",
        "3.1",
        "xBRL-CSV 5",
        "File naming",
    ]
