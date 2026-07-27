use std::collections::{BTreeMap, BTreeSet};

use semver::Version;
use serde::{Deserialize, Serialize};

use crate::{CoreError, Signature};

/// Declarative metadata for one composable project signature.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignatureSpec {
    pub id: Signature,
    pub version: Version,
    pub implies: BTreeSet<Signature>,
    pub capabilities: BTreeSet<String>,
    pub executable: bool,
}

/// Canonical signature closure consumed by planning and persisted in plans.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignatureResolution {
    pub requested: BTreeSet<Signature>,
    pub resolved: BTreeSet<Signature>,
    pub capabilities: BTreeSet<String>,
    pub default_signature: Option<Signature>,
}

/// Resolve signature implication, capability composition, and runtime selection.
///
/// `locks-api` supersedes `locks-base`, and `interactive-web` supersedes the
/// implied `api` executable when selecting a default runtime.
///
/// # Errors
///
/// Returns an error for an empty or unknown request, an implication cycle, an
/// invalid explicit runtime, or an ambiguous executable combination.
pub fn resolve_signatures(
    requested: &BTreeSet<Signature>,
    explicit_default: Option<Signature>,
    available: &BTreeMap<Signature, SignatureSpec>,
) -> Result<SignatureResolution, CoreError> {
    if requested.is_empty() {
        return Err(CoreError::InvalidIntent {
            message: "at least one project signature is required".to_owned(),
        });
    }

    let mut visiting = Vec::new();
    let mut resolved = BTreeSet::new();
    for signature in requested {
        visit_signature(*signature, available, &mut visiting, &mut resolved)?;
    }

    let mut capabilities = BTreeSet::new();
    for signature in &resolved {
        capabilities.extend(available[signature].capabilities.iter().cloned());
    }
    if capabilities.contains("locks-api") {
        capabilities.remove("locks-base");
    }

    let mut candidates = resolved
        .iter()
        .copied()
        .filter(|signature| available[signature].executable)
        .collect::<BTreeSet<_>>();
    if candidates.contains(&Signature::InteractiveWeb) {
        candidates.remove(&Signature::Api);
    }

    let default_signature = select_runtime(explicit_default, &candidates)?;
    Ok(SignatureResolution {
        requested: requested.clone(),
        resolved,
        capabilities,
        default_signature,
    })
}

fn visit_signature(
    signature: Signature,
    available: &BTreeMap<Signature, SignatureSpec>,
    visiting: &mut Vec<Signature>,
    resolved: &mut BTreeSet<Signature>,
) -> Result<(), CoreError> {
    if resolved.contains(&signature) {
        return Ok(());
    }
    if let Some(position) = visiting.iter().position(|current| *current == signature) {
        let mut cycle = visiting[position..]
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        cycle.push(signature.to_string());
        return Err(CoreError::SignatureCycle {
            path: cycle.join(" -> "),
        });
    }
    let spec = available
        .get(&signature)
        .ok_or_else(|| CoreError::UnknownSignature {
            id: signature.to_string(),
        })?;
    visiting.push(signature);
    for implied in &spec.implies {
        visit_signature(*implied, available, visiting, resolved)?;
    }
    let removed = visiting.pop();
    debug_assert_eq!(removed, Some(signature));
    resolved.insert(signature);
    Ok(())
}

fn select_runtime(
    explicit_default: Option<Signature>,
    candidates: &BTreeSet<Signature>,
) -> Result<Option<Signature>, CoreError> {
    if let Some(signature) = explicit_default {
        if !candidates.contains(&signature) {
            return Err(CoreError::InvalidRuntimeSignature {
                id: signature.to_string(),
            });
        }
        return Ok(Some(signature));
    }
    match candidates.len() {
        0 => Ok(None),
        1 => Ok(candidates.first().copied()),
        _ => Err(CoreError::AmbiguousRuntime {
            candidates: candidates
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>()
                .join(","),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec(
        id: Signature,
        implies: &[Signature],
        capabilities: &[&str],
        executable: bool,
    ) -> SignatureSpec {
        SignatureSpec {
            id,
            version: Version::new(1, 0, 0),
            implies: implies.iter().copied().collect(),
            capabilities: capabilities
                .iter()
                .map(|value| (*value).to_owned())
                .collect(),
            executable,
        }
    }

    fn catalog() -> BTreeMap<Signature, SignatureSpec> {
        BTreeMap::from([
            (
                Signature::Sdk,
                spec(Signature::Sdk, &[], &["locks-base", "testing"], false),
            ),
            (
                Signature::Cli,
                spec(Signature::Cli, &[Signature::Sdk], &["cli"], true),
            ),
            (
                Signature::Api,
                spec(
                    Signature::Api,
                    &[Signature::Sdk],
                    &["api", "locks-api"],
                    true,
                ),
            ),
            (
                Signature::InteractiveWeb,
                spec(
                    Signature::InteractiveWeb,
                    &[Signature::Api],
                    &["web-server"],
                    true,
                ),
            ),
            (
                Signature::Daemon,
                spec(Signature::Daemon, &[Signature::Sdk], &["daemon"], true),
            ),
        ])
    }

    #[test]
    fn api_composition_replaces_base_lock() {
        let resolution =
            resolve_signatures(&BTreeSet::from([Signature::Api]), None, &catalog()).unwrap();
        assert_eq!(
            resolution.resolved,
            BTreeSet::from([Signature::Sdk, Signature::Api])
        );
        assert!(!resolution.capabilities.contains("locks-base"));
        assert!(resolution.capabilities.contains("locks-api"));
        assert_eq!(resolution.default_signature, Some(Signature::Api));
    }

    #[test]
    fn interactive_web_shadows_api_runtime() {
        let resolution = resolve_signatures(
            &BTreeSet::from([Signature::InteractiveWeb]),
            None,
            &catalog(),
        )
        .unwrap();
        assert_eq!(
            resolution.default_signature,
            Some(Signature::InteractiveWeb)
        );
    }

    #[test]
    fn independent_runtimes_require_explicit_default() {
        let requested = BTreeSet::from([Signature::Cli, Signature::Daemon]);
        assert_eq!(
            resolve_signatures(&requested, None, &catalog()),
            Err(CoreError::AmbiguousRuntime {
                candidates: "cli,daemon".to_owned()
            })
        );
        let resolution =
            resolve_signatures(&requested, Some(Signature::Daemon), &catalog()).unwrap();
        assert_eq!(resolution.default_signature, Some(Signature::Daemon));
    }

    #[test]
    fn empty_request_is_rejected() {
        assert!(matches!(
            resolve_signatures(&BTreeSet::new(), None, &catalog()),
            Err(CoreError::InvalidIntent { .. })
        ));
    }
}
