"""Imported first by every test: point the scripts at a temporary data dir and the
fixture map, BEFORE scripts/mapconfig.py is imported (it reads these at import).
Never let a test write to the real data/ directory."""
import datetime as dt
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="ls-test-")
TODAY = dt.datetime.now(dt.timezone.utc).date()
YYMM = TODAY.strftime("%y%m")


def pid(n):
    return f"{YYMM}.{n:05d}"


NOTES = os.path.join(TMP, "notes.toml")
with open(NOTES, "w") as f:
    f.write(f'exclude = [{{ id = "{pid(3)}", why = "hand-excluded" }}]\n'
            f'include = [{{ id = "{pid(9)}", why = "the query misses it", tag = "charts" }}]\n')
os.environ.update(LS_MAP=os.path.join(HERE, "fixtures", "map.toml"), LS_NOTES=NOTES, LS_DATA=TMP,
                  LS_CACHE=os.path.join(TMP, "cache"))
os.environ.pop("LS_POOL", None)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import mapconfig  # noqa: E402

assert os.path.realpath(mapconfig.DATA) == os.path.realpath(TMP), "tests must not touch the real data/ directory"
assert mapconfig.CACHE.startswith(TMP), "tests must not touch the real scripts/.cache"

# No test may reach the network: any real HTTP call fails loudly instead of quietly
# talking to arXiv or Semantic Scholar.
import urllib.request  # noqa: E402


def _no_network(*a, **k):
    raise AssertionError("a test tried to use the network")


urllib.request.urlopen = _no_network
