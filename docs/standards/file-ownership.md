# File ownership

Kernform records exactly five ownership values in `.kernform/state.json`:

- `managed`: Kernform may apply a declared semantic update when the recorded hash still matches.
- `seeded`: Kernform writes the initial content once; the file becomes user-controlled afterward.
- `generated`: content is reproducible and may be replaced only when its current hash is known.
- `user`: Kernform observes but never writes the file.
- `external`: another system owns the path; Kernform neither writes nor adopts it.

`.git/` is always excluded. A changed precondition produces a conflict before mutation rather than
an overwrite or silent repair.
