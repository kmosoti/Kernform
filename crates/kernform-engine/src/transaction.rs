use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use kernform_core::{
    DocumentFormat, ManagedState, Operation, Ownership, Plan, Severity, StateFile, ToolchainState,
};
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;

use crate::{
    CommandSpec, EngineError, FileLock, ProcessExecutor, atomic_write, hash_bytes, merge_json,
    merge_toml,
};
use crate::{error::io_error, filesystem::safe_join};

/// Durable transaction phase used for recovery decisions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransactionPhase {
    Prepared,
    Applying,
    Committed,
    RolledBack,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JournalEntry {
    operation_id: String,
    path: String,
    backup: Option<String>,
    created_file: bool,
    created_directory: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Journal {
    schema: String,
    plan_id: String,
    phase: TransactionPhase,
    entries: Vec<JournalEntry>,
    git_created: bool,
}

/// Successful application metadata.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApplyResult {
    pub plan_id: String,
    pub operation_count: usize,
    pub state_path: PathBuf,
}

/// Controlled plan executor. All process effects use the injected structured executor.
#[derive(Debug)]
pub struct TransactionExecutor<E> {
    process: E,
}

impl<E: ProcessExecutor> TransactionExecutor<E> {
    /// Construct an executor around a process boundary.
    #[must_use]
    pub const fn new(process: E) -> Self {
        Self { process }
    }

    /// Apply an immutable plan to an existing directory with a durable journal and rollback.
    ///
    /// # Errors
    ///
    /// Returns an error for failed preconditions, concurrent mutation, operation failure, state
    /// persistence failure, or rollback failure.
    pub fn apply_existing(&self, root: &Path, plan: &Plan) -> Result<ApplyResult, EngineError> {
        validate_plan(root, plan)?;
        let control = root.join(".kernform");
        fs::create_dir_all(&control)
            .map_err(|error| io_error("create control directory", &control, error))?;
        let _lock = FileLock::acquire(&control.join("mutation.lock"))?;
        preflight(root, plan)?;

        let transaction = control.join("transactions").join(&plan.plan_id);
        let journal_path = transaction.join("journal.json");
        if journal_path.exists() {
            let existing: Journal =
                serde_json::from_slice(&fs::read(&journal_path).map_err(|error| {
                    io_error("read existing transaction", &journal_path, error)
                })?)
                .map_err(|error| EngineError::Serialization {
                    message: error.to_string(),
                })?;
            if existing.plan_id == plan.plan_id
                && existing.phase == TransactionPhase::Committed
                && plan.operations.is_empty()
            {
                return Ok(ApplyResult {
                    plan_id: plan.plan_id.clone(),
                    operation_count: 0,
                    state_path: root.join(".kernform/state.json"),
                });
            }
            return Err(EngineError::Policy {
                message: format!(
                    "transaction {} already exists; inspect or recover it before apply",
                    plan.plan_id
                ),
            });
        }
        fs::create_dir_all(transaction.join("backups"))
            .map_err(|error| io_error("create transaction journal", &transaction, error))?;
        let mut journal = Journal {
            schema: "kernform.transaction/v1".to_owned(),
            plan_id: plan.plan_id.clone(),
            phase: TransactionPhase::Prepared,
            entries: Vec::new(),
            git_created: false,
        };
        write_journal(&journal_path, &journal)?;
        journal.phase = TransactionPhase::Applying;
        write_journal(&journal_path, &journal)?;

        if let Err(error) =
            self.apply_operations(root, plan, &transaction, &journal_path, &mut journal)
        {
            rollback(root, &transaction, &mut journal, &journal_path)?;
            return Err(error);
        }
        let state = build_state(root, plan)?;
        let state_content = encode_json(&state)?;
        if let Err(error) = tracked_write(
            root,
            &transaction,
            &journal_path,
            &mut journal,
            "state:write",
            Path::new(".kernform/state.json"),
            &state_content,
        ) {
            rollback(root, &transaction, &mut journal, &journal_path)?;
            return Err(error);
        }
        journal.phase = TransactionPhase::Committed;
        write_journal(&journal_path, &journal)?;
        remove_git_marker(root, &journal);
        Ok(ApplyResult {
            plan_id: plan.plan_id.clone(),
            operation_count: plan.operations.len(),
            state_path: root.join(".kernform/state.json"),
        })
    }

