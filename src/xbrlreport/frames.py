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

Filing-rule findings on values are limited to special values (``#nil``,
``#empty`` and others). Checks that :func:`read_xbrl_csv` makes on every value
(the decimals suffix, leading or trailing spaces, special key values) cost a
second scan of millions of strings, so they are left to callers that already
split values by data type and key column.
"""

from __future__ import annotations

import io
import itertools
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._taxonomy import TaxonomyPackages
from .csv_reader import MetadataResolver, _CsvReportReader, _open_package
from .filing import EMPTY_VALUE, NIL_VALUE, SPECIAL_VALUE
from .model import Limits, Report, ReportError

if TYPE_CHECKING:
    import polars as pl


@dataclass(frozen=True)
class ReportFrames:
    """Report metadata plus one string frame per table template."""

    report: Report
    """The report with ``facts == ()``; use :attr:`tables` for the facts."""
    tables: Mapping[str, pl.DataFrame]
    """Template ID to a frame with ``datapoint``, ``factValue`` (strings) and
    key columns; ``datapoint`` and key columns are categorical."""

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
            )
            report = reader.read()
            return ReportFrames(report, reader.frames())
        finally:
            if taxonomy is not None:
                taxonomy.close()


class _FrameReader(_CsvReportReader):
    def __init__(
        self,
        *args: Any,
        on_metadata: Callable[[Report], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._frames: dict[str, list[pl.DataFrame]] = {}
        self._rows_read = 0
        self._on_metadata = on_metadata

    def _before_tables(self, header: Report) -> None:
        if self._on_metadata is not None:
            self._on_metadata(header)

    def _read_tables(self, metadata: Any) -> None:
        # Decompressing the next table while polars parses this one overlaps
        # the two (zlib releases the GIL); at most two tables are in memory.
        csv_names = [name for name in self._package.names if name.endswith(".csv")]
        with ThreadPoolExecutor(1, thread_name_prefix="xbrl-csv-read") as pool:
            self._prefetch = _Prefetch(self._package.read, csv_names, pool)
            super()._read_tables(metadata)

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
        data = self._prefetch.read(name)
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
        if frame.select(special.any()).item():
            for finding, mask in (
                (NIL_VALUE, value == "#nil"),
                (EMPTY_VALUE, value == "#empty"),
                (SPECIAL_VALUE, special & ~value.is_in(["#nil", "#empty"])),
            ):
                rows = frame.select(pl.arg_where(mask)).to_series()
                # Data rows start on line 2, after the header.
                for row in rows.head(5):
                    self._filing.add(*finding, f"{display}:{row + 2}")
                self._filing.add(*finding, count=rows.len() - min(rows.len(), 5))
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
        identity = [column for column in frame.columns if column != "factValue"]
        # One hash of the identity's category codes settles the common case
        # of no repeated cell and key; a collision only takes the exact path.
        hashed = frame.select(
            pl.struct([pl.col(column).to_physical() for column in identity])
            .hash()
            .n_unique()
        ).item()
        if hashed < frame.height and frame.select(identity).n_unique() < frame.height:
            before = frame.height
            frame = frame.unique(maintain_order=True)
            if frame.height < before:
                self._warnings.count(f"{display}: duplicate facts ignored", display)
            if frame.select(identity).n_unique() < frame.height:
                self._warnings.count(
                    f"{display}: conflicting duplicate facts kept", display
                )
        self._rows_read += frame.height
        if self._rows_read > self._limits.max_facts:
            raise ReportError(
                f"{display}: report exceeds the limit of {self._limits.max_facts} facts"
            )
        self._frames.setdefault(template_id, []).append(frame)


class _Prefetch:
    """Read package files in order, decompressing the next one ahead."""

    def __init__(
        self,
        read: Callable[[str], bytes],
        names: Sequence[str],
        pool: ThreadPoolExecutor,
    ) -> None:
        self._read = read
        self._next = dict(itertools.pairwise(names))
        self._pool = pool
        self._pending: dict[str, Future[bytes]] = {}

    def read(self, name: str) -> bytes:
        pending = self._pending.pop(name, None)
        data = pending.result() if pending is not None else self._read(name)
        following = self._next.get(name)
        if following is not None and following not in self._pending:
            self._pending[following] = self._pool.submit(self._read, following)
        return data


__all__ = ["ReportFrames", "read_xbrl_csv_frames"]
