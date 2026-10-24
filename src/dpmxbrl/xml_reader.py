"""Read XBRL 2.1 XML instances into the neutral fact model.

The reader streams the instance with ``iterparse``, clears each top-level
element once processed, and rejects any DOCTYPE before parsing so that no
entity is ever declared or resolved. The same pass records the EBA filing
rules the instance breaks (see :mod:`dpmxbrl.filing`).
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import IO, Any
from xml.etree import ElementTree as ET

from ._checks import check_with_taxonomy
from ._taxonomy import TaxonomyPackages
from ._util import EMPTY_MAPPING, FrozenDict, WarningLog, gc_paused
from ._xmlsafe import check_prolog
from .filing import FilingLog, check_entry_point, check_file_name, check_subject
from .model import Fact, Limits, Report, ReportError

XBRLI = "http://www.xbrl.org/2003/instance"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XBRLDI = "http://xbrl.org/2006/xbrldi"
FIND = "http://www.eurofiling.info/xbrl/ext/filing-indicators"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ISO4217 = "http://www.xbrl.org/2003/iso4217"
XINCLUDE = "http://www.w3.org/2001/XInclude"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
_NON_FACT_NAMESPACES = frozenset({XBRLI, LINK, FIND})
_XML_BASE = f"{{{XML_NAMESPACE}}}base"
_XML_LANG = f"{{{XML_NAMESPACE}}}lang"
_SCHEMA_LOCATIONS = frozenset(
    {
        f"{{{XSI}}}schemaLocation",
        f"{{{XSI}}}noNamespaceSchemaLocation",
    }
)
_DIMENSION_MEMBERS = frozenset({"explicitMember", "typedMember"})
# Dimensions that decide a monetary fact's currency (rule 3.1).
_CURRENCY_DIMENSIONS = (":CCA", ":qAEA", ":CUS", ":CUA")
_PLAIN_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DECLARATION = re.compile(rb"<\?xml\s([^?]*)\?>")
_PSEUDO_ATTRIBUTE = re.compile(rb"""(\w+)\s*=\s*["']([^"']*)["']""")
_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


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
    dimensions: Mapping[str, str]
    """Read-only, and shared by the facts of the context."""
    typed_dimensions: Mapping[str, str]
    signature: int
    """Index of the context's content; equal contexts share it."""
    qualified: bool
    """Whether the context has a segment or scenario."""
    denomination: bool
    """Whether its facts are in their currency of denomination (rule 3.1)."""
    currency: str | None
    """Code of the CU member of its CUS or CUA dimension, if any."""


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    currency: bool
    pure: bool


@dataclass(frozen=True, slots=True)
class _RawFact:
    concept: str
    value: str | None
    context: str
    unit: str | None
    decimals: int | None
    location: str
    lang: str | None


@dataclass(slots=True)
class _ContextBuilder:
    scheme: str | None = None
    identifier: str | None = None
    instant: str | None = None
    start: str | None = None
    end: str | None = None
    forever: bool = False
    segment: bool = False
    scenario: bool = False
    scenario_content: bool = False
    """Whether the scenario holds anything besides dimension members."""
    dates: list[str] = field(default_factory=list)
    denomination: bool = False
    currency: str | None = None
    dimensions: dict[str, str] = field(default_factory=dict)
    typed_dimensions: dict[str, str] = field(default_factory=dict)


def read_xbrl_xml(
    source: str | os.PathLike[str] | bytes,
    *,
    name: str | None = None,
    taxonomy_packages: str | os.PathLike[str] | Sequence[str | os.PathLike[str]] = (),
    limits: Limits = Limits(),
) -> Report:
    """Read one XBRL 2.1 XML instance.

    Args:
        source: Instance bytes or a path to the instance document.
        name: Label used in messages and fact locations.
        taxonomy_packages: Local taxonomy package ZIPs, one path or a
            sequence; with them the filing rules that need the taxonomy are
            checked too.
        limits: Resource limits for untrusted input.

    Returns:
        Report: Report with ``format == "xbrl-xml"``.

    Raises:
        ReportError: If the instance is malformed, unsafe or over a limit.

    Examples:
        >>> from dpmxbrl import read_xbrl_xml
        >>> fact = read_xbrl_xml("instance.xbrl").facts[2]
        >>> fact.concept, dict(fact.dimensions), dict(fact.typed_dimensions)
        ('eba_met:qNCO', {'eba_dim:qNCO': 'eba_qCO:qx2000'}, {'eba_dim:qINC': 'CP0001'})
    """
    report = _read(source, name=name, limits=limits)
    if not taxonomy_packages:
        return report
    log = FilingLog()
    log.extend(report.filing)
    taxonomy = TaxonomyPackages(taxonomy_packages, limits=limits)
    try:
        check_with_taxonomy(
            report,
            taxonomy,
            log,
            where=name or _label(source),
            limits=limits,
        )
    finally:
        taxonomy.close()
    return replace(report, filing=log.result())


