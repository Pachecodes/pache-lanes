"""Exercise installed console entry points without workers or network."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='.fixture-smoke-',dir=root) as tmp:
    base=Path(tmp)
    env=os.environ.copy()
    env.update(PACHE_LANES_STATE_DIR=str(base/'state'),PACHE_LANES_CONFIG=str(base/'config.json'),TMPDIR=tmp,PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH',None)
    env.pop('PACHE_LANES_HOME',None)
    env['PATH']=str(Path(sys.executable).parent)+os.pathsep+env['PATH']
    (base/'config.json').write_text(json.dumps({'machines':{'worker':{'target':'localhost','enabled':True}}}))
    repo=base/'repo'; repo.mkdir()
    subprocess.run(['git','init',str(repo)],check=True,capture_output=True)
    def call(*argv,expected=0):
        result=subprocess.run(argv,env=env,cwd=repo,text=True,capture_output=True)
        assert result.returncode==expected,(argv,result.returncode,result.stdout,result.stderr)
        print('PASS', ' '.join(argv), 'exit='+str(result.returncode))
        return result.stdout
    for exe in ('pache-lane','pache-remote-lane'):
        call(exe,'--help'); call(exe,'--version')
    call('pache-lane','create','--help')
    call('pache-lane','remote','create','--help')
    call('pache-lane','create','fixture','--repo',str(repo),'--prompt','Fixture only','--dry-run')
    assert json.loads(call('pache-lane','list','--json'))[0]['state']=='dry-run'
    assert json.loads(call('pache-lane','status','fixture','--json'))['state']=='dry-run'
    call('pache-lane','read','fixture','--log')
    report=json.loads(call('pache-lane','verify','fixture','--cmd','true'))
    assert report['gate_result']=='pass'
    report=json.loads(call('pache-lane','verify','fixture','--cmd','false',expected=1))
    assert report['gate_result']=='fail'
    call('pache-lane','stop','fixture'); call('pache-lane','remove','fixture')
    call('pache-remote-lane','create','fixture','--machine','worker','--repo','/fixture','--prompt','Fixture only','--dry-run')
    assert json.loads(call('pache-lane','remote','status','fixture'))['state']=='dry-run'
    call('pache-remote-lane','list'); call('pache-remote-lane','read','fixture')
    call('pache-remote-lane','stop','fixture'); call('pache-remote-lane','remove','fixture')
    call('pache-lane','create','..','--repo',str(repo),'--prompt','fixture','--dry-run',expected=1)
print('Installed CLI smoke passed; no worker or network launched.')
