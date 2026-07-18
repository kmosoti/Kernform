# Repository layout

- `crates/kernform-core/`: pure types, resolution, plans, diagnostics, and conformance
- `crates/kernform-engine/`: controlled effects, transactions, application services, and providers
- `crates/kernform-python/`: private PyO3 exposure
- `python/kernform/`: public Python API, command parsing, and renderers
- `schemas/`: canonical v1 JSON Schemas
- `capabilities/`: versioned composable capability manifests
- `profiles/`: library, CLI, and API profile manifests
- `templates/`: deterministic static resources with restricted placeholders
- `containers/`: rootless Podman build and runtime inputs
- `shell/`: separate human and agent Nushell modules
- `fixtures/`: valid, invalid, failure, and catalog inputs
- `reference/`: generator-derived profile outputs
- `tests/`: Python contract, boundary, integration, and acceptance tests
- `docs/`: architecture, decisions, development, history, profiles, and standards

Generated outputs never become a second source of truth. Profile and capability manifests plus
templates remain canonical.
