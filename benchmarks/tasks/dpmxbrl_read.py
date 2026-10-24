"""Read a report with dpm-xbrl: read_report, or the frames reader."""

import argparse

from dpmxbrl import Limits, read_report

parser = argparse.ArgumentParser()
parser.add_argument("path")
parser.add_argument("--taxonomy-package", action="append", default=[])
parser.add_argument("--frames", action="store_true")
parser.add_argument("--large", action="store_true", help="raise the limits")
arguments = parser.parse_args()
limits = (
    Limits(max_file_size=4 << 30, max_total_size=8 << 30, max_facts=50_000_000)
    if arguments.large
    else Limits()
)
if arguments.frames:
    from dpmxbrl.frames import read_xbrl_csv_frames

    frames = read_xbrl_csv_frames(arguments.path, limits=limits)
    print(frames.fact_count, "facts", len(frames.report.filing), "findings")
else:
    report = read_report(
        arguments.path, taxonomy_packages=arguments.taxonomy_package, limits=limits
    )
    print(len(report.facts), "facts", len(report.filing), "findings")
