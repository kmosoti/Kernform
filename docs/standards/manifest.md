# Manifest contract

`kernform.toml` uses schema marker `kernform.project-form/v2`. It separates generator version from
the identity and topology of the project being generated. Closed fields reject unknown values.

The manifest locks these defaults:

- `project.requested_signatures` contains one or more of `sdk`, `cli`, `api`,
  `interactive-web`, or `daemon`
- `project.resolved_signatures` records the deterministic dependency closure
- `runtime.default_signature` selects the executable surface when a composition has more than one
- local Git is enabled on `main`, without an initial commit or remote
- versions follow `newest-stable-exact` and reject prereleases
- container execution is rootless Podman
- web JavaScript policy is `none`

Signature or capability order in input is not execution order. Kernform validates composition,
resolves dependencies, and emits one deterministically sorted capability graph and scaffold plan.
