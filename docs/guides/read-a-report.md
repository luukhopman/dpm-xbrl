---
description: Read reports from paths, directories, report.json and bytes; use the facts; handle ReportError and warnings; read in threads.
---

# Read a report

[`read_report`][dpmxbrl.read_report] reads both formats and returns a
[`Report`][dpmxbrl.Report]. This guide shows the inputs it accepts, how to
label input that has no file name, and how to handle failures.

## From a path

```python
from dpmxbrl import read_report

package = read_report("report.zip")  # xBRL-CSV report package
instance = read_report("instance.xbrl")  # XBRL-XML instance
print(package.format, len(package.facts))
print(instance.format, len(instance.facts))
```

```text
xbrl-csv 14
xbrl-xml 3
```

A ZIP (by content, whatever its suffix), a directory and a `.json` path are
read as xBRL-CSV; anything else as XBRL-XML.
[`detect_format`][dpmxbrl.detect_format] tells you which without reading the
report:

```python
from dpmxbrl import detect_format

print(detect_format("report.zip"), detect_format("instance.xbrl"))
```

```text
xbrl-csv xbrl-xml
```

An unpacked package works too: pass its directory, or the path of its
`report.json`.

```python
from zipfile import ZipFile

ZipFile("report.zip").extractall("unpacked")
print(len(read_report("unpacked/report").facts))
print(len(read_report("unpacked/report/reports/report.json").facts))
```

```text
14
14
```

## From bytes

Uploads and message queues hand over bytes. Pass them directly, with
`name=` to label messages and locations the way the file would be:

```python
from pathlib import Path

data = Path("report.zip").read_bytes()
report = read_report(data, name="529900T8BM49AURSDO55.CON_upload.zip")
print(report.filing[0].examples)
```

```text
('529900T8BM49AURSDO55.CON_upload.zip',)
```

The name matters for the EBA file-naming rule, which checks the file name.
Without `name=`, ZIP bytes are labelled `<bytes>` and XML bytes
`instance.xbrl`.

## Use the facts

Facts are frozen dataclasses. Their mappings (`dimensions`,
`typed_dimensions`, `keys`) are read-only and may be shared between facts;
copy one with `dict()` to change it.

```python
fact = instance.facts[2]
print(fact.concept, fact.value)
print(fact.dimensions, fact.typed_dimensions)
labels = dict(fact.dimensions)
labels["note"] = "copied"
```

```text
eba_met:qNCO Northwind Holdings
{'eba_dim:qNCO': 'eba_qCO:qx2000'} {'eba_dim:qINC': 'CP0001'}
```

Facts and reports pickle, copy and convert to plain data:

```python
import dataclasses
import json

print(json.dumps(dataclasses.asdict(package.facts[4])))
```

```text
{"value": "86911000", "concept": null, "datapoint": "dp32026", "template": "c_26.00", "dimensions": {}, "typed_dimensions": {}, "keys": {}, "unit": null, "decimals": null, "location": "reports/c_26.00.csv:4"}
```

To group facts by template, use `Report.facts_for_template` with the
filing-indicator code. It compares codes case-insensitively; see
[table codes and filing indicators](../concepts/filing-indicators.md) for
how table files map to filing indicators.

## Handle failures

Every input that cannot be read raises [`ReportError`][dpmxbrl.ReportError],
a `ValueError`, naming the file and, where known, the line:

```python
from dpmxbrl import ReportError

for source in ("missing.zip", b"<xbrli:xbrl"):
    try:
        read_report(source)
    except ReportError as error:
        print(error)
```

```text
missing.zip: no such file or directory
instance.xbrl:1:0: malformed XML (unclosed token: line 1, column 0)
```

Catch `ReportError` alone: damaged ZIPs, unsafe entries, malformed JSON,
CSV and XML, and inputs over a [limit](untrusted-input.md) all raise it.

## Read the warnings

Problems that do not stop the read are kept in `Report.warnings`, in a
deterministic order, and repeated findings are aggregated with a count and
the first location:

```python
for warning in package.warnings:
    print(warning)
```

```text
reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json); tables without resolved metadata use the EBA datapoint/factValue convention
```

Warnings describe how the file was read; the EBA filing rules the report
breaks are in `Report.filing` instead. See
[check EBA filing rules](check-filing-rules.md).

## Read several reports at once

Readers share no state, so threads can read several reports at once. Large
packages are mostly CPU-bound Python work, so processes scale better for
many big reports:

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor() as pool:
    reports = list(pool.map(read_report, ["report.zip", "instance.xbrl"]))
print([len(item.facts) for item in reports])
```

```text
[14, 3]
```

While a reader builds facts it pauses Python's cyclic garbage collector for
the whole process and restores it afterwards; see
[performance](../concepts/fact-model.md#memory-and-speed).
