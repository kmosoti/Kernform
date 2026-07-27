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

## Publication boundary

Kernform does not automate deployment, tag creation, or publication through GitHub Actions.
`release build` creates the immutable local bundle, and `release finalize` freezes its verified
local state without publishing it. Any later publication is a separate operator-controlled action
outside Kernform's repository workflows and must use that exact finalized bundle without
rebuilding it.
