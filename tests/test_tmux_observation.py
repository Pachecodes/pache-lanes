"""Lifecycle regressions at the subprocess boundary; never contact tmux."""
import _sandbox
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pache_lanes import local


class TmuxObservationTests(unittest.TestCase):
    def setUp(self):
        # These tests isolate observation diagnostics; private transport has real E2E coverage.
        transport = patch.object(local, 'tmux_socket_path', return_value='/fixture/private.sock')
        guard = patch.object(local, "tmux_lane_guard")
        guard.start()
        self.addCleanup(guard.stop)
        transport.start()
        self.addCleanup(transport.stop)

    session = 'pache-fixture'
    transport_errors = (
        (1, 'error connecting to /private/tmp/tmux-501/pache-lanes (Connection refused)\n'),
        (1, 'no server running on /private/tmp/tmux-501/pache-lanes\n'),
        (1, 'error connecting to /private/tmp/tmux-501/pache-lanes (No such file or directory)\n'),
        (1, 'error connecting to /private/tmp/tmux-501/pache-lanes (Permission denied)\n'),
        (1, 'server exited unexpectedly\n'),
        (1, ''),
        (2, "can't find session: pache-fixture\n"),
        (1, "can't find session: different-worker\n"),
    )

    def fixture(self, root):
        local.write_meta('fixture', {'name': 'fixture', 'backend': 'tmux',
                                    'session': self.session, 'state': 'working'})
        directory = root / 'fixture'
        (directory / 'run.jsonl').write_text('synthetic worker evidence\n')
        (directory / 'events.jsonl').write_text('synthetic lifecycle evidence\n')
        return directory

    def snapshot(self, directory):
        return {p.name: p.read_bytes() for p in directory.iterdir()}

    def test_stop_and_remove_refuse_transport_failure_without_changing_evidence(self):
        for command in ('stop', 'remove'):
            for code, error in self.transport_errors:
                with self.subTest(command=command, error=error), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with patch.object(local, 'LANES_DIR', root), patch.object(local, 'which', return_value='/fixture/tmux'), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        directory = self.fixture(root)
                        before = self.snapshot(directory)
                        with patch('subprocess.run', return_value=subprocess.CompletedProcess(['tmux'], code, '', error)) as execute:
                            with self.assertRaises(SystemExit):
                                args = local.build_parser().parse_args([command, 'fixture'])
                                args.func(args)
                        self.assertEqual(self.snapshot(directory), before)
                        self.assertEqual(execute.call_count, 1)

    def test_missing_executable_and_os_errors_preserve_evidence(self):
        for command in ('stop', 'remove'):
            for binary, exception in ((None, None), ('/fixture/tmux', FileNotFoundError('tmux vanished')), ('/fixture/tmux', PermissionError('permission denied'))):
                with self.subTest(command=command, binary=binary, exception=exception), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with patch.object(local, 'LANES_DIR', root), patch.object(local, 'which', return_value=binary), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        directory = self.fixture(root)
                        before = self.snapshot(directory)
                        with patch('subprocess.run', side_effect=exception or AssertionError('must not execute')):
                            with self.assertRaises(SystemExit):
                                args = local.build_parser().parse_args([command, 'fixture'])
                                args.func(args)
                        self.assertEqual(self.snapshot(directory), before)

    def test_genuine_absence_allows_stop_then_remove(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local, 'LANES_DIR', Path(tmp)), patch.object(local, 'which', return_value='/fixture/tmux'), contextlib.redirect_stdout(io.StringIO()):
            directory = self.fixture(Path(tmp))
            absent = subprocess.CompletedProcess(['tmux'], 1, '', "can't find session: pache-fixture\n")
            with patch('subprocess.run', return_value=absent) as execute:
                local.stop_lane(local.build_parser().parse_args(['stop', 'fixture']))
                self.assertEqual(local.read_meta('fixture')['state'], 'stopped')
                self.assertTrue((directory / 'run.jsonl').exists())
                local.remove_lane(local.build_parser().parse_args(['remove', 'fixture']))
                self.assertFalse(directory.exists())
                self.assertEqual(execute.call_count, 2)

    def test_successful_stop_verifies_absence_before_marking_stopped(self):
        for final_code, final_error in ((1, "can't find session: pache-fixture\n"), (0, ''), (1, 'server exited unexpectedly\n')):
            with self.subTest(final_error=final_error, final_code=final_code), tempfile.TemporaryDirectory() as tmp, patch.object(local, 'LANES_DIR', Path(tmp)), patch.object(local, 'which', return_value='/fixture/tmux'), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                directory = self.fixture(Path(tmp))
                before = self.snapshot(directory)
                results = [subprocess.CompletedProcess([], 0, '', ''), subprocess.CompletedProcess([], 0, '', ''), subprocess.CompletedProcess([], final_code, '', final_error)]
                with patch('subprocess.run', side_effect=results) as execute:
                    args = local.build_parser().parse_args(['stop', 'fixture'])
                    if final_code == 1 and final_error.startswith("can't find session:"):
                        args.func(args)
                        self.assertEqual(local.read_meta('fixture')['state'], 'stopped')
                    else:
                        with self.assertRaises(SystemExit): args.func(args)
                        self.assertEqual(self.snapshot(directory), before)
                    self.assertEqual(execute.call_count, 3)

    def test_status_transport_failure_does_not_record_false_stopped(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local, 'LANES_DIR', Path(tmp)), patch.object(local, 'which', return_value='/fixture/tmux'), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            directory = self.fixture(Path(tmp))
            before = self.snapshot(directory)
            with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'server exited unexpectedly\n')):
                with self.assertRaises(SystemExit):
                    local.status_lane(local.build_parser().parse_args(['status', 'fixture', '--json']))
            self.assertEqual(self.snapshot(directory), before)

    def test_missing_session_identity_refuses_stop_remove_and_status(self):
        for command in ('stop', 'remove', 'status'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp, patch.object(local, 'LANES_DIR', Path(tmp)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                directory = self.fixture(Path(tmp))
                meta = local.read_meta('fixture')
                del meta['session']
                local.write_meta('fixture', meta)
                before = self.snapshot(directory)
                with patch('subprocess.run', side_effect=AssertionError('missing identity')):
                    with self.assertRaises(SystemExit):
                        args = local.build_parser().parse_args([command, 'fixture'])
                        args.func(args)
                self.assertEqual(self.snapshot(directory), before)

    def test_failed_kill_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local, 'LANES_DIR', Path(tmp)), patch.object(local, 'which', return_value='/fixture/tmux'), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            directory = self.fixture(Path(tmp))
            before = self.snapshot(directory)
            with patch('subprocess.run', side_effect=[subprocess.CompletedProcess([], 0, '', ''), subprocess.CompletedProcess([], 1, '', 'server exited unexpectedly\n')]):
                with self.assertRaises(SystemExit):
                    local.stop_lane(local.build_parser().parse_args(['stop', 'fixture']))
            self.assertEqual(self.snapshot(directory), before)

    def test_confirmed_absence_uses_exit_sentinel_for_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local, 'which', return_value='/fixture/tmux'), patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', "can't find session: pache-fixture\n")):
            sentinel = Path(tmp) / 'exit_code'
            for code, state in (('0', 'done'), ('1', 'failed')):
                sentinel.write_text(code)
                self.assertEqual(local.infer_state({'backend': 'tmux', 'session': self.session, 'exit_file': str(sentinel)}), state)

    def test_prune_unknown_worker_is_not_killed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local, 'LANES_DIR', Path(tmp)), patch.object(local, 'which', return_value='/fixture/tmux'), contextlib.redirect_stderr(io.StringIO()):
            inventory = subprocess.CompletedProcess([], 0, 'pache-unknown\tsh\t0\n', '')
            with patch('subprocess.run', return_value=inventory) as execute:
                with self.assertRaises(SystemExit):
                    local.prune_tmux(local.build_parser().parse_args(['prune', '--apply']))
                self.assertEqual(execute.call_count, 1)

    def test_prune_missing_binary_refuses_success(self):
        with patch.object(local, 'which', return_value=None), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                local.prune_tmux(local.build_parser().parse_args(['prune']))

    def test_prune_refuses_transport_and_kill_errors(self):
        cases = ([subprocess.CompletedProcess([], 1, '', 'server exited unexpectedly\n')],
                 [subprocess.CompletedProcess([], 0, 'pache-fixture\tzsh\t0\n', ''), subprocess.CompletedProcess([], 1, '', 'server exited unexpectedly\n')])
        for results in cases:
            with self.subTest(results=results), patch.object(local, 'read_meta', return_value={'backend': 'tmux', 'session': self.session}), patch.object(local, 'which', return_value='/fixture/tmux'), patch('subprocess.run', side_effect=results), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    local.prune_tmux(local.build_parser().parse_args(['prune', '--apply']))
