# Changelog

All notable changes to this project are documented here. The project follows
[semantic versioning](https://semver.org).

## Unreleased

### Added

- A documentation site at https://luukhopman.github.io/dpm-xbrl/, with
  `llms.txt` and `llms-full.txt` for AI agents.

### Fixed

- `inspect --help` gives 3, not 2, as the `--fail-on` exit status.

## 1.0.0 - 2026-10-24

### Added

- `dpm-xbrl inspect --fail-on error|warning` exits with status 3 when the
  report breaks a filing rule of that severity (2 stays the usage-error
  status); `--version`, and examples in `--help`. A limit error names the
  option that raises it.
- `dpmxbrl.__version__`; `inspect --json` output carries `schema_version`.
- `inspect --columnar` counts large xBRL-CSV packages with polars, and both
  commands take `--max-facts`, `--max-file-size`, `--max-total-size` and
  `--max-zip-entries`.
- `dpmxbrl.frames.MetadataTablesError`, a `ReportError` raised when a package
  needs `read_xbrl_csv`, so callers need not match the message.
- `write_xbrl_xml` and `convert --typed-domain` accept a typed domain element
  in Clark notation, `{namespace}local`, and declare its namespace.
- `write_xbrl_csv(..., taxonomy_packages=...)` and `convert --taxonomy-package`
  convert XBRL-XML to xBRL-CSV: facts go in the module's table rows by concept
  and dimensions. Facts that cannot be placed raise `ReportError`, or are left
  out and returned with `strict=False` (`convert --skip-unmapped`).
- `write_xbrl_xml(..., taxonomy_packages=...)` takes typed domains from the
  dimension schemas, so `convert` needs no `--typed-domain` for EBA packages.
- `read_xbrl_xml` takes `taxonomy_packages`, and both readers check with them
  the entry point and the module's reference dates (1.5), filing indicator
  codes (1.6, 1.6.3), percentages above 50 (3.2) and, for XML, canonical
  namespace prefixes (3.5).
- xBRL-CSV packages with files outside the EBA layout break the `Package`
  rule (`unexpectedFile`, a warning).
- `ReportError.problems` lists every problem; reading xBRL-CSV tables
  collects up to 100 row-length, quoting and header problems before failing.
- With taxonomy packages, decimals are checked against the accuracy
  requirements per data type (2.18).
- xBRL-CSV tables must hold every column their metadata defines (rule 2)
  and a value in each key column of a reported fact (rule 4).
- Taxonomy packages may be one ZIP holding the packages, as the EBA
  publishes them.
- `dpmxbrl.filing.CHECKED_RULES` lists the findings each reader can record,
  without and with taxonomy packages.
- `SkippedFacts`, the type `write_xbrl_csv` returns.
- The public API is documented: every name in the `__all__` of `dpmxbrl`,
  `dpmxbrl.filing` and `dpmxbrl.frames`, and how table codes map to filing
  indicators.

### Changed

- **Breaking:** `write_xbrl_csv` to a path names the package's root folder
  as the ZIP file, without `.zip`, as the EBA filing rules ask;
  `default_package_root` still names it for streams.
- **Breaking:** the `dimensions`, `typed_dimensions` and `keys` mappings of
  facts that are read are read-only `dict`s that facts may share; assigning
  to one raises `TypeError`, so copy it with `dict()` to change it. They
  pickle, copy and serialize as plain dicts.
- `inspect` no longer prints a `(none)` per-template row for XML reports,
  whose facts have no template.
- `detect_format` is annotated to return `ReportFormat`.
- `write_xbrl_xml` declares only the prefixes the instance uses, writes a
  fact repeated in several xBRL-CSV tables once, and gives numeric facts
  without a unit `xbrli:pure`.

### Fixed

- Unused contexts and units (2.7, 2.22) are listed in document order.
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
