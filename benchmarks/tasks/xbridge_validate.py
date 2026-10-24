"""Run eba-xbridge's validation with the EBA checks on a report."""

import sys

from xbridge.validation import validate

result = validate(sys.argv[1], eba=True)
codes = {
    code for section in result.values() for kind in section.values() for code in kind
}
print(len(codes), "distinct finding codes")
