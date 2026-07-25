use std::collections::BTreeMap;
use std::path::Path;

use serde_json::{Value, json};

use crate::{Diagnostic, RenderedFile, Severity};

/// Frozen non-web conformance families.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConformanceFamily {
    Architecture,
    Boundary,
    Git,
    Versions,
    Environment,
    Testing,
    State,
}

/// Result of one pure conformance observation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ConformanceCheck {
    pub family: ConformanceFamily,
    pub valid: bool,
}

/// Pure observations used by the stable conformance evaluator.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConformanceInput {
    pub checks: Vec<ConformanceCheck>,
    pub files: Vec<RenderedFile>,
}

/// Evaluate every frozen 0.1.0 conformance family in stable diagnostic order.
#[must_use]
pub fn evaluate_conformance(input: &ConformanceInput) -> Vec<Diagnostic> {
    let mut diagnostics = input
        .checks
        .iter()
        .filter(|check| !check.valid)
        .map(|check| {
            let (id, message) = check.family.failure();
            Diagnostic {
                id: id.to_owned(),
                severity: Severity::Error,
                message: message.to_owned(),
                context: BTreeMap::new(),
            }
        })
        .collect::<Vec<_>>();
    diagnostics.extend(check_web_policy(&input.files));
    diagnostics.sort_by(|left, right| diagnostic_key(left).cmp(&diagnostic_key(right)));
    diagnostics
}

impl ConformanceFamily {
    fn failure(self) -> (&'static str, &'static str) {
        match self {
            Self::Architecture => (
                "KF-ARCH-001",
                "architecture dependency direction is invalid",
            ),
            Self::Boundary => (
                "KF-BOUNDARY-001",
                "an adapter bypasses a declared application boundary",
            ),
            Self::Git => (
                "KF-GIT-001",
                "local Git state does not match project policy",
            ),
            Self::Versions => (
                "KF-VERSION-001",
                "toolchain or dependency input is not exactly pinned",
            ),
            Self::Environment => (
                "KF-ENV-001",
                "required local environment capability is unavailable",
            ),
            Self::Testing => ("KF-TEST-001", "required test tiers are not declared"),
            Self::State => (
                "KF-STATE-001",
                "managed state is invalid or requires recovery",
            ),
        }
    }
}

/// Check generated resources against the locked no-JavaScript policy.
#[must_use]
pub fn check_web_policy(files: &[RenderedFile]) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for file in files {
        let lower_path = file.path.to_ascii_lowercase();
        let lower_content = file.content.to_ascii_lowercase();
        let path = Path::new(&lower_path);
        let extension = path.extension().and_then(|value| value.to_str());
        let file_name = path.file_name().and_then(|value| value.to_str());
        let forbidden_path = matches!(extension, Some("js" | "mjs" | "cjs"))
            || matches!(
                file_name,
                Some("package.json" | "package-lock.json" | "pnpm-lock.yaml" | "yarn.lock")
            );
        let markup = matches!(extension, Some("html" | "htm" | "svg"));
        let forbidden_content = markup
            && (lower_content.contains("<script")
                || lower_content.contains("javascript:")
                || contains_inline_event_handler(&lower_content));
        if forbidden_path || forbidden_content {
            diagnostics.push(Diagnostic {
                id: "KF-WEB-001".to_owned(),
                severity: Severity::Error,
                message: "generated web resource violates JavaScript policy none".to_owned(),
                context: BTreeMap::from([("path".to_owned(), json!(file.path))]),
            });
        }
    }
    diagnostics.sort_by(|left, right| diagnostic_key(left).cmp(&diagnostic_key(right)));
    diagnostics
}

fn contains_inline_event_handler(content: &str) -> bool {
    let bytes = content.as_bytes();
    for index in 0..bytes.len().saturating_sub(4) {
        if bytes[index].is_ascii_whitespace() && bytes[index + 1..].starts_with(b"on") {
            let mut cursor = index + 3;
            while cursor < bytes.len() && bytes[cursor].is_ascii_alphabetic() {
                cursor += 1;
            }
            while cursor < bytes.len() && bytes[cursor].is_ascii_whitespace() {
                cursor += 1;
            }
            if cursor < bytes.len() && bytes[cursor] == b'=' {
                return true;
            }
        }
    }
    false
}

fn diagnostic_key(diagnostic: &Diagnostic) -> (&str, String) {
    (
        diagnostic.id.as_str(),
        diagnostic
            .context
            .get("path")
            .unwrap_or(&Value::Null)
            .to_string(),
    )
}

#[cfg(test)]
mod tests {
    use crate::Ownership;

    use super::*;

    #[test]
    fn rejects_script_and_event_handlers() {
        let files = vec![
            RenderedFile {
                path: "static/app.js".to_owned(),
                content: String::new(),
                ownership: Ownership::Generated,
            },
            RenderedFile {
                path: "templates/index.html".to_owned(),
                content: "<button onclick = \"submit()\">Send</button>".to_owned(),
                ownership: Ownership::Managed,
            },
        ];
        assert_eq!(check_web_policy(&files).len(), 2);
    }

    #[test]
    fn permits_server_rendered_html_and_css() {
        let files = vec![RenderedFile {
            path: "templates/index.html".to_owned(),
            content: "<main><form method=\"post\"><button>Send</button></form></main>".to_owned(),
            ownership: Ownership::Managed,
        }];
        assert!(check_web_policy(&files).is_empty());
    }

    #[test]
    fn all_stable_conformance_families_have_deterministic_ids() {
        let diagnostics = evaluate_conformance(&ConformanceInput {
            checks: [
                ConformanceFamily::Architecture,
                ConformanceFamily::Boundary,
                ConformanceFamily::Git,
                ConformanceFamily::Versions,
                ConformanceFamily::Environment,
                ConformanceFamily::Testing,
                ConformanceFamily::State,
            ]
            .into_iter()
            .map(|family| ConformanceCheck {
                family,
                valid: false,
            })
            .collect(),
            files: vec![RenderedFile {
                path: "package.json".to_owned(),
                content: "{}".to_owned(),
                ownership: Ownership::Generated,
            }],
        });
        assert_eq!(
            diagnostics
                .iter()
                .map(|diagnostic| diagnostic.id.as_str())
                .collect::<Vec<_>>(),
            vec![
                "KF-ARCH-001",
                "KF-BOUNDARY-001",
                "KF-ENV-001",
                "KF-GIT-001",
                "KF-STATE-001",
                "KF-TEST-001",
                "KF-VERSION-001",
                "KF-WEB-001",
            ]
        );
    }
}
