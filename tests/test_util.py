import copy
import dataclasses
import gc
import json
import pickle  # ruff: ignore[suspicious-pickle-import]
from pathlib import Path

import pytest

from dpmxbrl import read_report
from dpmxbrl._util import gc_paused
from tests.support import XML_INSTANCE, open_files, zip_bytes


def test_gc_paused_restores_the_collector_after_nested_pauses() -> None:
    assert gc.isenabled()
    with gc_paused():
        with gc_paused():
            assert not gc.isenabled()
        assert not gc.isenabled()
    assert gc.isenabled()


def test_gc_paused_keeps_a_disabled_collector_disabled() -> None:
    gc.disable()
    try:
        with gc_paused():
            pass
        assert not gc.isenabled()
    finally:
        gc.enable()


def test_gc_paused_restores_the_collector_after_an_error() -> None:
    with pytest.raises(RuntimeError), gc_paused():
        raise RuntimeError
    assert gc.isenabled()


@pytest.mark.parametrize("source", ["xml", "csv"])
def test_read_facts_pickle_copy_and_serialize_as_dicts(source: str) -> None:
    data = XML_INSTANCE.encode() if source == "xml" else zip_bytes(open_files())
    report = read_report(data)
    assert pickle.loads(pickle.dumps(report)) == report  # ruff: ignore[suspicious-pickle-usage]
    for fact in report.facts:
        assert copy.deepcopy(fact) == fact
        json.dumps(dataclasses.asdict(fact))
        with pytest.raises(TypeError, match="read-only"):
            fact.dimensions["x"] = "y"  # ty: ignore[invalid-assignment]
    json.dumps(dataclasses.asdict(report), default=str)
    for mapping in (
        report.parameters,
        report.decimals_parameters,
        report.filing_indicators,
        report.namespaces,
    ):
        assert type(copy.copy(mapping)) is dict
        with pytest.raises(TypeError, match="read-only"):
            mapping["x"] = "y"  # ty: ignore[invalid-assignment]


def test_metadata_facts_have_read_only_mappings(tmp_path: Path) -> None:
    from tests.support import metadata_files, taxonomy_package, write_zip

    report = read_report(
        write_zip(tmp_path / "r.zip", metadata_files()),
        taxonomy_packages=[taxonomy_package(tmp_path / "t.zip")],
    )
    assert pickle.loads(pickle.dumps(report)) == report  # ruff: ignore[suspicious-pickle-usage]
    for fact in report.facts:
        for mapping in (fact.dimensions, fact.typed_dimensions, fact.keys):
            with pytest.raises(TypeError, match="read-only"):
                mapping["x"] = "y"  # ty: ignore[invalid-assignment]