    /// Build a complete project in a sibling staging directory and atomically publish it.
    ///
    /// # Errors
    ///
    /// Returns an error if the destination exists, staging/apply fails, or the final sibling rename
    /// cannot be completed atomically.
    pub fn initialize_new(
        &self,
        destination: &Path,
        plan: &Plan,
    ) -> Result<ApplyResult, EngineError> {
        validate_plan_id(&plan.plan_id)?;
        if destination.exists() {
            return Err(EngineError::Precondition {
                path: destination.to_path_buf(),
            });
        }
        let parent = destination
            .parent()
            .ok_or_else(|| EngineError::UnsafePath {
                path: destination.to_path_buf(),
            })?;
        if !parent.is_dir() {
            return Err(EngineError::Precondition {
                path: parent.to_path_buf(),
            });
        }
        let name = destination
            .file_name()
            .ok_or_else(|| EngineError::UnsafePath {
                path: destination.to_path_buf(),
            })?
            .to_string_lossy();
        let staging = parent.join(format!(".{name}.kernform-{}.staging", &plan.plan_id[..12]));
        fs::create_dir(&staging)
            .map_err(|error| io_error("create sibling staging directory", &staging, error))?;
        let applied = match self.apply_existing(&staging, plan) {
            Ok(result) => result,
            Err(error) => {
                remove_internal_tree(&staging)?;
                return Err(error);
            }
        };
        if let Err(error) = fs::rename(&staging, destination) {
            remove_internal_tree(&staging)?;
            return Err(io_error(
                "atomically publish staged project",
                destination,
                error,
            ));
        }
        Ok(ApplyResult {
            state_path: destination.join(".kernform/state.json"),
            ..applied
        })
    }

    fn apply_operations(
        &self,
        root: &Path,
        plan: &Plan,
        transaction: &Path,
        journal_path: &Path,
        journal: &mut Journal,
    ) -> Result<(), EngineError> {
        for operation in &plan.operations {
            self.apply_operation(root, transaction, journal_path, journal, operation)?;
        }
        Ok(())
    }

    fn apply_operation(
        &self,
        root: &Path,
        transaction: &Path,
        journal_path: &Path,
        journal: &mut Journal,
        operation: &Operation,
    ) -> Result<(), EngineError> {
        match operation {
            Operation::CreateDirectory { id, path } => {
                tracked_directory(root, journal_path, journal, id, Path::new(path))
            }
            Operation::WriteFile {
                id, path, content, ..
            } => tracked_write(
                root,
                transaction,
                journal_path,
                journal,
                id,
                Path::new(path),
                content.as_bytes(),
            ),
            Operation::PatchDocument {
                id,
                path,
                format,
                patch,
                ..
            } => {
                let target = safe_join(root, Path::new(path))?;
                let content = render_patch(&target, *format, patch)?;
                tracked_write(
                    root,
                    transaction,
                    journal_path,
                    journal,
                    id,
                    Path::new(path),
                    &content,
                )
            }
            Operation::RunCommand {
                program,
                args,
                cwd,
                environment,
                timeout_seconds,
                ..
            } => {
                let cwd = safe_join(root, Path::new(cwd))?;
                let result = self.process.execute(&CommandSpec {
                    program: program.clone(),
                    args: args.clone(),
                    cwd,
                    environment: environment.clone(),
                    timeout_seconds: *timeout_seconds,
                })?;
                if result.timed_out || result.exit_code != Some(0) {
                    return Err(EngineError::Process {
                        program: program.clone(),
                        message: format!(
                            "command returned {:?}; stderr={}",
                            result.exit_code,
                            String::from_utf8_lossy(&result.stderr)
                        ),
                    });
                }
                Ok(())
            }
            Operation::InitGitRepository { initial_branch, .. } => {
                init_git(&self.process, root, initial_branch, journal, journal_path)
            }
            Operation::Check { check, .. } => execute_check(root, check),
        }
    }
}

