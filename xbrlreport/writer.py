"""Write reports as EBA xBRL-CSV report packages or XBRL 2.1 XML instances."""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable, Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import IO
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .csv_reader import XBRL_CSV_DOCUMENT_TYPE
from .model import Fact, Report, ReportError
from .xml_reader import FIND, ISO4217, LINK, XBRLDI, XBRLI, XLINK, XSI

REPORT_PACKAGE_DOCUMENT_TYPE = "https://xbrl.org/report-package/2023/xbrl-csv"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_KNOWN_SCHEME_PREFIXES = {
    "http://standards.iso.org/iso/17442": "lei",
    "https://eurofiling.info/eu/rs": "rs",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_TEMPLATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")


def _open_target(target: str | Path | IO[bytes], stack: ExitStack) -> IO[bytes]:
    if isinstance(target, str | Path):
        return stack.enter_context(Path(target).expanduser().open("wb"))
    return target


# xBRL-CSV ----------------------------------------------------------------------


def _csv_bytes(rows: Iterable[Iterable[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _encode_value(value: str | None) -> str:
    if value is None:
        return "#nil"
    if value == "":
        return "#empty"
    if value.startswith("#"):
        return "#" + value
    return value


def _entity_parameter(report: Report, namespaces: dict[str, str]) -> str | None:
    if report.entity_id is None:
        return report.parameters.get("entityID")
    scheme = report.entity_scheme
    if not scheme:
        return report.entity_id
    for prefix, uri in namespaces.items():
        if uri == scheme:
            return f"{prefix}:{report.entity_id}"
    if re.fullmatch(r"[A-Za-z_][\w.-]*", scheme):
        return f"{scheme}:{report.entity_id}"
    prefix = _KNOWN_SCHEME_PREFIXES.get(scheme, "entity")
    while prefix in namespaces:
        prefix += "_"
    namespaces[prefix] = scheme
    return f"{prefix}:{report.entity_id}"


def _decimals_text(value: int | None) -> str:
    return "#none" if value is None else str(value)


def _parameter_rows(report: Report, namespaces: dict[str, str]) -> list[list[str]]:
    rows: dict[str, str] = {}
    entity = _entity_parameter(report, namespaces)
    if entity is not None:
        rows["entityID"] = entity
    if report.reference_date is not None:
        rows["refPeriod"] = report.reference_date.isoformat()
    elif "refPeriod" in report.parameters:
        rows["refPeriod"] = report.parameters["refPeriod"]
    if report.base_currency is not None:
        rows["baseCurrency"] = report.base_currency
    for key in sorted(report.decimals_parameters):
        rows[key] = _decimals_text(report.decimals_parameters[key])
    for key, value in report.parameters.items():
        rows.setdefault(key, value)
    return [["name", "value"], *([key, value] for key, value in rows.items())]


def _template_keys(facts: list[Fact], template: str) -> list[str]:
    keys: dict[str, None] = {}
    for fact in facts:
        if fact.datapoint is None:
            raise ReportError(
                f"{fact.location or template}: fact has no datapoint and cannot "
                "be written as xBRL-CSV"
            )
        for key in fact.keys:
            if key in {"datapoint", "factValue"}:
                raise ReportError(
                    f"{fact.location or template}: key column {key!r} collides "
                    "with a fact column"
                )
            keys.setdefault(key)
    return list(keys)


def _write_table(stream: IO[bytes], facts: list[Fact], keys: list[str]) -> None:
    text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
    writer = csv.writer(text, lineterminator="\r\n")
    writer.writerow(["datapoint", "factValue", *keys])
    writer.writerows(
        [
            fact.datapoint or "",
            _encode_value(fact.value),
            *(fact.keys.get(key, "") for key in keys),
        ]
        for fact in facts
    )
    text.flush()
    text.detach()


def default_package_root(report: Report) -> str:
    """Return the default top-level folder name of a written report package.

    Returns:
        str: ``<entity id>_<reference date>`` made path-safe, or ``report``.
    """
    parts = [
        part
        for part in (
            report.entity_id,
            report.reference_date.isoformat() if report.reference_date else None,
        )
        if part
    ]
    name = _SAFE_NAME.sub("_", "_".join(parts)).strip("._")
    return name or "report"


def write_xbrl_csv(
    report: Report, target: str | Path | IO[bytes], *, root: str | None = None
) -> None:
    """Write an EBA xBRL-CSV report package ZIP.

    The package holds ``META-INF/reportPackage.json``, ``reports/report.json``,
    ``parameters.csv``, ``FilingIndicators.csv`` and one
    ``datapoint,factValue,<keys>`` table per template. Output is
    deterministic: templates are sorted, facts keep their order, and ZIP
    timestamps are fixed.

    Args:
        report: Report to write; every fact needs a template and datapoint.
        target: Destination path or writable binary stream.
        root: Top-level folder name; defaults to ``default_package_root``.

    Raises:
        ReportError: If a fact lacks a template or datapoint, or a template
            or root name is not a safe file name.
    """
    folder = root if root is not None else default_package_root(report)
    if not folder or not _SAFE_TEMPLATE.match(folder):
        raise ReportError(f"unsafe report package root folder {folder!r}")
    by_template: dict[str, list[Fact]] = {}
    for fact in report.facts:
        if not fact.template:
            raise ReportError(
                f"{fact.location or 'fact'}: fact has no template and cannot be "
                "written as xBRL-CSV"
            )
        by_template.setdefault(fact.template, []).append(fact)
    for template in by_template:
        if not _SAFE_TEMPLATE.match(template) or template.casefold() in {
            "parameters",
            "filingindicators",
        }:
            raise ReportError(f"template {template!r} is not a safe table file name")

    namespaces = dict(report.namespaces)
    parameters = _parameter_rows(report, namespaces)
    document_info: dict[str, object] = {"documentType": XBRL_CSV_DOCUMENT_TYPE}
    if report.entry_point:
        document_info["extends"] = [report.entry_point]
    document_info["namespaces"] = namespaces
    files: list[tuple[str, bytes]] = [
        (
            "META-INF/reportPackage.json",
            _json_bytes(
                {"documentInfo": {"documentType": REPORT_PACKAGE_DOCUMENT_TYPE}}
            ),
        ),
        ("reports/report.json", _json_bytes({"documentInfo": document_info})),
        ("reports/parameters.csv", _csv_bytes(parameters)),
        (
            "reports/FilingIndicators.csv",
            _csv_bytes(
                [
                    ["templateID", "reported"],
                    *(
                        [code, "true" if reported else "false"]
                        for code, reported in sorted(report.filing_indicators.items())
                    ),
                ]
            ),
        ),
    ]
    tables = [
        (template, facts, _template_keys(facts, template))
        for template, facts in sorted(by_template.items())
    ]
    with ExitStack() as stack:
        stream = _open_target(target, stack)
        with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
            for name, data in files:
                archive.writestr(_zip_info(f"{folder}/{name}"), data)
            for template, facts, keys in tables:
                info = _zip_info(f"{folder}/reports/{template}.csv")
                with archive.open(info, "w", force_zip64=True) as member:
                    _write_table(member, facts, keys)


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# XBRL-XML ----------------------------------------------------------------------


class _Namespaces:
    def __init__(self, declared: Mapping[str, str]) -> None:
        self.declared = {prefix: uri for prefix, uri in declared.items() if prefix}

    def prefix(self, uri: str, preferred: str) -> str:
        for prefix, bound in self.declared.items():
            if bound == uri:
                return prefix
        candidate = preferred
        while candidate in self.declared:
            candidate += "_"
        self.declared[candidate] = uri
        return candidate

    def check(self, qname: str, where: str) -> str:
        prefix, separator, local = qname.partition(":")
        if not separator or not local or prefix not in self.declared:
            raise ReportError(
                f"{where}: {qname!r} is not a qname with a declared prefix"
            )
        return qname


def write_xbrl_xml(
    report: Report,
    target: str | Path | IO[bytes],
    *,
    typed_domains: Mapping[str, str] | None = None,
) -> None:
    """Write an XBRL 2.1 XML instance.

    Contexts are deduplicated per dimension combination (ids ``c1``, ``c2``
    in first-use order) and use the report entity and an instant at the
    reference date; dimensions are written in the scenario. Facts with a unit
    are numeric and get ``decimals`` (``INF`` when unset) unless nil.

    Args:
        report: Report to write; every fact needs a concept.
        target: Destination path or writable binary stream.
        typed_domains: Typed dimension qname to the qname of its typed domain
            element, required for each typed dimension used by a fact.

    Raises:
        ReportError: If a fact lacks a concept, the entity or reference date
            is missing, a prefix is undeclared, or a typed domain is unknown.
    """
    if not report.entity_id or not report.entity_scheme:
        raise ReportError("XBRL-XML output requires an entity scheme and identifier")
    if report.reference_date is None:
        raise ReportError("XBRL-XML output requires a reference date")
    domains = dict(typed_domains or {})
    namespaces = _Namespaces(report.namespaces)
    xbrli = namespaces.prefix(XBRLI, "xbrli")
    link = namespaces.prefix(LINK, "link")
    xlink = namespaces.prefix(XLINK, "xlink")
    xbrldi = namespaces.prefix(XBRLDI, "xbrldi")
    xsi = namespaces.prefix(XSI, "xsi")
    find = namespaces.prefix(FIND, "find")
    namespaces.prefix(ISO4217, "iso4217")

    contexts: dict[tuple[tuple[str, str], ...], str] = {}
    context_dimensions: list[tuple[str, dict[str, str], dict[str, str]]] = []
    units: dict[str, str] = {}

    def context_id(dimensions: Mapping[str, str], typed: Mapping[str, str]) -> str:
        key = tuple(
            sorted(
                [(f"e:{dim}", member) for dim, member in dimensions.items()]
                + [(f"t:{dim}", value) for dim, value in typed.items()]
            )
        )
        existing = contexts.get(key)
        if existing is None:
            existing = contexts[key] = f"c{len(contexts) + 1}"
            context_dimensions.append((existing, dict(dimensions), dict(typed)))
        return existing

    if report.filing_indicators:
        context_id({}, {})
    fact_lines: list[str] = []
    for fact in report.facts:
        where = fact.location or "fact"
        if not fact.concept:
            raise ReportError(
                f"{where}: fact has no concept and cannot be written as XBRL-XML"
            )
        concept = namespaces.check(fact.concept, where)
        for dimension, member in fact.dimensions.items():
            namespaces.check(dimension, where)
            namespaces.check(member, where)
        for dimension in fact.typed_dimensions:
            namespaces.check(dimension, where)
            if dimension not in domains:
                raise ReportError(
                    f"{where}: no typed domain element given for typed "
                    f"dimension {dimension}"
                )
            namespaces.check(domains[dimension], f"typed domain of {dimension}")
        context = context_id(fact.dimensions, fact.typed_dimensions)
        attributes = [f"contextRef={quoteattr(context)}"]
        if fact.unit is not None:
            for measure in re.split(r"[*/]", fact.unit):
                namespaces.check(measure, where)
            unit_id = units.setdefault(fact.unit, f"u{len(units) + 1}")
            attributes.append(f"unitRef={quoteattr(unit_id)}")
            if fact.value is not None:
                decimals = "INF" if fact.decimals is None else str(fact.decimals)
                attributes.append(f"decimals={quoteattr(decimals)}")
        if fact.value is None:
            attributes.append(f'{xsi}:nil="true"')
            fact_lines.append(f"  <{concept} {' '.join(attributes)}/>")
        else:
            fact_lines.append(
                f"  <{concept} {' '.join(attributes)}>{escape(fact.value)}</{concept}>"
            )

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    declarations = " ".join(
        f"xmlns:{prefix}={quoteattr(uri)}"
        for prefix, uri in sorted(namespaces.declared.items())
    )
    lines.append(f"<{xbrli}:xbrl {declarations}>")
    if report.entry_point:
        lines.append(
            f'  <{link}:schemaRef {xlink}:type="simple" '
            f"{xlink}:href={quoteattr(report.entry_point)}/>"
        )
    if report.filing_indicators:
        base = contexts[()]
        lines.append(f"  <{find}:fIndicators>")
        for code, filed in report.filing_indicators.items():
            filed_attribute = "" if filed else f' {find}:filed="false"'
            lines.append(
                f"    <{find}:filingIndicator contextRef={quoteattr(base)}"
                f"{filed_attribute}>{escape(code)}</{find}:filingIndicator>"
            )
        lines.append(f"  </{find}:fIndicators>")
    for identifier, dimensions, typed in context_dimensions:
        lines.append(f"  <{xbrli}:context id={quoteattr(identifier)}>")
        lines.append(f"    <{xbrli}:entity>")
        lines.append(
            f"      <{xbrli}:identifier scheme={quoteattr(report.entity_scheme)}>"
            f"{escape(report.entity_id)}</{xbrli}:identifier>"
        )
        lines.append(f"    </{xbrli}:entity>")
        lines.append(
            f"    <{xbrli}:period><{xbrli}:instant>"
            f"{report.reference_date.isoformat()}</{xbrli}:instant></{xbrli}:period>"
        )
        if dimensions or typed:
            lines.append(f"    <{xbrli}:scenario>")
            lines.extend(
                f"      <{xbrldi}:explicitMember dimension={quoteattr(dimension)}>"
                f"{escape(dimensions[dimension])}</{xbrldi}:explicitMember>"
                for dimension in sorted(dimensions)
            )
            for dimension in sorted(typed):
                domain = domains[dimension]
                lines.append(
                    f"      <{xbrldi}:typedMember dimension={quoteattr(dimension)}>"
                    f"<{domain}>{escape(typed[dimension])}</{domain}>"
                    f"</{xbrldi}:typedMember>"
                )
            lines.append(f"    </{xbrli}:scenario>")
        lines.append(f"  </{xbrli}:context>")
    for unit, unit_id in units.items():
        lines.append(f"  <{xbrli}:unit id={quoteattr(unit_id)}>")
        numerator, separator, denominator = unit.partition("/")
        if separator:
            lines.append(f"    <{xbrli}:divide>")
            for part, measures in (
                ("unitNumerator", numerator),
                ("unitDenominator", denominator),
            ):
                lines.append(f"      <{xbrli}:{part}>")
                lines.extend(
                    f"        <{xbrli}:measure>{escape(measure)}</{xbrli}:measure>"
                    for measure in measures.split("*")
                )
                lines.append(f"      </{xbrli}:{part}>")
            lines.append(f"    </{xbrli}:divide>")
        else:
            lines.extend(
                f"    <{xbrli}:measure>{escape(measure)}</{xbrli}:measure>"
                for measure in unit.split("*")
            )
        lines.append(f"  </{xbrli}:unit>")
    lines.extend(fact_lines)
    lines.append(f"</{xbrli}:xbrl>")
    with ExitStack() as stack:
        stream = _open_target(target, stack)
        writer = io.TextIOWrapper(stream, encoding="utf-8", newline="\n")
        try:
            for line in lines:
                writer.write(line)
                writer.write("\n")
            writer.flush()
        finally:
            writer.detach()
