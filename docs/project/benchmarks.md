---
description: dpm-xbrl compared with eba-xbridge, Arelle, py-xbrl and brel-xbrl on EBA reports - capabilities, licence and reproducible timings.
---

# Benchmarks

dpm-xbrl compared with the Python packages used for the same job:
eba-xbridge, Arelle, py-xbrl and brel-xbrl. Their scope differs, so the
capabilities come first; the timings cover only tasks several tools do.

## Capabilities

| | dpm-xbrl | eba-xbridge | Arelle | py-xbrl | brel-xbrl |
| --- | --- | --- | --- | --- | --- |
| Licence | MIT | Apache-2.0 | Apache-2.0 | GPL-3.0 | Apache-2.0 |
| Runtime dependencies | none | lxml, numpy, pandas | 15 | 2 | 17 |
| Reads EBA XBRL-XML | yes | yes | with the taxonomy | no | no |
| Reads EBA xBRL-CSV | yes | no | with the taxonomy | no | no |
| Works without the taxonomy | yes | yes | no | no | no |
| Millions of facts in seconds | yes (`frames`) | no | no | no | no |
| Converts XML → xBRL-CSV | yes, EBA layout | yes, EBA layout | generic OIM (plugin) | no | no |
| Converts xBRL-CSV → XML | yes | no | generic OIM (plugin) | no | no |
| EBA filing rules, with rule numbers | yes, while reading | yes | older plugin | no | no |
| CLI with JSON and CI exit status | yes | JSON | yes | no | no |
| *Outside dpm-xbrl's scope:* | | | | | |
| Taxonomy validation (schemas, formulas) | no | no | yes | no | no |
| EBA validation rules on values | via [dpm-xl](https://luukhopman.github.io/dpm-xl/) | no | yes, slowly | no | no |
| Other filings (SEC, ESEF) | no | no | yes | yes | yes |

py-xbrl cannot find the DPM 2.0 taxonomy, and brel-xbrl downloads it and
runs out of memory, so neither reads EBA reports today.

## Timings

--8<-- "benchmarks/results.md"

- dpm-xbrl and eba-xbridge read the same facts from every EBA XML sample;
  Arelle also counts filing indicators as facts.
- Arelle needs the taxonomy to load any report, which makes it slow and
  large here; in return it validates against the taxonomy.
- Converted packages match the EBA's own xBRL-CSV samples table for table
  on all 53 official sample pairs.

## Reproduce

Set up `benchmarks/.venvs` as in
[`benchmarks/README.md`](https://github.com/luukhopman/dpm-xbrl/blob/main/benchmarks/README.md),
then run `uv run python benchmarks/run.py --samples SAMPLES --taxonomy
TAXONOMY` and `python benchmarks/render.py`.
