---
description: Convert between xBRL-CSV and XBRL-XML with write_xbrl_csv and write_xbrl_xml - what each conversion needs and what is not kept.
---

# Convert between formats

[`write_xbrl_csv`][dpmxbrl.write_xbrl_csv] writes an xBRL-CSV report
package and [`write_xbrl_xml`][dpmxbrl.write_xbrl_xml] an XBRL 2.1 XML
instance. Both take a [`Report`][dpmxbrl.Report], so a conversion is a read
followed by a write. This guide shows what each conversion needs.

## What can be converted

The two formats identify facts differently: xBRL-CSV in the EBA convention
by template, datapoint and key columns; XBRL-XML by concept, dimensions and
unit. The taxonomy packages of the module connect the two:

| From | To xBRL-CSV | To XBRL-XML |
| --- | --- | --- |
| xBRL-CSV, EBA convention (no metadata) | Yes | Read it with [taxonomy packages](taxonomy-packages.md) |
| xBRL-CSV with resolved metadata | Yes | Yes |
| XBRL-XML | With taxonomy packages | Yes |

Without them, facts that lack a needed field raise
[`ReportError`][dpmxbrl.ReportError] before anything is written:

```python
from dpmxbrl import ReportError, read_report, write_xbrl_csv, write_xbrl_xml

try:
    write_xbrl_xml(read_report("report.zip"), "report.xbrl")
except ReportError as error:
    print(error)
try:
    write_xbrl_csv(read_report("instance.xbrl"), "instance.zip")
except ReportError as error:
    print(error)
```

```text
reports/c_00.01.csv:2: fact has no concept and cannot be written as XBRL-XML
instance.xbrl#f1: fact has no template and cannot be written as xBRL-CSV; taxonomy packages place facts by concept
```

## xBRL-CSV to XBRL-XML

Read the package with its taxonomy packages, so that each fact gets its
concept, dimensions and unit, then write XML with the same packages:

```python
report = read_report("described.zip", taxonomy_packages=["taxonomy.zip"])
write_xbrl_xml(report, "described.xbrl", taxonomy_packages=["taxonomy.zip"])
instance = read_report("described.xbrl")
print(len(instance.facts), instance.entry_point)
print(instance.facts[3].concept, dict(instance.facts[3].typed_dimensions))
print([(finding.rule, finding.count) for finding in instance.filing])
```

```text
6 http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.xsd
eba_met:qNCO {'eba_dim:qINC': 'cp1'}
[('File naming', 1)]
```

The packages give what the xBRL-CSV report does not hold:

- **The `schemaRef`.** An xBRL-CSV report extends the module's `.json`
  entry point; XML references its `.xsd`, the one the packages'
  `taxonomyPackage.xml` lists for it. Without packages, or when they do not
  list it, the EBA's naming gives it (`corep_of.json` beside
  `corep_of.xsd`) and the writer warns with
  [`EntryPointWarning`][dpmxbrl.EntryPointWarning].
- **Typed domains.** The reader keeps typed dimension values but not the
  element that wraps them in XML; the dimension's `xbrldt:typedDomainRef`
  names it, declared with the prefix its schema uses. Without packages,
  pass `typed_domains`, such as
  `{"eba_dim:qINC": "{http://www.eba.europa.eu/xbrl/crr/dict/typ}CC"}`,
  with a prefix the report declares or in Clark notation.

Contexts are written once per combination of dimensions (`c1`, `c2`, ...),
each with the report entity and an instant at the reference date, and all
dimensions in the scenario; units are `u1`, `u2`, .... A fact with a unit
is numeric and gets `decimals` (`INF` when unset) unless it is nil; a fact
with decimals but no unit, as xBRL-CSV metadata gives pure facts, gets
`xbrli:pure`. A fact that the package repeats in several tables is written
once, and only the prefixes the instance uses are declared (rule 3.4).

The same conversion from the command line:

```console
$ dpm-xbrl convert described.zip described.xbrl --taxonomy-package taxonomy.zip
```

## XBRL-XML to xBRL-CSV

Pass the taxonomy packages to [`write_xbrl_csv`][dpmxbrl.write_xbrl_csv].
The module's JSON entry point, the `schemaRef` with `.json` for `.xsd`, and
the table documents it extends give the layout: each fact goes in every
table row whose data point has its concept and dimensions, as the EBA's own
packages do when a cell appears in several templates.

```python
write_xbrl_csv(instance, "described-again.zip", taxonomy_packages=["taxonomy.zip"])
again = read_report("described-again.zip")
print(again.entry_point)
print(sorted(again.parameters.items()))
for fact in again.facts_for_template("c_27.00"):
    print(fact.datapoint, dict(fact.keys), fact.value)
```

```text
http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json
[('baseCurrency', 'iso4217:EUR'), ('decimalsMonetary', '-3'), ('entityID', 'rs:SYNTHETICDPMXL000002.CON'), ('refPeriod', '2024-12-31')]
dp100 {'c0010': 'cp1', 'c0020': 'eba_qCO:qx2000'} ABC
dp101 {'c0010': 'cp1', 'c0020': 'eba_qCO:qx2000'} 12.5
dp100 {'c0010': 'cp2', 'c0020': 'eba_qCO:qx2001'} DEF
```

