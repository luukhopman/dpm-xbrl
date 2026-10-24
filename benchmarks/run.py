"""Time dpm-xbrl and its peers on EBA reports, and record the results.

Each task runs one small script under ``benchmarks/tasks`` in the tool's own
virtual environment, under GNU ``/usr/bin/time``: one warm-up run, then the
best wall time of ``--runs`` runs, and the peak resident memory over those
runs. Results are merged into ``benchmarks/results.json``; ``render.py``
turns them into the tables the documentation includes.

Usage (see benchmarks/README.md for the setup)::

    uv run --all-extras python benchmarks/run.py --samples DIR --taxonomy DIR
    uv run --all-extras python benchmarks/run.py ... --only xml-corep --tool eba-xbridge
    uv run --all-extras python benchmarks/run.py ... --heavy   # also the slow runs

Every tool runs with ``python -I`` from ``benchmarks/.venvs/<tool>/bin/python``,
or the interpreter named by the environment variable ``BENCH_PYTHON_<TOOL>``
(such as ``BENCH_PYTHON_EBA_XBRIDGE``). dpm-xbrl falls back to the
interpreter running this script, so it measures the checked-out code.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE / "tasks"
RESULTS = HERE / "results.json"
PACKAGES = {
    "dpm-xbrl": "dpm-xbrl",
    "eba-xbridge": "eba-xbridge",
    "Arelle": "arelle-release",
    "py-xbrl": "py-xbrl",
    "brel-xbrl": "brel-xbrl",
}


@dataclass(frozen=True)
class Task:
    """One measured task: an id, a description and a command per tool."""

    id: str
    title: str
    commands: dict[str, list[str]]
    heavy: frozenset[str] = field(default_factory=frozenset)
    """Tools whose run takes minutes or gigabytes: run once, only with --heavy."""


def tasks(samples: Path, taxonomy: list[str], out: Path) -> list[Task]:
    """Return the benchmark tasks with their file paths filled in.

    ``out`` is an empty directory for converted output.

    Returns:
        list[Task]: Every task, in table order.
    """
    eba = samples / "2-official-eba-samples"
    big = samples / "3-massive-open-tables"
    corep_xml = str(eba / "EBA-COREP_OF.xbrl")
    finrep_xml = str(eba / "EBA-FINREP9.xbrl")
    corep_csv = str(eba / "EBA-COREP_OF.csv.zip")
    finrep_csv = str(eba / "EBA-FINREP9.csv.zip")
    le_7m = str(big / "COREP_LE-7.3M-facts.zip")
    finrep_7m = str(big / "FINREP9-7.3M-facts.zip")
    le_22m = str(big / "COREP_LE-21.9M-facts.zip")
    read = [str(TASKS_DIR / "dpmxbrl_read.py")]
    packages = [item for path in taxonomy for item in ("--taxonomy-package", path)]
    arelle = str(TASKS_DIR / "arelle_load.py")
    return [
        Task(
            "import",
            "Import the package",
            {
                "dpm-xbrl": ["-c", "import dpmxbrl"],
                "eba-xbridge": ["-c", "import xbridge.api"],
                "Arelle": ["-c", "from arelle import Cntlr"],
            },
        ),
        Task(
            "xml-corep",
            "Read `EBA-COREP_OF.xbrl` (22.9 MB, 21,314 facts)",
            {
                "dpm-xbrl": [*read, corep_xml],
                "eba-xbridge": [str(TASKS_DIR / "xbridge_load.py"), corep_xml],
                "Arelle": [arelle, corep_xml, *taxonomy],
            },
            heavy=frozenset({"Arelle"}),
        ),
        Task(
            "xml-finrep",
            "Read `EBA-FINREP9.xbrl` (13.3 MB, 13,384 facts)",
            {
                "dpm-xbrl": [*read, finrep_xml],
                "eba-xbridge": [str(TASKS_DIR / "xbridge_load.py"), finrep_xml],
                "Arelle": [arelle, finrep_xml, *taxonomy],
            },
            heavy=frozenset({"Arelle"}),
        ),
        Task(
            "csv-corep",
            "Read `EBA-COREP_OF.csv.zip` (25,677 facts)",
            {
                "dpm-xbrl": [*read, corep_csv],
                "Arelle": [arelle, corep_csv, *taxonomy],
            },
            heavy=frozenset({"Arelle"}),
        ),
        Task(
            "csv-corep-metadata",
            "Read `EBA-COREP_OF.csv.zip` with the taxonomy's metadata resolved",
            {"dpm-xbrl": [*read, corep_csv, *packages]},
        ),
        Task(
            "csv-finrep",
            "Read `EBA-FINREP9.csv.zip` (14,148 facts)",
            {"dpm-xbrl": [*read, finrep_csv]},
        ),
        Task(
            "filing-xml-corep",
            "EBA filing-rule check, `EBA-COREP_OF.xbrl`",
            {
                "dpm-xbrl": [*read, corep_xml],
                "eba-xbridge": [str(TASKS_DIR / "xbridge_validate.py"), corep_xml],
            },
        ),
        Task(
            "filing-csv-corep",
            "EBA filing-rule check, `EBA-COREP_OF.csv.zip`",
            {
                "dpm-xbrl": [*read, corep_csv],
                "eba-xbridge": [str(TASKS_DIR / "xbridge_validate.py"), corep_csv],
            },
        ),
        Task(
            "csv-7m-frames",
            "Read COREP_LE, 7.3 million facts (`frames` for dpm-xbrl)",
            {
                "dpm-xbrl": [*read, le_7m, "--frames"],
                "eba-xbridge": [str(TASKS_DIR / "xbridge_validate.py"), le_7m],
            },
        ),
        Task(
            "csv-7m-facts",
            "Read COREP_LE, 7.3 million facts, one object per fact",
            {"dpm-xbrl": [*read, le_7m]},
            heavy=frozenset({"dpm-xbrl"}),
        ),
        Task(
            "csv-7m-finrep-frames",
            "Read FINREP9, 7.3 million facts (`frames`)",
            {"dpm-xbrl": [*read, finrep_7m, "--frames"]},
        ),
        Task(
            "csv-22m-frames",
            "Read COREP_LE, 21.9 million facts in one 587 MB table (`frames`)",
            {"dpm-xbrl": [*read, le_22m, "--frames", "--large"]},
        ),
        Task(
            "convert-xml-csv",
            "Convert `EBA-COREP_OF.xbrl` to xBRL-CSV",
            {
                "eba-xbridge": [
                    str(TASKS_DIR / "xbridge_convert.py"),
                    corep_xml,
                    str(out),
                ]
            },
        ),
    ]


def sample_files(samples: Path) -> list[str]:
    """Return the EBA sample reports and the small synthetic packages.

    Returns:
        list[str]: Report paths, sorted.
    """
    eba = samples / "2-official-eba-samples"
    files = [
        *eba.glob("EBA-*"),
        *(eba / "all").iterdir(),
        *(samples / "1-start-here").glob("*.zip"),
    ]
    return sorted(str(path) for path in files)


def python_for(tool: str) -> list[str]:
    """Return the command that starts the tool's Python interpreter.

    The interpreter is named by ``BENCH_PYTHON_<TOOL>``, else it is
    ``benchmarks/.venvs/<tool>/bin/python``. For dpm-xbrl without either,
    it is the interpreter running this script.

    Returns:
        list[str]: The interpreter, isolated with ``-I``.
    """
    variable = "BENCH_PYTHON_" + tool.upper().replace("-", "_")
    venv = HERE / ".venvs" / tool.lower() / "bin" / "python"
    python = os.environ.get(variable)
    if python is None:
        python = str(venv) if venv.exists() or tool != "dpm-xbrl" else sys.executable
    return [python, "-I"]


def measure(command: list[str], runs: int, warm_up: bool) -> dict[str, object]:
    """Run a command under GNU time; return the best time and peak memory.

    Returns:
        dict[str, object]: Best wall seconds, peak RSS in MB, each run's
        time, the exit status and the last lines of output.
    """
    times: list[float] = []
    peak = 0
    status = 0
    output = ""
    for index in range(runs + (1 if warm_up else 0)):
        result = subprocess.run(
            ["/usr/bin/time", "-f", "%e %M", *command],
            capture_output=True,
            text=True,
            check=False,
        )
        wall, rss = result.stderr.strip().splitlines()[-1].split()
        status = result.returncode
        # GNU time's line is the last of stderr; before it, any error.
        lines = result.stdout.strip().splitlines()
        if status:
            lines = [
                line
                for line in result.stderr.strip().splitlines()[:-1]
                if not line.startswith("Command exited with non-zero status")
            ]
        output = lines[-1][:300] if lines else ""
        if warm_up and index == 0:
            continue
        times.append(float(wall))
        peak = max(peak, int(rss) // 1024)
        if status:
            break
    return {
        "best_s": min(times),
        "rss_mb": peak,
        "runs_s": times,
        "status": status,
        "output": output,
    }


def environment(tools: set[str]) -> dict[str, object]:
    """Describe the machine and the tool versions.

    Returns:
        dict[str, object]: Date, platform, CPU, memory, load and versions.
    """
    cpu = platform.processor()
    memory = ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                memory = f"{int(line.split()[1]) / 1024**2:.0f} GB"
    except OSError:
        pass
    versions = {}
    for tool in sorted(tools):
        script = (
            "import importlib.metadata as m, sys; "
            f"print(m.version({PACKAGES[tool]!r}), sys.version.split()[0])"
        )
        try:
            result = subprocess.run(
                [*python_for(tool), "-c", script],
                capture_output=True,
                text=True,
                check=True,
            )
            version, python = result.stdout.split()
            versions[tool] = {"version": version, "python": python}
        except (OSError, subprocess.CalledProcessError, ValueError):
            versions[tool] = {"version": "not installed", "python": ""}
    commit = subprocess.run(
        ["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(HERE), "status", "--porcelain", "--", "../src"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if dirty:
        commit += " with uncommitted changes"
    return {
        "date": dt.date.today().isoformat(),
        "platform": f"{platform.system()} {platform.release()}",
        "cpu": cpu,
        "cores": os.cpu_count(),
        "memory": memory,
        "load_average": [round(value, 1) for value in os.getloadavg()],
        "dpm_xbrl_commit": commit,
        "versions": versions,
    }


def main() -> int:
    """Run the selected tasks and merge their results into results.json.

    Returns:
        int: The exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", action="append", help="task id (repeatable)")
    parser.add_argument("--tool", action="append", help="tool name (repeatable)")
    parser.add_argument("--heavy", action="store_true", help="include slow runs")
    parser.add_argument(
        "--coverage", action="store_true", help="count the sample reports each reads"
    )
    arguments = parser.parse_args()
    if not Path("/usr/bin/time").exists():
        parser.error("GNU time (/usr/bin/time) is required")
    taxonomy = sorted(str(path) for path in arguments.taxonomy.glob("EBA_XBRL_*.zip"))
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    measured = results.setdefault("results", {})
    work = Path(tempfile.mkdtemp(prefix="dpmxbrl-bench-"))
    used: set[str] = set()
    try:
        for task in tasks(arguments.samples, taxonomy, work):
            if arguments.only and task.id not in arguments.only:
                continue
            for tool, command in task.commands.items():
                if arguments.tool and tool not in arguments.tool:
                    continue
                heavy = tool in task.heavy
                if heavy and not arguments.heavy:
                    continue
                used.add(tool)
                print(f"{task.id} / {tool} ...", end=" ", flush=True)
                record = measure(
                    [*python_for(tool), *command],
                    runs=1 if heavy else arguments.runs,
                    warm_up=not heavy,
                )
                record["title"] = task.title
                measured.setdefault(task.id, {})[tool] = record
                print(
                    f"{record['best_s']} s, {record['rss_mb']} MB, {record['output']}"
                )
        if arguments.coverage:
            files = sample_files(arguments.samples)
            coverage = results.setdefault("coverage", {"files": len(files)})
            coverage["files"] = len(files)
            for tool, script in (
                ("dpm-xbrl", "coverage_dpmxbrl.py"),
                ("eba-xbridge", "coverage_xbridge.py"),
            ):
                if arguments.tool and tool not in arguments.tool:
                    continue
                used.add(tool)
                result = subprocess.run(
                    [*python_for(tool), str(TASKS_DIR / script), *files],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                coverage[tool] = result.stdout.strip()
                print(f"coverage / {tool}: {coverage[tool]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if used:
        previous = results.get("environment", {})
        current = environment(used | set(previous.get("versions", {})))
        results["environment"] = current
        RESULTS.write_text(json.dumps(results, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