def _label(source: str | os.PathLike[str] | bytes) -> str:
    if isinstance(source, bytes):
        return "instance.xbrl"
    return Path(source).name


def _read(
    source: str | os.PathLike[str] | bytes, *, name: str | None, limits: Limits
) -> Report:
    if isinstance(source, bytes):
        label = name or "instance.xbrl"
        if len(source) > limits.max_file_size:
            raise ReportError(
                f"{label}: exceeds the maximum file size of "
                f"{limits.max_file_size} bytes"
            )
        head = check_prolog(io.BytesIO(source).read, label)
        reader = _InstanceReader(label, limits, head, file_name=name)
        with gc_paused():
            return reader.read(io.BytesIO(source))
    path = Path(source).expanduser()
    label = name or path.name
    if not path.is_file():
        raise ReportError(f"{path}: no such file")
    try:
        if path.stat().st_size > limits.max_file_size:
            raise ReportError(
                f"{label}: exceeds the maximum file size of "
                f"{limits.max_file_size} bytes"
            )
        with path.open("rb") as stream:
            head = check_prolog(stream.read, label)
        stream = path.open("rb")
    except OSError as error:
        raise ReportError(f"{label}: cannot be read ({error.strerror})") from error
    with stream, gc_paused():
        return _InstanceReader(label, limits, head, file_name=label).read(stream)


def _frozen(mapping: dict[str, str]) -> Mapping[str, str]:
    return FrozenDict(mapping) if mapping else EMPTY_MAPPING


class _ForbiddenAttributeScanner:
    """Pass a stream to the parser, watching for attributes the rules forbid.

    The parser reads ahead in chunks, so the flag is set before it reports
    the elements of the chunk that holds the attribute's name.
    """

    _MARKERS = (b"xml:base", b"chemaLocation")
    _OVERLAP = 32

    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream
        self._tail = b""
        self.forbidden = False

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        if not self.forbidden and data:
            window = self._tail + data
            self.forbidden = any(marker in window for marker in self._MARKERS)
            self._tail = window[-self._OVERLAP :]
        return data


