"""Neutral fact model shared by the xBRL-CSV and XBRL-XML adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

ReportFormat = Literal["xbrl-csv", "xbrl-xml"]
Severity = Literal["error", "warning"]
"""``error`` for a "MUST" filing rule (the report is rejected), ``warning``
for a "SHOULD" rule."""


class ReportError(ValueError):
    """Raised when a report cannot be read or written safely.

    Every unreadable, unsafe or over-limit input raises it, with a message
    that names the file and, where known, the line or entry.

    Attributes:
        problems: Every problem found, one message each; an error about a
            single problem holds its own message.

    Examples:
        >>> from dpmxbrl import ReportError, read_report
        >>> try:
        ...     read_report("missing.zip")
        ... except ReportError as error:
        ...     print(error)
        missing.zip: no such file or directory

    """

    def __init__(self, message: str, *, problems: Sequence[str] = ()) -> None:
        """Create an error with a message and, optionally, all its problems."""
        super().__init__(message)
        self.problems: tuple[str, ...] = tuple(problems) or (message,)

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle with the problems.

        Returns:
            tuple: The class, its message and the problems as state.
        """
        return (type(self), (str(self),), {"problems": self.problems})


@dataclass(frozen=True, slots=True)
class Limits:
    """Resource limits applied while reading untrusted report input.

    Attributes:
        max_zip_entries: Maximum number of entries in a report package ZIP.
        max_total_size: Maximum total uncompressed size of a report package.
        max_file_size: Maximum uncompressed size of one file, including an
            XBRL-XML instance document.
        max_facts: Maximum number of facts in one report.
        max_extends_depth: Maximum nesting depth of xBRL-CSV ``extends``.

    Examples:
        >>> from dataclasses import replace
        >>> from dpmxbrl import Limits, ReportError, read_report
        >>> try:
        ...     read_report("report.zip", limits=replace(Limits(), max_facts=10))
        ... except ReportError as error:
        ...     print(error)
        reports/c_28.00.csv:2: report exceeds the limit of 10 facts
    """

    max_zip_entries: int = 10_000
    max_total_size: int = 2 * 1024**3
    max_file_size: int = 512 * 1024**2
    max_facts: int = 20_000_000
    max_extends_depth: int = 32


@dataclass(frozen=True, slots=True)
class Fact:
    """One reported fact independent of its serialization.

    Attributes:
        value: Lexical value as written; ``None`` when the fact is nil.
        concept: Prefixed concept qname such as ``eba_met:qABJ``. xBRL-CSV
            facts carry it only when table metadata was resolved.
        datapoint: xBRL-CSV datapoint code such as ``dp84817``.
        template: xBRL-CSV table template identifier; ``None`` for XML.
        dimensions: Explicit dimension qname to member qname.
        typed_dimensions: Typed dimension qname to typed value text.
        keys: xBRL-CSV non-fact column name to cell value, in header order.
        unit: Unit such as ``iso4217:EUR`` or ``a/b`` for a divide unit.
        decimals: Decimals accuracy; ``None`` means INF or unspecified.
        location: Source location, ``reports/x.csv:3`` (the 1-based
            physical line) or ``file.xbrl#id`` (``#factN`` for the Nth fact
            without an id).

    The mappings of facts that are read are read-only and may be shared
    between facts; copy one with ``dict()`` to change it.

    Examples:
        >>> from dpmxbrl import read_report
        >>> fact = read_report("report.zip").facts_for_template("C_27.00")[0]
        >>> fact.datapoint, fact.value
        ('dp5486584', 'Northwind Holdings')
        >>> dict(fact.keys)
        {'qINC': 'CP0001', 'qNCO': 'eba_qCO:qx2000'}
        >>> fact.location
        'reports/c_27.00.csv:2'
    """

    value: str | None
    concept: str | None = None
    datapoint: str | None = None
    template: str | None = None
    dimensions: Mapping[str, str] = field(default_factory=dict)
    typed_dimensions: Mapping[str, str] = field(default_factory=dict)
    keys: Mapping[str, str] = field(default_factory=dict)
    unit: str | None = None
    decimals: int | None = None
    location: str = ""


