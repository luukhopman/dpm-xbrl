"""Load a report with Arelle's command line, offline, with the EBA packages.

Usage: arelle_load.py REPORT PACKAGE.zip [PACKAGE.zip ...]

Arelle reads xBRL-CSV report packages as well as XML instances this way.
"""

import sys

from arelle.CntlrCmdLine import parseAndRun

controller = parseAndRun(
    [
        "--file",
        sys.argv[1],
        "--packages",
        "|".join(sys.argv[2:]),
        "--internetConnectivity",
        "offline",
        "--keepOpen",
        "--logFile",
        "logToBuffer",
    ]
)
model = controller.modelManager.modelXbrl
facts = len(model.factsInInstance) if model else 0
print(facts, "facts")
if not facts:
    raise SystemExit("Arelle loaded no facts")
