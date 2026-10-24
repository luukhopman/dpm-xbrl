---
description: Read xBRL-CSV packages with millions of facts into polars frames with read_xbrl_csv_frames, map rows back to files and process tables as they arrive.
---

# Read large reports as frames


[`read_report`][dpmxbrl.read_report] builds one Python object per fact,
which takes about 5 µs and 0.7 KB per fact: a report with 7 million
open-table facts reads in 30 to 50 seconds. The `frames` extra reads
EBA-convention tables straight into [polars] frames of strings instead,
the same report in about a second.

```text
pip install "dpm-xbrl[frames]"
```

## Read a package into frames

[`read_xbrl_csv_frames`][dpmxbrl.frames.read_xbrl_csv_frames] returns a
[`ReportFrames`][dpmxbrl.frames.ReportFrames]: the report header with no
facts, plus one frame per table template.

```python
from dpmxbrl.frames import read_xbrl_csv_frames

frames = read_xbrl_csv_frames("report.zip")
print(frames.report.reference_date, frames.report.facts, frames.fact_count)
print(frames.tables["c_27.00"])
```

```text
2025-12-31 () 14
shape: (4, 4)
┌───────────┬────────────────────┬────────┬────────────────┐
│ datapoint ┆ factValue          ┆ qINC   ┆ qNCO           │
│ ---       ┆ ---                ┆ ---    ┆ ---            │
│ cat       ┆ str                ┆ cat    ┆ cat            │
╞═══════════╪════════════════════╪════════╪════════════════╡
│ dp5486584 ┆ Northwind Holdings ┆ CP0001 ┆ eba_qCO:qx2000 │
│ dp5485645 ┆ eba_NC:DE          ┆ CP0001 ┆ eba_qCO:qx2000 │
│ dp5486584 ┆ Contoso Group      ┆ CP0002 ┆ eba_qCO:qx2000 │
│ dp5485645 ┆ eba_NC:FR          ┆ CP0002 ┆ eba_qCO:qx2000 │
└───────────┴────────────────────┴────────┴────────────────┘
```

Each frame has a `datapoint` column, a `factValue` column of strings (null
for a `#nil` value) and the table's key columns; `datapoint` and the key
columns are categorical. Keys are the frame's template IDs, the file stems
such as `c_27.00`.

Cast values once you know their data type, then work in polars:

```python
import polars as pl

exposures = frames.tables["c_28.00"].with_columns(pl.col("factValue").cast(pl.Int64))
print(exposures.group_by("qINC").agg(pl.col("factValue").sum()).sort("qINC"))
```

```text
shape: (2, 2)
┌────────┬───────────┐
│ qINC   ┆ factValue │
│ ---    ┆ ---       │
│ cat    ┆ i64       │
╞════════╪═══════════╡
│ CP0001 ┆ 127438000 │
│ CP0002 ┆ 80150000  │
└────────┴───────────┘
```

## Map frame rows back to file rows

Rows with no fact (an empty value, `#empty` or `#none`) and exact duplicate
rows are removed, so a frame row's index is not its place in the CSV file.
`ReportFrames.dropped_rows` lists the removed data rows per template:

```python
import io
from zipfile import ZipFile

# Add an empty value and a duplicate row to c_28.00.
buffer = io.BytesIO()
with ZipFile("report.zip") as source, ZipFile(buffer, "w") as target:
    for name in source.namelist():
        data = source.read(name)
        if name.endswith("c_28.00.csv"):
            data += b"dp5488015,,CP0001\r\ndp5488013,67129000,CP0001\r\n"
        target.writestr(name, data)

edited = read_xbrl_csv_frames(buffer.getvalue(), name="report.zip")
print(edited.tables["c_28.00"].height, edited.dropped_rows)
```

```text
4 {'c_28.00': (4, 5)}
```

Indices are 0-based data rows as read, before any row is removed. Data row
`i` of a file is on line `i + 2` when no value spans lines, so frame row `n`
is data row `n` plus the number of dropped indices at or below it.

