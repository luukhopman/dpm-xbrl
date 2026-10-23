"""EBA filing rules: checks on how a report is written, before its values.

The EBA Filing Rules (version 5.8, 25 February 2026) constrain the report
file itself: one entity and reference date, filing indicators, decimals,
units, file naming, and constructs that must not appear. A report that
breaks a "MUST" rule is rejected however good its values are; "SHOULD"
rules are recommendations.

The readers record a :class:`FilingFinding` for each rule a report breaks
that can be judged from the file alone. Rules that need the taxonomy, such
as which templates a module has or a data point's data type, are left to
callers, which can build findings with the same classes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from .model import FilingFinding, Report, Severity

RULE_TITLES: dict[str, str] = {
    "1.4": "Character encoding",
    "1.5": "Taxonomy entry point",
    "1.6": "Filing indicators",
    "1.6.1": "One filing indicator per template",
    "1.6.3": "Filing indicator codes",
    "1.7": "Templates indicated as reported",
    "1.7.1": "Facts outside the reported templates",
    "1.9": "Valid XBRL",
    "1.13": "Standalone declaration",
    "1.14": "Schema location attributes",
    "1.15": "XInclude",
    "2.1": "xml:base",
    "2.2": "Absolute entry point URL",
    "2.3": "One taxonomy reference",
    "2.4": "Linkbase references",
    "2.7": "Unused or duplicated contexts",
    "2.8": "Reporting subject identification",
    "2.9": "One reporting subject",
    "2.10": "Reference date format",
    "2.11": "xbrli:forever",
    "2.13": "Period consistency",
    "2.14": "xbrli:segment",
    "2.15": "Scenario content",
    "2.16": "Duplicate facts",
    "2.16.1": "Facts differing only by unit",
    "2.17": "Precision attribute",
    "2.18": "Decimals",
    "2.19": "Nil and empty values",
    "2.21": "Duplicated units",
    "2.22": "Unused units",
    "2.25": "Footnotes",
    "3.1": "Currency of monetary facts",
    "3.2": "Non-monetary units",
    "3.4": "Unused namespace prefixes",
    "3.6": "Reporting subject",
    "3.9": "Namespace declarations",
    "3.10": "One prefix per namespace",
    "3.11": "Leading or trailing spaces",
    "Package": "xBRL-CSV report package",
    "File naming": "File naming",
    "xBRL-CSV 1": "Decimals suffix",
    "xBRL-CSV 2": "Header row",
    "xBRL-CSV 4": "Key column values",
    "xBRL-CSV 5": "Special values",
    "xBRL-CSV 6": "Tables of templates not reported",
}
"""Each rule's number in the EBA Filing Rules and a short title.

Numbered rules come from sections 1 to 3. ``Package`` and ``File naming``
are the requirements in "File naming structure for remittance to the EBA";
``xBRL-CSV n`` are the numbered "xBRL-CSV reports extra rules"."""

Rule = tuple[str, str, Severity, str]
"""A finding's rule number, tag, severity and message, for :meth:`FilingLog.add`."""

# Findings on xBRL-CSV fact and key values, made by the readers here and by
# callers that check values the columnar reader leaves to them.
NIL_VALUE: Rule = (
    "2.19",
    "nilUsed",
    "error",
    "Facts must not be reported as #nil; leave out a fact that is not reported.",
)
EMPTY_VALUE: Rule = (
    "2.19",
    "emptyUsed",
    "error",
    "Facts must not be reported as #empty; such values were skipped.",
)
SPECIAL_VALUE: Rule = (
    "xBRL-CSV 5",
    "specialValueUsed",
    "error",
    "Fact values must not use special values starting with # (#none, #empty, "
    "#nil or others).",
)
SPECIAL_KEY_VALUE: Rule = (
    "xBRL-CSV 5",
    "specialKeyValueUsed",
    "error",
    "Key columns must not use special values starting with #.",
)
DECIMALS_SUFFIX: Rule = (
    "xBRL-CSV 1",
    "decimalsSuffixUsed",
    "error",
    "Fact values must not use the decimals suffix (such as 78920030d-4); "
    "decimals belong in parameters.csv.",
)
SPACES: Rule = (
    "3.11",
    "leadingOrTrailingSpacesInText",
    "warning",
    "Fact values should not start or end with spaces or line breaks.",
)
"""Rule 3.11 for fact values, which applies to string data points only.

The readers do not know data types, so they leave this check to callers
that do; they check key values (:data:`KEY_SPACES`) themselves."""
KEY_SPACES: Rule = (
    "3.11",
    "leadingOrTrailingSpacesInText",
    "warning",
    "Key values should not start or end with spaces or line breaks.",
)