class _InstanceReader:
    def __init__(
        self, label: str, limits: Limits, head: bytes, *, file_name: str | None
    ) -> None:
        self._label = label
        self._limits = limits
        self._file_name = file_name
        self._warnings = WarningLog()
        self._filing = FilingLog()
        self._namespaces: dict[str, str] = {}
        self._prefix_for_uri: dict[str, str] = {}
        self._scopes: list[dict[str, str]] = [{"xml": XML_NAMESPACE}]
        self._contexts: dict[str, _Context] = {}
        self._signatures: dict[tuple[Any, ...], tuple[int, str]] = {}
        self._units: dict[str, _Unit] = {}
        self._unit_signatures: dict[tuple[Any, ...], str] = {}
        self._facts: list[_RawFact] = []
        self._filing_indicators: dict[str, bool] = {}
        self._indicator_contexts: list[tuple[str | None, str]] = []
        self._schema_refs: list[str] = []
        self._context: _ContextBuilder | None = None
        self._context_child: str | None = None
        self._measures: dict[str, list[str]] | None = None
        self._measure_part = "measure"
        self._fact_count = 0
        # Namespace use, for rules 3.4, 3.9 and 3.10.
        self._root_prefixes: dict[str, str] = {}
        self._declared: dict[str, set[str]] = {}
        self._used: set[str] = set()
        self._tags: set[str] = set()
        self._qnames: dict[str | None, str] = {}
        self._tag_parts: dict[str, tuple[str, str]] = {}
        self._nested_declarations = False
        self._check_declaration(head)

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

    def _parts(self, rendered: str) -> tuple[str, str]:
        """Return the namespace URI and local name of a rendered QName."""
        prefix, _, local = rendered.partition(":")
        return self._namespaces.get(prefix, ""), local

    def _qname_value(self, text: str | None, where: str) -> str:
        # Dimension and member QNames repeat across thousands of contexts;
        # while no element redeclares a prefix, each text resolves once.
        if not self._nested_declarations:
            cached = self._qnames.get(text)
            if cached is not None:
                return cached
        rendered = self._resolve_qname(text, where)
        if not self._nested_declarations:
            self._qnames[text] = rendered
        return rendered

    def _resolve_qname(self, text: str | None, where: str) -> str:
        value = (text or "").strip()
        prefix, separator, local = value.partition(":")
        if not separator:
            prefix, local = "", value
        uri = self._scopes[-1].get(prefix)
        if not local or (prefix and uri is None):
            raise ReportError(f"{self._label}: {where} has invalid QName {value!r}")
        if uri:
            self._used.add(uri)
        return self._render(uri or "", local)

    # Parsing ---------------------------------------------------------------------

    def read(self, stream: IO[bytes]) -> Report:
        depth = 0
        root: ET.Element | None = None
        pending: dict[str, str] = {}
        tags = self._tags
        scanner = _ForbiddenAttributeScanner(stream)
        try:
            for event, item in ET.iterparse(
                scanner, events=("start-ns", "start", "end")
            ):
                if event == "start-ns":
                    prefix, uri = item  # type: ignore[misc]
                    pending[prefix] = uri
                    self._declared.setdefault(uri, set()).add(prefix)
                    continue
                element: ET.Element = item  # type: ignore[assignment]
                if event == "start":
                    # Scopes are never changed once made: an element that
                    # declares nothing shares its parent's.
                    scope = self._scopes[-1]
                    self._scopes.append({**scope, **pending} if pending else scope)
                    if element.tag not in tags:
                        self._new_tag(element)
                    # Namespaced attributes sit on the document element and
                    # its children. Deeper elements are examined only once
                    # the raw text has shown an attribute the rules forbid:
                    # reading element.attrib allocates a dictionary each time.
                    if depth <= 1 or scanner.forbidden:
                        self._attributes(element, element.attrib)
                    if depth == 0:
                        root = element
                        self._root_prefixes = dict(pending)
                        for prefix, uri in pending.items():
                            self._bind(prefix, uri)
                        if element.tag != f"{{{XBRLI}}}xbrl":
                            raise ReportError(
                                f"{self._label}: root element must be xbrli:xbrl, "
                                f"found {element.tag}"
                            )
                    else:
                        if pending:
                            self._nested_declarations = True
                            self._filing.add(
                                "3.9",
                                "unexpectedNamespaceDeclarations",
                                "warning",
                                "Namespace prefixes should be declared on the "
                                "document element only.",
                                self._where(element),
                            )
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
        except ReportError:
            raise
        except (LookupError, ValueError) as error:
            # An unknown or multi-byte encoding in the XML declaration.
            raise ReportError(f"{self._label}: unreadable XML ({error})") from error
        return self._report()

    def _where(self, element: ET.Element) -> str:
        identifier = element.get("id")
        return f"{self._label}#{identifier or _split(element.tag)[1]}"

    def _check_declaration(self, head: bytes) -> None:
        """Check the XML declaration (rules 1.4 and 1.13)."""
        if head.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in head[:2]:
            self._filing.add(
                "1.4",
                "encodingNotUtf8",
                "error",
                "The report must be encoded in UTF-8; it is encoded in UTF-16.",
                self._label,
            )
            return
        match = _DECLARATION.match(head.removeprefix(b"\xef\xbb\xbf"))
        if match is None:
            return
        pseudo = {
            key.decode("ascii").casefold(): value.decode("ascii", "replace")
            for key, value in _PSEUDO_ATTRIBUTE.findall(match.group(1))
        }
        encoding = pseudo.get("encoding")
        if encoding is not None and encoding.casefold() != "utf-8":
            self._filing.add(
                "1.4",
                "encodingNotUtf8",
                "error",
                f"The report must be encoded in UTF-8; it declares {encoding}.",
                self._label,
            )
        if "standalone" in pseudo:
            self._filing.add(
                "1.13",
                "standaloneDocumentDeclarationUsed",
                "warning",
                "The XML declaration should not include a standalone declaration.",
                self._label,
            )

    def _new_tag(self, element: ET.Element) -> None:
        """Record the namespace of a tag seen for the first time.

        Instances repeat a few dozen tags hundreds of thousands of times, so
        each tag is examined once.
        """
        uri = _split(element.tag)[0]
        self._tags.add(element.tag)
        self._used.add(uri)
        if uri == XINCLUDE:
            self._filing.add(
                "1.15",
                "xIncludeUsed",
                "error",
                "The report must not use XInclude (xi:include).",
                self._where(element),
            )

    def _attributes(self, element: ET.Element, names: Iterable[str]) -> None:
        """Record namespaced attributes and those the filing rules forbid."""
        for name in names:
            if name[0] != "{":
                continue
            self._used.add(name[1 : name.index("}")])
            if name == _XML_BASE:
                self._filing.add(
                    "2.1",
                    "xmlBaseUsed",
                    "error",
                    "The report must not use the xml:base attribute.",
                    self._where(element),
                )
            elif name in _SCHEMA_LOCATIONS:
                self._filing.add(
                    "1.14",
                    "schemaLocationAttributeUsed",
                    "error",
                    "The report must not use xsi:schemaLocation or "
                    "xsi:noNamespaceSchemaLocation.",
                    self._where(element),
                )

    def _tag(self, tag: str) -> tuple[str, str]:
        """Return a tag's namespace URI and local name, splitting each tag once."""
        parts = self._tag_parts.get(tag)
        if parts is None:
            parts = self._tag_parts[tag] = _split(tag)
        return parts

    def _start(self, element: ET.Element, depth: int) -> None:
        uri, local = self._tag(element.tag)
        if depth == 1 and uri == XBRLI and local == "context":
            self._context = _ContextBuilder()
        elif depth == 1 and uri == XBRLI and local == "unit":
            self._measures = {"measure": [], "numerator": [], "denominator": []}
            self._measure_part = "measure"
        elif uri == XBRLI and local == "unitNumerator":
            self._measure_part = "numerator"
        elif uri == XBRLI and local == "unitDenominator":
            self._measure_part = "denominator"
        elif self._context is not None:
            if depth == 2:
                self._context_child = local
            elif (
                depth == 3
                and self._context_child == "scenario"
                and (uri != XBRLDI or local not in _DIMENSION_MEMBERS)
            ):
                self._context.scenario_content = True
            if uri == XBRLI:
                if local == "segment":
                    self._context.segment = True
                elif local == "scenario":
                    self._context.scenario = True
                elif local == "forever":
                    self._context.forever = True

    def _end(self, element: ET.Element, depth: int) -> None:
        uri, local = self._tag(element.tag)
        if depth == 1:
            self._top_level(element, uri, local)
            return
        if self._context is not None and uri == XBRLI:
            text = (element.text or "").strip()
            if local == "identifier":
                self._context.scheme = element.get("scheme")
                self._context.identifier = text
            elif local in {"instant", "startDate", "endDate"}:
                if local == "instant":
                    self._context.instant = text
                elif local == "startDate":
                    self._context.start = text
                else:
                    self._context.end = text
                if not _PLAIN_DATE.fullmatch(text):
                    self._context.dates.append(text)
        elif self._context is not None and uri == XBRLDI:
            self._dimension_member(element, local)
        elif self._measures is not None and uri == XBRLI and local == "measure":
            self._measures[self._measure_part].append(
                self._qname_value(element.text, "unit measure")
            )
        elif uri == FIND and local == "filingIndicator":
            self._filing_indicator(element)
        elif uri in {XBRLI, LINK} and local in {"unitNumerator", "unitDenominator"}:
            self._measure_part = "measure"

    def _filing_indicator(self, element: ET.Element) -> None:
        code = (element.text or "").strip()
        filed = element.get(f"{{{FIND}}}filed", element.get("filed", "true"))
        if not code:
            self._warnings.add(f"{self._label}: empty filing indicator ignored")
            return
        if code in self._filing_indicators:
            self._filing.add(
                "1.6.1",
                "duplicateFilingIndicator",
                "error",
                "Each template must have exactly one filing indicator.",
                f"{self._label}: {code}",
            )
        self._filing_indicators[code] = filed.strip() not in {"false", "0"}
        self._indicator_contexts.append((element.get("contextRef"), code))

    def _dimension_member(self, element: ET.Element, local: str) -> None:
        assert self._context is not None
        raw_dimension = element.get("dimension")
        if raw_dimension is None:
            raise ReportError(f"{self._label}: xbrldi:{local} without dimension")
        dimension = self._qname_value(raw_dimension, f"xbrldi:{local} dimension")
        if local == "explicitMember":
            member = self._context.dimensions[dimension] = self._qname_value(
                element.text, f"explicit member of {dimension}"
            )
            if dimension.endswith(_CURRENCY_DIMENSIONS):
                self._currency_member(self._context, dimension, member)
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
            self._schema_refs.append(element.get(f"{{{XLINK}}}href") or "")
        elif uri == LINK and local == "linkbaseRef":
            self._filing.add(
                "2.4",
                "linkbaseRefUsed",
                "error",
                "The report must reference its taxonomy only with link:schemaRef, "
                "never link:linkbaseRef.",
                self._where(element),
            )
        elif uri == LINK and local == "footnoteLink":
            self._filing.add(
                "2.25",
                "xbrlFootnotesAreIgnored",
                "warning",
                "The EBA ignores footnotes; they must not carry regulatory content.",
                self._where(element),
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
        self._context_child = None
        assert builder is not None
        context_id = element.get("id")
        if not context_id:
            raise ReportError(f"{self._label}: context without id")
        period = builder.instant or builder.end
        reference_date = None
        if period:
            # fromisoformat alone would also accept 20241231 and week dates.
            if _PLAIN_DATE.fullmatch(period.strip()[:10]):
                with contextlib.suppress(ValueError):
                    reference_date = date.fromisoformat(period.strip()[:10])
            if reference_date is None:
                raise ReportError(
                    f"{self._label}: context {context_id} has invalid period {period!r}"
                )
        self._check_context(builder, f"{self._label}#{context_id}")
        content = (
            builder.scheme,
            builder.identifier,
            builder.instant,
            builder.start,
            builder.end,
            builder.forever,
            builder.segment,
            frozenset(builder.dimensions.items()),
            frozenset(builder.typed_dimensions.items()),
        )
        known = self._signatures.get(content)
        if known is None:
            known = self._signatures[content] = (len(self._signatures), context_id)
        else:
            self._filing.add(
                "2.7",
                "duplicateContext",
                "warning",
                "The report should not repeat a context with the same content.",
                f"{self._label}: context {context_id} duplicates context {known[1]}",
            )
        self._contexts[context_id] = _Context(
            builder.scheme,
            builder.identifier,
            reference_date,
            _frozen(builder.dimensions),
            _frozen(builder.typed_dimensions),
            known[0],
            builder.segment or builder.scenario,
            builder.denomination,
            builder.currency,
        )

    def _check_context(self, builder: _ContextBuilder, where: str) -> None:
        """Check one context's period and qualifiers (rules 2.10 to 2.15)."""
        if builder.segment:
            self._filing.add(
                "2.14",
                "segmentUsed",
                "error",
                "Contexts must not use xbrli:segment; dimensions belong in "
                "xbrli:scenario.",
                where,
            )
        if builder.scenario_content:
            self._filing.add(
                "2.15",
                "scenarioContainsNonDimensionContent",
                "error",
                "A scenario must hold only xbrldi:explicitMember and "
                "xbrldi:typedMember elements.",
                where,
            )
        if builder.forever:
            self._filing.add(
                "2.11",
                "foreverUsed",
                "error",
                "Contexts must not use xbrli:forever.",
                where,
            )
        if builder.start is not None:
            self._filing.add(
                "2.13",
                "nonInstantPeriodUsed",
                "error",
                "Every period must be an instant, the reference date; "
                "durations are not allowed.",
                where,
            )
        for text in builder.dates:
            timed = "T" in text
            self._filing.add(
                "2.10",
                "periodWithTimeContent" if timed else "periodWithTimezone",
                "error",
                "Period dates must be plain dates (YYYY-MM-DD) without a "
                + ("time." if timed else "time zone."),
                f"{where}: {text}",
            )

    def _currency_member(
        self, builder: _ContextBuilder, dimension: str, member: str
    ) -> None:
        """Note a member that decides a monetary fact's currency (rule 3.1)."""
        local = self._parts(dimension)[1]
        member_uri, code = self._parts(member)
        domain = member_uri.rstrip("/").rsplit("/", 1)[-1]
        if (local, domain, code) in {("CCA", "CA", "x1"), ("qAEA", "qCA", "qx2000")}:
            builder.denomination = True
        elif local in {"CUS", "CUA"} and domain == "CU":
            builder.currency = code

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
            currency = pure = False
        else:
            text = "*".join(measures["measure"])
            single = len(measures["measure"]) == 1
            iso_prefix = self._prefix_for_uri.get(ISO4217)
            currency = (
                single and iso_prefix is not None and text.startswith(f"{iso_prefix}:")
            )
            pure = single and self._parts(text) == (XBRLI, "pure")
        if not text:
            raise ReportError(f"{self._label}: unit {unit_id} has no measure")
        content = tuple(tuple(sorted(measures[part])) for part in measures)
        repeated = self._unit_signatures.setdefault(content, unit_id)
        if repeated != unit_id:
            self._filing.add(
                "2.21",
                "duplicateUnit",
                "warning",
                "The report should not repeat a unit with the same measures.",
                f"{self._label}: unit {unit_id} duplicates unit {repeated}",
            )
        self._units[unit_id] = _Unit(text, currency, pure)

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
        unit = element.get("unitRef")
        raw_decimals = element.get("decimals")
        decimals: int | None = None
        if raw_decimals is not None and raw_decimals.strip() != "INF":
            try:
                decimals = int(raw_decimals.strip())
            except ValueError as error:
                raise ReportError(
                    f"{location}: invalid decimals {raw_decimals!r}"
                ) from error
        precision = element.get("precision") is not None
        text = element.text or ""
        if unit is None:
            # Enumerated facts hold a domain member's QName as their value.
            prefix, colon, _ = text.strip().partition(":")
            if colon and (namespace := self._scopes[-1].get(prefix)):
                self._used.add(namespace)
        self._check_fact(location, nil, unit, raw_decimals, precision, text)
        self._facts.append(
            _RawFact(
                concept=sys.intern(self._render(uri, local)),
                value=None if nil else text,
                context=element.get("contextRef", ""),
                unit=unit,
                decimals=decimals,
                location=location,
                lang=element.get(_XML_LANG) if unit is None else None,
            )
        )

    def _check_fact(
        self,
        location: str,
        nil: bool,
        unit: str | None,
        decimals: str | None,
        precision: bool,
        text: str,
    ) -> None:
        """Check one fact's value and accuracy (rules 2.17 to 2.19)."""
        if nil:
            self._filing.add(
                "2.19",
                "nilUsed",
                "error",
                "Facts must not be nil (xsi:nil); leave out a fact that is not "
                "reported.",
                location,
            )
            return
        if precision:
            self._filing.add(
                "2.17",
                "precisionUsed",
                "error",
                "Facts must state their accuracy with decimals, not precision; "
                "precision is ignored.",
                location,
            )
        if unit is not None:
            if decimals is None and not precision:
                self._filing.add(
                    "2.18",
                    "missingDecimalsAttribute",
                    "error",
                    "Numeric facts must state their accuracy with a decimals "
                    "attribute.",
                    location,
                )
        elif not text:
            self._filing.add(
                "2.19",
                "emptyUsed",
                "error",
                "Text facts must not be empty; leave out a fact that is not reported.",
                location,
            )

    # Report ----------------------------------------------------------------------

    def _report(self) -> Report:
        facts: list[Fact] = []
        entities: Counter[tuple[str | None, str | None]] = Counter()
        periods: Counter[date | None] = Counter()
        currencies: Counter[str] = Counter()
        used_contexts: set[str] = set()
        used_units: set[str] = set()
        seen: dict[tuple[str, int, str | None], tuple[str | None, str]] = {}
        denominated: list[tuple[_RawFact, str, str]] = []
        currency_facts: dict[str, list[str]] = {}
        for raw in self._facts:
            context = self._contexts.get(raw.context)
            if context is None:
                raise ReportError(f"{raw.location}: undefined context {raw.context!r}")
            used_contexts.add(raw.context)
            unit = None
            if raw.unit is not None:
                unit_definition = self._units.get(raw.unit)
                if unit_definition is None:
                    raise ReportError(f"{raw.location}: undefined unit {raw.unit!r}")
                used_units.add(raw.unit)
                unit = unit_definition.text
                if unit_definition.currency:
                    currencies[unit] += 1
                    if context.denomination:
                        if context.currency is not None:
                            denominated.append((raw, context.currency, unit))
                    else:
                        currency_facts.setdefault(unit, []).append(raw.location)
                elif not unit_definition.pure:
                    self._filing.add(
                        "3.2",
                        "pureUnitNotUsedForMonetaryValue",
                        "error",
                        "Non-monetary numeric facts must use the unit xbrli:pure.",
                        raw.location,
                    )
            self._check_duplicate(raw, context, unit, seen)
            entities[context.scheme, context.identifier] += 1
            periods[context.reference_date] += 1
            facts.append(
                Fact(
                    value=raw.value,
                    concept=raw.concept,
                    dimensions=context.dimensions,
                    typed_dimensions=context.typed_dimensions,
                    unit=unit,
                    decimals=raw.decimals,
                    location=raw.location,
                )
            )
        if not facts:
            for context in self._contexts.values():
                entities[context.scheme, context.identifier] += 1
                periods[context.reference_date] += 1
        self._check_currencies(currency_facts, denominated)
        self._check_document(used_contexts, used_units)
        scheme, identifier = entities.most_common(1)[0][0] if entities else (None, None)
        report = Report(
            format="xbrl-xml",
            entry_point=self._schema_refs[0] if self._schema_refs else None,
            entity_scheme=scheme,
            entity_id=identifier,
            reference_date=periods.most_common(1)[0][0] if periods else None,
            base_currency=currencies.most_common(1)[0][0] if currencies else None,
            parameters=FrozenDict(),
            decimals_parameters=FrozenDict(),
            filing_indicators=FrozenDict(self._filing_indicators),
            facts=tuple(facts),
            namespaces=FrozenDict(self._namespaces),
            warnings=self._warnings.result(),
        )
        check_subject(report, self._filing)
        if self._file_name is not None:
            check_file_name(self._file_name, report, self._filing)
        return replace(report, filing=self._filing.result())

    def _check_duplicate(
        self,
        raw: _RawFact,
        context: _Context,
        unit: str | None,
        seen: dict[tuple[str, int, str | None], tuple[str | None, str]],
    ) -> None:
        """Find facts for the same data point (rules 2.16 and 2.16.1)."""
        key = (raw.concept, context.signature, raw.lang)
        first = seen.get(key)
        if first is None:
            seen[key] = (unit, raw.location)
            return
        if first[0] == unit:
            self._filing.add(
                "2.16",
                "duplicateFactXBRL-XML",
                "error",
                "The report must not report the same fact twice.",
                f"{raw.location} duplicates {first[1]}",
            )
        else:
            self._filing.add(
                "2.16.1",
                "factsDifferingOnlyByUnit",
                "error",
                "The report must not report one fact in several units.",
                f"{raw.location} duplicates {first[1]} in {unit}",
            )

    def _check_currencies(
        self,
        reporting: dict[str, list[str]],
        denominated: list[tuple[_RawFact, str, str]],
    ) -> None:
        """Check the currencies of monetary facts (rule 3.1)."""
        main = max(reporting, key=lambda unit: len(reporting[unit]), default=None)
        if len(reporting) > 1:
            names = ", ".join(sorted(self._parts(unit)[1] for unit in reporting))
            for unit, locations in reporting.items():
                if unit == main:
                    continue
                for location in locations:
                    self._filing.add(
                        "3.1",
                        "multipleReportingCurrencies",
                        "error",
                        "Monetary facts not in their currency of denomination must "
                        f"all use one reporting currency; the report uses {names}.",
                        location,
                    )
        iso_prefix = self._prefix_for_uri.get(ISO4217)
        for raw, code, unit in denominated:
            if _CURRENCY_CODE.fullmatch(code):
                expected: str | None = f"{iso_prefix}:{code}"
            elif code == "x1":
                expected = main
            else:
                # Other currency members (eba_CU:x46) accept any currency.
                continue
            if expected is not None and unit != expected:
                self._filing.add(
                    "3.1",
                    "inconsistentCurrencyUnitAndDimension",
                    "error",
                    "Facts in their currency of denomination must use the "
                    "currency their CUS or CUA dimension names (x1: the reporting "
                    "currency).",
                    f"{raw.location}: {self._parts(unit)[1]} for {code}",
                )

    def _check_document(self, used_contexts: set[str], used_units: set[str]) -> None:
        """Check the instance as a whole.

        Covers the entry point, filing indicators, reporting subject, period
        and unused declarations.
        """
        check_entry_point(self._schema_refs, self._filing, where=self._label, xml=True)
        if not self._filing_indicators:
            self._filing.add(
                "1.6",
                "missingFilingIndicators",
                "error",
                "The report has no filing indicators; each template of the module "
                "needs one, marked as reported or not reported.",
                self._label,
            )
        for context_ref, code in self._indicator_contexts:
            if context_ref is not None:
                used_contexts.add(context_ref)
            context = self._contexts.get(context_ref or "")
            if context is not None and context.qualified:
                self._filing.add(
                    "1.6",
                    "invalidContextForFilingIndicator",
                    "error",
                    "The context of a filing indicator must not have a segment or "
                    "scenario.",
                    f"{self._label}: {code}",
                )
        subjects = {(item.scheme, item.identifier) for item in self._contexts.values()}
        if len(subjects) > 1:
            shown = ", ".join(sorted(str(identifier) for _, identifier in subjects)[:3])
            self._filing.add(
                "2.9",
                "multipleIdentifiers",
                "error",
                f"All contexts must identify the same entity; the report uses "
                f"{len(subjects)} ({shown}).",
                self._label,
            )
        dates = {item.reference_date for item in self._contexts.values()}
        if len(dates) > 1:
            shown = ", ".join(sorted(str(day) for day in dates)[:3])
            self._filing.add(
                "2.13",
                "multiplePeriodsUsed",
                "error",
                f"All periods must be the same reference date; the report uses "
                f"{len(dates)} ({shown}).",
                self._label,
            )
        for context_id in [c for c in self._contexts if c not in used_contexts]:
            self._filing.add(
                "2.7",
                "unusedContext",
                "warning",
                "The report should not contain contexts that no fact uses.",
                f"{self._label}#{context_id}",
            )
        for unit_id in [u for u in self._units if u not in used_units]:
            self._filing.add(
                "2.22",
                "unusedUnit",
                "warning",
                "The report should not contain units that no fact uses.",
                f"{self._label}#{unit_id}",
            )
        self._check_namespaces()

    def _check_namespaces(self) -> None:
        """Check namespace declarations (rules 3.4 and 3.10)."""
        unused = sorted(
            prefix or "(default)"
            for prefix, uri in self._root_prefixes.items()
            if uri not in self._used
        )
        for prefix in unused:
            self._filing.add(
                "3.4",
                "unusedNamespacePrefix",
                "warning",
                "The report should not declare namespace prefixes it does not use.",
                f"{self._label}: {prefix}",
            )
        for uri, prefixes in self._declared.items():
            if len(prefixes) > 1:
                shown = ", ".join(sorted(prefix or "(default)" for prefix in prefixes))
                self._filing.add(
                    "3.10",
                    "multiplePrefixForNamespace",
                    "warning",
                    "Each namespace should have one prefix.",
                    f"{self._label}: {uri} as {shown}",
                )
