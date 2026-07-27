//! Controlled effect adapters and application services for Kernform.

pub mod capability;
pub mod document;
pub mod error;
pub mod filesystem;
pub mod git;
pub mod process;
pub mod provider;
pub mod release;
pub mod signature;
pub mod snapshot;
pub mod transaction;
pub mod versioning;

pub use capability::{
    CapabilityFile, CapabilityManifest, CapabilityPatch, EmbeddedCapability, LoadedCapability,
    expand_placeholders, load_capabilities, render_capabilities, render_embedded_capabilities,
};
pub use document::{merge_json, merge_toml};
pub use error::EngineError;
pub use filesystem::{FileLock, atomic_write, hash_bytes};
pub use git::{GitClient, GitSnapshot};
pub use process::{CommandSpec, ProcessExecutor, ProcessResult, SystemProcessExecutor};
pub use provider::{OfflineReleaseProvider, ReleaseProvider};
pub use release::{GitLifecycle, ReleaseManager};
pub use signature::{
    EmbeddedSignature, LoadedSignature, SignatureManifest, load_signatures,
    resolve_embedded_signatures,
};
pub use snapshot::{inspect_repository, inspect_repository_with_git};
pub use transaction::{ApplyResult, TransactionExecutor, TransactionPhase, recover_transaction};
pub use versioning::{
    OfflineCatalogSnapshot, ResolutionRequest, ToolchainLock, load_offline_catalog,
    render_toolchain_lock, resolve_catalog,
};

/// Return the core version through the effect layer.
#[must_use]
pub const fn version() -> &'static str {
    kernform_core::version()
}
