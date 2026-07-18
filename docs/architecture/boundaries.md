# Architecture boundaries

Kernform follows one dependency direction:

```text
Python CLI/API -> PyO3 adapter -> engine application services -> pure core
```

Core returns typed decisions. The engine obtains snapshots and version catalogs, executes structured
operations, and returns typed results. The adapter converts those results without changing policy.
The CLI parses and renders; it does not plan or mutate directly.
