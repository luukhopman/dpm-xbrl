"""Write reports as EBA xBRL-CSV report packages or XBRL 2.1 XML instances."""

from __future__ import annotations

import csv
import io
import json
import math
import posixpath
import re
import warnings
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import IO
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from ._module import (
    PURE,
    Member,
    Namespaces,
    Placement,
    PlacementIndex,
    describe,
    fact_members,
    load_module,
    module_json_url,
)
from ._taxonomy import TaxonomyPackages
from .csv_reader import XBRL_CSV_DOCUMENT_TYPE
from .model import Fact, Limits, Report, ReportError, SkippedFacts
from .xml_reader import FIND, ISO4217, LINK, XBRLDI, XBRLI, XLINK, XSI

REPORT_PACKAGE_DOCUMENT_TYPE = "https://xbrl.org/report-package/2023"
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


def _rows(facts: list[Fact], keys: list[str]) -> Iterator[list[str]]:
    for fact in facts:
        yield [
            fact.datapoint or "",
            _encode_value(fact.value),
            *(fact.keys.get(key, "") for key in keys),
        ]


def _write_table(
    stream: IO[bytes], header: Sequence[str], rows: Iterable[Sequence[str]]
) -> None:
    text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
    writer = csv.writer(text, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    text.flush()
    text.detach()


def _target_root(target: str | Path | IO[bytes], report: Report) -> str:
    """Name the root folder as the ZIP file, as the EBA filing rules ask.

    Returns:
        str: The target's file name without ``.zip``, or
        ``default_package_root(report)`` for a stream or another name.
    """
    if isinstance(target, str | Path):
        name = Path(target).name
        if name.casefold().endswith(".zip") and _SAFE_TEMPLATE.match(name[:-4]):
            return name[:-4]
    return default_package_root(report)


def default_package_root(report: Report) -> str:
    """Return the default top-level folder name of a written report package.

    Args:
        report: Report whose entity and reference date name the folder.

    Returns:
        str: ``<entity id>_<reference date>`` made path-safe, or ``report``.

    Examples:
        >>> from dpmxbrl import default_package_root, read_report
        >>> default_package_root(read_report("report.zip"))
        'SYNTHETICDPMXL000002.CON_2025-12-31'
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
    report: Report,
    target: str | Path | IO[bytes],
    *,
    root: str | None = None,
    taxonomy_packages: Sequence[str | Path] = (),
    strict: bool = True,
    limits: Limits = Limits(),
) -> SkippedFacts:
    """Write an EBA xBRL-CSV report package ZIP.

    The package holds ``META-INF/reportPackage.json``, ``reports/report.json``,
    ``parameters.csv``, ``FilingIndicators.csv`` and one
    ``datapoint,factValue,<keys>`` table per template. Output is
    deterministic: templates are sorted, facts keep their order, and ZIP
    timestamps are fixed.

    With ``taxonomy_packages``, the module's JSON entry point (the entry
    point with ``.json`` for ``.xsd``) gives the tables: each fact with a
    concept, such as one read from XML, goes in every table row whose data
    point has its concept and dimensions, with the module's table files,
    columns and prefixes. ``report.json`` extends the JSON entry point, and
    ``baseCurrency`` and the ``decimals*`` parameters come from the facts.
    Facts without a concept keep their template and datapoint.

    Args:
        report: Report to write; without taxonomy packages every fact needs a
            template and datapoint.
        target: Destination path or writable binary stream.
        root: Top-level folder name; defaults to the target's file name
            without ``.zip``, as the EBA filing rules ask, or to
            ``default_package_root`` for a stream.
        taxonomy_packages: Local taxonomy package ZIPs holding the module's
            xBRL-CSV metadata, used to place facts by concept.
        strict: With taxonomy packages, whether a fact that cannot be placed
            exactly raises ``ReportError``; when ``False`` it is left out and
            returned.
        limits: Resource limits for reading the taxonomy packages.

    Returns:
        SkippedFacts: The facts left out, each with the reason; always
        empty when ``strict`` is true.

    Raises:
        ReportError: If a fact lacks a template or datapoint (without
            taxonomy packages) or cannot be placed (with them, in strict
            mode), the module metadata is missing, or a template or root name
            is not a safe file name.

    Examples:
        >>> from dpmxbrl import read_report, write_xbrl_csv
        >>> report = read_report("report.zip")
        >>> write_xbrl_csv(report, "copy.zip", root="copy")
        >>> read_report("copy.zip").facts == report.facts
        True
    """
    folder = root if root is not None else _target_root(target, report)
    if not folder or not _SAFE_TEMPLATE.match(folder):
        raise ReportError(f"unsafe report package root folder {folder!r}")
    placed: _PlacedTables | None = None
    if taxonomy_packages:
        if not report.entry_point:
            raise ReportError(
                "the report names no entry point, so its module's tables are unknown"
            )
        taxonomy = TaxonomyPackages(taxonomy_packages, limits=limits)
        try:
            module = load_module(taxonomy, report.entry_point, limits=limits)
        finally:
            taxonomy.close()
        placed = _place_facts(report, PlacementIndex(module), strict=strict)
    by_template: dict[str, list[Fact]] = {}
    for fact in report.facts:
        if placed is not None and fact.concept:
            continue
        if not fact.template:
            raise ReportError(
                f"{fact.location or 'fact'}: fact has no template and cannot be "
                "written as xBRL-CSV"
                + ("" if placed else "; taxonomy packages place facts by concept")
            )
        by_template.setdefault(fact.template, []).append(fact)
    for template in by_template:
        if not _SAFE_TEMPLATE.match(template) or template.casefold() in {
            "parameters",
            "filingindicators",
        }:
            raise ReportError(f"template {template!r} is not a safe table file name")
        if placed is not None and template in placed.rows:
            raise ReportError(
                f"table {template} would get facts both with and without a concept"
            )

    if placed is None:
        namespaces = dict(report.namespaces)
        parameters = _parameter_rows(report, namespaces)
        document_info: dict[str, object] = {"documentType": XBRL_CSV_DOCUMENT_TYPE}
        if report.entry_point:
            document_info["extends"] = [report.entry_point]
        document_info["namespaces"] = namespaces
    else:
        parameters = placed.parameter_rows(report)
        document_info = {
            "documentType": XBRL_CSV_DOCUMENT_TYPE,
            "extends": [placed.index.module.url],
        }
        if placed.names.extra:
            document_info["namespaces"] = dict(placed.names.extra)
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
    tables: list[tuple[str, Sequence[str], Iterable[Sequence[str]]]] = []
    for template, facts in by_template.items():
        keys = _template_keys(facts, template)
        tables.append(
            (f"{template}.csv", ["datapoint", "factValue", *keys], _rows(facts, keys))
        )
    if placed is not None:
        tables.extend(
            (table.file, table.header, placed.rows[stem])
            for stem, table in placed.index.tables.items()
            if stem in placed.rows
        )
    tables.sort(key=lambda item: item[0])
    with ExitStack() as stack:
        stream = _open_target(target, stack)
        with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
            for name, data in files:
                archive.writestr(_zip_info(f"{folder}/{name}"), data)
            for file_name, header, rows in tables:
                info = _zip_info(f"{folder}/reports/{file_name}")
                with archive.open(info, "w", force_zip64=True) as member:
                    _write_table(member, header, rows)
    return placed.skipped if placed is not None else ()


class _PlacedTables:
    """Table rows of facts placed through a module's metadata."""

    def __init__(self, index: PlacementIndex, names: Namespaces) -> None:
        self.index = index
        self.names = names
        self.rows: dict[str, list[list[str]]] = {}
        self.parameters: dict[str, str] = {}
        self.skipped: SkippedFacts = ()

    def parameter_rows(self, report: Report) -> list[list[str]]:
        namespaces = {**self.index.module.namespaces, **self.names.extra}
        rows: dict[str, str] = {}
        entity = _entity_parameter(report, namespaces)
        for prefix, uri in namespaces.items():
            if prefix not in self.index.module.namespaces:
                self.names.extra[prefix] = uri
        if entity is not None:
            rows["entityID"] = entity
        if report.reference_date is not None:
            rows["refPeriod"] = report.reference_date.isoformat()
        elif "refPeriod" in report.parameters:
            rows["refPeriod"] = report.parameters["refPeriod"]
        if "baseCurrency" in self.parameters:
            rows["baseCurrency"] = self.parameters["baseCurrency"]
        elif report.base_currency is not None:
            rows["baseCurrency"] = self.names.translate(report.base_currency)
        for key in sorted(report.decimals_parameters):
            rows[key] = _decimals_text(report.decimals_parameters[key])
        rows.update(sorted(self.parameters.items()))
        for key, value in report.parameters.items():
            rows.setdefault(key, value)
        return [["name", "value"], *([key, value] for key, value in rows.items())]


