"""Format detection for regulatory report input."""

from __future__ import annotations

import io
import os
import zipfile
from collections.abc import Sequence
from pathlib import Path

from .csv_reader import MetadataResolver, read_xbrl_csv
from .model import Limits, Report, ReportError, ReportFormat
from .xml_reader import read_xbrl_xml


def detect_format(
    source: str | os.PathLike[str] | bytes, *, name: str | None = None
) -> ReportFormat:
    """Detect whether input is an xBRL-CSV package or an XBRL-XML instance.

    ZIP archives, directories and ``.json`` metadata paths are xBRL-CSV;
    anything else is read as XBRL-XML. A ZIP is recognized by its content,
    whatever its suffix.

    Args:
        source: Bytes, a file path, or an xBRL-CSV package directory.
        name: Label used in messages instead of the path, such as the file
            name of uploaded bytes.

    Returns:
        ReportFormat: ``"xbrl-csv"`` or ``"xbrl-xml"``.

    Raises:
        ReportError: If a path does not exist or cannot be read, or if a
            ``.zip`` file or one starting like a ZIP archive cannot be read as
            one (it is incomplete or damaged; reading it as XML would only
            report malformed XML).

    Examples:
        >>> from dpmxbrl import detect_format
        >>> detect_format("report.zip"), detect_format("instance.xbrl")
        ('xbrl-csv', 'xbrl-xml')
    """
    if isinstance(source, bytes):
        if zipfile.is_zipfile(io.BytesIO(source)):
            return "xbrl-csv"
        if source.startswith(_ZIP_SIGNATURE):
            raise ReportError(_DAMAGED_ZIP.format(name=name or "the report"))
        return "xbrl-xml"
    path = Path(source).expanduser()
    if path.is_dir():
        return "xbrl-csv"
    if not path.is_file():
        raise ReportError(f"{path}: no such file or directory")
    if path.suffix.casefold() == ".json" or zipfile.is_zipfile(path):
        return "xbrl-csv"
    try:
        with path.open("rb") as handle:
            zip_like = handle.read(len(_ZIP_SIGNATURE)) == _ZIP_SIGNATURE
    except OSError as error:
        raise ReportError(f"{path}: cannot be read ({error.strerror})") from error
    if zip_like or path.suffix.casefold() == ".zip":
        raise ReportError(_DAMAGED_ZIP.format(name=name or path.name))
    return "xbrl-xml"


_ZIP_SIGNATURE = b"PK"
_DAMAGED_ZIP = "{name} is not a readable ZIP archive: it may be incomplete or damaged"


def read_report(
    source: str | os.PathLike[str] | bytes,
    *,
    name: str | None = None,
    metadata_resolver: MetadataResolver | None = None,
    taxonomy_packages: Sequence[str | Path] = (),
    limits: Limits = Limits(),
) -> Report:
    """Read a report, detecting xBRL-CSV or XBRL-XML from the input.

    The format is detected as by :func:`detect_format`; the input is then
    read by :func:`read_xbrl_csv` or :func:`read_xbrl_xml`.

    Args:
        source: Bytes, a file path, an xBRL-CSV package directory, or the
            path of a package's ``report.json``.
        name: Label used in messages and fact locations, such as the file
            name of uploaded bytes; the EBA file-naming rule checks it.
        metadata_resolver: xBRL-CSV ``extends`` URL resolver; unused for XML.
        taxonomy_packages: Local taxonomy package ZIPs: they resolve xBRL-CSV
            metadata and add the filing rules that need the taxonomy.
        limits: Resource limits for untrusted input.

    Returns:
        Report: The parsed report.

    Raises:
        ReportError: If the input cannot be read safely.

    Examples:
        >>> from dpmxbrl import read_report
        >>> report = read_report("instance.xbrl")
        >>> report.format, report.reference_date.isoformat(), len(report.facts)
        ('xbrl-xml', '2025-12-31', 3)
        >>> [(finding.rule, finding.code) for finding in report.filing]
        [('File naming', 'invalidFileName')]
    """
    if detect_format(source, name=name) == "xbrl-csv":
        return read_xbrl_csv(
            source,
            name=name,
            metadata_resolver=metadata_resolver,
            taxonomy_packages=taxonomy_packages,
            limits=limits,
        )
    return read_xbrl_xml(
        source, name=name, taxonomy_packages=taxonomy_packages, limits=limits
    )
