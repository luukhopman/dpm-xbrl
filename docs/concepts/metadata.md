---
description: The EBA datapoint/factValue convention versus xBRL-CSV metadata resolved from the taxonomy, and when each applies.
---

# EBA convention and resolved metadata

An xBRL-CSV table is a CSV file; what its columns mean is defined in JSON
metadata, the *table templates*, that the report extends from the
taxonomy. dpm-xbrl reads a table in one of two ways, depending on whether
it can read that metadata.

## The EBA convention, without metadata

EBA tables follow one layout: a `datapoint` column, a `factValue` column,
and, for open tables, key columns such as `qINC` that identify the row.
dpm-xbrl reads that layout without the taxonomy:

- every row with a non-empty `factValue` is one fact;
- `datapoint` becomes `Fact.datapoint`, every other column a key in
  `Fact.keys`;
- `#nil` gives a nil fact, `#empty` and `#none` are skipped, `##` escapes a
  leading `#`, and other `#` values are kept as written; each case but `##`
  is recorded as a broken [filing rule](filing-rules.md);
- `Fact.concept`, `dimensions`, `unit` and `decimals` stay empty; the
  decimals that apply are the report's `decimals*` parameters.

This is what you get by default, and it is all that rule engines keyed by
datapoint, such as [dpm-xl], need. Reading also warns that the extended
metadata could not be resolved offline.

Exact duplicate rows are reported once; conflicting duplicates (same
template, datapoint and keys, different value) are all kept. Repeated
findings are aggregated into one warning with a count and the first
location.

## Resolved metadata

With [taxonomy packages or a resolver](../guides/taxonomy-packages.md),
dpm-xbrl follows `report.json` and its `extends` chain and reads each table
through its template, as the xBRL-CSV specification defines. Each fact then
gets its concept, explicit and typed dimensions, unit and decimals.
`Fact.datapoint` is the property-group key (EBA's `dp...` codes) and
`Fact.keys` keeps the key columns.

You need resolved metadata to:

- [convert](../guides/convert-formats.md) a report to XBRL-XML;
- work with concepts and dimensions rather than datapoint codes;
- read tables that do not follow the EBA layout.

The supported subset of the specification is listed in
[data formats](../reference/data-formats.md#resolved-metadata).

## Mixing the two

The choice is per table. A table whose template cannot be resolved falls
back to the EBA convention, so a package can have some tables of each.
[Columnar reading](../guides/large-reports.md) supports the EBA convention
only, and raises [`MetadataTablesError`][dpmxbrl.frames.MetadataTablesError]
when a table needs metadata.
