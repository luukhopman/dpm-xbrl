"""EBA filing rules that need the taxonomy, checked with taxonomy packages."""

from __future__ import annotations

import posixpath
from collections.abc import Callable, Iterable, Mapping

from ._module import ModuleMetadata, load_module, module_json_url
from ._taxonomy import TaxonomyPackages
from .filing import FilingLog
from .model import Fact, Limits, Report, ReportError

_STANDARD_PREFIXES = {
    "http://www.xbrl.org/2003/instance": "xbrli",
    "http://www.xbrl.org/2003/linkbase": "link",
    "http://www.w3.org/1999/xlink": "xlink",
    "http://xbrl.org/2006/xbrldi": "xbrldi",
    "http://xbrl.org/2005/xbrldt": "xbrldt",
    "http://www.w3.org/2001/XMLSchema-instance": "xsi",
    "http://www.xbrl.org/2003/iso4217": "iso4217",
    "http://www.eurofiling.info/xbrl/ext/filing-indicators": "find",
}
"""Prefixes the XBRL specifications and the filing rules themselves use."""
_PERCENT_TYPE_NAMESPACE = "http://www.xbrl.org/dtr/type/"
PERCENT_LIMIT = 50
"""A percentage above this (5,000%) suggests percent notation (rule 3.2)."""


def check_with_taxonomy(
    report: Report,
    taxonomy: TaxonomyPackages,
    log: FilingLog,
    *,
    where: str,
    limits: Limits,
    warn: Callable[[str], None],
) -> ModuleMetadata | None:
    """Check the rules that need the module: 1.5, 1.6, 1.6.3, 3.2 and 3.5.

    Args:
        report: The report read so far; facts are checked if present.
        taxonomy: The open taxonomy packages.
        log: Where findings go.
        where: Location for report-level findings.
        limits: Resource limits for reading the packages.
        warn: Records a warning, such as a module that cannot be read.

    Returns:
        ModuleMetadata | None: The module's metadata, or ``None`` when the
        entry point is not a module of the packages.
    """
    xml = report.format == "xbrl-xml"
    entry_point = report.entry_point
    module = None
    if entry_point and _known_entry_point(entry_point, taxonomy.entry_points):
        try:
            module = load_module(taxonomy, entry_point, limits=limits)
        except ReportError as error:
            warn(
                f"{where}: the module's xBRL-CSV metadata could not be read "
                f"({error}); its reference dates, templates and filing "
                "indicator codes were not checked"
            )
    elif entry_point and taxonomy.entry_points:
        log.add(
            "1.5",
            "inappropriateSchemaRef" if xml else "inappropriateTaxonomyRef",
            "error",
            f"The entry point {entry_point} is not one the taxonomy packages publish.",
            where,
        )
    if module is not None:
        _check_validity(report, module, log, xml=xml, where=where)
        _check_filing_indicators(report, module, log, where=where)
    types = _ConceptTypes(report.namespaces, taxonomy)
    _check_percentages(report.facts, types, log)
    _check_decimals(report, types, module, log)
    if xml:
        check_prefixes(report.namespaces, taxonomy, log, where=where)
    return module


def _known_entry_point(url: str, published: frozenset[str]) -> bool:
    """Whether a report's entry point is published, as XSD or as its JSON.

    Returns:
        bool: ``True`` when it or its XSD/JSON sibling is listed, or when the
        packages list no entry points at all.
    """
    if not published:
        return True
    json_url = module_json_url(url)
    return (
        url in published
        or json_url in published
        or any(module_json_url(point) == json_url for point in published)
    )


def _check_validity(
    report: Report, module: ModuleMetadata, log: FilingLog, *, xml: bool, where: str
) -> None:
    """Check the reference date against the module's reference dates (1.5)."""
    when = report.reference_date
    if when is None or (module.valid_from is None and module.valid_to is None):
        return
    too_early = module.valid_from is not None and when < module.valid_from
    too_late = module.valid_to is not None and when > module.valid_to
    if not too_early and not too_late:
        return
    span = f"from {module.valid_from}" if module.valid_from else ""
    if module.valid_to:
        span = f"{span} to {module.valid_to}".strip()
    log.add(
        "1.5",
        "inappropriateSchemaRef" if xml else "inappropriateTaxonomyRef",
        "error",
        f"The module {posixpath.basename(module.url)} applies to reference dates "
        f"{span}; the report's reference date is {when}.",
        where,
    )


def _check_filing_indicators(
    report: Report, module: ModuleMetadata, log: FilingLog, *, where: str
) -> None:
    """Check filing indicator codes against the module's templates (1.6)."""
    codes: set[str] = set()
    for table in module.tables.values():
        documentation = (
            table.get("eba:documentation") if isinstance(table, dict) else None
        )
        if isinstance(documentation, dict):
            code = documentation.get("FilingIndicator")
            if isinstance(code, str) and code:
                codes.add(code)
    if not codes:
        return
    for code in report.filing_indicators:
        if code not in codes:
            log.add(
                "1.6.3",
                "invalidFilingIndicatorValue",
                "error",
                "Filing indicator codes must be those of the module's templates.",
                f"{where}: {code}",
            )
    missing = sorted(codes - set(report.filing_indicators))
    if missing and report.filing_indicators:
        log.add(
            "1.6",
            "missingFilingIndicators",
            "error",
            "The report must give a filing indicator, true or false, for each "
            "template of the module.",
            f"{where}: {', '.join(missing[:3])}"
            + (f" and {len(missing) - 3} more" if len(missing) > 3 else ""),
            count=len(missing),
        )


