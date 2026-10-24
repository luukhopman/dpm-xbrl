"""Load an XBRL-XML instance with brel-xbrl."""

import sys

from brel import Filing

filing = Filing.open(sys.argv[1])
print(len(filing.get_all_facts()), "facts")
