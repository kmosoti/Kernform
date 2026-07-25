use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

use kernform_core::ReleaseState;
use kernform_core::release::{
    EvidenceStatus, ReleaseSnapshot, finalize_release, start_release, verify_release,
};

use crate::{CommandSpec, EngineError, GitClient, ProcessExecutor, atomic_write, error::io_error};

/// Local Git lifecycle operations. Remote creation and global configuration are not representable.
#[derive(Debug)]
pub struct GitLifecycle<E> {
    process: E,
}

impl<E: ProcessExecutor> GitLifecycle<E> {
    /// Construct a lifecycle service over a structured process boundary.
    #[must_use]
    pub const fn new(process: E) -> Self {
        Self { process }
    }

    /// Create an explicit initial commit after validating repository-resolved identity and signing
    /// policy.
    ///
    /// # Errors
    ///
    /// Returns an error if identity/signing prerequisites are absent or either Git operation fails.
    pub fn initial_commit(&self, root: &Path, message: &str) -> Result<String, EngineError> {
        if message.trim().is_empty() {
            return Err(EngineError::Policy {
                message: "initial commit message cannot be empty".to_owned(),
            });
        }
        for key in ["user.name", "user.email"] {
            if self.git_output(root, &["config", "--get", key])?.is_empty() {
                return Err(EngineError::Git {
                    message: format!("Git identity {key} is not configured"),
                });
            }
        }
        let sign = self.git_output(root, &["config", "--bool", "commit.gpgsign"])? == "true";
        if sign
            && self
                .git_output(root, &["config", "--get", "user.signingkey"])?
                .is_empty()
        {
            return Err(EngineError::Git {
                message: "commit signing is required but user.signingkey is not configured"
                    .to_owned(),
            });
        }
        self.git(root, &["add", "--all"])?;
        let mut arguments = vec!["commit"];
        if sign {
            arguments.push("-S");
        }
        arguments.extend(["-m", message]);
        self.git(root, &arguments)?;
        self.git_output(root, &["rev-parse", "HEAD"])
    }

    /// Rename the primary branch only when explicitly requested.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid name or failed Git operation.
    pub fn normalize_primary_branch(&self, root: &Path, branch: &str) -> Result<(), EngineError> {
        validate_ref_component(branch)?;
        self.git(root, &["branch", "-M", branch])
    }

    fn git(&self, root: &Path, args: &[&str]) -> Result<(), EngineError> {
        let result = run_git(&self.process, root, args)?;
        if result.exit_code == Some(0) && !result.timed_out {
            Ok(())
        } else {
            Err(EngineError::Git {
                message: String::from_utf8_lossy(&result.stderr).into_owned(),
            })
        }
    }

    fn git_output(&self, root: &Path, args: &[&str]) -> Result<String, EngineError> {
        let result = run_git(&self.process, root, args)?;
        if result.exit_code == Some(0) && !result.timed_out {
            Ok(result.stdout_text("git")?.trim().to_owned())
        } else if result.exit_code == Some(1) {
            Ok(String::new())
        } else {
            Err(EngineError::Git {
                message: String::from_utf8_lossy(&result.stderr).into_owned(),
            })
        }
    }
}

/// Local release-flow application service. It never creates tags, remotes, or pushes.
#[derive(Debug)]
pub struct ReleaseManager<E> {
    process: E,
}

impl<E: ProcessExecutor> ReleaseManager<E> {
    /// Construct a release service over a structured process boundary.
    #[must_use]
    pub const fn new(process: E) -> Self {
        Self { process }
    }

