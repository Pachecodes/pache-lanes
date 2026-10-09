import _sandbox
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pache_lanes import local

class SafetyTests(unittest.TestCase):
    def test_traversal_rejected(self):
        for name in ('.', '..', 'a..b', 'a/b', 'x\n'):
            with self.subTest(name=name), self.assertRaises(SystemExit):
                local.require_name(name)

    def test_dry_run_never_calls_external_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=local.build_parser().parse_args(['create','fixture','--repo',tmp,'--prompt','fixture','--dry-run'])
            with patch.object(local,'LANES_DIR',Path(tmp)/'state'), patch.object(local,'run',side_effect=AssertionError('external call')), patch.object(local,'which',side_effect=AssertionError('external discovery')), contextlib.redirect_stdout(io.StringIO()):
                local.create_lane(args)
            self.assertTrue((Path(tmp)/'state/fixture/status.json').is_file())

    def test_checker_claude_plan_mode(self):
        args=local.build_parser().parse_args(['create','fixture','--role','checker'])
        command=local.build_agent_command(args,Path('/fixture'))
        self.assertIn('--permission-mode plan',command)
        self.assertNotIn('Read,Edit,Write,Bash',command)

    def test_copilot_no_allow_all(self):
        self.assertNotIn('--allow-all-tools',local.copilot_agent_args(model=None,max_ai_credits=50,interactive=False))

    def test_no_replace(self):
        with self.assertRaises(SystemExit):
            local.build_parser().parse_args(['create','fixture','--replace'])

    def test_verify_fail_exits_nonzero(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'state'; state.mkdir()
            with patch.object(local,'LANES_DIR',Path(tmp)), patch.object(local,'read_meta',return_value={'repo':tmp}), patch.object(local,'shell',return_value=subprocess.CompletedProcess([],1,'','failed')), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                local.verify_lane(local.build_parser().parse_args(['verify','state']))

if __name__ == '__main__': unittest.main()
