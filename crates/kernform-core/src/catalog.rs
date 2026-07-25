use std::fmt::Write as _;

use semver::Version;
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::{CoreError, VersionCatalog};

/// Serialize a value to compact deterministic JSON.
///
/// # Errors
///
/// Returns an error when the value cannot be serialized.
pub fn canonical_json<T: Serialize>(value: &T) -> Result<String, CoreError> {
    serde_json::to_string(value).map_err(|error| CoreError::Serialization {
        message: error.to_string(),
    })
}

/// Select the newest stable semantic version from provider candidates.
///
/// # Errors
///
/// Returns an error when no stable semantic version is present.
pub fn select_newest_stable<I, S>(name: &str, candidates: I) -> Result<String, CoreError>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut stable = Vec::new();
    for candidate in candidates {
        let raw = candidate.as_ref();
        let normalized = raw.strip_prefix('v').unwrap_or(raw);
        if let Ok(version) = Version::parse(normalized)
            && version.pre.is_empty()
        {
            stable.push(version);
        }
    }
    stable.sort();
    stable
        .pop()
        .map(|version| version.to_string())
        .ok_or_else(|| CoreError::InvalidVersion {
            name: name.to_owned(),
            value: "no stable candidate".to_owned(),
        })
}

/// Validate exact stable versions and OCI digests in a catalog.
///
/// # Errors
///
/// Returns an error when a version is not exact and stable or an image digest is invalid.
pub fn validate_catalog(catalog: &VersionCatalog) -> Result<(), CoreError> {
    for (name, raw) in &catalog.versions {
        let version = Version::parse(raw).map_err(|_| CoreError::InvalidVersion {
            name: name.clone(),
            value: raw.clone(),
        })?;
        if !version.pre.is_empty() || raw.starts_with('v') {
            return Err(CoreError::InvalidVersion {
                name: name.clone(),
                value: raw.clone(),
            });
        }
    }
    for (name, digest) in &catalog.images {
        let valid = digest.len() == 71
            && digest.starts_with("sha256:")
            && digest[7..]
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase());
        if !valid {
            return Err(CoreError::InvalidDigest {
                name: name.clone(),
                digest: digest.clone(),
            });
        }
    }
    Ok(())
}

/// Compute and set a catalog hash over the same catalog with an empty hash field.
///
/// # Errors
///
/// Returns an error when serialization or catalog validation fails.
pub fn finalize_catalog(mut catalog: VersionCatalog) -> Result<VersionCatalog, CoreError> {
    catalog.hash.clear();
    let encoded = canonical_json(&catalog)?;
    catalog.hash = sha256_hex(encoded.as_bytes());
    validate_catalog(&catalog)?;
    Ok(catalog)
}

pub(crate) fn sha256_hex(content: &[u8]) -> String {
    let digest = Sha256::digest(content);
    let mut encoded = String::with_capacity(digest.len() * 2);
    for byte in digest {
        write!(&mut encoded, "{byte:02x}").expect("writing to a String cannot fail");
    }
    encoded
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::*;

    #[test]
    fn newest_stable_ignores_prereleases() {
        assert_eq!(
            select_newest_stable("python", ["3.14.5", "3.15.0b1", "v3.14.6"]).unwrap(),
            "3.14.6"
        );
    }

    #[test]
    fn catalog_hash_is_repeatable() {
        let catalog = VersionCatalog {
            id: "stable-test".to_owned(),
            hash: String::new(),
            resolved_at: "2026-07-17T12:00:00Z".to_owned(),
            source: "https://example.invalid/catalog".to_owned(),
            versions: BTreeMap::from([("python".to_owned(), "3.14.6".to_owned())]),
            images: BTreeMap::from([("python".to_owned(), format!("sha256:{}", "1".repeat(64)))]),
        };
        assert_eq!(
            finalize_catalog(catalog.clone()).unwrap(),
            finalize_catalog(catalog).unwrap()
        );
    }
}