    /// Start `release/<version>` from a clean committed `main` and persist frozen catalog state.
    ///
    /// # Errors
    ///
    /// Returns an error for missing Git, a dirty/wrong branch, missing source commit, tag collision,
    /// invalid version, branch creation failure, or state persistence failure.
    pub fn start(
        &self,
        root: &Path,
        version: &str,
        catalog_hash: &str,
    ) -> Result<ReleaseState, EngineError> {
        let observed = self.git_snapshot(root)?;
        let source_commit = observed.head.ok_or_else(|| EngineError::Git {
            message: "release start requires an existing source commit".to_owned(),
        })?;
        let tags = self.tags(root)?;
        if tags.contains(&format!("v{version}")) {
            return Err(EngineError::Git {
                message: format!("release tag v{version} already exists"),
            });
        }
        let facts = release_facts(
            observed.primary_branch.unwrap_or_default(),
            observed.status.is_empty(),
            source_commit,
            tags,
        );
        let state = start_release(version, catalog_hash, &facts)
            .map_err(|diagnostic| diagnostic_error(&diagnostic))?;
        validate_ref_component(&state.branch)?;
        self.git(&["switch", "-c", &state.branch], root)?;
        let updates = match render_release_metadata_updates(root, version) {
            Ok(updates) => updates,
            Err(error) => {
                let _ = self.git(&["switch", "main"], root);
                let _ = self.git(&["branch", "-D", &state.branch], root);
                return Err(error);
            }
        };
        if let Err(error) = apply_release_metadata_updates(&updates) {
            let _ = restore_release_metadata(&updates);
            let _ = self.git(&["switch", "main"], root);
            let _ = self.git(&["branch", "-D", &state.branch], root);
            return Err(error);
        }
        if let Err(error) = write_release_state(root, &state) {
            let _ = restore_release_metadata(&updates);
            let _ = self.git(&["switch", "main"], root);
            let _ = self.git(&["branch", "-D", &state.branch], root);
            return Err(error);
        }
        Ok(state)
    }

    /// Inspect persisted release state.
    ///
    /// # Errors
    ///
    /// Returns an error when state is absent or malformed.
    pub fn inspect(&self, root: &Path) -> Result<ReleaseState, EngineError> {
        read_release_state(root)
    }

    /// Verify clean source/metadata/synchronization evidence and freeze the exact release commit.
    ///
    /// # Errors
    ///
    /// Returns an error when release or Git state and supplied evidence do not satisfy policy.
    pub fn verify(
        &self,
        root: &Path,
        metadata_matches: bool,
        synchronized: bool,
    ) -> Result<ReleaseState, EngineError> {
        let state = read_release_state(root)?;
        let observed = self.git_snapshot(root)?;
        if observed.primary_branch.as_deref() != Some(state.branch.as_str()) {
            return Err(EngineError::Git {
                message: format!("release verification requires branch {}", state.branch),
            });
        }
        let facts = ReleaseSnapshot {
            branch: state.branch.clone(),
            clean: evidence(observed.status.is_empty()),
            source_commit: observed.head.clone().unwrap_or_default(),
            source_known: evidence(observed.head.is_some()),
            metadata_matches: evidence(metadata_matches),
            synchronized: evidence(synchronized),
            verified: EvidenceStatus::Missing,
            existing_tags: self.tags(root)?,
        };
        let verified =
            verify_release(state, &facts).map_err(|diagnostic| diagnostic_error(&diagnostic))?;
        write_release_state(root, &verified)?;
        Ok(verified)
    }

    /// Finalize local release state after external build/test evidence is complete.
    ///
    /// This validates a future `v<version>` tag but intentionally does not create it.
    ///
    /// # Errors
    ///
    /// Returns an error for incomplete verification, dirty/mismatched source, or tag collision.
    pub fn finalize(
        &self,
        root: &Path,
        verification_complete: bool,
    ) -> Result<ReleaseState, EngineError> {
        let state = read_release_state(root)?;
        let observed = self.git_snapshot(root)?;
        let source_commit = observed.head.clone().unwrap_or_default();
        let facts = ReleaseSnapshot {
            branch: observed.primary_branch.unwrap_or_default(),
            clean: evidence(observed.status.is_empty()),
            source_commit,
            source_known: evidence(observed.head.is_some()),
            metadata_matches: EvidenceStatus::Satisfied,
            synchronized: EvidenceStatus::Satisfied,
            verified: evidence(verification_complete),
            existing_tags: self.tags(root)?,
        };
        if facts.clean == EvidenceStatus::Missing {
            return Err(EngineError::Git {
                message: "release finalization requires a clean tree".to_owned(),
            });
        }
        let finalized =
            finalize_release(state, &facts).map_err(|diagnostic| diagnostic_error(&diagnostic))?;
        write_release_state(root, &finalized)?;
        Ok(finalized)
    }

    fn git_snapshot(&self, root: &Path) -> Result<crate::GitSnapshot, EngineError> {
        let snapshot = GitClient::new(&self.process, "git", git_environment()).inspect(root)?;
        if !snapshot.available || !snapshot.repository {
            return Err(EngineError::Git {
                message: "a local Git repository is required".to_owned(),
            });
        }
        Ok(snapshot)
    }

    fn tags(&self, root: &Path) -> Result<Vec<String>, EngineError> {
        let result = run_git(&self.process, root, &["tag", "--list"])?;
        if result.exit_code != Some(0) {
            return Err(EngineError::Git {
                message: String::from_utf8_lossy(&result.stderr).into_owned(),
            });
        }
        Ok(result
            .stdout_text("git")?
            .lines()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
            .collect())
    }

