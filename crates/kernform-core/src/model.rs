use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Canonical composable project signatures.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Signature {
    Sdk,
    Cli,
    Api,
    InteractiveWeb,
    Daemon,
}

impl std::fmt::Display for Signature {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let value = match self {
            Self::Sdk => "sdk",
            Self::Cli => "cli",
            Self::Api => "api",
            Self::InteractiveWeb => "interactive-web",
            Self::Daemon => "daemon",
        };
        formatter.write_str(value)
    }
}

/// File ownership values frozen for the v1 state contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Ownership {
    Managed,
    Seeded,
    Generated,
    User,
    External,
}

/// Local Git intent. Remote creation is intentionally not representable.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GitIntent {
    pub enabled: bool,
    pub initial_branch: String,
    pub initial_commit: bool,
}

impl Default for GitIntent {
    fn default() -> Self {
        Self {
            enabled: true,
            initial_branch: "main".to_owned(),
            initial_commit: false,
        }
    }
}

/// User intent after deterministic signature and capability resolution.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectIntent {
    pub name: String,
    pub requested_signatures: BTreeSet<Signature>,
    pub resolved_signatures: BTreeSet<Signature>,
    pub default_signature: Option<Signature>,
    pub capabilities: BTreeSet<String>,
    pub git: GitIntent,
}

/// One exact version catalog frozen into an immutable plan.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VersionCatalog {
    pub id: String,
    pub hash: String,
    pub resolved_at: String,
    pub source: String,
    pub versions: BTreeMap<String, String>,
    pub images: BTreeMap<String, String>,
}

/// Snapshot metadata for one observed repository file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotFile {
    pub hash: String,
    pub ownership: Option<Ownership>,
}

/// Side-effect-free representation of observed repository state.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(deny_unknown_fields)]
pub struct RepositorySnapshot {
    pub exists: bool,
    pub git: bool,
    pub primary_branch: Option<String>,
    pub files: BTreeMap<String, SnapshotFile>,
}

/// Fully rendered desired content supplied to the pure planner.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RenderedFile {
    pub path: String,
    pub content: String,
    pub ownership: Ownership,
}

/// Supported structured document formats.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentFormat {
    Json,
    Toml,
}

/// Explicit operations that may be executed by the engine.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Operation {
    CreateDirectory {
        id: String,
        path: String,
    },
    WriteFile {
        id: String,
        path: String,
        content: String,
        ownership: Ownership,
        expected_hash: Option<String>,
    },
    PatchDocument {
        id: String,
        path: String,
        format: DocumentFormat,
        patch: Value,
        expected_hash: String,
    },
    RunCommand {
        id: String,
        program: String,
        args: Vec<String>,
        cwd: String,
        environment: BTreeMap<String, String>,
        timeout_seconds: u64,
    },
    InitGitRepository {
        id: String,
        initial_branch: String,
    },
    Check {
        id: String,
        check: String,
    },
}

impl Operation {
    /// Stable operation identifier.
    #[must_use]
    pub fn id(&self) -> &str {
        match self {
            Self::CreateDirectory { id, .. }
            | Self::WriteFile { id, .. }
            | Self::PatchDocument { id, .. }
            | Self::RunCommand { id, .. }
            | Self::InitGitRepository { id, .. }
            | Self::Check { id, .. } => id,
        }
    }
}

/// Stable diagnostic severity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Info,
    Warning,
    Error,
}

/// Stable diagnostic envelope.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Diagnostic {
    pub id: String,
    pub severity: Severity,
    pub message: String,
    pub context: BTreeMap<String, Value>,
}

/// Immutable initialization or adoption plan.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub schema: String,
    pub plan_id: String,
    pub generator_version: String,
    pub intent: PlanIntent,
    pub catalog: VersionCatalog,
    pub operations: Vec<Operation>,
    pub diagnostics: Vec<Diagnostic>,
}

/// Intent projection frozen into the v2 plan schema.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlanIntent {
    pub name: String,
    pub requested_signatures: BTreeSet<Signature>,
    pub resolved_signatures: BTreeSet<Signature>,
    pub default_signature: Option<Signature>,
    pub capabilities: BTreeSet<String>,
    pub git: bool,
}

/// File recorded by managed state.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StateFile {
    pub path: String,
    pub hash: String,
    pub ownership: Ownership,
}

/// Catalog identity retained in managed state.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ToolchainState {
    pub catalog_id: String,
    pub catalog_hash: String,
}

/// Deterministic managed state written by the engine.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ManagedState {
    pub schema: String,
    pub generator_version: String,
    pub project_root: String,
    #[serde(default)]
    pub requested_signatures: BTreeSet<Signature>,
    #[serde(default)]
    pub resolved_signatures: BTreeSet<Signature>,
    #[serde(default)]
    pub default_signature: Option<Signature>,
    pub manifest_hash: String,
    pub toolchains: ToolchainState,
    pub files: Vec<StateFile>,
}

/// Stable command status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommandStatus {
    Success,
    Failure,
    Refused,
}

/// Command artifact reference.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Artifact {
    pub kind: String,
    pub path: String,
    pub hash: Option<String>,
}

/// Stable command result envelope shared by Rust, Python, and CLI output.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommandEnvelope {
    pub schema: String,
    pub command: String,
    pub status: CommandStatus,
    pub exit_code: u8,
    pub result: Value,
    pub diagnostics: Vec<Diagnostic>,
    pub artifacts: Vec<Artifact>,
}

/// Pure release-flow phase.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReleasePhase {
    Idle,
    Started,
    Verified,
    Finalized,
}

/// Pure release-flow state stored by the application layer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseState {
    pub version: String,
    pub branch: String,
    pub source_commit: String,
    pub catalog_hash: String,
    pub phase: ReleasePhase,
}
