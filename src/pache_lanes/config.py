"""User-owned configuration; no automatic network targets."""
import json
import os
from pathlib import Path

def config():
    path = Path(os.environ.get("PACHE_LANES_CONFIG", "~/.config/pache-lanes/config.json")).expanduser()
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    return data

def state_root():
    value = os.environ.get("PACHE_LANES_HOME") or os.environ.get("PACHE_LANES_STATE_DIR") or config().get("state_dir") or "~/.local/state/pache-lanes"
    path = Path(value).expanduser().resolve()
    if path == Path.home() or path == Path('/') or '.hermes' in path.parts:
        raise ValueError("state must be a dedicated directory outside Hermes")
    return path
