use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use kernform_core::{Signature, SignatureResolution, SignatureSpec, resolve_signatures};
use semver::Version;
use serde::{Deserialize, Serialize};

use crate::{EngineError, error::io_error};

/// Versioned, non-executable signature manifest.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SignatureManifest {
    pub schema: String,
    pub id: Signature,
    pub version: Version,
    #[serde(default)]
    pub implies: BTreeSet<Signature>,
    #[serde(default)]
    pub capabilities: BTreeSet<String>,
    #[serde(default)]
    pub executable: bool,
}

/// Loaded signature and its canonical directory.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LoadedSignature {
    pub manifest: SignatureManifest,
    pub root: PathBuf,
}

/// Compile-time signature manifest used by the installed native wheel.
#[derive(Debug, Clone, Copy)]
pub struct EmbeddedSignature {
    pub id: &'static str,
    pub manifest: &'static str,
}

/// Load and validate all immediate signature directories.
///
/// # Errors
///
/// Returns an error for unreadable or malformed manifests, unstable versions,
/// invalid identities, or duplicate signatures.
pub fn load_signatures(root: &Path) -> Result<BTreeMap<Signature, LoadedSignature>, EngineError> {
    let mut entries = fs::read_dir(root)
        .map_err(|error| io_error("read signature catalog", root, error))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| io_error("read signature entry", root, error))?;
    entries.sort_by_key(std::fs::DirEntry::file_name);
    let mut loaded = BTreeMap::new();
    for entry in entries {
        let file_type = entry
            .file_type()
            .map_err(|error| io_error("inspect signature entry", entry.path(), error))?;
        if !file_type.is_dir() || !entry.path().join("signature.toml").is_file() {
            continue;
        }
        let signature = load_signature(&entry.path())?;
        let id = signature.manifest.id;
        if loaded.insert(id, signature).is_some() {
            return Err(EngineError::Policy {
                message: format!("duplicate signature {id}"),
            });
        }
    }
    Ok(loaded)
}

/// Resolve the compile-time signature catalog embedded in the native wheel.
///
/// # Errors
///
/// Returns an error for malformed manifests or an invalid signature request.
pub fn resolve_embedded_signatures(
    embedded: &[EmbeddedSignature],
    requested: &BTreeSet<Signature>,
    default_signature: Option<Signature>,
) -> Result<SignatureResolution, EngineError> {
    let mut specs = BTreeMap::new();
    for signature in embedded {
        let manifest: SignatureManifest =
            toml::from_str(signature.manifest).map_err(|error| EngineError::Serialization {
                message: format!("embedded signature {}: {error}", signature.id),
            })?;
        validate_manifest_identity(&manifest, signature.id)?;
        let id = manifest.id;
        if specs.insert(id, to_spec(manifest)).is_some() {
            return Err(EngineError::Policy {
                message: format!("duplicate embedded signature {id}"),
            });
        }
    }
    resolve_signatures(requested, default_signature, &specs).map_err(|error| EngineError::Policy {
        message: error.to_string(),
    })
}

fn load_signature(root: &Path) -> Result<LoadedSignature, EngineError> {
    let path = root.join("signature.toml");
    let content = fs::read_to_string(&path)
        .map_err(|error| io_error("read signature manifest", &path, error))?;
    let manifest: SignatureManifest =
        toml::from_str(&content).map_err(|error| EngineError::Serialization {
            message: format!("{}: {error}", path.display()),
        })?;
    let directory_id = root
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| EngineError::Policy {
            message: format!("signature directory is not UTF-8: {}", root.display()),
        })?;
    validate_manifest_identity(&manifest, directory_id)?;
    Ok(LoadedSignature {
        manifest,
        root: root.to_path_buf(),
    })
}

fn validate_manifest_identity(
    manifest: &SignatureManifest,
    expected_id: &str,
) -> Result<(), EngineError> {
    if manifest.schema != "kernform.signature/v1"
        || manifest.id.to_string() != expected_id
        || !manifest.version.pre.is_empty()
    {
        return Err(EngineError::Policy {
            message: format!("invalid signature identity for {expected_id}"),
        });
    }
    Ok(())
}

fn to_spec(manifest: SignatureManifest) -> SignatureSpec {
    SignatureSpec {
        id: manifest.id,
        version: manifest.version,
        implies: manifest.implies,
        capabilities: manifest.capabilities,
        executable: manifest.executable,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checked_in_signature_manifests_are_closed_and_resolvable() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../signatures");
        let signatures = load_signatures(&root).unwrap();
        assert_eq!(
            signatures.keys().copied().collect::<Vec<_>>(),
            vec![
                Signature::Sdk,
                Signature::Cli,
                Signature::Api,
                Signature::InteractiveWeb,
                Signature::Daemon,
            ]
        );
        let specs = signatures
            .into_iter()
            .map(|(id, loaded)| (id, to_spec(loaded.manifest)))
            .collect();
        let resolution =
            resolve_signatures(&BTreeSet::from([Signature::InteractiveWeb]), None, &specs).unwrap();
        assert_eq!(
            resolution.default_signature,
            Some(Signature::InteractiveWeb)
        );
        assert!(resolution.capabilities.contains("web-server"));
        assert!(!resolution.capabilities.contains("locks-base"));
    }
}
