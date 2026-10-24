"""Load an XBRL-XML instance with py-xbrl, using a local HTTP cache directory.

Usage: pyxbrl_load.py INSTANCE CACHE_DIR
"""

import sys

from xbrl.cache import HttpCache
from xbrl.instance import XbrlParser

cache = HttpCache(sys.argv[2])
instance = XbrlParser(cache).parse_instance(sys.argv[1])
print(len(instance.facts), "facts")
