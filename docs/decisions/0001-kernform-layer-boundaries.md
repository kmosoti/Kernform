# 0001: Kernform layer boundaries

## Status

Accepted.

## Context

Project initialization combines pure policy with high-risk filesystem, process, Git, and network
effects. Mixing those concerns makes replay, testing, and recovery unreliable.

## Decision

Use a pure `kernform-core`, an effectful `kernform-engine`, a thin private PyO3 adapter, and a public
Python API/CLI. All effect requests are typed operations. Shell command strings are forbidden.

## Consequences

Core behavior is black-box testable. Effects can be replaced with fakes. Python and CLI callers use
the same application services. Boundary conversion remains explicit maintenance work.
