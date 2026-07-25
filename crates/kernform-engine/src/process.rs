use std::collections::BTreeMap;
use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use wait_timeout::ChildExt;

use crate::{EngineError, error::io_error};

/// A structured process request. Shell command strings are not representable.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandSpec {
    pub program: String,
    pub args: Vec<String>,
    pub cwd: PathBuf,
    pub environment: BTreeMap<String, String>,
    pub timeout_seconds: u64,
}

/// Captured structured process result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessResult {
    pub exit_code: Option<i32>,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
    pub timed_out: bool,
    pub duration_millis: u128,
}

impl ProcessResult {
    /// Decode captured standard output as UTF-8.
    ///
    /// # Errors
    ///
    /// Returns an error when output is not valid UTF-8.
    pub fn stdout_text(&self, program: &str) -> Result<&str, EngineError> {
        std::str::from_utf8(&self.stdout).map_err(|_| EngineError::Encoding {
            program: program.to_owned(),
        })
    }

    /// Decode captured standard error as UTF-8.
    ///
    /// # Errors
    ///
    /// Returns an error when output is not valid UTF-8.
    pub fn stderr_text(&self, program: &str) -> Result<&str, EngineError> {
        std::str::from_utf8(&self.stderr).map_err(|_| EngineError::Encoding {
            program: program.to_owned(),
        })
    }
}

/// Injectable structured process boundary.
pub trait ProcessExecutor: Send + Sync {
    /// Execute one request.
    ///
    /// # Errors
    ///
    /// Returns an error when spawning, waiting, capturing output, or enforcing timeout fails.
    fn execute(&self, spec: &CommandSpec) -> Result<ProcessResult, EngineError>;
}

impl<T: ProcessExecutor + ?Sized> ProcessExecutor for &T {
    fn execute(&self, spec: &CommandSpec) -> Result<ProcessResult, EngineError> {
        (**self).execute(spec)
    }
}

/// Host process executor using `std::process::Command` without a shell.
#[derive(Debug, Default, Clone, Copy)]
pub struct SystemProcessExecutor;

impl ProcessExecutor for SystemProcessExecutor {
    fn execute(&self, spec: &CommandSpec) -> Result<ProcessResult, EngineError> {
        if spec.program.trim().is_empty() || spec.timeout_seconds == 0 {
            return Err(EngineError::Policy {
                message: "program and positive timeout are required".to_owned(),
            });
        }
        let started = Instant::now();
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .current_dir(&spec.cwd)
            .env_clear()
            .envs(&spec.environment)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut child = command.spawn().map_err(|error| EngineError::Process {
            program: spec.program.clone(),
            message: error.to_string(),
        })?;

        let stdout = child.stdout.take().ok_or_else(|| EngineError::Process {
            program: spec.program.clone(),
            message: "standard output pipe unavailable".to_owned(),
        })?;
        let stderr = child.stderr.take().ok_or_else(|| EngineError::Process {
            program: spec.program.clone(),
            message: "standard error pipe unavailable".to_owned(),
        })?;
        let stdout_reader = thread::spawn(move || read_all(stdout));
        let stderr_reader = thread::spawn(move || read_all(stderr));

        let timeout = Duration::from_secs(spec.timeout_seconds);
        let status = child
            .wait_timeout(timeout)
            .map_err(|error| io_error("wait for process", &spec.cwd, error))?;
        let timed_out = status.is_none();
        let status = if let Some(status) = status {
            status
        } else {
            child.kill().map_err(|error| EngineError::Process {
                program: spec.program.clone(),
                message: format!("failed to terminate timed-out process: {error}"),
            })?;
            child.wait().map_err(|error| EngineError::Process {
                program: spec.program.clone(),
                message: format!("failed to reap timed-out process: {error}"),
            })?
        };
        let stdout = join_reader(stdout_reader, &spec.program, "stdout")?;
        let stderr = join_reader(stderr_reader, &spec.program, "stderr")?;
        Ok(ProcessResult {
            exit_code: status.code(),
            stdout,
            stderr,
            timed_out,
            duration_millis: started.elapsed().as_millis(),
        })
    }
}

fn read_all(mut source: impl Read) -> std::io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    source.read_to_end(&mut bytes)?;
    Ok(bytes)
}

fn join_reader(
    reader: thread::JoinHandle<std::io::Result<Vec<u8>>>,
    program: &str,
    stream: &str,
) -> Result<Vec<u8>, EngineError> {
    reader
        .join()
        .map_err(|_| EngineError::Process {
            program: program.to_owned(),
            message: format!("{stream} reader panicked"),
        })?
        .map_err(|error| EngineError::Process {
            program: program.to_owned(),
            message: format!("failed to read {stream}: {error}"),
        })
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::*;

    fn spec(program: &str, args: &[&str], timeout_seconds: u64) -> CommandSpec {
        CommandSpec {
            program: program.to_owned(),
            args: args.iter().map(|value| (*value).to_owned()).collect(),
            cwd: Path::new("/").to_path_buf(),
            environment: BTreeMap::new(),
            timeout_seconds,
        }
    }

    #[test]
    fn captures_nonzero_exit_without_hiding_output() {
        let result = SystemProcessExecutor
            .execute(&spec("/usr/bin/printf", &["hello"], 2))
            .unwrap();
        assert_eq!(result.exit_code, Some(0));
        assert_eq!(result.stdout_text("printf").unwrap(), "hello");
        assert!(!result.timed_out);
    }

    #[test]
    fn enforces_timeout() {
        let result = SystemProcessExecutor
            .execute(&spec("/usr/bin/sleep", &["2"], 1))
            .unwrap();
        assert!(result.timed_out);
        assert_ne!(result.exit_code, Some(0));
    }
}
