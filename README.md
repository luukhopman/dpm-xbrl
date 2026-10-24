# dpm-xbrl

Read and write EBA-style regulatory XBRL reports in both serializations, xBRL-CSV
report packages and XBRL 2.1 XML instances, through one neutral fact model.
It targets reports built on the data point model (DPM) taxonomies of the
European Banking Authority and is tested on EBA reports. It is an independent
project, not affiliated with or endorsed by the EBA.
The package uses only the standard library and needs Python 3.11 or newer.

```
pip install dpm-xbrl            # standard library only
pip install "dpm-xbrl[fast]"    # isal: inflates ZIP entries about twice as fast
pip install "dpm-xbrl[frames]"  # polars: columnar reading of large reports
```

The `fast` extra changes speed only; the bytes read are the same either way.

```python
from dpmxbrl import read_report

report = read_report("report.zip")  # or a directory, report.json, .xbrl, or bytes
print(report.entity_id, report.reference_date, len(report.facts))
for fact in report.facts_for_template("C_01.00"):
    print(fact.datapoint, fact.keys, fact.value)
```

## Model

`dpmxbrl.model` (re-exported from `dpmxbrl`) defines two frozen, slotted
dataclasses:

- `Fact`: `value` (lexical value as written, `None` when nil), `concept`
  (prefixed qname), `datapoint` (xBRL-CSV datapoint code), `template`
  (xBRL-CSV table template id, `None` for XML), `dimensions` (explicit dimension
  qname to member qname), `typed_dimensions` (typed dimension qname to the typed
  value text), `keys` (xBRL-CSV non-fact column name to cell value, in header
  order), `unit` (`iso4217:EUR`, `xbrli:pure`, `num/denom` for divide units,
  `a*b` for products), `decimals` (`None` means INF or unspecified) and
  `location` (`reports/c_01.00.csv:3` with the 1-based physical line, or
  `instance.xbrl#f12` with the fact id, `#factN` for the Nth fact without id).
- `Report`: `format`, `entry_point`, `entity_scheme`, `entity_id`,
  `reference_date`, `base_currency`, `parameters`, `decimals_parameters`,
  `filing_indicators`, `facts`, `namespaces`, `warnings` and `filing` (the
  EBA filing rules the report breaks, see below).

`Report.facts_for_template(code)` compares template codes case-insensitively,
so filing-indicator codes such as `C_01.00` select facts from `c_01.00.csv`.
`local_name(qname)` returns the local part of a prefixed or Clark qname.

Qnames always use prefixes declared in `Report.namespaces`. XML keeps the
instance's own prefixes; a namespace declared again deeper in the document
under another prefix is rendered with the first prefix bound to it.

## Reading

```python
read_report(source, *, name=None, metadata_resolver=None,
            taxonomy_packages=(), limits=Limits()) -> Report
read_xbrl_csv(source, *, name=None, metadata_resolver=None,
              taxonomy_packages=(), limits=Limits()) -> Report
read_xbrl_xml(source, *, name=None, limits=Limits()) -> Report
detect_format(source) -> "xbrl-csv" | "xbrl-xml"
```

`read_report` treats ZIP input (bytes or a path), a directory and a `.json`
path as xBRL-CSV and everything else as XBRL-XML. Every failure raises
`ReportError` (a `ValueError`) naming the file and, where known, the line.

### xBRL-CSV

- A ZIP or directory with exactly one `reports/*.json` report (normally
  `reports/report.json`), optionally below one top-level folder, plus an
  optional `META-INF/reportPackage.json` whose `documentType` must be
  `https://xbrl.org/report-package/2023` or `.../2023/xbrl-csv`. A directory
  may also hold `report.json` directly.
- `documentInfo.documentType` must be `https://xbrl.org/2021/xbrl-csv`; the
  2019-2021 PWD/CR/PR draft URIs are accepted with a warning. Duplicate JSON
  keys are rejected.
