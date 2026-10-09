#!/usr/bin/env python3
"""pache-lane: bounded Hermes lane manager with Herdr-first lifecycle."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import state_root, config

LANES_DIR = state_root() / "local"
HERDR_SESSION = config().get("herdr_session", "pache-lanes")
from . import tmux_private


def tmux_socket_path() -> str:
    try:
        return str(tmux_private.validate(LANES_DIR.parent))
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        die(f"tmux transport unavailable; preserving lane evidence: {exc}")


def tmux_owner() -> str:
    socket = Path(tmux_socket_path())
    return json.loads((socket.parent / 'owner.json').read_text())['nonce']


def tmux_lane_guard(meta: Dict[str, Any]) -> None:
    if not meta.get('tmux_owner') or meta['tmux_owner'] != tmux_owner():
        die('tmux lane not bound to this private server; preserving lane evidence')


def init_tmux(args: argparse.Namespace) -> None:
    try:
        socket = tmux_private.initialize(LANES_DIR.parent)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        die(f"tmux initialization refused; reservation/evidence retained: {exc}")
    print(json.dumps({"ok": True, "socket": str(socket)}))
_run_shadow_route = None
_sanitize_reflex_event = None

SCRIPT_VERSION = "0.1.0"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def run(
    cmd: List[str], *, cwd: Optional[str] = None, check: bool = False,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    if cmd and cmd[0] == "tmux":
        cmd = ["tmux", "-S", tmux_socket_path()] + cmd[1:]
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd, cwd=cwd, check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=merged_env,
    )


def shell(cmd: str, *, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)


def require_name(name: str) -> None:
    if not SAFE_NAME_RE.fullmatch(name) or ".." in name or name == ".":
        die("lane name may only contain letters, numbers, dot, underscore, and dash")


def copilot_credit_limit(value: str) -> int:
    credits = int(value)
    if credits < 30:
        raise argparse.ArgumentTypeError("Copilot requires at least 30 AI credits per session ceiling")
    return credits


def lane_dir(name: str) -> Path:
    require_name(name)
    path = LANES_DIR / name
    if path.is_symlink():
        die("lane directory may not be a symlink")
    return path


def meta_path(name: str) -> Path:
    return lane_dir(name) / "status.json"


def read_meta(name: str) -> Dict[str, Any]:
    path = meta_path(name)
    if not path.exists():
        die(f"lane not found: {name}")
    meta = json.loads(path.read_text())
    if meta.get("backend") == "herdr" and meta.get("herdr_session") != HERDR_SESSION:
        die("recorded Herdr session differs from configured session; restore owner configuration")
    if meta.get("backend") == "tmux":
        tmux_lane_guard(meta)
    return meta


def write_meta(name: str, meta: Dict[str, Any]) -> None:
    directory = lane_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    if "reflex" in meta and meta["reflex"] is not None:
        try:
            if _sanitize_reflex_event is None:
                raise RuntimeError("reflex sanitizer unavailable")
            meta["reflex"] = dict(_sanitize_reflex_event(meta["reflex"]))
        except Exception:
            meta["reflex"] = {
                "event": "route_shadow",
                "mode": "shadow",
                "status": "error",
                "reason": "component_failure",
            }
    meta["updated_at"] = now_iso()
    (directory / "status.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")


def append_event(name: str, event: Dict[str, Any]) -> None:
    directory = lane_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    event.setdefault("ts", now_iso())
    with (directory / "events.jsonl").open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def which(binary: str) -> Optional[str]:
    return shutil.which(binary)


def resolve_backend(requested: str) -> str:
    if requested != "auto":
        return requested
    if which("herdr"):
        return "herdr"
    if which("tmux"):
        return "tmux"
    die("neither herdr nor tmux is installed")
    return "unknown"


def resolve_agent_backend(agent: str, requested: str) -> str:
    # Herdr detects Copilot CLI, but current interactive prompt injection can
    # remain idle. Non-interactive tmux mode is deterministic and observable.
    if agent == "copilot" and requested == "auto" and which("tmux"):
        return "tmux"
    return resolve_backend(requested)


def account_environment(agent: str, account: str) -> Dict[str, str]:
    """Default reuses the existing login. Isolation is explicit and never automatic."""
    if account == "default":
        return {}
    if agent == "claude":
        return {"CLAUDE_CONFIG_DIR": str(Path.home() / f".claude-{account}")}
    if agent == "codex":
        return {"CODEX_HOME": str(Path.home() / f".codex-{account}")}
    return {}


def auth_preflight(agent: str, account: str) -> None:
    env = account_environment(agent, account)
    if agent == "claude":
        cp = run(["claude", "auth", "status", "--text"], env=env)
    elif agent == "codex":
        cp = run(["codex", "login", "status"], env=env)
    else:
        return
    if cp.returncode != 0:
        namespace = "current default login" if account == "default" else f"explicit {account} namespace"
        die(f"{agent} is not authenticated in the {namespace}; authenticate it once before launching lanes")


def validate_raw_agent_args(raw_args: List[str]) -> None:
    if raw_args:
        raise ValueError(
            "raw --agent-arg is disabled; use typed --add-dir/--sandbox options, "
            "raw overrides are not supported"
        )


def render_typed_agent_args(agent: str, add_dirs: List[str], sandbox: Optional[str]) -> List[str]:
    rendered: List[str] = []
    if add_dirs and agent != "claude":
        raise ValueError("--add-dir is supported only for Claude lanes")
    for directory in add_dirs:
        resolved = str(Path(directory).expanduser().resolve())
        if not Path(resolved).exists():
            raise ValueError(f"--add-dir path does not exist: {resolved}")
        rendered += ["--add-dir", shlex.quote(resolved)]
    if sandbox:
        if agent != "codex":
            raise ValueError("--sandbox is supported only for Codex lanes")
        rendered += ["--sandbox", shlex.quote(sandbox)]
    return rendered


def copilot_agent_args(*, model: Optional[str], max_ai_credits: int, interactive: bool) -> List[str]:
    """Bound unattended Copilot lanes and prevent common remote/destructive effects."""
    args = [
        "--deny-tool=shell(git push)",
        "--deny-tool=shell(gh pr merge)",
        "--deny-tool=shell(rm)",
        "--no-remote",
        "--max-ai-credits", str(max_ai_credits),
    ]
    if interactive:
        args.append("--no-alt-screen")
    if model:
        args += ["--model", model]
    return args


def run_reflex_shadow(**kwargs: Any) -> Dict[str, Any]:
    """Run advisory routing without ever blocking or mutating lane execution."""
    if _run_shadow_route is None or _sanitize_reflex_event is None:
        return {
            "event": "route_shadow",
            "mode": "shadow",
            "status": "skipped",
            "reason": "component_unavailable",
        }
    try:
        return dict(_sanitize_reflex_event(_run_shadow_route(**kwargs)))
    except Exception:
        return {
            "event": "route_shadow",
            "mode": "shadow",
            "status": "error",
            "reason": "component_failure",
        }


def build_task_packet(
    *, name: str, repo: str, role: str, risk: str, max_repairs: int,
    verification_commands: List[str],
) -> str:
    checks = "\n".join(f"- `{cmd}`" for cmd in verification_commands)
    if not checks:
        checks = "- Discover and report the narrowest deterministic check."
    return f"""# Pache Lane: {name}

