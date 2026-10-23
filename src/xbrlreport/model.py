"""Neutral fact model shared by the xBRL-CSV and XBRL-XML adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

ReportFormat = Literal["xbrl-csv", "xbrl-xml"]
Severity = Literal["error", "warning"]
"""``error`` for a "MUST" filing rule (the report is rejected), ``warning``
for a "SHOULD" rule."""


class ReportError(ValueError):
    """Raised when a report cannot be read or written safely."""


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
        location: Source location, ``reports/x.csv:3`` or ``file.xbrl#id``.
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
        rule: The rule's number, a key of :data:`xbrlreport.filing.RULE_TITLES`.
        code: The rule's tag in the EBA document, such as ``nilUsed``.
        severity: ``error`` when the rule says MUST, ``warning`` for SHOULD.
        message: What is wrong and what the rule requires, as a sentence.
        count: How many times the report breaks it.
        examples: Up to five locations, such as ``report.xbrl#f12``.
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
            shows (see :mod:`xbrlreport.filing`), in rule order.
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
        such as ``C_01.00`` match table templates such as ``c_01.00``.

        Returns:
            tuple[Fact, ...]: Matching facts in source order.
        """
        wanted = code.casefold()
        return tuple(
            fact
            for fact in self.facts
            if fact.template is not None and fact.template.casefold() == wanted
        )


def local_name(qname: str) -> str:
    """Return the local part of a prefixed or Clark-notation qname.

    Returns:
        str: Text after the last ``}`` or the first ``:``.
    """
    if qname.startswith("{"):
        return qname.rpartition("}")[2]
    return qname.partition(":")[2] or qname
