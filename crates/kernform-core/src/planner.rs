use std::collections::{BTreeMap, BTreeSet};
use std::path::{Component, Path};

use crate::{
    CoreError, Diagnostic, Operation, Ownership, Plan, PlanIntent, ProjectIntent, RenderedFile,
    RepositorySnapshot, Severity, VersionCatalog, canonical_json, check_web_policy,
    validate_catalog,
};
use serde_json::json;

/// SHA-256 hash used for plan preconditions and managed state.
#[must_use]
pub fn file_hash(content: &str) -> String {
    crate::catalog::sha256_hex(content.as_bytes())
}

/// Produce an immutable deterministic initialization or adoption plan.
///
/// # Errors
///
/// Returns an error for invalid intent, catalog data, serialization, or unsafe paths.
pub fn plan_initialization(
    intent: ProjectIntent,
    snapshot: &RepositorySnapshot,
    catalog: VersionCatalog,
    mut desired_files: Vec<RenderedFile>,
) -> Result<Plan, CoreError> {
    validate_intent(&intent)?;
    validate_catalog(&catalog)?;
    desired_files.sort_by(|left, right| left.path.cmp(&right.path));

    let mut operations = Vec::new();
    let mut diagnostics = check_web_policy(&desired_files);
    for file in &desired_files {
        validate_relative_path(&file.path)?;
    }
    append_file_operations(snapshot, desired_files, &mut operations, &mut diagnostics);
    append_git_decision(&intent, snapshot, &mut operations, &mut diagnostics);
    operations.sort_by(|left, right| left.id().cmp(right.id()));
    diagnostics.sort_by(|left, right| {
        (
            left.id.as_str(),
            canonical_json(&left.context).unwrap_or_default(),
        )
            .cmp(&(
                right.id.as_str(),
                canonical_json(&right.context).unwrap_or_default(),
            ))
    });

    let mut plan = Plan {
        schema: "kernform.plan/v1".to_owned(),
        plan_id: String::new(),
        generator_version: crate::VERSION.to_owned(),
        intent: PlanIntent {
            name: intent.name,
            profile: intent.profile,
            capabilities: intent.capabilities,
            git: intent.git.enabled,
        },
        catalog,
        operations,
        diagnostics,
    };
    plan.plan_id = file_hash(&canonical_json(&plan)?);
    Ok(plan)
}

fn append_file_operations(
    snapshot: &RepositorySnapshot,
    desired_files: Vec<RenderedFile>,
    operations: &mut Vec<Operation>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let mut directories = BTreeSet::new();
    for file in desired_files {
        let desired_hash = file_hash(&file.content);
        match snapshot.files.get(&file.path) {
            None => {
                if let Some(parent) = Path::new(&file.path).parent() {
                    let mut current = Path::new("").to_path_buf();
                    for component in parent.components() {
                        if let Component::Normal(segment) = component {
                            current.push(segment);
                            directories.insert(current.to_string_lossy().replace('\\', "/"));
                        }
                    }
                }
                operations.push(Operation::WriteFile {
                    id: format!("write:{}", file.path),
                    path: file.path,
                    content: file.content,
                    ownership: file.ownership,
                    expected_hash: None,
                });
            }
            Some(existing) if existing.hash == desired_hash => {}
            Some(existing)
                if matches!(
                    existing.ownership.unwrap_or(Ownership::User),
                    Ownership::Managed | Ownership::Generated
                ) =>
            {
                operations.push(Operation::WriteFile {
                    id: format!("write:{}", file.path),
                    path: file.path,
                    content: file.content,
                    ownership: file.ownership,
                    expected_hash: Some(existing.hash.clone()),
                });
            }
            Some(existing) => diagnostics.push(Diagnostic {
                id: "KF-OWNERSHIP-001".to_owned(),
                severity: Severity::Error,
                message: "existing user-controlled content conflicts with generated intent"
                    .to_owned(),
                context: BTreeMap::from([
                    ("path".to_owned(), json!(file.path)),
                    ("actual_hash".to_owned(), json!(existing.hash)),
                    ("desired_hash".to_owned(), json!(desired_hash)),
                ]),
            }),
        }
    }

    for path in directories {
        operations.push(Operation::CreateDirectory {
            id: format!("directory:{path}"),
            path,
        });
    }
}

fn append_git_decision(
    intent: &ProjectIntent,
    snapshot: &RepositorySnapshot,
    operations: &mut Vec<Operation>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if intent.git.enabled && !snapshot.git {
        operations.push(Operation::InitGitRepository {
            id: "git:init".to_owned(),
            initial_branch: intent.git.initial_branch.clone(),
        });
    } else if intent.git.enabled
        && snapshot
            .primary_branch
            .as_deref()
            .is_some_and(|branch| branch != intent.git.initial_branch)
    {
        diagnostics.push(Diagnostic {
            id: "KF-GIT-001".to_owned(),
            severity: Severity::Warning,
            message: "existing primary branch is preserved during adoption".to_owned(),
            context: BTreeMap::from([
                ("actual_branch".to_owned(), json!(snapshot.primary_branch)),
                (
                    "requested_branch".to_owned(),
                    json!(intent.git.initial_branch),
                ),
            ]),
        });
    }
}

