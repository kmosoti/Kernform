# Signatures

Kernform 0.2.0 defines exactly five project signatures: `sdk`, `cli`, `api`, `interactive-web`, and
`daemon`. Signatures compose capabilities; they do not copy shared resources.

Signatures are compositional. For example, requesting `cli` resolves `sdk + cli`, requesting
`interactive-web` resolves `sdk + api + interactive-web`, and an explicit `sdk + cli + api`
request produces one merged plan. Kernform rejects incompatible executable combinations unless
`runtime.default_signature` selects the intended executable surface.

All signatures include exact Cargo/uv/toolchain locks, generated CI, testing, release metadata,
rootless Podman, and separate human/agent Nushell surfaces. SDK adds the reusable PyO3 boundary;
CLI adds stable rendering and completion; API adds Litestar/msgspec/Granian; interactive-web adds
packaged HTML/CSS without authored JavaScript; daemon adds lifecycle and supervision resources.
