"""Command-line interface for inspecting and converting reports."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .model import Report, ReportError
from .reader import read_report
from .writer import write_xbrl_csv, write_xbrl_xml


def _summary(report: Report) -> dict[str, Any]:
    templates = Counter(fact.template or "(none)" for fact in report.facts)
    reported = sum(1 for value in report.filing_indicators.values() if value)
    return {
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
        "fact_count": len(report.facts),
        "facts_per_template": dict(sorted(templates.items())),
        "warnings": list(report.warnings),
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
    if per_template:
        name_width = max(len(name) for name in per_template)
        for name, count in per_template.items():
            print(f"  {name:<{name_width}}  {count}")
    warnings = summary["warnings"]
    print(f"Warnings: {len(warnings)}")
    for warning in warnings:
        print(f"  - {warning}")


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xbrl-report",
        description="Inspect and convert EBA xBRL-CSV and XBRL-XML reports.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="summarize a report")
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--json", action="store_true", help="print JSON")
    convert = commands.add_parser(
        "convert", help="convert a report (.zip -> xBRL-CSV, .xbrl/.xml -> XML)"
    )
    convert.add_argument("input", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument(
        "--typed-domain",
        action="append",
        default=[],
        metavar="DIMENSION=ELEMENT",
        help="typed domain element for a typed dimension (XML output)",
    )
    convert.add_argument("--root", help="top-level folder name (xBRL-CSV output)")
    for command in (inspect, convert):
        command.add_argument(
            "--taxonomy-package",
            action="append",
            default=[],
            type=Path,
            metavar="ZIP",
            help="local taxonomy package used to resolve xBRL-CSV metadata",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``xbrl-report`` command.

    Returns:
        int: Process exit status; 1 when the report cannot be processed.
    """
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "inspect":
            report = read_report(
                arguments.path, taxonomy_packages=arguments.taxonomy_package
            )
            summary = _summary(report)
            if arguments.json:
                print(json.dumps(summary, indent=2, ensure_ascii=False))
            else:
                _print_summary(summary)
            return 0
        suffix = arguments.output.suffix.casefold()
        if suffix not in {".zip", ".xbrl", ".xml"}:
            print(
                f"error: {arguments.output}: output must end in .zip, .xbrl or .xml",
                file=sys.stderr,
            )
            return 1
        typed_domains = _typed_domains(arguments.typed_domain)
        report = read_report(
            arguments.input, taxonomy_packages=arguments.taxonomy_package
        )
        for warning in report.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if suffix == ".zip":
            write_xbrl_csv(report, arguments.output, root=arguments.root)
        else:
            write_xbrl_xml(report, arguments.output, typed_domains=typed_domains)
    except (ReportError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
