---
description: What dpm-xbrl does not do - taxonomy validation, parts of xBRL-CSV and XBRL-XML it does not keep, and conversion limits.
---

# Known gaps

- No taxonomy validation, schema lookups, or calculation and formula
  checks. Without a taxonomy, an explicit member and a typed value that
  looks like a declared qname cannot be told apart in xBRL-CSV metadata.
  For the EBA validation rules on report values, see [dpm-xl].
- xBRL-CSV: no `rowIdColumn`, `links`, footnotes, `@start`/`@end` period
  semantics, per-fact `period`/`entity`/`language` values (they are
  ignored), or multiple reports per package. Taxonomy packages must be
  ZIPs.
- EBA-convention CSV facts carry no concept, dimensions, unit or decimals,
  so they cannot be written as XML; XML facts carry no datapoint or
  template, so they cannot be written as CSV. Converting between formats
  needs resolved xBRL-CSV metadata, and XBRL-XML to xBRL-CSV is not
  possible.
- `write_xbrl_xml` writes the report's entry point as it is, so an
  xBRL-CSV report's `.json` entry point needs replacing with the `.xsd` one,
  and it declares every namespace of the report, used or not (rule 3.4).
- Empty-string facts do not survive an xBRL-CSV round trip (`#empty` is
  skipped when read), and `Fact.decimals`, concepts and dimensions are not
  written to EBA-convention CSV.
- XML: tuples, footnotes, `precision`, segment versus scenario placement,
  forever periods and typed-domain element names are not kept. XML output
  puts all dimensions in the scenario and uses one entity and instant. The
  XML writer holds the instance text in memory before writing it.
- Fact locations in XML use the fact id rather than a line number.
- Reading stops at the first problem that makes the input unreadable; it
  does not collect every structural problem of a broken file.
