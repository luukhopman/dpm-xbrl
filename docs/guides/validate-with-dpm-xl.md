---
description: Evaluate EBA DPM-XL validation rules on the facts of a report read with dpm-xbrl, using the sibling package dpm-xl.
---

# Validate a report with dpm-xl

dpm-xbrl reads a report and checks how the file is written. Whether the
*values* are right, for example that a total equals the sum of its parts, is
decided by the EBA validation rules, written in DPM-XL. The sibling package
[dpm-xl] parses and evaluates those rules.

The two packages are independent: neither depends on the other. You
connect them with a small `DataProvider` that answers dpm-xl's queries for
table, row and column cells from the facts that dpm-xbrl reads. The mapping
from a datapoint code to its table, row and column comes from the DPM
release of the taxonomy.

The dpm-xl documentation has the full, tested walk-through:
[from an XBRL report to explained failures][dpm-xl-validate]. It reads a
report with `read_report`, binds its facts to a provider through an
explicit datapoint mapping, evaluates rules with dpm-xl's columnar engine,
falls back to the reference engine where the columnar engine does not
support a rule, and explains each failure.

## What dpm-xbrl gives the provider

- `Report.facts`, each with `datapoint`, `template`, `keys` and `value`
  (see [the fact model](../concepts/fact-model.md)). For large reports,
  [read the tables as frames](large-reports.md) instead and hand the frames
  to dpm-xl's columnar engine.
- `Report.filing_indicators`, keyed by template code, for dpm-xl's
  `table_reported`. Map a table file to its filing indicator as described
  in [table codes and filing indicators](../concepts/filing-indicators.md).
- `Report.parameters` (such as `refPeriod` and `baseCurrency`) and
  `Report.decimals_parameters`, for dpm-xl's `parameter`.

```python
from dpmxbrl import read_report

report = read_report("report.zip")
print(report.parameters["refPeriod"], report.filing_indicators["C_26.00"])
print([(fact.datapoint, fact.value) for fact in report.facts_for_template("C_26.00")])
```

```text
2025-12-31 True
[('dp457468', '56058000'), ('dp32024', '92592000'), ('dp32026', '86911000'), ('dp32025', '0.71')]
```

Values are strings as written; convert numbers with the decimals parameter
that applies to their data type before evaluating rules.
