# Pache Lanes

Standalone extraction of the **actual Pachebot lane tooling**, not a mock agent
runner. Coordinate maker/checker task packets, finite local tmux workers,
interactive Herdr workers, and experimental finite Claude workers over SSH.
MIT licensed; see [NOTICE.md](NOTICE.md) for original attribution.

## Install

Python 3.10+; runtime package has no Python dependencies. From this checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
pache-lane --help
pache-lane create --help
pache-remote-lane --help
pache-lane --version
```

Installing creates `pache-lane` and `pache-remote-lane` only in the selected
Python environment. It does not install, configure or log into any agent CLI,
change Hermes, start a gateway, or enable remote access. Keep the original and
standalone commands in separate PATH environments to avoid confusing them.

Runtime requirements:

- Local tmux: POSIX shell + tmux + selected authenticated agent CLI on PATH.
- Local Herdr: running **dedicated** Herdr session, CLI and agent on PATH. The
  expected JSON protocol is Herdr 0.9.0 (`workspace create`, `agent start`,
  `agent prompt --wait`, `agent get/read`, `workspace close`). Herdr does not
  come bundled. Set up/start its dedicated session using Herdr's documentation;
  this package does not attach to or create your existing/shared gateway.
- SSH remote: POSIX host with SSH server, sh, python3, git, Herdr 0.9.0 CLI and
  dedicated session, authenticated Claude CLI. User-local binaries in
  `~/.local/bin` are included in the remote PATH. Other toolchain paths must be
  configured on the host. Remote repo must already exist as an absolute path.
- `verify`: git plus every project-specific executable named in your checks.

Agent subscriptions/API billing are your responsibility. Authenticate agent
CLIs using their own instructions **before** launching real lanes. No account,
provider, model alias, personal hostname or login is embedded.

## Safe first run (no worker, no network)

Dry-run creates only the packet and private metadata; it does not probe auth,
call Herdr/tmux, run a model, contact SSH, or spend credits.

```sh
pache-lane create packet-demo --repo "$PWD" --agent claude \
  --role maker --prompt-file examples/maker.md --dry-run
pache-lane list --json
pache-lane status packet-demo --json
pache-lane read packet-demo --log
pache-lane stop packet-demo
pache-lane remove packet-demo
```

Default state: `~/.local/state/pache-lanes/{local,remote}/<lane>/`. Override with
`PACHE_LANES_STATE_DIR=/absolute/dedicated/directory`. No live Hermes state is
read or written. Even environment overrides inside `.hermes` are refused.
Runtime prompts, output, events, exit files and verification evidence are
private local state, not repository assets. Don't upload them to public issues.

Optional user-owned JSON config defaults to
`~/.config/pache-lanes/config.json`; select another with `PACHE_LANES_CONFIG`.
Copy `examples/config.json` yourself; nothing auto-installs it. Environment state
root takes precedence over config `state_dir`. Herdr session names are configured
with `herdr_session` and `remote_herdr_session`, default `pache-lanes`. Tmux uses
a dedicated owner-controlled `-S <state>/tmux/server.sock`, never the default
or historical `-L pache-lanes` socket. `PACHE_LANES_HOME` is a state-root alias
with precedence over `PACHE_LANES_STATE_DIR`, then config `state_dir`.

### First tmux initialization (explicit, no agent/network)

```sh
# Select a NEW dedicated state directory, outside Hermes. Use the same value thereafter.
export PACHE_LANES_HOME="$HOME/.local/state/pache-lanes"
pache-lane tmux-init
# Harmless finite printf worker for a local readiness check:
pache-lane create inert-check --backend tmux --agent noop --repo "$PWD" --prompt inert
pache-lane status inert-check --json
pache-lane read inert-check --log
pache-lane stop inert-check
pache-lane remove inert-check
```

`tmux-init` exclusively reserves a private mode-0700 transport directory and
starts tmux with `/dev/null` configuration, a bounded bootstrap sleep, an owner
nonce, and `exit-empty off`. It verifies ownership and removes the bootstrap.
The empty server intentionally stays alive after the last worker completes or is
stopped: connected empty inventory provides real absence readback. No idle
worker shell is retained. Socket device/inode, owner UID, directory/file privacy,
server nonce and empty-server policy are verified before tmux operations. Each
new lane is bound to that server nonce; legacy/unbound metadata is refused.

Initialization refuses any existing transport directory (even inaccessible,
failed or apparently stale) and any prior tmux lane evidence. It never unlinks,
overwrites, adopts or restarts an old server. A missing/moved socket, changed
ownership/policy, unavailable tmux or ambiguous response blocks create, status,
stop and remove without changing existing lane evidence. Missing socket is
**not** proof that a server or worker exited. Restore the exact original owned
transport before retrying; there is deliberately no automatic recovery/reset or
force-remove. Do not delete ownership state to bypass these guards. Prior
`-L pache-lanes` workers require separate owner-led reconciliation; this release
does not contact them or certify their termination.

Use a short state path (socket path at most 100 encoded bytes); root must be
owner-controlled mode 0700. Failed initialization retains its reservation for
manual investigation. Same-UID hostile tampering, daemonized worker descendants,
OS sandboxing, paid agents and other tmux versions are not certified. Session
absence proves tmux session removal, not arbitrary descendant-process teardown.
No production server-shutdown/recovery command is shipped. The disposable test
fixtures explicitly kill only nonce/socket-verified owned servers and verify
their recorded PIDs exited before cleaning state.

## Local maker → independent checker

Use an isolated git worktree; Pache Lanes does not create or merge worktrees.
Only one maker writes to each worktree. Set precise objectives and editable scope
in the prompt. Choose a model available in your own CLI; no silent substitution.
The following commands **launch real workers and may incur costs**:

```sh
pache-lane create feature-maker --repo /absolute/path/to/worktree \
  --backend tmux --agent claude --role maker \
  --prompt-file examples/maker.md \
  --verification-cmd 'python -m unittest discover -s tests -v' --max-turns 20