def _place_facts(
    report: Report, index: PlacementIndex, *, strict: bool
) -> _PlacedTables:
    """Place each fact with a concept in the module's table rows.

    A unit that the module takes from a parameter (``baseCurrency``) must
    be the same for all facts: the parameter gets the report's base currency
    or the most common unit, and a fact in another unit cannot be placed. A
    decimals parameter gets the lowest decimals of its facts, so that no
    value claims more accuracy than its source gave it.

    Returns:
        _PlacedTables: The rows per table and the parameter values.

    Raises:
        ReportError: In strict mode, if any fact cannot be placed exactly.
    """
    names = Namespaces(report.namespaces, index.module.namespaces)
    result = _PlacedTables(index, names)
    problems: list[tuple[Fact, str]] = []
    placed: list[tuple[Fact, list[Placement], dict[str, Member]]] = []
    votes: dict[str, Counter[str]] = {}
    lowest: dict[str, float] = {}
    cache: dict[int, object] = {}
    base_currency = report.base_currency
    module_name = posixpath.basename(index.module.url)
    for fact in report.facts:
        if not fact.concept:
            continue
        concept = names.clark(fact.concept)
        members = fact_members(fact, names, cache)
        if concept is None or members is None:
            problems.append(
                (fact, "a prefix of its concept or dimensions is undeclared")
            )
            continue
        placements = index.find(concept, members)
        if not placements:
            problems.append(
                (
                    fact,
                    f"no data point of {module_name} has concept {fact.concept} "
                    "with these dimensions",
                )
            )
            continue
        problem = _unit_problem(fact, placements[0], names)
        if problem:
            problems.append((fact, problem))
            continue
        placed.append((fact, placements, members))
        if fact.value is None:
            continue
        place = placements[0]
        if place.unit and place.unit[0] == "parameter" and fact.unit:
            votes.setdefault(place.unit[1], Counter())[names.translate(fact.unit)] += 1
        if place.decimals and fact.unit is not None:
            decimals = math.inf if fact.decimals is None else fact.decimals
            if decimals < lowest.get(place.decimals, math.inf) or (
                place.decimals not in lowest
            ):
                lowest[place.decimals] = decimals
    for parameter, counts in votes.items():
        preferred = (
            names.translate(base_currency)
            if parameter == "baseCurrency" and base_currency
            else None
        )
        result.parameters[parameter] = (
            preferred
            if preferred in counts
            else max(sorted(counts), key=lambda value: counts[value])
        )
    for parameter, decimals in lowest.items():
        result.parameters[parameter] = (
            "INF" if decimals == math.inf else str(int(decimals))
        )
    for fact, placements, members in placed:
        problem = _parameter_problem(fact, placements[0], names, result.parameters)
        if problem:
            problems.append((fact, problem))
            continue
        value = _encode_value(fact.value)
        if placements[0].enumeration and fact.value:
            value = _encode_value(names.translate_list(fact.value))
        for place in placements:
            row = [place.datapoint, value]
            row.extend(
                "" if dimension is None else _key_cell(fact, dimension, members, names)
                for dimension in place.keys
            )
            result.rows.setdefault(place.table, []).append(row)
    if problems and strict:
        shown = [f"{fact.location or 'fact'}: {reason}" for fact, reason in problems]
        raise ReportError(
            f"{len(problems)} fact{'' if len(problems) == 1 else 's'} cannot be "
            f"written as xBRL-CSV: {describe(shown, 3)}",
            problems=tuple(shown),
        )
    result.skipped = tuple(problems)
    return result


