---
description: dpm-xbrl's semantic versioning policy - what the public API is, what may change in minor releases, and the supported Python versions.
---

# Stability and versioning

dpm-xbrl follows [semantic versioning][semver]. A major version may break
the public API; minor and patch versions do not. The
[changelog](changelog.md) lists every change, with breaking changes marked.

## The public API

- The names in the `__all__` of `dpmxbrl`, `dpmxbrl.filing` (including
  `FilingLog` and `Rule`, with which callers add their own findings, and
  `RULE_TITLES`) and `dpmxbrl.frames` (including the `on_metadata` and
  `on_table` callbacks).
- The fields of `Report`, `Fact`, `FilingFinding` and `Limits`, and the
  attributes of `ReportFrames`.
- The `ReportError` contract: every unreadable or unsafe input raises
  `ReportError` (or its subclass `MetadataTablesError`), a `ValueError`.
- The CLI: its commands, options, exit statuses and the `--json` layout,
  versioned by `schema_version`.
- Filing rule numbers (`FilingFinding.rule`) and tags (`FilingFinding.code`).

Modules whose names start with an underscore are internal, as are names
not in an `__all__`. `dpmxbrl.__version__` gives the installed version.

## What may change in a minor release

- New functions, parameters with defaults, fields with defaults, CLI
  options, JSON fields and filing checks. A new filing check can add
  findings to a report that had none, so a pipeline with `--fail-on` may
  start failing on a report it accepted before; read the changelog before
  upgrading such a pipeline.
- The wording of warnings, filing-finding messages and error messages.
  Match on rule numbers and tags, never on messages.
- Performance characteristics.

## Python versions

dpm-xbrl supports Python 3.11 to 3.14. Support for a Python version is
dropped only in a minor release, after its end of life.

## Dependencies

The core package uses only the standard library and will stay so. The
optional extras (`fast` for isal, `frames` for polars) pin a major version
range.
