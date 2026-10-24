---
description: For AI agents and their users - the essential dpm-xbrl API on one page, its contracts, common pitfalls, and the llms.txt files.
---

# Using dpm-xbrl with AI agents

This page is for coding agents that write code *using* dpm-xbrl, and for
people who brief them. It gives the essential API, the contracts to rely on
and the mistakes to avoid. Agents working *on* the dpm-xbrl repository
should read `AGENTS.md` in its root instead.

Machine-readable copies of these docs:

- [`llms.txt`](llms.txt): an index of every page with a one-line
  description ([llmstxt.org](https://llmstxt.org) format).
- [`llms-full.txt`](llms-full.txt): every page in one Markdown file,
  including the API reference.
- Each page as Markdown: replace the trailing `/` of a page URL with
  `.md`, for example
  `https://luukhopman.github.io/dpm-xbrl/guides/read-a-report.md`
  (section index pages are `.../guides/index.md`).

## Essentials

```python
from dpmxbrl import Limits, ReportError, read_report

try:
    # A path, a directory, a report.json, an .xbrl file, or bytes.
    report = read_report("report.zip", limits=Limits())
except ReportError as error:  # the only exception for bad input
    raise SystemExit(f"cannot read: {error}")

report.format  # "xbrl-csv" or "xbrl-xml"
report.entity_id  # "SYNTHETICDPMXL000002.CON"
report.reference_date  # datetime.date(2025, 12, 31)
report.filing_indicators  # {"C_26.00": True, ...}
report.parameters  # {"refPeriod": "2025-12-31", ...}; xBRL-CSV only
report.facts  # tuple[Fact, ...] in file order
report.warnings  # tuple[str, ...]: how the file was read
report.filing  # tuple[FilingFinding, ...]: EBA filing rules broken

for fact in report.facts_for_template("C_28.00"):
    fact.datapoint, fact.keys, fact.value, fact.location
```

| Task | Call |
| --- | --- |
| Read any report | `dpmxbrl.read_report(source, name=None, metadata_resolver=None, taxonomy_packages=(), limits=Limits())` |
| Read one format | `read_xbrl_csv(...)`, `read_xbrl_xml(source, name=None, taxonomy_packages=(), limits=Limits())` |
| Detect the format | `detect_format(source, name=None) -> "xbrl-csv" \| "xbrl-xml"` |
| Millions of facts | `dpmxbrl.frames.read_xbrl_csv_frames(source, ...) -> ReportFrames` (`frames` extra) |
| Write | `write_xbrl_csv(report, target, root=None, taxonomy_packages=(), strict=True) -> SkippedFacts`, `write_xbrl_xml(report, target, typed_domains=None, taxonomy_packages=())` |
| Convert | Read, then write with `taxonomy_packages`, or `dpm-xbrl convert IN OUT --taxonomy-package ZIP` |
| Avoid duplicate findings | `dpmxbrl.filing.CHECKED_RULES[mode]`: the `(rule, code)` pairs a reader checks |
| Gate on filing rules | `[f for f in report.filing if f.severity == "error"]`, or `dpm-xbrl inspect PATH --fail-on error` (exit 3) |
| Add findings | `dpmxbrl.filing.FilingLog`: `.extend(report.filing)`, `.add(*rule_tuple, location)`, `.result()` |
| Change a report | `dataclasses.replace(report, filing=..., entry_point=...)` |

## Contracts

- Every unreadable, unsafe or over-limit input raises `ReportError`, a
  `ValueError`. Anything else is a bug.
- `Report`, `Fact`, `FilingFinding` and `Limits` are frozen dataclasses.
  `Fact.dimensions`, `typed_dimensions` and `keys` are read-only dicts that
  facts may share; `dict(fact.keys)` makes a mutable copy.
- `Fact.value` is the lexical string from the file, or `None` for nil.
  Nothing is converted to numbers or dates.
- Match findings on `FilingFinding.rule` and `.code`, which are stable;
  never on `.message`, which may be reworded.
- `inspect --json` output carries `schema_version` (1); it changes only
  with a major version.
- Nothing is fetched over the network.
- Readers and writers are thread-safe; results are immutable.

## Pitfalls

- **Facts of EBA-convention CSV have no concept.** Without
  `taxonomy_packages`, `Fact.concept`, `dimensions`, `unit` and `decimals`
  are empty; use `datapoint`, `keys` and `report.decimals_parameters`.
  The warning "could not be resolved offline" is expected, not an error.
- **XML facts have no datapoint or template.** `facts_for_template` returns
  nothing for XML reports; identify XML facts by `concept` and `dimensions`.
- **Template ids are not filing indicators.** A file `c_07.00.a.csv` has
  `Fact.template == "c_07.00.a"`, filed as `C_07.00`;
  `facts_for_template` matches either, ignoring case, and
  `filing_indicator_code` maps one to the other. See
  [table codes and filing indicators](concepts/filing-indicators.md).
- **Warnings are not filing findings.** Gate on `report.filing`, not on
  `report.warnings`.
- **Conversion needs the taxonomy packages.** Without them, EBA-convention
  CSV cannot be written as XML, and XML cannot be written as CSV. See
  [convert between formats](guides/convert-formats.md).
- **Taxonomy checks need the packages.** 1.5 (published entry point and
  reference dates), 1.6 (each template), 1.6.3, 2.18, 3.2 (b) and 3.5 are
  checked only with `taxonomy_packages`.
- **Bytes need a name.** Pass `name=` with the real file name when reading
  bytes, or the file-naming rule checks `<bytes>`.
- **Large reports.** `read_report` costs about 5 µs and 0.7 KB per fact.
  Above a few million facts use `read_xbrl_csv_frames`, and raise `Limits`
  for trusted packages over 512 MiB per file.
- **Columnar reading checks less.** It checks special fact values only, and
  raises `MetadataTablesError` for metadata-described tables; fall back to
  `read_report`.
- **The garbage collector is paused process-wide** while facts are built.
  Do not rely on cyclic collection in other threads during a read.

## Where to look next

- [Getting started](getting-started.md) for a guided first use.
- [Python API](reference/api/index.md) for every signature.
- [CLI](reference/cli.md) and [JSON output](reference/json-output.md).
- [Filing rules checked](reference/filing-rules.md) and
  [known gaps](reference/known-gaps.md).