pache-lane status feature-maker --json
pache-lane read feature-maker --log --lines 100
pache-lane verify feature-maker --cmd 'python -m unittest discover -s tests -v'
# Only after maker settles and you independently inspect its diff:
pache-lane create feature-checker --repo /absolute/path/to/worktree \
  --backend tmux --agent claude --role checker \
  --prompt-file examples/checker.md --max-turns 10
pache-lane read feature-checker --log
pache-lane verify feature-checker --cmd 'python -m unittest discover -s tests -v'
pache-lane stop feature-maker
pache-lane stop feature-checker
# Preserve evidence you need, then:
pache-lane remove feature-maker
pache-lane remove feature-checker
```

`verify` always executes `git status --short --untracked-files=all`,
`git diff --name-only`, `git diff --check` and repeated `--cmd` values; it writes
`verify.json` and exits nonzero if any check fails. A clean exit is not proof your
acceptance criteria were tested. Packet `--verification-cmd` values tell the
worker what to run; parent-side verify requires your explicit `--cmd` values.

Claude checker/planner uses plan mode; Codex checker uses read-only sandbox.
These are runtime permission policies, not OS isolation. Maker Claude keeps
its normal permission mode, so unattended jobs may block for approval. No unsafe
bypass is auto-added. Explicit `--allowed-tools` grants are your decision and
may allow powerful shell commands. For typed Claude reference roots, repeat
`--add-dir`; this is access expansion, not guaranteed read-only mounting. Codex
maker defaults to workspace-write; `--sandbox read-only` is available. Do not
use worker-readable production credentials or unrestricted SSH agents.

`--backend auto` prefers Herdr, then tmux (Copilot prefers tmux). For Herdr use
`--backend herdr` only after setting up a dedicated session. Herdr supports
`pache-lane send NAME 'follow-up'` through atomic prompt transition wait.
Finite print-mode tmux lanes **do not** support send or resume: create a new lane
after collecting output and proving the first worker has exited. Tmux logs its
true exit code and the session exits, without leaving a login shell behind.

`stop` snapshots Herdr output and closes the exact recorded workspace, or kills
the named session inside the private tmux socket. `remove` refuses active
workers/unclosed Herdr workspaces. There is no force-remove/replace option.
`prune` previews detached shell-only sessions in the private socket; `prune
--apply` removes only candidates with matching server-bound lane metadata and
verified absence afterward; unknown sessions are refused, not adopted. `cmux-help` is an optional manual cockpit
reference only; `--backend cmux` records a manual packet, **does not launch a
worker**, and must not be mistaken for automated execution.

## Remote POSIX Claude lanes (experimental)

First configure and verify SSH independently, without disabling host-key checks:

```sh
ssh my-worker 'command -v python3; command -v herdr; command -v claude'
ssh my-worker 'herdr --version; claude auth status --text'
```

Add `worker` with `target: "my-worker"`, `platform: "posix"`, `enabled: true` to
your config only after reviewing the worker/account. All example targets
(including localhost) ship **disabled**. Use a dedicated SSH account/session.
SSH host/user/port/identity settings belong in your own `~/.ssh/config`; targets
accept only a hostname or SSH alias, never option strings or shell snippets.

```sh
pache-remote-lane create remote-packet --machine worker --repo /srv/project \
  --role checker --prompt-file examples/checker.md --dry-run
