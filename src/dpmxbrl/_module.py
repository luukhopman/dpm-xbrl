"""xBRL-CSV metadata of a taxonomy module, read from local taxonomy packages.

An EBA module's JSON entry point (``corep_of.json``) extends one JSON
document per table, whose table template lists each data point as a
property group: a concept, dimension members, a unit and decimals, with
``$column`` references for the dimensions that key columns give. Inverting
those groups places an XML fact, which carries a concept and dimensions,
in the table rows of an xBRL-CSV report.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit

from ._taxonomy import TaxonomyPackages
from ._util import load_json_object
from .model import Fact, Limits, ReportError

_IGNORED_DIMENSIONS = frozenset({"period", "entity", "language", "noteId"})
_ENUMERATION_TYPES = frozenset({"e", "es"})
"""EBA data point types whose values are member qnames."""
PURE = "{http://www.xbrl.org/2003/instance}pure"

Member = tuple[bool, str]
"""A dimension value: ``(True, clark member)`` or ``(False, typed value)``."""


def module_json_url(entry_point: str) -> str:
    """Return the JSON entry point of a module named by its XSD or JSON URL.

    Returns:
        str: The URL with a ``.json`` suffix, as the EBA publishes both.
    """
    extension = posixpath.splitext(urlsplit(entry_point).path)[1]
    if extension.casefold() == ".xsd" and entry_point.endswith(extension):
        return entry_point[: -len(extension)] + ".json"
    return entry_point


@dataclass(slots=True)
class ModuleMetadata:
    """A module's merged xBRL-CSV metadata.

    Attributes:
        url: Absolute URL of the JSON entry point.
        namespaces: Prefix to namespace URI, over the whole ``extends`` chain.
        table_templates: Table template id to its definition.
        tables: Table name to its definition (``template``, ``url``).
        parameters: Parameters the metadata defines.
        dimensions: Report-level dimensions.
        decimals: Report-level decimals.
        valid_from: The module's first reference date, if documented.
        valid_to: The module's last reference date, if documented.
    """

    url: str
    namespaces: dict[str, str] = field(default_factory=dict)
    table_templates: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    dimensions: dict[str, Any] = field(default_factory=dict)
    decimals: Any = None
    valid_from: date | None = None
    valid_to: date | None = None
    _clark: dict[str, str | None] = field(default_factory=dict, repr=False)

    def clark(self, qname: str) -> str | None:
        """Return a prefixed qname of the metadata in Clark notation.

        Returns:
            str | None: ``{uri}local``, or ``None`` if the prefix is unknown.
        """
        try:
            return self._clark[qname]
        except KeyError:
            prefix, separator, local = qname.partition(":")
            uri = self.namespaces.get(prefix) if separator else None
            result = self._clark[qname] = f"{{{uri}}}{local}" if uri and local else None
            return result

    def table_files(self) -> dict[str, str]:
        """Return each table's file name, from its ``url``, to its template.

        Returns:
            dict[str, str]: CSV file name, such as ``c_01.00.csv``, to the
            template id.
        """
        files: dict[str, str] = {}
        for name, table in self.tables.items():
            if isinstance(table, dict) and isinstance(table.get("url"), str):
                files[table["url"]] = str(table.get("template", name))
        return files


def _date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def load_module(
    taxonomy: TaxonomyPackages, entry_point: str, *, limits: Limits
) -> ModuleMetadata:
    """Read a module's JSON entry point and every document it extends.

    Relative ``extends`` resolve against the extending document; every URL
    is looked up in the taxonomy packages. Documents that cannot be found
    are skipped, as the reader does.

    Returns:
        ModuleMetadata: The merged metadata.

    Raises:
        ReportError: If the entry point is not in the packages, or a
            document is not valid JSON.
    """
    url = module_json_url(entry_point)
    data = taxonomy.resolve(url)
    if data is None:
        raise ReportError(
            f"{entry_point}: the taxonomy packages hold no xBRL-CSV entry point {url}"
        )
    module = ModuleMetadata(url=url)
    document = load_json_object(data, url)
    info = document.get("documentInfo")
    if isinstance(info, dict):
        documentation = info.get("eba:documentation")
        if isinstance(documentation, dict):
            module.valid_from = _date(documentation.get("FromReferenceDate"))
            module.valid_to = _date(documentation.get("toReferenceDate"))
    _collect(taxonomy, document, url, 0, {url}, module, limits)
    return module


def _collect(
    taxonomy: TaxonomyPackages,
    document: dict[str, Any],
    url: str,
    depth: int,
    loaded: set[str],
    module: ModuleMetadata,
    limits: Limits,
) -> None:
    info = document.get("documentInfo")
    extends = info.get("extends", []) if isinstance(info, dict) else []
    if not isinstance(extends, list):
        raise ReportError(f"{url}: 'documentInfo.extends' must list URLs")
    for reference in extends:
        if not isinstance(reference, str):
            raise ReportError(f"{url}: 'documentInfo.extends' must list URLs")
        target = urljoin(url, reference)
        if target in loaded:
            continue
        if depth + 1 > limits.max_extends_depth:
            raise ReportError(
                f"{url}: extends chain exceeds the maximum depth of "
                f"{limits.max_extends_depth}"
            )
        loaded.add(target)
        data = taxonomy.resolve(target)
        if data is None:
            continue
        child = load_json_object(data, target)
        _collect(taxonomy, child, target, depth + 1, loaded, module, limits)
    _merge(document, url, module)


def _merge(document: dict[str, Any], url: str, module: ModuleMetadata) -> None:
    info = document.get("documentInfo")
    namespaces = info.get("namespaces", {}) if isinstance(info, dict) else {}
    if not isinstance(namespaces, dict):
        raise ReportError(f"{url}: 'documentInfo.namespaces' must be an object")
    module.namespaces.update(
        (prefix, uri) for prefix, uri in namespaces.items() if isinstance(uri, str)
    )
    for key, target in (
        ("tableTemplates", module.table_templates),
        ("tables", module.tables),
        ("parameters", module.parameters),
        ("dimensions", module.dimensions),
    ):
        value = document.get(key)
        if isinstance(value, dict):
            target.update(value)
    if "decimals" in document:
        module.decimals = document["decimals"]


@dataclass(frozen=True, slots=True)
class Placement:
    """Where facts with one concept and set of dimensions go in xBRL-CSV.

    Attributes:
        table: The table's file stem, such as ``c_07.00.a``.
        datapoint: The property group key, such as ``dp3291879``.
        keys: For each key column of the table, in header order, the Clark
            dimension it gives, ``unit``, or ``None`` when the data point does
            not use the column.
        unit: ``("parameter", name)``, ``("fixed", clark measure)`` or ``None``
            when the fact has no unit or ``xbrli:pure``; a unit from a key
            column is listed in ``keys``.
        decimals: Name of the decimals parameter, or ``None``.
        enumeration: Whether values are member qnames.
    """

    table: str
    datapoint: str
    keys: tuple[str | None, ...]
    unit: tuple[str, str] | None
    decimals: str | None
    enumeration: bool


@dataclass(frozen=True, slots=True)
class Table:
    """One table file of the module.

    Attributes:
        file: The CSV file name from the table's ``url``.
        header: Column names: the property group, fact and key columns.
    """

    file: str
    header: tuple[str, ...]


class PlacementIndex:
    """Find a fact's table rows from its concept and dimensions."""

    def __init__(self, module: ModuleMetadata) -> None:
        """Invert the property groups of every table of the module."""
        self.module = module
        self.tables: dict[str, Table] = {}
        # Variable (key column) dimensions -> (concept, fixed members) -> places.
        self._index: dict[
            frozenset[str],
            dict[tuple[str, frozenset[tuple[str, Member]]], list[Placement]],
        ] = {}
        self._terms: dict[tuple[str, object], tuple[str, Any, Any]] = {}
        self._by_names: dict[frozenset[str], list[frozenset[str]]] = {}
        for table in module.tables.values():
            if isinstance(table, dict):
                self._add_table(table)

    def _add_table(self, table: Mapping[str, Any]) -> None:
        url = table.get("url")
        template = self.module.table_templates.get(table.get("template"))
        if not isinstance(url, str) or not isinstance(template, dict):
            return
        columns = template.get("columns")
        if not isinstance(columns, dict):
            return
        groups = {
            name: definition["propertyGroups"]
            for name, definition in columns.items()
            if isinstance(definition, dict)
            and isinstance(definition.get("propertyGroups"), dict)
        }
        fact_columns = [
            (name, definition)
            for name, definition in columns.items()
            if isinstance(definition, dict)
            and name not in groups
            and ("dimensions" in definition or "propertiesFrom" in definition)
        ]
        # Only the EBA layout: one property group column, one fact column.
        if len(groups) != 1 or len(fact_columns) != 1:
            return
        (group_column, property_groups), (fact_column, definition) = (
            next(iter(groups.items())),
            fact_columns[0],
        )
        if definition.get("propertiesFrom") != [group_column]:
            return
        stem = posixpath.splitext(posixpath.basename(url))[0]
        key_columns = [
            name for name in columns if name not in {group_column, fact_column}
        ]
        key_columns.sort(key=lambda name: _header_code(columns[name]))
        self.tables[stem] = Table(url, (group_column, fact_column, *key_columns))
        base = {
            **self.module.dimensions,
            **(template.get("dimensions") or {}),
            **(definition.get("dimensions") or {}),
        }
        decimals = self.module.decimals
        decimals = template.get("decimals", decimals)
        decimals = definition.get("decimals", decimals)
        for datapoint, group in property_groups.items():
            if isinstance(group, dict):
                self._add_group(stem, datapoint, group, base, decimals, key_columns)

    def _term(self, dimension: str, raw: object) -> tuple[str, Any, Any]:
        """Classify one dimension of a property group, cached.

        Returns:
            tuple: ``(kind, a, b)``: ``skip``, ``invalid``, ``concept``
            (clark), ``unit`` (``None`` for pure, a ``$`` column or parameter
            name, or a clark measure), ``key`` (clark dimension, column) or
            ``member`` (clark dimension, member).
        """
        cached = self._terms.get((dimension, raw))
        if cached is not None:
            return cached
        term: tuple[str, Any, Any]
        if not isinstance(raw, str) or dimension in _IGNORED_DIMENSIONS:
            term = ("skip", None, None)
        else:
            reference = None
            if raw.startswith("$$"):
                raw = raw[1:]
            elif raw.startswith("$"):
                reference = raw[1:].partition("@")[0]
            if dimension == "concept":
                concept = None if reference else self.module.clark(raw)
                term = ("concept", concept, None) if concept else ("invalid", 0, 0)
            elif dimension == "unit":
                measure = None if reference else self.module.clark(raw)
                if reference:
                    term = ("unit", "$", reference)
                elif measure is None:
                    term = ("invalid", None, None)
                else:
                    term = ("unit", None if measure == PURE else measure, None)
            elif (name := self.module.clark(dimension)) is None:
                term = ("invalid", None, None)
            elif reference:
                term = ("key", name, reference)
            elif raw == "#none":
                term = ("skip", None, None)
            else:
                member = self.module.clark(raw)
                term = ("member", name, (True, member) if member else (False, raw))
        self._terms[dimension, raw] = term
        return term

    def _add_group(
        self,
        table: str,
        datapoint: str,
        group: Mapping[str, Any],
        base: Mapping[str, Any],
        decimals: Any,
        key_columns: list[str],
    ) -> None:
        dimensions = {**base, **(group.get("dimensions") or {})}
        decimals = group.get("decimals", decimals)
        concept: str | None = None
        unit: tuple[str, str] | None = None
        by_column: dict[str, str] = {}
        fixed: list[tuple[str, Member]] = []
        for dimension, raw in dimensions.items():
            kind, first, second = self._term(dimension, raw)
            if kind == "member":
                fixed.append((first, second))
            elif kind == "concept":
                concept = first
            elif kind == "key":
                if second not in key_columns:
                    return  # A dimension from a parameter: not an EBA pattern.
                by_column[second] = first
            elif kind == "unit":
                if first != "$":
                    unit = None if first is None else ("fixed", first)
                elif second in key_columns:
                    by_column[second] = "unit"
                else:
                    unit = ("parameter", second)
            elif kind == "invalid":
                return
        if concept is None:
            return
        documentation = group.get("eba:documentation")
        kind = documentation.get("type") if isinstance(documentation, dict) else None
        decimals_parameter = (
            decimals[1:]
            if isinstance(decimals, str) and decimals.startswith("$")
            else None
        )
        variable = frozenset(name for name in by_column.values() if name != "unit")
        self._index.setdefault(variable, {}).setdefault(
            (concept, frozenset(fixed)), []
        ).append(
            Placement(
                table=table,
                datapoint=datapoint,
                keys=tuple(by_column.get(column) for column in key_columns),
                unit=unit,
                decimals=decimals_parameter,
                enumeration=kind in _ENUMERATION_TYPES,
            )
        )

    def find(self, concept: str, members: Mapping[str, Member]) -> list[Placement]:
        """Return the table rows a fact belongs in.

        Every key column of a row must be given (EBA xBRL-CSV rule 4), so a
        table's key dimensions must all be among the fact's dimensions.

        Args:
            concept: The fact's concept in Clark notation.
            members: Clark dimension to the fact's member or typed value.

        Returns:
            list[Placement]: Every matching table row; empty if none.
        """
        names = frozenset(members)
        variables = self._by_names.get(names)
        if variables is None:
            variables = self._by_names[names] = [
                variable for variable in self._index if variable <= names
            ]
        found: list[Placement] = []
        for variable in variables:
            fixed = frozenset(
                item for item in members.items() if item[0] not in variable
            )
            found.extend(self._index[variable].get((concept, fixed), ()))
        return found


