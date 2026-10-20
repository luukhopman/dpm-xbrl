"""Columnar xBRL-CSV reading: one polars data frame per table.

:func:`read_xbrl_csv` builds one :class:`~xbrlreport.model.Fact` per row, which
is convenient but costs several microseconds per fact in Python. Reports with
millions of open-table rows need columnar access instead:
:func:`read_xbrl_csv_frames` applies the same package, ``report.json``,
parameter and filing-indicator checks, then reads each EBA-convention table
straight into a polars frame of strings (``datapoint``, ``factValue`` and the
key columns), applying the same special-value and duplicate rules.

Requires the optional ``frames`` extra (``polars``). Tables described by
resolved xBRL-CSV metadata are not supported here; use :func:`read_xbrl_csv`.
"""

from __future__ import annotations

import io
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._taxonomy import TaxonomyPackages
from .csv_reader import MetadataResolver, _CsvReportReader, _open_package
from .model import Limits, Report, ReportError

if TYPE_CHECKING:
    import polars as pl


@dataclass(frozen=True)
class ReportFrames:
    """Report metadata plus one string frame per table template."""

    report: Report
    """The report with ``facts == ()``; use :attr:`tables` for the facts."""
    tables: Mapping[str, pl.DataFrame]
    """Template ID to a frame with ``datapoint``, ``factValue`` and key columns."""

    @property
    def fact_count(self) -> int:
        """Total number of fact rows across tables."""
        return sum(frame.height for frame in self.tables.values())


def read_xbrl_csv_frames(
    source: str | os.PathLike[str] | bytes,
    *,
    name: str | None = None,
    metadata_resolver: MetadataResolver | None = None,
    taxonomy_packages: Sequence[str | Path] = (),
    limits: Limits = Limits(),
) -> ReportFrames:
    """Read an xBRL-CSV report package into columnar table frames.

    Returns:
        ReportFrames: Report metadata and the table frames.

    Raises:
        ReportError: If the package is invalid, unsafe, over a limit, or
            uses metadata-described tables.
    """
    try:
        import polars as pl  # ruff: ignore[unused-import]
    except ImportError as error:  # pragma: no cover - depends on the extra
        raise ReportError(
            "columnar reading requires the optional 'frames' extra (polars)"
        ) from error
    package, report_json = _open_package(source, name=name, limits=limits)
    with package:
        taxonomy = (
            TaxonomyPackages(taxonomy_packages, limits=limits)
            if taxonomy_packages
            else None
        )
        try:
            reader = _FrameReader(
                package,
                report_json,
                resolver=metadata_resolver,
                taxonomy=taxonomy,
                limits=limits,
            )
            report = reader.read()
            return ReportFrames(report, reader.frames())
        finally:
            if taxonomy is not None:
                taxonomy.close()


class _FrameReader(_CsvReportReader):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._frames: dict[str, list[pl.DataFrame]] = {}
        self._rows_read = 0

    def frames(self) -> dict[str, pl.DataFrame]:
        import polars as pl

        return {
            template: parts[0] if len(parts) == 1 else pl.concat(parts, how="diagonal")
            for template, parts in self._frames.items()
        }

    def _read_metadata_table(self, name: str, *args: Any, **kwargs: Any) -> None:
        raise ReportError(
            f"{self._display(name)}: tables described by xBRL-CSV metadata need "
            "read_xbrl_csv; columnar reading supports the EBA datapoint/factValue "
            "convention"
        )

    def _read_convention_table(self, name: str, template_id: str) -> None:
        import polars as pl

        display = self._display(name)
        data = self._package.read(name)
        try:
            frame = pl.read_csv(io.BytesIO(data), infer_schema=False, encoding="utf8")
            # Empty CSV fields read as null; the reader treats them as "".
            frame = frame.with_columns(pl.all().fill_null(""))
        except (pl.exceptions.ComputeError, pl.exceptions.NoDataError) as error:
            if not data.strip():
                raise ReportError(
                    f"{display}:1: the first row must be a header"
                ) from error
            raise ReportError(f"{display}: {error}") from error
        header = frame.columns
        if "datapoint" not in header or "factValue" not in header:
            raise ReportError(
                f"{display}:1: table header must contain 'datapoint' and "
                f"'factValue' columns, found {','.join(header)!r}"
            )
        value = pl.col("factValue")
        special = value.str.starts_with("#") & ~value.str.starts_with("##")
        skipped = frame.filter(value.is_in(["#empty", "#none"])).height
        nils = frame.filter(value == "#nil").height
        unknown = frame.filter(
            special & ~value.is_in(["#empty", "#none", "#nil"])
        ).height
        if skipped:
            self._warnings.count(
                f"{display}: '#empty'/'#none' fact values skipped", display
            )
        if nils:
            self._warnings.count(
                f"{display}: '#nil' fact values read as nil facts", display
            )
        if unknown:
            self._warnings.count(
                f"{display}: unknown special values starting with '#' kept as written",
                display,
            )
        frame = frame.filter(
            (value != "") & ~value.is_in(["#empty", "#none"])
        ).with_columns(
            pl.when(value == "#nil")
            .then(None)
            .when(value.str.starts_with("##"))
            .then(value.str.slice(1))
            .otherwise(value)
            .alias("factValue")
        )
        missing = frame.filter(pl.col("datapoint") == "").height
        if missing:
            self._warnings.count(f"{display}: facts without a datapoint", display)
        before = frame.height
        frame = frame.unique(maintain_order=True)
        if frame.height < before:
            self._warnings.count(f"{display}: duplicate facts ignored", display)
        identity = [column for column in frame.columns if column != "factValue"]
        conflicts = frame.height - frame.unique(subset=identity).height
        if conflicts:
            self._warnings.count(
                f"{display}: conflicting duplicate facts kept", display
            )
        self._rows_read += frame.height
        if self._rows_read > self._limits.max_facts:
            raise ReportError(
                f"{display}: report exceeds the limit of {self._limits.max_facts} facts"
            )
        self._frames.setdefault(template_id, []).append(frame)


__all__ = ["ReportFrames", "read_xbrl_csv_frames"]
