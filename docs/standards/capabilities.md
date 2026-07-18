# Capability contract

Each versioned `capability.toml` declares an ID, version, requirements, conflicts, files, structured
patches, tests, and conformance rules. Capability resources are static and deterministic.

Allowed placeholders are explicitly named by the renderer. Unknown placeholders, absolute output
paths, parent traversal, shell strings, inline scripts, and undeclared resources are rejected before
mutation.

Capabilities form an acyclic dependency graph. Unknown nodes, conflicts, and cycles are diagnostics,
not partial generation results.
