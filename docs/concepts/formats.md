---
description: xBRL-CSV report packages and XBRL 2.1 XML instances, the two serializations of an EBA report, and how dpm-xbrl reads each.
---

# xBRL-CSV and XBRL-XML

An EBA report can be written in two serializations of the same XBRL
model. The EBA accepts xBRL-CSV for most frameworks and has moved its
reporting to it; XBRL-XML is the older form, still used and still found in
archives.

## xBRL-CSV report packages

A report package is a ZIP with one top-level folder:

```text
529900T8BM49AURSDO55.CON_FR_COREP030300_COREPLE_2025-12-31_20260115093000000/
  META-INF/reportPackage.json      the package type
  reports/report.json              documentInfo: extends the taxonomy entry point
  reports/parameters.csv           entityID, refPeriod, baseCurrency, decimals*
  reports/FilingIndicators.csv     templateID, reported
  reports/c_26.00.csv              one CSV file per table
  reports/c_27.00.csv
```

Each table file has one row per fact (EBA's convention: `datapoint`,
`factValue`, then key columns for open tables). The meaning of each
datapoint, its concept and dimensions, lives in the taxonomy's metadata
that `report.json` extends; see
[EBA convention and resolved metadata](metadata.md). The format is defined
by the [xBRL-CSV 1.0][xbrl-csv-spec] and [Report Packages 1.0][report-packages]
specifications.

dpm-xbrl streams table rows with the `csv` module (`utf-8-sig`), straight
from the ZIP, so a package is never unpacked to disk. The exact package
rules are in [data formats](../reference/data-formats.md#xbrl-csv-report-packages).

## XBRL-XML instances

An instance is one XML document under the [XBRL 2.1][xbrl-21]
specification: a `link:schemaRef` to the entry point, filing indicators,
contexts (entity, period and dimensions), units, and one element per fact
that refers to a context and a unit.

```xml
<eba_met:mi53 id="f1" contextRef="c0" unitRef="u1" decimals="-3">56058000</eba_met:mi53>
```

dpm-xbrl scans the prolog, rejects any DOCTYPE, then streams the document
with `iterparse`, clearing each top-level element once it is processed. The
exact rules are in [data formats](../reference/data-formats.md#xbrl-xml-instances).

## The same fact in both

A fact in an xBRL-CSV table is identified by its template, datapoint and
key values; in XML, by its concept, dimensions and unit. The taxonomy maps
one to the other. Without it, a CSV fact has no concept and an XML fact has
no datapoint, which is why [conversion](../guides/convert-formats.md)
between the formats needs resolved metadata.

| | xBRL-CSV | XBRL-XML |
| --- | --- | --- |
| Identifies a fact by | template, datapoint, key columns | concept, dimensions, unit |
| Decimals | report parameters per data type (`decimalsMonetary`) | `decimals` attribute on each fact |
| Filing indicators | `FilingIndicators.csv` | `find:fIndicators` |
| Size | compact; millions of facts per table | verbose; a context per dimension combination |
| `Fact.location` | `reports/c_27.00.csv:3` | `instance.xbrl#f12` |
| Reads without the taxonomy | yes, in the EBA convention | yes |
