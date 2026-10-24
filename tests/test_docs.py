"""Run the examples in the documentation, so the docs cannot drift.

Every Markdown page under ``docs/`` (and the README) is checked, in a fresh
directory holding the sample reports from ``docs/samples``:

* ``python`` blocks run in order in one namespace per page. A ``text`` block
  that directly follows a ``python`` block is its expected output and must
  match what the code prints.
* ``console`` blocks hold ``$ dpm-xbrl ...`` commands, each followed by its
  expected output (stdout and stderr, as a terminal shows them);
  ``$ echo $?`` prints the previous command's exit status.

``<!-- docs: skip -->`` on the line before a block leaves it out. Pages that
import ``polars`` are skipped when it is not installed (``uv sync`` installs
it with the ``docs`` group).

The docstring examples of every public module run as doctests, in the same
kind of directory, and the committed samples must match their generator.
"""

from __future__ import annotations

import contextlib
import doctest
import importlib
import io
import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from dpmxbrl.cli import main
from tests.docs_samples import SAMPLES, samples

ROOT = Path(__file__).parent.parent
PAGES = [
    *sorted(
        path for path in (ROOT / "docs").rglob("*.md") if ".snippets" not in path.parts
    ),
    ROOT / "README.md",
]
OPTIONAL_MODULES = {"polars"}
FENCE = re.compile(r"^(?P<indent> *)```(?P<lang>[\w-]*)[^\n]*$")
MARKER = re.compile(r"^\s*<!-- docs: (?P<marker>[\w-]+) -->\s*$")


@dataclass
class Block:
    """One fenced code block of a page."""

    lang: str
    code: str
    line: int
    marker: str | None
    follows_python: bool


def blocks(path: Path) -> list[Block]:
    """Return the fenced code blocks of a Markdown page.

    Returns:
        list[Block]: Blocks in page order.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    found: list[Block] = []
    index = 0
    previous_end: int | None = None
    while index < len(lines):
        match = FENCE.match(lines[index])
        if not match:
            index += 1
            continue
        indent = len(match["indent"])
        start = index
        body: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != "```":
            body.append(lines[index][indent:])
            index += 1
        marker_match = MARKER.match(lines[start - 1]) if start else None
        between = lines[previous_end + 1 : start] if previous_end is not None else []
        follows_python = (
            bool(found)
            and found[-1].lang == "python"
            and all(not line.strip() for line in between)
        )
        found.append(
            Block(
                match["lang"],
                "\n".join(body) + "\n",
                start + 1,
                marker_match["marker"] if marker_match else None,
                follows_python,
            )
        )
        previous_end = index
        index += 1
    return found


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())


def _run_cli(command: str) -> tuple[int, str]:
    output = io.StringIO()
    # argparse wraps help text to the terminal width.
    os.environ["COLUMNS"] = "80"
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            status = main(shlex.split(command)[1:])
        except SystemExit as exit_:
            status = exit_.code if isinstance(exit_.code, int) else 0
    return status, output.getvalue()


def _check_console(block: Block, where: str) -> None:
    status = 0
    commands: list[tuple[str, list[str]]] = []
    for line in block.code.splitlines():
        if line.startswith("$ "):
            commands.append((line[2:], []))
        elif commands:
            commands[-1][1].append(line)
        elif line.strip():
            pytest.fail(f"{where}: output before the first command")
    for command, expected in commands:
        if command == "echo $?":
            output = f"{status}\n"
        elif command.startswith("dpm-xbrl"):
            status, output = _run_cli(command)
        else:
            pytest.fail(f"{where}: only dpm-xbrl commands run in console blocks")
        assert _normalize(output) == _normalize("\n".join(expected)), (
            f"{where}: output of {command!r} differs"
        )


@pytest.fixture
def samples_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for sample in SAMPLES.iterdir():
        shutil.copy(sample, tmp_path / sample.name)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("path", PAGES, ids=lambda path: str(path.relative_to(ROOT)))
@pytest.mark.usefixtures("samples_directory")
def test_page_examples(path: Path) -> None:
    namespace: dict[str, object] = {"__name__": "__docs__"}
    last_output: str | None = None
    for block in blocks(path):
        where = f"{path.relative_to(ROOT)}:{block.line}"
        if block.marker == "skip":
            last_output = None
            continue
        if block.lang == "python":
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    exec(compile(block.code, where, "exec"), namespace)  # ruff: ignore[exec-builtin]
            except ModuleNotFoundError as error:
                if error.name in OPTIONAL_MODULES:
                    pytest.skip(f"{error.name} is not installed")
                raise
            last_output = output.getvalue()
        elif block.lang == "text" and block.follows_python:
            assert last_output is not None
            assert _normalize(last_output) == _normalize(block.code), (
                f"{where}: printed output differs"
            )
            last_output = None
        elif block.lang == "console":
            _check_console(block, where)


MODULES = [
    "dpmxbrl",
    "dpmxbrl.model",
    "dpmxbrl.reader",
    "dpmxbrl.csv_reader",
    "dpmxbrl.xml_reader",
    "dpmxbrl.writer",
    "dpmxbrl.filing",
    "dpmxbrl.frames",
    "dpmxbrl.cli",
]


@pytest.mark.parametrize("name", MODULES)
@pytest.mark.usefixtures("samples_directory")
def test_docstring_examples(name: str) -> None:
    if name == "dpmxbrl.frames":
        pytest.importorskip("polars")
    module = importlib.import_module(name)
    finder = doctest.DocTestFinder(exclude_empty=True)
    runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
    for test in finder.find(module):
        runner.run(test)
    result = runner.summarize(verbose=False)
    assert result.failed == 0


def test_samples_are_current() -> None:
    for name, data in samples().items():
        assert (SAMPLES / name).read_bytes() == data, (
            f"docs/samples/{name} is stale: run uv run python -m tests.docs_samples"
        )


def test_every_page_is_in_the_navigation() -> None:
    config = (ROOT / "zensical.toml").read_text(encoding="utf-8")
    for page in (ROOT / "docs").rglob("*.md"):
        if ".snippets" in page.parts:
            continue
        relative = page.relative_to(ROOT / "docs").as_posix()
        assert f'"{relative}"' in config, f"{relative} is not in the zensical.toml nav"
