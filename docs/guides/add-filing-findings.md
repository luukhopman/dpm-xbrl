---
description: Record taxonomy-aware filing findings with FilingLog and the rule tuples, including the checks the columnar reader leaves to callers.
---

# Add your own filing findings

The readers check the filing rules that the report file alone can show,
and, given taxonomy packages, those that need the module's templates and
data types. Other rules, and checks from your own sources, are left to
you. This guide shows how to record your findings in the same form, so
that one list holds them all; check
[`checked_rules`][dpmxbrl.filing.checked_rules] so as not to repeat one
the reader made.

## Record findings with `FilingLog`

[`FilingLog`][dpmxbrl.filing.FilingLog] collects findings, counts repeats
and keeps up to five locations per finding. A finding is identified by a
[`Rule`][dpmxbrl.filing.Rule] tuple: the rule number, the EBA tag, the
severity and the message.

Rule 1.6 requires a filing indicator for every template of the module.
The readers check it with taxonomy packages; without them, or with a list
of templates from elsewhere, such as the DPM database, the check is yours:

```python
import dataclasses

from dpmxbrl import read_report
from dpmxbrl.filing import FilingLog, Rule

# The module's templates, from your copy of the taxonomy.
MODULE_TEMPLATES = {"C_00.01", "C_26.00", "C_27.00", "C_28.00", "C_29.00", "C_30.00"}
MISSING_INDICATOR: Rule = (
    "1.6",
    "missingFilingIndicator",
    "error",
    "Each template of the module must have a filing indicator.",
)

report = read_report("report.zip")
log = FilingLog()
log.extend(report.filing)  # keep what the reader found
for template in sorted(MODULE_TEMPLATES - set(report.filing_indicators)):
    log.add(*MISSING_INDICATOR, template)

report = dataclasses.replace(report, filing=log.result())
for finding in report.filing:
    print(finding.severity, finding.rule, finding.code, finding.examples)
```

```text
error 1.6 missingFilingIndicator ('C_30.00',)
warning File naming invalidFileName ('report.zip',)
```

`log.result()` returns the findings sorted in rule order, the same order
the readers use. [`sort_findings`][dpmxbrl.filing.sort_findings] sorts any
other iterable of findings the same way.

Use the rule number from [`RULE_TITLES`][dpmxbrl.filing.RULE_TITLES] and
the tag from the [EBA Filing Rules][eba-filing-rules]; the tag above is
illustrative. Severity is `error` for a MUST rule and `warning` for a
SHOULD rule.

`FilingLog.add` takes an optional location and a `count`, for when you
count occurrences without keeping each location:

```python
log = FilingLog()
log.add(*MISSING_INDICATOR, "C_30.00")
log.add(*MISSING_INDICATOR, "C_30.00")  # the same location is kept once
log.add(*MISSING_INDICATOR, count=3)
(finding,) = log.result()
print(finding.count, finding.examples)
```

```text
5 ('C_30.00',)
```

## Spaces around string values

Rule 3.11 forbids leading and trailing spaces in string values, but only
for string data points, so the readers check key values and leave fact
values to you. [`SPACES`][dpmxbrl.filing.SPACES] is the rule tuple:

```python
from dpmxbrl.filing import SPACES

STRING_DATAPOINTS = {"dp5486584"}  # from the taxonomy's data types

log = FilingLog()
for fact in read_report("report.zip").facts:
    if fact.datapoint in STRING_DATAPOINTS and fact.value != (fact.value or "").strip():
        log.add(*SPACES, fact.location)
print(log.result())
```

```text
()
```

## Checks the columnar reader leaves to you

[`read_xbrl_csv_frames`][dpmxbrl.frames.read_xbrl_csv_frames] checks special
fact values only. The decimals suffix, spaces around key values and special
key values cost a second pass over millions of strings, so it leaves them
to callers, which can make them in polars and record them with the same
messages as `read_report`:
[`DECIMALS_SUFFIX`][dpmxbrl.filing.DECIMALS_SUFFIX],
[`KEY_SPACES`][dpmxbrl.filing.KEY_SPACES] and
[`SPECIAL_KEY_VALUE`][dpmxbrl.filing.SPECIAL_KEY_VALUE].


<!-- docs: requires-polars -->
```python
import polars as pl

from dpmxbrl.filing import DECIMALS_SUFFIX, KEY_SPACES, SPECIAL_KEY_VALUE
from dpmxbrl.frames import read_xbrl_csv_frames

SUFFIX = r"^[-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?d(?:[-+]?[0-9]+|INF)$"


def location(template, row, dropped):
    """Return the file line of a frame row, skipping the removed rows."""
    for removed in dropped:
        if removed <= row:
            row += 1
    return f"reports/{template}.csv:{row + 2}"


frames = read_xbrl_csv_frames("needs_fixes.zip")
log = FilingLog()
log.extend(frames.report.filing)
for template, frame in frames.tables.items():
    dropped = frames.dropped_rows.get(template, ())
    rows = frame.with_row_index("row")
    for row in rows.filter(pl.col("factValue").str.contains(SUFFIX))["row"]:
        log.add(*DECIMALS_SUFFIX, location(template, row, dropped))
    for key in frame.columns[2:]:
        text = pl.col(key).cast(pl.String)
        for row in rows.filter(text != text.str.strip_chars())["row"]:
            log.add(*KEY_SPACES, location(template, row, dropped))
        for row in rows.filter(text.str.starts_with("#"))["row"]:
            log.add(*SPECIAL_KEY_VALUE, location(template, row, dropped))

for finding in log.result():
    print(finding.rule, finding.code, finding.examples)
```

```text
2.19 nilUsed ('reports/c_26.00.csv:3',)
3.11 leadingOrTrailingSpacesInText ('reports/c_27.00.csv:2', 'reports/c_27.00.csv:3')
xBRL-CSV 1 decimalsSuffixUsed ('reports/c_26.00.csv:2',)
xBRL-CSV 6 tableForNegativeFilingIndicator ('reports/c_29.00.csv',)
File naming invalidFileName ('needs_fixes.zip',)
```

The result matches what `read_report` finds in the same package. The line
arithmetic assumes one file per template and no values spanning lines.

## Reuse the readers' checks

The checks the readers run on the report header are public, so you can run
them on a report you built yourself:
[`check_subject`][dpmxbrl.filing.check_subject] (rules 2.8 and 3.6),
[`check_file_name`][dpmxbrl.filing.check_file_name] and
[`check_entry_point`][dpmxbrl.filing.check_entry_point] (1.5, 2.2, 2.3).

```python
from dpmxbrl.filing import check_entry_point, check_file_name, check_subject

report = read_report("report.zip")
log = FilingLog()
check_subject(dataclasses.replace(report, entity_id="syntheticdpmxl000002.CON"), log)
check_file_name(
    "SYNTHETICDPMXL000002.CON_FR_COREP030300_COREPLE_2025-12-31.zip", report, log
)
check_entry_point(["corep_le.json"], log, where="report.json", xml=False)
for finding in log.result():
    print(finding.rule, finding.code, "|", finding.message)
```

```text
2.2 inappropriateTaxonomyRef | The entry point corep_le.json must be the full published URL.
3.6 reportingSubjectNotUppercase | The reporting subject syntheticdpmxl000002.CON must be written in upper case.
File naming invalidFileName | The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.
```
