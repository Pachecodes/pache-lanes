"""POSIX SSH/Herdr finite remote lanes, derived from pache-remote-lane."""
from __future__ import annotations
import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from .config import state_root, config
VERSION = "0.1.0"
SESSION = config().get("remote_herdr_session", "pache-lanes")
ROOT = state_root() / "remote"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
OWNER_ONLY_WRITE = 'import base64,os,pathlib,sys; os.umask(0o077); p=pathlib.Path(sys.argv[1]).expanduser(); p.parent.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(p.parent,0o700); fd=os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600); os.write(fd,base64.b64decode(sys.argv[2])); os.close(fd)'

def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)

def require_name(name: str) -> None:
    """Accept only a flat lane identifier that is safe as a single path segment.

    The regex alone still admits ``.``, ``..`` and names like ``lane..escape``,
    every one of which is either a directory-traversal segment or contains one,
    so they are rejected explicitly. Ordinary dotted names (``lane.v2``) stay
    valid as long as they hold no consecutive dots.
    """
    if not SAFE_NAME.fullmatch(name) or name in {".", ".."} or ".." in name:
        die(
            "lane name may only contain letters, numbers, dot, underscore, and dash, "
            "and may not be '.', '..', or contain '..'"
        )

def lane_dir(name: str) -> Path:
    require_name(name)
    path = ROOT / name
    if path.is_symlink():
        die("lane directory may not be a symlink")
    return path

def load(name: str) -> dict[str, Any]:
    path = lane_dir(name) / "status.json"
    if not path.exists():
        die(f"lane not found: {name}")
    return json.loads(path.read_text())

def save(name: str, meta: dict[str, Any]) -> None:
    directory = lane_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    meta["updated_at"] = now()
    (directory / "status.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")

def event(name: str, kind: str, **data: Any) -> None:
    directory = lane_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "events.jsonl").open("a") as handle:
        handle.write(json.dumps({"ts": now(), "event": kind, **data}, sort_keys=True) + "\n")

def remote_json(machine: str, args: list[str]) -> dict[str, Any]:
    cp = remote_herdr(machine, args)
    if cp.returncode != 0:
        die(cp.stderr.strip() or cp.stdout.strip() or "remote Herdr command failed")
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        die(f"invalid remote Herdr JSON: {cp.stdout[:600]}")
    return {}

def prefix(meta: dict[str, Any] | None = None) -> list[str]:
    return ["--session", (meta or {}).get("herdr_session", SESSION)]

def pane_text(meta: dict[str, Any], lines: int = 100) -> str:
    cp = remote_herdr(meta["machine"], prefix(meta) + ["pane", "read", meta["pane_id"], "--lines", str(lines), "--format", "text"])
    if cp.returncode != 0:
        return ""
    try:
        result = json.loads(cp.stdout).get("result", {})
        return result.get("text", result.get("read", {}).get("text", cp.stdout))
    except json.JSONDecodeError:
        return cp.stdout

def upload_packet(machine: str, name: str, packet: str) -> None:
    payload = base64.b64encode(packet.encode()).decode()
    if machine_config(machine)["platform"] == "posix":
        remote_path = f"~/.local/share/herdr/pache-lanes/{name}/prompt.md"
        cp = remote_sh(machine, ["python3", "-c", OWNER_ONLY_WRITE, remote_path, payload])
        if cp.returncode != 0:
            die(cp.stderr.strip() or cp.stdout.strip() or "remote prompt upload failed")
        return

def remote_command(machine: str, cwd: str, command: str) -> subprocess.CompletedProcess[str]:
    if machine_config(machine)["platform"] == "posix":
        config = machine_config(machine)
        remote = f"cd -- {shlex.quote(cwd)} && {command}"
        return run(["ssh", "-o", "BatchMode=yes", config["target"], remote])

