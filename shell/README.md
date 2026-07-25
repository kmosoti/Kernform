# Shell interfaces

Human and agent Nushell surfaces are separate. Human mode loads ergonomic typed wrappers. Agent
mode exposes one `kf` wrapper that forces `kernform --agent`, parses the single JSON envelope, and
propagates the external exit code. On a terminal, human mode attaches the user's streams; agent and
non-terminal checks use deterministic closed input. Agent mode also uses an allowlisted
environment, no history, and a bounded timeout.
