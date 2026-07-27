use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Deterministic failures produced by pure Kernform decisions.
#[derive(Debug, Clone, PartialEq, Eq, Error, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum CoreError {
    #[error("invalid project intent: {message}")]
    InvalidIntent { message: String },
    #[error("unknown signature: {id}")]
    UnknownSignature { id: String },
    #[error("signature cycle: {path}")]
    SignatureCycle { path: String },
    #[error("runtime signature {id} is not available in the resolved project form")]
    InvalidRuntimeSignature { id: String },
    #[error("multiple executable signatures require runtime.default_signature: {candidates}")]
    AmbiguousRuntime { candidates: String },
    #[error("unknown capability: {id}")]
    UnknownCapability { id: String },
    #[error("capability cycle: {path}")]
    CapabilityCycle { path: String },
    #[error("capability conflict: {left} conflicts with {right}")]
    CapabilityConflict { left: String, right: String },
    #[error("invalid stable version {value:?} for {name}")]
    InvalidVersion { name: String, value: String },
    #[error("invalid OCI digest {digest:?} for {name}")]
    InvalidDigest { name: String, digest: String },
    #[error("unsafe generated path: {path}")]
    UnsafePath { path: String },
    #[error("serialization failed: {message}")]
    Serialization { message: String },
}
