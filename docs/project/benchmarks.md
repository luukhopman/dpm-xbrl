---
description: How dpm-xbrl compares with eba-xbridge, Arelle, py-xbrl and brel-xbrl on EBA reports - a capability matrix and reproducible timings.
---

# Benchmarks

This page compares dpm-xbrl with the Python packages people consider for
the same job: [eba-xbridge](https://pypi.org/project/eba-xbridge/),
[Arelle](https://pypi.org/project/arelle-release/),
[py-xbrl](https://pypi.org/project/py-xbrl/) and
[brel-xbrl](https://pypi.org/project/brel-xbrl/). They differ in scope, so
the capability matrix comes first; the timings only compare tasks that
several tools do.

Every number on this page comes from the scripts in
[`benchmarks/`](https://github.com/luukhopman/dpm-xbrl/tree/main/benchmarks),
which anyone can re-run; the README there explains the setup.

## Capabilities

Rows above the line are dpm-xbrl's job; rows below help you choose a tool
for work dpm-xbrl does not do.

<!-- Keep in step with the code: conversion and filing-check rows change
     when dpm-xbrl gains those features. -->

| | dpm-xbrl | eba-xbridge | Arelle | py-xbrl | brel-xbrl |
| --- | --- | --- | --- | --- | --- |
| Read EBA XBRL-XML instances | yes | yes | yes, with the EBA taxonomy | no: cannot find the DPM 2.0 taxonomy | no: downloads the taxonomy, runs out of memory |
| Read EBA xBRL-CSV report packages | yes | no (validates them) | yes, with the EBA taxonomy | no | no |
| Read without the taxonomy | yes | yes, with bundled module metadata | no | no | no |
| Millions of facts in seconds | yes, `frames` extra | no | no | no | no |
| Write xBRL-CSV from XBRL-XML | no | yes | not evaluated | no | no |
| Write XBRL-XML from xBRL-CSV | yes, with taxonomy packages and typed domains | no | not evaluated | no | no |
| EBA filing rules checked from the file | v5.8, in the same pass as reading; [list](../reference/filing-rules.md) | yes, including taxonomy-aware checks (module dates, known entry points, canonical prefixes, rate notation) | EBA plugin for an older filing-rules version | no | no |
| Findings with EBA rule numbers and tags | yes | yes, with its own codes | yes, error codes | no | no |
| Reports every structural problem of a broken file | no: stops at the first fatal one | yes, as coded findings | not evaluated | not evaluated | not evaluated |
| CLI with JSON output and a CI exit status | yes (`--json`, `--fail-on`) | JSON output (`xbridge validate`); exit status not evaluated | full CLI; not evaluated for CI | no | no |
| Resource limits and DOCTYPE rejection for untrusted input | yes | not evaluated | not evaluated | not evaluated | not evaluated |
| Works offline | yes | yes | yes, with local packages | no | no |
| Runtime dependencies | none (optional polars, isal) | lxml, numpy, pandas | 15, including lxml, numpy, openpyxl, pillow | requests, urllib3 | 17 pinned, including pandas, pyspark, lxml |
| **Out of dpm-xbrl's scope** | | | | | |
| Taxonomy-driven XBRL validation (schemas, dimensions, calculations) | no | no | yes | not evaluated | not evaluated |
| EBA validation rules on report values | no; use [dpm-xl] | no | yes, as XBRL formula from the taxonomy (minutes and gigabytes per report) | no | no |
| OneGate envelope unwrapping | no | yes | no | no | no |
| Other XBRL filings, such as SEC and ESEF | no | no | yes | yes, its focus | yes, its focus (SEC) |

"Not evaluated" means the benchmark did not test it; it is not a claim
that the tool lacks it.

## Timings

--8<-- "benchmarks/results.md"

## What the numbers mean

- **XML.** dpm-xbrl and eba-xbridge read the same facts from every EBA XML
  sample (the fact counts and the (concept, value, decimals) multisets
  agree on COREP and FINREP); Arelle counts the filing indicators as facts
  too. Arelle needs the taxonomy to load a report at all, which is what
  makes it slow and large here; in return it validates the report against
  the taxonomy.
- **xBRL-CSV.** Only dpm-xbrl and Arelle read xBRL-CSV report packages.
  dpm-xbrl reads the EBA convention without the taxonomy; resolving the
  taxonomy's metadata, for concepts and dimensions, costs extra time.
- **Millions of facts.** `read_xbrl_csv_frames` reads an EBA package with
  one open table of millions of rows as polars frames. `read_report`
  builds one Python object per fact, about 5 µs and 0.7 KB each, and
  pauses the cyclic garbage collector while it does.
- **Filing rules.** dpm-xbrl and eba-xbridge agree on the rules both
  check. eba-xbridge checks more rules that need the module's metadata,
  such as the reference date against the module's dates; dpm-xbrl checks
  LEI check digits, which eba-xbridge does not.

## Reproduce

```text
git clone https://github.com/luukhopman/dpm-xbrl
cd dpm-xbrl
# set up benchmarks/.venvs as in benchmarks/README.md, then:
uv run python benchmarks/run.py --samples SAMPLES --taxonomy TAXONOMY --coverage
python benchmarks/render.py
uv run python scripts/build_docs.py
```
