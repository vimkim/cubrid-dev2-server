# Agent guidance

Use `just status`, `just plan`, and `just apply` for the container roster. Pass
exact names to `just apply`, or pass `--all` for the whole roster. Review the
plan before applying changes. Existing containers are preserved, including
stopped and drifted containers.

Use `just sync` for the locked Python environment and `just check` to run the
lock and CLI tests. The [README](README.md#run-containers) documents offline
fixtures, JSON output, sudo access, and partial provisioning failures. The
Ubuntu and CentOS example recipes are separate from the roster workflow.
