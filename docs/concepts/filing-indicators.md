---
description: How xBRL-CSV table codes map to EBA filing indicators (single-letter parts dropped, compared case-insensitively), with a recipe to group facts by filing indicator.
---

# Table codes and filing indicators

A report says which templates it reports through its *filing indicators*,
codes such as `C_07.00` with a reported flag. Its xBRL-CSV tables are named
by *table codes*, the file stems such as `c_07.00.a`. One template can be
split over several tables, so the two codes differ.

## The mapping

dpm-xbrl maps a table code to its filing indicator in two steps:

1. **Single-letter parts are dropped.** A part is the text between dots; a
   part of one letter (any case) is a table's letter within its template.
2. **Codes are compared case-insensitively.**

| Table file | Template id | Filing indicator |
| --- | --- | --- |
| `c_01.00.csv` | `c_01.00` | `C_01.00` |
| `c_07.00.a.csv`, `c_07.00.b.csv` | `c_07.00.a`, `c_07.00.b` | `C_07.00` |
| `f_18.00.a.dp.csv` | `f_18.00.a.dp` | `F_18.00.dp` |
| `c_43.00.c.csv` | `c_43.00.c` | `C_43.00` |

The template id is the file stem, unless the metadata's `tables` maps the
file URL to another template.

dpm-xbrl uses this mapping for xBRL-CSV rule 6: a package must not contain
the table file of a template whose filing indicator is false.

## Where the mapping applies, and where it does not

`Fact.template` is always the template id, `c_07.00.a`, never the filing
indicator. [`Report.facts_for_template`][dpmxbrl.Report.facts_for_template]
compares case-insensitively but does **not** drop letter parts: it matches
one template id. For a template split over lettered tables, group facts
yourself:

```python
import io
import re
from zipfile import ZipFile

from dpmxbrl import read_report

# report.zip plus a template split into two tables, and one filed as not reported.
buffer = io.BytesIO()
with ZipFile("report.zip") as source, ZipFile(buffer, "w") as target:
    for name in source.namelist():
        data = source.read(name)
        if name.endswith("FilingIndicators.csv"):
            data += b"C_07.00,true\r\nF_18.00.dp,false\r\n"
        target.writestr(name, data)
    target.writestr(
        "report/reports/c_07.00.a.csv", "datapoint,factValue\r\ndp1001,500\r\n"
    )
    target.writestr(
        "report/reports/c_07.00.b.csv", "datapoint,factValue\r\ndp1002,700\r\n"
    )
    target.writestr(
        "report/reports/f_18.00.a.dp.csv", "datapoint,factValue\r\ndp1003,1\r\n"
    )
report = read_report(buffer.getvalue(), name="report.zip")

print(
    len(report.facts_for_template("C_07.00")),
    len(report.facts_for_template("C_07.00.A")),
)
```

```text
0 1
```

```python
LETTER_PART = re.compile(r"\.[a-z](?=\.|$)", re.IGNORECASE)


def filing_indicator(template: str) -> str:
    """Return the casefolded filing-indicator code of a table code."""
    return LETTER_PART.sub("", template).casefold()


by_indicator = {}
for fact in report.facts:
    by_indicator.setdefault(filing_indicator(fact.template), []).append(fact)
reported = {code.casefold(): filed for code, filed in report.filing_indicators.items()}
for code, facts in sorted(by_indicator.items()):
    print(code, len(facts), reported.get(code))
```

```text
c_00.01 2 True
c_07.00 2 True
c_26.00 4 True
c_27.00 4 True
c_28.00 4 True
f_18.00.dp 1 False
```

The table filed as not reported breaks rule 6:

```python
print(
    [
        (finding.rule, finding.examples)
        for finding in report.filing
        if finding.rule == "xBRL-CSV 6"
    ]
)
```

```text
[('xBRL-CSV 6', ('reports/f_18.00.a.dp.csv',))]
```

The frames reader keys `ReportFrames.tables` by template id too, so the
same recipe groups frames.

## XML reports

XBRL-XML facts carry no template: the filing indicators say which
templates are reported, but which template a fact belongs to is only known
from the taxonomy. `facts_for_template` returns nothing for XML reports.