_EXAMPLES = 5
_LEI_SCHEME = "http://standards.iso.org/iso/17442"
_LEI_SCHEME_TYPO = "http://standard.iso.org/iso/17442"
_REPORTING_SUBJECT_SCHEME = "https://eurofiling.info/eu/rs"
# Suffixes of a reporting subject under the reporting-subject scheme (3.6).
_ENTITY_SUFFIXES = frozenset({"IND", "CON", "CRDLIQSUBGRP"})
_AGGREGATE_SUFFIXES = frozenset(
    {
        "AUTALL",
        "MEMSTAAGGALL",
        "MEMSTAAGGCRDCREINS",
        "MEMSTAAGGINVFIR",
    }
)
# Reports from this reference date onwards carry a suffix, unless their
# module is a _con or _ind module (3.6).
_SUFFIX_FROM = date(2022, 12, 31)
_LEI = re.compile(r"[0-9A-Z]{18}[0-9]{2}")
_FILE_NAME = re.compile(
    r"(?P<subject>[^_]+)_(?P<country>[^_]+)_(?P<framework>[^_]+)_"
    r"(?P<module>[^_]+)_(?P<date>[^_]+)_(?P<timestamp>[^_]+)"
)


class FilingLog:
    """Collect findings, counting repeats of the same finding."""

    def __init__(self) -> None:
        """Create an empty log."""
        self._found: dict[
            tuple[str, str, str], tuple[Severity, list[str], list[int]]
        ] = {}

    def add(
        self,
        rule: str,
        code: str,
        severity: Severity,
        message: str,
        location: str | None = None,
        *,
        count: int = 1,
    ) -> None:
        """Record ``count`` occurrences of a finding, keeping a few locations.

        A location already kept for the finding is not kept again.
        """
        if count <= 0:
            return
        entry = self._found.get((rule, code, message))
        if entry is None:
            entry = self._found[rule, code, message] = (severity, [], [0])
        _, examples, total = entry
        total[0] += count
        if location is not None:
            _keep(examples, (location,))

    def extend(self, findings: Iterable[FilingFinding]) -> None:
        """Record findings made elsewhere, keeping each location once."""
        for finding in findings:
            entry = self._found.get((finding.rule, finding.code, finding.message))
            if entry is None:
                entry = self._found[finding.rule, finding.code, finding.message] = (
                    finding.severity,
                    [],
                    [0],
                )
            _, examples, total = entry
            total[0] += finding.count
            _keep(examples, finding.examples)

    def result(self) -> tuple[FilingFinding, ...]:
        """Return the findings in rule order.

        Returns:
            tuple[FilingFinding, ...]: One finding per rule, tag and message.
        """
        return sort_findings(
            FilingFinding(rule, code, severity, message, total[0], tuple(examples))
            for (rule, code, message), (
                severity,
                examples,
                total,
            ) in self._found.items()
        )


def _keep(examples: list[str], locations: Iterable[str]) -> None:
    """Append new locations to a finding's examples, up to the limit."""
    for location in locations:
        if len(examples) >= _EXAMPLES:
            return
        if location not in examples:
            examples.append(location)


def sort_findings(findings: Iterable[FilingFinding]) -> tuple[FilingFinding, ...]:
    """Order findings by rule number, then the annex requirements.

    Returns:
        tuple[FilingFinding, ...]: The findings in document order.
    """
    return tuple(sorted(findings, key=lambda item: (_rule_order(item.rule), item.code)))


def _rule_order(rule: str) -> tuple[int, ...]:
    if re.fullmatch(r"\d+(\.\d+)*", rule):
        return (0, *map(int, rule.split(".")))
    if rule.startswith("xBRL-CSV "):
        return (1, int(rule.removeprefix("xBRL-CSV ")))
    return (2, list(RULE_TITLES).index(rule) if rule in RULE_TITLES else 99)