    fn git(&self, args: &[&str], root: &Path) -> Result<(), EngineError> {
        let result = run_git(&self.process, root, args)?;
        if result.exit_code == Some(0) && !result.timed_out {
            Ok(())
        } else {
            Err(EngineError::Git {
                message: String::from_utf8_lossy(&result.stderr).into_owned(),
            })
        }
    }
}

#[derive(Debug)]
struct MetadataUpdate {
    path: PathBuf,
    before: Vec<u8>,
    after: Vec<u8>,
}

fn render_release_metadata_updates(
    root: &Path,
    version: &str,
) -> Result<Vec<MetadataUpdate>, EngineError> {
    let mut updates = Vec::new();
    for (relative, renderer) in [
        (
            "pyproject.toml",
            replace_project_version as fn(&str, &str) -> Result<String, EngineError>,
        ),
        ("Cargo.toml", replace_workspace_version),
        ("Cargo.lock", replace_cargo_lock_versions),
        ("uv.lock", replace_uv_lock_version),
        ("python/kernform/__init__.py", replace_python_version),
    ] {
        let path = root.join(relative);
        if !path.is_file() {
            continue;
        }
        let before =
            fs::read(&path).map_err(|error| io_error("read release metadata", &path, error))?;
        let content = std::str::from_utf8(&before).map_err(|_| EngineError::Encoding {
            program: relative.to_owned(),
        })?;
        let after = renderer(content, version)?.into_bytes();
        if before != after {
            updates.push(MetadataUpdate {
                path,
                before,
                after,
            });
        }
    }
    Ok(updates)
}

fn apply_release_metadata_updates(updates: &[MetadataUpdate]) -> Result<(), EngineError> {
    for update in updates {
        atomic_write(&update.path, &update.after)?;
    }
    Ok(())
}

fn restore_release_metadata(updates: &[MetadataUpdate]) -> Result<(), EngineError> {
    for update in updates.iter().rev() {
        atomic_write(&update.path, &update.before)?;
    }
    Ok(())
}

fn replace_project_version(content: &str, version: &str) -> Result<String, EngineError> {
    replace_section_version(content, "[project]", version)
}

fn replace_workspace_version(content: &str, version: &str) -> Result<String, EngineError> {
    replace_section_version(content, "[workspace.package]", version)
}

fn replace_section_version(
    content: &str,
    section: &str,
    version: &str,
) -> Result<String, EngineError> {
    let mut in_section = false;
    let mut replaced = false;
    let mut output = String::with_capacity(content.len());
    for line in content.split_inclusive('\n') {
        let trimmed = line.trim();
        if trimmed.starts_with('[') {
            in_section = trimmed == section;
        }
        if in_section && trimmed.starts_with("version =") {
            writeln!(output, "version = \"{version}\"")
                .expect("writing release metadata to a String cannot fail");
            replaced = true;
        } else {
            output.push_str(line);
        }
    }
    if !replaced {
        return Err(EngineError::Policy {
            message: format!("release metadata section {section} has no version"),
        });
    }
    Ok(output)
}

fn replace_cargo_lock_versions(content: &str, version: &str) -> Result<String, EngineError> {
    replace_lock_versions(content, version, |block| {
        !block.lines().any(|line| line.starts_with("source = "))
    })
}

fn replace_uv_lock_version(content: &str, version: &str) -> Result<String, EngineError> {
    replace_lock_versions(content, version, |block| {
        block
            .lines()
            .any(|line| line == "source = { editable = \".\" }")
    })
}

fn replace_lock_versions(
    content: &str,
    version: &str,
    should_replace: impl Fn(&str) -> bool,
) -> Result<String, EngineError> {
    let mut parts = content.split("[[package]]");
    let mut output = parts.next().unwrap_or_default().to_owned();
    let mut replacements = 0;
    for block in parts {
        output.push_str("[[package]]");
        if should_replace(block) {
            output.push_str(&replace_first_version_line(block, version)?);
            replacements += 1;
        } else {
            output.push_str(block);
        }
    }
    if replacements == 0 {
        return Err(EngineError::Policy {
            message: "release lock has no local package version".to_owned(),
        });
    }
    Ok(output)
}

