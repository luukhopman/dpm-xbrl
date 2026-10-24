---
description: Tutorial - install dpm-xbrl, inspect a sample report, read its facts in Python and find the EBA filing rules it breaks.
---

# Getting started

This tutorial takes you from installing dpm-xbrl to reading a report,
looking at its facts and finding the EBA filing rules it breaks. It takes
about ten minutes.

## Install

dpm-xbrl needs Python 3.11 or newer and has no required dependencies.

```text
pip install dpm-xbrl
```

or, in a project managed with [uv](https://docs.astral.sh/uv/):

```text
uv add dpm-xbrl
```

Check the installed version:

<!-- docs: skip -->
```console
$ dpm-xbrl --version
dpm-xbrl 1.0.0
```

## Get a sample report

Download two small sample reports into an empty folder:

- [`report.zip`](samples/report.zip): a COREP large-exposures report as an
  xBRL-CSV report package, written in the EBA's `datapoint`/`factValue`
  convention.
- [`needs_fixes.zip`](samples/needs_fixes.zip): the same report with mistakes
  the EBA would reject.

An xBRL-CSV report package is a ZIP holding a few JSON and CSV files:

```python
from zipfile import ZipFile

print(*ZipFile("report.zip").namelist(), sep="\n")
```

```text
report/META-INF/reportPackage.json
report/reports/report.json
report/reports/parameters.csv
report/reports/FilingIndicators.csv
report/reports/c_00.01.csv
report/reports/c_26.00.csv
report/reports/c_27.00.csv
report/reports/c_28.00.csv
```

`parameters.csv` names the reporting entity and the reference date,
`FilingIndicators.csv` says which templates are reported, and each other
CSV file is one table of facts.

## Inspect it from the command line

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

Two things to notice:

- The warning says the taxonomy's metadata was not available offline, so
  the tables were read in the EBA `datapoint`/`factValue` convention. That
  is normal and enough for most uses; see
  [EBA convention and resolved metadata](concepts/metadata.md).
- The only filing rule broken is a recommendation: EBA report files are
  named `ReportSubject_Country_..._CreationTimestamp`, and `report.zip` is
  not.

## Read it in Python

```python
from dpmxbrl import read_report

report = read_report("report.zip")
print(report.format, report.entity_id, report.reference_date)
print(report.filing_indicators)
```

```text
xbrl-csv 529900T8BM49AURSDO55.CON 2025-12-31
{'C_00.01': True, 'C_26.00': True, 'C_27.00': True, 'C_28.00': True, 'C_29.00': False}
```

[`read_report`][dpmxbrl.read_report] detects the format, so the same call
reads an XBRL-XML instance. It returns a [`Report`][dpmxbrl.Report], a frozen
dataclass with the report's header and a tuple of facts.

## Look at the facts

Each [`Fact`][dpmxbrl.Fact] carries its value as written and where it came
from:

```python
fact = report.facts[2]
print(fact.datapoint, fact.value, fact.template, fact.location)
```

```text
dp457468 56058000 c_26.00 reports/c_26.00.csv:2
```

Open tables have key columns, which identify the row, for example the
counterparty of a large exposure:

```python
for fact in report.facts_for_template("C_27.00"):
    print(fact.datapoint, fact.keys["qINC"], fact.value)
```

```text
dp5486584 CP0001 Northwind Holdings
dp5485645 CP0001 eba_NC:DE
dp5486584 CP0002 Contoso Group
dp5485645 CP0002 eba_NC:FR
```

`facts_for_template` takes the code of a filing indicator (`C_27.00`) and
compares it case-insensitively with the table template (`c_27.00`).

Values are strings exactly as written. The decimals that apply to a numeric
value are report parameters in this convention:

```python
print(report.decimals_parameters)
```

```text
{'decimalsInteger': 0, 'decimalsMonetary': -3, 'decimalsPercentage': 4}
```

## Find the filing rules a report breaks

`needs_fixes.zip` contains four mistakes. Each broken rule is a
[`FilingFinding`][dpmxbrl.FilingFinding] in `Report.filing`:

```python
broken = read_report("needs_fixes.zip")
for finding in broken.filing:
    print(
        f"{finding.severity:7} {finding.rule:11} {finding.code:31} {finding.examples}"
    )
```

```text
error   2.19        nilUsed                         ('reports/c_26.00.csv:3',)
warning 3.11        leadingOrTrailingSpacesInText   ('reports/c_27.00.csv:2', 'reports/c_27.00.csv:3')
error   xBRL-CSV 1  decimalsSuffixUsed              ('reports/c_26.00.csv:2',)
error   xBRL-CSV 6  tableForNegativeFilingIndicator ('reports/c_29.00.csv',)
warning File naming invalidFileName                 ('needs_fixes.zip',)
```

An `error` is a rule the EBA states with MUST: the report would be
rejected. A `warning` is a SHOULD. The command line can stop a pipeline on
them with `--fail-on`, which exits with status 3:

```console
$ dpm-xbrl inspect needs_fixes.zip --fail-on error
Format:            xbrl-csv
Entry point:       http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json
Entity:            529900T8BM49AURSDO55.CON (https://eurofiling.info/eu/rs)
Reference date:    2025-12-31
Base currency:     iso4217:EUR
Filing indicators: 4 reported of 5
Facts:             13
  c_00.01  2
  c_26.00  4
  c_27.00  2
  c_28.00  4
  c_29.00  1
Warnings: 1
  - reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.json); tables without resolved metadata use the EBA datapoint/factValue convention
EBA filing rules broken: 3 must be fixed, 2 recommended
  - [error] 2.19 Facts must not be reported as #nil; leave out a fact that is not reported.
  - [warning] 3.11 Key values should not start or end with spaces or line breaks. (2 times)
  - [error] xBRL-CSV 1 Fact values must not use the decimals suffix (such as 78920030d-4); decimals belong in parameters.csv.
  - [error] xBRL-CSV 6 The package must not contain the table file of a template whose filing indicator is false.
  - [warning] File naming The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.
$ echo $?
3
```

## Next steps

- [Read a report](guides/read-a-report.md) from bytes, a directory or an
  XML instance.
- [Check EBA filing rules](guides/check-filing-rules.md) and gate a CI
  pipeline.
- [Read large reports as frames](guides/large-reports.md) when a report has
  millions of facts.
- [Validate a report with dpm-xl](guides/validate-with-dpm-xl.md): evaluate
  the EBA validation rules on the facts.
- Learn [the fact model](concepts/fact-model.md).
