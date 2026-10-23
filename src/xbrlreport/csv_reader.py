"""Read EBA xBRL-CSV report packages into the neutral fact model.

Tables are read in the EBA ``datapoint``/``factValue`` convention unless the
report's OIM metadata (``report.json`` and its ``extends`` chain) can be
resolved offline, in which case the supported xBRL-CSV subset also provides
concepts, dimensions, units and decimals.
"""

from __future__ import annotations

import csv
import io
import os
import posixpath
import re
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from ._package import (
    DAMAGED_ENTRY_ERRORS,
    DamagedEntryError,
    Package,
    open_directory_package,
    open_zip_package,
)
from ._taxonomy import TaxonomyPackages
from ._util import WarningLog, load_json_object
from .filing import (
    DECIMALS_SUFFIX,
    EMPTY_VALUE,
    KEY_SPACES,
    NIL_VALUE,
    SPACES,
    SPECIAL_KEY_VALUE,
    SPECIAL_VALUE,
    FilingLog,
    check_entry_point,
    check_file_name,
    check_subject,
)
from .model import Fact, Limits, Report, ReportError

XBRL_CSV_DOCUMENT_TYPE = "https://xbrl.org/2021/xbrl-csv"
REPORT_PACKAGE_DOCUMENT_TYPES = frozenset(
    {
        "https://xbrl.org/report-package/2023",
        "https://xbrl.org/report-package/2023/xbrl-csv",
    }
)
_DRAFT_DOCUMENT_TYPE = re.compile(
    r"^https?://xbrl\.org/(?:PWD|CR|PR)/20(?:19|20|21)-\d{2}-\d{2}/xbrl-csv$"
)
_REPORT_JSON = re.compile(r"^(?:[^/]+/)?reports/[^/]+\.json$")
_NCNAME = re.compile(r"^[A-Za-z_][\w.\-]*$")
_IGNORED_CORE_DIMENSIONS = frozenset({"period", "entity", "language", "noteId"})
# The EBA's JSON entry points bind these prefixes for entityID (filing rule
# 3.6); they apply when the entry point cannot be read offline.
_ENTITY_SCHEMES = {
    "lei": "http://standards.iso.org/iso/17442",
    "rs": "https://eurofiling.info/eu/rs",
}
_PLAIN_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DECIMALS_SUFFIX = re.compile(r"[-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?d(?:[-+]?[0-9]+|INF)")
"""A value with the xBRL-CSV decimals suffix, such as ``78920030d-4``."""
_TABLE_SUFFIX = re.compile(r"(\.[a-z])+$", re.IGNORECASE)
"""Letter suffixes of a table code that its filing indicator omits."""

MetadataResolver = Callable[[str], bytes | None]
_Ref = tuple[str, str]


@dataclass(slots=True)
class _Metadata:
    namespaces: dict[str, str] = field(default_factory=dict)
    table_templates: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    dimensions: dict[str, Any] = field(default_factory=dict)
    decimals: Any = None
    parameter_url: str | None = None
    unresolved: list[str] = field(default_factory=list)
    loaded: set[_Ref] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _FactColumn:
    index: int
    name: str
    dimensions: Mapping[str, Any]
    decimals: Any
    groups: tuple[tuple[int, Mapping[str, Any]], ...]
    datapoint_index: int | None


def read_xbrl_csv(
    source: str | os.PathLike[str] | bytes,
    *,
    name: str | None = None,
    metadata_resolver: MetadataResolver | None = None,
    taxonomy_packages: Sequence[str | Path] = (),
    limits: Limits = Limits(),
) -> Report:
    """Read an xBRL-CSV report package from a ZIP or a directory.

    Args:
        source: ZIP bytes, a ZIP path, a package directory, or ``report.json``.
        name: Label used in messages instead of the source path.
        metadata_resolver: Returns the bytes for an absolute ``extends`` URL,
            or ``None`` when unknown. It is consulted before taxonomy packages.
        taxonomy_packages: Local taxonomy package ZIPs whose
            ``META-INF/catalog.xml`` rewrites resolve ``extends`` URLs.
        limits: Resource limits for untrusted input.

    Returns:
        Report: Report with ``format == "xbrl-csv"``.

    Raises:
        ReportError: If the package is invalid, unsafe or over a limit.
    """
    package, report_json = _open_package(source, name=name, limits=limits)
    with package:
        taxonomy = (
            TaxonomyPackages(taxonomy_packages, limits=limits)
            if taxonomy_packages
            else None
        )
        try:
            return _CsvReportReader(
                package,
                report_json,
                resolver=metadata_resolver,
                taxonomy=taxonomy,
                limits=limits,
            ).read()
        finally:
            if taxonomy is not None:
                taxonomy.close()


