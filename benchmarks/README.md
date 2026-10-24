# Benchmarks

Scripts that time dpm-xbrl and its peers on EBA reports. They are not part
of the package or the test suite. The results feed the
[benchmarks page](https://luukhopman.github.io/dpm-xbrl/project/benchmarks/)
of the documentation, which includes `results.md`.

| File | Does |
| --- | --- |
| `run.py` | Runs the tasks, merges the measurements into `results.json`. |
| `render.py` | Writes `results.md` from `results.json`. |
| `tasks/*.py` | One small script per tool and task, run in the tool's own environment. |

## Method

Each measurement runs a task script in a fresh process under GNU
`/usr/bin/time`: one warm-up run, then the best wall time of three runs,
and the peak resident set size over those runs. Runs marked heavy (Arelle,
and `read_report` on 7.3 million facts) take minutes or gigabytes; they run
once, without a warm-up, and only with `--heavy`. Each tool runs from its
own virtual environment with `python -I`. Times include starting Python
and importing the package. Nothing reaches the network: Arelle runs
offline with the EBA taxonomy packages.

Run on an otherwise idle machine; `results.md` records the load average.

## Set up

Use the same Python for every tool (the published numbers use 3.12).

```text
cd dpm-xbrl
for tool in dpm-xbrl eba-xbridge arelle py-xbrl brel-xbrl; do
  uv venv --python 3.12 benchmarks/.venvs/$tool
done
uv pip install --python benchmarks/.venvs/dpm-xbrl/bin/python -e ".[fast,frames]"
uv pip install --python benchmarks/.venvs/eba-xbridge/bin/python eba-xbridge==2.2.1
uv pip install --python benchmarks/.venvs/arelle/bin/python arelle-release==2.47.2
uv pip install --python benchmarks/.venvs/py-xbrl/bin/python py-xbrl==3.0.3
uv pip install --python benchmarks/.venvs/brel-xbrl/bin/python brel-xbrl==0.8.2a1
```

`BENCH_PYTHON_<TOOL>` (such as `BENCH_PYTHON_EBA_XBRIDGE=/path/to/python`)
points a tool at another interpreter instead.

## Data

The samples directory (`--samples`) must hold:

```text
1-start-here/*.zip                         small synthetic packages
2-official-eba-samples/EBA-COREP_OF.xbrl   EBA 4.2 sample instances and packages
2-official-eba-samples/EBA-FINREP9.xbrl
2-official-eba-samples/EBA-COREP_OF.csv.zip
2-official-eba-samples/EBA-FINREP9.csv.zip
2-official-eba-samples/all/*               the other EBA 4.2 samples
3-massive-open-tables/COREP_LE-7.3M-facts.zip
3-massive-open-tables/FINREP9-7.3M-facts.zip
3-massive-open-tables/COREP_LE-21.9M-facts.zip
```

The EBA samples come with the EBA's 4.2 reporting framework release on
eba.europa.eu. The large packages are synthetic EBA-convention packages
with one open table of millions of rows; any package of that shape will do.

The taxonomy directory (`--taxonomy`) holds the EBA 4.2 taxonomy packages,
`EBA_XBRL_4.2_Dictionary_4.2.0.0.zip`,
`EBA_XBRL_4.2_Reporting_Frameworks_4.2.0.0.zip` and
`EBA_XBRL_4.2_Severity_4.2.0.0.zip`, also from eba.europa.eu.

## Run

```text
uv run python benchmarks/run.py --samples SAMPLES --taxonomy TAXONOMY --coverage
uv run python benchmarks/run.py --samples SAMPLES --taxonomy TAXONOMY --heavy --tool Arelle
uv run python benchmarks/run.py --samples SAMPLES --taxonomy TAXONOMY --heavy --only csv-7m-facts
python benchmarks/render.py
```

`--only TASK` and `--tool TOOL` (both repeatable) re-run part of the
table; other results in `results.json` are kept. Commit `results.json` and
`results.md` together.

py-xbrl and brel-xbrl are not timed: on the EBA samples, py-xbrl cannot
find the DPM 2.0 taxonomy (`TaxonomyNotFound`) and brel-xbrl downloads the
taxonomy over HTTP and runs out of memory. `tasks/pyxbrl_load.py` and
`tasks/brel_load.py` reproduce those attempts.