def check_subject(report: Report, log: FilingLog) -> None:
    """Check the reporting subject's scheme and identifier (rules 2.8 and 3.6).

    The EBA prescribes two schemes: the LEI scheme for a bare LEI, and the
    reporting-subject scheme for an identifier with a suffix such as
    ``.CON``. Reports from 31 December 2022 onwards must use a suffix
    unless their module name ends in ``_con`` or ``_ind``. A suffix the
    EBA does not list is a warning: other codes are agreed with the EBA.
    """
    scheme, identifier = report.entity_scheme, report.entity_id
    if not identifier:
        log.add(
            "2.8",
            "missingIdentifier",
            "error",
            "The report does not identify its reporting subject.",
        )
        return
    where = f"{scheme} {identifier}" if scheme else identifier
    if identifier != identifier.upper():
        log.add(
            "3.6",
            "reportingSubjectNotUppercase",
            "error",
            f"The reporting subject {identifier} must be written in upper case.",
            where,
        )
    if scheme == _LEI_SCHEME_TYPO:
        log.add(
            "3.6",
            "incorrectLeiScheme",
            "warning",
            f"The LEI scheme is written {_LEI_SCHEME_TYPO}; the correct form is "
            f"{_LEI_SCHEME}.",
            where,
        )
        scheme = _LEI_SCHEME
    base, dot, suffix = identifier.upper().rpartition(".")
    if not dot:
        base, suffix = identifier.upper(), ""
    if scheme == _LEI_SCHEME:
        if suffix:
            log.add(
                "3.6",
                "inappropriateScheme",
                "error",
                f"The reporting subject {identifier} has a suffix, so its scheme "
                f"must be {_REPORTING_SUBJECT_SCHEME}, not the LEI scheme.",
                where,
            )
        _check_lei(base, identifier, where, log)
    elif scheme == _REPORTING_SUBJECT_SCHEME:
        if not suffix:
            log.add(
                "3.6",
                "inappropriateScheme",
                "error",
                f"The reporting subject {identifier} has no suffix such as .CON or "
                f".IND, so its scheme must be the LEI scheme {_LEI_SCHEME}.",
                where,
            )
        elif suffix not in _ENTITY_SUFFIXES | _AGGREGATE_SUFFIXES:
            log.add(
                "3.6",
                "unrecognizedReportingSubjectSuffix",
                "warning",
                f"The suffix .{suffix} of the reporting subject {identifier} is not "
                "one the EBA lists; other codes must be agreed with and "
                "preregistered by the EBA.",
                where,
            )
        elif suffix in _ENTITY_SUFFIXES and "-" not in base:
            # IssuerID-TokenID (MiCA) identifiers are not LEIs.
            _check_lei(base, identifier, where, log)
    else:
        log.add(
            "2.8",
            "inappropriateScheme",
            "warning",
            f"The entity scheme {scheme or '(none)'} is not one the EBA prescribes "
            f"({_LEI_SCHEME} or {_REPORTING_SUBJECT_SCHEME}); confirm it with "
            "the supervisor.",
            where,
        )
        return
    module = _module_file(report.entry_point)
    expects_suffix = (
        report.reference_date is not None
        and report.reference_date >= _SUFFIX_FROM
        and not module.endswith(("_con", "_ind"))
    )
    if expects_suffix and scheme == _LEI_SCHEME and not suffix:
        log.add(
            "3.6",
            "missingReportingSubjectSuffix",
            "error",
            "From 31 December 2022 the reporting subject must end in .IND, .CON "
            "or another suffix, with the reporting-subject scheme.",
            where,
        )
    elif not expects_suffix and suffix in _ENTITY_SUFFIXES - {"CRDLIQSUBGRP"}:
        log.add(
            "3.6",
            "unexpectedReportingSubjectSuffix",
            "warning",
            "Before 31 December 2022, and for _con and _ind modules, the reporting "
            "subject should be the bare LEI with the LEI scheme.",
            where,
        )


def _check_lei(base: str, identifier: str, where: str, log: FilingLog) -> None:
    if _LEI.fullmatch(base) and _lei_checksum_valid(base):
        return
    log.add(
        "2.8",
        "unacceptableIdentifier",
        "error",
        f"{base} in the reporting subject {identifier} is not a valid LEI "
        "(20 characters ending in two check digits, ISO 17442).",
        where,
    )


def _lei_checksum_valid(lei: str) -> bool:
    """Return whether an LEI's check digits are right (ISO 7064 MOD 97-10)."""
    digits = "".join(str(int(character, 36)) for character in lei)
    return int(digits) % 97 == 1