## Process tables as they arrive

`on_metadata` receives the report header before any table is read, and
`on_table` receives each template's frame as soon as its last file is read,
on the calling thread and in package order. Use them to start dependent
work, such as loading rules for the module, while later tables are still
being parsed:

```python
def on_metadata(report):
    print("header:", report.entity_id, sorted(report.filing_indicators))


def on_table(template, frame, dropped):
    print("table:", template, frame.height, dropped)


frames = read_xbrl_csv_frames("report.zip", on_metadata=on_metadata, on_table=on_table)
```

```text
header: 529900T8BM49AURSDO55.CON ['C_00.01', 'C_26.00', 'C_27.00', 'C_28.00', 'C_29.00']
table: c_00.01 2 ()
table: c_26.00 4 ()
table: c_27.00 4 ()
table: c_28.00 4 ()
```

An exception raised by a callback aborts the read.

## What is checked, and what is left to you

Columnar reading applies the same package, metadata, parameter,
filing-indicator, header, special-value and duplicate checks as
`read_report`. Checks that need a second pass over every string are left to
the caller, which usually splits values by data type anyway:

- the decimals suffix (xBRL-CSV rule 1),
- spaces around key values (3.11),
- special values in key columns (xBRL-CSV rule 5).

`needs_fixes.zip` breaks the first two. `read_report` finds five broken
rules in it; the frames reader finds three, without the decimals suffix and
the key spaces:

```python
broken = read_xbrl_csv_frames("needs_fixes.zip")
for finding in broken.report.filing:
    print(finding.rule, finding.code)
```

```text
2.19 nilUsed
xBRL-CSV 6 tableForNegativeFilingIndicator
File naming invalidFileName
```

Record the checks you make with the rule tuples in
[`dpmxbrl.filing`](../reference/api/filing.md); see
[add your own filing findings](add-filing-findings.md#checks-the-columnar-reader-leaves-to-you).

Table files are parsed by polars, which differs from the `csv` module: a
row with fewer cells than the header is padded with empty cells instead of
rejected, lines must end in LF or CRLF, and line numbers in findings count
data rows rather than physical lines.

## Tables described by metadata

Columnar reading supports the EBA `datapoint`/`factValue` convention only.
A package whose tables are described by resolved xBRL-CSV metadata raises
[`MetadataTablesError`][dpmxbrl.frames.MetadataTablesError], a
`ReportError`; fall back to `read_report`:

```python
from dpmxbrl import read_report
from dpmxbrl.frames import MetadataTablesError

try:
    frames = read_xbrl_csv_frames("described.zip", taxonomy_packages=["taxonomy.zip"])
except MetadataTablesError:
    report = read_report("described.zip", taxonomy_packages=["taxonomy.zip"])
    print("read", len(report.facts), "facts with read_report")
```

```text
read 6 facts with read_report
```

## From the command line

`dpm-xbrl inspect --columnar` counts facts with the frames reader and says
so on standard error:

```console
$ dpm-xbrl inspect report.zip --columnar
note: --columnar checks special fact values only; key values and decimals suffixes are not checked
Format:            xbrl-csv
Entry point:       http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json
Entity:            529900T8BM49AURSDO55.CON (https://eurofiling.info/eu/rs)
Reference date:    2025-12-31
Base currency:     iso4217:EUR
Filing indicators: 4 reported of 5
Facts:             14
  c_00.01  2
  c_26.00  4
  c_27.00  4
  c_28.00  4
Warnings: 1
  - reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json); tables without resolved metadata use the EBA datapoint/factValue convention
EBA filing rules broken: 0 must be fixed, 1 recommended
  - [warning] File naming The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.
```

On a 21.9-million-fact package (one 587 MB table) it takes 2 seconds and
2.3 GB instead of minutes; such a package also needs higher
[limits](untrusted-input.md#raise-the-limits-for-large-trusted-reports).
