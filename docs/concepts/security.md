---
description: What dpm-xbrl protects against when reading untrusted reports (resource limits, ZIP and XML hardening, no network), and its thread-safety guarantees.
---

# Security model

dpm-xbrl assumes that a report file may be hostile: crafted to exhaust
memory, escape a directory, or make the parser read local files. It
protects the process reading it as follows. To use these protections, see
[handle untrusted uploads](../guides/untrusted-input.md).

## One error type

Every input that cannot be read safely raises
[`ReportError`][dpmxbrl.ReportError], a `ValueError`. Other exceptions
from reading are bugs. Messages name the file and, where known, the line or
entry, and never include data from outside the input.

## Resource limits

[`Limits`][dpmxbrl.Limits] bounds a read: entries in a ZIP, total and
per-file uncompressed size, facts, and the depth of xBRL-CSV `extends`.
Sizes are checked against the ZIP's directory before anything is inflated,
and inflation never produces more than an entry declares, so an entry that
understates its size is rejected rather than inflated without bound. The file-size limit
also applies to XML instances and to files read from taxonomy packages.

## ZIP packages and directories

- Entry names that are absolute or contain `..` are rejected, as are
  duplicate and encrypted entries and unsupported compression methods.
- Entries are read straight from the ZIP; nothing is extracted to disk.
- A package directory is rejected if a link leaves it, and each file is
  checked again when it is opened.
- An entry with damaged compressed data raises `ReportError` naming it.

## XML

The prolog is scanned before parsing, including for UTF-16 without a byte
order mark, and any DOCTYPE, and with it any ENTITY declaration, is
rejected. External entities are therefore never resolved, and entity
expansion attacks cannot start. Parsing streams with `iterparse`.

XML from taxonomy packages (catalogs, `taxonomyPackage.xml` and schemas)
gets the same prolog scan, with one difference: a DOCTYPE that only names
an external DTD, as the EBA's catalogs name the OASIS catalog DTD, is
allowed, because the DTD is never loaded. A DOCTYPE with an internal
subset, where ENTITY declarations live, any other declaration and an
unknown encoding raise `ReportError`.

## JSON

Duplicate keys are rejected rather than silently resolved, and documents
nested too deeply raise `ReportError` instead of `RecursionError`.

## No network

Nothing is fetched over the network. Metadata URLs resolve only through a
`metadata_resolver` you supply and the catalogs of local taxonomy packages.

## Thread safety

- Readers and writers keep no shared state: each call reads its own input
  and returns new objects, so threads may call them concurrently.
- `Report`, `Fact`, `FilingFinding` and `Limits` are frozen, and the
  mappings of read facts are read-only, so results can be shared between
  threads without copying.
- While a reader builds facts it pauses the cyclic garbage collector for
  the whole process. Concurrent reads share the pause, and the collector
  is re-enabled when the last one ends, if it was enabled before the
  first. Other threads run without cyclic collection meanwhile.
- `FilingLog` is not synchronized; use one per thread.
- The frames reader calls `on_metadata` and `on_table` on the calling
  thread.

## Reporting a vulnerability

See the [security policy](../project/security.md).
