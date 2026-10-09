"""Installed CLI + real private tmux; bounded noop only, no agents/network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from pache_lanes import tmux_private

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='.t-', dir=root) as tmp:
    state = Path(tmp)
    env = {**os.environ, 'PACHE_LANES_HOME': tmp,
           'PACHE_LANES_CONFIG': str(state/'absent.json'), 'PYTHONDONTWRITEBYTECODE': '1'}
    env.pop('PYTHONPATH', None)
    exe = Path(sys.executable).parent / 'pache-lane'
    def cli(*args, expected=0):
        cp = subprocess.run([str(exe), *args], env=env, text=True, capture_output=True)
        assert cp.returncode == expected, (args, cp.stdout, cp.stderr)
        print('PASS', *args, 'exit='+str(cp.returncode))
        return cp
    cli('tmux-init')
    record = json.loads((state/'tmux/owner.json').read_text())
    try:
        cli('create', 'finite', '--repo', tmp, '--agent', 'noop', '--backend', 'tmux', '--prompt', 'inert')
        for _ in range(100):
            meta = json.loads(cli('status', 'finite', '--json').stdout)
            if meta['state'] == 'done': break
            time.sleep(.02)
        assert meta['state'] == 'done'
        assert (state/'local/finite/exit_code').read_text().strip() == '0'
        cli('stop', 'finite')
        before = {p.name:p.read_bytes() for p in (state/'local/finite').iterdir()}
        socket = tmux_private.validate(state)
        hidden = socket.with_name('hidden.sock'); socket.rename(hidden)
        try:
            cli('remove', 'finite', expected=1)
            assert before == {p.name:p.read_bytes() for p in (state/'local/finite').iterdir()}
            cli('tmux-init', expected=1)
        finally:
            hidden.rename(socket)
        cli('remove', 'finite')
    finally:
        socket = tmux_private.validate(state)
        cp = tmux_private._call(socket, 'kill-server')
        assert cp.returncode == 0
        for _ in range(100):
            cp = subprocess.run(['ps', '-p', str(record['server_pid']), '-o', 'pid='], capture_output=True)
            if cp.returncode == 1: break
            time.sleep(.02)
        assert cp.returncode == 1
        print('PASS owned fixture server PID exited; cleanup safe')
print('Installed real tmux lifecycle passed; no agents/models/network.')
