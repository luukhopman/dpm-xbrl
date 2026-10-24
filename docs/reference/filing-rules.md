---
description: Every EBA filing rule (v5.8, February 2026) that the dpm-xbrl readers check, by format, and the rules left to callers or not checked.
---

# Filing rules checked

The readers record the [EBA Filing Rules][eba-filing-rules] (version 5.8,
February 2026) that a report breaks and that the file alone can show, in
`Report.filing`. [`RULE_TITLES`][dpmxbrl.filing.RULE_TITLES] names each
rule; [filing rules and coverage](../concepts/filing-rules.md) explains the
approach.

## Both formats

| Rule | Checks |
| --- | --- |
| 1.5, 2.2, 2.3 | One absolute taxonomy entry point. |
| 2.8, 3.6 | The reporting subject: scheme (LEI or reporting-subject), suffix such as `.CON` or `.IND` from 31 December 2022 (unless the module is a `_con` or `_ind` module), upper case, and LEI check digits (ISO 17442). |
| File naming | The file name against `ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp`, including the reporting subject, module and reference date. Warnings. |

## XBRL-XML

| Rule | Checks |
| --- | --- |
| 1.4, 1.13 | UTF-8, and no standalone declaration. |
| 1.6, 1.6.1 | Filing indicators present, unique, and in a context without segment or scenario. |
| 1.14, 1.15, 2.1, 2.4, 2.25 | No `xsi:schemaLocation`, XInclude, `xml:base`, `link:linkbaseRef` or footnotes. |
| 2.11, 2.13, 2.14, 2.15 | No forever or duration periods, segments, or non-dimensional scenario content. |
| 2.9, 2.10, 2.13 | One entity and one reference date, as plain dates. |
| 2.16, 2.16.1 | No duplicate facts, and none differing only by unit. |
| 2.17, 2.18 | `decimals` rather than `precision`, and present on numeric facts. |
| 2.19 | No nil or empty facts. |
| 2.7, 2.21, 2.22 | No unused or repeated contexts and units. |
| 3.1 | One reporting currency (a), and currency-of-denomination facts in the currency their CUS or CUA member names (c). Rule (c) binds only facts under (b), in contexts with CCA `eba_CA:x1` or qAEA `eba_qCA:qx2000`, so a CUS or CUA member in other contexts is not compared with the unit. |
| 3.2 (a) | `xbrli:pure` for other numeric facts. |
| 3.4, 3.9, 3.10 | Namespace prefixes declared once, on the document element, and used. |

## xBRL-CSV

| Rule | Checks |
| --- | --- |
| Package | `META-INF/reportPackage.json`, `parameters.csv` with `refPeriod`, and `FilingIndicators.csv`. |
| File naming | The root folder named as the ZIP. |
| 1.5 | No `documentInfo.taxonomy`. |
| 2.10 | A plain-date `refPeriod`. |
| 1.6.1 | Unique filing indicators. |
| xBRL-CSV 6 | No table file for a template indicated as not reported. |
| 2.19, xBRL-CSV 5 | No special values in fact or key columns: `#nil`, `#empty` and any other value starting with `#`. |
| xBRL-CSV 1 | No decimals suffix, such as `78920030d-4`. |
| 3.11 | Key values without leading or trailing spaces. |
| xBRL-CSV 4 | A value in the key columns of each reported fact: without metadata every key column but `unit`, which only some data points use; with metadata, the columns each data point refers to. |
| xBRL-CSV 2 | With resolved metadata, every column the table's metadata defines in its header. |
| Package | No files besides `META-INF/reportPackage.json` and, in `reports`, `report.json`, `parameters.csv`, `FilingIndicators.csv` and the tables (`unexpectedFile`, a warning: the filing rules describe the layout without a MUST). |

[`read_xbrl_csv_frames`][dpmxbrl.frames.read_xbrl_csv_frames] checks
special fact values only; the decimals suffix, spaces around key values,
special key values and empty key values are left to the caller.