Role: {role}
Risk: {risk}
Repo/workdir: {repo}
Maximum repair cycles: {max_repairs}

Operating contract:
- One writer per worktree. A checker is read-only unless explicitly promoted.
- Deterministic checks run before LLM review.
- Do not commit, push, deploy, send externally, spend credits, or print secrets unless explicitly authorized.
- Keep edits inside the stated scope and preserve exact identifiers, commands, and error strings.
- Worker self-report is evidence to inspect, never final proof.
- Stop after the second failure of the same gate; preserve exact evidence and escalate with a clean diagnostic context.

Required verification:
{checks}

Handoff schema:
- files_changed
- commands_run with exit codes
- gate_result: pass|fail|blocked
- unresolved_risks
- repair_cycles_used
"""


def tmux_session_name(name: str) -> str:
    return f"pache-{name}"


def tmux_has_session(session: str) -> bool:
    """Present/absent observation; unavailable is a fatal error, never False.

    Exit 1 also means an unreachable/missing server socket. Only the server's
    exact missing-target diagnostic proves absence; socket errors do not prove
    that an old worker exited (the socket may have been unlinked).
    """
    if not session or not SAFE_NAME_RE.fullmatch(session):
        die("tmux session identity missing or invalid; preserving lane evidence")
    if not which("tmux"):
        die("tmux unavailable; preserving lane evidence")
    try:
        cp = run(["tmux", "has-session", "-t", "=" + session], env={"LC_ALL": "C"})
    except OSError as exc:
        die(f"tmux observation unavailable; preserving lane evidence: {exc}")
    if cp.returncode == 0:
        return True
    if (cp.returncode == 1 and not cp.stdout.strip()
            and cp.stderr.strip() == f"can't find session: {session}"):
        return False
    if cp.returncode == 1 and not cp.stdout.strip() and cp.stderr.strip() == 'no current target':
        # A connected, ownership-verified empty server has no current target.
        inventory = run(['tmux', 'list-sessions', '-F', '#{session_name}'], env={'LC_ALL': 'C'})
        if inventory.returncode == 0 and not inventory.stdout.strip() and not inventory.stderr.strip():
            return False
    die(f"tmux observation unavailable; preserving lane evidence: {cp.stderr.strip() or 'unrecognized response'}")


def tmux_capture(session: str, lines: int = 80) -> str:
    if not tmux_has_session(session):
        return ""
    cp = run(["tmux", "capture-pane", "-t", "=" + session, "-p", "-S", f"-{lines}"])
    return cp.stdout.rstrip() if cp.returncode == 0 else cp.stderr.strip()


def build_tmux_launch(repo: str, command: str, exit_file: Optional[str] = None) -> str:
    launch = f"cd {shlex.quote(repo)} && {command}"
    if exit_file:
        launch += f"; rc=$?; printf '%s\\n' \"$rc\" > {shlex.quote(exit_file)}; exit \"$rc\""
    return launch


def idle_tmux_sessions(rows: List[Dict[str, str]]) -> List[str]:
    shells = {"sh", "bash", "zsh", "fish", "dash", "ksh"}
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get("session", ""), []).append(row)
    return sorted(
        session for session, panes in grouped.items()
        if session.startswith("pache-")
        and all(pane.get("command") in shells and pane.get("attached") == "0" for pane in panes)
    )


def herdr_prefix() -> List[str]:
    return ["herdr", "--session", HERDR_SESSION]


def herdr_prompt_command(target: str, text: str) -> List[str]:
    return herdr_prefix() + [
        "agent", "prompt", target, text,
        "--wait",
        "--until", "working",
        "--until", "done",
        "--until", "blocked",
        "--timeout", "10000",
    ]


def run_json(cmd: List[str]) -> Dict[str, Any]:
    cp = run(cmd)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or f"command failed: {cmd}")
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from {' '.join(cmd[:4])}: {cp.stdout[:500]}") from exc


def build_agent_command(args: argparse.Namespace, directory: Path) -> str:
    validate_raw_agent_args(args.extra)
    run_log = directory / "run.jsonl"
    prompt_file = directory / "prompt.md"
    env = account_environment(args.agent, args.account)
    env_prefix = "".join(f"{key}={shlex.quote(value)} " for key, value in env.items())
    effective_sandbox = None if args.role in {"checker", "planner"} else args.sandbox
    if args.agent == "codex" and args.role == "maker":
        effective_sandbox = effective_sandbox or "workspace-write"
    typed = render_typed_agent_args(args.agent, args.add_dir, effective_sandbox)
    prompt_arg = '"$(cat ' + shlex.quote(str(prompt_file)) + ')"'

    if args.agent == "claude":
        parts = ["claude", "-p", prompt_arg]
        if args.model:
            parts += ["--model", shlex.quote(args.model)]
        if args.effort:
            parts += ["--effort", shlex.quote(args.effort)]
        if args.role in {"checker", "planner"}:
            parts += ["--permission-mode", "plan"]
        elif args.allowed_tools:
            parts += ["--allowedTools", shlex.quote(args.allowed_tools)]
        if args.max_turns:
            parts += ["--max-turns", str(args.max_turns)]
        parts += ["--output-format", "stream-json", "--verbose"] if args.stream else ["--output-format", "json"]
    elif args.agent == "codex":
        parts = ["codex", "exec", prompt_arg]
        if args.role in {"checker", "planner"}:
            parts += ["--sandbox", "read-only"]
        if args.model:
            parts += ["--model", shlex.quote(args.model)]
    elif args.agent == "hermes":
        parts = ["hermes", "chat", "-q", prompt_arg, "--quiet"]
        if args.model:
            parts += ["--model", shlex.quote(args.model)]
    elif args.agent == "copilot":
        parts = ["copilot", "-p", prompt_arg, "--silent"]
        parts += [shlex.quote(value) for value in copilot_agent_args(
            model=args.model or "auto", max_ai_credits=args.max_ai_credits, interactive=False,
        )]
    elif args.agent == "noop":
        return f"printf 'pache-lane noop completed at {now_iso()}\\n' > {shlex.quote(str(run_log))} 2>&1"
    else:
        die(f"unsupported agent: {args.agent}")
        return ""

    parts += typed
    if args.extra:
        parts += [shlex.quote(value) for value in args.extra]
    return env_prefix + " ".join(parts) + f" > {shlex.quote(str(run_log))} 2>&1"


def infer_state(meta: Dict[str, Any]) -> str:
    if meta.get("backend") == "tmux":
        tmux_lane_guard(meta)
        if tmux_has_session(meta.get("session", "")):
            return "working"
        exit_file = Path(meta.get("exit_file", ""))
        if exit_file.is_file():
            try:
                return "done" if int(exit_file.read_text().strip()) == 0 else "failed"
            except ValueError:
                return "failed"
        return "stopped"
    return meta.get("state", "unknown")


def create_herdr_lane(args: argparse.Namespace, meta: Dict[str, Any], directory: Path, repo: str) -> None:
    env = account_environment(args.agent, args.account)
    create_cmd = herdr_prefix() + ["workspace", "create", "--cwd", repo, "--label", f"Pache {args.name}", "--no-focus"]
    for key, value in env.items():
        create_cmd += ["--env", f"{key}={value}"]
    workspace_id: Optional[str] = None
    try:
        result = run_json(create_cmd)["result"]
        workspace_id = result["workspace"]["workspace_id"]
        pane_id = result["root_pane"]["pane_id"]
        meta.update({"workspace_id": workspace_id, "pane_id": pane_id,
                     "agent_name": args.name, "herdr_session": HERDR_SESSION,
                     "state": "creating"})
        write_meta(args.name, meta)
        agent_args: List[str] = []
        if args.model:
            agent_args += ["--model", args.model]
        if args.agent == "claude":
            if args.effort:
                agent_args += ["--effort", args.effort]
            if args.role in {"checker", "planner"}:
                agent_args += ["--permission-mode", "plan"]
            elif args.allowed_tools:
                agent_args += ["--allowedTools", args.allowed_tools]
            for extra_dir in args.add_dir:
                agent_args += ["--add-dir", str(Path(extra_dir).expanduser().resolve())]
        if args.agent == "codex":
            agent_args += ["--sandbox", "read-only" if args.role in {"checker", "planner"} else (args.sandbox or "workspace-write")]
        if args.agent == "copilot":
            agent_args += copilot_agent_args(
                model=args.model or "auto", max_ai_credits=args.max_ai_credits, interactive=True,
            )
        if args.extra:
            agent_args += args.extra
        start = herdr_prefix() + ["agent", "start", args.name, "--kind", args.agent, "--pane", pane_id, "--timeout", "60000"]
        if agent_args:
            start += ["--"] + agent_args
        run_json(start)
        run_json(herdr_prompt_command(args.name, (directory / "prompt.md").read_text()))
    except (RuntimeError, KeyError, OSError) as exc:
        meta.update({"state": "failed", "herdr_session": HERDR_SESSION})
        if workspace_id:
            cleanup = run(herdr_prefix() + ["workspace", "close", workspace_id])
            meta["cleanup_ok"] = cleanup.returncode == 0
        write_meta(args.name, meta)
        die(f"failed to start Herdr lane: {exc}")
    meta.update({
        "workspace_id": workspace_id, "pane_id": pane_id, "agent_name": args.name,
        "herdr_session": HERDR_SESSION, "state": "working",
    })
    write_meta(args.name, meta)
    append_event(args.name, {"event": "created", "backend": "herdr", "workspace_id": workspace_id, "repo": repo})
    print(json.dumps({"ok": True, "lane": args.name, "backend": "herdr", "workspace_id": workspace_id, "dir": str(directory)}, indent=2))


def create_lane(args: argparse.Namespace) -> None:
    require_name(args.name)
    directory = lane_dir(args.name)
    if directory.exists():
        die(f"lane already exists: {args.name}; stop and remove it first")
    repo = str(Path(args.repo).expanduser().resolve())
    if not Path(repo).exists():
        die(f"repo/workdir does not exist: {repo}")
    prompt_text = Path(args.prompt_file).expanduser().read_text() if args.prompt_file else (args.prompt or "")
    if not prompt_text.strip():
        die("provide --prompt or --prompt-file")
    try:
        validate_raw_agent_args(args.extra)
        render_typed_agent_args(args.agent, args.add_dir, args.sandbox)
    except ValueError as exc:
        die(str(exc))
    if args.role in {"checker", "planner"} and args.agent not in {"claude", "codex", "noop"}:
        die("checker/planner enforcement is supported only for Claude and Codex")
    if args.role in {"checker", "planner"} and args.sandbox == "workspace-write":
        die("checkers cannot request workspace-write")
    if not args.dry_run:
        auth_preflight(args.agent, args.account)
    backend = "dry-run" if args.dry_run else resolve_agent_backend(args.agent, args.backend)
    if args.agent == "noop" and backend == "herdr":
        backend = "tmux"
    if backend in {"herdr", "tmux", "cmux"} and not which(backend):
        die(f"{backend} requested but not installed/on PATH")
    if backend == "tmux":
        if tmux_has_session(tmux_session_name(args.name)):
            die("tmux session already exists; unknown worker will not be adopted")
    directory.mkdir(parents=True, exist_ok=False)

    reflex_result: Optional[Dict[str, Any]] = None
    if args.reflex_mode == "shadow":
        reflex_result = run_reflex_shadow(
            lane_name=args.name,
            repo=repo,
            role=args.role,
            risk=args.risk,
            current_agent=args.agent,
            current_model=args.model,
            verification_commands=args.verification_cmd,
            prompt_text=prompt_text,
        )
    header = build_task_packet(
        name=args.name, repo=repo, role=args.role, risk=args.risk,
        max_repairs=args.max_repairs, verification_commands=args.verification_cmd,
    ) + f"\nStarted: {now_iso()}\n\n---\n\n"
    (directory / "prompt.md").write_text(header + prompt_text.strip() + "\n")
    (directory / "run.jsonl").touch()
    (directory / "events.jsonl").touch()

    meta: Dict[str, Any] = {
        "name": args.name, "version": SCRIPT_VERSION, "created_at": now_iso(),
        "repo": repo, "agent": args.agent, "backend": backend, "model": args.model,
        "effort": args.effort, "allowed_tools": args.allowed_tools, "account": args.account,
        "max_ai_credits": args.max_ai_credits if args.agent == "copilot" else None,
        "role": args.role, "risk": args.risk, "max_repairs": args.max_repairs,
        "verification_commands": args.verification_cmd,
        "reflex_mode": args.reflex_mode, "reflex": reflex_result,
        "prompt_file": str(directory / "prompt.md"), "run_log": str(directory / "run.jsonl"),
        "events_log": str(directory / "events.jsonl"), "state": "created",
    }
    if args.dry_run:
        meta.update({"state": "dry-run", "note": "Lane packet created; no process started."})
        write_meta(args.name, meta)
        append_event(args.name, {"event": "dry-run-created", "repo": repo})
        print(json.dumps({"ok": True, "lane": args.name, "backend": backend, "dir": str(directory), "dry_run": True}, indent=2))
        return
    if backend == "herdr":
        create_herdr_lane(args, meta, directory, repo)
        return
    if backend == "tmux":
        session = tmux_session_name(args.name)
        if tmux_has_session(session):
            die(f"tmux session already exists: {session}")
        command = build_agent_command(args, directory)
        exit_file = str(directory / "exit_code")
        Path(exit_file).unlink(missing_ok=True)
        launch = build_tmux_launch(repo, command, exit_file)
        meta.update({"session": session, "exit_file": exit_file, "state": "creating", "command": command, "tmux_owner": tmux_owner()})
        write_meta(args.name, meta)
        cp = run(["tmux", "new-session", "-d", "-s", session, "-x", str(args.width), "-y", str(args.height), launch])
        if cp.returncode != 0:
            die(cp.stderr.strip() or "failed to create tmux session")
        meta.update({"session": session, "exit_file": exit_file, "state": "working", "command": command, "tmux_owner": tmux_owner()})
        write_meta(args.name, meta)
        append_event(args.name, {"event": "created", "backend": "tmux", "session": session, "repo": repo})
        print(json.dumps({"ok": True, "lane": args.name, "backend": "tmux", "session": session, "dir": str(directory)}, indent=2))
        return
    meta.update({"state": "manual-cmux", "note": "Use Herdr or tmux for automated lifecycle; cmux remains a manual cockpit."})
    write_meta(args.name, meta)
    print(json.dumps({"ok": True, "lane": args.name, "backend": backend, "dir": str(directory), "note": meta["note"]}, indent=2))


def herdr_agent_status(meta: Dict[str, Any]) -> Dict[str, Any]:
    cp = run(herdr_prefix() + ["agent", "get", meta.get("agent_name", meta["name"])])
    if cp.returncode != 0:
        return {"agent_status": "unknown"}
    try:
        result = json.loads(cp.stdout).get("result", {})
        return result.get("agent", result)
    except json.JSONDecodeError:
        return {"agent_status": "unknown"}


def list_lanes(args: argparse.Namespace) -> None:
    LANES_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(LANES_DIR.glob("*/status.json")):
        if path.parent.is_symlink():
            continue
        try:
            meta = json.loads(path.read_text())
        except Exception:
            continue
        if meta.get("backend") == "herdr":
            meta["state"] = herdr_agent_status(meta).get("agent_status", meta.get("state", "unknown"))
        else:
            meta["state"] = infer_state(meta)
        rows.append(meta)
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return
    if not rows:
        print("No lanes.")
        return
    print(f"{'LANE':28} {'STATE':10} {'ROLE':8} {'AGENT':8} {'BACKEND':8} {'REPO'}")
    for meta in rows:
        print(f"{meta.get('name','')[:28]:28} {meta.get('state','')[:10]:10} {meta.get('role','')[:8]:8} {meta.get('agent','')[:8]:8} {meta.get('backend','')[:8]:8} {meta.get('repo','')}")


def status_lane(args: argparse.Namespace) -> None:
    meta = read_meta(args.name)
    if meta.get("backend") == "herdr":
        agent = herdr_agent_status(meta)
        meta["state"] = agent.get("agent_status", meta.get("state", "unknown"))
        meta["herdr_agent"] = agent
    else:
        meta["state"] = infer_state(meta)
    write_meta(args.name, meta)
    print(json.dumps(meta, indent=2, sort_keys=True))
    if not args.json and meta.get("backend") == "tmux" and meta.get("session"):
        screen = tmux_capture(meta["session"], args.lines)
        if screen:
            print("\n--- screen tail ---\n" + screen)


def read_lane(args: argparse.Namespace) -> None:
    meta = read_meta(args.name)
    if args.log:
        log = Path(meta.get("run_log", lane_dir(args.name) / "run.jsonl"))
        if not log.exists():
            die("run log not found")
        print("\n".join(log.read_text(errors="replace").splitlines()[-args.lines:]))
        return
    if meta.get("backend") == "herdr":
        cp = run(herdr_prefix() + ["agent", "read", meta.get("agent_name", args.name), "--lines", str(args.lines), "--format", "text"])
        if cp.returncode != 0:
            die(cp.stderr.strip() or cp.stdout.strip() or "Herdr read failed")
        try:
            result = json.loads(cp.stdout).get("result", {})
            print(result.get("text", result.get("output", cp.stdout)))
        except json.JSONDecodeError:
            print(cp.stdout.rstrip())
        return
    if meta.get("backend") == "tmux" and meta.get("session"):
        print(tmux_capture(meta["session"], args.lines))
        return
    die("no readable backend session; use --log for completed lanes")


def send_lane(args: argparse.Namespace) -> None:
    meta = read_meta(args.name)
    if meta.get("backend") == "herdr":
        cp = run(herdr_prompt_command(meta.get("agent_name", args.name), args.text))
        if cp.returncode != 0:
            die(cp.stderr.strip() or cp.stdout.strip() or "Herdr prompt failed")
    elif meta.get("backend") == "tmux":
        die("finite tmux workers cannot receive follow-ups; create a new lane after completion")
    else:
        die("lane is not active")
    append_event(args.name, {"event": "send", "text": args.text})
    print(json.dumps({"ok": True, "lane": args.name, "sent": args.text}, indent=2))


def stop_lane(args: argparse.Namespace) -> None:
    meta = read_meta(args.name)
    if meta.get("backend") == "herdr" and meta.get("workspace_id"):
        target = meta.get("agent_name", args.name)
        snapshot = run(herdr_prefix() + ["agent", "read", target, "--lines", "400", "--format", "text"])
        if snapshot.returncode == 0:
            Path(meta["run_log"]).write_text(snapshot.stdout)
        cp = run(herdr_prefix() + ["workspace", "close", meta["workspace_id"]])
        if cp.returncode != 0:
            die(cp.stderr.strip() or cp.stdout.strip() or "Herdr workspace close failed")
    elif meta.get("backend") == "tmux" and meta.get("session"):
        if tmux_has_session(meta["session"]):
            cp = run(["tmux", "kill-session", "-t", "=" + meta["session"]])
            if cp.returncode != 0:
                die(cp.stderr.strip() or "tmux kill-session failed")
            if tmux_has_session(meta["session"]):
                die("tmux session still present after kill; preserving lane evidence")
    elif meta.get("backend") not in {"dry-run", "cmux"}:
        die("unsupported lane backend")
    meta["state"] = "stopped"
    write_meta(args.name, meta)
    append_event(args.name, {"event": "stopped"})
    print(json.dumps({"ok": True, "lane": args.name, "state": "stopped"}, indent=2))


def remove_lane(args: argparse.Namespace) -> None:
    meta = read_meta(args.name)
    if meta.get("backend") == "herdr" and meta.get("state") != "stopped":
        die("close the Herdr workspace with stop before removing")
    if meta.get("backend") == "tmux" and tmux_has_session(meta.get("session", "")):
        die("stop active tmux lane before removing")
    shutil.rmtree(lane_dir(args.name))
    print(json.dumps({"ok": True, "removed": args.name}))



def verify_lane(args: argparse.Namespace) -> None:
    meta = read_meta(args.name)
    repo = meta.get("repo")
    if not repo or not Path(repo).exists():
        die("lane repo missing")
    commands = ["git status --short --untracked-files=all", "git diff --name-only", "git diff --check"] + (args.cmd or [])
    checks = []
    for command in commands:
        cp = shell(command, cwd=repo)
        checks.append({"cmd": command, "exit_code": cp.returncode, "stdout": cp.stdout[-12000:], "stderr": cp.stderr[-12000:]})
    output = {"lane": args.name, "repo": repo, "verified_at": now_iso(), "gate_result": "pass" if all(item["exit_code"] == 0 for item in checks) else "fail", "checks": checks}
    (lane_dir(args.name) / "verify.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))
    if output["gate_result"] != "pass":
        raise SystemExit(1)


def prune_tmux(args: argparse.Namespace) -> None:
    if not which("tmux"):
        die("tmux unavailable; prune cannot establish session inventory")
    cp = run(["tmux", "list-panes", "-a", "-F", "#{session_name}\t#{pane_current_command}\t#{session_attached}"])
    if cp.returncode != 0:
        die(cp.stderr.strip() or "tmux inventory unavailable; prune refused")
    rows = []
    if cp.returncode == 0:
        for line in cp.stdout.splitlines():
            values = line.split("\t")
            if len(values) == 3:
                rows.append({"session": values[0], "command": values[1], "attached": values[2]})
    candidates = idle_tmux_sessions(rows)
    removed: List[str] = []
    if args.apply:
        for session in candidates:
            meta = read_meta(session[len('pache-'):])
            if meta.get('backend') != 'tmux' or meta.get('session') != session:
                die('prune target not an owned tmux lane; refused')
            tmux_lane_guard(meta)
            cp = run(["tmux", "kill-session", "-t", "=" + session])
            if cp.returncode != 0:
                die(cp.stderr.strip() or "tmux prune kill failed")
            if tmux_has_session(session):
                die('prune session still present; preserving evidence')
            removed.append(session)
    print(json.dumps({"ok": True, "candidates": candidates, "removed": removed, "dry_run": not args.apply}, indent=2))


def cmux_help(args: argparse.Namespace) -> None:
    if not which("cmux"):
        die("cmux not installed/on PATH")
    for command in (["cmux", "--help"], ["cmux", "list-workspaces", "--help"], ["cmux", "read-screen", "--help"], ["cmux", "send", "--help"]):
        cp = run(list(command))
        print(f"\n$ {' '.join(command)}\nexit={cp.returncode}\n{cp.stdout}{cp.stderr}")


def remote_lane(args: argparse.Namespace) -> None:
    from .remote import main
    main(args.remote_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pache-lane", description="Herdr-first bounded coding-agent lane manager")
    parser.add_argument("--version", action="version", version=SCRIPT_VERSION)
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("tmux-init", help="initialize a NEW private tmux server; never adopt/replace")
    init.set_defaults(func=init_tmux)

    create = sub.add_parser("create", help="create and start a bounded lane")
    create.add_argument("name")
    create.add_argument("--repo", default=str(Path.cwd()))
    create.add_argument("--agent", choices=["claude", "codex", "copilot", "hermes", "noop"], default="claude")
    create.add_argument("--backend", choices=["auto", "herdr", "tmux", "cmux"], default="auto")
    create.add_argument("--model")
    create.add_argument("--effort", choices=["low", "medium", "high", "max", "auto"])
    create.add_argument("--allowed-tools", default=None)
    create.add_argument("--max-turns", type=int)
    create.add_argument("--max-ai-credits", type=copilot_credit_limit, default=50, help="Copilot per-session ceiling (minimum 30)")
    create.add_argument("--account", choices=["default"], default="default", help="default reuses current CLI login")
    create.add_argument("--role", choices=["maker", "checker", "planner"], default="maker")
    create.add_argument("--risk", choices=["low", "medium", "high"], default="medium")
    create.add_argument("--max-repairs", type=int, choices=[0, 1, 2], default=2)
    create.add_argument("--reflex-mode", choices=["off"], default="off", help="advisory Jev route evaluation; shadow never changes execution")
    create.add_argument("--verification-cmd", action="append", default=[])
    create.add_argument("--add-dir", action="append", default=[], help="typed Claude reference directory; repeatable")
    create.add_argument("--sandbox", choices=["read-only", "workspace-write"], help="typed Codex sandbox policy")
    create.add_argument("--prompt")
    create.add_argument("--prompt-file")
    create.add_argument("--dry-run", action="store_true")
    create.add_argument("--stream", action=argparse.BooleanOptionalAction, default=True)
    create.add_argument("--width", type=int, default=140)
    create.add_argument("--height", type=int, default=40)
    create.add_argument("--agent-arg", dest="extra", action="append", default=[], help="raw args are always rejected; use typed options")
    create.set_defaults(func=create_lane)

    listing = sub.add_parser("list", aliases=["ls", "status-all"])
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=list_lanes)

    status = sub.add_parser("status")
    status.add_argument("name")
    status.add_argument("--json", action="store_true")
    status.add_argument("--lines", type=int, default=60)
    status.set_defaults(func=status_lane)

    read_cmd = sub.add_parser("read")
    read_cmd.add_argument("name")
    read_cmd.add_argument("--lines", type=int, default=100)
    read_cmd.add_argument("--log", action="store_true")
    read_cmd.set_defaults(func=read_lane)

    send = sub.add_parser("send")
    send.add_argument("name")
    send.add_argument("text")
    send.set_defaults(func=send_lane)

    stop = sub.add_parser("stop")
    stop.add_argument("name")
    stop.set_defaults(func=stop_lane)

    remove = sub.add_parser("remove", aliases=["rm"])
    remove.add_argument("name")
    remove.set_defaults(func=remove_lane)

    verify = sub.add_parser("verify")
    verify.add_argument("name")
    verify.add_argument("--cmd", action="append")
    verify.set_defaults(func=verify_lane)

    prune = sub.add_parser("prune", help="preview/remove detached pache-* tmux sessions at idle shells")
    prune.add_argument("--apply", action="store_true")
    prune.set_defaults(func=prune_tmux)

    cmux = sub.add_parser("cmux-help")
    cmux.set_defaults(func=cmux_help)

    remote = sub.add_parser("remote", help="delegate to the safe Herdr-over-SSH backend")
    remote.add_argument("remote_args", nargs=argparse.REMAINDER)
    remote.set_defaults(func=remote_lane)
    return parser


def main() -> None:
    os.umask(0o077)
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
