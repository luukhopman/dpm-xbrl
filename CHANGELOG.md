# Changelog

All notable changes to this project are documented here. The project follows
[semantic versioning](https://semver.org).

## 1.0.0 - 2026-10-24

### Added

- Python 3.15 support, tested in CI on 3.11 to 3.15 with and without extras.
  On 3.15 the `fast` extra installs without `isal`, which has no 3.15
  wheels yet, and ZIP entries are inflated with zlib.
- A documentation site at https://luukhopman.github.io/dpm-xbrl/, with
  `llms.txt` and `llms-full.txt` for AI agents.
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
- Both writers take `limits=`, for reading the taxonomy packages.
- `taxonomy_packages` may be one path, a `str` or `os.PathLike`, as well as
  a sequence of them.
- `EntryPointWarning`, which `write_xbrl_xml` gives when it names an XSD
  entry point by the EBA's naming rather than from the taxonomy packages.
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
  and a value in each key column of a reported fact (rule 4);
  `dpmxbrl.filing.MISSING_KEY_VALUE` is the rule 4 tuple for callers.
- Taxonomy packages may be one ZIP holding the packages, as the EBA
  publishes them.
- `dpmxbrl.filing.checked_rules(format, *, taxonomy, columnar)` gives the
  findings a reader can record in each mode, so callers can avoid
  reporting a rule twice.
- `SkippedFacts`, the type `write_xbrl_csv` returns: a tuple of
  `SkippedFact(fact, reason, code)`, with stable codes.
- `DecimalsWarning` names the facts whose decimals a converted package's
  `decimals*` parameter lowers.
- `Limits.max_taxonomy_entries` bounds the entries of a taxonomy package
  ZIP, and files read from taxonomy packages count towards
  `Limits.max_total_size`.
- `filing_indicator_code` maps a table template to its filing indicator.
- `detect_format(..., name=...)` names the input in its errors.
- The public API is documented: every name in the `__all__` of `dpmxbrl`,
  `dpmxbrl.filing` and `dpmxbrl.frames`, and how table codes map to filing
  indicators.

### Changed

- **Breaking:** `write_xbrl_csv` to a path names the package's root folder
  as the ZIP file, without `.zip`, as the EBA filing rules ask;
  `default_package_root` still names it for streams.
- **Breaking:** the mappings of a report that is read are read-only
  `dict`s: the `dimensions`, `typed_dimensions` and `keys` of its facts,
  which facts may share, and its `parameters`, `decimals_parameters`,
  `filing_indicators` and `namespaces`. Assigning to one raises
  `TypeError`, so copy it with `dict()` to change it. They pickle, copy and
  serialize as plain dicts.
- `inspect` no longer prints a `(none)` per-template row for XML reports,
  whose facts have no template.
- `detect_format` is annotated to return `ReportFormat`.
- `Report.facts_for_template` also matches a table by its filing indicator,
  so `C_07.00` selects the facts of `c_07.00.a` and `c_07.00.b`.
- `write_xbrl_xml` declares only the prefixes the instance uses, writes a
  fact repeated in several xBRL-CSV tables once, and gives numeric facts
  without a unit `xbrli:pure`.

### Fixed

- Unused contexts and units (2.7, 2.22) are listed in document order.
- `write_xbrl_xml` references the module's `.xsd` entry point when the
  report extends its `.json` one: the one the taxonomy packages list, or by
  the EBA's naming with an `EntryPointWarning`.
- The error for a damaged ZIP uses the `name=` given to `read_report`.
- `write_xbrl_csv` declares the Report Packages 1.0 type
  `https://xbrl.org/report-package/2023` that EBA packages use; the
  `/2023/xbrl-csv` it wrote before is not a defined type, and other tools
  reject it. The reader accepts `/2023` and `/2023/xbr`, and reads the old
  value with a warning.
- A DOCTYPE in a UTF-16 instance without a byte order mark is rejected, and
  such an instance breaks filing rule 1.4.
- Every unreadable input raises `ReportError`: unknown or multi-byte XML
  encodings, unreadable files, ZIP entries with an unsupported compression
  method or version, damaged report and taxonomy package archives, JSON
  nested too deeply and a malformed `propertiesFrom`. URLs that cannot be
  parsed are unresolved rather than raising `ValueError`, and
  `ReportError` subclasses pickle with their `problems`.
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
