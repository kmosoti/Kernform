# Kernform

Kernform 0.1.0 is a deterministic local project lifecycle initializer for Python/Rust projects.
It composes versioned capabilities, emits an immutable plan, applies it transactionally, and never
overwrites user-owned content.

The 0.1.0 schemas, command envelope, profile names, ownership classes, diagnostic IDs, and local
release flow are frozen. Publication remains a separate explicit operation.

## Quick start

From this repository:

```console
$ uv sync --all-groups --frozen
$ uv run kernform --agent init example --profile api --with web-server
$ cd example
$ git symbolic-ref --short HEAD
main
$ git remote
$ git rev-parse --verify HEAD
fatal: Needed a single revision
$ uv sync --all-groups --frozen
$ cargo test --workspace --locked
$ uv run pytest
```

Initialization creates an unborn local `main` branch by default. It creates no commit, remote,
forge repository, tag, or release. Repeating the exact initialization produces zero operations.

## Profiles

| Profile | Adds | Optional extension |
| --- | --- | --- |
| `library` | typed Python SDK, private PyO3 extension, pure Rust core | — |
| `cli` | library base, stable human/JSON/NUON CLI, completion | — |
| `api` | library base, Litestar/msgspec API, Granian runtime | `web-server` |

Every profile includes exact Cargo/uv locks, generated CI, rootless Podman assets, separate human
and agent Nushell configuration, tests, and local release metadata. `web-server` packages
server-rendered HTML/CSS and contains no authored JavaScript or Node artifact.

## Commands

```text
kernform init | adopt | scaffold
kernform inspect | check | doctor
kernform versions inspect | check | plan | update
kernform test fast | full | deep
kernform container build | run | inspect | test
kernform dev up | down | reset | logs
kernform shell human | agent
kernform release start | inspect | verify | build | finalize
```

`--agent` selects single-line `kernform.command/v1` JSON, disables interaction, and preserves stable
exit classes: usage `1`, state/conformance `2`, environment/process `3`, internal `4`, and policy
refusal `5`. `--format human|json|nuon` selects rendering explicitly.

## Architecture

```text
CLI / typed Python API
          |
          v
private PyO3 adapter
          |
          v
kernform-core       pure models, resolution, planning, conformance
          |
          v
kernform-engine     controlled filesystem, process, Git, and provider effects
```

Process execution is program plus argv; shell command strings are not a supported boundary. New
projects publish from sibling staging directories. Adoption uses a durable journal, backups,
preconditions, rollback, and recovery. Kernform never owns `.git/`.

## Verification and release

`kernform test fast` is the ordinary cross-language gate. `full` adds clean wheel/sdist builds,
profile regeneration/install/idempotence, and the rootless Podman matrix. `deep` adds release-mode
stress/property checks and explicitly reported optional fuzz, Miri, mutation, audit, and security
tools. See [verification](docs/development/verification.md) and the reproducible
[0.1.0 acceptance flow](docs/development/acceptance.md).

The release build promotes one exact wheel, source distribution, and OCI archive with checksums,
SPDX SBOM, and in-toto/SLSA provenance. It never rebuilds in the publication job. See the
[release flow](docs/development/release-flow.md) and [deferred work](docs/development/deferred.md).

## Repository map

- `crates/`: pure core, effectful engine, and thin PyO3 adapter
- `python/kernform/`: typed public API, CLI, and bounded orchestration
- `schemas/`: closed v1 manifest, state, plan, and command contracts
- `capabilities/`, `profiles/`, `templates/`: canonical generation inputs
- `containers/`, `shell/`: rootless Podman and separated Nushell surfaces
- `fixtures/`, `reference/`, `tests/`: evidence, derived projects, and maintained gates
- `docs/`: architecture, standards, decisions, development guidance, and retained history

The active tree is Kernform-only; pre-reform context remains isolated under `docs/history/` and in
Git history.
