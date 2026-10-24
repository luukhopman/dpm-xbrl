"""Columnar xBRL-CSV reading: one polars data frame per table.

:func:`read_xbrl_csv` builds one :class:`~dpmxbrl.model.Fact` per row, which
is convenient but costs several microseconds per fact in Python. Reports with
millions of open-table rows need columnar access instead:
:func:`read_xbrl_csv_frames` applies the same package, ``report.json``,
parameter and filing-indicator checks, then reads each EBA-convention table
straight into a polars frame of strings (``datapoint``, ``factValue`` and the
key columns), applying the same special-value and duplicate rules.

Requires the optional ``frames`` extra (``polars``). Tables described by
resolved xBRL-CSV metadata are not supported here; use :func:`read_xbrl_csv`.

Filing-rule findings on values are limited to special values (``#nil``,
``#empty`` and others). Checks that :func:`read_xbrl_csv` makes on every value
(the decimals suffix, spaces around key values, special key values) cost a
second scan of millions of strings, so they are left to callers that already
split values by data type and key column.

Table files are parsed by polars, which is more lenient than the ``csv``
module: a row with fewer cells than the header is padded with empty cells
instead of rejected, and line numbers in findings count data rows rather
than physical lines, so they differ when a file has blank lines or values
spanning lines.

Rows with no fact (an empty value, ``#empty`` or ``#none``) and exact
duplicate rows are removed, so a frame's row index is not the row's place in
its CSV file. :attr:`ReportFrames.dropped_rows` lists the removed rows by
template, which maps a frame row back to its data row when a caller needs
the file location.
"""

from __future__ import annotations

import csv
import io
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._taxonomy import TaxonomyPackages
from .csv_reader import MetadataResolver, _CsvReportReader, _open_package
from .filing import EMPTY_VALUE, NIL_VALUE, SPECIAL_VALUE, Rule
from .model import Limits, Report, ReportError

if TYPE_CHECKING:
    import polars as pl

# Table files inflated and parsed at once; each parse also uses polars' own
# threads, so a few files at a time fill the cores between their steps.
_READ_WORKERS = max(1, min(3, os.cpu_count() or 1))


