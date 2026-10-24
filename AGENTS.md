# AGENTS.md

Instructions for coding agents working on this repository. For using
dpm-xbrl as a library, see `docs/agents.md`
(<https://luukhopman.github.io/dpm-xbrl/agents/>).

## What this is

dpm-xbrl reads and writes EBA xBRL-CSV report packages and XBRL 2.1 XML
instances through one fact model, and records the EBA filing rules a report
breaks. Python 3.11+, standard library only at runtime. Import name
`dpmxbrl`, distribution name `dpm-xbrl`, CLI `dpm-xbrl`.

## Layout

```text
src/dpmxbrl/
  __init__.py      public API re-exports (__all__)
  model.py         Report, Fact, FilingFinding, Limits, ReportError
  reader.py        read_report, detect_format
  csv_reader.py    xBRL-CSV reader (EBA convention and resolved metadata)
  xml_reader.py    XBRL-XML reader (streaming, DOCTYPE rejected)
  writer.py        write_xbrl_csv, write_xbrl_xml
  filing.py        EBA filing rules: RULE_TITLES, FilingLog, checks, rule tuples
  frames.py        columnar reading into polars (frames extra)
  cli.py           dpm-xbrl inspect / convert
  _package.py      ZIP and directory packages, limits    (internal)
  _taxonomy.py     taxonomy package catalogs              (internal)
  _xmlsafe.py      XML prolog checks                      (internal)
  _util.py         shared helpers, GC pause               (internal)
tests/
  support.py       builds fixture packages and instances in code
  docs_samples.py  generates docs/samples from the fixtures
  test_docs.py     runs every docs example and docstring example
docs/              documentation site (Zensical), nav in zensical.toml
docs/samples/      small sample reports the docs examples read
scripts/build_docs.py  strict site build plus llms.txt and llms-full.txt
benchmarks/        comparisons with peer packages (not run by the tests)
```

## Commands

```text
uv sync --all-extras                 # environment with polars and isal
uv run pytest                        # all tests, including docs examples
uv run ruff check
uv run ruff format --check           # also formats Python in Markdown
uv run ty check
uv run python scripts/build_docs.py  # strict docs build into site/
uv run python -m tests.docs_samples  # regenerate docs/samples
```

All of these must pass before a commit.

## Conventions

- Google-style docstrings on every public name, with `Args`, `Returns`,
  `Raises` and, where it helps, an `Example` that runs as a doctest in a
  directory holding `docs/samples` (`tests/test_docs.py`).
- No new runtime dependencies. Optional ones go in an extra
  (`[project.optional-dependencies]`); docs tools go in the `docs`
  dependency group.
- Keep `__all__`, the docs and `CHANGELOG.md` in step with the code. A new
  public name needs an entry on the API pages under `docs/reference/api/`.
- Every behaviour has a test; build fixtures with `tests/support.py`.
- Every invalid or unsafe input raises `ReportError`; never let another
  exception escape a reader.
- Filing findings: rule numbers and tags are a stable contract; messages
  may change. Add new rules to `RULE_TITLES` and to
  `docs/reference/filing-rules.md`.
- Docs examples: a `text` block directly after a `python` block is its
  expected output; `console` blocks run `dpm-xbrl` commands (`$ echo $?`
  prints the exit status); `<!-- docs: skip -->` before a block skips it.
  Examples that need polars are marked `<!-- docs: requires-polars -->`
  (one block) or `requires: polars` in the front matter (whole page), so the
  tests pass without the frames extra. Show real output, never invented
  output.
- Shared link targets for the docs (such as the dpm-xl site) are in
  `docs/.snippets/links.md`.
- Commit messages follow Conventional Commits (`type(scope): description`),
  imperative, under 72 characters, no trailing period.
- British spelling in prose, as in the existing docs. Plain, precise
  sentences; no marketing language.
- dpm-xbrl is independent and not affiliated with the EBA; keep that
  statement where it appears.

## Release

1. Move the `Unreleased` changelog entries under a new version heading.
2. Set `version` in `pyproject.toml` and run `uv lock`.
3. Commit as `build: release X.Y.Z`, tag `vX.Y.Z` and publish a GitHub
   release. `.github/workflows/publish.yml` tests, builds and uploads to PyPI
   through trusted publishing; `.github/workflows/docs.yml` deploys the docs
   on every push to `main`.
