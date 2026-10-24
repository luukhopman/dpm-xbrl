---
description: How dpm-xbrl models reports, the two serializations, metadata, filing indicators, filing rules and the security model.
---

# Concepts

These pages explain how dpm-xbrl sees a report and why it behaves as it
does. They are background reading; for tasks, see the
[how-to guides](../guides/index.md), and for exact behaviour, the
[reference](../reference/index.md).

| Page | Explains |
| --- | --- |
| [The fact model](fact-model.md) | `Report` and `Fact`, what each field holds in each format, and memory and speed. |
| [xBRL-CSV and XBRL-XML](formats.md) | The two serializations of the same report and how dpm-xbrl reads each. |
| [EBA convention and resolved metadata](metadata.md) | The two ways an xBRL-CSV table is read, and when you need a taxonomy. |
| [Table codes and filing indicators](filing-indicators.md) | How a table file such as `c_07.00.a.csv` maps to the filing indicator `C_07.00`. |
| [Filing rules and coverage](filing-rules.md) | What the EBA filing rules are, which ones dpm-xbrl checks and why some are left to you. |
| [Security model](security.md) | What dpm-xbrl protects against when it reads untrusted input, and its thread-safety guarantees. |
