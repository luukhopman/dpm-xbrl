"""Build the small sample reports that the documentation's examples read.

The samples live in ``docs/samples`` so that readers can download them from
the site and run the examples themselves. They are generated here from the
test fixtures, byte for byte reproducibly, and ``tests/test_docs.py`` checks
that the committed files are current. Regenerate them with::

    uv run python -m tests.docs_samples
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from tests.support import (
    CSV_DOCUMENT_TYPE,
    NAMESPACES,
    PACKAGE_DOCUMENT_TYPE,
    csv_text,
    metadata_files,
    report_json,
    taxonomy_files,
)

SAMPLES = Path(__file__).resolve().parent.parent / "docs" / "samples"

ENTRY_POINT = "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json"
SUBJECT = "SYNTHETICDPMXL000002.CON"


def _zip(files: Mapping[str, str | bytes], *, root: str) -> bytes:
    """Return a ZIP of ``files`` below ``root`` with fixed timestamps."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = ZipInfo(f"{root}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(info, data)
    return buffer.getvalue()


def _corep_le(**overrides: str | None) -> dict[str, str]:
    """Return the files of a small COREP large-exposures package."""
    files: dict[str, str | None] = {
        "META-INF/reportPackage.json": json.dumps(
            {"documentInfo": {"documentType": PACKAGE_DOCUMENT_TYPE}}, indent=2
        ),
        "reports/report.json": json.dumps(
            {
                "documentInfo": {
                    "documentType": CSV_DOCUMENT_TYPE,
                    "extends": [ENTRY_POINT],
                }
            },
            indent=2,
        ),
        "reports/parameters.csv": csv_text(
            "name,value",
            f"entityID,rs:{SUBJECT}",
            "refPeriod,2025-12-31",
            "baseCurrency,iso4217:EUR",
            "decimalsInteger,0",
            "decimalsMonetary,-3",
            "decimalsPercentage,4",
        ),
        "reports/FilingIndicators.csv": csv_text(
            "templateID,reported",
            "C_00.01,true",
            "C_26.00,true",
            "C_27.00,true",
            "C_28.00,true",
            "C_29.00,false",
        ),
        "reports/c_00.01.csv": csv_text(
            "datapoint,factValue",
            "dp37969,eba_qSC:qx9",
            "dp31870,eba_qAS:qx2004",
        ),
        "reports/c_26.00.csv": csv_text(
            "datapoint,factValue",
            "dp457468,56058000",
            "dp32024,92592000",
            "dp32026,86911000",
            "dp32025,0.71",
        ),
        "reports/c_27.00.csv": csv_text(
            "datapoint,factValue,qINC,qNCO",
            "dp5486584,Northwind Holdings,CP0001,eba_qCO:qx2000",
            "dp5485645,eba_NC:DE,CP0001,eba_qCO:qx2000",
            "dp5486584,Contoso Group,CP0002,eba_qCO:qx2000",
            "dp5485645,eba_NC:FR,CP0002,eba_qCO:qx2000",
        ),
        "reports/c_28.00.csv": csv_text(
            "datapoint,factValue,qINC",
            "dp5488013,67129000,CP0001",
            "dp5488014,60309000,CP0001",
            "dp5488013,41250000,CP0002",
            "dp5488014,38900000,CP0002",
        ),
    }
    files.update(overrides)
    return {name: text for name, text in files.items() if text is not None}


def _needs_fixes() -> dict[str, str]:
    """Return the COREP package with values that break EBA filing rules."""
    return _corep_le(
        **{
            "reports/c_26.00.csv": csv_text(
                "datapoint,factValue",
                "dp457468,56058d-3",
                "dp32024,#nil",
                "dp32026,86911000",
                "dp32025,0.71",
            ),
            "reports/c_27.00.csv": csv_text(
                "datapoint,factValue,qINC,qNCO",
                "dp5486584,Northwind Holdings,CP0001 ,eba_qCO:qx2000",
                "dp5485645,eba_NC:DE,CP0001 ,eba_qCO:qx2000",
            ),
            "reports/c_29.00.csv": csv_text(
                "datapoint,factValue,qINC,qGCC",
                "dp5488020,87312000,CP0001,GC0001",
            ),
        }
    )