def check_file_name(name: str, report: Report, log: FilingLog) -> None:
    """Check a report file's name against the EBA naming structure.

    The structure, ``ReportSubject_Country_FrameworkCodeModuleVersion_
    Module_ReferenceDate_CreationTimestamp``, is the one competent
    authorities use when they send reports to the EBA; reporters confirm
    their own with their supervisor, so mismatches are warnings.
    """
    stem = re.sub(
        r"\.(zip|xbrl|xml)$", "", name.rsplit("/", 1)[-1], flags=re.IGNORECASE
    )
    match = _FILE_NAME.fullmatch(stem)
    if match is None:
        log.add(
            "File naming",
            "invalidFileName",
            "warning",
            "The file name does not follow ReportSubject_Country_"
            "FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, "
            "the structure for reports sent to the EBA.",
            name,
        )
        return
    parts = match.groupdict()
    problems: list[str] = []
    if report.entity_id and parts["subject"] != report.entity_id:
        problems.append(
            f"the reporting subject {parts['subject']} is not {report.entity_id}"
        )
    if not re.fullmatch(r"[A-Z]{2}", parts["country"]):
        problems.append(f"the country {parts['country']} is not an ISO country code")
    if not re.fullmatch(r"[A-Z][A-Z0-9]*\d{6}", parts["framework"]):
        problems.append(
            f"{parts['framework']} is not a framework code followed by a six-digit "
            "module version"
        )
    module = _module_file(report.entry_point).replace("_", "").upper()
    if not re.fullmatch(r"[A-Z0-9]+", parts["module"]):
        problems.append(
            f"the module {parts['module']} is not upper case without underscores"
        )
    elif module and parts["module"] != module:
        problems.append(f"the module {parts['module']} is not {module}")
    reference = report.reference_date.isoformat() if report.reference_date else None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts["date"]):
        problems.append(f"the reference date {parts['date']} is not YYYY-MM-DD")
    elif reference and parts["date"] != reference:
        problems.append(f"the reference date {parts['date']} is not {reference}")
    if not re.fullmatch(r"\d{17}", parts["timestamp"]):
        problems.append(
            f"the creation timestamp {parts['timestamp']} is not YYYYMMDDhhmmssfff"
        )
    for problem in problems:
        log.add(
            "File naming",
            "invalidFileName",
            "warning",
            f"In the file name, {problem}.",
            name,
        )


def _module_file(entry_point: str | None) -> str:
    """Return the entry point's file name without extension, in lower case."""
    if not entry_point:
        return ""
    name = re.split(r"[/\\]", entry_point.rstrip("/"))[-1]
    return re.sub(r"\.(json|xsd)$", "", name, flags=re.IGNORECASE).casefold()


def check_entry_point(
    entry_points: list[str], log: FilingLog, *, where: str, xml: bool
) -> None:
    """Check that one absolute entry point URL is referenced (1.5, 2.2, 2.3)."""
    element = "link:schemaRef" if xml else "documentInfo.extends"
    if not entry_points:
        log.add(
            "1.5",
            "inappropriateSchemaRef" if xml else "inappropriateTaxonomyRef",
            "error",
            f"The report names no taxonomy entry point ({element}).",
            where,
        )
        return
    if len(entry_points) > 1:
        log.add(
            "2.3",
            "multipleSchemaRefs" if xml else "multipleTaxonomyRefs",
            "error",
            f"The report must reference exactly one entry point; it references "
            f"{len(entry_points)} ({element}).",
            where,
        )
    for url in entry_points:
        if not re.match(r"https?://", url, flags=re.IGNORECASE):
            log.add(
                "2.2",
                "inappropriateSchemaRef" if xml else "inappropriateTaxonomyRef",
                "error",
                f"The entry point {url} must be the full published URL.",
                where,
            )


__all__ = [
    "DECIMALS_SUFFIX",
    "EMPTY_VALUE",
    "KEY_SPACES",
    "NIL_VALUE",
    "RULE_TITLES",
    "SPACES",
    "SPECIAL_KEY_VALUE",
    "SPECIAL_VALUE",
    "FilingFinding",
    "FilingLog",
    "Rule",
    "Severity",
    "check_entry_point",
    "check_file_name",
    "check_subject",
    "sort_findings",
]
