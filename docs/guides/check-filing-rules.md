---
description: List the EBA filing rules a report breaks, decide whether to send it, and gate a CI pipeline with dpm-xbrl inspect --fail-on.
---

# Check EBA filing rules

The [EBA Filing Rules][eba-filing-rules] constrain how a report file is
written: one entity and reference date, filing indicators, decimals, units,
naming, and constructs that must not appear. A report that breaks a MUST
rule is rejected however good its values are.

Both readers record the rules a report breaks, as far as the file alone can
show, in `Report.filing`. This guide shows how to read the findings and how
to stop a pipeline on them. What is and is not checked is listed in
[filing rules checked](../reference/filing-rules.md).

## List the broken rules

```python
from dpmxbrl import read_report
from dpmxbrl.filing import RULE_TITLES

report = read_report("needs_fixes.zip")
for finding in report.filing:
    title = RULE_TITLES[finding.rule]
    print(
        f"[{finding.severity}] {finding.rule} {title} ({finding.code}), {finding.count}x"
    )
    print(f"    {finding.message}")
    print(f"    at {', '.join(finding.examples)}")
```

```text
[error] 2.19 Nil and empty values (nilUsed), 1x
    Facts must not be reported as #nil; leave out a fact that is not reported.
    at reports/c_26.00.csv:3
[warning] 3.11 Leading or trailing spaces (leadingOrTrailingSpacesInText), 2x
    Key values should not start or end with spaces or line breaks.
    at reports/c_27.00.csv:2, reports/c_27.00.csv:3
[error] xBRL-CSV 1 Decimals suffix (decimalsSuffixUsed), 1x
    Fact values must not use the decimals suffix (such as 78920030d-4); decimals belong in parameters.csv.
    at reports/c_26.00.csv:2
[error] xBRL-CSV 6 Tables of templates not reported (tableForNegativeFilingIndicator), 1x
    The package must not contain the table file of a template whose filing indicator is false.
    at reports/c_29.00.csv
[warning] File naming File naming (invalidFileName), 1x
    The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.
    at needs_fixes.zip
```

Each [`FilingFinding`][dpmxbrl.FilingFinding] has:

- `rule`: the rule's number in the EBA document (`2.19`), or `xBRL-CSV n`
  for the extra xBRL-CSV rules, or `Package` and `File naming` for the
  remittance requirements. Rule numbers are stable across releases.
- `code`: the rule's tag in the EBA document, such as `nilUsed`. Also
  stable.
- `severity`: `error` where the rule says MUST, `warning` where it says
  SHOULD.
- `message`: what is wrong, as a sentence. Messages may be reworded in
  minor releases, so match on `rule` and `code`, never on the message.
- `count` and up to five `examples` of locations.

Findings come in rule order, and one finding is kept per rule, code and
message.

## Decide whether to send a report

```python
must_fix = [finding for finding in report.filing if finding.severity == "error"]
print(f"{len(must_fix)} rules must be fixed before sending")
```

```text
3 rules must be fixed before sending
```

File-naming findings are always warnings, because each supervisor confirms
its own naming.

## Gate a CI pipeline with `--fail-on`

`dpm-xbrl inspect --fail-on error` exits with status 3 when the report
breaks a MUST rule; `--fail-on warning` also fails on SHOULD rules. Status 1
means the report could not be read at all, and 2 is a usage error.

```python
import subprocess

for path, level in [
    ("report.zip", "error"),
    ("report.zip", "warning"),
    ("needs_fixes.zip", "error"),
]:
    command = ["dpm-xbrl", "inspect", path, "--fail-on", level]
    status = subprocess.run(command, capture_output=True, check=False).returncode
    print(f"{path} --fail-on {level}: exit status {status}")
```

```text
report.zip --fail-on error: exit status 0
report.zip --fail-on warning: exit status 3
needs_fixes.zip --fail-on error: exit status 3
```

`report.zip` breaks only the file-naming recommendation, so it passes
`--fail-on error` and fails `--fail-on warning`.

A GitHub Actions step that checks every report in a folder:

```yaml
- name: Check EBA filing rules
  run: |
    for report in reports/*.zip; do
      uvx dpm-xbrl inspect "$report" --fail-on error
    done
```

To keep the details for a dashboard or an artefact, add `--json`; the exit
status is the same. The layout is in [JSON output](../reference/json-output.md).

```python
import json

command = ["dpm-xbrl", "inspect", "needs_fixes.zip", "--json", "--fail-on", "error"]
result = subprocess.run(command, capture_output=True, text=True, check=False)
summary = json.loads(result.stdout)
print(result.returncode, [rule["code"] for rule in summary["filing_rules"]])
```

```text
3 ['nilUsed', 'leadingOrTrailingSpacesInText', 'decimalsSuffixUsed', 'tableForNegativeFilingIndicator', 'invalidFileName']
```

## Check a file name before sending

The file-naming check compares the name with the report's own entity,
module and reference date. Read bytes with the final name to check it:

```python
from pathlib import Path

name = (
    "SYNTHETICDPMXL000002.CON_FR_COREP030300_COREPLE_2025-12-31_20260115093000000.zip"
)
renamed = read_report(Path("report.zip").read_bytes(), name=name)
print([finding.code for finding in renamed.filing])
```

```text
['invalidRootFolder']
```

The name is right; what remains is that the package's root folder must be
named as the file, without `.zip`. Rename the folder inside the ZIP, or
write the package again with
[`write_xbrl_csv(report, target, root=...)`][dpmxbrl.write_xbrl_csv].

## Rules that need the taxonomy

Some rules need the taxonomy, such as which templates a module has, or a
data point's data type: a filing indicator for every template of the module
(1.6), facts outside the reported templates (1.7.1), minimum decimals per
data type (2.18), and spaces around string values (3.11). The readers leave
them to you; [add your own filing findings](add-filing-findings.md) shows how
to record them in the same form.
