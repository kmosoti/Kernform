//! Thin `PyO3` exposure for Kernform.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use kernform_core::{
    CoreError, ManagedState, Plan, ProjectIntent, RenderedFile, RepositorySnapshot, VersionCatalog,
    check_web_policy, plan_initialization,
};
use kernform_engine::{
    EngineError, GitLifecycle, ReleaseManager, SystemProcessExecutor, TransactionExecutor,
    inspect_repository_with_git, render_embedded_capabilities,
};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;
use serde::Serialize;
use serde::de::DeserializeOwned;

mod builtins {
    include!(concat!(env!("OUT_DIR"), "/builtin_capabilities.rs"));
}

create_exception!(_native, KernformNativeError, PyException);
create_exception!(_native, KernformPolicyError, KernformNativeError);
create_exception!(_native, KernformPreconditionError, KernformNativeError);
create_exception!(_native, KernformProcessError, KernformNativeError);

#[pyfunction]
fn native_version() -> &'static str {
    kernform_engine::version()
}

#[pyfunction]
fn plan_initialization_json(
    py: Python<'_>,
    intent_json: &str,
    snapshot_json: &str,
    catalog_json: &str,
    files_json: &str,
) -> PyResult<String> {
    let intent = decode::<ProjectIntent>(intent_json, "project intent")?;
    let snapshot = decode::<RepositorySnapshot>(snapshot_json, "repository snapshot")?;
    let catalog = decode::<VersionCatalog>(catalog_json, "version catalog")?;
    let files = decode::<Vec<RenderedFile>>(files_json, "rendered files")?;
    py.detach(move || plan_initialization(intent, &snapshot, catalog, files))
        .map_err(|error| map_core_error(&error))
        .and_then(|plan| encode(&plan))
}

#[pyfunction]
fn inspect_repository_json(
    py: Python<'_>,
    root: String,
    state_json: Option<&str>,
) -> PyResult<String> {
    let state = state_json
        .map(|value| decode::<ManagedState>(value, "managed state"))
        .transpose()?;
    py.detach(move || {
        inspect_repository_with_git(Path::new(&root), state.as_ref(), SystemProcessExecutor)
    })
    .map_err(|error| map_engine_error(&error))
    .and_then(|snapshot| encode(&snapshot))
}

#[pyfunction]
fn apply_plan_json(
    py: Python<'_>,
    root: String,
    plan_json: &str,
    new_project: bool,
) -> PyResult<String> {
    let plan = decode::<Plan>(plan_json, "plan")?;
    let result = py.detach(move || {
        let executor = TransactionExecutor::new(SystemProcessExecutor);
        if new_project {
            executor.initialize_new(Path::new(&root), &plan)
        } else {
            executor.apply_existing(Path::new(&root), &plan)
        }
    });
    result
        .map_err(|error| map_engine_error(&error))
        .and_then(|applied| {
            encode(&serde_json::json!({
            "plan_id": applied.plan_id,
            "operation_count": applied.operation_count,
            "state_path": applied.state_path,
            }))
        })
}

#[pyfunction]
fn check_web_policy_json(py: Python<'_>, files_json: &str) -> PyResult<String> {
    let files = decode::<Vec<RenderedFile>>(files_json, "rendered files")?;
    let diagnostics = py.detach(move || check_web_policy(&files));
    encode(&diagnostics)
}

#[pyfunction]
fn render_capabilities_json(
    py: Python<'_>,
    requested_json: &str,
    variables_json: &str,
) -> PyResult<String> {
    let requested = decode::<BTreeSet<String>>(requested_json, "requested capabilities")?;
    let variables = decode::<BTreeMap<String, String>>(variables_json, "template variables")?;
    py.detach(move || {
        render_embedded_capabilities(builtins::BUILTIN_CAPABILITIES, &requested, &variables)
    })
    .map_err(|error| map_engine_error(&error))
    .and_then(|files| encode(&files))
}

#[pyfunction]
fn git_initial_commit_json(py: Python<'_>, root: String, message: String) -> PyResult<String> {
    py.detach(move || {
        GitLifecycle::new(SystemProcessExecutor).initial_commit(Path::new(&root), &message)
    })
    .map_err(|error| map_engine_error(&error))
}

#[pyfunction]
fn release_start_json(
    py: Python<'_>,
    root: String,
    version: String,
    catalog_hash: String,
) -> PyResult<String> {
    py.detach(move || {
        ReleaseManager::new(SystemProcessExecutor).start(Path::new(&root), &version, &catalog_hash)
    })
    .map_err(|error| map_engine_error(&error))
    .and_then(|state| encode(&state))
}

#[pyfunction]
fn release_inspect_json(py: Python<'_>, root: String) -> PyResult<String> {
    py.detach(move || ReleaseManager::new(SystemProcessExecutor).inspect(Path::new(&root)))
        .map_err(|error| map_engine_error(&error))
        .and_then(|state| encode(&state))
}

