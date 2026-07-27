# Repository layout

- `crates/kernform-core/`: pure types, resolution, plans, diagnostics, and conformance
- `crates/kernform-engine/`: controlled effects, transactions, application services, and providers
- `crates/kernform-python/`: private PyO3 exposure
- `python/kernform/`: public Python API, command parsing, and renderers
- `schemas/`: canonical v2 JSON Schemas plus explicit legacy migration input
- `capabilities/`: versioned composable capability manifests
- `signatures/`: SDK, CLI, API, interactive-web, and daemon signature manifests
- `templates/`: deterministic static resources with restricted placeholders
- `containers/`: rootless Podman build and runtime inputs
- `shell/`: separate human and agent Nushell modules
- `fixtures/`: valid, invalid, failure, and catalog inputs
- `reference/`: generator-derived single-signature outputs
- `tests/`: Python contract, boundary, integration, and acceptance tests
- `docs/`: architecture, decisions, development, history, signatures, and standards

Generated outputs never become a second source of truth. Signature and capability manifests plus
templates remain canonical.