/// Recover a non-committed transaction from its durable journal.
///
/// # Errors
///
/// Returns an error for a malformed plan identifier, missing/corrupt journal, concurrent mutation,
/// or failed restoration.
pub fn recover_transaction(root: &Path, plan_id: &str) -> Result<TransactionPhase, EngineError> {
    validate_plan_id(plan_id)?;
    let control = root.join(".kernform");
    let _lock = FileLock::acquire(&control.join("mutation.lock"))?;
    let transaction = control.join("transactions").join(plan_id);
    let journal_path = transaction.join("journal.json");
    let mut journal: Journal = serde_json::from_slice(
        &fs::read(&journal_path)
            .map_err(|error| io_error("read transaction journal", &journal_path, error))?,
    )
    .map_err(|error| EngineError::Serialization {
        message: error.to_string(),
    })?;
    if journal.plan_id != plan_id || journal.schema != "kernform.transaction/v1" {
        return Err(EngineError::Policy {
            message: "transaction journal identity does not match its path".to_owned(),
        });
    }
    if matches!(
        journal.phase,
        TransactionPhase::Committed | TransactionPhase::RolledBack
    ) {
        if journal.phase == TransactionPhase::Committed {
            remove_git_marker(root, &journal);
        }
        return Ok(journal.phase);
    }
    rollback(root, &transaction, &mut journal, &journal_path)?;
    Ok(journal.phase)
}

fn validate_plan(root: &Path, plan: &Plan) -> Result<(), EngineError> {
    if !root.is_dir() || plan.schema != "kernform.plan/v1" {
        return Err(EngineError::Policy {
            message: "apply requires an existing directory and kernform.plan/v1".to_owned(),
        });
    }
    validate_plan_id(&plan.plan_id)?;
    if plan
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == Severity::Error)
    {
        return Err(EngineError::Policy {
            message: "plan contains error diagnostics and cannot be applied".to_owned(),
        });
    }
    let mut ids = BTreeSet::new();
    if plan
        .operations
        .iter()
        .any(|operation| !ids.insert(operation.id()))
    {
        return Err(EngineError::Policy {
            message: "plan contains duplicate operation identifiers".to_owned(),
        });
    }
    Ok(())
}

fn validate_plan_id(plan_id: &str) -> Result<(), EngineError> {
    if plan_id.len() != 64
        || !plan_id
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(EngineError::Policy {
            message: "plan ID must be a lowercase SHA-256 digest".to_owned(),
        });
    }
    Ok(())
}

fn preflight(root: &Path, plan: &Plan) -> Result<(), EngineError> {
    for operation in &plan.operations {
        match operation {
            Operation::CreateDirectory { path, .. } => {
                let target = safe_join(root, Path::new(path))?;
                if target.exists() && !target.is_dir() {
                    return Err(EngineError::Precondition { path: target });
                }
            }
            Operation::WriteFile {
                path,
                expected_hash,
                ..
            } => check_file_precondition(root, path, expected_hash.as_deref())?,
            Operation::PatchDocument {
                path,
                expected_hash,
                ..
            } => check_file_precondition(root, path, Some(expected_hash))?,
            Operation::RunCommand { cwd, .. } => {
                let target = safe_join(root, Path::new(cwd))?;
                if !target.is_dir() {
                    return Err(EngineError::Precondition { path: target });
                }
            }
            Operation::InitGitRepository { .. } if root.join(".git").exists() => {
                return Err(EngineError::Precondition {
                    path: root.join(".git"),
                });
            }
            Operation::InitGitRepository { .. } | Operation::Check { .. } => {}
        }
    }
    Ok(())
}

fn check_file_precondition(
    root: &Path,
    path: &str,
    expected_hash: Option<&str>,
) -> Result<(), EngineError> {
    let target = safe_join(root, Path::new(path))?;
    if target.exists() {
        let metadata = fs::symlink_metadata(&target)
            .map_err(|error| io_error("inspect precondition", &target, error))?;
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err(EngineError::Precondition { path: target });
        }
        let actual = hash_bytes(
            &fs::read(&target).map_err(|error| io_error("read precondition", &target, error))?,
        );
        if expected_hash != Some(actual.as_str()) {
            return Err(EngineError::Precondition { path: target });
        }
    } else if expected_hash.is_some() {
        return Err(EngineError::Precondition { path: target });
    }
    Ok(())
}

fn tracked_directory(
    root: &Path,
    journal_path: &Path,
    journal: &mut Journal,
    operation_id: &str,
    relative: &Path,
) -> Result<(), EngineError> {
    let target = safe_join(root, relative)?;
    if target.is_dir() {
        return Ok(());
    }
    journal.entries.push(JournalEntry {
        operation_id: operation_id.to_owned(),
        path: path_string(relative)?,
        backup: None,
        created_file: false,
        created_directory: true,
    });
    write_journal(journal_path, journal)?;
    fs::create_dir(&target).map_err(|error| io_error("create planned directory", &target, error))
}