def _unit_problem(fact: Fact, place: Placement, names: Namespaces) -> str | None:
    """Return why a fact's unit does not fit its data point, if it does not."""
    keyed = "unit" in place.keys
    if keyed or (place.unit and place.unit[0] == "parameter"):
        if fact.unit is None and fact.value is not None:
            return f"data point {place.datapoint} needs a unit"
        return None
    if place.unit is not None:
        if fact.unit is not None and names.clark(fact.unit) != place.unit[1]:
            return f"its unit {fact.unit} is not {names.render(place.unit[1])}"
        return None
    if fact.unit is not None and names.clark(fact.unit) != PURE:
        return f"its unit is {fact.unit}, but data point {place.datapoint} has none"
    return None


def _parameter_problem(
    fact: Fact, place: Placement, names: Namespaces, parameters: Mapping[str, str]
) -> str | None:
    """Return why a fact differs from a parameter it uses, if it does."""
    if fact.value is None:
        return None
    if place.unit and place.unit[0] == "parameter" and fact.unit:
        expected = parameters.get(place.unit[1])
        if expected is not None and names.translate(fact.unit) != expected:
            return (
                f"its unit {fact.unit} differs from {place.unit[1]} {expected}, "
                "which the other facts use"
            )
    return None


def _key_cell(
    fact: Fact, dimension: str, members: Mapping[str, Member], names: Namespaces
) -> str:
    if dimension == "unit":
        return names.translate(fact.unit) if fact.unit else ""
    explicit, value = members[dimension]
    return names.render(value) if explicit else value


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# XBRL-XML ----------------------------------------------------------------------

