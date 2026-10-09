import _sandbox
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pache_lanes import local

class RegressionTests(unittest.TestCase):
    def test_failed_herdr_start_retains_workspace_for_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local,'LANES_DIR',Path(tmp)/'state'), patch.object(local,'which',return_value='/fixture/herdr'), patch.object(local,'auth_preflight'):
            created={'result':{'workspace':{'workspace_id':'workspace:fixture'},'root_pane':{'pane_id':'pane:fixture'}}}
            with patch.object(local,'run_json',side_effect=[created,RuntimeError('start failed')]), patch.object(local,'run',return_value=subprocess.CompletedProcess([],1,'','close failed')), self.assertRaises(SystemExit):
                local.create_lane(local.build_parser().parse_args(['create','fixture','--repo',tmp,'--prompt','fixture','--backend','herdr']))
            meta=local.read_meta('fixture')
            self.assertEqual(meta['workspace_id'],'workspace:fixture')
            self.assertFalse(meta['cleanup_ok'])

    def test_herdr_transport_failure_unknown_not_stopped(self):
        with patch.object(local,'run',return_value=subprocess.CompletedProcess([],1,'','unreachable')):
            self.assertEqual(local.herdr_agent_status({'name':'fixture'})['agent_status'],'unknown')

    def test_backend_missing_leaves_no_incomplete_lane(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local,'LANES_DIR',Path(tmp)/'state'), patch.object(local,'which',return_value=None), patch.object(local,'auth_preflight'), self.assertRaises(SystemExit):
            local.create_lane(local.build_parser().parse_args(['create','fixture','--repo',tmp,'--prompt','fixture','--backend','tmux']))
            self.fail('must refuse missing backend')
        # Directory must not have been allocated before backend prerequisite checks.
        with tempfile.TemporaryDirectory() as tmp, patch.object(local,'LANES_DIR',Path(tmp)/'state'), patch.object(local,'which',return_value=None), patch.object(local,'auth_preflight'):
            with self.assertRaises(SystemExit):
                local.create_lane(local.build_parser().parse_args(['create','fixture','--repo',tmp,'--prompt','fixture','--backend','tmux']))
            self.assertFalse((Path(tmp)/'state/fixture').exists())

    def test_stored_herdr_session_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local,'LANES_DIR',Path(tmp)):
            local.write_meta('fixture',{'name':'fixture','backend':'herdr','herdr_session':'some-other-session'})
            with self.assertRaises(SystemExit): local.read_meta('fixture')
