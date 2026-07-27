//! Pure domain models and deterministic planning for Kernform.

pub mod capability;
pub mod catalog;
pub mod command;
pub mod conformance;
pub mod error;
pub mod model;
pub mod planner;
pub mod release;
pub mod signature;

pub use capability::{CapabilitySpec, resolve_capabilities};
pub use catalog::{canonical_json, finalize_catalog, select_newest_stable, validate_catalog};
pub use command::{command_failure, command_success};
pub use conformance::{
    ConformanceCheck, ConformanceFamily, ConformanceInput, check_web_policy, evaluate_conformance,
};
pub use error::CoreError;
pub use model::*;
pub use planner::{
    file_hash, plan_initialization, validate_initial_branch, validate_plan_identity,
};
pub use signature::{SignatureResolution, SignatureSpec, resolve_signatures};

/// Current generator version.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Return the current generator version without performing any effects.
#[must_use]
pub const fn version() -> &'static str {
    VERSION
}
