use std::collections::{BTreeMap, BTreeSet};

use semver::Version;
use serde::{Deserialize, Serialize};

use crate::CoreError;

/// Declarative capability metadata used by pure graph resolution.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilitySpec {
    pub id: String,
    pub version: Version,
    pub requires: BTreeSet<String>,
    pub conflicts: BTreeSet<String>,
}

/// Resolve an exact deterministic topological capability order.
///
/// # Errors
///
/// Returns an error for unknown, cyclic, or conflicting capabilities.
pub fn resolve_capabilities(
    requested: &BTreeSet<String>,
    available: &BTreeMap<String, CapabilitySpec>,
) -> Result<Vec<String>, CoreError> {
    let mut visiting = Vec::new();
    let mut visited = BTreeSet::new();
    let mut ordered = Vec::new();
    for id in requested {
        visit(id, available, &mut visiting, &mut visited, &mut ordered)?;
    }

    let selected: BTreeSet<&str> = ordered.iter().map(String::as_str).collect();
    for id in &ordered {
        let spec = &available[id];
        for conflict in &spec.conflicts {
            if selected.contains(conflict.as_str()) {
                let (left, right) = if id <= conflict {
                    (id.clone(), conflict.clone())
                } else {
                    (conflict.clone(), id.clone())
                };
                return Err(CoreError::CapabilityConflict { left, right });
            }
        }
    }
    Ok(ordered)
}

fn visit(
    id: &str,
    available: &BTreeMap<String, CapabilitySpec>,
    visiting: &mut Vec<String>,
    visited: &mut BTreeSet<String>,
    ordered: &mut Vec<String>,
) -> Result<(), CoreError> {
    if visited.contains(id) {
        return Ok(());
    }
    if let Some(position) = visiting.iter().position(|current| current == id) {
        let mut cycle = visiting[position..].to_vec();
        cycle.push(id.to_owned());
        return Err(CoreError::CapabilityCycle {
            path: cycle.join(" -> "),
        });
    }
    let spec = available
        .get(id)
        .ok_or_else(|| CoreError::UnknownCapability { id: id.to_owned() })?;
    visiting.push(id.to_owned());
    for dependency in &spec.requires {
        visit(dependency, available, visiting, visited, ordered)?;
    }
    let removed = visiting.pop();
    debug_assert_eq!(removed.as_deref(), Some(id));
    visited.insert(id.to_owned());
    ordered.push(id.to_owned());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn capability(id: &str, requires: &[&str], conflicts: &[&str]) -> CapabilitySpec {
        CapabilitySpec {
            id: id.to_owned(),
            version: Version::new(1, 0, 0),
            requires: requires.iter().map(|value| (*value).to_owned()).collect(),
            conflicts: conflicts.iter().map(|value| (*value).to_owned()).collect(),
        }
    }

    #[test]
    fn dependencies_precede_consumers() {
        let available = BTreeMap::from([
            ("base".to_owned(), capability("base", &[], &[])),
            ("api".to_owned(), capability("api", &["base"], &[])),
        ]);
        let requested = BTreeSet::from(["api".to_owned()]);
        assert_eq!(
            resolve_capabilities(&requested, &available).unwrap(),
            ["base", "api"]
        );
    }

    #[test]
    fn cycles_are_explicit() {
        let available = BTreeMap::from([
            ("a".to_owned(), capability("a", &["b"], &[])),
            ("b".to_owned(), capability("b", &["a"], &[])),
        ]);
        let error = resolve_capabilities(&BTreeSet::from(["a".to_owned()]), &available)
            .expect_err("cycle must fail");
        assert_eq!(
            error,
            CoreError::CapabilityCycle {
                path: "a -> b -> a".to_owned()
            }
        );
    }

    #[test]
    fn conflicts_are_ordered() {
        let available = BTreeMap::from([
            ("a".to_owned(), capability("a", &[], &["b"])),
            ("b".to_owned(), capability("b", &[], &[])),
        ]);
        let requested = BTreeSet::from(["b".to_owned(), "a".to_owned()]);
        assert_eq!(
            resolve_capabilities(&requested, &available),
            Err(CoreError::CapabilityConflict {
                left: "a".to_owned(),
                right: "b".to_owned()
            })
        );
    }
}