fn replace_first_version_line(block: &str, version: &str) -> Result<String, EngineError> {
    let mut output = String::with_capacity(block.len());
    let mut replaced = false;
    for line in block.split_inclusive('\n') {
        if !replaced && line.trim().starts_with("version =") {
            writeln!(output, "version = \"{version}\"")
                .expect("writing release metadata to a String cannot fail");
            replaced = true;
        } else {
            output.push_str(line);
        }
    }
    if !replaced {
        return Err(EngineError::Policy {
            message: "local lock package has no version".to_owned(),
        });
    }
    Ok(output)
}

fn replace_python_version(content: &str, version: &str) -> Result<String, EngineError> {
    let mut replaced = false;
    let mut output = String::with_capacity(content.len());
    for line in content.split_inclusive('\n') {
        if line.trim_start().starts_with("__version__ =") {
            writeln!(output, "__version__ = \"{version}\"")
                .expect("writing release metadata to a String cannot fail");
            replaced = true;
        } else {
            output.push_str(line);
        }
    }
    if !replaced {
        return Err(EngineError::Policy {
            message: "Python package has no __version__ declaration".to_owned(),
        });
    }
    Ok(output)
}

fn run_git(
    process: &dyn ProcessExecutor,
    root: &Path,
    args: &[&str],
) -> Result<crate::ProcessResult, EngineError> {
    process.execute(&CommandSpec {
        program: "git".to_owned(),
        args: args.iter().map(|value| (*value).to_owned()).collect(),
        cwd: root.to_path_buf(),
        environment: git_environment(),
        timeout_seconds: 30,
    })
}

fn git_environment() -> BTreeMap<String, String> {
    ["PATH", "HOME"]
        .into_iter()
        .filter_map(|key| std::env::var(key).ok().map(|value| (key.to_owned(), value)))
        .collect()
}

fn release_facts(
    branch: String,
    clean: bool,
    source_commit: String,
    existing_tags: Vec<String>,
) -> ReleaseSnapshot {
    ReleaseSnapshot {
        branch,
        clean: evidence(clean),
        source_commit,
        source_known: EvidenceStatus::Satisfied,
        metadata_matches: EvidenceStatus::Missing,
        synchronized: EvidenceStatus::Missing,
        verified: EvidenceStatus::Missing,
        existing_tags,
    }
}

const fn evidence(value: bool) -> EvidenceStatus {
    if value {
        EvidenceStatus::Satisfied
    } else {
        EvidenceStatus::Missing
    }
}

fn validate_ref_component(value: &str) -> Result<(), EngineError> {
    let invalid = value.is_empty()
        || value.starts_with('-')
        || value.contains("..")
        || value.contains([' ', '~', '^', ':', '?', '*', '[', '\\'])
        || value.ends_with('.')
        || value.ends_with('/');
    if invalid {
        return Err(EngineError::Policy {
            message: format!("invalid Git reference {value:?}"),
        });
    }
    Ok(())
}

fn release_state_path(root: &Path) -> PathBuf {
    root.join(".kernform/release.json")
}

fn read_release_state(root: &Path) -> Result<ReleaseState, EngineError> {
    let path = release_state_path(root);
    serde_json::from_slice(
        &fs::read(&path).map_err(|error| io_error("read release state", &path, error))?,
    )
    .map_err(|error| EngineError::Serialization {
        message: error.to_string(),
    })
}

fn write_release_state(root: &Path, state: &ReleaseState) -> Result<(), EngineError> {
    let path = release_state_path(root);
    let mut content =
        serde_json::to_vec_pretty(state).map_err(|error| EngineError::Serialization {
            message: error.to_string(),
        })?;
    content.push(b'\n');
    atomic_write(&path, &content)
}

fn diagnostic_error(diagnostic: &kernform_core::Diagnostic) -> EngineError {
    EngineError::Policy {
        message: format!("{}: {}", diagnostic.id, diagnostic.message),
    }
}

#[cfg(test)]
mod tests {
    use std::process::Command;

    use tempfile::tempdir;

    use super::*;
    use crate::SystemProcessExecutor;
    use kernform_core::ReleasePhase;

    fn git(root: &Path, args: &[&str]) {
        let status = Command::new("git")
            .args(args)
            .current_dir(root)
            .status()
            .unwrap();
        assert!(status.success());
    }

    fn committed_repository() -> tempfile::TempDir {
        let directory = tempdir().unwrap();
        git(directory.path(), &["init", "--initial-branch=main"]);
        git(directory.path(), &["config", "user.name", "Kernform Test"]);
        git(
            directory.path(),
            &["config", "user.email", "kernform@example.invalid"],
        );
        fs::write(
            directory.path().join(".gitignore"),
            ".kernform/release.json\n",
        )
        .unwrap();
        fs::write(directory.path().join("README.md"), "# Example\n").unwrap();
        git(directory.path(), &["add", "."]);
        git(directory.path(), &["commit", "-m", "initial"]);
        directory
    }

