# Verification

## Maintained tiers

Tier membership is emitted without execution by `kernform --agent test <tier> --plan`.

- `fast`: Rust format, Clippy, unit/doc tests; Python format, lint, strict types, unit, contract,
  boundary, scaffold, and deterministic-planner tests.
- `full`: fast static gates plus all non-deep Python tests, four clean generated-profile builds,
  exact-lock installs, idempotence, clean wheel/sdist verification, and the rootless Podman matrix.
- `deep`: full plus release-mode Rust tests, stress/property/performance canaries, and optional
  fuzz, Miri, mutation, dependency-audit, and security tools. Missing optional tools are reported as
  skipped with their exact program name.

Run focused checks first, then:

```console
uv sync --all-groups --frozen
uv run kernform check
uv run kernform test fast
```

For generation, installation, container, release, or cross-surface changes:

```console
uv run kernform test full
```

The Linux x86_64 release baseline requires rootless Podman. Nushell is optional on a host; when it
is absent, maintained shell tests retain an explicit skip reason while still validating quoting,
timeouts, environment isolation, config paths, and exit propagation.

Equivalent direct repository gates are:

```console
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-features --locked
uv run ruff check python tests
uv run ruff format --check python tests
uv run pyright
uv run pytest
git diff --check
```
