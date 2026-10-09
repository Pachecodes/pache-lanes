# Security model

Lanes run tools as your user and can spend provider credits. Do not use them on
untrusted repositories, prompts or production systems. SSH targets are empty
by default and each target must be explicitly enabled. OpenSSH host-key checking
is not disabled. Use verified SSH aliases and dedicated worker accounts.

State defaults outside Hermes to `~/.local/state/pache-lanes`; state roots inside
`.hermes`, home itself and `/` are refused. Runtime entry points set umask 077.
Lane names reject traversal and lane-directory symlinks. State and configuration
are trusted owner-controlled inputs, not a multi-user authorization database.
Keep them private; do not store them on a world-writable/shared filesystem.

No approval-bypass flag is enabled by default. Claude retains default permissions
for makers and plan mode for checkers. Codex uses workspace-write for makers and
read-only for checkers. `--allowed-tools` is explicit user permission (not a
sandbox) and may authorize shell effects; use it sparingly. Raw agent overrides
are rejected even if the legacy override environment variable is set. Copilot
retains explicit destructive-tool denials, but no allow-all-tools grant.
Hermes and Copilot checker lanes are refused because their enforcement is not
established here. Roles, repair counts and prohibitions are otherwise task-packet
governance, not OS isolation or a guaranteed spending cap. A blocked permission
prompt is safer than silently approving it. Inspect it and stop the lane.

Herdr session and tmux socket default to dedicated `pache-lanes` namespaces;
never point them at a shared gateway/session. Prune applies only inside the
private tmux socket; it does not clean arbitrary system sessions. Stop uses only
recorded workspace/session IDs. Remove refuses an unclosed Herdr workspace or
active tmux session and never force-closes unrelated workers.

`verify --cmd` deliberately executes your shell command, locally or remotely.
Only supply trusted commands. Worker output and exit markers are evidence, not
proof against a malicious agent: a worker can print a fake sentinel. Independently
inspect diffs and run tests before integration. Remote follow-up sends/resume are
not offered, avoiding stale completion markers and duplicate writer launches.

For issues, privately contact the repository maintainer using the eventual
hosting platform's private security-reporting channel. If unavailable, open an
issue containing only a minimal non-sensitive description and request private
contact; never publish credentials, runtime prompts, logs or production data.
