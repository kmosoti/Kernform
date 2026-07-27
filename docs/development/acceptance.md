# Kernform 0.2.0 acceptance

## Repository gate

```console
uv sync --all-groups --frozen
uv run kernform --agent check
uv run kernform --agent versions check
uv run kernform --agent test fast
uv run kernform --agent test full
```

The full tier regenerates and builds `sdk`, `cli`, `api`, `interactive-web`, and `daemon`; installs
from exact Cargo and uv locks; checks the unborn `main`/no-remote defaults; repeats initialization
with zero operations; builds clean wheel/source artifacts; and exercises rootless Podman CI/runtime
targets. On the required release baseline, Podman must report `host.security.rootless=true`.

## Defining generated-project case

Run from the Kernform checkout:

```console
workdir=$(mktemp -d)
uv run kernform --agent init example \
  --destination "$workdir/example" \
  --signature interactive-web \
  --default-signature interactive-web
git -C "$workdir/example" symbolic-ref --short HEAD
git -C "$workdir/example" remote
git -C "$workdir/example" rev-parse --verify HEAD
cargo test --manifest-path "$workdir/example/Cargo.toml" --workspace --locked
uv sync --directory "$workdir/example" --all-groups --frozen
uv run --directory "$workdir/example" pytest
uv run kernform --agent check "$workdir/example"
uv run kernform --agent init example \
  --destination "$workdir/example" \
  --signature interactive-web \
  --default-signature interactive-web
uv run kernform --agent container test --path "$workdir/example"
```

Expected invariants are `main`, no remote, no valid `HEAD`, passing locked builds/tests, a second
`operation_count` of zero, rootless container execution, working `/health` and `/`, and no `.js`,
`.mjs`, `.cjs`, `package.json`, `<script>`, or inline event handler in generator-owned output.

## Durable evidence

- `tests/contracts`: frozen schemas, enumerations, diagnostics, and command grammar
- `tests/signatures` and `tests/reference`: composition, conflict rejection, clean
  build/install/idempotence, and exact regeneration
- `tests/python/test_lifecycle.py`: compile, check, apply, adopt, and explicit v1 migration
- `tests/containers` and `tests/shell`: runtime isolation and host-dependent evidence
- `tests/git_release` and `tests/ci_release`: local release state and immutable artifact promotion
- `reference/*`: five derived review projects, including exact locks and CI

No commit, tag, push, release, or remote metadata mutation is part of repository acceptance.