@dataclass(frozen=True)
class ReportFrames:
    """Report metadata plus one string frame per table template."""

    report: Report
    """The report with ``facts == ()``; use :attr:`tables` for the facts."""
    tables: Mapping[str, pl.DataFrame]
    """Template ID to a frame with ``datapoint``, ``factValue`` (strings) and
    key columns; ``datapoint`` and key columns are categorical."""
    dropped_rows: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    """Template ID to the sorted 0-based data-row indices of the rows removed
    from its frame: rows without a fact (an empty value, ``#empty`` or
    ``#none``) and exact duplicates of an earlier row. Indices count data
    rows as read, before any row is removed, and continue across the files
    of a template in file order, as the frame does; data row ``i`` of a file
    is on line ``i + 2`` when no value spans lines. Only templates with
    removed rows appear."""

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
    on_metadata: Callable[[Report], None] | None = None,
    on_table: Callable[[str, pl.DataFrame, tuple[int, ...]], None] | None = None,
) -> ReportFrames:
    """Read an xBRL-CSV report package into columnar table frames.

    Args:
        source: Package bytes, path, or directory.
        name: Label used in messages.
        metadata_resolver: Returns the bytes for an absolute ``extends`` URL.
        taxonomy_packages: Taxonomy packages for offline metadata.
        limits: Resource limits for untrusted input.
        on_metadata: Called with the report (entry point, reference date,
            parameters and filing indicators, no facts) before the tables
            are read, so callers can start dependent work that overlaps the
            table parsing. Exceptions it raises abort the read.
        on_table: Called on the calling thread with each template ID, its
            frame and its removed rows (as in :attr:`ReportFrames.tables` and
            :attr:`ReportFrames.dropped_rows`) as soon as the template's last
            file is read, in package order, so callers can process tables
            while later ones are still being read. Exceptions it raises abort
            the read.

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
                on_metadata=on_metadata,
                on_table=on_table,
            )
            report = reader.read()
            return ReportFrames(report, reader.frames(), reader.dropped_rows())
        finally:
            if taxonomy is not None:
                taxonomy.close()


class _FrameReader(_CsvReportReader):
    def __init__(
        self,
        *args: Any,
        on_metadata: Callable[[Report], None] | None = None,
        on_table: Callable[[str, pl.DataFrame, tuple[int, ...]], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._frames: dict[str, list[pl.DataFrame]] = {}
        self._rows_read = 0
        # Data rows read per template before filtering, and those removed.
        self._rows_in_files: dict[str, int] = {}
        self._dropped: dict[str, list[int]] = {}
        self._on_metadata = on_metadata
        self._on_table = on_table
        self._pool: ThreadPoolExecutor | None = None
        self._scheduled: list[tuple[str, Future[_Parsed]]] = []

    def _before_tables(self, header: Report) -> None:
        if self._on_metadata is not None:
            self._on_metadata(header)

    def _read_tables(self, metadata: Any) -> None:
        # Files inflate and parse concurrently (zlib and polars release the
        # GIL); their findings, warnings and frames are then taken in package
        # order, so the result is the same as reading one file at a time.
        with ThreadPoolExecutor(
            _READ_WORKERS, thread_name_prefix="xbrl-csv-read"
        ) as pool:
            self._pool = pool
            try:
                super()._read_tables(metadata)
                remaining = Counter(template for template, _ in self._scheduled)
                for template_id, parsed in self._scheduled:
                    self._take(template_id, parsed.result())
                    remaining[template_id] -= 1
                    if not remaining[template_id] and self._on_table is not None:
                        self._on_table(
                            template_id,
                            self._frame(template_id),
                            tuple(self._dropped.get(template_id, ())),
                        )
            finally:
                for _, parsed in self._scheduled:
                    parsed.cancel()
                self._scheduled = []
                self._pool = None

    def frames(self) -> dict[str, pl.DataFrame]:
        return {template: self._frame(template) for template in self._frames}

    def _frame(self, template_id: str) -> pl.DataFrame:
        import polars as pl

        parts = self._frames[template_id]
        if len(parts) > 1:
            parts[:] = [pl.concat(parts, how="diagonal")]
        return parts[0]

    def dropped_rows(self) -> dict[str, tuple[int, ...]]:
        return {template: tuple(rows) for template, rows in self._dropped.items()}

    def _read_metadata_table(self, name: str, *args: Any, **kwargs: Any) -> None:
        raise ReportError(
            f"{self._display(name)}: tables described by xBRL-CSV metadata need "
            "read_xbrl_csv; columnar reading supports the EBA datapoint/factValue "
            "convention"
        )

    def _read_convention_table(self, name: str, template_id: str) -> None:
        assert self._pool is not None
        display = self._display(name)
        read = self._package.read
        self._scheduled.append(
            (template_id, self._pool.submit(lambda: _parse(read(name), display)))
        )

    def _take(self, template_id: str, parsed: _Parsed) -> None:
        """Record one parsed file's findings, removed rows and frame.

        Raises:
            ReportError: If the report now exceeds the fact limit.
        """
        import polars as pl

        for finding, location, count in parsed.findings:
            self._filing.add(*finding, location, count=count)
        for message, location in parsed.warnings:
            self._warnings.count(message, location)
        offset = self._rows_in_files.get(template_id, 0)
        self._rows_in_files[template_id] = offset + parsed.read
        if parsed.removed:
            self._dropped.setdefault(template_id, []).extend(
                (pl.concat(parsed.removed).sort() + offset).to_list()
            )
        frame = parsed.frame
        self._rows_read += frame.height
        if self._rows_read > self._limits.max_facts:
            raise ReportError(
                f"{parsed.display}: report exceeds the limit of "
                f"{self._limits.max_facts} facts"
            )
        self._frames.setdefault(template_id, []).append(frame)


@dataclass
class _Parsed:
    """One table file read into a frame, with what reading it found."""

    display: str
    frame: pl.DataFrame
    read: int
    """Data rows in the file, before any was removed."""
    removed: list[pl.Series]
    """File-relative indices of the removed rows (no fact, repeats)."""
    findings: list[tuple[Rule, str | None, int]]
    warnings: list[tuple[str, str]]


def _parse(data: bytes, display: str) -> _Parsed:
    """Read one EBA-convention table file (datapoint, factValue and keys).

    Returns:
        _Parsed: The frame and the findings to record, in reading order.

    Raises:
        ReportError: If the file has no usable header.
    """
    import polars as pl

    findings: list[tuple[Rule, str | None, int]] = []
    warnings: list[tuple[str, str]] = []
    try:
        header = pl.read_csv(io.BytesIO(data), n_rows=0, infer_schema=False)
        # Datapoints and key values repeat once per cell of a row; read as
        # categoricals they are stored once and compared as integers.
        frame = pl.read_csv(
            io.BytesIO(data),
            infer_schema=False,
            encoding="utf8",
            schema_overrides={
                column: pl.Categorical
                for column in header.columns
                if column != "factValue"
            },
        )
        # Empty CSV fields read as null; the reader treats them as "".
        frame = frame.with_columns(pl.all().fill_null(""))
    except (pl.exceptions.ComputeError, pl.exceptions.NoDataError) as error:
        if not data.strip():
            raise ReportError(f"{display}:1: the first row must be a header") from error
        raise ReportError(f"{display}: {error}") from error
    # polars renames a repeated column and names an empty one; the header
    # row as written is checked like read_xbrl_csv checks it.
    written = next(csv.reader([data.split(b"\n", 1)[0].decode("utf-8-sig")]), [])
    del data
    if any(not column.strip("\r") for column in written):
        raise ReportError(f"{display}:1: table header has an empty column name")
    duplicates = sorted({column for column in written if written.count(column) > 1})
    if duplicates:
        raise ReportError(
            f"{display}:1: duplicate table columns {', '.join(duplicates)}"
        )
    header = frame.columns
    if "datapoint" not in header or "factValue" not in header:
        raise ReportError(
            f"{display}:1: table header must contain 'datapoint' and "
            f"'factValue' columns, found {','.join(header)!r}"
        )
    value = pl.col("factValue")
    special = value.str.starts_with("#") & ~value.str.starts_with("##")
    # Special values are located before any row is removed, so their row
    # numbers are the file's.
    if frame.select(special.any()).item():
        for finding, mask in (
            (NIL_VALUE, value == "#nil"),
            (EMPTY_VALUE, value == "#empty"),
            (SPECIAL_VALUE, special & ~value.is_in(["#nil", "#empty"])),
        ):
            rows = frame.select(pl.arg_where(mask)).to_series()
            # Data rows start on line 2, after the header.
            for row in rows.head(5):
                findings.append((finding, f"{display}:{row + 2}", 1))
            findings.append((finding, None, rows.len() - min(rows.len(), 5)))
    read = frame.height
    has_fact = (value != "") & ~value.is_in(["#empty", "#none"])
    kept = frame.filter(has_fact)
    # Locating removed rows costs a second pass, so only when there are any.
    no_fact = (
        frame.select(pl.arg_where(~has_fact)).to_series().cast(pl.Int64)
        if kept.height < read
        else None
    )
    frame = kept.with_columns(
        pl.when(value == "#nil")
        .then(None)
        .when(value.str.starts_with("##"))
        .then(value.str.slice(1))
        .otherwise(value)
        .alias("factValue")
    )
    missing = frame.filter(pl.col("datapoint") == "").height
    if missing:
        warnings.append((f"{display}: facts without a datapoint", display))
    identity = [column for column in frame.columns if column != "factValue"]
    # One hash of the identity's category codes settles the common case
    # of no repeated cell and key; a collision only takes the exact path.
    hashed = frame.select(
        pl.struct([pl.col(column).to_physical() for column in identity])
        .hash()
        .n_unique()
    ).item()
    repeats = None
    if hashed < frame.height and frame.select(identity).n_unique() < frame.height:
        first = frame.select(pl.struct(pl.all()).is_first_distinct()).to_series()
        if not first.all():
            repeats = _rows_before(
                frame.select(pl.arg_where(~first)).to_series(), no_fact
            )
            frame = frame.filter(first)
            warnings.append(
                (f"{display}: duplicate facts ignored", f"{display}:{repeats[0] + 2}")
            )
        if frame.select(identity).n_unique() < frame.height:
            warnings.append((f"{display}: conflicting duplicate facts kept", display))
    return _Parsed(
        display,
        frame,
        read,
        [rows for rows in (no_fact, repeats) if rows is not None],
        findings,
        warnings,
    )


def _rows_before(rows: pl.Series, removed: pl.Series | None) -> pl.Series:
    """Return the indices that rows of a filtered frame had before the filter.

    Args:
        rows: Row indices in the filtered frame.
        removed: Sorted indices of the rows the filter removed, if any.

    Returns:
        pl.Series: The same rows' indices in the frame before the filter.
    """
    import polars as pl

    rows = rows.cast(pl.Int64)
    if removed is None:
        return rows
    # removed[i] - i rows were kept before the i-th removed row, so a kept
    # row at position p follows each removed row with removed[i] - i <= p.
    kept_before = removed - pl.int_range(removed.len(), eager=True)
    return rows + kept_before.search_sorted(rows, side="right").cast(pl.Int64)


__all__ = ["ReportFrames", "read_xbrl_csv_frames"]
