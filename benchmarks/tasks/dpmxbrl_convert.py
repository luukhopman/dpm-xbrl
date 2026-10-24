"""Convert an XBRL-XML instance to an xBRL-CSV package with dpm-xbrl.

Usage: dpmxbrl_convert.py INSTANCE OUTPUT_ZIP TAXONOMY_PACKAGE...
"""

import sys

from dpmxbrl import read_report, write_xbrl_csv

report = read_report(sys.argv[1])
skipped = write_xbrl_csv(report, sys.argv[2], taxonomy_packages=sys.argv[3:])
print(len(report.facts), "facts", len(skipped), "left out")
