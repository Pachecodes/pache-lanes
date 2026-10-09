# Attribution and provenance

Derived from the actual Pachebot `pache-lane` 0.6.0 and `pache-remote-lane`
0.7.0 scripts by Jesus / Pachebot and contributors. Local packet generation,
agent command assembly, tmux exit accounting and Herdr lifecycle were adapted,
not replaced with a demonstration-only implementation. Remote flat-name
validation, private packet upload, SSH quoting, Herdr pane reads and verification
were retained and generalized for user-configured POSIX targets.

The standalone extraction and safety changes are distributed under MIT by the
source owner's release instruction. No third-party agent runtimes or Herdr code
are bundled; those programs retain their own licenses and terms.

The optional `pache_reflex` import chain was traced (router → client, policy,
schemas, telemetry). It is not required for lane execution and is deliberately
excluded with shadow routing unsupported in this release. No authentication,
logs, lane state, prompts, session transcripts or private Forgejo payloads were
copied. Personal host maps, package-manager PATH pins, account namespaces,
Forgejo provisioning and graph/search helper integrations were removed.
