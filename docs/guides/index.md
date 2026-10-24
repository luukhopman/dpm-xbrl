---
description: Task-oriented recipes for dpm-xbrl - reading, large reports, filing rules and CI, findings, conversion, taxonomy packages, uploads, dpm-xl.
---

# How-to guides

Recipes for specific tasks. Each assumes you have dpm-xbrl installed and
know what a report is; the [getting started](../getting-started.md)
tutorial covers the basics. Every example runs against the files in
[`docs/samples`](../samples/report.zip).

| Guide | Use it to |
| --- | --- |
| [Read a report](read-a-report.md) | Read paths, directories, bytes and XML instances; handle errors and warnings. |
| [Read large reports as frames](large-reports.md) | Read packages with millions of facts into polars frames in seconds. |
| [Check EBA filing rules](check-filing-rules.md) | List the filing rules a report breaks and stop a CI pipeline with `--fail-on`. |
| [Add your own filing findings](add-filing-findings.md) | Record taxonomy-aware findings next to the ones the readers make. |
| [Convert between formats](convert-formats.md) | Write xBRL-CSV packages and XBRL-XML instances. |
| [Resolve metadata offline](taxonomy-packages.md) | Read concepts, dimensions and units from local taxonomy packages. |
| [Handle untrusted uploads](untrusted-input.md) | Accept reports from users safely, with limits and one error type. |
| [Validate a report with dpm-xl](validate-with-dpm-xl.md) | Evaluate DPM-XL validation rules on the facts of a report. |
