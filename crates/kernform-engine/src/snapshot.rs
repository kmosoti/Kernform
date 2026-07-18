use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use kernform_core::{ManagedState, Ownership, RepositorySnapshot, SnapshotFile, StateFile};

use crate::{EngineError, GitClient, ProcessExecutor, error::io_error, hash_bytes};

/// Inspect a repository without following symlinks or reading `.git` content.
///
/// # Errors
///
/// Returns an error when repository metadata or file content cannot be read safely.
pub fn inspect_repository(
    root: &Path,
    state: Option<&ManagedState>,
) -> Result<RepositorySnapshot, EngineError> {
    if !root.exists() {
        return Ok(RepositorySnapshot::default());
    }
    if !root.is_dir() {
        return Err(EngineError::Policy {
            message: format!("repository root is not a directory: {}", root.display()),
        });
    }
    let recorded: BTreeMap<&str, &StateFile> = state
        .map(|state| {
            state
                .files
                .iter()
                .map(|file| (file.path.as_str(), file))
                .collect()
        })
        .unwrap_or_default();
    let mut paths = Vec::new();
    collect_files(root, root, &mut paths)?;
    paths.sort();
    let mut files = BTreeMap::new();
    for path in paths {
        let relative = path
            .strip_prefix(root)
            .map_err(|error| EngineError::Policy {
                message: error.to_string(),
            })?;
        let key = relative
            .to_str()
            .ok_or_else(|| EngineError::Policy {
                message: format!("non-UTF-8 repository path: {}", relative.display()),
            })?
            .replace('\\', "/");
        let metadata =
            fs::symlink_metadata(&path).map_err(|error| io_error("inspect file", &path, error))?;
        let (content, default_ownership) = if metadata.file_type().is_symlink() {
            (
                fs::read_link(&path)
                    .map_err(|error| io_error("read symlink", &path, error))?
                    .as_os_str()
                    .as_encoded_bytes()
                    .to_vec(),
                Ownership::External,
            )
        } else {
            (
                fs::read(&path).map_err(|error| io_error("read file", &path, error))?,
                Ownership::User,
            )
        };
        let hash = hash_bytes(&content);
        let effective_ownership = recorded
            .get(key.as_str())
            .map_or(default_ownership, |file| match file.ownership {
                Ownership::Seeded => Ownership::User,
                Ownership::Managed if file.hash != hash => Ownership::User,
                ownership => ownership,
            });
        files.insert(
            key.clone(),
            SnapshotFile {
                hash,
                ownership: Some(effective_ownership),
            },
        );
    }
    Ok(RepositorySnapshot {
        exists: true,
        git: root.join(".git").exists(),
        primary_branch: None,
        files,
    })
}

/// Inspect repository files and enrich existing Git repositories with their actual primary branch.
///
/// # Errors
///
/// Returns filesystem inspection errors or structured Git discovery failures.
pub fn inspect_repository_with_git<E: ProcessExecutor>(
    root: &Path,
    state: Option<&ManagedState>,
    executor: E,
) -> Result<RepositorySnapshot, EngineError> {
    let mut snapshot = inspect_repository(root, state)?;
    if snapshot.git {
        let environment = ["PATH", "HOME"]
            .into_iter()
            .filter_map(|key| std::env::var(key).ok().map(|value| (key.to_owned(), value)))
            .collect();
        let git = GitClient::new(executor, "git", environment).inspect(root)?;
        if !git.available || !git.repository {
            return Err(EngineError::Policy {
                message: "repository contains .git but Git inspection is unavailable".to_owned(),
            });
        }
        snapshot.primary_branch = git.primary_branch;
    }
    Ok(snapshot)
}

fn collect_files(
    root: &Path,
    current: &Path,
    output: &mut Vec<PathBuf>,
) -> Result<(), EngineError> {
    let mut entries = fs::read_dir(current)
        .map_err(|error| io_error("read directory", current, error))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| io_error("read directory entry", current, error))?;
    entries.sort_by_key(std::fs::DirEntry::file_name);
    for entry in entries {
        let path = entry.path();
        let relative = path
            .strip_prefix(root)
            .map_err(|error| EngineError::Policy {
                message: error.to_string(),
            })?;
        if relative == Path::new(".git")
            || relative.starts_with(Path::new(".git"))
            || relative.starts_with(Path::new(".kernform/transactions"))
        {
            continue;
        }
        let file_type = entry
            .file_type()
            .map_err(|error| io_error("inspect directory entry", &path, error))?;
        if file_type.is_dir() {
            collect_files(root, &path, output)?;
        } else {
            output.push(path);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use super::*;

    #[test]
    fn snapshot_excludes_git_and_transaction_journals() {
        let directory = tempdir().unwrap();
        fs::create_dir(directory.path().join(".git")).unwrap();
        fs::write(directory.path().join(".git/config"), b"secret").unwrap();
        fs::create_dir_all(directory.path().join(".kernform/transactions")).unwrap();
        fs::write(
            directory.path().join(".kernform/transactions/journal.json"),
            b"journal",
        )
        .unwrap();
        fs::write(directory.path().join("README.md"), b"read me").unwrap();
        let snapshot = inspect_repository(directory.path(), None).unwrap();
        assert!(snapshot.git);
        assert_eq!(snapshot.files.len(), 1);
        assert!(snapshot.files.contains_key("README.md"));
    }

    #[test]
    fn snapshot_treats_seeded_and_modified_managed_files_as_user_owned() {
        let directory = tempdir().unwrap();
        fs::write(directory.path().join("seeded.txt"), b"seeded edit").unwrap();
        fs::write(directory.path().join("managed.txt"), b"managed edit").unwrap();
        fs::write(directory.path().join("generated.txt"), b"generated edit").unwrap();
        let state = ManagedState {
            schema: "kernform.state/v1".to_owned(),
            generator_version: "0.1.0".to_owned(),
            project_root: "example".to_owned(),
            manifest_hash: hash_bytes(b""),
            toolchains: kernform_core::ToolchainState {
                catalog_id: "stable-test".to_owned(),
                catalog_hash: "0".repeat(64),
            },
            files: vec![
                StateFile {
                    path: "seeded.txt".to_owned(),
                    hash: hash_bytes(b"original seeded"),
                    ownership: Ownership::Seeded,
                },
                StateFile {
                    path: "managed.txt".to_owned(),
                    hash: hash_bytes(b"original managed"),
                    ownership: Ownership::Managed,
                },
                StateFile {
                    path: "generated.txt".to_owned(),
                    hash: hash_bytes(b"original generated"),
                    ownership: Ownership::Generated,
                },
            ],
        };

        let snapshot = inspect_repository(directory.path(), Some(&state)).unwrap();
        assert_eq!(
            snapshot.files["seeded.txt"].ownership,
            Some(Ownership::User)
        );
        assert_eq!(
            snapshot.files["managed.txt"].ownership,
            Some(Ownership::User)
        );
        assert_eq!(
            snapshot.files["generated.txt"].ownership,
            Some(Ownership::Generated)
        );
    }
}
