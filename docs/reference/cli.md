---
description: Every dpm-xbrl command and option (inspect, convert, limits, --fail-on, --columnar), the output, and the exit statuses.
---

# CLI

Installing dpm-xbrl installs the `dpm-xbrl` command. It has two
subcommands: `inspect` summarizes a report and the filing rules it breaks,
`convert` writes a report in the other format. `python -m dpmxbrl.cli` is
not provided; use `dpm-xbrl`, or `uvx dpm-xbrl` without installing.

```console
$ dpm-xbrl --help
usage: dpm-xbrl [-h] [--version] {inspect,convert} ...

Inspect and convert EBA xBRL-CSV and XBRL-XML reports.

positional arguments:
  {inspect,convert}
    inspect          summarize a report and the EBA filing rules it breaks
    convert          convert a report (.zip -> xBRL-CSV, .xbrl/.xml -> XML)

options:
  -h, --help         show this help message and exit
  --version          show program's version number and exit

examples:
  dpm-xbrl inspect report.zip
  dpm-xbrl inspect instance.xbrl --json
  dpm-xbrl inspect report.zip --fail-on error
  dpm-xbrl convert report.zip instance.xbrl --taxonomy-package taxonomy.zip
```

## Exit statuses

| Status | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | The report cannot be read or written: `error: ...` on standard error, with a `hint:` naming the option when a limit is hit. |
| 2 | Usage error (unknown option, missing argument). |
| 3 | `inspect --fail-on` found a broken filing rule of that severity. |

## `dpm-xbrl inspect`

```console
$ dpm-xbrl inspect --help
usage: dpm-xbrl inspect [-h] [--json] [--columnar] [--fail-on {error,warning}]
                        [--max-file-size N] [--max-total-size N]
                        [--max-zip-entries N] [--max-facts N]
                        [--taxonomy-package ZIP]
                        path

positional arguments:
  path                  report package (.zip), directory or XML instance

options:
  -h, --help            show this help message and exit
  --json                print JSON
  --columnar            count xBRL-CSV facts with polars: seconds instead of
                        minutes for millions of facts, checking special fact
                        values only (frames extra)
  --fail-on {error,warning}
                        exit with status 3 when the report breaks a filing
                        rule of this severity or worse
  --taxonomy-package ZIP
                        local taxonomy package used to resolve xBRL-CSV
                        metadata

limits:
  resource limits for untrusted input (defaults in the documentation)

  --max-file-size N     largest uncompressed file, in bytes
  --max-total-size N    largest uncompressed package, in bytes
  --max-zip-entries N   most entries in a package
  --max-facts N         most facts in a report
```

`inspect` reads the report with `read_report` (format detected as in
[`detect_format`][dpmxbrl.detect_format]) and prints the format, entry
point, entity, reference date, base currency, filing indicators (reported
of total), the fact count, the count per template (xBRL-CSV only), the
reader warnings and the EBA filing rules broken, errors counted as "must be
fixed" and warnings as "recommended":

```console
$ dpm-xbrl inspect instance.xbrl
Format:            xbrl-xml
Entry point:       http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_le.xsd
Entity:            SYNTHETICDPMXL000002.CON (https://eurofiling.info/eu/rs)
Reference date:    2025-12-31
Base currency:     iso4217:EUR
Filing indicators: 2 reported of 3
Facts:             3
Warnings: 0
EBA filing rules broken: 0 must be fixed, 1 recommended
  - [warning] File naming The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.
```

A finding that occurs more than once ends in `(N times)`.

| Option | Effect |
| --- | --- |
| `--json` | Print the summary as JSON; see [JSON output](json-output.md). |
| `--fail-on error` | Exit with status 3 if any `error` finding is present. |
| `--fail-on warning` | Exit with status 3 if any finding is present. |
| `--columnar` | Count xBRL-CSV facts with the `frames` extra (polars) instead of building every fact. Prints a note on standard error; checks special fact values only. Falls back to a full read, with a note, for tables described by metadata; ignored with a note for XML. Fails with status 1 without the extra. |
| `--taxonomy-package ZIP` | Resolve xBRL-CSV metadata from a local taxonomy package. Repeat for several. |
| `--max-file-size N` | Raise or lower [`Limits.max_file_size`][dpmxbrl.Limits] (default 536870912). |
| `--max-total-size N` | `Limits.max_total_size` (default 2147483648). |
| `--max-zip-entries N` | `Limits.max_zip_entries` (default 10000). |
| `--max-facts N` | `Limits.max_facts` (default 20000000). |

Limit values are positive whole numbers; `_` separators are accepted, as
in `--max-facts 30_000_000`.

## `dpm-xbrl convert`

```console
$ dpm-xbrl convert --help
usage: dpm-xbrl convert [-h] [--typed-domain DIMENSION=ELEMENT] [--root ROOT]
                        [--max-file-size N] [--max-total-size N]
                        [--max-zip-entries N] [--max-facts N]
                        [--taxonomy-package ZIP]
                        input output

positional arguments:
  input                 report to read
  output                file to write

options:
  -h, --help            show this help message and exit
  --typed-domain DIMENSION=ELEMENT
                        typed domain element for a typed dimension (XML
                        output)
  --root ROOT           top-level folder name (xBRL-CSV output)
  --taxonomy-package ZIP
                        local taxonomy package used to resolve xBRL-CSV
                        metadata

limits:
  resource limits for untrusted input (defaults in the documentation)

  --max-file-size N     largest uncompressed file, in bytes
  --max-total-size N    largest uncompressed package, in bytes
  --max-zip-entries N   most entries in a package
  --max-facts N         most facts in a report
```

`convert` reads `input` as `inspect` does, prints each reader warning on
standard error as `warning: ...`, and writes `output` in the format its
suffix names: `.zip` writes an xBRL-CSV package with
[`write_xbrl_csv`][dpmxbrl.write_xbrl_csv], `.xbrl` or `.xml` an XBRL-XML
instance with [`write_xbrl_xml`][dpmxbrl.write_xbrl_xml]. Any other suffix
is an error:

```console
$ dpm-xbrl convert report.zip report.txt
error: report.txt: output must end in .zip, .xbrl or .xml
$ echo $?
1
```

| Option | Effect |
| --- | --- |
| `--typed-domain DIMENSION=ELEMENT` | Typed domain element of a typed dimension, for XML output, such as `eba_dim:qINC=eba_typ:qCC` or with the element in Clark notation, `eba_dim:qINC={http://www.eba.europa.eu/xbrl/crr/dict/typ}qCC`. Repeat for each typed dimension the facts use. |
| `--root NAME` | Top-level folder of the xBRL-CSV package; defaults to `<entity id>_<reference date>`. |
| `--taxonomy-package ZIP`, `--max-*` | As for `inspect`. |

See [convert between formats](../guides/convert-formats.md) for which
conversions are possible.