fn tracked_write(
    root: &Path,
    transaction: &Path,
    journal_path: &Path,
    journal: &mut Journal,
    operation_id: &str,
    relative: &Path,
    content: &[u8],
) -> Result<(), EngineError> {
    let target = safe_join(root, relative)?;
    let existed = target.exists();
    let backup = if existed {
        let backup_relative = format!("backups/{:04}", journal.entries.len());
        let backup_path = transaction.join(&backup_relative);
        fs::copy(&target, &backup_path)
            .map_err(|error| io_error("back up managed file", &target, error))?;
        Some(backup_relative)
    } else {
        None
    };
    journal.entries.push(JournalEntry {
        operation_id: operation_id.to_owned(),
        path: path_string(relative)?,
        backup,
        created_file: !existed,
        created_directory: false,
    });
    write_journal(journal_path, journal)?;
    atomic_write(&target, content)
}

fn render_patch(
    document_path: &Path,
    format: DocumentFormat,
    patch_value: &JsonValue,
) -> Result<Vec<u8>, EngineError> {
    let source = fs::read_to_string(document_path)
        .map_err(|error| io_error("read document for semantic patch", document_path, error))?;
    match format {
        DocumentFormat::Json => {
            let mut target: JsonValue =
                serde_json::from_str(&source).map_err(|error| EngineError::Serialization {
                    message: error.to_string(),
                })?;
            merge_json(&mut target, patch_value)?;
            encode_json(&target)
        }
        DocumentFormat::Toml => {
            let mut target: toml::Value =
                toml::from_str(&source).map_err(|error| EngineError::Serialization {
                    message: error.to_string(),
                })?;
            let toml_patch = toml::Value::try_from(patch_value.clone()).map_err(|error| {
                EngineError::Serialization {
                    message: error.to_string(),
                }
            })?;
            merge_toml(&mut target, &toml_patch)?;
            toml::to_string_pretty(&target)
                .map(String::into_bytes)
                .map_err(|error| EngineError::Serialization {
                    message: error.to_string(),
                })
        }
    }
}

fn init_git(
    process: &dyn ProcessExecutor,
    root: &Path,
    initial_branch: &str,
    journal: &mut Journal,
    journal_path: &Path,
) -> Result<(), EngineError> {
    if initial_branch.is_empty() || initial_branch.starts_with('-') {
        return Err(EngineError::Policy {
            message: "Git initial branch is invalid".to_owned(),
        });
    }
    journal.git_created = true;
    write_journal(journal_path, journal)?;
    let environment =
        BTreeMap::from([("PATH".to_owned(), std::env::var("PATH").unwrap_or_default())]);
    let result = process.execute(&CommandSpec {
        program: "git".to_owned(),
        args: vec![
            "init".to_owned(),
            format!("--initial-branch={initial_branch}"),
        ],
        cwd: root.to_path_buf(),
        environment,
        timeout_seconds: 30,
    })?;
    if result.exit_code != Some(0) || result.timed_out {
        return Err(EngineError::Git {
            message: String::from_utf8_lossy(&result.stderr).into_owned(),
        });
    }
    let marker = root
        .join(".git")
        .join(format!("kernform-transaction-{}", journal.plan_id));
    atomic_write(&marker, b"created by an incomplete Kernform transaction\n")?;
    Ok(())
}

fn execute_check(root: &Path, check: &str) -> Result<(), EngineError> {
    match check {
        "repository-exists" if root.is_dir() => Ok(()),
        "git-present" if root.join(".git").is_dir() => Ok(()),
        "repository-exists" | "git-present" => Err(EngineError::Policy {
            message: format!("planned check failed: {check}"),
        }),
        _ => Err(EngineError::Policy {
            message: format!("unknown planned check: {check}"),
        }),
    }
}

