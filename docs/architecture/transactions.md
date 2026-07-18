# Transaction model

## Purpose

Kernform publishes new projects atomically and adopts existing repositories without silently
overwriting content.

## New projects

The engine creates a uniquely named sibling staging directory, applies and validates the complete
immutable plan there, then publishes the destination with one same-parent rename. Any failure before
the rename removes only that transaction-owned staging tree. An existing destination is always a
precondition failure.

## Existing projects

Adoption acquires `.kernform/mutation.lock`, validates every content-hash precondition before the
first write, and records backups plus intended mutations under
`.kernform/transactions/<plan-id>/journal.json`. Each journal entry is durable before its mutation.
Failure restores backups and removes transaction-created files and empty directories in reverse
order. Recovery is explicit and repeatable.

Kernform preserves existing Git history, branches, remotes, configuration, and hooks. When a plan
creates a new local repository, rollback removes it only while the transaction-specific creation
marker is present. `.git/` is never included in managed state.

## State

After all operations succeed, `.kernform/state.json` records the exact catalog identity plus hashes
and ownership for generated resources. The immutable plan remains the sole version input during
apply; the executor never resolves versions or templates again.
