"""Convert an XBRL-XML instance to an xBRL-CSV package with eba-xbridge.

Usage: xbridge_convert.py INSTANCE OUTPUT_DIRECTORY
"""

import sys

from xbridge.api import convert_instance

print(convert_instance(sys.argv[1], sys.argv[2]))
