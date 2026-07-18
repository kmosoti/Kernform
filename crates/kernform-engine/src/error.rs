use std::path::PathBuf;

use thiserror::Error;

/// Failures produced by controlled effect boundaries.
#[derive(Debug, Error)]
pub enum EngineError {
    #[error("{operation} failed for {path}: {message}")]
    Io {
        operation: &'static str,
        path: PathBuf,
        message: String,
    },
    #[error("process {program:?} failed: {message}")]
    Process { program: String, message: String },
    #[error("process {program:?} timed out after {timeout_seconds}s")]
    Timeout {
        program: String,
        timeout_seconds: u64,
    },
    #[error("captured output from {program:?} is not valid UTF-8")]
    Encoding { program: String },
    #[error("Git operation failed: {message}")]
    Git { message: String },
    #[error("serialization failed: {message}")]
    Serialization { message: String },
    #[error("file precondition failed for {path}")]
    Precondition { path: PathBuf },
    #[error("project mutation lock already exists at {path}")]
    LockHeld { path: PathBuf },
    #[error("unsafe effect path: {path}")]
    UnsafePath { path: PathBuf },
    #[error("effect policy refused operation: {message}")]
    Policy { message: String },
}

pub(crate) fn io_error(
    operation: &'static str,
    path: impl Into<PathBuf>,
    error: impl std::fmt::Display,
) -> EngineError {
    EngineError::Io {
        operation,
        path: path.into(),
        message: error.to_string(),
    }
}
