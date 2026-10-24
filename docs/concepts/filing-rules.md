---
description: What the EBA filing rules are, which ones dpm-xbrl checks from the file alone, severities, and which rules are left to callers with the taxonomy.
---

# Filing rules and coverage

The [EBA Filing Rules][eba-filing-rules] (version 5.8, February 2026)
constrain how a report file is written, before anyone looks at its values:
one taxonomy entry point, one entity and reference date, filing indicators,
decimals, units, naming, and XML constructs that must not appear. They are
separate from the EBA *validation rules*, written in DPM-XL, which check the
values; for those, see [dpm-xl].

## What dpm-xbrl checks

Both readers record every rule that the file alone can show to be broken,
in the same pass that reads the facts, so checking costs nothing extra.
Each broken rule becomes one [`FilingFinding`][dpmxbrl.FilingFinding] per
rule, tag and message, with a count and up to five locations, in
`Report.filing`. The full list is in
[filing rules checked](../reference/filing-rules.md).

Severity follows the rule text: `error` where the rule says MUST (the EBA
rejects the report) and `warning` where it says SHOULD. File-naming
findings are warnings, because each supervisor confirms its own naming
structure with its reporters.

## What is left to you

Some rules need the taxonomy or a data point's data type, which the file
does not carry. The readers leave them to callers, which can record them
with the same classes; see
[add your own filing findings](../guides/add-filing-findings.md):

- a filing indicator for every template of the module, and only valid
  codes (1.6, 1.6.3);
- facts outside the reported templates (1.7.1);
- minimum decimals per data type (2.18);
- leading or trailing spaces in string fact values (3.11);
- an entry point valid for the reference date (1.5);
- `baseCurrency` when monetary facts use it.

[Columnar reading](../guides/large-reports.md) checks special fact values
only, and leaves the decimals suffix, key spaces and special key values to
the caller as well.

## What is not checked

Units against the XBRL unit registry (2.23), decimal notation for rates
(3.2), canonical prefixes (3.5), generating-software information (2.26) and
comments (2.5).

## Warnings are not filing findings

`Report.warnings` describes how the file was read: an unresolved metadata
document, a draft document type, aggregated duplicates. `Report.filing`
lists the rules the report breaks. Pipelines gate on `filing`; warnings
explain surprises.
