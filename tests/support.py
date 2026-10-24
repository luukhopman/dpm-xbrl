"""Programmatic fixtures for xBRL-CSV packages and XBRL-XML instances."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

CSV_DOCUMENT_TYPE = "https://xbrl.org/2021/xbrl-csv"
PACKAGE_DOCUMENT_TYPE = "https://xbrl.org/report-package/2023"
ENTRY_POINT = "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json"
LEI = "http://standards.iso.org/iso/17442"
NAMESPACES = {
    "eba": "http://www.eba.europa.eu/xbrl/crr",
    "lei": LEI,
    "iso4217": "http://www.xbrl.org/2003/iso4217",
}


def csv_text(*rows: str) -> str:
    return "".join(f"{row}\r\n" for row in rows)


def report_json(
    *,
    extends: list[str] | None = None,
    namespaces: Mapping[str, str] | None = None,
    document_type: str = CSV_DOCUMENT_TYPE,
    **extra: Any,
) -> str:
    info: dict[str, Any] = {
        "documentType": document_type,
        "extends": [ENTRY_POINT] if extends is None else extends,
        "namespaces": dict(NAMESPACES if namespaces is None else namespaces),
    }
    return json.dumps({"documentInfo": info, **extra}, indent=2)


def closed_files(**overrides: str | bytes | None) -> dict[str, str | bytes]:
    """Return the files of a small closed-table EBA package (root-relative)."""
    files: dict[str, str | bytes | None] = {
        "META-INF/reportPackage.json": json.dumps(
            {"documentInfo": {"documentType": PACKAGE_DOCUMENT_TYPE}}
        ),
        "reports/report.json": report_json(),
        "reports/parameters.csv": csv_text(
            "name,value",
            "entityID,lei:5299000000000000000A",
            "refPeriod,2024-12-31",
            "baseCurrency,iso4217:EUR",
            "decimalsInteger,0",
            "decimalsMonetary,-3",
            "decimalsPercentage,4",
            "decimalsDecimal,#none",
        ),
        "reports/FilingIndicators.csv": csv_text(
            "templateID,reported",
            "C_01.00,true",
            "C_02.00,false",
            "C_27.00,1",
        ),
        "reports/c_01.00.csv": csv_text(
            "datapoint,factValue",
            "dp84817,1000",
            "dp84818,-250.5",
            "dp84819,",
        ),
    }
    files.update(overrides)
    return {name: content for name, content in files.items() if content is not None}


def open_files(**overrides: str | bytes | None) -> dict[str, str | bytes]:
    """Return a package that also has an open table with key columns."""
    return closed_files(
        **{
            "reports/c_27.00.csv": csv_text(
                "datapoint,factValue,c0010,c0020",
                "dp100,ABC,cp1,eba_qCO:qx2000",
                "dp101,12.5,cp1,eba_qCO:qx2000",
                "dp100,DEF,cp2,eba_qCO:qx2001",
            ),
            **overrides,
        }
    )


def _encode(content: str | bytes) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content


def zip_bytes(files: Mapping[str, str | bytes], *, root: str = "") -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(f"{root}{name}", _encode(content))
    return buffer.getvalue()


def write_zip(
    path: Path, files: Mapping[str, str | bytes], *, root: str = "report/"
) -> Path:
    path.write_bytes(zip_bytes(files, root=root))
    return path


def write_directory(path: Path, files: Mapping[str, str | bytes]) -> Path:
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_encode(content))
    return path


def catalog_xml(rewrites: Mapping[str, str]) -> str:
    entries = "".join(
        f'  <rewriteURI uriStartString="{start}" rewritePrefix="{prefix}"/>\n'
        for start, prefix in rewrites.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        f"{entries}</catalog>\n"
    )


# Metadata-resolved xBRL-CSV --------------------------------------------------

META_NAMESPACES = {
    "eba_met": "http://www.eba.europa.eu/xbrl/crr/dict/met",
    "eba_dim": "http://www.eba.europa.eu/xbrl/crr/dict/dim",
    "eba_qCO": "http://www.eba.europa.eu/xbrl/crr/dict/dom/qCO",
    "eba_BA": "http://www.eba.europa.eu/xbrl/crr/dict/dom/BA",
    "iso4217": "http://www.xbrl.org/2003/iso4217",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "lei": LEI,
}
TAB_BASE = "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/tab/"


def module_json() -> str:
    return json.dumps(
        {
            "documentInfo": {
                "documentType": CSV_DOCUMENT_TYPE,
                "namespaces": META_NAMESPACES,
                "extends": [
                    "../tab/c_01.00/c_01.00.json",
                    "../tab/c_27.00/c_27.00.json",
                ],
            },
            "parameterURL": "parameters.csv",
            "tables": {
                "c_01.00": {
                    "template": "c_01.00",
                    "url": "c_01.00.csv",
                    "optional": True,
                },
                "c_27.00": {
                    "template": "c_27.00",
                    "url": "c_27.00.csv",
                    "optional": True,
                },
            },
        }
    )


def closed_template_json() -> str:
    return json.dumps(
        {
            "documentInfo": {
                "documentType": CSV_DOCUMENT_TYPE,
                "namespaces": META_NAMESPACES,
            },
            "tableTemplates": {
                "c_01.00": {
                    "dimensions": {"entity": "$entityID", "period": "$refPeriod"},
                    "columns": {
                        "datapoint": {
                            "propertyGroups": {
                                "dp84817": {
                                    "decimals": "$decimalsMonetary",
                                    "dimensions": {
                                        "concept": "eba_met:mi53",
                                        "eba_dim:BAS": "eba_BA:x6",
                                        "unit": "$baseCurrency",
                                    },
                                },
                                "dp84818": {
                                    "decimals": 4,
                                    "dimensions": {
                                        "concept": "eba_met:pi1",
                                        "unit": "xbrli:pure",
                                    },
                                },
                                "dp84820": {
                                    "dimensions": {"concept": "eba_met:ei2"},
                                },
                            }
                        },
                        "factValue": {"propertiesFrom": ["datapoint"]},
                    },
                }
            },
        }
    )


def open_template_json() -> str:
    return json.dumps(
        {
            "documentInfo": {
                "documentType": CSV_DOCUMENT_TYPE,
                "namespaces": META_NAMESPACES,
            },
            "tableTemplates": {
                "c_27.00": {
                    "dimensions": {"entity": "$entityID", "period": "$refPeriod"},
                    "columns": {
                        "c0010": {},
                        "c0020": {},
                        "datapoint": {
                            "propertyGroups": {
                                "dp100": {
                                    "dimensions": {
                                        "concept": "eba_met:qNCO",
                                        "eba_dim:qINC": "$c0010",
                                        "eba_dim:qCO": "$c0020",
                                    }
                                },
                                "dp101": {
                                    "decimals": "$decimalsMonetary",
                                    "dimensions": {
                                        "concept": "eba_met:mi1",
                                        "eba_dim:qINC": "$c0010",
                                        "eba_dim:qCO": "$c0020",
                                        "unit": "$baseCurrency",
                                    },
                                },
                            }
                        },
                        "factValue": {"propertiesFrom": ["datapoint"]},
                    },
                }
            },
        }
    )


def metadata_files() -> dict[str, str | bytes]:
    return open_files(
        **{
            "reports/c_01.00.csv": csv_text(
                "datapoint,factValue",
                "dp84817,1000",
                "dp84818,0.1234",
                "dp84820,#nil",
            )
        }
    )


DICT = "www.eba.europa.eu/eu/fr/xbrl/crr/dict/"
SCHEMA_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:xbrldt="http://xbrl.org/2005/xbrldt" '
    'xmlns:num="http://www.xbrl.org/dtr/type/numeric" '
)
DICTIONARY_SCHEMAS = {
    f"{DICT}dim/dim.xsd": SCHEMA_HEAD
    + 'xmlns:eba_dim="http://www.eba.europa.eu/xbrl/crr/dict/dim" '
    'targetNamespace="http://www.eba.europa.eu/xbrl/crr/dict/dim">\n'
    '  <xs:element name="qINC" id="eba_qINC" substitutionGroup="xbrldt:dimensionItem" '
    'type="xbrli:stringItemType" xbrldt:typedDomainRef="../dom/typ.xsd#eba_CC"/>\n'
    '  <xs:element name="qCO" id="eba_qCO" substitutionGroup="xbrldt:dimensionItem" '
    'type="xbrli:stringItemType"/>\n'
    "</xs:schema>\n",
    f"{DICT}dom/typ.xsd": SCHEMA_HEAD
    + 'xmlns:eba_typ="http://www.eba.europa.eu/xbrl/crr/dict/typ" '
    'targetNamespace="http://www.eba.europa.eu/xbrl/crr/dict/typ">\n'
    '  <xs:element name="CC" type="xs:string" id="eba_CC"/>\n'
    "</xs:schema>\n",
    f"{DICT}met/met.xsd": SCHEMA_HEAD
    + 'xmlns:eba_met="http://www.eba.europa.eu/xbrl/crr/dict/met" '
    'targetNamespace="http://www.eba.europa.eu/xbrl/crr/dict/met">\n'
    '  <xs:element name="mi53" type="xbrli:monetaryItemType" id="eba_mi53"/>\n'
    '  <xs:element name="pi1" type="num:percentItemType" id="eba_pi1"/>\n'
    "</xs:schema>\n",
}
ENTRY_POINT_XSD = (
    "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.xsd"
)


def taxonomy_package(
    path: Path, *, full: bool = False, valid_from: str = "2024-01-01"
) -> Path:
    """Write a fake EBA taxonomy package with a catalog rewrite.

    With ``full``, it also lists its entry point, documents the module's
    first reference date and filing indicator codes, and holds dimension,
    typed domain and metric schemas.
    """
    return write_zip(
        path, taxonomy_files(full=full, valid_from=valid_from), root="EBA_CRD_4.0/"
    )


def taxonomy_files(
    *, full: bool = False, valid_from: str = "2024-01-01"
) -> dict[str, str]:
    """Return the files of the fake EBA taxonomy package (see ``taxonomy_package``)."""
    module = json.loads(module_json())
    metadata = "<taxonomyPackage/>"
    if full:
        module["documentInfo"]["eba:documentation"] = {
            "FromReferenceDate": valid_from,
            "toReferenceDate": "",
        }
        for code, table in (("C_01.00", "c_01.00"), ("C_27.00", "c_27.00")):
            module["tables"][table]["eba:documentation"] = {"FilingIndicator": code}
        metadata = (
            '<taxonomyPackage xmlns="http://xbrl.org/2016/taxonomy-package">'
            f'<entryPoints><entryPoint><entryPointDocument href="{ENTRY_POINT_XSD}"/>'
            "</entryPoint></entryPoints></taxonomyPackage>"
        )
    return {
        "META-INF/catalog.xml": catalog_xml(
            {"http://www.eba.europa.eu/eu/fr/xbrl/": "../www.eba.europa.eu/eu/fr/xbrl/"}
        ),
        "META-INF/taxonomyPackage.xml": metadata,
        "www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json": (
            json.dumps(module)
        ),
        **(DICTIONARY_SCHEMAS if full else {}),
        "www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/tab/c_01.00/c_01.00.json": (
            closed_template_json()
        ),
        "www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/tab/c_27.00/c_27.00.json": (
            open_template_json()
        ),
    }


# XBRL-XML ------------------------------------------------------------------------

XML_INSTANCE = """<?xml version="1.0" encoding="UTF-8"?>
<!-- generated for tests -->
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:link="http://www.xbrl.org/2003/linkbase"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:find="http://www.eurofiling.info/xbrl/ext/filing-indicators"
    xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
    xmlns:eba_met="http://www.eba.europa.eu/xbrl/crr/dict/met"
    xmlns:eba_dim="http://www.eba.europa.eu/xbrl/crr/dict/dim"
    xmlns:eba_qOR="http://www.eba.europa.eu/xbrl/crr/dict/dom/qOR"
    xmlns:eba_typ="http://www.eba.europa.eu/xbrl/crr/dict/typ">
  <link:schemaRef xlink:type="simple"
      xlink:href="http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.xsd"/>
  <find:fIndicators>
    <find:filingIndicator contextRef="c0">C_01.00</find:filingIndicator>
    <find:filingIndicator contextRef="c0" find:filed="false">C_02.00</find:filingIndicator>
  </find:fIndicators>
  <xbrli:context id="c0">
    <xbrli:entity>
      <xbrli:identifier scheme="http://standards.iso.org/iso/17442">5299000000000000000A</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c1">
    <xbrli:entity>
      <xbrli:identifier scheme="http://standards.iso.org/iso/17442">5299000000000000000A</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
    <xbrli:scenario xmlns:dom="http://www.eba.europa.eu/xbrl/crr/dict/dom/qOR">
      <xbrldi:explicitMember dimension="eba_dim:qADT">dom:qx2060</xbrldi:explicitMember>
      <xbrldi:typedMember dimension="eba_dim:qINC"><eba_typ:qCC> CP-1 </eba_typ:qCC></xbrldi:typedMember>
    </xbrli:scenario>
  </xbrli:context>
  <xbrli:unit id="EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
  <xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
  <xbrli:unit id="EURperShare">
    <xbrli:divide>
      <xbrli:unitNumerator><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unitNumerator>
      <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
    </xbrli:divide>
  </xbrli:unit>
  <eba_met:qABJ id="f1" contextRef="c1" unitRef="EUR" decimals="-3">1000</eba_met:qABJ>
  <eba_met:qABK id="f2" contextRef="c0" unitRef="pure" decimals="INF">0.25</eba_met:qABK>
  <eba_met:qABL id="f3" contextRef="c0" unitRef="EUR" xsi:nil="true"/>
  <eba_met:qABM contextRef="c0">Text &amp; more</eba_met:qABM>
  <eba_met:qABN id="f5" contextRef="c0" unitRef="EURperShare" decimals="2">1.5</eba_met:qABN>
</xbrli:xbrl>
"""
