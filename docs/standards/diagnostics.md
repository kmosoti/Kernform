# Diagnostic registry

Stable diagnostic IDs use `KF-<FAMILY>-<NNN>` and include severity, message, and structured context.
The first reserved IDs are:

| ID | Boundary |
|---|---|
| `KF-ARCH-001` | Architecture or dependency direction |
| `KF-BOUNDARY-001` | Adapter or process boundary |
| `KF-GIT-001` | Local Git prerequisite or invariant |
| `KF-VERSION-001` | Version, catalog, or digest policy |
| `KF-ENV-001` | Host tool or environment |
| `KF-TEST-001` | Test-tier or matrix contract |
| `KF-WEB-001` | No-JavaScript web policy |
| `KF-OWNERSHIP-001` | File ownership or precondition conflict |
| `KF-STATE-001` | State, journal, lock, or recovery |
| `KF-INTERNAL-001` | Unexpected internal failure |

New meanings require new IDs. Messages may become clearer without changing the identity or context
shape of an existing diagnostic.