fn build_state(root: &Path, plan: &Plan) -> Result<ManagedState, EngineError> {
    let state_path = root.join(".kernform/state.json");
    let existing = if state_path.is_file() {
        Some(
            serde_json::from_slice::<ManagedState>(
                &fs::read(&state_path)
                    .map_err(|error| io_error("read managed state", &state_path, error))?,
            )
            .map_err(|error| EngineError::Serialization {
                message: error.to_string(),
            })?,
        )
    } else {
        None
    };
    let mut files = existing
        .map(|state| {
            state
                .files
                .into_iter()
                .map(|file| (file.path.clone(), file))
                .collect::<BTreeMap<_, _>>()
        })
        .unwrap_or_default();
    for operation in &plan.operations {
        match operation {
            Operation::WriteFile {
                path, ownership, ..
            } => record_state_file(root, &mut files, path, *ownership)?,
            Operation::PatchDocument { path, .. } => {
                let ownership = files
                    .get(path)
                    .map_or(Ownership::Managed, |file| file.ownership);
                record_state_file(root, &mut files, path, ownership)?;
            }
            _ => {}
        }
    }
    let manifest = root.join("kernform.toml");
    let manifest_hash = if manifest.is_file() {
        hash_bytes(
            &fs::read(&manifest)
                .map_err(|error| io_error("hash project manifest", &manifest, error))?,
        )
    } else {
        hash_bytes(b"")
    };
    Ok(ManagedState {
        schema: "kernform.state/v1".to_owned(),
        generator_version: plan.generator_version.clone(),
        project_root: plan.intent.name.clone(),
        manifest_hash,
        toolchains: ToolchainState {
            catalog_id: plan.catalog.id.clone(),
            catalog_hash: plan.catalog.hash.clone(),
        },
        files: files.into_values().collect(),
    })
}

fn record_state_file(
    root: &Path,
    files: &mut BTreeMap<String, StateFile>,
    path: &str,
    ownership: Ownership,
) -> Result<(), EngineError> {
    let target = safe_join(root, Path::new(path))?;
    let hash = hash_bytes(
        &fs::read(&target).map_err(|error| io_error("hash managed file", &target, error))?,
    );
    files.insert(
        path.to_owned(),
        StateFile {
            path: path.to_owned(),
            hash,
            ownership,
        },
    );
    Ok(())
}

fn rollback(
    root: &Path,
    transaction: &Path,
    journal: &mut Journal,
    journal_path: &Path,
) -> Result<(), EngineError> {
    if journal.git_created {
        let marker = root
            .join(".git")
            .join(format!("kernform-transaction-{}", journal.plan_id));
        if marker.is_file() {
            fs::remove_dir_all(root.join(".git"))
                .map_err(|error| io_error("roll back new Git repository", root, error))?;
        }
    }
    for entry in journal.entries.iter().rev() {
        let target = safe_join(root, Path::new(&entry.path))?;
        if let Some(backup) = &entry.backup {
            let backup_path = transaction.join(backup);
            let content = fs::read(&backup_path)
                .map_err(|error| io_error("read transaction backup", &backup_path, error))?;
            atomic_write(&target, &content)?;
        } else if entry.created_file && target.exists() {
            fs::remove_file(&target)
                .map_err(|error| io_error("remove transaction-created file", &target, error))?;
        } else if entry.created_directory && target.is_dir() {
            match fs::remove_dir(&target) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::DirectoryNotEmpty => {}
                Err(error) => {
                    return Err(io_error(
                        "remove transaction-created directory",
                        &target,
                        error,
                    ));
                }
            }
        }
    }
    journal.phase = TransactionPhase::RolledBack;
    write_journal(journal_path, journal)
}

fn remove_git_marker(root: &Path, journal: &Journal) {
    if journal.git_created {
        let marker = root
            .join(".git")
            .join(format!("kernform-transaction-{}", journal.plan_id));
        let _ = fs::remove_file(marker);
    }
}

fn write_journal(path: &Path, journal: &Journal) -> Result<(), EngineError> {
    atomic_write(path, &encode_json(journal)?)
}

fn encode_json(value: &impl Serialize) -> Result<Vec<u8>, EngineError> {
    let mut content =
        serde_json::to_vec_pretty(value).map_err(|error| EngineError::Serialization {
            message: error.to_string(),
        })?;
    content.push(b'\n');
    Ok(content)
}

fn path_string(path: &Path) -> Result<String, EngineError> {
    path.to_str()
        .map(|value| value.replace('\\', "/"))
        .ok_or_else(|| EngineError::UnsafePath {
            path: path.to_path_buf(),
        })
}

