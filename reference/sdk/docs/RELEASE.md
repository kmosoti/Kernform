# Release flow

Start releases from clean `main` as `release/<version>`. Kernform freezes the exact catalog,
verifies source and artifact metadata, and treats tag creation and publication as explicit terminal
actions. There is no permanent `develop` branch.
