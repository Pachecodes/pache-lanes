import _sandbox
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pache_lanes import local, remote
from pache_lanes.config import state_root

class ProtocolTests(unittest.TestCase):
    def test_private_tmux_socket(self):
        cp=subprocess.CompletedProcess([],0,'','')
        with patch.object(local, 'tmux_socket_path', return_value='/fixture/private.sock'), patch('subprocess.run',return_value=cp) as execute:
            local.run(['tmux','has-session','-t','pache-fixture'])
        self.assertEqual(execute.call_args.args[0][:3],['tmux','-S','/fixture/private.sock'])

    def test_tmux_launch_records_exit_and_is_finite(self):
        cmd=local.build_tmux_launch('/repo with spaces','false','/state/exit_code')
        self.assertIn('rc=$?',cmd)
        self.assertIn('exit "$rc"',cmd)
        self.assertNotIn('exec $SHELL',cmd)

    def test_tmux_state_true_exit(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local,'tmux_lane_guard'), patch.object(local,'tmux_has_session',return_value=False):
            file=Path(tmp)/'exit'; file.write_text('1')
            self.assertEqual(local.infer_state({'backend':'tmux','exit_file':str(file)}),'failed')
            file.write_text('0')
            self.assertEqual(local.infer_state({'backend':'tmux','exit_file':str(file)}),'done')

    def test_invalid_json_fails(self):
        with patch.object(local,'run',return_value=subprocess.CompletedProcess([],0,'not-json','')), self.assertRaises(RuntimeError):
            local.run_json(['herdr','fixture'])

    def test_codex_checker_read_only(self):
        args=local.build_parser().parse_args(['create','fixture','--agent','codex','--role','checker'])
        command=local.build_agent_command(args,Path('/fixture'))
        self.assertIn('--sandbox read-only',command)
        self.assertNotIn('workspace-write',command)

    def test_raw_args_always_rejected(self):
        with patch.dict('os.environ',{'PACHE_LANE_ALLOW_RAW_ARGS':'1'}), self.assertRaises(ValueError):
            local.validate_raw_agent_args(['--dangerously-skip-permissions'])

    def test_hermes_state_rejected(self):
        with patch.dict('os.environ',{'PACHE_LANES_STATE_DIR':str(Path.home()/'.hermes/lanes')}), self.assertRaises(ValueError): state_root()

    def test_symlink_lane_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local,'LANES_DIR',Path(tmp)):
            (Path(tmp)/'fixture').symlink_to(Path(tmp),target_is_directory=True)
            with self.assertRaises(SystemExit): local.lane_dir('fixture')

    def test_local_herdr_fixture_create(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(local,'LANES_DIR',Path(tmp)/'state'), patch.object(local,'auth_preflight'), patch.object(local,'which',return_value='/fixture/herdr'), contextlib.redirect_stdout(io.StringIO()):
            made={'result':{'workspace':{'workspace_id':'workspace:fixture'},'root_pane':{'pane_id':'pane:fixture'}}}
            with patch.object(local,'run_json',side_effect=[made,{'result':{}},{'result':{}}]) as calls:
                local.create_lane(local.build_parser().parse_args(['create','fixture','--repo',tmp,'--backend','herdr','--role','checker','--prompt','fixture']))
            start=calls.call_args_list[1].args[0]
            self.assertEqual(start[-2:],['--permission-mode','plan'])
            self.assertEqual(local.read_meta('fixture')['workspace_id'],'workspace:fixture')

    def test_remote_create_protocol_fixture(self):
        cfg={'machines':{'worker':{'enabled':True,'target':'localhost'}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote,'ROOT',Path(tmp)), patch.object(remote,'config',return_value=cfg), contextlib.redirect_stdout(io.StringIO()):
            created=json.dumps({'result':{'workspace':{'workspace_id':'workspace:fixture'},'root_pane':{'pane_id':'pane:fixture'}}})
            def execute(argv):
                return subprocess.CompletedProcess(argv,0,created if 'workspace create' in ' '.join(argv) else '{}','')
            with patch.object(remote,'run',side_effect=execute) as calls:
                remote.main(['create','fixture','--machine','worker','--repo','/repo with spaces','--role','checker','--prompt','fixture'])
            self.assertEqual(remote.load('fixture')['state'],'working')
            self.assertTrue(all(c.args[0][:3]==['ssh','-o','BatchMode=yes'] for c in calls.call_args_list))
            self.assertIn('--permission-mode plan',' '.join(calls.call_args_list[-1].args[0]))

    def test_remote_sentinal_needs_standalone_line(self):
        meta={'state':'working'}
        with patch.object(remote,'pane_text',return_value='echo __PACHE_EXIT__=0'):
            self.assertEqual(remote.pane_state(meta),'working')
        with patch.object(remote,'pane_text',return_value='__PACHE_EXIT__=1\n'):
            self.assertEqual(remote.pane_state(meta),'failed')

    def test_remote_unknown_is_not_success(self):
        with patch.object(remote,'pane_text',return_value=''):
            self.assertEqual(remote.pane_state({'state':'working'}),'unknown')

    def test_remove_never_closes_an_active_workspace(self):
        with patch.object(local,'read_meta',return_value={'backend':'herdr','state':'working'}), patch.object(local,'run',side_effect=AssertionError('close')), self.assertRaises(SystemExit):
            local.remove_lane(local.build_parser().parse_args(['remove','fixture']))
