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


def detect_format(source: str | os.PathLike[str] | bytes) -> ReportFormat:
    """Detect whether input is an xBRL-CSV package or an XBRL-XML instance.

    ZIP archives, directories and ``.json`` metadata paths are xBRL-CSV;
    anything else is read as XBRL-XML.

    Returns:
        ReportFormat: ``"xbrl-csv"`` or ``"xbrl-xml"``.

    Raises:
        ReportError: If a path does not exist or cannot be read, or if a
            ``.zip`` file or one starting like a ZIP archive cannot be read as
            one (it is incomplete or damaged; reading it as XML would only
            report malformed XML).
    """
    if isinstance(source, bytes):
        if zipfile.is_zipfile(io.BytesIO(source)):
            return "xbrl-csv"
        if source.startswith(_ZIP_SIGNATURE):
            raise ReportError(_DAMAGED_ZIP.format(name="the report"))
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
        raise ReportError(_DAMAGED_ZIP.format(name=path.name))
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

    Args:
        source: Bytes, a file path, or an xBRL-CSV package directory.
        name: Label used in messages and fact locations.
        metadata_resolver: xBRL-CSV ``extends`` URL resolver; unused for XML.
        taxonomy_packages: Local taxonomy package ZIPs for xBRL-CSV metadata.
        limits: Resource limits for untrusted input.

    Returns:
        Report: The parsed report.

    Raises:
        ReportError: If the input cannot be read safely.
    """
    if detect_format(source) == "xbrl-csv":
        return read_xbrl_csv(
            source,
            name=name,
            metadata_resolver=metadata_resolver,
            taxonomy_packages=taxonomy_packages,
            limits=limits,
        )
    return read_xbrl_xml(source, name=name, limits=limits)
