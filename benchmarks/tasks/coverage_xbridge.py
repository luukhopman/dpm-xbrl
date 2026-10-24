"""Count the reports eba-xbridge loads (XML) and validates. Usage: FILE [FILE ...]."""

import sys
import warnings

from xbridge.api import load_instance
from xbridge.validation import validate

warnings.simplefilter("ignore")
xml = [path for path in sys.argv[1:] if path.endswith((".xbrl", ".xml"))]
loaded = validated = 0
for path in xml:
    try:
        load_instance(path)
    except Exception as error:
        print(f"{path}: load: {type(error).__name__}: {error}", file=sys.stderr)
    else:
        loaded += 1
for path in sys.argv[1:]:
    try:
        validate(path, eba=True)
    except Exception as error:
        print(f"{path}: validate: {type(error).__name__}: {error}", file=sys.stderr)
    else:
        validated += 1
print(f"loaded {loaded}/{len(xml)} XML, validated {validated}/{len(sys.argv) - 1}")
