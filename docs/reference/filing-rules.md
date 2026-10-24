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
| 3.1 | One reporting currency, and currency-of-denomination facts in the currency their CUS or CUA member names. |
| 3.2 | `xbrli:pure` for other numeric facts. |
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

[`read_xbrl_csv_frames`][dpmxbrl.frames.read_xbrl_csv_frames] checks
special fact values only; the decimals suffix, spaces around key values and
special key values are left to the caller.

## Left to callers

Rules that need the taxonomy are left to the caller, which can build
`FilingFinding`s and merge them with
[`FilingLog`][dpmxbrl.filing.FilingLog]; see
[add your own filing findings](../guides/add-filing-findings.md):

| Rule | Needs |
| --- | --- |
| 1.6, 1.6.3 | A filing indicator for every template of the module, and only valid codes. |
| 1.7.1 | Facts outside the reported templates. |
| 2.18 | Minimum decimals per data type. |
| 3.11 | Fact values without leading or trailing spaces, for string data points only ([`SPACES`][dpmxbrl.filing.SPACES]). |
| 1.5 | An entry point valid for the reference date. |
| (none) | `baseCurrency` when monetary facts use it. |

## Not checked

Units against the XBRL unit registry (2.23), decimal notation for rates
(3.2), canonical prefixes (3.5), generating-software information (2.26) and
comments (2.5).
