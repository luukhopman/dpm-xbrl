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
unit. A fact needs the fields of the format it is written to:

| From | To xBRL-CSV | To XBRL-XML |
| --- | --- | --- |
| xBRL-CSV, EBA convention (no metadata) | Yes | No: facts have no concept |
| xBRL-CSV with [resolved metadata](taxonomy-packages.md) | Yes | Yes |
| XBRL-XML | No: facts have no template or datapoint | Yes |

Facts that lack a needed field raise [`ReportError`][dpmxbrl.ReportError]
before anything is written:

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
instance.xbrl#f1: fact has no template and cannot be written as xBRL-CSV
```

## xBRL-CSV to XBRL-XML

Read the package with its taxonomy package, so that each fact gets its
concept, dimensions and unit, then write XML. The reader keeps typed
dimension values but not the name of their typed domain element, so pass
`typed_domains` for every typed dimension the facts use, with a prefix the
report declares or in Clark notation:

```python
report = read_report("described.zip", taxonomy_packages=["taxonomy.zip"])
write_xbrl_xml(
    report,
    "described.xbrl",
    typed_domains={"eba_dim:qINC": "{http://www.eba.europa.eu/xbrl/crr/dict/typ}qCC"},
)
instance = read_report("described.xbrl")
print(
    len(instance.facts),
    instance.facts[3].concept,
    dict(instance.facts[3].typed_dimensions),
)
```

```text
6 eba_met:qNCO {'eba_dim:qINC': 'cp1'}
```

Contexts are written once per combination of dimensions (`c1`, `c2`, ...),
each with the report entity and an instant at the reference date, and all
dimensions in the scenario; units are `u1`, `u2`, .... A fact with a unit
is numeric and gets `decimals` (`INF` when unset) unless it is nil.

!!! warning "Check the result before sending it"

    The writer copies the report's entry point and namespaces as they are.
    An xBRL-CSV report extends the module's `.json` entry point, while an
    EBA XBRL-XML instance must reference the `.xsd` one, so replace it
    first, for example with
    `dataclasses.replace(report, entry_point="...corep_of.xsd")`. Prefixes
    that the report declares but no fact uses are declared too, and break
    rule 3.4 (a warning):

    ```python
    print([(finding.rule, finding.count) for finding in instance.filing])
    ```

    ```text
    [('3.4', 4), ('File naming', 1)]
    ```

The same conversion from the command line:

```console
$ dpm-xbrl convert described.zip described.xbrl --taxonomy-package taxonomy.zip --typed-domain "eba_dim:qINC={http://www.eba.europa.eu/xbrl/crr/dict/typ}qCC"
```

## XBRL-XML to XBRL-XML, xBRL-CSV to xBRL-CSV

Writing the same format again normalizes a report: contexts and units are
deduplicated and renumbered, or a package is rewritten in the EBA layout.
Reading a written report reproduces its facts:

```python
original = read_report("report.zip")
write_xbrl_csv(original, "rewritten.zip", root="rewritten")
print(read_report("rewritten.zip").facts == original.facts)
```

```text
True
```

The package is deterministic: templates are sorted, facts keep their order
and ZIP timestamps are fixed, so the same report always gives the same
bytes. The top-level folder defaults to
[`default_package_root(report)`][dpmxbrl.default_package_root],
`<entity id>_<reference date>`:

```python
from dpmxbrl import default_package_root

print(default_package_root(original))
```

```text
529900T8BM49AURSDO55.CON_2025-12-31
```

EBA file naming wants the folder to match the ZIP's file name without
`.zip`, so pass `root=` when you name the file; see
[check EBA filing rules](check-filing-rules.md#check-a-file-name-before-sending).

From the command line, the output suffix chooses the format: `.zip` writes
xBRL-CSV, `.xbrl` or `.xml` writes XBRL-XML. Reader warnings go to standard
error.

```console
$ dpm-xbrl convert report.zip copy.zip --root copy
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
529900T8BM49AURSDO55.CON
```

## What is not kept

See [known gaps](../reference/known-gaps.md) for the details. In short:
empty-string facts do not survive an xBRL-CSV round trip, `Fact.decimals`,
concepts and dimensions are not written to EBA-convention CSV, and XML
tuples, footnotes, `precision` and segment placement are not kept.
