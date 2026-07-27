# Reference projects

Reference projects are regenerated from canonical signatures, capabilities,
catalogs, and templates. Do not edit generated references manually.

The five derived directories are `sdk`, `cli`, `api`, `interactive-web`, and
`daemon`. Each is the exact output of one `kernform init --no-git` operation
from an absent destination. `tests/reference` regenerates them in temporary
directories and compares every byte, including managed state, locks, CI,
containers, daemon lifecycle resources, and shell resources.
