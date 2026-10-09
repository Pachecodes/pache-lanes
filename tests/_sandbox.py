"""Keep all fixture writes inside an ephemeral checkout-local sandbox."""
import atexit
import os
import tempfile
from pathlib import Path
sandbox = tempfile.TemporaryDirectory(prefix='.fixture-', dir=Path(__file__).resolve().parents[1])
atexit.register(sandbox.cleanup)
os.environ.pop('PACHE_LANES_HOME', None)
os.environ['PACHE_LANES_STATE_DIR'] = str(Path(sandbox.name)/'state')
os.environ['PACHE_LANES_CONFIG'] = str(Path(sandbox.name)/'absent.json')
tempfile.tempdir = sandbox.name