class _ConceptTypes:
    """Look up the schema type of each concept once."""

    def __init__(self, namespaces: Mapping[str, str], taxonomy: TaxonomyPackages):
        self._namespaces = namespaces
        self._taxonomy = taxonomy
        self._types: dict[str, str] = {}

    def __call__(self, concept: str) -> str:
        """Return the concept's type in Clark notation, or ``""``."""
        kind = self._types.get(concept)
        if kind is None:
            prefix, _, local = concept.partition(":")
            uri = self._namespaces.get(prefix)
            found = self._taxonomy.element(f"{{{uri}}}{local}") if uri else None
            kind = self._types[concept] = found[1].get("type", "") if found else ""
        return kind


def _is_percent(kind: str) -> bool:
    return kind.startswith("{" + _PERCENT_TYPE_NAMESPACE) and kind.endswith(
        "}percentItemType"
    )


def _check_percentages(
    facts: Iterable[Fact], types: _ConceptTypes, log: FilingLog
) -> None:
    """Flag percentages that look multiplied by 100 (rule 3.2 (b)).

    The metric's schema type tells percentages apart; only the value can
    suggest the notation, so the finding is a warning.
    """
    for fact in facts:
        if not fact.concept or not fact.value or not _is_percent(types(fact.concept)):
            continue
        try:
            number = abs(float(fact.value))
        except ValueError:
            continue
        if number > PERCENT_LIMIT:
            log.add(
                "3.2",
                "useDecimalFractions",
                "warning",
                "Percentages must be decimal fractions, 9.31% as 0.0931; a value "
                f"above {PERCENT_LIMIT} suggests one multiplied by 100.",
                fact.location,
            )


_MONETARY = "{http://www.xbrl.org/2003/instance}monetaryItemType"
_INTEGER = "{http://www.xbrl.org/2003/instance}integerItemType"
_COARSE_MONETARY_MODULES = ("/fws/fp/", "/fws/esg/", "/fws/pillar3/", "/rem_dbm.")
"""Modules whose monetary facts may be accurate to millions (2.18)."""


def _check_decimals(
    report: Report,
    types: _ConceptTypes,
    module: ModuleMetadata | None,
    log: FilingLog,
) -> None:
    """Check decimals against the accuracy requirements per data type (2.18).

    Monetary facts need decimals of at least -4 (-6 in the FP, ESG, Pillar 3
    and REM_DBM modules), percentages at least 4 and integers 0; INF is
    always accepted. The -3 that applied to submissions until 31 March 2025
    is not checked, as the file does not show when it is submitted.
    """
    url = module.url if module else report.entry_point or ""
    monetary = -6 if any(part in url for part in _COARSE_MONETARY_MODULES) else -4
    for fact in report.facts:
        if not fact.concept or fact.value is None or fact.decimals is None:
            continue
        kind = types(fact.concept)
        if kind == _MONETARY and fact.decimals < monetary:
            message = f"Monetary facts need decimals of {monetary} or more, or INF."
        elif _is_percent(kind) and fact.decimals < 4:
            message = "Percentages need decimals of 4 or more, or INF."
        elif kind == _INTEGER and fact.decimals != 0:
            message = "Integer facts need decimals 0, or INF."
        else:
            continue
        log.add(
            "2.18",
            "accuracyRequirements",
            "error",
            message,
            f"{fact.location}: decimals {fact.decimals}",
        )


def check_prefixes(
    namespaces: Mapping[str, str],
    taxonomy: TaxonomyPackages,
    log: FilingLog,
    *,
    where: str,
) -> None:
    """Compare namespace prefixes with their schema authors' prefixes (3.5).

    A namespace's canonical prefix is the one its schema in the taxonomy
    packages binds to its own target namespace, or for XBRL's own namespaces
    the prefix of the specifications. Other namespaces are not judged.
    """
    for prefix, uri in namespaces.items():
        if not prefix:
            continue
        canonical = _STANDARD_PREFIXES.get(uri)
        if canonical is None:
            schemas = taxonomy.schemas(uri)
            canonical = schemas[0].prefix if schemas else None
        if canonical is not None and prefix != canonical:
            log.add(
                "3.5",
                "notRecommendedNamespacePrefix",
                "warning",
                "Namespace prefixes should be those their schema authors use.",
                f"{where}: {prefix} for {uri} (expected {canonical})",
            )
        elif canonical is None and prefix in _STANDARD_PREFIXES.values():
            log.add(
                "3.5",
                "notRecommendedNamespacePrefix",
                "warning",
                "Namespace prefixes should be those their schema authors use.",
                f"{where}: {prefix} for {uri}, not its usual namespace",
            )
