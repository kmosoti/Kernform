# AGENTS.md

## Repository identity

Kernform is a bounded Python/Rust project lifecycle initializer. It creates, adopts, validates,
tests, containers, and prepares releases for deterministic generated projects.

Do not turn this repository into a hosted service, forge orchestrator, plugin runtime, arbitrary
script runner, deployment platform, or general template collection.

## Architecture boundaries

- `crates/kernform-core/`: pure decisions, typed models, schemas, capability resolution, plans,
  diagnostics, conformance, ownership, and release state. No filesystem, process, network, output,
  or PyO3 dependencies.
- `crates/kernform-engine/`: controlled filesystem, process, Git, provider, transaction, container,
  and application effects. Commands are program plus argv, never shell strings.
- `crates/kernform-python/`: PyO3 conversion and exposure only.
- `python/kernform/`: typed public Python API, CLI parsing, renderers, and interaction policy.
- `schemas/`: canonical v1 contracts. Contract changes require fixture and compatibility review.
- `capabilities/`, `profiles/`, `templates/`: declarative generation inputs. They cannot execute
  arbitrary scripts or escape declared destinations.

## Locked behavior

- Local Git is the default, with initial branch `main` and no initial commit or remote.
- Plans are immutable between resolution and apply.
- User and external files are never overwritten. `.git/` is never owned by Kernform.
- Stable exact versions and OCI digests are required; prereleases and floating tags are rejected.
- Web capability output contains server-rendered HTML/CSS and no JavaScript or Node artifacts.
- Human and agent Nushell modes are separate; agent mode never prompts.
- Release artifacts are built once per exact source commit and promoted without rebuilding.

## Change workflow

Before editing, inspect the relevant issue, dependency edges, affected contracts, tests, branch,
status, and current diff. Keep one work-package concern per change and do not modify downstream
contracts casually. Structural work precedes additive work.

Use small typed boundaries, explicit errors, deterministic ordering, injectable effects, and
black-box tests. Do not add dependencies without a concrete boundary benefit.

## Verification

Run focused checks first. The maintained repository gate is documented in
`docs/development/verification.md`. At minimum, run formatting, linting, type checks, Rust tests,
Python tests, `kernform check`, and the appropriate `kernform test` tier for the changed surface.

Do not commit, push, tag, publish, deploy, or mutate remote metadata unless explicitly requested.
