use serde_json::Value;

use crate::{Artifact, CommandEnvelope, CommandStatus, Diagnostic};

/// Build a successful stable command envelope.
#[must_use]
pub fn command_success(
    command: impl Into<String>,
    result: Value,
    artifacts: Vec<Artifact>,
) -> CommandEnvelope {
    CommandEnvelope {
        schema: "kernform.command/v2".to_owned(),
        command: command.into(),
        status: CommandStatus::Success,
        exit_code: 0,
        result,
        diagnostics: Vec::new(),
        artifacts,
    }
}

/// Build a failed or refused stable command envelope.
#[must_use]
pub fn command_failure(
    command: impl Into<String>,
    exit_code: u8,
    refused: bool,
    diagnostics: Vec<Diagnostic>,
) -> CommandEnvelope {
    CommandEnvelope {
        schema: "kernform.command/v2".to_owned(),
        command: command.into(),
        status: if refused {
            CommandStatus::Refused
        } else {
            CommandStatus::Failure
        },
        exit_code,
        result: Value::Null,
        diagnostics,
        artifacts: Vec::new(),
    }
}
