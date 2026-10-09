# Contributing

Use Python 3.10+ and a disposable checkout. Install with `python -m pip install .`
and run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`.
Tests create checkout-local temporary fixture state, mock external transports,
and never launch authenticated agents. Add negative boundary tests before fixes.

Keep config, prompts, state, credentials and logs out of commits. Do not add a
personal hostname, fixed username or deployment policy. New runtimes/backends
must document their tested CLI protocol/version, permissions, lifecycle and
limitations. Never claim mocked transport tests prove a paid-worker E2E. Real
worker tests require explicit authorization, budgets and disposable worktrees;
keep them out of default CI. No auto-push, auto-deploy or unsafe approval bypass.
