---
description: Accept report uploads from users safely, with resource limits, ZIP and XML hardening, and one exception type to catch.
---

# Handle untrusted uploads

Reports often come from outside: an upload form, a supervisor's portal, an
e-mail attachment. dpm-xbrl is built to read them safely. This guide shows
the settings that matter; [the security model](../concepts/security.md)
explains what is protected and why.

## Read bytes, catch `ReportError`

Read the upload's bytes directly, with `name=` set to the uploaded file
name, and catch [`ReportError`][dpmxbrl.ReportError]. Every problem with the
input raises it, so one handler covers malformed files, unsafe archives and
inputs over a limit:

```python
from dpmxbrl import Limits, ReportError, read_report


def accept(data: bytes, filename: str) -> str:
    try:
        report = read_report(data, name=filename, limits=Limits(max_facts=1_000_000))
    except ReportError as error:
        return f"rejected: {error}"
    errors = [finding for finding in report.filing if finding.severity == "error"]
    return f"accepted: {len(report.facts)} facts, {len(errors)} filing errors"


with open("report.zip", "rb") as upload:
    print(accept(upload.read(), "report.zip"))
print(accept(b"PK\x03\x04 truncated", "broken.zip"))
print(
    accept(
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>',
        "evil.xbrl",
    )
)
```

```text
accepted: 14 facts, 0 filing errors
rejected: broken.zip is not a readable ZIP archive: it may be incomplete or damaged
rejected: evil.xbrl: DOCTYPE and ENTITY declarations are not allowed
```

Messages name the file and, where known, the line, and are safe to show to
the person who uploaded it. They contain no stack traces and no paths other
than the names inside the upload.

## Set the limits

[`Limits`][dpmxbrl.Limits] caps the resources one read may use. The
defaults suit reports from regular reporting; tighten them for a public
upload form:

| Field | Default | Caps |
| --- | --- | --- |
| `max_zip_entries` | 10,000 | entries in a report package ZIP |
| `max_total_size` | 2 GiB | total uncompressed size of a package |
| `max_file_size` | 512 MiB | uncompressed size of one file, including an XML instance and files read from taxonomy packages |
| `max_facts` | 20,000,000 | facts in one report |
| `max_extends_depth` | 32 | nesting of xBRL-CSV `extends` |
| `max_taxonomy_entries` | 100,000 | entries in one taxonomy package ZIP (the EBA's reporting frameworks package has about 17,400) |

Each limit raises `ReportError` when exceeded, before the data is inflated
or the facts are built:

```python
for limits in (
    Limits(max_facts=10),
    Limits(max_zip_entries=5),
    Limits(max_file_size=100),
    Limits(max_total_size=500),
):
    try:
        read_report("report.zip", limits=limits)
    except ReportError as error:
        print(error)
```

```text
reports/c_28.00.csv:2: report exceeds the limit of 10 facts
report.zip: 8 ZIP entries exceed the limit of 5
report.zip: entry 'report/reports/report.json' exceeds the maximum file size of 100 bytes
report.zip: uncompressed size exceeds the limit of 500 bytes
```

`Limits` is a frozen dataclass; derive one from the defaults with
`dataclasses.replace(Limits(), max_facts=1_000_000)`.

## Raise the limits for large trusted reports

The largest EBA packages hold tens of millions of facts in files over
512 MiB. For reports you trust, raise the limits; from the command line,
`--max-facts`, `--max-file-size`, `--max-total-size` and
`--max-zip-entries` do the same, and a limit error names the option:

```console
$ dpm-xbrl inspect report.zip --max-facts 10
error: reports/c_28.00.csv:2: report exceeds the limit of 10 facts
hint: --max-facts raises the limit
$ echo $?
1
```

A 21.9-million-fact package with one 587 MB table needs
`--max-file-size 1000000000 --max-total-size 4000000000 --max-facts 30000000`.

## What else is rejected

Report packages are rejected for entry names that are absolute or contain
`..`, duplicate entries and encrypted entries; package directories for
links that leave the directory. XML instances are scanned before parsing,
and any DOCTYPE, and with it any entity declaration, is rejected. Nothing
is ever fetched over the network.

```python
import io
from zipfile import ZipFile

buffer = io.BytesIO()
with ZipFile(buffer, "w") as archive:
    archive.writestr("../evil/reports/report.json", "{}")
try:
    read_report(buffer.getvalue(), name="upload.zip")
except ReportError as error:
    print(error)
```

```text
upload.zip: unsafe parent-relative entry '../evil/reports/report.json'
```

## Run reads in a separate process

Limits bound one read, not the whole process. For a public service, run
reads in a worker process with an operating-system memory limit and a
timeout as well, so one hostile upload cannot slow other requests. Readers
pause the cyclic garbage collector for the whole process while they build
facts, which is another reason to keep them out of a latency-sensitive
server process.
