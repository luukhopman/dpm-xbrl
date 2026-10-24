---
description: Resolve xBRL-CSV metadata offline from taxonomy package ZIPs or your own resolver, so facts get concepts, dimensions, units and decimals.
---

# Resolve metadata offline

An xBRL-CSV report extends a taxonomy entry point, such as
`http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json`,
whose table templates describe what each column and datapoint means. When
dpm-xbrl can read that metadata, each fact gets its concept, dimensions,
unit and decimals. dpm-xbrl never fetches anything over the network, so you
hand it the metadata: as taxonomy package ZIPs, or through a resolver
function.

Without metadata, tables are read in the EBA `datapoint`/`factValue`
convention, which is enough to work with datapoint codes; see
[EBA convention and resolved metadata](../concepts/metadata.md) for the
difference.

## With taxonomy packages

Pass the taxonomy package ZIPs the EBA publishes for the framework release.
dpm-xbrl reads each package's `META-INF/catalog.xml` and maps the entry
point URL to the file inside the package:

```python
from dpmxbrl import read_report

plain = read_report("described.zip")
resolved = read_report("described.zip", taxonomy_packages=["taxonomy.zip"])
print(plain.facts[0])
print(resolved.facts[0])
```

```text
Fact(value='1000', concept=None, datapoint='dp84817', template='c_01.00', dimensions={}, typed_dimensions={}, keys={}, unit=None, decimals=None, location='reports/c_01.00.csv:2')
Fact(value='1000', concept='eba_met:mi53', datapoint='dp84817', template='c_01.00', dimensions={'eba_dim:BAS': 'eba_BA:x6'}, typed_dimensions={}, keys={}, unit='iso4217:EUR', decimals=-3, location='reports/c_01.00.csv:2')
```

Facts of open tables also get their typed dimensions from the key columns,
while `Fact.keys` keeps the columns as written:

```python
fact = resolved.facts[4]
print(fact.concept, dict(fact.dimensions), dict(fact.typed_dimensions))
print(dict(fact.keys), fact.unit, fact.decimals)
```

```text
eba_met:mi1 {'eba_dim:qCO': 'eba_qCO:qx2000'} {'eba_dim:qINC': 'cp1'}
{'c0010': 'cp1', 'c0020': 'eba_qCO:qx2000'} iso4217:EUR -3
```

The sample [`taxonomy.zip`](../samples/taxonomy.zip) is a minimal package
for the examples. For real reports, pass every ZIP of the EBA taxonomy
release (for 4.2, the dictionary and reporting-frameworks packages); the
order does not matter. The same works from the command line with
`--taxonomy-package`, once per ZIP:

```console
$ dpm-xbrl inspect described.zip --taxonomy-package taxonomy.zip
Format:            xbrl-csv
Entry point:       http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json
Entity:            529900T8BM49AURSDO55.CON (https://eurofiling.info/eu/rs)
Reference date:    2024-12-31
Base currency:     iso4217:EUR
Filing indicators: 2 reported of 3
Facts:             6
  c_01.00  3
  c_27.00  3
Warnings: 0
EBA filing rules broken: 0 must be fixed, 1 recommended
  - [warning] File naming The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.
```

Without the package, the same command prints the warning that the entry
point could not be resolved offline.

## With a resolver function

If the taxonomy files live elsewhere, in a database, a cache directory or
an unpacked taxonomy, pass `metadata_resolver`: a function from an absolute
URL to the document's bytes, or `None` when it does not know the URL. It is
asked before any taxonomy package.

```python
from zipfile import ZipFile

# Index the taxonomy's files by URL, as a cache of your own would.
with ZipFile("taxonomy.zip") as package:
    documents = {
        "http://" + name.split("/", 1)[1]: package.read(name)
        for name in package.namelist()
        if "/www.eba.europa.eu/" in name
    }


def resolve(url):
    print("resolve", url)
    return documents.get(url)


report = read_report("described.zip", metadata_resolver=resolve)
print(report.facts[0].concept)
```

```text
resolve http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json
resolve http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/tab/c_01.00/c_01.00.json
resolve http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/tab/c_27.00/c_27.00.json
eba_met:mi53
```

The module's `extends` are followed recursively, relative URLs against the
document that names them. The chain is cycle-safe and limited to
`Limits.max_extends_depth` levels.

## What is resolved

Metadata documents merge `namespaces`, `tableTemplates`, `tables`,
`parameters`, `dimensions`, `decimals` and `parameterURL`, with the
extending document taking precedence. The supported subset of xBRL-CSV
table templates is listed in [data formats](../reference/data-formats.md#resolved-metadata).
A table whose template cannot be resolved falls back to the EBA
convention; an unresolved `extends` produces one warning.

Resolving metadata costs time: the EBA COREP own-funds sample reads
several times slower with its metadata than without; see the
[benchmarks](../project/benchmarks.md).