pache-remote-lane status remote-packet
pache-remote-lane remove remote-packet
# Real paid worker after explicit target opt-in:
pache-lane remote create remote-maker --machine worker --repo /srv/project \
  --role maker --prompt-file examples/maker.md \
  --verification-cmd 'npm test'
pache-lane remote status remote-maker
pache-lane remote read remote-maker --lines 100
pache-lane remote verify remote-maker --cmd 'npm test'
pache-lane remote stop remote-maker
pache-lane remote remove remote-maker
```

The remote backend uses SSH batch mode → Herdr workspace/pane → a finite Claude
print command. Packets are uploaded privately outside the repository to
`~/.local/share/herdr/pache-lanes/<name>/prompt.md`; they remain on the worker
for owner-managed retention. Pane completion requires a standalone exit marker;
transport failure is `unknown`, not success. Marker spoofing is possible by an
untrusted worker. Read output and independently inspect/test changes; **do not
merge on marker or agent self-report alone**. Stop before removing local metadata.
Remote send/resume is intentionally absent (recreate a new bounded lane).

## Compatibility / release scope

| Capability | This release |
|---|---|
| Local Claude, Codex, Herdr/tmux lifecycle | Private tmux cold/finite/last-stop lifecycle tested with real inert workers; Herdr offline protocol + installed CLI smoke tested |
| Local Hermes, Copilot launch adapters | Experimental; flags retained except unsafe Copilot allow-all removed; not real-worker tested; may wait for approval |
| Maker/checker packet, role/risk/repair handoff | Retained; max-repairs is prompt governance, not automatic repair scheduling |
| Claude/Codex checker enforcement | Plan/read-only mode; no checker for Hermes/Copilot |
| Remote POSIX Claude | Experimental generalized SSH/Herdr implementation; fixture tested, no live host E2E |
| Windows/PowerShell remote, AGY/OpenCode/remote Hermes | Not shipped/supported; historical integrations require separate runtime-specific validation |
| `pache_reflex`/Jev shadow routing | Disabled (`--reflex-mode off` only); optional import chain excluded, no hidden telemetry/network request |
| pache-graph, tgrep servers, private Forgejo worktrees | Not shipped; provision your own worktree/search tools; no personal infrastructure helper invoked |
| Resume, forced replace, raw CLI override | Removed: old resume was not reliable session continuation; prevents duplicate writers and bypasses |
| cmux | Manual-only reference; not an automation transport |

Herdr 0.9.0 help/version was inspected on the extraction host, and fixture tests
exercise expected JSON contracts. **No authenticated worker was launched for
this release**. Compatibility with other Herdr/agent versions, provider/model
availability, paid-worker completion and Windows are not certified. CLI defaults
can change upstream. Inspect your installed versions and permission behavior in
a disposable explicitly authorized environment before using real tasks.

## Tests

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v
# After pip install, validate installed entry points and fixture lifecycle:
python tests/installed_smoke.py
# With tmux installed: real isolated server + finite printf worker (no agents/network):
python tests/installed_tmux_smoke.py
```

Tests use checkout-local ephemeral state and fixture/mock transports; the tmux
private-lifecycle tests also use real unique disposable servers (skip if tmux is
not installed). The installed tmux smoke requires tmux and never skips. No
`~/.hermes` access, SSH network call, gateway mutation or paid worker. The
installed smoke runs real installed commands and git only, not agents. CI runs
these gates on Linux/macOS with Python 3.10/3.12; a workflow file is not a claim
that hosted CI has already run. See [SECURITY.md](SECURITY.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).
