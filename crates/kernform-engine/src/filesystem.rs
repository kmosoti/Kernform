use std::fmt::Write as _;
use std::fs::{self, File, OpenOptions};
use std::io::Write as _;
use std::path::{Component, Path, PathBuf};

use sha2::{Digest, Sha256};

use crate::{EngineError, error::io_error};

/// Compute a lowercase SHA-256 digest for arbitrary bytes.
#[must_use]
pub fn hash_bytes(content: &[u8]) -> String {
    let digest = Sha256::digest(content);
    let mut encoded = String::with_capacity(digest.len() * 2);
    for byte in digest {
        write!(&mut encoded, "{byte:02x}").expect("writing to a String cannot fail");
    }
    encoded
}

/// Validate and join a repository-relative effect path.
///
/// # Errors
///
/// Returns an error for empty, absolute, parent-traversing, or `.git`-owned paths.
pub fn safe_join(root: &Path, relative: &Path) -> Result<PathBuf, EngineError> {
    let unsafe_path = relative.as_os_str().is_empty()
        || relative.is_absolute()
        || relative.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
        || relative
            .components()
            .next()
            .is_some_and(|component| component.as_os_str() == ".git");
    if unsafe_path {
        return Err(EngineError::UnsafePath {
            path: relative.to_path_buf(),
        });
    }
    Ok(root.join(relative))
}

/// Write a file through a synchronized sibling and atomic rename.
///
/// # Errors
///
/// Returns an error when creating, writing, syncing, or renaming the file fails.
pub fn atomic_write(path: &Path, content: &[u8]) -> Result<(), EngineError> {
    let parent = path.parent().ok_or_else(|| EngineError::UnsafePath {
        path: path.to_path_buf(),
    })?;
    fs::create_dir_all(parent).map_err(|error| io_error("create parent", parent, error))?;
    let name = path
        .file_name()
        .ok_or_else(|| EngineError::UnsafePath {
            path: path.to_path_buf(),
        })?
        .to_string_lossy();
    let temporary = parent.join(format!(".{name}.kernform-{}.tmp", std::process::id()));
    let mut file = File::create(&temporary)
        .map_err(|error| io_error("create temporary file", &temporary, error))?;
    file.write_all(content)
        .map_err(|error| io_error("write temporary file", &temporary, error))?;
    file.sync_all()
        .map_err(|error| io_error("sync temporary file", &temporary, error))?;
    fs::rename(&temporary, path).map_err(|error| io_error("publish file", path, error))?;
    Ok(())
}

/// Exclusive mutation lock removed automatically on drop.
#[derive(Debug)]
pub struct FileLock {
    path: PathBuf,
    _file: File,
}

impl FileLock {
    /// Acquire a create-new lock containing the current process ID.
    ///
    /// # Errors
    ///
    /// Returns `LockHeld` when a lock already exists or an I/O error otherwise.
    pub fn acquire(path: &Path) -> Result<Self, EngineError> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| io_error("create lock directory", parent, error))?;
        }
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|error| {
                if error.kind() == std::io::ErrorKind::AlreadyExists {
                    EngineError::LockHeld {
                        path: path.to_path_buf(),
                    }
                } else {
                    io_error("acquire lock", path, error)
                }
            })?;
        writeln!(file, "{}", std::process::id())
            .map_err(|error| io_error("write lock", path, error))?;
        file.sync_all()
            .map_err(|error| io_error("sync lock", path, error))?;
        Ok(Self {
            path: path.to_path_buf(),
            _file: file,
        })
    }
}

impl Drop for FileLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

#[cfg(test)]
mod tests {
    use tempfile::tempdir;

    use super::*;

    #[test]
    fn atomic_write_replaces_complete_content() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("nested/file.txt");
        atomic_write(&path, b"first").unwrap();
        atomic_write(&path, b"second").unwrap();
        assert_eq!(fs::read(path).unwrap(), b"second");
    }

    #[test]
    fn lock_refuses_concurrent_owner() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("lock");
        let first = FileLock::acquire(&path).unwrap();
        assert!(matches!(
            FileLock::acquire(&path),
            Err(EngineError::LockHeld { .. })
        ));
        drop(first);
        assert!(FileLock::acquire(&path).is_ok());
    }

    #[test]
    fn safe_join_rejects_git_and_parent_paths() {
        assert!(safe_join(Path::new("/tmp/root"), Path::new("../escape")).is_err());
        assert!(safe_join(Path::new("/tmp/root"), Path::new(".git/config")).is_err());
    }
}