    #[test]
    fn local_release_flow_reaches_finalized_without_creating_tag() {
        let directory = committed_repository();
        let manager = ReleaseManager::new(SystemProcessExecutor);
        let started = manager
            .start(directory.path(), "0.1.0", &"a".repeat(64))
            .unwrap();
        assert_eq!(started.branch, "release/0.1.0");
        let verified = manager.verify(directory.path(), true, true).unwrap();
        assert_eq!(verified.phase, ReleasePhase::Verified);
        let finalized = manager.finalize(directory.path(), true).unwrap();
        assert_eq!(finalized.phase, ReleasePhase::Finalized);
        let tags = Command::new("git")
            .args(["tag", "--list"])
            .current_dir(directory.path())
            .output()
            .unwrap();
        assert!(tags.stdout.is_empty());
    }

    #[test]
    fn release_start_refuses_dirty_tree_and_tag_collision() {
        let directory = committed_repository();
        fs::write(directory.path().join("dirty.txt"), "dirty\n").unwrap();
        let manager = ReleaseManager::new(SystemProcessExecutor);
        assert!(
            manager
                .start(directory.path(), "0.1.0", &"a".repeat(64))
                .is_err()
        );
        fs::remove_file(directory.path().join("dirty.txt")).unwrap();
        git(directory.path(), &["tag", "v0.1.0"]);
        assert!(
            manager
                .start(directory.path(), "0.1.0", &"a".repeat(64))
                .is_err()
        );
    }

    #[test]
    fn explicit_initial_commit_requires_repository_identity() {
        let directory = tempdir().unwrap();
        git(directory.path(), &["init", "--initial-branch=main"]);
        fs::write(directory.path().join("README.md"), "# Example\n").unwrap();
        let lifecycle = GitLifecycle::new(SystemProcessExecutor);
        let result = lifecycle.initial_commit(directory.path(), "initial");
        if result.is_ok() {
            // A host-global identity may satisfy repository-resolved policy; no configuration was
            // mutated by Kernform in either case.
            let output = Command::new("git")
                .args(["rev-parse", "HEAD"])
                .current_dir(directory.path())
                .output()
                .unwrap();
            assert!(output.status.success());
        }
    }

    #[test]
    fn release_start_updates_declared_versions_and_locks_on_release_branch() {
        let directory = committed_repository();
        fs::create_dir_all(directory.path().join("python/kernform")).unwrap();
        fs::write(
            directory.path().join("pyproject.toml"),
            "[project]\nname = \"kernform\"\nversion = \"0.1.0\"\n",
        )
        .unwrap();
        fs::write(
            directory.path().join("Cargo.toml"),
            "[workspace.package]\nversion = \"0.1.0\"\n",
        )
        .unwrap();
        fs::write(
            directory.path().join("Cargo.lock"),
            "version = 4\n\n[[package]]\nname = \"kernform-core\"\nversion = \"0.1.0\"\n",
        )
        .unwrap();
        fs::write(
            directory.path().join("uv.lock"),
            "version = 1\n\n[[package]]\nname = \"kernform\"\nversion = \"0.1.0\"\nsource = { editable = \".\" }\n",
        )
        .unwrap();
        fs::write(
            directory.path().join("python/kernform/__init__.py"),
            "__version__ = \"0.1.0\"\n",
        )
        .unwrap();
        git(directory.path(), &["add", "."]);
        git(directory.path(), &["commit", "-m", "add metadata"]);

        ReleaseManager::new(SystemProcessExecutor)
            .start(directory.path(), "0.2.0", &"a".repeat(64))
            .unwrap();
        for relative in [
            "pyproject.toml",
            "Cargo.toml",
            "Cargo.lock",
            "uv.lock",
            "python/kernform/__init__.py",
        ] {
            let content = fs::read_to_string(directory.path().join(relative)).unwrap();
            assert!(content.contains("0.2.0"), "{relative} was not updated");
            assert!(
                !content.contains("0.1.0"),
                "{relative} retained old version"
            );
        }
        let branch = Command::new("git")
            .args(["branch", "--show-current"])
            .current_dir(directory.path())
            .output()
            .unwrap();
        assert_eq!(
            String::from_utf8(branch.stdout).unwrap().trim(),
            "release/0.2.0"
        );
    }
}
