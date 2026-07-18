# Manifest contract

`kernform.toml` uses schema marker `kernform/v1`. It separates generator version from the version of
the project being generated. Closed fields reject unknown values.

The manifest locks these defaults:

- profile is `library`, `cli`, or `api`
- local Git is enabled on `main`, without an initial commit or remote
- versions follow `newest-stable-exact` and reject prereleases
- container execution is rootless Podman
- web JavaScript policy is `none`

Capability order in input is not execution order. Kernform resolves dependencies and emits one
deterministically sorted capability graph.
