---
description: Exactly what dpm-xbrl reads from xBRL-CSV report packages (EBA convention and resolved metadata) and XBRL-XML instances, and what its writers produce.
---

# Data formats

This page lists exactly what the readers accept and what the writers
produce. [`read_report`][dpmxbrl.read_report] treats ZIP input (bytes or a
path), a directory and a `.json` path as xBRL-CSV and everything else as
XBRL-XML. Every failure raises [`ReportError`][dpmxbrl.ReportError] naming
the file and, where known, the line.

## xBRL-CSV report packages

### Package

- A ZIP or directory with exactly one `reports/*.json` report (normally
  `reports/report.json`), optionally below one top-level folder, plus an
  optional `META-INF/reportPackage.json` whose `documentType` must be
  `https://xbrl.org/report-package/2023` or `.../2023/xbr`.
  `.../2023/xbrl-csv`, which dpm-xbrl 0.1 wrote, is read with a warning. A
  directory may also hold `report.json` directly.
- `documentInfo.documentType` must be `https://xbrl.org/2021/xbrl-csv`; the
  2019 to 2021 PWD, CR and PR draft URIs are accepted with a warning.
  Duplicate JSON keys are rejected.

### Parameters

- `parameters.csv` (or the metadata's `parameterURL`) must have the header
  `name,value`.
- `entityID`, such as `lei:5299...`, becomes `Report.entity_id`; its prefix
  is looked up in `namespaces` for `entity_scheme`, else kept as the
  scheme. When the entry point cannot be read offline, the EBA prefixes
  `lei` (`http://standards.iso.org/iso/17442`) and `rs`
  (`https://eurofiling.info/eu/rs`) apply.
- `refPeriod` must be a `YYYY-MM-DD` date. A basic-format `YYYYMMDD` date,
  or one with a time or time zone, is read and breaks filing rule 2.10;
  week dates and mixed or non-ASCII digits are rejected.
- Parameters named `decimals*` populate `Report.decimals_parameters`;
  `#none` and `INF` map to `None`.
- Inline JSON `parameters` are merged first; the CSV file overrides them.

### Filing indicators

`FilingIndicators.csv` must have the header `templateID,reported`, with
`reported` one of `true`, `false`, `1`, `0`. See
[table codes and filing indicators](../concepts/filing-indicators.md) for
how tables map to them.

### Tables

Every other `*.csv` under the reports folder is a table. Its template id is
the file stem, unless the metadata `tables` maps the file URL to a
template. Rows are streamed with the `csv` module (`utf-8-sig`), including
from ZIPs; every row must have as many cells as the header, and the header
must not repeat or leave empty a column name.

**EBA convention (no metadata).** Tables need `datapoint` and `factValue`
columns; every other column is a key column kept in `Fact.keys`. Each row
with a non-empty `factValue` is one fact. `#nil` gives a nil fact, `#empty`
and `#none` are skipped, `##` escapes a leading `#`, and other `#` values
are kept as written; each case but `##` is recorded in `Report.filing`.
`Fact.decimals` stays `None`; consumers pick the `decimals_parameters`
entry for the fact's data type. Exact duplicate rows are reported once;
conflicting duplicates (same template, datapoint and keys, different value)
are all kept, and exact copies of a fact whose key already had a
conflicting value are dropped. Repeated findings are aggregated into one
warning with a count and the first location.

### Resolved metadata

`report.json` and its `extends` chain are followed recursively (cycle-safe,
diamond-safe, depth-limited by `Limits.max_extends_depth`), merging
`namespaces`, `tableTemplates`, `tables`, `parameters`, `dimensions`,
`decimals` and `parameterURL`, with the extending document taking
precedence. Relative URLs resolve inside the package or against the
extending document's URL. Absolute URLs are resolved by
`metadata_resolver(url)` first and then through the `META-INF/catalog.xml`
`rewriteURI` and `rewriteSystem` prefixes of the given taxonomy package
ZIPs. Nothing is fetched over the network. Table `url`s and `parameterURL`
resolve against the report's own JSON.

For a table whose template is resolved, the supported subset is:

- template `columns`;
- fact columns, with `dimensions` or `propertiesFrom`;
- property-group columns (`propertyGroups`, such as EBA's `datapoint`
  column keyed by `dp...`);
- other columns as key columns;
- report, template, column and property-group `dimensions` and `decimals`,
  in increasing precedence;
- `$column` and `$parameter` references (row cell, then table parameters,
  then report parameters), `$$` escapes and `#none`;
- the core dimensions `concept`, `unit`, `period`, `entity` and `language`
  (`period`, `entity` and `language` values are ignored);
- taxonomy-defined dimensions. A value that is a qname with a declared
  prefix is an explicit member; any other value is a typed value.

`Fact.datapoint` is the property-group key and `Fact.keys` keeps the key
columns. A table whose template cannot be resolved falls back to the EBA
convention, and unresolved `extends` produce one warning.

## XBRL-XML instances

- The prolog is scanned before parsing, and any DOCTYPE (and with it any
  ENTITY declaration) is rejected; external entities are never resolved.
  UTF-8, UTF-16 and single-byte encodings such as ISO-8859-1 are read
  (anything but UTF-8 breaks rule 1.4); unknown or other multi-byte
  encodings raise `ReportError`. Parsing streams with
  `iterparse` and clears each top-level element once processed.
- `link:schemaRef` gives `entry_point`.
- Contexts provide the entity identifier and scheme, the reference date
  (an instant, or the end date of a duration; it must start with a
  `YYYY-MM-DD` date) and `xbrldi:explicitMember`/`xbrldi:typedMember` from
  the segment or scenario. A typed member's value is the stripped text of
  its single child element; the child element name is not kept.
- Units with one or more measures, or a divide, become strings:
  `iso4217:EUR`, `a*b` for a product, `num/denom` for a divide.
- Facts are top-level elements outside the `xbrli`, `link` and `find`
  namespaces with a `contextRef`. `xsi:nil="true"` gives `value=None`;
  `decimals="INF"` gives `None`. `precision` is ignored, and tuples and
  elements without `contextRef` are skipped, each with a warning.
- `find:fIndicators/find:filingIndicator` provide filing indicators;
  `find:filed` defaults to true.
- The report entity and reference date are the most common across facts,
  and `base_currency` is the most common single-measure `iso4217` unit.
  More than one entity or period adds a warning, because the EBA requires
  one.
- Qnames use the instance's own prefixes; a namespace declared again deeper
  in the document under another prefix is rendered with the first prefix
  bound to it.

## Written xBRL-CSV

[`write_xbrl_csv`][dpmxbrl.write_xbrl_csv] writes a ZIP report package in
the EBA convention:

```text
<root>/META-INF/reportPackage.json   documentType https://xbrl.org/report-package/2023
<root>/reports/report.json           extends entry_point, declares namespaces
<root>/reports/parameters.csv        entityID, refPeriod, baseCurrency, decimals*, then other parameters
<root>/reports/FilingIndicators.csv  templateID,reported, sorted
<root>/reports/<template>.csv        datapoint,factValue,<key columns in first-seen order>
```

Nil values are written as `#nil`, empty strings as `#empty` and a leading
`#` as `##`. The root defaults to
[`default_package_root(report)`][dpmxbrl.default_package_root],
`<entity id>_<reference date>`. Output is deterministic: sorted templates,
source fact order, fixed ZIP timestamps. Facts without a template or
datapoint, unsafe template or root names, and the template names
`parameters` and `FilingIndicators` raise `ReportError` before anything is
written.

## Written XBRL-XML

[`write_xbrl_xml`][dpmxbrl.write_xbrl_xml] writes `link:schemaRef`, the
filing indicators, contexts deduplicated by dimensions (`c1`, `c2`, ...,
each with the entity and an instant at `reference_date`, dimensions in the
scenario), units (`u1`, ...) and facts. A fact with a unit is numeric and
gets `decimals` (`INF` when unset) unless it is nil. The report's
namespaces are declared on the root element.

Facts without a concept, undeclared or invalid prefixes, invalid local
names, characters XML cannot represent, a missing entity or reference date,
and a typed dimension without a typed domain raise `ReportError`. Because
the reader does not keep typed-domain element names, typed dimensions need
`typed_domains={"eba_dim:qINC": "eba_typ:qCC"}`, with a prefix the report
declares or in Clark notation
(`{http://www.eba.europa.eu/xbrl/crr/dict/typ}qCC`), whose namespace is then
declared; only the domains of dimensions that facts use are written.
Carriage returns in values are kept. The writer holds the instance text in
memory before writing it.

Reading a written report reproduces its facts in both formats; the test
suite covers these round trips.