def _header_code(definition: object) -> str:
    """Sort key putting key columns in the EBA's header order.

    Returns:
        str: The column's documented header code; columns without one last.
    """
    if isinstance(definition, dict):
        documentation = definition.get("eba:documentation")
        if isinstance(documentation, dict):
            code = documentation.get("headerCode")
            if isinstance(code, str):
                return code
    return "￿"


class Namespaces:
    """Translate qnames between a report's prefixes and the module's."""

    def __init__(self, report: Mapping[str, str], module: Mapping[str, str]) -> None:
        """Index both prefix maps."""
        self.report = report
        self.module_prefixes: dict[str, str] = {}
        for prefix, uri in module.items():
            self.module_prefixes.setdefault(uri, prefix)
        self.module = module
        self.extra: dict[str, str] = {}
        self._clark: dict[str, str | None] = {}
        self._rendered: dict[str, str] = {}
        """Prefixes the written report.json must declare."""

    def clark(self, qname: str) -> str | None:
        """Return a report qname in Clark notation, or ``None``.

        Returns:
            str | None: ``{uri}local``, or ``None`` for an unknown prefix.
        """
        try:
            return self._clark[qname]
        except KeyError:
            if qname.startswith("{"):
                result = qname
            else:
                prefix, separator, local = qname.partition(":")
                uri = self.report.get(prefix) if separator else None
                result = f"{{{uri}}}{local}" if uri else None
            self._clark[qname] = result
            return result

    def render(self, clark: str) -> str:
        """Return a Clark qname with the module's prefix for its namespace.

        A namespace the module does not declare keeps the report's prefix,
        which is then declared in ``extra``.

        Returns:
            str: A prefixed qname.
        """
        rendered = self._rendered.get(clark)
        if rendered is None:
            uri, _, local = clark[1:].partition("}")
            prefix = self.module_prefixes.get(uri) or self.extra_prefix(uri)
            rendered = self._rendered[clark] = f"{prefix}:{local}"
        return rendered

    def extra_prefix(self, uri: str) -> str:
        """Pick and record a prefix for a namespace the module lacks.

        Returns:
            str: The report's prefix for it, made unique against the module.
        """
        for prefix, bound in self.extra.items():
            if bound == uri:
                return prefix
        base = next(
            (prefix for prefix, bound in self.report.items() if bound == uri), "ns"
        )
        prefix = base
        while prefix in self.module or prefix in self.extra:
            prefix += "_"
        self.extra[prefix] = uri
        return prefix

    def translate(self, qname: str) -> str:
        """Re-prefix a report qname for the module, keeping unknown text.

        Returns:
            str: The qname with the module's prefix, or ``qname`` unchanged.
        """
        clark = self.clark(qname)
        return self.render(clark) if clark else qname

    def translate_list(self, value: str) -> str:
        """Re-prefix a space-separated list of qnames.

        Returns:
            str: The translated list.
        """
        return " ".join(self.translate(item) for item in value.split())


