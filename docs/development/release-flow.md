# Release flow

Kernform uses `feature/`, `fix/`, `chore/`, `release/`, and `maintenance/` prefixes. There is no
permanent `develop` branch.

## Local state machine

1. `kernform release start <version> --yes` requires clean committed `main`, an unused
   `v<version>` tag, and a known source commit. It creates `release/<version>` and atomically updates
   Python metadata, Cargo metadata, `Cargo.lock`, `uv.lock`, and the Python version declaration.
2. Review and commit the version update. `release verify --metadata-matches --synchronized`
   requires the release branch, clean tree, known commit, and both evidence assertions.
3. `release build` requires verified state, runs the full tier, builds wheel and source distribution,
   exports the tested runtime image as OCI, and emits one immutable ZIP with checksums, SPDX SBOM,
   and in-toto/SLSA provenance.
4. `release finalize --verification-complete --yes` freezes local final state. It validates the
   future tag but deliberately creates no tag and performs no publication.

Signing defaults to disabled. When repository Git policy requires signing, resolved identity,
signing key, and signing capability must exist before mutation.

## GitHub workflow

`.github/workflows/release.yml` accepts an exact version and full source commit. Its build-once job
runs on the controlled `kernform-release` Linux x86_64 runner label with rootless Podman. The gated
publication job downloads that exact candidate and uses `gh release create --verify-tag`; it cannot
rebuild. Publication therefore also requires a separately created matching tag and the protected
`release` environment.

Actions are pinned by full commit ID. Candidate attestation uses short-lived GitHub OIDC; no
long-lived release credential is declared.
