---
description: The public Python API of dpm-xbrl, generated from the docstrings - dpmxbrl, dpmxbrl.filing and dpmxbrl.frames.
---

# Python API

The public API is the names in the `__all__` of three modules. Everything
else, including modules whose names start with an underscore, is internal.

| Module | Contents |
| --- | --- |
| [`dpmxbrl`](dpmxbrl.md) | Readers, writers, format detection, and the model: `Report`, `Fact`, `FilingFinding`, `Limits`, `ReportError`. |
| [`dpmxbrl.filing`](filing.md) | The filing-rule catalogue, `FilingLog`, the header checks and the rule tuples for your own findings. |
| [`dpmxbrl.frames`](frames.md) | Columnar reading into polars frames (`frames` extra). |

The model is defined in `dpmxbrl.model`, and the readers and writers in
`dpmxbrl.reader`, `dpmxbrl.csv_reader`, `dpmxbrl.xml_reader` and
`dpmxbrl.writer`; import them from `dpmxbrl`. The CLI is documented in
[CLI](../cli.md).

## Thread safety

All readers and writers may be called from several threads at once: they
keep no shared state, and their results (`Report`, `Fact`,
`FilingFinding`, `ReportFrames`) are immutable. While a reader builds facts,
it pauses Python's cyclic garbage collector for the whole process and
restores it when the last concurrent read ends. `FilingLog` is not
synchronized; use one per thread. Details are in
[the security model](../../concepts/security.md#thread-safety).
