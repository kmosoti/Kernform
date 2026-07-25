# Reference projects

Reference projects are regenerated from canonical profiles, capabilities, catalogs, and templates.
Do not edit generated references manually.

The four derived directories are `library`, `cli`, `api`, and `api-web`. Each is the exact output of
one `kernform init --no-git` call from an absent destination. `tests/reference` regenerates all four
into temporary directories and compares every byte, including managed state, locks, CI, containers,
and shell resources.
