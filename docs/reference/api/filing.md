---
description: API reference for dpmxbrl.filing - RULE_TITLES, FilingLog, the header checks and the rule tuples for your own findings.
---

# `dpmxbrl.filing`

The EBA filing rules: the rule catalogue, the log that collects findings,
the checks the readers run, and the rule tuples that callers use to add
their own findings. Everything on this page is in `dpmxbrl.filing.__all__`.

See [check EBA filing rules](../../guides/check-filing-rules.md),
[add your own filing findings](../../guides/add-filing-findings.md) and the
[list of rules checked](../filing-rules.md).

::: dpmxbrl.filing
    options:
      show_root_heading: false
      members:
        - RULE_TITLES
        - Rule
        - FilingLog
        - sort_findings
        - check_subject
        - check_file_name
        - check_entry_point
        - NIL_VALUE
        - EMPTY_VALUE
        - SPECIAL_VALUE
        - SPECIAL_KEY_VALUE
        - DECIMALS_SUFFIX
        - SPACES
        - KEY_SPACES

`FilingFinding` and `Severity` are re-exported here from
[`dpmxbrl`](dpmxbrl.md#dpmxbrl.FilingFinding).