fn validate_intent(intent: &ProjectIntent) -> Result<(), CoreError> {
    let valid_name = !intent.name.is_empty()
        && intent.name.len() <= 63
        && intent.name.bytes().enumerate().all(|(index, byte)| {
            if index == 0 {
                byte.is_ascii_lowercase()
            } else {
                byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-'
            }
        });
    if !valid_name {
        return Err(CoreError::InvalidIntent {
            message: "project name must match ^[a-z][a-z0-9-]{0,62}$".to_owned(),
        });
    }
    if intent.git.initial_commit {
        return Err(CoreError::InvalidIntent {
            message: "initial commits require the explicit release/Git operation boundary"
                .to_owned(),
        });
    }
    Ok(())
}

fn validate_relative_path(raw: &str) -> Result<(), CoreError> {
    let path = Path::new(raw);
    let unsafe_path = raw.is_empty()
        || path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
        || path
            .components()
            .next()
            .is_some_and(|component| component.as_os_str() == ".git");
    if unsafe_path {
        return Err(CoreError::UnsafePath {
            path: raw.to_owned(),
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, BTreeSet};

    use crate::{GitIntent, Profile, SnapshotFile, finalize_catalog};

    use super::*;

    fn catalog() -> VersionCatalog {
        finalize_catalog(VersionCatalog {
            id: "stable-test".to_owned(),
            hash: String::new(),
            resolved_at: "2026-07-17T12:00:00Z".to_owned(),
            source: "https://example.invalid/catalog".to_owned(),
            versions: BTreeMap::from([
                ("python".to_owned(), "3.14.6".to_owned()),
                ("rust".to_owned(), "1.96.0".to_owned()),
            ]),
            images: BTreeMap::from([("python".to_owned(), format!("sha256:{}", "1".repeat(64)))]),
        })
        .unwrap()
    }

    fn intent() -> ProjectIntent {
        ProjectIntent {
            name: "example".to_owned(),
            profile: Profile::Library,
            capabilities: BTreeSet::from(["python-package".to_owned()]),
            git: GitIntent::default(),
        }
    }

    #[test]
    fn second_plan_is_empty() {
        let file = RenderedFile {
            path: "src/README.md".to_owned(),
            content: "# Example\n".to_owned(),
            ownership: Ownership::Seeded,
        };
        let first = plan_initialization(
            intent(),
            &RepositorySnapshot::default(),
            catalog(),
            vec![file.clone()],
        )
        .unwrap();
        assert!(!first.operations.is_empty());

        let snapshot = RepositorySnapshot {
            exists: true,
            git: true,
            primary_branch: Some("main".to_owned()),
            files: BTreeMap::from([(
                "src/README.md".to_owned(),
                SnapshotFile {
                    hash: file_hash(&file.content),
                    ownership: Some(Ownership::Seeded),
                },
            )]),
        };
        let second = plan_initialization(intent(), &snapshot, catalog(), vec![file]).unwrap();
        assert!(second.operations.is_empty());
        assert!(second.diagnostics.is_empty());
    }

    #[test]
    fn changed_user_file_is_reported_without_a_write() {
        let snapshot = RepositorySnapshot {
            exists: true,
            git: true,
            primary_branch: Some("feature/preserved".to_owned()),
            files: BTreeMap::from([(
                "README.md".to_owned(),
                SnapshotFile {
                    hash: file_hash("user content\n"),
                    ownership: Some(Ownership::User),
                },
            )]),
        };
        let plan = plan_initialization(
            intent(),
            &snapshot,
            catalog(),
            vec![RenderedFile {
                path: "README.md".to_owned(),
                content: "generated content\n".to_owned(),
                ownership: Ownership::Seeded,
            }],
        )
        .unwrap();
        assert!(plan.operations.is_empty());
        assert_eq!(
            plan.diagnostics
                .iter()
                .map(|diagnostic| diagnostic.id.as_str())
                .collect::<Vec<_>>(),
            vec!["KF-GIT-001", "KF-OWNERSHIP-001"]
        );
    }

    #[test]
    fn refuses_parent_traversal() {
        let error = plan_initialization(
            intent(),
            &RepositorySnapshot::default(),
            catalog(),
            vec![RenderedFile {
                path: "../escape".to_owned(),
                content: String::new(),
                ownership: Ownership::Generated,
            }],
        )
        .expect_err("parent traversal must fail");
        assert_eq!(
            error,
            CoreError::UnsafePath {
                path: "../escape".to_owned()
            }
        );
    }
}
