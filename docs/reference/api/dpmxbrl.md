---
description: API reference for the dpmxbrl package - read_report, the readers and writers, Report, Fact, FilingFinding, Limits and ReportError.
---

# `dpmxbrl`

The top-level package: readers, writers and the fact model. Everything on
this page is in `dpmxbrl.__all__` and covered by the
[stability policy](../../project/stability.md). The model classes are
defined in `dpmxbrl.model` and re-exported here; import them from
`dpmxbrl`.

All functions are safe to call from several threads at once: each call
works on its own input and returns immutable results. See
[thread safety](../../concepts/security.md#thread-safety).

## Reading

::: dpmxbrl.read_report

::: dpmxbrl.read_xbrl_csv

::: dpmxbrl.read_xbrl_xml

::: dpmxbrl.detect_format

## Writing

::: dpmxbrl.write_xbrl_csv

::: dpmxbrl.write_xbrl_xml

::: dpmxbrl.default_package_root

::: dpmxbrl.SkippedFacts

::: dpmxbrl.SkippedFact

::: dpmxbrl.EntryPointWarning

## Model

::: dpmxbrl.Report

::: dpmxbrl.Fact

::: dpmxbrl.FilingFinding

::: dpmxbrl.Limits

::: dpmxbrl.ReportError

::: dpmxbrl.ReportFormat

::: dpmxbrl.Severity

::: dpmxbrl.local_name

::: dpmxbrl.filing_indicator_code

## Version

::: dpmxbrl.__version__
