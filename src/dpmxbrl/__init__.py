r"""Read and write EBA-style xBRL-CSV and XBRL-XML regulatory reports.

The readers return a :class:`Report` with its facts (:class:`Fact`) and the EBA
filing rules the report breaks; the writers take a :class:`Report`.

Examples:
    >>> from dpmxbrl import read_report
    >>> report = read_report("report.zip")
    >>> report.format, report.entity_id, len(report.facts)
    ('xbrl-csv', 'SYNTHETICDPMXL000002.CON', 14)
"""

from ._version import __version__
from .csv_reader import read_xbrl_csv
from .model import (
    Fact,
    FilingFinding,
    Limits,
    Report,
    ReportError,
    ReportFormat,
    Severity,
    SkippedFact,
    SkippedFacts,
    filing_indicator_code,
    local_name,
)
from .reader import detect_format, read_report
from .writer import (
    EntryPointWarning,
    default_package_root,
    write_xbrl_csv,
    write_xbrl_xml,
)
from .xml_reader import read_xbrl_xml

__all__ = [
    "EntryPointWarning",
    "Fact",
    "FilingFinding",
    "Limits",
    "Report",
    "ReportError",
    "ReportFormat",
    "Severity",
    "SkippedFact",
    "SkippedFacts",
    "__version__",
    "default_package_root",
    "detect_format",
    "filing_indicator_code",
    "local_name",
    "read_report",
    "read_xbrl_csv",
    "read_xbrl_xml",
    "write_xbrl_csv",
    "write_xbrl_xml",
]
