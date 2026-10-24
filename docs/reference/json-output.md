---
description: The JSON layout printed by dpm-xbrl inspect --json, field by field, with schema_version and its compatibility promise.
---

# JSON output

`dpm-xbrl inspect --json` prints one JSON object (UTF-8, two-space
indentation, non-ASCII characters as is). The exit status is the same as
without `--json`, including `--fail-on`.

```console
$ dpm-xbrl inspect instance.xbrl --json
{
  "schema_version": 1,
  "format": "xbrl-xml",
  "entry_point": "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.xsd",
  "entity_scheme": "https://eurofiling.info/eu/rs",
  "entity_id": "529900T8BM49AURSDO55.CON",
  "reference_date": "2025-12-31",
  "base_currency": "iso4217:EUR",
  "filing_indicators": {
    "reported": 2,
    "total": 3,
    "templates": {
      "C_26.00": true,
      "C_27.00": true,
      "C_29.00": false
    }
  },
  "fact_count": 3,
  "facts_per_template": {
    "(none)": 3
  },
  "warnings": [],
  "filing_rules": [
    {
      "rule": "File naming",
      "title": "File naming",
      "code": "invalidFileName",
      "severity": "warning",
      "message": "The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.",
      "count": 1,
      "examples": [
        "instance.xbrl"
      ]
    }
  ]
}
```

## Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Version of this layout, currently `1`. |
| `format` | string | `"xbrl-csv"` or `"xbrl-xml"`. |
| `entry_point` | string or null | `Report.entry_point`. |
| `entity_scheme` | string or null | `Report.entity_scheme`. |
| `entity_id` | string or null | `Report.entity_id`. |
| `reference_date` | string or null | `Report.reference_date` as `YYYY-MM-DD`. |
| `base_currency` | string or null | `Report.base_currency`, such as `iso4217:EUR`. |
| `filing_indicators.reported` | integer | Templates indicated as reported. |
| `filing_indicators.total` | integer | All filing indicators. |
| `filing_indicators.templates` | object | Template code to reported (boolean), in report order. |
| `fact_count` | integer | Facts in the report (with `--columnar`, frame rows). |
| `facts_per_template` | object | Template id to fact count, sorted by template. XML facts have no template and count under `"(none)"`. |
| `warnings` | array of strings | `Report.warnings`. |
| `filing_rules` | array of objects | `Report.filing`, in rule order. |
| `filing_rules[].rule` | string | Rule number, such as `"2.19"`, `"xBRL-CSV 1"` or `"File naming"`. |
| `filing_rules[].title` | string | Short title from [`RULE_TITLES`][dpmxbrl.filing.RULE_TITLES]. |
| `filing_rules[].code` | string | The rule's tag in the EBA document, such as `"nilUsed"`. |
| `filing_rules[].severity` | string | `"error"` (MUST) or `"warning"` (SHOULD). |
| `filing_rules[].message` | string | What is wrong, as a sentence. |
| `filing_rules[].count` | integer | How often the report breaks it. |
| `filing_rules[].examples` | array of strings | Up to five locations. |

## Compatibility

`schema_version` changes only with a new major version of dpm-xbrl. Within
a major version, fields are not removed or renamed and their types do not
change; new fields may be added, so ignore fields you do not know. Warning
texts and finding messages may be reworded in minor releases; `rule` and
`code` may not. See [stability and versioning](../project/stability.md).