- `parameters.csv` (or the metadata's `parameterURL`) must have the header
  `name,value`. `entityID` such as `lei:5299...` becomes `entity_id`; its
  prefix is looked up in `namespaces` for `entity_scheme`, else kept as the
  scheme. `refPeriod` must be a `YYYY-MM-DD` date. Parameters named
  `decimals*` populate `decimals_parameters` (`#none` and `INF` map to `None`).
  Inline JSON `parameters` are merged first; the CSV file overrides them.
- `FilingIndicators.csv` must have the header `templateID,reported`, with
  `reported` one of `true`, `false`, `1`, `0`.
- Every other `*.csv` under the reports folder is a table. Its template id is
  the file stem unless the metadata `tables` maps the file URL to a template.

**EBA convention (no metadata).** Tables need `datapoint` and `factValue`
columns; every other column is a key column kept in `Fact.keys`. Each row with
a non-empty `factValue` is one fact. `#nil` gives a nil fact, `#empty` and
`#none` are skipped, `##` escapes a leading `#`, and other `#` values are kept
as written; each case but `##` is recorded in `Report.filing`. `Fact.decimals` stays `None`; consumers
pick the `decimals_parameters` entry for the fact's data type. Exact duplicate
rows are reported once; conflicting duplicates (same template, datapoint and
keys, different value) are all kept. Repeated findings are aggregated into one
warning with a count and the first location.

**Resolved metadata.** `report.json` and its `extends` chain are followed
recursively (cycle-safe, diamond-safe, depth-limited), merging `namespaces`,
`tableTemplates`, `tables`, `parameters`, `dimensions`, `decimals` and
`parameterURL`, with the extending document taking precedence. Relative URLs
resolve inside the package or against the extending document's URL. Absolute
URLs are resolved by `metadata_resolver(url)` first and then through the
`META-INF/catalog.xml` `rewriteURI`/`rewriteSystem` prefixes of the given
taxonomy package ZIPs. Nothing is fetched over the network. Table `url`s and
`parameterURL` resolve against the report's own JSON.

For a table whose template is resolved, the supported xBRL-CSV subset is:
template `columns`; fact columns (with `dimensions` or `propertiesFrom`);
property-group columns (`propertyGroups`, such as EBA's `datapoint` column keyed
by `dp...`); other columns as key columns; report, template, column and
property-group `dimensions` and `decimals`, in increasing precedence;
`$column` and `$parameter` references (row cell, then table parameters, then
report parameters), `$$` escapes and `#none`; core dimensions `concept`,
`unit`, `period`, `entity` and `language`; and taxonomy-defined dimensions. A
taxonomy-defined dimension value that is a qname with a declared prefix is an
explicit member; any other value is a typed value. `Fact.datapoint` is the
property-group key and `Fact.keys` keeps the key columns. A table whose
template cannot be resolved falls back to the EBA convention, and unresolved
`extends` produce one warning.

### XBRL-XML

- The prolog is scanned before parsing and any DOCTYPE (and with it any ENTITY
  declaration) is rejected; external entities are never resolved. Parsing
  streams with `iterparse` and clears each top-level element once processed.
- `link:schemaRef` gives `entry_point`. Contexts provide the entity identifier
  and scheme, the reference date (instant, or the end date of a duration) and
  `xbrldi:explicitMember`/`xbrldi:typedMember` from segment or scenario. A typed
  member's value is the stripped text of its single child element; the child
  element name is not kept.
- Units with one or more measures, or a divide, become strings. Facts are
  top-level elements outside the `xbrli`, `link` and `find` namespaces with a
  `contextRef`; `xsi:nil="true"` gives `value=None`; `decimals="INF"` gives
  `None`. `precision` is ignored, and tuples and elements without `contextRef`
  are skipped, each with a warning.
- `find:fIndicators/find:filingIndicator` provide filing indicators;
  `find:filed` defaults to true.
- The report entity and reference date are the most common across facts, and
  `base_currency` is the most common single-measure `iso4217` unit. More than
  one entity or period adds a warning, because EBA requires one.

### Limits

`Limits(max_zip_entries=10_000, max_total_size=2 GiB, max_file_size=512 MiB,
max_facts=20_000_000, max_extends_depth=32)`. Report packages are also rejected
for absolute or `..` entry names, duplicate entries and encrypted entries, and
package directories for links that leave the directory. The file-size limit
also applies to XML instances and to files read from taxonomy packages. CSV
rows are streamed with the `csv` module (`utf-8-sig`), including from ZIPs.
An entry whose compressed data is damaged raises `ReportError` naming the entry.

### EBA filing rules

Both readers record the [EBA Filing Rules](https://www.eba.europa.eu/sites/default/files/2026-02/10436139-46ae-4a7d-880f-c399ba6de669/EBA%20Filing%20Rules%20v5.8_2026_02_25.pdf)
(version 5.8, February 2026) that a report breaks and that the file alone can show, in
`Report.filing`: one `FilingFinding` per rule and problem, with the rule's
number (`2.19`), its tag in the EBA document (`nilUsed`), a severity, a
message, how many times it occurs and up to five locations.
`dpmxbrl.filing.RULE_TITLES` names each rule. Severity is `error` where the
rule says MUST (EBA rejects the report) and `warning` where it says SHOULD;
file-naming findings are warnings because each supervisor confirms its own
naming.

- Both formats: one absolute taxonomy entry point (1.5, 2.2, 2.3); the
  reporting subject's scheme, suffix, upper case and LEI check digits (2.8,
  3.6); and the file name against `ReportSubject_Country_
  FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp`,
  including the reporting subject, module and reference date.
- XBRL-XML: UTF-8 and no standalone declaration (1.4, 1.13); filing
  indicators present, unique and in a context without segment or scenario
  (1.6, 1.6.1); no `xsi:schemaLocation`, XInclude, `xml:base`,
  `link:linkbaseRef`, footnotes, segments, forever or duration periods, or
  non-dimensional scenario content (1.14, 1.15, 2.1, 2.4, 2.25, 2.11, 2.13, 2.14,
  2.15); one entity and reference date, as plain dates (2.9, 2.10, 2.13); no
  duplicate facts, and none differing only by unit (2.16, 2.16.1); `decimals`
  rather than `precision`, and present on numeric facts (2.17, 2.18); no nil or
  empty facts (2.19); unused or repeated contexts and units (2.7, 2.21, 2.22);
  one reporting currency, and currency-of-denomination facts in the currency
  their CUS or CUA member names (3.1); `xbrli:pure` for other numeric facts
  (3.2); and namespace prefixes declared once, on the document element, and
  used (3.4, 3.9, 3.10).
- xBRL-CSV: `META-INF/reportPackage.json`, `parameters.csv` with
  `refPeriod`, and `FilingIndicators.csv`; the root folder named as the ZIP;
  no `documentInfo.taxonomy` (1.5); a plain-date `refPeriod` (2.10); unique
  filing indicators (1.6.1); no table file for a template indicated as not
  reported (xBRL-CSV rule 6); no special values in fact or key columns
  (`#nil`, `#empty` and any other value starting with `#`; 2.19 and rule 5);
  no decimals suffix (rule 1); key values without leading or trailing spaces
  (3.11).

Rules that need the taxonomy are left to the caller, which can build
`FilingFinding`s and merge them with `dpmxbrl.filing.FilingLog`: a filing
indicator for every template of the module and only valid codes (1.6, 1.6.3),
facts outside the reported templates (1.7.1), minimum decimals per data type
(2.18), fact values without leading or trailing spaces, which applies to
string data points only (3.11, `SPACES` in `dpmxbrl.filing`), an entry
point valid for the reference date (1.5), and `baseCurrency` when monetary
facts use it. Not checked: units against the XBRL unit registry (2.23),
decimal notation for rates (3.2), canonical prefixes (3.5),
generating-software information (2.26) and comments (2.5).
`read_xbrl_csv_frames` checks special fact values only; the decimals suffix,
spaces around key values and special key values are left to callers that
split values by data type, which can record them with the same messages
(`DECIMALS_SUFFIX`, `KEY_SPACES`, `SPECIAL_KEY_VALUE` in `dpmxbrl.filing`).

### Columnar reading

```python
from dpmxbrl.frames import read_xbrl_csv_frames

frames = read_xbrl_csv_frames("report.zip")
frames.report.reference_date          # the Report, with facts == ()
frames.tables["c_01.00"]              # polars frame: datapoint, factValue, keys
```

`read_report` builds one `Fact` per value, which takes about 5 µs and 0.7 KB
per fact: a report with 7 million open-table facts reads in about 30 seconds.
The `frames` extra reads EBA-convention tables straight into polars frames of
strings instead, the same report in about a second. It applies the same
package, metadata, parameter, filing-indicator, header, special-value and
duplicate checks; value checks that need a second pass over every string
(see the end of the filing rules above) are left to the caller. Tables
described by resolved metadata need `read_xbrl_csv`. `on_metadata` and
`on_table` callbacks hand over the report header and each table as soon as
they are read, and `ReportFrames.dropped_rows` maps frame rows back to file
rows.

## Writing

```python
write_xbrl_csv(report, target, *, root=None) -> None
write_xbrl_xml(report, target, *, typed_domains=None) -> None
default_package_root(report) -> str
```

`write_xbrl_csv` writes a ZIP report package in EBA convention:
`<root>/META-INF/reportPackage.json`, `<root>/reports/report.json` (extending
`entry_point` and declaring `namespaces`), `parameters.csv` (`entityID`,
`refPeriod`, `baseCurrency`, `decimals*`, then any other parameter),
`FilingIndicators.csv` and one `<template>.csv` per template with header
`datapoint,factValue,<key columns in first-seen order>`. Nil values are
written as `#nil`, empty strings as `#empty` and a leading `#` as `##`. The root
defaults to `<entity id>_<reference date>`. Output is deterministic (sorted
templates, source fact order, fixed ZIP timestamps). Facts without a template
or datapoint raise `ReportError` before anything is written.

`write_xbrl_xml` writes `schemaRef`, filing indicators, contexts deduplicated
by dimensions (`c1`, `c2`, ..., entity plus an instant at `reference_date`,
dimensions in the scenario), units (`u1`, ...) and facts. A fact with a unit
is numeric and gets `decimals` (`INF` when unset) unless it is nil. Facts
without a concept, undeclared prefixes and a missing entity or reference date
raise `ReportError`. Because the reader does not keep typed-domain element
names, typed dimensions need `typed_domains={"eba_dim:qINC": "eba_typ:qCC"}`.

Reading a written report reproduces its facts in both formats; the tests
cover these round trips.

## CLI

```
dpm-xbrl inspect PATH [--json] [--taxonomy-package ZIP ...]
dpm-xbrl convert IN OUT [--taxonomy-package ZIP ...]
                           [--typed-domain DIMENSION=ELEMENT ...] [--root NAME]
```

`inspect` prints the format, entry point, entity, reference date, base
currency, filing indicators (reported of total), the fact count per template,
the warnings and the EBA filing rules the report breaks. `convert` chooses the output format from the suffix: `.zip`
writes xBRL-CSV, `.xbrl` or `.xml` writes XBRL-XML. Errors print `error: ...`
and exit with status 1.

## Stability

Releases follow [semantic versioning](https://semver.org). The public API is
everything documented here: the names exported by `dpmxbrl`, `dpmxbrl.filing`
and `dpmxbrl.frames`, the fields of `Report`, `Fact`, `FilingFinding` and
`Limits`, the CLI and the `ReportError` contract. Modules whose names start
with an underscore are internal. Warning texts and filing-finding messages may
be reworded in minor releases; rule numbers and codes may not. See
[CHANGELOG.md](CHANGELOG.md) for what changed in each release.

## Development

```
uv sync
uv run pytest
uv run ruff check
uv run ruff format --check
uv run ty check
```

## Known gaps

- No taxonomy validation, schema lookups or calculation and formula checks.
  Without a taxonomy, an explicit member and a typed value that looks like a
  declared qname cannot be told apart in xBRL-CSV metadata.
- xBRL-CSV: no `rowIdColumn`, `links`, footnotes, `@start`/`@end` period
  semantics, per-fact `period`/`entity`/`language` values (they are ignored),
  or multiple reports per package. Taxonomy packages must be ZIPs.
- EBA-convention CSV facts carry no concept, dimensions, unit or decimals, so
  they cannot be written as XML; XML facts carry no datapoint or template, so
  they cannot be written as CSV. Converting between formats needs resolved
  xBRL-CSV metadata.
- Empty-string facts do not survive an xBRL-CSV round trip (`#empty` is
  skipped when read), and `Fact.decimals`, concepts and dimensions are not
  written to EBA-convention CSV.
- XML: tuples, footnotes, `precision`, segment versus scenario placement,
  forever periods and typed-domain element names are not kept. XML output puts
  all dimensions in the scenario and uses one entity and instant. The XML
  writer holds the instance text in memory before writing it.
- Fact locations in XML use the fact id rather than a line number.
