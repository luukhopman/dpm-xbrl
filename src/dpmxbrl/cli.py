"""Command-line interface for inspecting and converting reports."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from ._version import __version__
from .filing import RULE_TITLES
from .model import Limits, Report, ReportError
from .reader import detect_format, read_report
from .writer import write_xbrl_csv, write_xbrl_xml

FAILED_FILING_RULES = 3
"""Exit status of ``inspect --fail-on`` when the report breaks a rule."""

_LIMIT_OPTIONS = (
    ("facts", "--max-facts"),
    ("ZIP entries", "--max-zip-entries"),
    ("files in the package", "--max-zip-entries"),
    ("uncompressed size", "--max-total-size"),
    ("total size", "--max-total-size"),
    ("file size", "--max-file-size"),
)

JSON_SCHEMA_VERSION = 1
"""Version of the ``inspect --json`` layout; it changes only with a new major."""


def _summary(
    report: Report, templates: Mapping[str, int] | None = None
) -> dict[str, Any]:
    if templates is None:
        templates = Counter(fact.template or "(none)" for fact in report.facts)
    reported = sum(1 for value in report.filing_indicators.values() if value)
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "format": report.format,
        "entry_point": report.entry_point,
        "entity_scheme": report.entity_scheme,
        "entity_id": report.entity_id,
        "reference_date": (
            report.reference_date.isoformat() if report.reference_date else None
        ),
        "base_currency": report.base_currency,
        "filing_indicators": {
            "reported": reported,
            "total": len(report.filing_indicators),
            "templates": dict(report.filing_indicators),
        },
        "fact_count": sum(templates.values()),
        "facts_per_template": dict(sorted(templates.items())),
        "warnings": list(report.warnings),
        "filing_rules": [
            {
                "rule": item.rule,
                "title": RULE_TITLES.get(item.rule, item.rule),
                "code": item.code,
                "severity": item.severity,
                "message": item.message,
                "count": item.count,
                "examples": list(item.examples),
            }
            for item in report.filing
        ],
    }


def _print_summary(summary: dict[str, Any]) -> None:
    entity = summary["entity_id"] or "-"
    if summary["entity_scheme"]:
        entity = f"{entity} ({summary['entity_scheme']})"
    indicators = summary["filing_indicators"]
    rows = [
        ("Format", summary["format"]),
        ("Entry point", summary["entry_point"] or "-"),
        ("Entity", entity),
        ("Reference date", summary["reference_date"] or "-"),
        ("Base currency", summary["base_currency"] or "-"),
        (
            "Filing indicators",
            f"{indicators['reported']} reported of {indicators['total']}",
        ),
        ("Facts", str(summary["fact_count"])),
    ]
    width = max(len(label) for label, _ in rows) + 1
    for label, value in rows:
        print(f"{label + ':':<{width}} {value}")
    per_template = summary["facts_per_template"]
    if per_template and list(per_template) != ["(none)"]:
        name_width = max(len(name) for name in per_template)
        for name, count in per_template.items():
            print(f"  {name:<{name_width}}  {count}")
    warnings = summary["warnings"]
    print(f"Warnings: {len(warnings)}")
    for warning in warnings:
        print(f"  - {warning}")
    findings = summary["filing_rules"]
    errors = sum(1 for item in findings if item["severity"] == "error")
    print(
        f"EBA filing rules broken: {errors} must be fixed, "
        f"{len(findings) - errors} recommended"
    )
    for item in findings:
        times = f" ({item['count']} times)" if item["count"] > 1 else ""
        print(f"  - [{item['severity']}] {item['rule']} {item['message']}{times}")


def _typed_domains(values: Sequence[str]) -> dict[str, str]:
    """Parse ``DIMENSION=ELEMENT`` options.

    Returns:
        dict[str, str]: Typed dimension qname to typed domain element qname.

    Raises:
        ReportError: If an option is not of the form ``DIMENSION=ELEMENT``.
    """
    result: dict[str, str] = {}
    for value in values:
        dimension, separator, element = value.partition("=")
        if not separator or not dimension or not element:
            raise ReportError(
                f"--typed-domain expects DIMENSION=ELEMENT, got {value!r}"
            )
        result[dimension] = element
    return result


_EPILOG = """examples:
  dpm-xbrl inspect report.zip
  dpm-xbrl inspect instance.xbrl --json
  dpm-xbrl inspect report.zip --fail-on error
  dpm-xbrl convert report.zip instance.xbrl --taxonomy-package taxonomy.zip"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dpm-xbrl",
        description="Inspect and convert EBA xBRL-CSV and XBRL-XML reports.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser(
        "inspect", help="summarize a report and the EBA filing rules it breaks"
    )
    inspect.add_argument(
        "path", type=Path, help="report package (.zip), directory or XML instance"
    )
    inspect.add_argument("--json", action="store_true", help="print JSON")
    inspect.add_argument(
        "--columnar",
        action="store_true",
        help="count xBRL-CSV facts with polars: seconds instead of minutes for "
        "millions of facts, checking special fact values only (frames extra)",
    )
    inspect.add_argument(
        "--fail-on",
        choices=("error", "warning"),
        help="exit with status 3 when the report breaks a filing rule of this "
        "severity or worse",
    )
    convert = commands.add_parser(
        "convert", help="convert a report (.zip -> xBRL-CSV, .xbrl/.xml -> XML)"
    )
    convert.add_argument("input", type=Path, help="report to read")
    convert.add_argument("output", type=Path, help="file to write")
    convert.add_argument(
        "--typed-domain",
        action="append",
        default=[],
        metavar="DIMENSION=ELEMENT",
        help="typed domain element for a typed dimension (XML output)",
    )
    convert.add_argument("--root", help="top-level folder name (xBRL-CSV output)")
    for command in (inspect, convert):
        limits = command.add_argument_group(
            "limits",
            "resource limits for untrusted input (defaults in the documentation)",
        )
        for option, help_text in (
            ("--max-file-size", "largest uncompressed file, in bytes"),
            ("--max-total-size", "largest uncompressed package, in bytes"),
            ("--max-zip-entries", "most entries in a package"),
            ("--max-facts", "most facts in a report"),
        ):
            limits.add_argument(option, type=_positive, metavar="N", help=help_text)
        command.add_argument(
            "--taxonomy-package",
            action="append",
            default=[],
            type=Path,
            metavar="ZIP",
            help="local taxonomy package used to resolve xBRL-CSV metadata",
        )
    return parser