# XML names: a letter or underscore, then letters, digits, "_", "." or "-".
_NCNAME = re.compile(r"[^\W\d][\w.\-\u00b7\u0300-\u036f\u203f-\u2040]*")
_PREFIX_USE = re.compile(r"([^\W\d][\w.\-\u00b7]*):")
"""A name followed by a colon: a prefix in a tag, attribute or qname value."""
_XML_ILLEGAL = re.compile(r"[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def _checked(value: str, where: str) -> str:
    match = _XML_ILLEGAL.search(value)
    if match:
        raise ReportError(
            f"{where}: {value!r} contains the character "
            f"U+{ord(match.group()):04X}, which XML cannot represent"
        )
    return value


def _text(value: str, where: str = "XBRL-XML output") -> str:
    # A literal carriage return would be read back as a line feed.
    return escape(_checked(value, where), {"\r": "&#13;"})


def _attribute(value: str) -> str:
    return quoteattr(_checked(value, "XBRL-XML output"))


class _Namespaces:
    def __init__(self, declared: Mapping[str, str]) -> None:
        self.declared = {prefix: uri for prefix, uri in declared.items() if prefix}
        for prefix in self.declared:
            if not _NCNAME.fullmatch(prefix):
                raise ReportError(f"{prefix!r} is not a valid namespace prefix")

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
        if not separator or prefix not in self.declared:
            raise ReportError(
                f"{where}: {qname!r} is not a qname with a declared prefix"
            )
        if not _NCNAME.fullmatch(local):
            raise ReportError(f"{where}: {qname!r} has an invalid local name")
        return qname


def write_xbrl_xml(
    report: Report,
    target: str | Path | IO[bytes],
    *,
    typed_domains: Mapping[str, str] | None = None,
    taxonomy_packages: Sequence[str | Path] = (),
    limits: Limits = Limits(),
) -> None:
    """Write an XBRL 2.1 XML instance.

    Contexts are deduplicated per dimension combination (ids ``c1``, ``c2``
    in first-use order) and use the report entity and an instant at the
    reference date; dimensions are written in the scenario. Facts with a unit
    are numeric and get ``decimals`` (``INF`` when unset) unless nil; a fact
    with decimals but no unit, as xBRL-CSV metadata gives pure facts, gets
    ``xbrli:pure``. A fact repeated with the same concept, dimensions, unit,
    value and decimals, as in several xBRL-CSV tables, is written once.
    The ``schemaRef`` names the module's XSD entry point: a JSON entry point,
    as xBRL-CSV reports extend, is mapped to the XSD that the taxonomy
    packages list for it, or else named by the EBA's convention.

    Args:
        report: Report to write; every fact needs a concept.
        target: Destination path or writable binary stream.
        typed_domains: Typed dimension qname to the qname of its typed domain
            element, with a prefix the report declares or in Clark notation
            (``{namespace}local``, declared under a new prefix if needed);
            required for each typed dimension used by a fact unless the
            taxonomy packages give it.
        taxonomy_packages: Local taxonomy package ZIPs whose dimension
            schemas give the typed domain (``xbrldt:typedDomainRef``) of each
            typed dimension not in ``typed_domains``, declared with the prefix
            its schema uses.
        limits: Resource limits for reading the taxonomy packages.

    Raises:
        ReportError: If a fact lacks a concept, the entity or reference date
            is missing, a prefix is undeclared or invalid, a qname has an
            invalid local name, a typed domain is unknown, or a value holds
            a character XML cannot represent.

    Warns:
        EntryPointWarning: If the XSD entry point for a JSON one comes from
            the EBA's naming convention rather than the taxonomy packages.

    Examples:
        >>> from dpmxbrl import read_report, write_xbrl_xml
        >>> report = read_report("described.zip", taxonomy_packages=["taxonomy.zip"])
        >>> typ = "{http://www.eba.europa.eu/xbrl/crr/dict/typ}qCC"
        >>> write_xbrl_xml(
        ...     report, "described.xbrl", typed_domains={"eba_dim:qINC": typ}
        ... )
        >>> len(read_report("described.xbrl").facts)
        6
    """
    with ExitStack() as stack:
        taxonomy = None
        if taxonomy_packages:
            taxonomy = TaxonomyPackages(taxonomy_packages, limits=limits)
            stack.callback(taxonomy.close)
        lines = _xml_lines(report, dict(typed_domains or {}), taxonomy)
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


class EntryPointWarning(UserWarning):
    """``write_xbrl_xml`` named an XSD entry point it could not confirm."""


def _schema_entry_point(entry_point: str, taxonomy: TaxonomyPackages | None) -> str:
    """Return the XSD entry point for a ``schemaRef``.

    An xBRL-CSV report extends the module's JSON entry point; XML references
    its XSD. The taxonomy packages' entry points confirm the XSD; without
    them, or when they do not list it, the EBA's naming (``corep_of.json``
    beside ``corep_of.xsd``) gives it with an :class:`EntryPointWarning`.

    Returns:
        str: The XSD URL, or ``entry_point`` when it is not a JSON URL.
    """
    stem, extension = posixpath.splitext(entry_point)
    if extension.casefold() != ".json":
        return entry_point
    if taxonomy is not None:
        for point in sorted(taxonomy.entry_points):
            if point.casefold().endswith(".xsd") and module_json_url(point) == (
                entry_point
            ):
                return point
    schema = f"{stem}.xsd"
    warnings.warn(
        f"the schemaRef {schema} is the JSON entry point {entry_point} with .xsd, "
        "as the EBA names modules; "
        + (
            "the taxonomy packages do not list it"
            if taxonomy is not None
            else "taxonomy packages can confirm it"
        ),
        EntryPointWarning,
        stacklevel=4,
    )
    return schema


def _xml_lines(
    report: Report, given: dict[str, str], taxonomy: TaxonomyPackages | None
) -> list[str]:
    """Return the lines of the XML instance.

    Returns:
        list[str]: The instance, one element per line.

    Raises:
        ReportError: As ``write_xbrl_xml`` documents.
    """
    scheme, entity, reference_date = (
        report.entity_scheme,
        report.entity_id,
        report.reference_date,
    )
    if not entity or not scheme:
        raise ReportError("XBRL-XML output requires an entity scheme and identifier")
    if reference_date is None:
        raise ReportError("XBRL-XML output requires a reference date")
    namespaces = _Namespaces(report.namespaces)
    domains: dict[str, str] = {}

    def resolve_domain(dimension: str, where: str) -> str:
        """Prefix the typed domain of a dimension a fact uses, once.

        Returns:
            str: The domain element's prefixed qname.

        Raises:
            ReportError: If no domain is given, or it is not a valid qname.
        """
        if dimension in domains:
            return domains[dimension]
        preferred = "typ"
        if dimension in given:
            element = given[dimension]
        else:
            found = None
            if taxonomy is not None:
                prefix, _, local = dimension.partition(":")
                uri = namespaces.declared.get(prefix)
                found = taxonomy.typed_domain(f"{{{uri}}}{local}") if uri else None
            if found is None:
                raise ReportError(
                    f"{where}: no typed domain element given for typed "
                    f"dimension {dimension}"
                    + ("" if taxonomy else "; taxonomy packages can give it")
                )
            element, preferred = found[0], found[1] or preferred
        if element.startswith("{"):
            # Clark notation, {namespace}local: declare the namespace.
            uri, closed, local = element[1:].partition("}")
            if not closed or not uri:
                raise ReportError(
                    f"typed domain of {dimension}: {element!r} needs a namespace"
                )
            element = f"{namespaces.prefix(uri, preferred)}:{local}"
        domains[dimension] = namespaces.check(element, f"typed domain of {dimension}")
        return domains[dimension]

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
    # xBRL-CSV repeats a fact in every table that shows it; XML holds it once.
    written: set[tuple[str, str, str | None, str | None, int | None]] = set()
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
            resolve_domain(dimension, where)
        context = context_id(fact.dimensions, fact.typed_dimensions)
        unit = fact.unit
        if unit is None and fact.decimals is not None:
            # A numeric xBRL-CSV fact without a unit is pure.
            unit = f"{xbrli}:pure"
        identity = (concept, context, unit, fact.value, fact.decimals)
        if identity in written:
            continue
        written.add(identity)
        attributes = [f"contextRef={_attribute(context)}"]
        if unit is not None:
            for measure in re.split(r"[*/]", unit):
                namespaces.check(measure, where)
            unit_id = units.setdefault(unit, f"u{len(units) + 1}")
            attributes.append(f"unitRef={_attribute(unit_id)}")
            if fact.value is not None:
                decimals = "INF" if fact.decimals is None else str(fact.decimals)
                attributes.append(f"decimals={_attribute(decimals)}")
        if fact.value is None:
            attributes.append(f'{xsi}:nil="true"')
            fact_lines.append(f"  <{concept} {' '.join(attributes)}/>")
        else:
            value = _text(fact.value, where)
            fact_lines.append(
                f"  <{concept} {' '.join(attributes)}>{value}</{concept}>"
            )

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    declarations = " ".join(
        f"xmlns:{prefix}={_attribute(uri)}"
        for prefix, uri in sorted(namespaces.declared.items())
    )
    lines.append(f"<{xbrli}:xbrl {declarations}>")
    if report.entry_point:
        schema = _schema_entry_point(report.entry_point, taxonomy)
        lines.append(
            f'  <{link}:schemaRef {xlink}:type="simple" '
            f"{xlink}:href={_attribute(schema)}/>"
        )
    if report.filing_indicators:
        base = contexts[()]
        lines.append(f"  <{find}:fIndicators>")
        for code, filed in report.filing_indicators.items():
            filed_attribute = "" if filed else f' {find}:filed="false"'
            lines.append(
                f"    <{find}:filingIndicator contextRef={_attribute(base)}"
                f"{filed_attribute}>{_text(code)}</{find}:filingIndicator>"
            )
        lines.append(f"  </{find}:fIndicators>")
    for identifier, dimensions, typed in context_dimensions:
        lines.append(f"  <{xbrli}:context id={_attribute(identifier)}>")
        lines.append(f"    <{xbrli}:entity>")
        lines.append(
            f"      <{xbrli}:identifier scheme={_attribute(scheme)}>"
            f"{_text(entity)}</{xbrli}:identifier>"
        )
        lines.append(f"    </{xbrli}:entity>")
        lines.append(
            f"    <{xbrli}:period><{xbrli}:instant>"
            f"{reference_date.isoformat()}</{xbrli}:instant></{xbrli}:period>"
        )
        if dimensions or typed:
            lines.append(f"    <{xbrli}:scenario>")
            lines.extend(
                f"      <{xbrldi}:explicitMember dimension={_attribute(dimension)}>"
                f"{_text(dimensions[dimension])}</{xbrldi}:explicitMember>"
                for dimension in sorted(dimensions)
            )
            for dimension in sorted(typed):
                domain = domains[dimension]
                lines.append(
                    f"      <{xbrldi}:typedMember dimension={_attribute(dimension)}>"
                    f"<{domain}>{_text(typed[dimension])}</{domain}>"
                    f"</{xbrldi}:typedMember>"
                )
            lines.append(f"    </{xbrli}:scenario>")
        lines.append(f"  </{xbrli}:context>")
    for unit, unit_id in units.items():
        lines.append(f"  <{xbrli}:unit id={_attribute(unit_id)}>")
        numerator, separator, denominator = unit.partition("/")
        if separator:
            lines.append(f"    <{xbrli}:divide>")
            for part, measures in (
                ("unitNumerator", numerator),
                ("unitDenominator", denominator),
            ):
                lines.append(f"      <{xbrli}:{part}>")
                lines.extend(
                    f"        <{xbrli}:measure>{_text(measure)}</{xbrli}:measure>"
                    for measure in measures.split("*")
                )
                lines.append(f"      </{xbrli}:{part}>")
            lines.append(f"    </{xbrli}:divide>")
        else:
            lines.extend(
                f"    <{xbrli}:measure>{_text(measure)}</{xbrli}:measure>"
                for measure in unit.split("*")
            )
        lines.append(f"  </{xbrli}:unit>")
    lines.extend(fact_lines)
    lines.append(f"</{xbrli}:xbrl>")
    # Declare only the prefixes the instance uses (filing rule 3.4).
    used = {xbrli, link, xlink}
    for line in lines[2:]:
        used.update(_PREFIX_USE.findall(line))
    lines[1] = (
        f"<{xbrli}:xbrl "
        + " ".join(
            f"xmlns:{prefix}={_attribute(uri)}"
            for prefix, uri in sorted(namespaces.declared.items())
            if prefix in used
        )
        + ">"
    )
    return lines