def verify(args: argparse.Namespace) -> None:
    meta = load(args.name)
    commands = ["git status --short --untracked-files=all", "git diff --name-only", "git diff --check"] + (args.cmd or [])
    checks = []
    for command in commands:
        cp = remote_command(meta["machine"], meta["repo"], command)
        checks.append({"cmd": command, "exit_code": cp.returncode, "stdout": cp.stdout[-12000:], "stderr": cp.stderr[-12000:]})
    output = {"lane": args.name, "machine": meta["machine"], "repo": meta["repo"], "verified_at": now(), "gate_result": "pass" if all(x["exit_code"] == 0 for x in checks) else "fail", "checks": checks}
    (lane_dir(args.name) / "verify.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))
    if output["gate_result"] != "pass":
        raise SystemExit(1)

def run(argv):
    return subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def machine_config(machine):
    entry = config().get("machines", {}).get(machine)
    if not isinstance(entry, dict) or entry.get("enabled") is not True:
        die("remote target is not explicitly enabled in configuration")
    target = entry.get("target", "")
    if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", target):
        die("SSH target must be a hostname or SSH alias, not options or shell text")
    if entry.get("platform", "posix") != "posix":
        die("this release supports only POSIX remote workers")
    return {**entry, "platform": "posix", "label": machine, "target": target}

def remote_sh(machine, argv):
    cfg = machine_config(machine)
    command = 'export PATH="$HOME/.local/bin:$PATH"; exec ' + shlex.join(argv)
    return run(["ssh", "-o", "BatchMode=yes", cfg["target"], "sh", "-lc", shlex.quote(command)])

def remote_herdr(machine, args):
    return remote_sh(machine, ["herdr", *args])

def one_shot_command(args):
    require_name(args.name)
    path = f'$HOME/.local/share/herdr/pache-lanes/{args.name}/prompt.md'
    command = f'claude -p "$(cat "{path}")" --output-format text'
    command += " --permission-mode plan" if args.role in {"checker", "planner"} else " --permission-mode default"
    if args.model: command += " --model " + shlex.quote(args.model)
    if args.effort: command += " --effort " + shlex.quote(args.effort)
    return command + '; rc=$?; printf "__PACHE_EXIT__=%s\\n" "$rc"'

def create(args):
    require_name(args.name)
    machine_config(args.machine)
    if not args.repo.startswith('/') or '\n' in args.repo:
        die("--repo must be an absolute POSIX path")
    directory = lane_dir(args.name)
    if directory.exists(): die("lane already exists; stop/remove before recreating")
    prompt = Path(args.prompt_file).expanduser().read_text() if args.prompt_file else args.prompt or ""
    if not prompt.strip(): die("provide --prompt or --prompt-file")
    from .local import build_task_packet
    packet = build_task_packet(name=args.name, repo=args.repo, role=args.role, risk=args.risk, max_repairs=2, verification_commands=args.verification_cmd) + "\n" + prompt
    if not args.dry_run:
        for argv in (["test", "-d", args.repo], ["claude", "auth", "status", "--text"]):
            result = remote_sh(args.machine, argv)
            if result.returncode: die("remote repo/auth preflight failed")
    directory.mkdir(parents=True, mode=0o700)
    (directory/'prompt.md').write_text(packet)
    (directory/'run.log').touch()
    meta = {"name":args.name,"machine":args.machine,"repo":args.repo,"agent":"claude","role":args.role,"risk":args.risk,"model":args.model,"effort":args.effort,"verification_commands":args.verification_cmd,"run_log":str(directory/'run.log'),"herdr_session":SESSION,"state":"dry-run" if args.dry_run else "creating","created_at":now()}
    save(args.name, meta)
    if args.dry_run:
        print(json.dumps({"ok":True,"dry_run":True,"lane":args.name,"command":one_shot_command(args)})); return
    workspace = None
    try:
        made = remote_json(args.machine,prefix(meta)+["workspace","create","--cwd",args.repo,"--label",f"Pache {args.name}","--no-focus"])["result"]
        workspace = made["workspace"]["workspace_id"]
        pane = made["root_pane"]["pane_id"]
        meta.update(workspace_id=workspace,pane_id=pane)
        save(args.name,meta)
        upload_packet(args.machine,args.name,packet)
        result=remote_herdr(args.machine,prefix(meta)+["pane","run",pane,one_shot_command(args)])
        if result.returncode: die("remote launch failed")
    except (KeyError,SystemExit,OSError):
        if workspace:
            cleanup=remote_herdr(args.machine,prefix(meta)+["workspace","close",workspace])
            meta["cleanup_ok"]=cleanup.returncode==0
        meta["state"]="failed"; save(args.name,meta); raise
    meta["state"]="working"; save(args.name,meta)
    print(json.dumps({"ok":True,"lane":args.name,"workspace_id":workspace}))

def pane_state(meta):
    if meta.get("state") in {"dry-run","stopped"}: return meta["state"]
    text=pane_text(meta,500)
    if not text: return "unknown"
    # Require a standalone sentinel, not arbitrary prompt prose.
    matches=re.findall(r"(?m)^__PACHE_EXIT__=(\d+)\r?$",text)
    if matches: return "done" if matches[-1]=="0" else "failed"
    return "working"

def status(args):
    meta=load(args.name); meta["state"]=pane_state(meta); save(args.name,meta)
    print(json.dumps(meta,indent=2))

def listing(args):
    rows=[]
    for path in sorted(ROOT.glob('*/status.json')):
        if path.parent.is_symlink(): continue
        meta=load(path.parent.name); meta["state"]=pane_state(meta); rows.append(meta)
    print(json.dumps(rows,indent=2))

def read_lane(args):
    meta=load(args.name)
    text=Path(meta["run_log"]).read_text() if meta.get("state") in {"dry-run","stopped"} else pane_text(meta,args.lines)
    Path(meta["run_log"]).write_text(text); print(text)

def stop(args):
    meta=load(args.name)
    if meta.get("state") not in {"dry-run","stopped"}:
        text=pane_text(meta,500)
        if text: Path(meta["run_log"]).write_text(text)
        result=remote_herdr(meta["machine"],prefix(meta)+["workspace","close",meta["workspace_id"]])
        if result.returncode: die("remote close failed; evidence retained")
    meta["state"]="stopped"; save(args.name,meta)
    print(json.dumps({"ok":True,"state":"stopped"}))

def remove(args):
    import shutil
    meta=load(args.name)
    if meta.get("state") not in {"stopped","dry-run"}: die("stop workspace before remove")
    shutil.rmtree(lane_dir(args.name)); print(json.dumps({"ok":True,"removed":args.name}))

def parser():
    p=argparse.ArgumentParser(prog="pache-remote-lane",description="Experimental POSIX Herdr-over-SSH finite Claude lanes")
    p.add_argument('--version',action='version',version=VERSION)
    sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('create'); c.add_argument('name'); c.add_argument('--machine',required=True); c.add_argument('--repo',required=True)
    c.add_argument('--role',choices=['maker','checker','planner'],default='maker'); c.add_argument('--risk',choices=['low','medium','high'],default='medium')
    c.add_argument('--model'); c.add_argument('--effort',choices=['low','medium','high']); c.add_argument('--prompt'); c.add_argument('--prompt-file'); c.add_argument('--verification-cmd',action='append',default=[]); c.add_argument('--dry-run',action='store_true'); c.set_defaults(func=create)
    for name,func in [('status',status),('stop',stop),('remove',remove),('read',read_lane),('verify',verify)]:
        s=sub.add_parser(name); s.add_argument('name'); s.set_defaults(func=func)
        if name=='read': s.add_argument('--lines',type=int,default=100)
        if name=='verify': s.add_argument('--cmd',action='append')
    sub.add_parser('list').set_defaults(func=listing)
    return p

def main(argv=None):
    os.umask(0o077)
    args=parser().parse_args(argv); args.func(args)
