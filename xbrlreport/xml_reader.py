"""Read XBRL 2.1 XML instances into the neutral fact model.

The reader streams the instance with ``iterparse``, clears each top-level
element once processed, and rejects any DOCTYPE before parsing so that no
entity is ever declared or resolved.
"""

from __future__ import annotations

import io
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import IO
from xml.etree import ElementTree as ET

from ._util import WarningLog
from ._xmlsafe import check_prolog
from .model import Fact, Limits, Report, ReportError

XBRLI = "http://www.xbrl.org/2003/instance"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XBRLDI = "http://xbrl.org/2006/xbrldi"
FIND = "http://www.eurofiling.info/xbrl/ext/filing-indicators"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ISO4217 = "http://www.xbrl.org/2003/iso4217"
_NON_FACT_NAMESPACES = frozenset({XBRLI, LINK, FIND})


def _split(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        uri, _, local = tag[1:].partition("}")
        return uri, local
    return "", tag


@dataclass(frozen=True, slots=True)
class _Context:
    scheme: str | None
    identifier: str | None
    reference_date: date | None
    dimensions: dict[str, str]
    typed_dimensions: dict[str, str]


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    currency: bool


@dataclass(frozen=True, slots=True)
class _RawFact:
    concept: str
    value: str | None
    context: str
    unit: str | None
    decimals: int | None
    location: str


@dataclass(slots=True)
class _ContextBuilder:
    scheme: str | None = None
    identifier: str | None = None
    instant: str | None = None
    end: str | None = None
    dimensions: dict[str, str] = field(default_factory=dict)
    typed_dimensions: dict[str, str] = field(default_factory=dict)


def read_xbrl_xml(
    source: str | os.PathLike[str] | bytes,
    *,
    name: str | None = None,
    limits: Limits = Limits(),
) -> Report:
    """Read one XBRL 2.1 XML instance.

    Args:
        source: Instance bytes or a path to the instance document.
        name: Label used in messages and fact locations.
        limits: Resource limits for untrusted input.

    Returns:
        Report: Report with ``format == "xbrl-xml"``.

    Raises:
        ReportError: If the instance is malformed, unsafe or over a limit.
    """
    if isinstance(source, bytes):
        label = name or "instance.xbrl"
        if len(source) > limits.max_file_size:
            raise ReportError(
                f"{label}: exceeds the maximum file size of "
                f"{limits.max_file_size} bytes"
            )
        check_prolog(io.BytesIO(source).read, label)
        return _InstanceReader(label, limits).read(io.BytesIO(source))
    path = Path(source).expanduser()
    label = name or path.name
    if not path.is_file():
        raise ReportError(f"{path}: no such file")
    if path.stat().st_size > limits.max_file_size:
        raise ReportError(
            f"{label}: exceeds the maximum file size of {limits.max_file_size} bytes"
        )
    with path.open("rb") as stream:
        check_prolog(stream.read, label)
    with path.open("rb") as stream:
        return _InstanceReader(label, limits).read(stream)


class _InstanceReader:
    def __init__(self, label: str, limits: Limits) -> None:
        self._label = label
        self._limits = limits
        self._warnings = WarningLog()
        self._namespaces: dict[str, str] = {}
        self._prefix_for_uri: dict[str, str] = {}
        self._scopes: list[dict[str, str]] = [
            {"xml": "http://www.w3.org/XML/1998/namespace"}
        ]
        self._contexts: dict[str, _Context] = {}
        self._units: dict[str, _Unit] = {}
        self._facts: list[_RawFact] = []
        self._filing_indicators: dict[str, bool] = {}
        self._entry_point: str | None = None
        self._context: _ContextBuilder | None = None
        self._measures: dict[str, list[str]] | None = None
        self._measure_part = "measure"
        self._fact_count = 0

    # Namespaces ------------------------------------------------------------------

    def _bind(self, prefix: str, uri: str) -> None:
        if prefix and uri not in self._prefix_for_uri:
            candidate = prefix
            counter = 1
            while candidate in self._namespaces and self._namespaces[candidate] != uri:
                candidate = f"{prefix}{counter}"
                counter += 1
            self._namespaces[candidate] = uri
            self._prefix_for_uri[uri] = candidate

    def _render(self, uri: str, local: str) -> str:
        if not uri:
            return local
        prefix = self._prefix_for_uri.get(uri)
        if prefix is None:
            counter = 0
            while f"ns{counter}" in self._namespaces:
                counter += 1
            self._bind(f"ns{counter}", uri)
            prefix = self._prefix_for_uri[uri]
        return f"{prefix}:{local}"

    def _qname_value(self, text: str | None, where: str) -> str:
        value = (text or "").strip()
        prefix, separator, local = value.partition(":")
        if not separator:
            prefix, local = "", value
        uri = self._scopes[-1].get(prefix)
        if not local or (prefix and uri is None):
            raise ReportError(f"{self._label}: {where} has invalid QName {value!r}")
        return self._render(uri or "", local)

    # Parsing ---------------------------------------------------------------------

    def read(self, stream: IO[bytes]) -> Report:
        depth = 0
        root: ET.Element | None = None
        pending: dict[str, str] = {}
        try:
            for event, item in ET.iterparse(
                stream, events=("start-ns", "start", "end")
            ):
                if event == "start-ns":
                    prefix, uri = item  # type: ignore[misc]
                    pending[prefix] = uri
                    continue
                element: ET.Element = item  # type: ignore[assignment]
                if event == "start":
                    self._scopes.append({**self._scopes[-1], **pending})
                    if depth == 0:
                        root = element
                        for prefix, uri in pending.items():
                            self._bind(prefix, uri)
                        if element.tag != f"{{{XBRLI}}}xbrl":
                            raise ReportError(
                                f"{self._label}: root element must be xbrli:xbrl, "
                                f"found {element.tag}"
                            )
                    else:
                        for prefix, uri in pending.items():
                            self._bind(prefix, uri)
                        self._start(element, depth)
                    pending = {}
                    depth += 1
                    continue
                depth -= 1
                self._end(element, depth)
                self._scopes.pop()
                if depth == 1 and root is not None:
                    root.clear()
        except ET.ParseError as error:
            line, column = getattr(error, "position", (0, 0))
            raise ReportError(
                f"{self._label}:{line}:{column}: malformed XML ({error})"
            ) from error
        return self._report()

    def _start(self, element: ET.Element, depth: int) -> None:
        uri, local = _split(element.tag)
        if depth == 1 and uri == XBRLI and local == "context":
            self._context = _ContextBuilder()
        elif depth == 1 and uri == XBRLI and local == "unit":
            self._measures = {"measure": [], "numerator": [], "denominator": []}
            self._measure_part = "measure"
        elif uri == XBRLI and local == "unitNumerator":
            self._measure_part = "numerator"
        elif uri == XBRLI and local == "unitDenominator":
            self._measure_part = "denominator"

    def _end(self, element: ET.Element, depth: int) -> None:
        uri, local = _split(element.tag)
        if depth == 1:
            self._top_level(element, uri, local)
            return
        if self._context is not None and uri == XBRLI:
            text = (element.text or "").strip()
            if local == "identifier":
                self._context.scheme = element.get("scheme")
                self._context.identifier = text
            elif local == "instant":
                self._context.instant = text
            elif local == "endDate":
                self._context.end = text
        elif self._context is not None and uri == XBRLDI:
            self._dimension_member(element, local)
        elif self._measures is not None and uri == XBRLI and local == "measure":
            self._measures[self._measure_part].append(
                self._qname_value(element.text, "unit measure")
            )
        elif uri == FIND and local == "filingIndicator":
            code = (element.text or "").strip()
            filed = element.get(f"{{{FIND}}}filed", element.get("filed", "true"))
            if not code:
                self._warnings.add(f"{self._label}: empty filing indicator ignored")
            else:
                self._filing_indicators[code] = filed.strip() not in {"false", "0"}
        elif uri in {XBRLI, LINK} and local in {"unitNumerator", "unitDenominator"}:
            self._measure_part = "measure"

    def _dimension_member(self, element: ET.Element, local: str) -> None:
        assert self._context is not None
        raw_dimension = element.get("dimension")
        if raw_dimension is None:
            raise ReportError(f"{self._label}: xbrldi:{local} without dimension")
        dimension = self._qname_value(raw_dimension, f"xbrldi:{local} dimension")
        if local == "explicitMember":
            self._context.dimensions[dimension] = self._qname_value(
                element.text, f"explicit member of {dimension}"
            )
        elif local == "typedMember":
            children = list(element)
            if len(children) != 1:
                raise ReportError(
                    f"{self._label}: typed member of {dimension} must have one "
                    "child element"
                )
            self._context.typed_dimensions[dimension] = "".join(
                children[0].itertext()
            ).strip()

    def _top_level(self, element: ET.Element, uri: str, local: str) -> None:
        if uri == XBRLI and local == "context":
            self._finish_context(element)
        elif uri == XBRLI and local == "unit":
            self._finish_unit(element)
        elif uri == LINK and local == "schemaRef":
            href = element.get(f"{{{XLINK}}}href")
            if self._entry_point is None:
                self._entry_point = href
            elif href != self._entry_point:
                self._warnings.add(
                    f"{self._label}: additional schemaRef {href} ignored"
                )
        elif uri in _NON_FACT_NAMESPACES:
            return
        elif element.get("contextRef") is not None:
            self._fact(element, uri, local)
        elif len(element):
            self._warnings.count(
                f"{self._label}: tuples are not supported and were skipped",
                f"{self._label}#{element.get('id') or local}",
            )
        else:
            self._warnings.count(
                f"{self._label}: elements without contextRef skipped",
                f"{self._label}#{element.get('id') or local}",
            )

    def _finish_context(self, element: ET.Element) -> None:
        builder = self._context
        self._context = None
        assert builder is not None
        context_id = element.get("id")
        if not context_id:
            raise ReportError(f"{self._label}: context without id")
        period = builder.instant or builder.end
        reference_date = None
        if period:
            try:
                reference_date = date.fromisoformat(period[:10])
            except ValueError as error:
                raise ReportError(
                    f"{self._label}: context {context_id} has invalid period {period!r}"
                ) from error
        self._contexts[context_id] = _Context(
            builder.scheme,
            builder.identifier,
            reference_date,
            builder.dimensions,
            builder.typed_dimensions,
        )

    def _finish_unit(self, element: ET.Element) -> None:
        measures = self._measures
        self._measures = None
        assert measures is not None
        unit_id = element.get("id")
        if not unit_id:
            raise ReportError(f"{self._label}: unit without id")
        if measures["numerator"] or measures["denominator"]:
            text = (
                "*".join(measures["numerator"])
                + "/"
                + "*".join(measures["denominator"])
            )
            currency = False
        else:
            text = "*".join(measures["measure"])
            iso_prefix = self._prefix_for_uri.get(ISO4217)
            currency = (
                len(measures["measure"]) == 1
                and iso_prefix is not None
                and text.startswith(f"{iso_prefix}:")
            )
        if not text:
            raise ReportError(f"{self._label}: unit {unit_id} has no measure")
        self._units[unit_id] = _Unit(text, currency)

    def _fact(self, element: ET.Element, uri: str, local: str) -> None:
        self._fact_count += 1
        if self._fact_count > self._limits.max_facts:
            raise ReportError(
                f"{self._label}: report exceeds the limit of "
                f"{self._limits.max_facts} facts"
            )
        fact_id = element.get("id")
        location = f"{self._label}#{fact_id or f'fact{self._fact_count}'}"
        if len(element):
            self._warnings.count(
                f"{self._label}: tuples are not supported and were skipped", location
            )
            return
        nil = element.get(f"{{{XSI}}}nil", "false").strip() in {"true", "1"}
        raw_decimals = element.get("decimals")
        decimals: int | None = None
        if raw_decimals is not None and raw_decimals.strip() != "INF":
            try:
                decimals = int(raw_decimals.strip())
            except ValueError as error:
                raise ReportError(
                    f"{location}: invalid decimals {raw_decimals!r}"
                ) from error
        if element.get("precision") is not None:
            self._warnings.count(
                f"{self._label}: precision attributes ignored", location
            )
        self._facts.append(
            _RawFact(
                concept=self._render(uri, local),
                value=None if nil else element.text or "",
                context=element.get("contextRef", ""),
                unit=element.get("unitRef"),
                decimals=decimals,
                location=location,
            )
        )

    # Report ----------------------------------------------------------------------

    def _report(self) -> Report:
        facts: list[Fact] = []
        entities: Counter[tuple[str | None, str | None]] = Counter()
        periods: Counter[date | None] = Counter()
        currencies: Counter[str] = Counter()
        for raw in self._facts:
            context = self._contexts.get(raw.context)
            if context is None:
                raise ReportError(f"{raw.location}: undefined context {raw.context!r}")
            unit = None
            if raw.unit is not None:
                unit_definition = self._units.get(raw.unit)
                if unit_definition is None:
                    raise ReportError(f"{raw.location}: undefined unit {raw.unit!r}")
                unit = unit_definition.text
                if unit_definition.currency:
                    currencies[unit] += 1
            entities[context.scheme, context.identifier] += 1
            periods[context.reference_date] += 1
            facts.append(
                Fact(
                    value=raw.value,
                    concept=raw.concept,
                    dimensions=dict(context.dimensions),
                    typed_dimensions=dict(context.typed_dimensions),
                    unit=unit,
                    decimals=raw.decimals,
                    location=raw.location,
                )
            )
        if not facts:
            for context in self._contexts.values():
                entities[context.scheme, context.identifier] += 1
                periods[context.reference_date] += 1
        if len(entities) > 1:
            self._warnings.add(
                f"{self._label}: facts use {len(entities)} distinct entities; "
                "EBA filing rules require one"
            )
        if len(periods) > 1:
            self._warnings.add(
                f"{self._label}: facts use {len(periods)} distinct periods; "
                "EBA filing rules require one"
            )
        scheme, identifier = entities.most_common(1)[0][0] if entities else (None, None)
        return Report(
            format="xbrl-xml",
            entry_point=self._entry_point,
            entity_scheme=scheme,
            entity_id=identifier,
            reference_date=periods.most_common(1)[0][0] if periods else None,
            base_currency=currencies.most_common(1)[0][0] if currencies else None,
            parameters={},
            decimals_parameters={},
            filing_indicators=dict(self._filing_indicators),
            facts=tuple(facts),
            namespaces=dict(self._namespaces),
            warnings=self._warnings.result(),
        )