## With taxonomy packages

Given `taxonomy_packages`, both readers also check the rules that need the
taxonomy, and only then:

| Rule | Checks |
| --- | --- |
| 1.5 | The entry point is one the packages' `taxonomyPackage.xml` lists (an XSD, or the JSON beside it), and the reference date is within the module's `FromReferenceDate` and `toReferenceDate`. The EBA's placeholder 9999-12-31 counts as no date. |
| 1.6, 1.6.3 | A filing indicator, true or false, for each template of the module, and only the module's codes. |
| 2.18 | Decimals of at least -4 for monetary facts (-6 in the FP, ESG, Pillar 3 and REM_DBM modules), at least 4 for percentages and exactly 0 for integers, or INF, by the metric's schema type (`accuracyRequirements`). The -3 that applied to submissions before April 2025 is not checked: the file does not show when it is sent. |
| 3.2 (b) | Percentages, by the metric's `percentItemType`, as decimal fractions: a value above 50 is a warning, since only the value suggests a percentage multiplied by 100. |
| 3.5 | XML only: each namespace prefix as the namespace's schema in the packages binds it, or as the XBRL specifications use it (`xbrli`, `link`, `xlink`, `xbrldi`, `xbrldt`, `xsi`, `iso4217`, `find`). |
| xBRL-CSV 2 | Header columns, as the packages resolve the metadata. |
| Package | Only the module's table files in `reports`. |

## What each mode checks

| Mode | Rules |
| --- | --- |
| `read_xbrl_xml` | 1.4, 1.5, 1.6, 1.6.1, 1.13 to 1.15, 2.1 to 2.4, 2.7 to 2.11, 2.13 to 2.19, 2.21, 2.22, 2.25, 3.1, 3.2 (a), 3.4, 3.6, 3.9, 3.10, file naming |
| `read_xbrl_csv` | 1.5, 1.6, 1.6.1, 2.2, 2.3, 2.8, 2.10, 2.19, 3.6, 3.11 (keys), xBRL-CSV 1, 2 (with metadata), 4, 5, 6, package, file naming |
| `read_xbrl_csv_frames` | As `read_xbrl_csv`, but of the values only special fact values (2.19, xBRL-CSV 5) |
| Any, with `taxonomy_packages` | Adds 1.5 (published entry point, reference dates), 1.6 (each template), 1.6.3, 2.18, 3.2 (b), and 3.5 for XML; the frames reader, which builds no facts, adds neither 2.18 nor 3.2 |

[`checked_rules`][dpmxbrl.filing.checked_rules] gives the same, exactly,
as `(rule, code)` pairs for one mode, so that callers who check rules
themselves can skip the ones the reader already reports:

```python
from dpmxbrl.filing import checked_rules

xml = checked_rules("xbrl-xml", taxonomy=True) - checked_rules("xbrl-xml")
frames = checked_rules("xbrl-csv", taxonomy=True, columnar=True)
print(sorted(xml))
print(("2.18", "accuracyRequirements") in frames)
```

```text
[('1.6.3', 'invalidFilingIndicatorValue'), ('2.18', 'accuracyRequirements'), ('3.2', 'useDecimalFractions'), ('3.5', 'notRecommendedNamespacePrefix')]
False
```

## Left to callers

The other rules that need the taxonomy are left to the caller, which can build
`FilingFinding`s and merge them with
[`FilingLog`][dpmxbrl.filing.FilingLog]; see
[add your own filing findings](../guides/add-filing-findings.md):

| Rule | Needs |
| --- | --- |
| 1.7.1 | Facts outside the reported templates. |
| 3.11 | Fact values without leading or trailing spaces, for string data points only ([`SPACES`][dpmxbrl.filing.SPACES]). |
| (none) | `baseCurrency` when monetary facts use it. |

## Not checked

Units against the XBRL unit registry (2.23), generating-software
information (2.26) and comments (2.5).