def _open_package(
    source: str | os.PathLike[str] | bytes, *, name: str | None, limits: Limits
) -> tuple[Package, str]:
    if isinstance(source, bytes):
        package = open_zip_package(source, label=name or "<bytes>", limits=limits)
        allow_bare = False
    else:
        path = Path(source).expanduser()
        if path.is_dir():
            package = open_directory_package(path, limits=limits)
            allow_bare = True
        elif path.is_file() and path.suffix.casefold() == ".json":
            package = open_directory_package(path.parent, limits=limits)
            if path.name not in package:
                package.close()
                raise ReportError(f"{path}: report metadata not found")
            return package, path.name
        elif path.is_file() and zipfile.is_zipfile(path):
            package = open_zip_package(path, label=name or str(path), limits=limits)
            allow_bare = False
        elif path.exists():
            raise ReportError(f"{path}: not an xBRL-CSV report package")
        else:
            raise ReportError(f"{path}: no such file or directory")
    if name is not None:
        package.label = name
    try:
        return package, _locate_report_json(package, allow_bare=allow_bare)
    except BaseException:
        package.close()
        raise


def _locate_report_json(package: Package, *, allow_bare: bool) -> str:
    candidates = [name for name in package.names if _REPORT_JSON.match(name)]
    if not candidates and allow_bare and "report.json" in package:
        candidates = ["report.json"]
    if not candidates:
        raise ReportError(
            f"{package.label}: no reports/report.json found in the report package"
        )
    if len(candidates) > 1:
        raise ReportError(
            f"{package.label}: expected exactly one report JSON, found "
            + ", ".join(sorted(candidates))
        )
    return candidates[0]


def _parse_bool(value: str) -> bool | None:
    lowered = value.strip().casefold()
    if lowered in {"true", "1"}:
        return True
    if lowered in {"false", "0"}:
        return False
    return None


def _parse_decimals(value: str) -> int | None:
    text = value.strip()
    if text in {"#none", "INF"}:
        return None
    return int(text)


