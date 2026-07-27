# Kernform

Kernform 0.2.0 is a deterministic project-form compiler and local lifecycle tool for hybrid
Python/Rust projects. Typed project intent becomes an immutable, agent-readable scaffold plan;
filesystem, process, Git, and container effects remain in the imperative shell. Kernform never
silently overwrites user-owned content.

The v2 project-form, plan, state, migration-plan, and command schemas are closed contracts.
Provider or model behavior is intentionally outside Kernform: agents may supply project-form JSON,
but the native kernel owns signature expansion, capability closure, conflict detection, ownership,
diff planning, and deterministic emission.

## Quick start

Compile a project form without writing a project:

```console
$ uv sync --all-groups --frozen
$ uv run kernform --agent compile --form fixtures/contracts/valid/kernform.json
{"artifacts":[],"command":"compile",...,"schema":"kernform.command/v2","status":"success"}
```

Initialize a compositional `sdk + cli` project:

```console
$ workdir=$(mktemp -d)
$ uv run kernform --agent init example \
    --destination "$workdir/example" \
    --signature sdk \
    --signature cli \
    --default-signature cli
$ uv run kernform --agent check "$workdir/example"
```

Initialization creates an unborn local `main` branch by default. It creates no commit, remote,
forge repository, tag, or release. Repeating the exact initialization produces zero operations.

## Composable signatures

| Signature | Adds |
| --- | --- |
| `sdk` | typed Python SDK, private PyO3 extension, pure Rust core |
| `cli` | stable human/JSON/NUON CLI over the SDK |
| `api` | Litestar/msgspec API and Granian runtime over the SDK |
| `interactive-web` | server-rendered HTML/CSS over the API; no authored JavaScript |
| `daemon` | long-running service lifecycle and supervision resources |

Signatures compose rather than select mutually exclusive templates. For example, `cli` resolves
with `sdk`, while `interactive-web` resolves with `sdk + api`. Ambiguous executable combinations
must declare `--default-signature`; incompatible combinations fail before emission. Declarative
manifests under `signatures/` remain the human-readable contract, while the Rust resolver is the
runtime authority.

## Lifecycle commands

```text
kernform compile --form FILE|-
kernform init | adopt | migrate plan | migrate apply | scaffold
kernform inspect | check | doctor
kernform versions inspect | check | plan | update
kernform test fast | full | deep
kernform container build | run | inspect | test
kernform dev up | down | reset | logs
kernform shell human | agent
kernform release start | inspect | verify | build | finalize
```

`adopt` and `migrate apply` require explicit confirmation. A v1 manifest is readable only through
the migration flow; Kernform does not silently reinterpret it as v2. `--agent` selects single-line
`kernform.command/v2` JSON, disables interaction, and preserves stable exit classes: usage `1`,
state/conformance `2`, environment/process `3`, internal `4`, and policy refusal `5`.
`--format human|json|nuon` selects rendering explicitly.

## Architecture

```text
Python CLI / typed SDK                 imperative shell
            |
            v
private coarse PyO3 bridge             JSON request/result boundary
            |
            v
kernform-core                          pure contracts and plan model
            |
            v
kernform-engine                        signature resolution, diffing, ownership,
                                       transactions, and controlled adapters
```

Process execution is program plus argv; shell command strings are not a supported boundary. New
projects publish from sibling staging directories. Adoption uses a durable journal, backups,
preconditions, rollback, and recovery. Kernform never owns `.git/`.

## Verification and release

`kernform test fast` is the ordinary cross-language gate. `full` adds clean wheel/sdist builds,
five signature regeneration/install/idempotence cases, and the rootless Podman matrix. `deep` adds
release-mode stress/property checks and explicitly reported optional fuzz, Miri, mutation, audit,
and security tools. See [verification](docs/development/verification.md) and the reproducible
[0.2.0 acceptance flow](docs/development/acceptance.md).

The release build promotes one exact wheel, source distribution, and OCI archive with checksums,
SPDX SBOM, and in-toto/SLSA provenance. It never rebuilds in the publication job. See the
[release flow](docs/development/release-flow.md) and [deferred work](docs/development/deferred.md).

## Repository map

- `crates/`: pure core, deterministic engine, and thin PyO3 adapter
- `python/kernform/`: typed public API, CLI, migration, and effect orchestration
- `schemas/`: closed v2 contracts plus read-only legacy migration schemas
- `signatures/`, `capabilities/`, `templates/`: canonical generation inputs
- `containers/`, `shell/`: rootless Podman and separated Nushell surfaces
- `fixtures/`, `reference/`, `tests/`: evidence, five derived projects, and maintained gates
- `docs/`: architecture, standards, decisions, development guidance, and retained history

The active tree is Kernform-only; pre-reform context remains isolated under `docs/history/` and in
Git history.
