# Changelog

All notable changes to this project are documented here. The project follows
[semantic versioning](https://semver.org).

## Unreleased

### Added

- `dpm-xbrl inspect --fail-on error|warning` exits with status 2 when the
  report breaks a filing rule of that severity; `--version`, and examples in
  `--help`.
- `dpmxbrl.__version__`; `inspect --json` output carries `schema_version`.
- `inspect --columnar` counts large xBRL-CSV packages with polars, and both
  commands take `--max-facts`, `--max-file-size`, `--max-total-size` and
  `--max-zip-entries`.
- `dpmxbrl.frames.MetadataTablesError`, a `ReportError` raised when a package
  needs `read_xbrl_csv`, so callers need not match the message.
- `write_xbrl_xml` and `convert --typed-domain` accept a typed domain element
  in Clark notation, `{namespace}local`, and declare its namespace.
- The public API is documented: every name in the `__all__` of `dpmxbrl`,
  `dpmxbrl.filing` and `dpmxbrl.frames`, and how table codes map to filing
  indicators.

### Changed

- The `dimensions`, `typed_dimensions` and `keys` mappings of facts that are
  read are read-only `dict`s that facts may share; copy one with `dict()` to
  change it. They pickle, copy and serialize as plain dicts.
- `detect_format` is annotated to return `ReportFormat`.

### Fixed

- `write_xbrl_csv` declares the Report Packages 1.0 type
  `https://xbrl.org/report-package/2023` that EBA packages use; the
  `/2023/xbrl-csv` it wrote before is not a defined type, and other tools
  reject it. The reader accepts `/2023` and `/2023/xbr`, and reads the old
  value with a warning.
- A DOCTYPE in a UTF-16 instance without a byte order mark is rejected, and
  such an instance breaks filing rule 1.4.
- Every unreadable input raises `ReportError`: unknown or multi-byte XML
  encodings, unreadable files, ZIP entries with an unsupported compression
  method, damaged taxonomy package entries, JSON nested too deeply and a
  malformed `propertiesFrom`.
- A `refPeriod` must be a `YYYY-MM-DD` or `YYYYMMDD` date: week dates and
  mixed or non-ASCII digits are rejected. An XML period must start with a
  `YYYY-MM-DD` date, as `xs:date` requires.
- Directory packages reject linked directories that leave the package, and
  re-check each file when it is opened.
- xBRL-CSV drops exact copies of a fact whose key already had a conflicting
  value; XML finds duplicate facts that share a fact id or have none.
- `write_xbrl_xml` rejects invalid qnames, namespace prefixes and characters
  XML cannot represent, and keeps carriage returns.
- `read_xbrl_csv_frames` rejects repeated and empty table columns, and an
  unreadable header raises `ReportError`.
- Caller-built filing findings with any `xBRL-CSV` rule name can be sorted.

### Performance

- Reading 7.3 million CSV facts takes 33 s and 5.0 GB instead of 55 s and
  7.4 GB: the cyclic garbage collector is paused (process-wide) while facts
  are built, and facts share empty mappings, datapoint codes and XML context
  dimensions.

## 0.1.1 - 2026-10-23

### Performance

- XML elements that declare no namespace share their parent's scope.

## 0.1.0 - 2026-10-23

First release on PyPI.
