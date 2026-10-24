from datetime import date

import pytest

pytest.importorskip("polars")

from dpmxbrl import Fact, Report, ReportError, read_xbrl_csv, write_xbrl_csv
from dpmxbrl.frames import read_xbrl_csv_frames
from tests.support import csv_text, open_files, report_json, write_zip


def report() -> Report:
    facts = [Fact("100", datapoint="dp1", template="c_01.00")]
    facts += [
        Fact(
            str(n),
            datapoint="dp2",
            template="c_27.00",
            keys={"qINC": f"L{n}", "qNCO": "eba_qCO:qx2000"},
        )
        for n in range(500)
    ]
    facts.append(Fact(None, datapoint="dp3", template="c_01.00"))
    return Report(
        format="xbrl-csv",
        entry_point="http://example/mod/corep_le.json",
        entity_scheme="http://standards.iso.org/iso/17442",
        entity_id="LEI.CON",
        reference_date=date(2026, 12, 31),
        base_currency="iso4217:EUR",
        parameters={},
        decimals_parameters={"decimalsMonetary": 0},
        filing_indicators={"C_01.00": True, "C_27.00": True},
        facts=tuple(facts),
        namespaces={},
    )


def test_frames_match_the_object_reader(tmp_path) -> None:
    path = tmp_path / "report.zip"
    write_xbrl_csv(report(), path)
    objects = read_xbrl_csv(path)
    frames = read_xbrl_csv_frames(path)
    assert frames.report.facts == ()
    assert frames.report.reference_date == objects.reference_date
    assert frames.report.decimals_parameters == {"decimalsMonetary": 0}
    assert frames.fact_count == len(objects.facts)
    open_table = frames.tables["c_27.00"]
    assert set(open_table.columns) == {"datapoint", "factValue", "qINC", "qNCO"}
    assert open_table.height == 500
    closed = frames.tables["c_01.00"].to_dicts()
    assert {"datapoint": "dp3", "factValue": None} in closed


def test_metadata_arrives_before_tables_and_can_abort(tmp_path) -> None:
    path = tmp_path / "report.zip"
    write_xbrl_csv(report(), path)
    seen: list[Report] = []
    frames = read_xbrl_csv_frames(path, on_metadata=seen.append)
    (header,) = seen
    assert header.entry_point == "http://example/mod/corep_le.json"
    assert header.reference_date == date(2026, 12, 31)
    assert header.filing_indicators == {"C_01.00": True, "C_27.00": True}
    assert header.facts == ()
    assert frames.fact_count == 502

    class Stop(Exception):
        pass

    def stop(_header: Report) -> None:
        raise Stop

    with pytest.raises(Stop):
        read_xbrl_csv_frames(path, on_metadata=stop)


def _replace_entry(path, suffix: str, text: str) -> None:
    import zipfile

    with zipfile.ZipFile(path) as source:
        entries = {info.filename: source.read(info) for info in source.infolist()}
    with zipfile.ZipFile(path, "w") as target:
        for name, data in entries.items():
            target.writestr(name, text.encode() if name.endswith(suffix) else data)


def test_duplicates_and_special_values_match_the_object_reader(tmp_path) -> None:
    path = tmp_path / "report.zip"
    write_xbrl_csv(report(), path)
    _replace_entry(
        path,
        "c_27.00.csv",
        "datapoint,factValue,qINC,qNCO\n"
        "dp2,1,A,x\n"
        "dp2,1,A,x\n"  # exact repeat: ignored
        "dp2,2,B,x\n"
        "dp2,3,B,x\n"  # same cell and key, other value: kept, reported
        "dp2,#nil,C,x\n"
        "dp2,#empty,D,x\n"
        "dp2,##E,E,x\n",
    )
    objects = read_xbrl_csv(path)
    frames = read_xbrl_csv_frames(path)

    table = frames.tables["c_27.00"]
    rows = sorted(
        (row["qINC"], row["factValue"]) for row in table.iter_rows(named=True)
    )
    assert rows == [("A", "1"), ("B", "2"), ("B", "3"), ("C", None), ("E", "#E")]
    assert rows == sorted(
        (fact.keys["qINC"], fact.value)
        for fact in objects.facts
        if fact.template == "c_27.00"
    )
    warnings = " | ".join(frames.report.warnings)
    assert "duplicate facts ignored" in warnings
    assert "conflicting duplicate facts kept" in warnings

    def values(report) -> list[tuple[str, int, tuple[str, ...]]]:
        return [
            (item.code, item.count, item.examples)
            for item in report.filing
            if item.rule in {"2.19", "xBRL-CSV 5"}
        ]

    assert (
        values(frames.report)
        == values(objects)
        == [
            ("emptyUsed", 1, ("reports/c_27.00.csv:7",)),
            ("nilUsed", 2, ("reports/c_01.00.csv:3", "reports/c_27.00.csv:6")),
        ]
    )


