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
  ZIPs, or one ZIP of them as the EBA publishes a release (one level deep,
  read into memory).
- EBA-convention CSV facts carry no concept, dimensions, unit or decimals,
  and XML facts no datapoint or template, so converting between formats
  needs the module's taxonomy packages. XML to xBRL-CSV places facts in
  tables of the EBA layout only (one property-group column, one fact
  column), and a `decimals*` parameter takes the lowest decimals of its
  facts. Key columns follow the EBA's header-code order, which matches
  the EBA's own packages for most but not all tables.
- Without taxonomy packages, `write_xbrl_xml` names the `.xsd` entry
  point of a `.json` one by the EBA's naming convention, with an
  `EntryPointWarning`.
- Empty-string facts do not survive an xBRL-CSV round trip (`#empty` is
  skipped when read), and `Fact.decimals`, concepts and dimensions are not
  written to EBA-convention CSV.
- XML: tuples, footnotes, `precision`, segment versus scenario placement,
  forever periods and typed-domain element names are not kept. XML output
  puts all dimensions in the scenario and uses one entity and instant. The
  XML writer holds the instance text in memory before writing it.
- Fact locations in XML use the fact id rather than a line number.
- Reading collects up to 100 structural problems of xBRL-CSV tables (row
  lengths, quoting, headers) in `ReportError.problems`; other problems,
  such as a broken `report.json` or parameters file, stop it at the first.
  The frames reader stops at the first problem.
- The 2.18 check does not apply the -3 minimum for monetary facts sent
  before April 2025, and 3.2 (b) flags only percentages above 50.