- Tables, columns and prefixes are the module's: key columns come in the
  EBA's header-code order, take the members, typed values and units that
  the data point leaves open, and enumeration values take the module's
  prefixes. `report.json` declares no namespaces unless a fact needs one
  the module lacks.
- `baseCurrency` is the report's base currency, and each `decimals*`
  parameter the lowest decimals of its facts, so that no value claims more
  accuracy than its source gave it. The facts that had more decimals are
  named in a [`DecimalsWarning`][dpmxbrl.DecimalsWarning].
- Read back with the packages, the package gives the facts of the instance
  again; the tests check this on the EBA's official samples.

A fact that no data point holds, or whose unit differs from `baseCurrency`
or from its data point's, cannot be written exactly. By default it raises
`ReportError`, whose [`problems`][dpmxbrl.ReportError] list every such
fact; with `strict=False` it is left out and returned in
[`SkippedFacts`][dpmxbrl.SkippedFacts], as a
[`SkippedFact`][dpmxbrl.SkippedFact] with the reason and a stable code:
`undeclaredPrefix`, `noDataPoint`, `unitMismatch` or `currencyMismatch`.

```python
from dataclasses import replace

from dpmxbrl import Fact

stray = Fact("5", concept="eba_met:mi53", unit="iso4217:EUR", location="x#f9")
odd = replace(instance, facts=(*instance.facts, stray))
try:
    write_xbrl_csv(odd, "odd.zip", taxonomy_packages=["taxonomy.zip"])
except ReportError as error:
    print(error.problems)
skipped = write_xbrl_csv(
    odd, "odd.zip", taxonomy_packages=["taxonomy.zip"], strict=False
)
for item in skipped:
    print(item.fact.location, item.code, item.reason)
write_xbrl_xml(odd, "odd.xbrl", taxonomy_packages=["taxonomy.zip"])
```

```text
('x#f9: no data point of corep_of.json has concept eba_met:mi53 with these dimensions',)
x#f9 noDataPoint no data point of corep_of.json has concept eba_met:mi53 with these dimensions
```

From the command line, `--skip-unmapped` leaves such facts out and lists
them on standard error:

```console
$ dpm-xbrl convert odd.xbrl odd.zip --taxonomy-package taxonomy.zip
error: 1 fact cannot be written as xBRL-CSV: odd.xbrl#fact7: no data point of corep_of.json has concept eba_met:mi53 with these dimensions
$ echo $?
1
$ dpm-xbrl convert odd.xbrl odd.zip --taxonomy-package taxonomy.zip --skip-unmapped
warning: 1 fact left out:
  odd.xbrl#fact7: no data point of corep_of.json has concept eba_met:mi53 with these dimensions (noDataPoint)
```

For EBA reports, pass the release ZIP the EBA publishes, or its dictionary
and reporting-frameworks packages. Converting the 21,314-fact
`EBA-COREP_OF.xbrl` sample takes about 3 seconds; see the
[benchmarks](../project/benchmarks.md).

## XBRL-XML to XBRL-XML, xBRL-CSV to xBRL-CSV

Writing the same format again normalizes a report: contexts and units are
deduplicated and renumbered, or a package is rewritten in the EBA layout.
Reading a written report reproduces its facts:

```python
original = read_report("report.zip")
write_xbrl_csv(original, "rewritten.zip")
print(read_report("rewritten.zip").facts == original.facts)
```

```text
True
```

The package is deterministic: templates are sorted, facts keep their order
and ZIP timestamps are fixed, so the same report always gives the same
bytes. The top-level folder is the ZIP's file name without `.zip`, as EBA
file naming asks, or, when writing to a stream,
[`default_package_root(report)`][dpmxbrl.default_package_root],
`<entity id>_<reference date>`:

```python
from dpmxbrl import default_package_root

print(default_package_root(original))
```

```text
SYNTHETICDPMXL000002.CON_2025-12-31
```

Pass `root=` to name it otherwise; see
[check EBA filing rules](check-filing-rules.md#check-a-file-name-before-sending)
for the file name itself.

From the command line, the output suffix chooses the format: `.zip` writes
xBRL-CSV, `.xbrl` or `.xml` writes XBRL-XML. Reader warnings go to standard
error.

```console
$ dpm-xbrl convert report.zip copy.zip
warning: reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json); tables without resolved metadata use the EBA datapoint/factValue convention
```

## Write to a stream

Both writers accept a writable binary stream as well as a path:

```python
import io

buffer = io.BytesIO()
write_xbrl_csv(original, buffer)
print(read_report(buffer.getvalue()).entity_id)
```

```text
SYNTHETICDPMXL000002.CON
```

## What is not kept

See [known gaps](../reference/known-gaps.md) for the details. In short:
empty-string facts do not survive an xBRL-CSV round trip, `Fact.decimals`,
concepts and dimensions are not written to EBA-convention CSV, and XML
tuples, footnotes, `precision` and segment placement are not kept.
