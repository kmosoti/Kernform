use std::collections::BTreeMap;
use std::path::Path;

use kernform_core::{VersionCatalog, finalize_catalog, select_newest_stable, validate_catalog};
use serde::{Deserialize, Serialize};

use crate::{EngineError, ReleaseProvider};

/// Versioned offline catalog document.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OfflineCatalogSnapshot {
    pub schema: String,
    pub maximum_age_days: u64,
    pub catalog: VersionCatalog,
}

/// Deterministic version and image keys to resolve from one provider snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolutionRequest {
    pub id: String,
    pub resolved_at: String,
    pub source: String,
    pub version_keys: Vec<String>,
    pub image_keys: Vec<String>,
}

/// Exact, serializable lock input retained by generated projects.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ToolchainLock {
    pub schema: String,
    pub catalog_id: String,
    pub catalog_hash: String,
    pub resolved_at: String,
    pub source: String,
    pub tools: BTreeMap<String, String>,
    pub images: BTreeMap<String, String>,
}

/// Resolve all requested values exactly once and freeze them into a hashed catalog.
///
/// The timestamp and source are explicit inputs so replaying the same provider response is
/// deterministic and apply never needs to query the provider again.
///
/// # Errors
///
/// Returns an error for provider failures, missing stable releases, prereleases, or invalid image
/// digests.
pub fn resolve_catalog(
    provider: &dyn ReleaseProvider,
    request: &ResolutionRequest,
) -> Result<VersionCatalog, EngineError> {
    let mut versions = BTreeMap::new();
    let mut version_keys = request.version_keys.clone();
    version_keys.sort();
    version_keys.dedup();
    for key in version_keys {
        let selected = select_newest_stable(&key, provider.versions(&key)?).map_err(|error| {
            EngineError::Policy {
                message: error.to_string(),
            }
        })?;
        versions.insert(key, selected);
    }

    let mut images = BTreeMap::new();
    let mut image_keys = request.image_keys.clone();
    image_keys.sort();
    image_keys.dedup();
    for key in image_keys {
        images.insert(key.clone(), provider.image_digest(&key)?);
    }

    finalize_catalog(VersionCatalog {
        id: request.id.clone(),
        hash: String::new(),
        resolved_at: request.resolved_at.clone(),
        source: request.source.clone(),
        versions,
        images,
    })
    .map_err(|error| EngineError::Policy {
        message: error.to_string(),
    })
}

/// Load and verify a versioned offline catalog snapshot.
///
/// # Errors
///
/// Returns an error if the file is unreadable, malformed, uses another schema, contains invalid
/// exact values, or does not match its recorded hash.
pub fn load_offline_catalog(path: &Path) -> Result<OfflineCatalogSnapshot, EngineError> {
    let content = std::fs::read(path).map_err(|error| EngineError::Io {
        operation: "read catalog",
        path: path.to_path_buf(),
        message: error.to_string(),
    })?;
    let snapshot: OfflineCatalogSnapshot =
        serde_json::from_slice(&content).map_err(|error| EngineError::Serialization {
            message: error.to_string(),
        })?;
    if snapshot.schema != "kernform.catalog/v1" {
        return Err(EngineError::Policy {
            message: format!("unsupported catalog schema {}", snapshot.schema),
        });
    }
    validate_catalog(&snapshot.catalog).map_err(|error| EngineError::Policy {
        message: error.to_string(),
    })?;
    let expected =
        finalize_catalog(snapshot.catalog.clone()).map_err(|error| EngineError::Policy {
            message: error.to_string(),
        })?;
    if expected.hash != snapshot.catalog.hash {
        return Err(EngineError::Policy {
            message: format!(
                "catalog hash mismatch: recorded {}, computed {}",
                snapshot.catalog.hash, expected.hash
            ),
        });
    }
    Ok(snapshot)
}

/// Render an exact catalog as deterministic TOML lock content.
///
/// # Errors
///
/// Returns an error if TOML serialization fails.
pub fn render_toolchain_lock(catalog: &VersionCatalog) -> Result<String, EngineError> {
    validate_catalog(catalog).map_err(|error| EngineError::Policy {
        message: error.to_string(),
    })?;
    let lock = ToolchainLock {
        schema: "kernform.toolchains/v1".to_owned(),
        catalog_id: catalog.id.clone(),
        catalog_hash: catalog.hash.clone(),
        resolved_at: catalog.resolved_at.clone(),
        source: catalog.source.clone(),
        tools: catalog.versions.clone(),
        images: catalog.images.clone(),
    };
    toml::to_string(&lock).map_err(|error| EngineError::Serialization {
        message: error.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::*;
    use crate::OfflineReleaseProvider;

    fn catalog() -> VersionCatalog {
        finalize_catalog(VersionCatalog {
            id: "stable-test".to_owned(),
            hash: String::new(),
            resolved_at: "2026-07-18T05:00:04Z".to_owned(),
            source: "offline-test".to_owned(),
            versions: BTreeMap::from([
                ("python".to_owned(), "3.14.6".to_owned()),
                ("rust".to_owned(), "1.96.0".to_owned()),
            ]),
            images: BTreeMap::from([(
                "python-slim-linux-amd64".to_owned(),
                format!("sha256:{}", "a".repeat(64)),
            )]),
        })
        .unwrap()
    }

    #[test]
    fn resolution_is_order_independent_and_exact() {
        let provider = OfflineReleaseProvider::new(catalog(), 0, 30);
        let first = resolve_catalog(
            &provider,
            &ResolutionRequest {
                id: "resolved".to_owned(),
                resolved_at: "2026-07-18T05:00:04Z".to_owned(),
                source: "offline-test".to_owned(),
                version_keys: vec!["rust".to_owned(), "python".to_owned()],
                image_keys: vec!["python-slim-linux-amd64".to_owned()],
            },
        )
        .unwrap();
        let second = resolve_catalog(
            &provider,
            &ResolutionRequest {
                id: "resolved".to_owned(),
                resolved_at: "2026-07-18T05:00:04Z".to_owned(),
                source: "offline-test".to_owned(),
                version_keys: vec!["python".to_owned(), "rust".to_owned()],
                image_keys: vec!["python-slim-linux-amd64".to_owned()],
            },
        )
        .unwrap();
        assert_eq!(first, second);
        assert_eq!(first.versions["python"], "3.14.6");
    }

    #[test]
    fn stale_offline_provider_refuses_resolution() {
        let provider = OfflineReleaseProvider::new(catalog(), 31, 30);
        let error = provider.versions("python").unwrap_err();
        assert!(error.to_string().contains("stale"));
    }

    #[test]
    fn lock_serialization_is_exact_and_repeatable() {
        let catalog = catalog();
        let first = render_toolchain_lock(&catalog).unwrap();
        let second = render_toolchain_lock(&catalog).unwrap();
        assert_eq!(first, second);
        assert!(first.contains("python = \"3.14.6\""));
        assert!(first.contains("sha256:"));
        assert!(!first.contains("latest"));
    }

    #[test]
    fn checked_in_offline_catalog_has_a_valid_hash() {
        let path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/catalogs/stable-v1.json");
        let snapshot = load_offline_catalog(&path).unwrap();
        assert_eq!(snapshot.schema, "kernform.catalog/v1");
        assert_eq!(snapshot.catalog.versions["python"], "3.14.6");
        assert_eq!(snapshot.maximum_age_days, 30);
    }
}