class _CsvReportReader:
    def __init__(
        self,
        package: Package,
        report_json: str,
        *,
        resolver: MetadataResolver | None,
        taxonomy: TaxonomyPackages | None,
        limits: Limits,
    ) -> None:
        self._package = package
        self._report_json = report_json
        self._reports_dir = posixpath.dirname(report_json)
        if self._reports_dir == "reports" or self._reports_dir.endswith("/reports"):
            self._root_prefix = self._reports_dir[: -len("reports")]
        else:
            self._root_prefix = self._reports_dir + "/" if self._reports_dir else ""
        self._resolver = resolver
        self._taxonomy = taxonomy
        self._limits = limits
        self._warnings = WarningLog()
        self._filing = FilingLog()
        self._facts: list[Fact] = []
        self._seen: dict[tuple[Any, ...], str | None] = {}
        self._namespaces: dict[str, str] = {}
        self._parameters: dict[str, str] = {}
        self._negative: set[str] = set()

    def _display(self, name: str) -> str:
        return name.removeprefix(self._root_prefix)

    def _local(self, url: str) -> str | None:
        if urlsplit(url).scheme or url.startswith("/"):
            return None
        path = posixpath.normpath(posixpath.join(self._reports_dir, url))
        return None if path == ".." or path.startswith("../") else path

    def read(self) -> Report:
        self._check_report_package()
        label = self._display(self._report_json)
        document = load_json_object(self._package.read(self._report_json), label)
        info = document.get("documentInfo")
        if not isinstance(info, dict):
            raise ReportError(f"{label}: missing 'documentInfo' object")
        self._check_document_type(info.get("documentType"), label, required=True)
        extends = info.get("extends", [])
        if not isinstance(extends, list) or not all(
            isinstance(item, str) for item in extends
        ):
            raise ReportError(f"{label}: 'documentInfo.extends' must list URLs")
        entry_point = extends[0] if extends else None
        check_entry_point(extends, self._filing, where=label, xml=False)
        if "taxonomy" in info:
            self._filing.add(
                "1.5",
                "multipleTaxonomyRefs",
                "error",
                "report.json must not populate documentInfo.taxonomy; the entry "
                "point in documentInfo.extends names the taxonomy.",
                label,
            )

        metadata = _Metadata()
        root_ref: _Ref = ("pkg", self._report_json)
        metadata.loaded.add(root_ref)
        self._collect(document, root_ref, label, 0, frozenset({root_ref}), metadata)
        if metadata.unresolved:
            shown = ", ".join(metadata.unresolved[:3])
            more = len(metadata.unresolved) - 3
            self._warnings.add(
                f"{label}: {len(metadata.unresolved)} extended metadata document"
                f"{'' if len(metadata.unresolved) == 1 else 's'} could not be "
                f"resolved offline ({shown}{f', +{more} more' if more > 0 else ''}); "
                "tables without resolved metadata use the EBA "
                "datapoint/factValue convention"
            )
        self._namespaces = metadata.namespaces

        parameter_lines = self._read_parameters(metadata, label)
        entity_scheme, entity_id = self._entity()
        reference_date = self._reference_date(parameter_lines, label)
        decimals_parameters = self._decimals_parameters(parameter_lines, label)
        filing_indicators = self._read_filing_indicators()
        self._negative = {
            code.casefold()
            for code, reported in filing_indicators.items()
            if not reported
        }
        header = Report(
            format="xbrl-csv",
            entry_point=entry_point,
            entity_scheme=entity_scheme,
            entity_id=entity_id,
            reference_date=reference_date,
            base_currency=self._parameters.get("baseCurrency") or None,
            parameters=dict(self._parameters),
            decimals_parameters=decimals_parameters,
            filing_indicators=filing_indicators,
            facts=(),
            namespaces=dict(metadata.namespaces),
        )
        check_subject(header, self._filing)
        self._check_names(header)
        self._before_tables(header)
        self._read_tables(metadata)
        return replace(
            header,
            facts=tuple(self._facts),
            warnings=self._warnings.result(),
            filing=self._filing.result(),
        )

    def _check_names(self, header: Report) -> None:
        """Check the package file and root folder names (EBA file naming)."""
        if not self._package.is_archive:
            return
        file_name = posixpath.basename(self._package.label.replace("\\", "/"))
        if not file_name.casefold().endswith(".zip"):
            return
        check_file_name(file_name, header, self._filing)
        root = self._root_prefix.rstrip("/")
        if root != file_name[: -len(".zip")]:
            self._filing.add(
                "File naming",
                "invalidRootFolder",
                "warning",
                "The package's root folder should be named as the file, without .zip.",
                f"{file_name}: {root or '(no root folder)'}",
            )

    def _before_tables(self, header: Report) -> None:
        """Called with the report's metadata before any table is read."""

    # Package and document checks -------------------------------------------

    def _check_report_package(self) -> None:
        name = f"{self._root_prefix}META-INF/reportPackage.json"
        if name not in self._package:
            if self._package.is_archive:
                self._filing.add(
                    "Package",
                    "missingReportPackageJson",
                    "error",
                    "The package must contain META-INF/reportPackage.json.",
                    self._package.label,
                )
            return
        label = self._display(name)
        document = load_json_object(self._package.read(name), label)
        info = document.get("documentInfo")
        document_type = info.get("documentType") if isinstance(info, dict) else None
        if document_type not in REPORT_PACKAGE_DOCUMENT_TYPES:
            raise ReportError(
                f"{label}: unsupported report package documentType "
                f"{document_type!r}; expected "
                + " or ".join(sorted(REPORT_PACKAGE_DOCUMENT_TYPES))
            )

    def _check_document_type(
        self, document_type: object, label: str, *, required: bool
    ) -> None:
        if document_type == XBRL_CSV_DOCUMENT_TYPE:
            return
        if isinstance(document_type, str) and _DRAFT_DOCUMENT_TYPE.match(document_type):
            self._warnings.add(
                f"{label}: documentType {document_type} is a pre-recommendation "
                f"xBRL-CSV draft; read as {XBRL_CSV_DOCUMENT_TYPE}"
            )
            return
        message = (
            f"{label}: unsupported documentType {document_type!r}; expected "
            f"{XBRL_CSV_DOCUMENT_TYPE}"
        )
        if required:
            raise ReportError(message)
        self._warnings.add(message)

    # Metadata ----------------------------------------------------------------

    def _collect(
        self,
        document: dict[str, Any],
        ref: _Ref,
        label: str,
        depth: int,
        stack: frozenset[_Ref],
        metadata: _Metadata,
    ) -> None:
        info = document.get("documentInfo")
        if not isinstance(info, dict):
            raise ReportError(f"{label}: missing 'documentInfo' object")
        extends = info.get("extends", [])
        if not isinstance(extends, list) or not all(
            isinstance(item, str) for item in extends
        ):
            raise ReportError(f"{label}: 'documentInfo.extends' must list URLs")
        for url in extends:
            target = self._resolve_ref(ref, url)
            if target is None:
                metadata.unresolved.append(url)
                continue
            if target in stack:
                self._warnings.add(f"{label}: ignored cyclic extends of {target[1]}")
                continue
            if target in metadata.loaded:
                continue
            if depth + 1 > self._limits.max_extends_depth:
                raise ReportError(
                    f"{label}: extends chain exceeds the maximum depth of "
                    f"{self._limits.max_extends_depth}"
                )
            data = self._fetch(target)
            if data is None:
                metadata.unresolved.append(target[1])
                continue
            child_label = self._display(target[1]) if target[0] == "pkg" else target[1]
            child = load_json_object(data, child_label)
            metadata.loaded.add(target)
            child_info = child.get("documentInfo")
            if isinstance(child_info, dict):
                self._check_document_type(
                    child_info.get("documentType"), child_label, required=False
                )
            self._collect(
                child, target, child_label, depth + 1, stack | {target}, metadata
            )
        self._merge(document, label, metadata)

    def _resolve_ref(self, base: _Ref, url: str) -> _Ref | None:
        if urlsplit(url).scheme:
            return ("url", url)
        if base[0] == "url":
            return ("url", urljoin(base[1], url))
        if url.startswith("/"):
            return None
        path = posixpath.normpath(posixpath.join(posixpath.dirname(base[1]), url))
        return None if path == ".." or path.startswith("../") else ("pkg", path)

    def _fetch(self, ref: _Ref) -> bytes | None:
        kind, location = ref
        if kind == "pkg":
            return self._package.read(location) if location in self._package else None
        data = self._resolver(location) if self._resolver is not None else None
        if data is None and self._taxonomy is not None:
            data = self._taxonomy.resolve(location)
        return data

    def _merge(self, document: dict[str, Any], label: str, metadata: _Metadata) -> None:
        info = document.get("documentInfo", {})
        namespaces = info.get("namespaces", {})
        if not isinstance(namespaces, dict):
            raise ReportError(f"{label}: 'documentInfo.namespaces' must be an object")
        for prefix, uri in namespaces.items():
            if not isinstance(uri, str):
                raise ReportError(f"{label}: namespace {prefix!r} must be a string")
            previous = metadata.namespaces.get(prefix)
            if previous is not None and previous != uri:
                self._warnings.add(
                    f"{label}: prefix {prefix!r} rebinds {previous} to {uri}"
                )
            metadata.namespaces[prefix] = uri
        for key, target in (
            ("tableTemplates", metadata.table_templates),
            ("tables", metadata.tables),
            ("parameters", metadata.parameters),
            ("dimensions", metadata.dimensions),
        ):
            value = document.get(key)
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ReportError(f"{label}: '{key}' must be a JSON object")
            target.update(value)
        if "decimals" in document:
            metadata.decimals = document["decimals"]
        parameter_url = document.get("parameterURL")
        if isinstance(parameter_url, str):
            metadata.parameter_url = parameter_url

    # Parameters and filing indicators ------------------------------------------

    def _csv_rows(self, name: str) -> Iterator[tuple[int, list[str]]]:
        label = self._display(name)
        with self._package.open(name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.reader(text, strict=True)
            previous = 0
            try:
                for row in reader:
                    line = previous + 1
                    previous = reader.line_num
                    if row:
                        yield line, row
            except UnicodeDecodeError as error:
                raise ReportError(
                    f"{label}: not valid UTF-8 after line {previous} ({error.reason})"
                ) from error
            except csv.Error as error:
                raise ReportError(f"{label}:{reader.line_num}: {error}") from error
            except DAMAGED_ENTRY_ERRORS as error:
                raise DamagedEntryError(self._package.label, name, error) from error

    def _read_parameters(self, metadata: _Metadata, label: str) -> dict[str, str]:
        lines: dict[str, str] = {}
        for key, value in metadata.parameters.items():
            if value is None or isinstance(value, dict | list):
                raise ReportError(f"{label}: parameter {key!r} must be a scalar")
            self._parameters[key] = str(value)
            lines[key] = label
        url = metadata.parameter_url or "parameters.csv"
        name = self._local(url)
        if name is None or name not in self._package:
            self._filing.add(
                "Package",
                "missingParametersFile",
                "error",
                f"The package must contain the parameters file {url}.",
                label,
            )
            return lines
        display = self._display(name)
        rows = self._csv_rows(name)
        header = next(rows, None)
        if header is None or header[1] != ["name", "value"]:
            found = ",".join(header[1]) if header else "nothing"
            raise ReportError(
                f"{display}:1: parameters header must be 'name,value', found {found!r}"
            )
        for line, row in rows:
            if len(row) != 2:
                raise ReportError(
                    f"{display}:{line}: expected 2 cells, found {len(row)}"
                )
            key, value = row
            if not key:
                raise ReportError(f"{display}:{line}: empty parameter name")
            previous = self._parameters.get(key)
            if previous is not None and previous != value:
                self._warnings.add(
                    f"{display}:{line}: parameter {key!r} overrides {previous!r} "
                    f"with {value!r}"
                )
            self._parameters[key] = value
            lines[key] = f"{display}:{line}"
        return lines

    def _entity(self) -> tuple[str | None, str | None]:
        value = self._parameters.get("entityID")
        if not value:
            return None, None
        prefix, separator, identifier = value.partition(":")
        if not separator:
            return None, value
        scheme = self._namespaces.get(prefix) or _ENTITY_SCHEMES.get(prefix, prefix)
        return scheme, identifier

    def _reference_date(self, lines: Mapping[str, str], label: str) -> date | None:
        value = self._parameters.get("refPeriod")
        if not value:
            self._filing.add(
                "Package",
                "missingReferencePeriod",
                "error",
                "parameters.csv must give the reference date as refPeriod.",
                lines.get("refPeriod", label),
            )
            return None
        if not _PLAIN_DATE.fullmatch(value):
            self._filing.add(
                "2.10",
                "periodWithTimeContent" if "T" in value else "periodWithTimezone",
                "error",
                "refPeriod must be a plain date (YYYY-MM-DD) without a time or "
                "time zone.",
                f"{lines.get('refPeriod', label)}: {value}",
            )
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as error:
            raise ReportError(
                f"{lines.get('refPeriod', label)}: refPeriod {value!r} is not a "
                "YYYY-MM-DD date"
            ) from error

    def _decimals_parameters(
        self, lines: Mapping[str, str], label: str
    ) -> dict[str, int | None]:
        result: dict[str, int | None] = {}
        for key, value in self._parameters.items():
            if not key.startswith("decimals"):
                continue
            try:
                result[key] = _parse_decimals(value)
            except ValueError as error:
                raise ReportError(
                    f"{lines.get(key, label)}: parameter {key} value {value!r} is "
                    "not an integer, INF or #none"
                ) from error
        return result

    def _filing_indicator_name(self) -> str | None:
        wanted = posixpath.join(self._reports_dir, "filingindicators.csv").casefold()
        for name in self._package.names:
            if name.casefold() == wanted:
                return name
        return None

    def _read_filing_indicators(self) -> dict[str, bool]:
        name = self._filing_indicator_name()
        if name is None:
            self._filing.add(
                "1.6",
                "missingFilingIndicators",
                "error",
                "The package must contain reports/FilingIndicators.csv with a "
                "filing indicator for each template of the module.",
                self._package.label,
            )
            return {}
        display = self._display(name)
        rows = self._csv_rows(name)
        header = next(rows, None)
        if header is None or header[1] != ["templateID", "reported"]:
            found = ",".join(header[1]) if header else "nothing"
            raise ReportError(
                f"{display}:1: filing indicator header must be "
                f"'templateID,reported', found {found!r}"
            )
        result: dict[str, bool] = {}
        for line, row in rows:
            if len(row) != 2:
                raise ReportError(
                    f"{display}:{line}: expected 2 cells, found {len(row)}"
                )
            template, raw = row
            reported = _parse_bool(raw)
            if not template or reported is None:
                raise ReportError(
                    f"{display}:{line}: invalid filing indicator "
                    f"{template!r},{raw!r}; reported must be true, false, 1 or 0"
                )
            if template in result:
                self._filing.add(
                    "1.6.1",
                    "duplicateFilingIndicator",
                    "error",
                    "Each template must have exactly one filing indicator.",
                    f"{display}:{line}: {template}",
                )
            result[template] = reported
        return result

    # Tables --------------------------------------------------------------------

    def _read_tables(self, metadata: _Metadata) -> None:
        mapped: dict[str, tuple[str, Mapping[str, Any]]] = {}
        for table_name, definition in metadata.tables.items():
            if not isinstance(definition, dict):
                continue
            url = definition.get("url")
            path = self._local(url) if isinstance(url, str) else None
            if path is None:
                continue
            template = definition.get("template", table_name)
            parameters = definition.get("parameters", {})
            mapped[path] = (
                str(template),
                parameters if isinstance(parameters, dict) else {},
            )

        excluded = {self._filing_indicator_name()}
        excluded.add(self._local(metadata.parameter_url or "parameters.csv"))
        prefix = f"{self._reports_dir}/" if self._reports_dir else ""
        for name in self._package.names:
            if (
                not name.startswith(prefix)
                or not name.casefold().endswith(".csv")
                or name in excluded
            ):
                continue
            template_id, table_parameters = mapped.get(
                name, (posixpath.splitext(posixpath.basename(name))[0], {})
            )
            if self._not_reported(template_id):
                self._filing.add(
                    "xBRL-CSV 6",
                    "tableForNegativeFilingIndicator",
                    "error",
                    "The package must not contain the table file of a template "
                    "whose filing indicator is false.",
                    self._display(name),
                )
            template = metadata.table_templates.get(template_id)
            if isinstance(template, dict) and isinstance(template.get("columns"), dict):
                self._read_metadata_table(
                    name, template_id, template, table_parameters, metadata
                )
            else:
                self._read_convention_table(name, template_id)

    def _not_reported(self, template_id: str) -> bool:
        """Check whether a table's template has a negative filing indicator.

        Returns:
            bool: Whether the template is indicated as not reported.
        """
        return _TABLE_SUFFIX.sub("", template_id).casefold() in self._negative

    def _header(self, rows: Iterator[tuple[int, list[str]]], display: str) -> list[str]:
        first = next(rows, None)
        if first is None:
            raise ReportError(f"{display}:1: table file has no header row")
        header = first[1]
        if any(not column for column in header):
            raise ReportError(f"{display}:1: table header has an empty column name")
        duplicates = sorted({column for column in header if header.count(column) > 1})
        if duplicates:
            raise ReportError(
                f"{display}:1: duplicate table columns {', '.join(duplicates)}"
            )
        return header

    def _rows(
        self, rows: Iterator[tuple[int, list[str]]], width: int, display: str
    ) -> Iterator[tuple[int, list[str]]]:
        for line, row in rows:
            if len(row) != width:
                raise ReportError(
                    f"{display}:{line}: expected {width} cells, found {len(row)}"
                )
            yield line, row

    def _fact_value(
        self, cell: str, display: str, location: str
    ) -> tuple[bool, str | None]:
        if not cell:
            return False, None
        if cell.startswith("##"):
            return True, cell[1:]
        if not cell.startswith("#"):
            if cell != cell.strip():
                self._filing.add(*SPACES, location)
            elif "d" in cell and _DECIMALS_SUFFIX.fullmatch(cell):
                self._filing.add(*DECIMALS_SUFFIX, location)
            return True, cell
        if cell == "#nil":
            self._filing.add(*NIL_VALUE, location)
            return True, None
        if cell == "#empty":
            self._filing.add(*EMPTY_VALUE, location)
            return False, None
        self._filing.add(*SPECIAL_VALUE, location)
        return cell != "#none", None if cell == "#none" else cell

    def _check_keys(self, keys: Mapping[str, str], location: str) -> None:
        """Check key column values for special values and spaces."""
        for value in keys.values():
            if value.startswith("#") and not value.startswith("##"):
                self._filing.add(*SPECIAL_KEY_VALUE, location)
            elif value != value.strip():
                self._filing.add(*KEY_SPACES, location)

    def _emit(self, fact: Fact, key: tuple[Any, ...], display: str) -> None:
        if key in self._seen:
            if self._seen[key] == fact.value:
                self._warnings.count(
                    f"{display}: duplicate facts ignored", fact.location
                )
                return
            self._warnings.count(
                f"{display}: conflicting duplicate facts kept", fact.location
            )
        else:
            self._seen[key] = fact.value
        if len(self._facts) >= self._limits.max_facts:
            raise ReportError(
                f"{fact.location}: report exceeds the limit of "
                f"{self._limits.max_facts} facts"
            )
        self._facts.append(fact)

    def _read_convention_table(self, name: str, template_id: str) -> None:
        display = self._display(name)
        rows = self._csv_rows(name)
        header = self._header(rows, display)
        if "datapoint" not in header or "factValue" not in header:
            raise ReportError(
                f"{display}:1: table header must contain 'datapoint' and "
                f"'factValue' columns, found {','.join(header)!r}"
            )
        datapoint_index = header.index("datapoint")
        value_index = header.index("factValue")
        key_columns = [
            (index, column)
            for index, column in enumerate(header)
            if index not in {datapoint_index, value_index}
        ]
        for line, row in self._rows(rows, len(header), display):
            location = f"{display}:{line}"
            keep, value = self._fact_value(row[value_index], display, location)
            if not keep:
                continue
            datapoint = row[datapoint_index] or None
            if datapoint is None:
                self._warnings.count(f"{display}: facts without a datapoint", location)
            keys = {column: row[index] for index, column in key_columns}
            self._check_keys(keys, location)
            self._emit(
                Fact(
                    value=value,
                    datapoint=datapoint,
                    template=template_id,
                    keys=keys,
                    location=location,
                ),
                (template_id, "factValue", datapoint, tuple(keys.items())),
                display,
            )

    def _fact_columns(
        self,
        header: list[str],
        template: Mapping[str, Any],
        metadata: _Metadata,
        display: str,
    ) -> tuple[list[_FactColumn], list[tuple[int, str]]]:
        columns: Mapping[str, Any] = template["columns"]
        template_dimensions = template.get("dimensions") or {}
        if not isinstance(template_dimensions, dict):
            raise ReportError(f"{display}: template 'dimensions' must be an object")
        groups: dict[str, int] = {}
        fact_names: list[tuple[int, str, Mapping[str, Any]]] = []
        keys: list[tuple[int, str]] = []
        for index, column in enumerate(header):
            definition = columns.get(column)
            if column == "datapoint" and not isinstance(definition, dict):
                continue
            if not isinstance(definition, dict):
                self._warnings.add(
                    f"{display}: column {column!r} is not defined by the table "
                    "template; kept as a key column"
                )
                keys.append((index, column))
            elif "propertyGroups" in definition:
                groups[column] = index
            elif "dimensions" in definition or "propertiesFrom" in definition:
                fact_names.append((index, column, definition))
            elif column != "datapoint":
                keys.append((index, column))
        fact_columns: list[_FactColumn] = []
        for index, column, definition in fact_names:
            column_dimensions = definition.get("dimensions") or {}
            if not isinstance(column_dimensions, dict):
                raise ReportError(
                    f"{display}: column {column!r} 'dimensions' must be an object"
                )
            properties_from = definition.get("propertiesFrom") or []
            group_columns = tuple(
                (groups[source], columns[source]["propertyGroups"])
                for source in properties_from
                if source in groups
                and isinstance(columns[source].get("propertyGroups"), dict)
            )
            decimals = metadata.decimals
            if "decimals" in template:
                decimals = template["decimals"]
            if "decimals" in definition:
                decimals = definition["decimals"]
            datapoint_index = (
                group_columns[0][0]
                if group_columns
                else header.index("datapoint")
                if "datapoint" in header
                else None
            )
            fact_columns.append(
                _FactColumn(
                    index=index,
                    name=column,
                    dimensions={
                        **metadata.dimensions,
                        **template_dimensions,
                        **column_dimensions,
                    },
                    decimals=decimals,
                    groups=group_columns,
                    datapoint_index=datapoint_index,
                )
            )
        return fact_columns, keys

    def _read_metadata_table(
        self,
        name: str,
        template_id: str,
        template: Mapping[str, Any],
        table_parameters: Mapping[str, Any],
        metadata: _Metadata,
    ) -> None:
        display = self._display(name)
        rows = self._csv_rows(name)
        header = self._header(rows, display)
        fact_columns, key_columns = self._fact_columns(
            header, template, metadata, display
        )
        if not fact_columns:
            self._warnings.add(f"{display}: table template defines no fact columns")
        for line, row in self._rows(rows, len(header), display):
            location = f"{display}:{line}"
            cells = dict(zip(header, row, strict=True))
            keys = {column: row[index] for index, column in key_columns}
            self._check_keys(keys, location)
            key_items = tuple(keys.items())
            for column in fact_columns:
                keep, value = self._fact_value(row[column.index], display, location)
                if not keep:
                    continue
                dimensions = dict(column.dimensions)
                decimals = column.decimals
                for group_index, property_groups in column.groups:
                    group_key = row[group_index]
                    if not group_key:
                        continue
                    group = property_groups.get(group_key)
                    if not isinstance(group, dict):
                        self._warnings.count(
                            f"{display}: unknown property group values", location
                        )
                        continue
                    group_dimensions = group.get("dimensions")
                    if isinstance(group_dimensions, dict):
                        dimensions.update(group_dimensions)
                    if "decimals" in group:
                        decimals = group["decimals"]
                fact = self._metadata_fact(
                    value,
                    dimensions,
                    decimals,
                    cells,
                    table_parameters,
                    display=display,
                    location=location,
                    template_id=template_id,
                    keys=keys,
                    datapoint=(
                        row[column.datapoint_index] or None
                        if column.datapoint_index is not None
                        else None
                    ),
                )
                self._emit(
                    fact,
                    (template_id, column.name, fact.datapoint, key_items),
                    display,
                )

    def _resolve(
        self,
        raw: Any,
        cells: Mapping[str, str],
        table_parameters: Mapping[str, Any],
        display: str,
        location: str,
    ) -> str | None:
        if raw is None:
            return None
        if not isinstance(raw, str):
            return str(raw)
        if raw.startswith("$$"):
            return raw[1:]
        if not raw.startswith("$"):
            return raw
        reference = raw[1:].partition("@")[0]
        if reference in cells:
            return cells[reference] or None
        if reference in table_parameters:
            return str(table_parameters[reference])
        if reference in self._parameters:
            return self._parameters[reference]
        self._warnings.count(
            f"{display}: unresolved reference {raw!r} ignored", location
        )
        return None

    def _is_declared_qname(self, value: str) -> bool:
        prefix, separator, local = value.partition(":")
        return bool(separator and prefix in self._namespaces and _NCNAME.match(local))

    def _metadata_fact(
        self,
        value: str | None,
        dimensions: Mapping[str, Any],
        raw_decimals: Any,
        cells: Mapping[str, str],
        table_parameters: Mapping[str, Any],
        *,
        display: str,
        location: str,
        template_id: str,
        keys: Mapping[str, str],
        datapoint: str | None,
    ) -> Fact:
        concept: str | None = None
        unit: str | None = None
        explicit: dict[str, str] = {}
        typed: dict[str, str] = {}
        for dimension, raw in dimensions.items():
            resolved = self._resolve(raw, cells, table_parameters, display, location)
            if resolved is None or resolved == "#none":
                continue
            if dimension == "concept":
                concept = resolved
            elif dimension == "unit":
                unit = resolved
            elif dimension in _IGNORED_CORE_DIMENSIONS:
                continue
            elif ":" in dimension:
                if self._is_declared_qname(resolved):
                    explicit[dimension] = resolved
                else:
                    typed[dimension] = resolved
            else:
                self._warnings.count(
                    f"{display}: unsupported core dimension {dimension!r} ignored",
                    location,
                )
        decimals: int | None = None
        if raw_decimals is not None and not isinstance(raw_decimals, bool):
            resolved_decimals = self._resolve(
                raw_decimals, cells, table_parameters, display, location
            )
            if resolved_decimals is not None:
                try:
                    decimals = _parse_decimals(resolved_decimals)
                except ValueError:
                    self._warnings.count(
                        f"{display}: invalid decimals {resolved_decimals!r} ignored",
                        location,
                    )
        return Fact(
            value=value,
            concept=concept,
            datapoint=datapoint,
            template=template_id,
            dimensions=explicit,
            typed_dimensions=typed,
            keys=keys,
            unit=unit,
            decimals=decimals,
            location=location,
        )
