# Plan operations

An immutable `kernform.plan/v1` contains only typed operations:

- `create_directory`
- `write_file`
- `patch_document` for structured JSON or TOML changes
- `run_command` with program, argv, cwd, explicit environment, and timeout
- `init_git_repository`
- `check`

Every operation has a stable ID. Mutating operations carry ownership or content-hash preconditions.
Plans embed the exact resolved catalog and are never re-resolved during apply.

Shell command strings and capability-provided scripts are not plan operations.