@dataclass(frozen=True, slots=True)
class FilingFinding:
    """One EBA filing rule a report breaks, with how often and where.

    Attributes:
        rule: The rule's number, a key of :data:`dpmxbrl.filing.RULE_TITLES`.
        code: The rule's tag in the EBA document, such as ``nilUsed``.
        severity: ``error`` when the rule says MUST, ``warning`` for SHOULD.
        message: What is wrong and what the rule requires, as a sentence.
        count: How many times the report breaks it.
        examples: Up to five locations, such as ``report.xbrl#f12``.

    ``rule`` and ``code`` are stable across releases; ``message`` may be
    reworded in a minor release.
    """

    rule: str
    code: str
    severity: Severity
    message: str
    count: int = 1
    examples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Report:
    """One regulatory report read from xBRL-CSV or XBRL-XML.

    Attributes:
        format: Serialization the report was read from.
        entry_point: Taxonomy entry point (``extends[0]`` or ``schemaRef``).
        entity_scheme: Entity identifier scheme URI, or the CSV prefix when
            no namespace declares it.
        entity_id: Entity identifier without scheme.
        reference_date: Reference date (CSV ``refPeriod``; XML instant/end).
        base_currency: Base currency unit such as ``iso4217:EUR``.
        parameters: xBRL-CSV report parameters; empty for XML.
        decimals_parameters: xBRL-CSV ``decimals*`` parameters; ``None`` for
            ``#none``/``INF``.
        filing_indicators: Template code to whether it was reported.
        facts: Reported facts in source order.
        namespaces: Prefix to namespace URI.
        warnings: Non-fatal findings in deterministic order.
        filing: EBA filing rules the report breaks that the file alone
            shows (see :mod:`dpmxbrl.filing`), in rule order.
    """

    format: ReportFormat
    entry_point: str | None
    entity_scheme: str | None
    entity_id: str | None
    reference_date: date | None
    base_currency: str | None
    parameters: Mapping[str, str]
    decimals_parameters: Mapping[str, int | None]
    filing_indicators: Mapping[str, bool]
    facts: tuple[Fact, ...]
    namespaces: Mapping[str, str]
    warnings: tuple[str, ...] = ()
    filing: tuple[FilingFinding, ...] = ()

    def facts_for_template(self, code: str) -> tuple[Fact, ...]:
        """Select facts reported in one xBRL-CSV table template.

        Template codes compare case-insensitively, so filing-indicator codes
        such as ``C_01.00`` match table templates such as ``c_01.00``. Letter
        parts are not dropped: ``C_07.00`` does not match ``c_07.00.a``.
        XML facts have no template, so nothing matches in an XML report.

        Args:
            code: Template code, such as ``C_27.00`` or ``c_07.00.a``.

        Returns:
            tuple[Fact, ...]: Matching facts in source order.

        Examples:
            >>> from dpmxbrl import read_report
            >>> report = read_report("report.zip")
            >>> [fact.value for fact in report.facts_for_template("C_28.00")]
            ['67129000', '60309000', '41250000', '38900000']
        """
        wanted = code.casefold()
        return tuple(
            fact
            for fact in self.facts
            if fact.template is not None and fact.template.casefold() == wanted
        )


def local_name(qname: str) -> str:
    """Return the local part of a prefixed or Clark-notation qname.

    Args:
        qname: A qname such as ``eba_met:mi53`` or ``{namespace}mi53``.

    Returns:
        str: Text after the last ``}`` or the first ``:``; a name without
        either is returned as is.

    Examples:
        >>> from dpmxbrl import local_name
        >>> local_name("eba_met:mi53"), local_name("{http://example.com/met}mi53")
        ('mi53', 'mi53')
    """
    if qname.startswith("{"):
        return qname.rpartition("}")[2]
    return qname.partition(":")[2] or qname