INSTANCE = f"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:link="http://www.xbrl.org/2003/linkbase"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
    xmlns:find="http://www.eurofiling.info/xbrl/ext/filing-indicators"
    xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
    xmlns:eba_met="http://www.eba.europa.eu/xbrl/crr/dict/met"
    xmlns:eba_dim="http://www.eba.europa.eu/xbrl/crr/dict/dim"
    xmlns:eba_typ="http://www.eba.europa.eu/xbrl/crr/dict/typ"
    xmlns:eba_qCO="http://www.eba.europa.eu/xbrl/crr/dict/dom/qCO">
  <link:schemaRef xlink:type="simple"
      xlink:href="{ENTRY_POINT.removesuffix(".json")}.xsd"/>
  <find:fIndicators>
    <find:filingIndicator contextRef="c0">C_26.00</find:filingIndicator>
    <find:filingIndicator contextRef="c0">C_27.00</find:filingIndicator>
    <find:filingIndicator contextRef="c0" find:filed="false">C_29.00</find:filingIndicator>
  </find:fIndicators>
  <xbrli:context id="c0">
    <xbrli:entity>
      <xbrli:identifier scheme="https://eurofiling.info/eu/rs">{SUBJECT}</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c1">
    <xbrli:entity>
      <xbrli:identifier scheme="https://eurofiling.info/eu/rs">{SUBJECT}</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
    <xbrli:scenario>
      <xbrldi:explicitMember dimension="eba_dim:qNCO">eba_qCO:qx2000</xbrldi:explicitMember>
      <xbrldi:typedMember dimension="eba_dim:qINC"><eba_typ:qCC>CP0001</eba_typ:qCC></xbrldi:typedMember>
    </xbrli:scenario>
  </xbrli:context>
  <xbrli:unit id="u1"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
  <xbrli:unit id="u2"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
  <eba_met:mi53 id="f1" contextRef="c0" unitRef="u1" decimals="-3">56058000</eba_met:mi53>
  <eba_met:pi1 id="f2" contextRef="c0" unitRef="u2" decimals="4">0.71</eba_met:pi1>
  <eba_met:qNCO id="f3" contextRef="c1">Northwind Holdings</eba_met:qNCO>
</xbrli:xbrl>
"""


def _taxonomy() -> dict[str, str]:
    """Return a small taxonomy package that resolves ``described.zip``.

    It lists its entry point, documents the module's reference dates and
    filing indicator codes, and holds the dimension, typed domain and metric
    schemas the conversions and taxonomy checks use.
    """
    return taxonomy_files(full=True)


def samples() -> dict[str, bytes]:
    """Return each sample's file name and content.

    Returns:
        dict[str, bytes]: File name in ``docs/samples`` to its bytes.
    """
    described = {
        name: content if isinstance(content, str) else content.decode("utf-8")
        for name, content in metadata_files().items()
    }
    described["reports/report.json"] = report_json(
        namespaces={**NAMESPACES, "rs": "https://eurofiling.info/eu/rs"}
    )
    described["reports/parameters.csv"] = described["reports/parameters.csv"].replace(
        "lei:5299000000000000000A", f"rs:{SUBJECT}"
    )
    described["reports/FilingIndicators.csv"] = csv_text(
        "templateID,reported", "C_01.00,true", "C_27.00,true"
    )
    described["reports/c_01.00.csv"] = csv_text(
        "datapoint,factValue", "dp84817,1000", "dp84818,0.1234", "dp84820,Yes"
    )
    return {
        "report.zip": _zip(_corep_le(), root="report"),
        "needs_fixes.zip": _zip(_needs_fixes(), root="needs_fixes"),
        "instance.xbrl": INSTANCE.encode("utf-8"),
        "described.zip": _zip(described, root="described"),
        "taxonomy.zip": _zip(_taxonomy(), root="EBA_CRD_4.0"),
    }


def main() -> None:
    """Write the samples to ``docs/samples``."""
    SAMPLES.mkdir(parents=True, exist_ok=True)
    for name, data in samples().items():
        (SAMPLES / name).write_bytes(data)


if __name__ == "__main__":
    main()
