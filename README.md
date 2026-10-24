<p align="center">
  <a href="https://luukhopman.github.io/dpm-xbrl/"><img src="https://luukhopman.github.io/dpm-xbrl/assets/logo.svg" alt="dpm-xbrl" width="240"></a>
</p>

<p align="center"><em>Read, write and check EBA xBRL-CSV and XBRL-XML reports in Python.</em></p>

Read and write EBA-style regulatory XBRL reports in both serializations,
xBRL-CSV report packages and XBRL 2.1 XML instances, through one neutral
fact model, and find the EBA filing rules a report breaks. It targets
reports built on the data point model (DPM) taxonomies of the European
Banking Authority and is tested on EBA reports.

dpm-xbrl is an independent project, not affiliated with or endorsed by the
European Banking Authority.

## Installation

```text
pip install dpm-xbrl            # standard library only, Python 3.11+
pip install "dpm-xbrl[fast]"    # isal: inflates ZIP entries about twice as fast
pip install "dpm-xbrl[frames]"  # polars: columnar reading of large reports
```

## Quickstart

```python
from dpmxbrl import read_report

report = read_report("report.zip")  # or a directory, report.json, .xbrl, or bytes
print(report.entity_id, report.reference_date, len(report.facts))
for fact in report.facts_for_template("C_28.00"):
    print(fact.datapoint, dict(fact.keys), fact.value)
for finding in report.filing:  # the EBA filing rules the report breaks
    print(finding.severity, finding.rule, finding.code)
```

```text
SYNTHETICDPMXL000002.CON 2025-12-31 14
dp5488013 {'qINC': 'CP0001'} 67129000
dp5488014 {'qINC': 'CP0001'} 60309000
dp5488013 {'qINC': 'CP0002'} 41250000
dp5488014 {'qINC': 'CP0002'} 38900000
warning File naming invalidFileName
```

From the command line, stopping a pipeline when the EBA would reject the
report:

```text
dpm-xbrl inspect report.zip --fail-on error   # exit status 3 on a broken MUST rule
dpm-xbrl convert report.zip instance.xbrl --taxonomy-package taxonomy.zip
```

The sample `report.zip` is in
[`docs/samples`](https://github.com/luukhopman/dpm-xbrl/tree/main/docs/samples).

## Features

- **One fact model for both formats**: frozen `Report` and `Fact`
  dataclasses, with every value as written and its file and line.
- **EBA filing rules**: each report lists the rules of the EBA Filing Rules
  v5.8 that the file breaks, with the rule number, tag, severity and
  locations; with the taxonomy packages also those that need the module,
  such as reference dates, templates and decimals per data type.
- **Millions of facts**: the `frames` extra reads a 7-million-fact package
  into polars frames in about a second.
- **Writing and conversion**: deterministic xBRL-CSV packages and XBRL-XML
  instances that read back as written; with the EBA taxonomy packages,
  XBRL-XML converts to xBRL-CSV and back, about 3 seconds for a
  21,000-fact report.
- **Offline**: nothing is fetched over the network; xBRL-CSV metadata
  resolves through local taxonomy packages.
- **Safe on untrusted input**: resource limits, ZIP and XML hardening, and
  one exception type, `ReportError`.

## Toolkit

**Part of the dpm toolkit**, three Python packages that work together:

| Package | What it does |
| :-- | :-- |
| <a href="https://luukhopman.github.io/dpm-xl/"><img src="https://luukhopman.github.io/dpm-xl/assets/logo.svg" alt="dpm-xl" height="32"></a> | Parse and evaluate DPM-XL validation rules |
| <a href="https://luukhopman.github.io/dpm-xbrl/"><img src="https://luukhopman.github.io/dpm-xbrl/assets/logo.svg" alt="dpm-xbrl" height="32"></a> | Read, write and check xBRL-CSV and XBRL-XML reports **(this package)** |
| <a href="https://luukhopman.github.io/dpm-synth/"><img src="https://luukhopman.github.io/dpm-synth/assets/logo.svg" alt="dpm-synth" height="32"></a> | Generate test reports that satisfy DPM-XL rules |

The [toolkit tour](https://luukhopman.github.io/dpm-xl/guides/toolkit-tour/)
takes one report through all three: generated with dpm-synth, read with
dpm-xbrl, then evaluated and explained with dpm-xl.

## Documentation

**Documentation: <https://luukhopman.github.io/dpm-xbrl/>**

- [Getting started](https://luukhopman.github.io/dpm-xbrl/getting-started/)
- [How-to guides](https://luukhopman.github.io/dpm-xbrl/guides/): read a
  report, large reports, filing rules and CI, conversion, taxonomy
  packages, untrusted uploads, validation with
  [dpm-xl](https://luukhopman.github.io/dpm-xl/)
- [Concepts](https://luukhopman.github.io/dpm-xbrl/concepts/) and
  [reference](https://luukhopman.github.io/dpm-xbrl/reference/), including
  the [Python API](https://luukhopman.github.io/dpm-xbrl/reference/api/) and
  the [CLI](https://luukhopman.github.io/dpm-xbrl/reference/cli/)
- [Known gaps](https://luukhopman.github.io/dpm-xbrl/reference/known-gaps/)
  and [benchmarks](https://luukhopman.github.io/dpm-xbrl/project/benchmarks/)
- For AI agents: [llms.txt](https://luukhopman.github.io/dpm-xbrl/llms.txt)
  and [llms-full.txt](https://luukhopman.github.io/dpm-xbrl/llms-full.txt)
- [Changelog](https://github.com/luukhopman/dpm-xbrl/blob/main/CHANGELOG.md),
  [stability policy](https://luukhopman.github.io/dpm-xbrl/project/stability/)
  and [security policy](https://luukhopman.github.io/dpm-xbrl/project/security/)

## Development

```text
uv sync --all-extras
uv run pytest
uv run ruff check
uv run ruff format --check
uv run ty check
uv run python scripts/build_docs.py
```

See [contributing](https://luukhopman.github.io/dpm-xbrl/project/contributing/).

## Licence

MIT. See [LICENSE](https://github.com/luukhopman/dpm-xbrl/blob/main/LICENSE).
