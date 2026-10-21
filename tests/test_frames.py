from datetime import date

import pytest

pytest.importorskip("polars")

from xbrlreport import Fact, Report, read_xbrl_csv, write_xbrl_csv
from xbrlreport.frames import read_xbrl_csv_frames


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
