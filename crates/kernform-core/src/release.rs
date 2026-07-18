use std::collections::BTreeMap;

use semver::Version;
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::{Diagnostic, ReleasePhase, ReleaseState, Severity};

/// Pure facts required to start or finalize a release.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReleaseSnapshot {
    pub branch: String,
    pub clean: EvidenceStatus,
    pub source_commit: String,
    pub source_known: EvidenceStatus,
    pub metadata_matches: EvidenceStatus,
    pub synchronized: EvidenceStatus,
    pub verified: EvidenceStatus,
    pub existing_tags: Vec<String>,
}

/// Binary evidence state with an explicit semantic name.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceStatus {
    Missing,
    Satisfied,
}

impl EvidenceStatus {
    const fn is_satisfied(self) -> bool {
        matches!(self, Self::Satisfied)
    }
}

/// Start a release state from a clean primary branch.
///
/// # Errors
///
/// Returns a diagnostic for an invalid version, non-main branch, or dirty repository.
pub fn start_release(
    version: &str,
    catalog_hash: &str,
    snapshot: &ReleaseSnapshot,
) -> Result<ReleaseState, Diagnostic> {
    if Version::parse(version).is_err() || version.contains('-') {
        return Err(release_diagnostic("version", version));
    }
    if snapshot.branch != "main" || !snapshot.clean.is_satisfied() {
        return Err(release_diagnostic("branch", &snapshot.branch));
    }
    Ok(ReleaseState {
        version: version.to_owned(),
        branch: format!("release/{version}"),
        source_commit: snapshot.source_commit.clone(),
        catalog_hash: catalog_hash.to_owned(),
        phase: ReleasePhase::Started,
    })
}

/// Advance a release only when source and metadata evidence agree.
///
/// # Errors
///
/// Returns a diagnostic when any required source, metadata, or synchronization evidence is absent.
pub fn verify_release(
    mut state: ReleaseState,
    snapshot: &ReleaseSnapshot,
) -> Result<ReleaseState, Diagnostic> {
    if !snapshot.clean.is_satisfied()
        || !snapshot.source_known.is_satisfied()
        || !snapshot.metadata_matches.is_satisfied()
        || !snapshot.synchronized.is_satisfied()
    {
        return Err(release_diagnostic("verification", &state.version));
    }
    state.source_commit.clone_from(&snapshot.source_commit);
    state.phase = ReleasePhase::Verified;
    Ok(state)
}

/// Finalize a verified release if the target tag does not already exist.
///
/// # Errors
///
/// Returns a diagnostic unless verification is complete and the target tag is unused.
pub fn finalize_release(
    mut state: ReleaseState,
    snapshot: &ReleaseSnapshot,
) -> Result<ReleaseState, Diagnostic> {
    let tag = format!("v{}", state.version);
    if state.phase != ReleasePhase::Verified
        || !snapshot.verified.is_satisfied()
        || !snapshot.source_known.is_satisfied()
        || snapshot.source_commit != state.source_commit
        || snapshot.existing_tags.contains(&tag)
    {
        return Err(release_diagnostic("finalize", &state.version));
    }
    state.phase = ReleasePhase::Finalized;
    Ok(state)
}

fn release_diagnostic(stage: &str, value: &str) -> Diagnostic {
    Diagnostic {
        id: "KF-GIT-001".to_owned(),
        severity: Severity::Error,
        message: "release invariant failed".to_owned(),
        context: BTreeMap::from([
            ("stage".to_owned(), json!(stage)),
            ("value".to_owned(), json!(value)),
        ]),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot() -> ReleaseSnapshot {
        ReleaseSnapshot {
            branch: "main".to_owned(),
            clean: EvidenceStatus::Satisfied,
            source_commit: "a".repeat(40),
            source_known: EvidenceStatus::Satisfied,
            metadata_matches: EvidenceStatus::Satisfied,
            synchronized: EvidenceStatus::Satisfied,
            verified: EvidenceStatus::Satisfied,
            existing_tags: Vec::new(),
        }
    }

    #[test]
    fn release_transitions_require_complete_evidence() {
        let started = start_release("0.1.0", &"b".repeat(64), &snapshot()).unwrap();
        assert_eq!(started.phase, ReleasePhase::Started);
        let verified = verify_release(started, &snapshot()).unwrap();
        assert_eq!(verified.phase, ReleasePhase::Verified);
        let finalized = finalize_release(verified, &snapshot()).unwrap();
        assert_eq!(finalized.phase, ReleasePhase::Finalized);
    }

    #[test]
    fn release_refuses_dirty_or_colliding_state() {
        let mut dirty = snapshot();
        dirty.clean = EvidenceStatus::Missing;
        assert!(start_release("0.1.0", &"b".repeat(64), &dirty).is_err());

        let verified = ReleaseState {
            version: "0.1.0".to_owned(),
            branch: "release/0.1.0".to_owned(),
            source_commit: "a".repeat(40),
            catalog_hash: "b".repeat(64),
            phase: ReleasePhase::Verified,
        };
        let mut colliding = snapshot();
        colliding.existing_tags.push("v0.1.0".to_owned());
        assert!(finalize_release(verified, &colliding).is_err());
    }
}
