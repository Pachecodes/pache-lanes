import _sandbox
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

class RemoteTests(unittest.TestCase):
    def remote(self):
        from pache_lanes import remote
        return remote

    def test_remote_available(self):
        try:
            self.remote()
        except ImportError:
            self.fail('remote backend missing')

    def test_unconfigured_machine_rejected(self):
        r=self.remote()
        with patch.object(r,'config',return_value={}), self.assertRaises(SystemExit):
            r.machine_config('worker')

    def test_disabled_machine_rejected(self):
        r=self.remote()
        with patch.object(r,'config',return_value={'machines':{'worker':{'target':'localhost','enabled':False}}}), self.assertRaises(SystemExit):
            r.machine_config('worker')

    def test_ssh_option_target_rejected(self):
        r=self.remote()
        with patch.object(r,'config',return_value={'machines':{'worker':{'target':'-oProxyCommand=bad','enabled':True}}}), self.assertRaises(SystemExit):
            r.machine_config('worker')

    def test_dry_run_no_network(self):
        r=self.remote()
        with tempfile.TemporaryDirectory() as tmp, patch.object(r,'ROOT',Path(tmp)), patch.object(r,'config',return_value={'machines':{'worker':{'target':'localhost','enabled':True}}}), patch.object(r,'run',side_effect=AssertionError('network')), contextlib.redirect_stdout(io.StringIO()):
            r.main(['create','fixture','--machine','worker','--repo','/srv/project','--prompt','fixture','--dry-run'])
            self.assertEqual(json.loads((Path(tmp)/'fixture/status.json').read_text())['state'],'dry-run')

    def test_claude_checker_no_edit_permission(self):
        import argparse
        r=self.remote()
        cmd=r.one_shot_command(argparse.Namespace(name='fixture',role='checker',model=None,effort=None))
        self.assertIn('--permission-mode plan',cmd)
        self.assertNotIn('acceptEdits',cmd)

    def test_failed_close_keeps_evidence(self):
        import argparse, subprocess
        r=self.remote()
        with tempfile.TemporaryDirectory() as tmp, patch.object(r,'ROOT',Path(tmp)), patch.object(r,'pane_text',return_value='fixture'), patch.object(r,'remote_herdr',return_value=subprocess.CompletedProcess([],1,'','failure')):
            r.save('fixture',{'name':'fixture','machine':'worker','workspace_id':'workspace:fixture','run_log':str(Path(tmp)/'fixture/run.log'),'state':'working'})
            with self.assertRaises(SystemExit): r.stop(argparse.Namespace(name='fixture'))
            self.assertEqual(r.load('fixture')['state'],'working')
