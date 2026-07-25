use std::collections::BTreeMap;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::{CommandSpec, EngineError, ProcessExecutor};

/// Read-only local Git state.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GitSnapshot {
    pub available: bool,
    pub repository: bool,
    pub primary_branch: Option<String>,
    pub head: Option<String>,
    pub remotes: Vec<String>,
    pub status: Vec<String>,
}

/// Local Git adapter using only structured process requests.
#[derive(Debug)]
pub struct GitClient<E> {
    executor: E,
    program: String,
    environment: BTreeMap<String, String>,
}

impl<E: ProcessExecutor> GitClient<E> {
    /// Construct a Git adapter with an explicit program and environment.
    #[must_use]
    pub fn new(
        executor: E,
        program: impl Into<String>,
        environment: BTreeMap<String, String>,
    ) -> Self {
        Self {
            executor,
            program: program.into(),
            environment,
        }
    }

    /// Inspect availability and repository state without mutation.
    ///
    /// # Errors
    ///
    /// Returns an error when Git cannot be executed or returns undecodable output.
    pub fn inspect(&self, root: &Path) -> Result<GitSnapshot, EngineError> {
        let version = self.run(root, &["--version"])?;
        if version.exit_code != Some(0) {
            return Ok(GitSnapshot {
                available: false,
                repository: false,
                primary_branch: None,
                head: None,
                remotes: Vec::new(),
                status: Vec::new(),
            });
        }
        let repository = root.join(".git").exists();
        if !repository {
            return Ok(GitSnapshot {
                available: true,
                repository: false,
                primary_branch: None,
                head: None,
                remotes: Vec::new(),
                status: Vec::new(),
            });
        }
        let branch = self.run(root, &["symbolic-ref", "--quiet", "--short", "HEAD"])?;
        let head = self.run(root, &["rev-parse", "--verify", "HEAD"])?;
        let remotes = self.run(root, &["remote"])?;
        let status = self.run(root, &["status", "--porcelain=v1"])?;
        Ok(GitSnapshot {
            available: true,
            repository: true,
            primary_branch: successful_lines(&branch, &self.program)?.into_iter().next(),
            head: successful_lines(&head, &self.program)?.into_iter().next(),
            remotes: successful_lines(&remotes, &self.program)?,
            status: successful_lines(&status, &self.program)?,
        })
    }

    fn run(&self, root: &Path, args: &[&str]) -> Result<crate::ProcessResult, EngineError> {
        self.executor.execute(&CommandSpec {
            program: self.program.clone(),
            args: args.iter().map(|value| (*value).to_owned()).collect(),
            cwd: root.to_path_buf(),
            environment: self.environment.clone(),
            timeout_seconds: 30,
        })
    }
}

fn successful_lines(
    result: &crate::ProcessResult,
    program: &str,
) -> Result<Vec<String>, EngineError> {
    if result.exit_code != Some(0) {
        return Ok(Vec::new());
    }
    Ok(result
        .stdout_text(program)?
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(str::to_owned)
        .collect())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use crate::SystemProcessExecutor;

    use super::*;

    #[test]
    fn inspects_unborn_repository_without_inventing_head() {
        let directory = tempdir().unwrap();
        let environment =
            BTreeMap::from([("PATH".to_owned(), std::env::var("PATH").unwrap_or_default())]);
        let init = std::process::Command::new("git")
            .args(["init", "--initial-branch=main"])
            .current_dir(directory.path())
            .output()
            .unwrap();
        assert!(init.status.success());
        fs::write(directory.path().join("README.md"), b"untracked").unwrap();
        let snapshot = GitClient::new(SystemProcessExecutor, "git", environment)
            .inspect(directory.path())
            .unwrap();
        assert_eq!(snapshot.primary_branch.as_deref(), Some("main"));
        assert!(snapshot.head.is_none());
        assert!(snapshot.remotes.is_empty());
        assert_eq!(snapshot.status, ["?? README.md"]);
    }
}
