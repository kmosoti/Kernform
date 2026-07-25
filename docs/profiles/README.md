# Profiles

Kernform 0.1.0 defines exactly three profiles: `library`, `cli`, and `api`. Profiles compose
capabilities; they do not copy shared resources. The API profile may add the optional `web-server`
capability.

All profiles include exact Cargo/uv/toolchain locks, generated CI, testing, release metadata,
rootless Podman, and separate human/agent Nushell surfaces. Library adds the reusable PyO3 boundary;
CLI adds stable rendering and completion; API adds Litestar/msgspec/Granian. Web resources are
packaged with the Python module so installed wheels and runtime containers serve the same HTML/CSS.