def _positive(text: str) -> int:
    try:
        value = int(text.replace("_", ""))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be positive: {text!r}")
    return value


def _limits(arguments: argparse.Namespace) -> Limits:
    overrides = {
        name: getattr(arguments, name)
        for name in ("max_file_size", "max_total_size", "max_zip_entries", "max_facts")
        if getattr(arguments, name) is not None
    }
    return replace(Limits(), **overrides)


def _inspected(
    arguments: argparse.Namespace,
) -> tuple[Report, Mapping[str, int] | None]:
    """Read a report for inspect, columnar with ``--columnar``.

    Counting the facts of a large xBRL-CSV package from polars frames takes
    seconds where building every fact takes minutes, but checks special fact
    values only (see the frames module), and needs the frames extra.

    Returns:
        tuple: The report and its fact count per template, or ``None`` when
        the report's facts hold them.

    Raises:
        ReportError: If ``--columnar`` is used without the frames extra.
    """
    limits = _limits(arguments)
    if arguments.columnar and detect_format(arguments.path) == "xbrl-csv":
        if not find_spec("polars"):
            raise ReportError("--columnar needs the frames extra: dpm-xbrl[frames]")
        from .frames import MetadataTablesError, read_xbrl_csv_frames

        try:
            frames = read_xbrl_csv_frames(
                arguments.path,
                taxonomy_packages=arguments.taxonomy_package,
                limits=limits,
            )
        except MetadataTablesError:
            pass
        else:
            print(
                "note: --columnar checks special fact values only; key values and "
                "decimals suffixes are not checked",
                file=sys.stderr,
            )
            counts = {
                name: frame.height
                for name, frame in frames.tables.items()
                if frame.height
            }
            return frames.report, dict(sorted(counts.items()))
        print(
            "note: --columnar does not apply to tables described by metadata; "
            "reading every fact",
            file=sys.stderr,
        )
    elif arguments.columnar:
        print("note: --columnar applies to xBRL-CSV only", file=sys.stderr)
    report = read_report(
        arguments.path, taxonomy_packages=arguments.taxonomy_package, limits=limits
    )
    return report, None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``dpm-xbrl`` command.

    Returns:
        int: Process exit status: 1 when the report cannot be processed, 3
        when ``inspect --fail-on`` finds a filing rule broken (argparse uses 2
        for usage errors).
    """
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "inspect":
            report, templates = _inspected(arguments)
            summary = _summary(report, templates)
            if arguments.json:
                print(json.dumps(summary, indent=2, ensure_ascii=False))
            else:
                _print_summary(summary)
            failing = (
                {"error"} if arguments.fail_on == "error" else {"error", "warning"}
            )
            broken = arguments.fail_on and any(
                item.severity in failing for item in report.filing
            )
            return FAILED_FILING_RULES if broken else 0
        suffix = arguments.output.suffix.casefold()
        if suffix not in {".zip", ".xbrl", ".xml"}:
            print(
                f"error: {arguments.output}: output must end in .zip, .xbrl or .xml",
                file=sys.stderr,
            )
            return 1
        typed_domains = _typed_domains(arguments.typed_domain)
        report = read_report(
            arguments.input,
            taxonomy_packages=arguments.taxonomy_package,
            limits=_limits(arguments),
        )
        for warning in report.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if suffix == ".zip":
            write_xbrl_csv(report, arguments.output, root=arguments.root)
        else:
            write_xbrl_xml(report, arguments.output, typed_domains=typed_domains)
    except (ReportError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        message = str(error)
        if "limit" in message or "maximum" in message:
            option = next(
                (option for word, option in _LIMIT_OPTIONS if word in message), None
            )
            if option:
                print(f"hint: {option} raises the limit", file=sys.stderr)
        return 1
    return 0
