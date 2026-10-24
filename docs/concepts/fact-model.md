---
description: The Report and Fact dataclasses, what each field holds for xBRL-CSV and XBRL-XML, read-only mappings, qnames, and memory and speed.
---

# The fact model

dpm-xbrl reads both serializations into the same two frozen, slotted
dataclasses, defined in `dpmxbrl.model` and exported from `dpmxbrl`:
[`Report`][dpmxbrl.Report] for the report as a whole and
[`Fact`][dpmxbrl.Fact] for each reported value. The model is neutral: it
keeps what the file says, as written, and does not interpret values against
a taxonomy.

## Report

A `Report` holds the report header and its facts:

| Field | xBRL-CSV | XBRL-XML |
| --- | --- | --- |
| `format` | `"xbrl-csv"` | `"xbrl-xml"` |
| `entry_point` | first `documentInfo.extends` URL | `link:schemaRef` |
| `entity_scheme`, `entity_id` | from `entityID` such as `rs:5299...CON`; the prefix is looked up in `namespaces` | the context identifier's scheme and value, the most common across facts |
| `reference_date` | `refPeriod` | the instant, or a duration's end date, most common across facts |
| `base_currency` | `baseCurrency` | the most common single-measure `iso4217` unit |
| `parameters` | every report parameter, as strings | empty |
| `decimals_parameters` | parameters named `decimals*`, as integers; `None` for `#none` and `INF` | empty |
| `filing_indicators` | `FilingIndicators.csv`, code to reported | `find:filingIndicator`, `find:filed` defaulting to true |
| `facts` | one per table row value, in file order | one per fact element, in document order |
| `namespaces` | prefix to URI from the metadata | the instance's declarations |
| `warnings` | how the file was read, deterministic order | same |
| `filing` | [EBA filing rules broken](filing-rules.md), in rule order | same |

## Fact

| Field | xBRL-CSV, EBA convention | xBRL-CSV, resolved metadata | XBRL-XML |
| --- | --- | --- | --- |
| `value` | the cell as written; `None` for `#nil` | same | the element text; `None` for `xsi:nil="true"` |
| `concept` | `None` | concept qname | element qname |
| `datapoint` | `datapoint` column, such as `dp84817` | property-group key | `None` |
| `template` | file stem, such as `c_27.00` | template id | `None` |
| `dimensions` | empty | explicit dimension to member | `xbrldi:explicitMember` |
| `typed_dimensions` | empty | typed dimension to value | `xbrldi:typedMember` text, stripped |
| `keys` | other columns, in header order | key columns | empty |
| `unit` | `None` | unit | `iso4217:EUR`, `xbrli:pure`, `num/denom`, `a*b` |
| `decimals` | `None`; use `Report.decimals_parameters` | from metadata | `decimals`; `None` for `INF` |
| `location` | `reports/c_27.00.csv:3`, the physical line | same | `instance.xbrl#f12`, the fact id, or `#factN` for the Nth fact without one |

Values are always the lexical text from the file. dpm-xbrl does not parse
numbers or dates in fact values, because their data type lives in the
taxonomy; parse them where you know the type.

```python
from dpmxbrl import read_report

instance = read_report("instance.xbrl")
for fact in instance.facts:
    print(fact.concept, repr(fact.value), fact.unit, fact.decimals, fact.location)
```

```text
eba_met:mi53 '56058000' iso4217:EUR -3 instance.xbrl#f1
eba_met:pi1 '0.71' xbrli:pure 4 instance.xbrl#f2
eba_met:qNCO 'Northwind Holdings' None None instance.xbrl#f3
```

## Read-only mappings

The mappings of a report that is read are read-only `dict`s: a fact's
`dimensions`, `typed_dimensions` and `keys`, which facts may share, and the
report's `parameters`, `decimals_parameters`, `filing_indicators` and
`namespaces`. Assigning to one raises `TypeError`; copy it with `dict()` to
change it. They pickle, copy and serialize as plain dicts.

```python
fact = instance.facts[2]
try:
    fact.dimensions["eba_dim:qNCO"] = "eba_qCO:qx2001"
except TypeError as error:
    print(error)
```

```text
report and fact mappings are read-only; copy one with dict()
```

## Qnames

Qnames use prefixes declared in `Report.namespaces`. XML keeps the
instance's own prefixes; a namespace declared again deeper in the document
under another prefix is rendered with the first prefix bound to it.
[`local_name`][dpmxbrl.local_name] returns the part after the prefix, for
prefixed and Clark-notation names:

```python
from dpmxbrl import local_name

print(
    local_name("eba_met:mi53"),
    local_name("{http://www.eba.europa.eu/xbrl/crr/dict/met}mi53"),
)
```

```text
mi53 mi53
```

## Memory and speed

`read_report` builds one `Fact` per value, about 5 µs and 0.7 KB per fact.
A report with 7 million open-table facts reads in 30 to 50 seconds,
depending on the machine. To keep that low, facts share empty mappings,
datapoint codes and the dimensions of an XML context, and while the readers
build facts they pause Python's cyclic garbage collector for the whole
process (facts form no reference cycles) and restore it afterwards. Nested
and concurrent reads re-enable it only when the last one ends, and only if
it was enabled before.

For millions of facts, read the tables as polars frames instead; see
[read large reports as frames](../guides/large-reports.md).
