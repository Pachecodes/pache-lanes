"""Real inert lifecycle, dedicated disposable transport only."""
import _sandbox
import contextlib
import io
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from pache_lanes import local


@unittest.skipUnless(shutil.which('tmux'), 'tmux not installed')
class PrivateLifecycleTests(unittest.TestCase):
    def test_cold_init_finite_create_last_stop_remove_and_transport_loss(self):
        with tempfile.TemporaryDirectory(prefix='.t-', dir=Path(__file__).resolve().parents[1]) as tmp, patch.object(local, 'LANES_DIR', Path(tmp)/'local'), contextlib.redirect_stdout(io.StringIO()):
            def cli(*argv):
                args = local.build_parser().parse_args(list(argv))
                args.func(args)
            with self.assertRaises(SystemExit):
                cli('create', 'uninitialized', '--repo', tmp, '--backend', 'tmux', '--agent', 'noop', '--prompt', 'inert')
            self.assertFalse((Path(tmp)/'local/uninitialized').exists())
            cli('tmux-init')
            record = __import__('json').loads((Path(tmp)/'tmux/owner.json').read_text())
            try:
                self.assertIsInstance(record.get('server_pid'), int)
                with self.assertRaises(SystemExit): cli('tmux-init')
                # An unknown colliding session must not be adopted, replaced or given metadata.
                self.assertEqual(local.run(['tmux', 'new-session', '-d', '-s', 'pache-collision', '/bin/sleep 60']).returncode, 0)
                try:
                    with self.assertRaises(SystemExit):
                        cli('create', 'collision', '--repo', tmp, '--backend', 'tmux', '--agent', 'noop', '--prompt', 'inert')
                    self.assertFalse((Path(tmp)/'local/collision').exists())
                    self.assertFalse(local.tmux_has_session('pache-not-present'))
                    self.assertTrue(local.tmux_has_session('pache-collision'))
                finally:
                    self.assertEqual(local.run(['tmux', 'kill-session', '-t', '=pache-collision']).returncode, 0)
                cli('create', 'finite', '--repo', tmp, '--backend', 'tmux', '--agent', 'noop', '--prompt', 'inert')
                for _ in range(100):
                    if local.infer_state(local.read_meta('finite')) == 'done': break
                    time.sleep(.02)
                self.assertEqual(local.infer_state(local.read_meta('finite')), 'done')
                cli('stop', 'finite')
                cli('remove', 'finite')
                with patch.object(local, 'build_agent_command', return_value='sleep 60'):
                    cli('create', 'inert', '--repo', tmp, '--backend', 'tmux', '--agent', 'noop', '--prompt', 'inert')
                meta = local.read_meta('inert')
                unbound = dict(meta); unbound.pop('tmux_owner', None)
                with self.assertRaises(SystemExit): local.infer_state(unbound)
                self.assertTrue(local.tmux_has_session('pache-inert'))
                Path(tmp).chmod(0o755)
                try:
                    with self.assertRaises(SystemExit): cli('stop', 'inert')
                finally:
                    Path(tmp).chmod(0o700)
                self.assertTrue(local.tmux_has_session('pache-inert'))
                cli('stop', 'inert')
                self.assertFalse(local.tmux_has_session('pache-inert'))
                directory = Path(tmp)/'local/inert'
                before = {p.name:p.read_bytes() for p in directory.iterdir()}
                socket = Path(local.tmux_socket_path())
                hidden = socket.with_name('hidden.sock')
                socket.rename(hidden)
                try:
                    for verb in ('stop', 'remove', 'status'):
                        with self.assertRaises(SystemExit): cli(verb, 'inert')
                        self.assertEqual(before, {p.name:p.read_bytes() for p in directory.iterdir()})
                    with self.assertRaises(SystemExit): cli('tmux-init')
                    # A replacement path cannot turn unavailable into an adopted transport.
                    socket.write_text('not the recorded socket')
                    try:
                        with self.assertRaises(SystemExit): cli('remove', 'inert')
                        self.assertEqual(before, {p.name:p.read_bytes() for p in directory.iterdir()})
                    finally:
                        socket.unlink()
                finally:
                    hidden.rename(socket)
                cli('remove', 'inert')
            finally:
                # Only the recorded socket/nonce-verified fixture server.
                self.assertEqual(local.run(['tmux', 'kill-server']).returncode, 0)
                # Wait for the exact recorded fixture server to exit before directory cleanup.
                if 'server_pid' in record:
                    for _ in range(100):
                        cp = local.run(['ps', '-p', str(record['server_pid']), '-o', 'pid='])
                        if cp.returncode == 1: break
                        time.sleep(.02)
                    self.assertEqual(cp.returncode, 1)

    def test_home_alias_selects_disposable_state(self):
        with patch.dict(os.environ, {'PACHE_LANES_HOME': '/owned/disposable'}):
            from pache_lanes.config import state_root
            self.assertEqual(state_root(), Path('/owned/disposable'))

    def test_legacy_worker_evidence_blocks_first_initialization(self):
        with tempfile.TemporaryDirectory(prefix='.t-', dir=Path(__file__).resolve().parents[1]) as tmp, patch.object(local, 'LANES_DIR', Path(tmp)/'local'):
            local.write_meta('legacy', {'backend': 'tmux', 'session': 'pache-legacy'})
            with self.assertRaises(SystemExit):
                args = local.build_parser().parse_args(['tmux-init']); args.func(args)
            self.assertFalse((Path(tmp)/'tmux').exists())

    def test_existing_unknown_transport_is_never_adopted(self):
        with tempfile.TemporaryDirectory(prefix='.t-', dir=Path(__file__).resolve().parents[1]) as tmp, patch.object(local, 'LANES_DIR', Path(tmp)/'local'):
            private = Path(tmp)/'tmux'
            private.mkdir(mode=0o700)
            evidence = private/'unknown'; evidence.write_text('do not touch')
            with self.assertRaises(SystemExit):
                args = local.build_parser().parse_args(['tmux-init']); args.func(args)
            self.assertEqual(evidence.read_text(), 'do not touch')
