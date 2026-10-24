"""Count the reports dpm-xbrl reads without error. Usage: FILE [FILE ...]."""

import sys

from dpmxbrl import ReportError, read_report

read = 0
for path in sys.argv[1:]:
    try:
        read_report(path)
    except ReportError as error:
        print(f"{path}: {error}", file=sys.stderr)
    else:
        read += 1
print(f"{read}/{len(sys.argv) - 1}")
