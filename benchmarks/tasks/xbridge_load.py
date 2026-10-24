"""Load an XBRL-XML instance with eba-xbridge."""

import sys

from xbridge.api import load_instance

instance = load_instance(sys.argv[1])
print(len(instance.facts), "facts")
