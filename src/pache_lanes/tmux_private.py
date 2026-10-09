"""Explicit, non-adopting private tmux transport. Failure retains ownership evidence."""
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess


def _directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('tmux directory must be owner-controlled mode 0700 (no symlink)')


def _call(socket, *args):
    return subprocess.run(['tmux', '-S', str(socket), *args], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env={**os.environ, 'LC_ALL': 'C'})


def socket_path(root):
    return root / 'tmux' / 'server.sock'


def validate(root):
    _directory(root)
    directory = root / 'tmux'
    _directory(directory)
    record_path = directory / 'owner.json'
    info = record_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('unsafe tmux ownership record')
    record = json.loads(record_path.read_text())
    socket = socket_path(root)
    info = socket.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
            or [info.st_dev, info.st_ino] != record['socket_identity']):
        raise RuntimeError('tmux socket identity differs; restore original transport')
    for option, expected in (('@pache_owner', record['nonce']), ('exit-empty', 'off')):
        cp = _call(socket, 'show-options', '-s', '-v', option)
        if cp.returncode or cp.stdout.strip() != expected:
            raise RuntimeError('tmux server ownership/configuration unavailable or changed')
    return socket


def initialize(root):
    # Exclusive mkdir is the reservation. Never unlink/retry/adopt an old socket.
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _directory(root)
    # Legacy/unbound workers must be resolved before provisioning a new transport.
    for metadata in (root / 'local').glob('*/status.json'):
        if json.loads(metadata.read_text()).get('backend') == 'tmux':
            raise RuntimeError('existing tmux lane evidence; initialization cannot adopt previous workers')
    directory = root / 'tmux'
    directory.mkdir(mode=0o700, exist_ok=False)
    socket = socket_path(root)
    if len(os.fsencode(socket)) > 100:
        raise RuntimeError('private tmux socket path too long; use a shorter dedicated state root')
    nonce = secrets.token_hex(32)
    # Empty-server lifetime is explicit. Bootstrap has no models/network and is bounded.
    cp = _call(socket, '-f', '/dev/null', 'new-session', '-d', '-s', 'bootstrap',
               '/bin/sleep 60', ';', 'set-option', '-s', 'exit-empty', 'off',
               ';', 'set-option', '-s', '@pache_owner', nonce)
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip() or 'tmux initialization failed; reservation retained')
    info = socket.lstat()
    pid = _call(socket, 'display-message', '-p', '#{pid}')
    if pid.returncode or not pid.stdout.strip().isdigit():
        raise RuntimeError('server process identity unavailable; reservation retained')
    record = {'nonce': nonce, 'socket_identity': [info.st_dev, info.st_ino],
              'server_pid': int(pid.stdout.strip())}
    with (directory / 'owner.json').open('x') as handle:
        os.chmod(directory / 'owner.json', 0o600)
        json.dump(record, handle)
    validate(root)
    cp = _call(socket, 'kill-session', '-t', '=bootstrap')
    if cp.returncode:
        raise RuntimeError('bootstrap teardown failed; evidence retained')
    validate(root)
    return socket