fn remove_internal_tree(path: &Path) -> Result<(), EngineError> {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("");
    if !name.starts_with('.') || !name.contains(".kernform-") || !name.ends_with(".staging") {
        return Err(EngineError::UnsafePath {
            path: path.to_path_buf(),
        });
    }
    fs::remove_dir_all(path)
        .map_err(|error| io_error("remove failed staging directory", path, error))
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, BTreeSet};

    use kernform_core::{
        GitIntent, Profile, ProjectIntent, RenderedFile, RepositorySnapshot, VersionCatalog,
        finalize_catalog, plan_initialization,
    };
    use tempfile::tempdir;

    use super::*;
    use crate::{ProcessResult, SystemProcessExecutor};

    fn catalog() -> VersionCatalog {
        finalize_catalog(VersionCatalog {
            id: "transaction-test".to_owned(),
            hash: String::new(),
            resolved_at: "2026-07-18T05:00:04Z".to_owned(),
            source: "https://example.invalid/catalog".to_owned(),
            versions: BTreeMap::from([("python".to_owned(), "3.14.6".to_owned())]),
            images: BTreeMap::new(),
        })
        .unwrap()
    }

    fn plan(git: bool) -> Plan {
        plan_initialization(
            ProjectIntent {
                name: "example".to_owned(),
                profile: Profile::Library,
                capabilities: BTreeSet::new(),
                git: GitIntent {
                    enabled: git,
                    ..GitIntent::default()
                },
            },
            &RepositorySnapshot::default(),
            catalog(),
            vec![RenderedFile {
                path: "src/value.txt".to_owned(),
                content: "complete\n".to_owned(),
                ownership: Ownership::Generated,
            }],
        )
        .unwrap()
    }

    #[derive(Debug)]
    struct FailingProcess;

    impl ProcessExecutor for FailingProcess {
        fn execute(&self, _spec: &CommandSpec) -> Result<ProcessResult, EngineError> {
            Ok(ProcessResult {
                exit_code: Some(7),
                stdout: Vec::new(),
                stderr: b"injected failure".to_vec(),
                timed_out: false,
                duration_millis: 0,
            })
        }
    }

    #[test]
    fn new_project_is_published_complete_with_unborn_main() {
        let parent = tempdir().unwrap();
        let destination = parent.path().join("example");
        TransactionExecutor::new(SystemProcessExecutor)
            .initialize_new(&destination, &plan(true))
            .unwrap();
        assert_eq!(
            fs::read(destination.join("src/value.txt")).unwrap(),
            b"complete\n"
        );
        assert!(destination.join(".kernform/state.json").is_file());
        let output = std::process::Command::new("git")
            .args(["symbolic-ref", "--short", "HEAD"])
            .current_dir(&destination)
            .output()
            .unwrap();
        assert_eq!(String::from_utf8(output.stdout).unwrap().trim(), "main");
        assert!(!destination.join(".git/refs/heads/main").exists());
    }

    #[test]
    fn failed_git_initialization_rolls_back_files() {
        let directory = tempdir().unwrap();
        let error = TransactionExecutor::new(FailingProcess)
            .apply_existing(directory.path(), &plan(true))
            .unwrap_err();
        assert!(matches!(error, EngineError::Git { .. }));
        assert!(!directory.path().join("src/value.txt").exists());
        assert!(!directory.path().join(".git").exists());
    }

    #[test]
    fn file_precondition_failure_mutates_nothing() {
        let directory = tempdir().unwrap();
        fs::create_dir(directory.path().join("src")).unwrap();
        fs::write(directory.path().join("src/value.txt"), b"user\n").unwrap();
        let error = TransactionExecutor::new(SystemProcessExecutor)
            .apply_existing(directory.path(), &plan(false))
            .unwrap_err();
        assert!(matches!(error, EngineError::Precondition { .. }));
        assert_eq!(
            fs::read(directory.path().join("src/value.txt")).unwrap(),
            b"user\n"
        );
    }

    #[test]
    fn interrupted_transaction_recovery_is_repeatable() {
        let directory = tempdir().unwrap();
        let plan_id = "a".repeat(64);
        let transaction = directory
            .path()
            .join(".kernform/transactions")
            .join(&plan_id);
        fs::create_dir_all(transaction.join("backups")).unwrap();
        fs::write(directory.path().join("partial.txt"), b"partial\n").unwrap();
        let journal = Journal {
            schema: "kernform.transaction/v1".to_owned(),
            plan_id: plan_id.clone(),
            phase: TransactionPhase::Applying,
            entries: vec![JournalEntry {
                operation_id: "write:partial.txt".to_owned(),
                path: "partial.txt".to_owned(),
                backup: None,
                created_file: true,
                created_directory: false,
            }],
            git_created: false,
        };
        write_journal(&transaction.join("journal.json"), &journal).unwrap();

        assert_eq!(
            recover_transaction(directory.path(), &plan_id).unwrap(),
            TransactionPhase::RolledBack
        );
        assert!(!directory.path().join("partial.txt").exists());
        assert_eq!(
            recover_transaction(directory.path(), &plan_id).unwrap(),
            TransactionPhase::RolledBack
        );
    }
}