def test_dropped_rows_name_the_data_rows_removed(tmp_path) -> None:
    files = open_files(
        **{
            "reports/c_01.00.csv": csv_text("datapoint,factValue", "dp1,1", "dp2,2"),
            "reports/c_27.00.csv": csv_text(
                "datapoint,factValue,c0010",
                "dp100,1,A",  # 0
                "dp100,,B",  # 1: empty value
                "dp100,#none,C",  # 2
                "dp100,1,A",  # 3: repeats row 0
                "dp100,#nil,D",  # 4
                "dp100,#nil,D",  # 5: repeats row 4
                "dp100,5,E",  # 6
            ),
        }
    )
    frames = read_xbrl_csv_frames(write_zip(tmp_path / "report.zip", files))
    assert frames.dropped_rows == {"c_27.00": (1, 2, 3, 5)}
    assert frames.tables["c_27.00"]["c0010"].cast(str).to_list() == ["A", "D", "E"]
    assert (
        "reports/c_27.00.csv: duplicate facts ignored (1 occurrence, first at "
        "reports/c_27.00.csv:5)"
    ) in frames.report.warnings
    nil = next(item for item in frames.report.filing if item.code == "nilUsed")
    assert nil.examples == ("reports/c_27.00.csv:6", "reports/c_27.00.csv:7")


def test_dropped_rows_continue_across_the_files_of_a_template(tmp_path) -> None:
    tables = {
        "a": {"url": "c_27.00.a.csv", "template": "c_27.00"},
        "b": {"url": "c_27.00.b.csv", "template": "c_27.00"},
    }
    files = open_files(
        **{
            "reports/report.json": report_json(tables=tables),
            "reports/c_01.00.csv": csv_text("datapoint,factValue", "dp1,1"),
            "reports/c_27.00.csv": None,
            "reports/c_27.00.a.csv": csv_text(
                "datapoint,factValue,c0010", "dp100,1,A", "dp100,,B"
            ),
            "reports/c_27.00.b.csv": csv_text(
                "datapoint,factValue,c0010", "dp100,2,C", "dp100,2,C", "dp100,3,D"
            ),
        }
    )
    frames = read_xbrl_csv_frames(write_zip(tmp_path / "report.zip", files))
    assert frames.dropped_rows == {"c_27.00": (1, 3)}
    assert frames.tables["c_27.00"]["c0010"].cast(str).to_list() == ["A", "C", "D"]


def test_tables_arrive_once_their_last_file_is_read(tmp_path) -> None:
    tables = {
        "a": {"url": "c_27.00.a.csv", "template": "c_27.00"},
        "b": {"url": "c_27.00.b.csv", "template": "c_27.00"},
    }
    files = open_files(
        **{
            "reports/report.json": report_json(tables=tables),
            "reports/c_01.00.csv": csv_text("datapoint,factValue", "dp1,1", "dp2,"),
            "reports/c_27.00.csv": None,
            "reports/c_27.00.a.csv": csv_text(
                "datapoint,factValue,c0010", "dp100,1,A", "dp100,,B"
            ),
            "reports/c_27.00.b.csv": csv_text(
                "datapoint,factValue,c0010", "dp100,2,C", "dp100,2,C", "dp100,3,D"
            ),
        }
    )
    path = write_zip(tmp_path / "report.zip", files)
    seen: list[tuple[str, object, tuple[int, ...]]] = []
    frames = read_xbrl_csv_frames(path, on_table=lambda *table: seen.append(table))

    # Each template once, in package order, as ReportFrames holds it.
    assert [template for template, _, _ in seen] == list(frames.tables)
    for template, frame, dropped in seen:
        assert frame is frames.tables[template]
        assert dropped == frames.dropped_rows.get(template, ())
    assert frames.dropped_rows == {"c_01.00": (1,), "c_27.00": (1, 3)}

    class Stop(Exception):
        pass

    def stop(*_table: object) -> None:
        raise Stop

    with pytest.raises(Stop):
        read_xbrl_csv_frames(path, on_table=stop)


def test_files_read_together_report_in_package_order(tmp_path) -> None:
    files = {
        "reports/c_01.00.csv": csv_text("datapoint,factValue", "dp1,#nil"),
        **{
            f"reports/c_{n:02d}.00.csv": csv_text(
                "datapoint,factValue,c0010", f"dp{n},#nil,A", f"dp{n},1,A"
            )
            for n in range(2, 12)
        },
    }
    broken = {
        **files,
        "reports/c_05.00.csv": "no header\n",
        "reports/c_12.00.csv": "no header\n",
    }
    path = write_zip(tmp_path / "report.zip", open_files(**broken))
    # The first broken file in package order fails the read.
    with pytest.raises(ReportError, match=r"reports/c_05\.00\.csv:1"):
        read_xbrl_csv_frames(path)

    frames = read_xbrl_csv_frames(write_zip(tmp_path / "ok.zip", open_files(**files)))
    nil = next(item for item in frames.report.filing if item.code == "nilUsed")
    assert nil.count == 11
    assert nil.examples == tuple(f"reports/c_{n:02d}.00.csv:2" for n in range(1, 6))
    tables = [
        warning.split(":")[0]
        for warning in frames.report.warnings
        if "conflicting duplicate facts" in warning
    ]
    assert tables == [f"reports/c_{n:02d}.00.csv" for n in range(2, 12)]