def fact_members(
    fact: Fact, namespaces: Namespaces, cache: dict[int, Any]
) -> dict[str, Member] | None:
    """Return a fact's dimensions in Clark notation, cached per context.

    XML facts of one context share their dimension mappings, so the result
    is cached by their identity (the caller keeps the report alive).

    Returns:
        dict[str, Member] | None: Clark dimension to member or typed value,
        or ``None`` if a prefix is undeclared.
    """
    key = id(fact.dimensions) ^ (id(fact.typed_dimensions) << 1)
    entry = cache.get(key)
    if (
        entry is not None
        and entry[0] is fact.dimensions
        and entry[1] is fact.typed_dimensions
    ):
        return entry[2]
    members: dict[str, Member] | None = {}
    for dimension, member in fact.dimensions.items():
        name, clark = namespaces.clark(dimension), namespaces.clark(member)
        if name is None or clark is None:
            members = None
            break
        members[name] = (True, clark)
    if members is not None:
        for dimension, value in fact.typed_dimensions.items():
            name = namespaces.clark(dimension)
            if name is None:
                members = None
                break
            members[name] = (False, value)
    cache[key] = (fact.dimensions, fact.typed_dimensions, members)
    return members


def describe(items: Iterable[str], limit: int = 5) -> str:
    """Join the first few items and count the rest.

    Returns:
        str: ``a, b, c`` or ``a, b, c and 7 more``.
    """
    items = list(items)
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown} and {len(items) - limit} more"
