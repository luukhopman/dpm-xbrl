---
description: What dpm-xbrl is, who it is for, a 30-second example, installation and where to go next.
---

# dpm-xbrl

dpm-xbrl reads and writes EBA-style regulatory XBRL reports in both
serializations, xBRL-CSV report packages and XBRL 2.1 XML instances, through
one neutral fact model. While it reads, it records the
[EBA Filing Rules][eba-filing-rules] that the report breaks and that the file
alone can show.

It targets reports built on the data point model (DPM) taxonomies of the
European Banking Authority and is tested on EBA reports. It uses only the
standard library and needs Python 3.11 or newer.

!!! note "Independent project"

    dpm-xbrl is an independent project, not affiliated with or endorsed by
    the EBA.

## Who it is for

- Teams that receive, produce or archive EBA reports (COREP, FINREP, large
  exposures, resolution, remuneration and the other DPM frameworks) and
  need the facts in Python.
- Pipelines that must stop a report the EBA would reject before it is sent.
- Rule engines, such as [dpm-xl], that evaluate validation rules on the
  facts of a report.

## In 30 seconds

```python
from dpmxbrl import read_report

report = read_report("report.zip")  # or a directory, report.json, .xbrl, or bytes
print(report.entity_id, report.reference_date, len(report.facts))
for fact in report.facts_for_template("C_28.00"):
    print(fact.datapoint, dict(fact.keys), fact.value)
```

```text
529900T8BM49AURSDO55.CON 2025-12-31 14
dp5488013 {'qINC': 'CP0001'} 67129000
dp5488014 {'qINC': 'CP0001'} 60309000
dp5488013 {'qINC': 'CP0002'} 41250000
dp5488014 {'qINC': 'CP0002'} 38900000
```

The same report from the command line, with the filing rules it breaks:

```console
$ dpm-xbrl inspect report.zip
Format:            xbrl-csv
Entry point:       http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json
Entity:            529900T8BM49AURSDO55.CON (https://eurofiling.info/eu/rs)
Reference date:    2025-12-31
Base currency:     iso4217:EUR
Filing indicators: 4 reported of 5
Facts:             14
  c_00.01  2
  c_26.00  4
  c_27.00  4
  c_28.00  4
Warnings: 1
  - reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json); tables without resolved metadata use the EBA datapoint/factValue convention
EBA filing rules broken: 0 must be fixed, 1 recommended
  - [warning] File naming The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.
```

The sample report is [`report.zip`](samples/report.zip). Every example in
these pages runs against the files in
[`docs/samples`](https://github.com/luukhopman/dpm-xbrl/tree/main/docs/samples),
and the test suite checks that each prints what is shown.

## Install

```text
pip install dpm-xbrl            # standard library only
pip install "dpm-xbrl[fast]"    # isal: inflates ZIP entries about twice as fast
pip install "dpm-xbrl[frames]"  # polars: columnar reading of large reports
```

The `fast` extra changes speed only; the bytes read are the same either way.

## Key features

- **One fact model for both formats.** [`Report`][dpmxbrl.Report] and
  [`Fact`][dpmxbrl.Fact] are frozen dataclasses; see
  [the fact model](concepts/fact-model.md).
- **EBA filing rules.** Each report carries the filing rules it breaks, with
  the rule number, the EBA tag, a severity and locations; see
  [check EBA filing rules](guides/check-filing-rules.md).
- **Millions of facts.** The `frames` extra reads a 7-million-fact package
  into polars frames in about a second; see
  [read large reports as frames](guides/large-reports.md).
- **Writing.** Deterministic xBRL-CSV packages and XBRL-XML instances that
  read back as written; see [convert between formats](guides/convert-formats.md).
- **Offline.** Nothing is fetched over the network; xBRL-CSV metadata
  resolves through local taxonomy packages; see
  [resolve metadata offline](guides/taxonomy-packages.md).
- **Safe on untrusted input.** Resource limits, ZIP and XML hardening, and a
  single exception type; see [the security model](concepts/security.md).

## Where next

- New here: the [getting started](getting-started.md) tutorial.
- A task to do: the [how-to guides](guides/index.md).
- How it works: the [concepts](concepts/index.md).
- Exact behaviour: the [reference](reference/index.md), including the
  [API](reference/api/dpmxbrl.md) and the [command line](reference/cli.md).
- Working with an AI agent: [dpm-xbrl for AI agents](agents.md),
  [`llms.txt`](llms.txt) and [`llms-full.txt`](llms-full.txt).