#[pyfunction]
fn release_verify_json(
    py: Python<'_>,
    root: String,
    metadata_matches: bool,
    synchronized: bool,
) -> PyResult<String> {
    py.detach(move || {
        ReleaseManager::new(SystemProcessExecutor).verify(
            Path::new(&root),
            metadata_matches,
            synchronized,
        )
    })
    .map_err(|error| map_engine_error(&error))
    .and_then(|state| encode(&state))
}

#[pyfunction]
fn release_finalize_json(
    py: Python<'_>,
    root: String,
    verification_complete: bool,
) -> PyResult<String> {
    py.detach(move || {
        ReleaseManager::new(SystemProcessExecutor).finalize(Path::new(&root), verification_complete)
    })
    .map_err(|error| map_engine_error(&error))
    .and_then(|state| encode(&state))
}

fn decode<T: DeserializeOwned>(raw: &str, label: &str) -> PyResult<T> {
    serde_json::from_str(raw)
        .map_err(|error| PyValueError::new_err(format!("invalid {label} JSON: {error}")))
}

fn encode(value: &impl Serialize) -> PyResult<String> {
    serde_json::to_string(value)
        .map_err(|error| PyValueError::new_err(format!("JSON serialization failed: {error}")))
}

fn map_core_error(error: &CoreError) -> PyErr {
    KernformPolicyError::new_err(format!("core:{}:{error}", core_error_kind(error)))
}

fn core_error_kind(error: &CoreError) -> &'static str {
    match error {
        CoreError::InvalidIntent { .. } => "invalid_intent",
        CoreError::UnknownCapability { .. } => "unknown_capability",
        CoreError::CapabilityCycle { .. } => "capability_cycle",
        CoreError::CapabilityConflict { .. } => "capability_conflict",
        CoreError::InvalidVersion { .. } => "invalid_version",
        CoreError::InvalidDigest { .. } => "invalid_digest",
        CoreError::UnsafePath { .. } => "unsafe_path",
        CoreError::Serialization { .. } => "serialization",
    }
}

fn map_engine_error(error: &EngineError) -> PyErr {
    let identity = engine_error_kind(error);
    let message = format!("engine:{identity}:{error}");
    match error {
        EngineError::Precondition { .. } | EngineError::LockHeld { .. } => {
            KernformPreconditionError::new_err(message)
        }
        EngineError::Process { .. }
        | EngineError::Timeout { .. }
        | EngineError::Encoding { .. }
        | EngineError::Git { .. } => KernformProcessError::new_err(message),
        EngineError::Policy { .. } | EngineError::UnsafePath { .. } => {
            KernformPolicyError::new_err(message)
        }
        EngineError::Io { .. } | EngineError::Serialization { .. } => {
            KernformNativeError::new_err(message)
        }
    }
}

fn engine_error_kind(error: &EngineError) -> &'static str {
    match error {
        EngineError::Io { .. } => "io",
        EngineError::Process { .. } => "process",
        EngineError::Timeout { .. } => "timeout",
        EngineError::Encoding { .. } => "encoding",
        EngineError::Git { .. } => "git",
        EngineError::Serialization { .. } => "serialization",
        EngineError::Precondition { .. } => "precondition",
        EngineError::LockHeld { .. } => "lock_held",
        EngineError::UnsafePath { .. } => "unsafe_path",
        EngineError::Policy { .. } => "policy",
    }
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add(
        "KernformNativeError",
        module.py().get_type::<KernformNativeError>(),
    )?;
    module.add(
        "KernformPolicyError",
        module.py().get_type::<KernformPolicyError>(),
    )?;
    module.add(
        "KernformPreconditionError",
        module.py().get_type::<KernformPreconditionError>(),
    )?;
    module.add(
        "KernformProcessError",
        module.py().get_type::<KernformProcessError>(),
    )?;
    module.add_function(wrap_pyfunction!(native_version, module)?)?;
    module.add_function(wrap_pyfunction!(plan_initialization_json, module)?)?;
    module.add_function(wrap_pyfunction!(inspect_repository_json, module)?)?;
    module.add_function(wrap_pyfunction!(apply_plan_json, module)?)?;
    module.add_function(wrap_pyfunction!(check_web_policy_json, module)?)?;
    module.add_function(wrap_pyfunction!(render_capabilities_json, module)?)?;
    module.add_function(wrap_pyfunction!(git_initial_commit_json, module)?)?;
    module.add_function(wrap_pyfunction!(release_start_json, module)?)?;
    module.add_function(wrap_pyfunction!(release_inspect_json, module)?)?;
    module.add_function(wrap_pyfunction!(release_verify_json, module)?)?;
    module.add_function(wrap_pyfunction!(release_finalize_json, module)?)?;
    Ok(())
}
