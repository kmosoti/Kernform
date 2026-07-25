use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use kernform_core::{
    CapabilitySpec, DocumentFormat, Ownership, RenderedFile, resolve_capabilities,
};
use semver::Version;
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use toml::Value as TomlValue;

use crate::{EngineError, error::io_error, filesystem::safe_join, merge_json, merge_toml};

/// One static file resource declared by a capability.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityFile {
    pub source: String,
    pub destination: String,
    pub ownership: Ownership,
}

/// One structured document patch declaration.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityPatch {
    pub destination: String,
    pub format: DocumentFormat,
    pub data: TomlValue,
}

/// Versioned, non-executable capability manifest.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityManifest {
    pub schema: String,
    pub id: String,
    pub version: Version,
    #[serde(default)]
    pub requires: BTreeSet<String>,
    #[serde(default)]
    pub conflicts: BTreeSet<String>,
    #[serde(default)]
    pub dependencies: BTreeMap<String, String>,
    #[serde(default)]
    pub files: Vec<CapabilityFile>,
    #[serde(default)]
    pub patches: Vec<CapabilityPatch>,
    #[serde(default)]
    pub tests: Vec<String>,
    #[serde(default)]
    pub conformance: Vec<String>,
}

/// Loaded capability and its canonical directory.
#[derive(Debug, Clone, PartialEq)]
pub struct LoadedCapability {
    pub manifest: CapabilityManifest,
    pub root: PathBuf,
}

/// Compile-time capability resources used by the installed native wheel.
#[derive(Debug, Clone, Copy)]
pub struct EmbeddedCapability {
    pub id: &'static str,
    pub manifest: &'static str,
    pub resources: &'static [(&'static str, &'static str)],
}

/// Load all immediate capability directories and reject malformed or unsafe declarations.
///
/// # Errors
///
/// Returns an error for unreadable directories/manifests, unsupported schemas, mismatched IDs,
/// unstable versions, duplicate IDs, unsafe resource paths, or invalid structured patches.
pub fn load_capabilities(root: &Path) -> Result<BTreeMap<String, LoadedCapability>, EngineError> {
    let mut entries = fs::read_dir(root)
        .map_err(|error| io_error("read capability catalog", root, error))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| io_error("read capability entry", root, error))?;
    entries.sort_by_key(std::fs::DirEntry::file_name);
    let mut loaded = BTreeMap::new();
    for entry in entries {
        let file_type = entry
            .file_type()
            .map_err(|error| io_error("inspect capability entry", entry.path(), error))?;
        if !file_type.is_dir() || !entry.path().join("capability.toml").is_file() {
            continue;
        }
        let capability = load_capability(&entry.path())?;
        let id = capability.manifest.id.clone();
        if loaded.insert(id.clone(), capability).is_some() {
            return Err(EngineError::Policy {
                message: format!("duplicate capability {id}"),
            });
        }
    }
    Ok(loaded)
}

/// Render a deterministic capability closure from static resources and restricted placeholders.
///
/// # Errors
///
/// Returns an error for graph failures, missing variables/resources, unsafe paths, symlinks,
/// conflicting destination content, or malformed templates.
pub fn render_capabilities(
    root: &Path,
    requested: &BTreeSet<String>,
    variables: &BTreeMap<String, String>,
) -> Result<Vec<RenderedFile>, EngineError> {
    let loaded = load_capabilities(root)?;
    let graph = loaded
        .iter()
        .map(|(id, capability)| {
            (
                id.clone(),
                CapabilitySpec {
                    id: id.clone(),
                    version: capability.manifest.version.clone(),
                    requires: capability.manifest.requires.clone(),
                    conflicts: capability.manifest.conflicts.clone(),
                },
            )
        })
        .collect();
    let ordered = resolve_capabilities(requested, &graph).map_err(|error| EngineError::Policy {
        message: error.to_string(),
    })?;
    let mut rendered = BTreeMap::<String, RenderedFile>::new();
    for id in ordered {
        let capability = &loaded[&id];
        for resource in &capability.manifest.files {
            let destination = expand_placeholders(&resource.destination, variables)?;
            safe_join(Path::new("/render-root"), Path::new(&destination))?;
            let source = safe_join(&capability.root, Path::new(&resource.source))?;
            let metadata = fs::symlink_metadata(&source)
                .map_err(|error| io_error("inspect capability resource", &source, error))?;
            if !metadata.is_file() || metadata.file_type().is_symlink() {
                return Err(EngineError::Policy {
                    message: format!(
                        "capability resource is not a regular file: {}",
                        source.display()
                    ),
                });
            }
            let content = fs::read_to_string(&source)
                .map_err(|error| io_error("read capability resource", &source, error))?;
            let file = RenderedFile {
                path: destination.clone(),
                content: expand_placeholders(&content, variables)?,
                ownership: resource.ownership,
            };
            if let Some(existing) = rendered.get(&destination)
                && existing != &file
            {
                return Err(EngineError::Policy {
                    message: format!("capabilities render conflicting destination {destination}"),
                });
            }
            rendered.insert(destination, file);
        }
        apply_capability_patches(&mut rendered, &capability.manifest.patches, variables)?;
    }
    Ok(rendered.into_values().collect())
}

/// Render the compile-time capability catalog embedded in the native wheel.
///
/// # Errors
///
/// Returns the same graph, template, path, and destination-conflict errors as the filesystem-backed
/// renderer, plus errors for a mismatched embedded resource table.
pub fn render_embedded_capabilities(
    embedded: &[EmbeddedCapability],
    requested: &BTreeSet<String>,
    variables: &BTreeMap<String, String>,
) -> Result<Vec<RenderedFile>, EngineError> {
    let mut manifests = BTreeMap::new();
    let mut resources = BTreeMap::new();
    for capability in embedded {
        let manifest: CapabilityManifest =
            toml::from_str(capability.manifest).map_err(|error| EngineError::Serialization {
                message: format!("embedded capability {}: {error}", capability.id),
            })?;
        validate_manifest_identity(&manifest, capability.id)?;
        if manifests
            .insert(capability.id.to_owned(), manifest)
            .is_some()
        {
            return Err(EngineError::Policy {
                message: format!("duplicate embedded capability {}", capability.id),
            });
        }
        resources.insert(
            capability.id,
            capability
                .resources
                .iter()
                .copied()
                .collect::<BTreeMap<_, _>>(),
        );
    }
    let graph = manifests
        .iter()
        .map(|(id, manifest)| {
            (
                id.clone(),
                CapabilitySpec {
                    id: id.clone(),
                    version: manifest.version.clone(),
                    requires: manifest.requires.clone(),
                    conflicts: manifest.conflicts.clone(),
                },
            )
        })
        .collect();
    let ordered = resolve_capabilities(requested, &graph).map_err(|error| EngineError::Policy {
        message: error.to_string(),
    })?;
    let mut rendered = BTreeMap::<String, RenderedFile>::new();
    for id in ordered {
        let manifest = &manifests[&id];
        let capability_resources = &resources[id.as_str()];
        for resource in &manifest.files {
            safe_join(Path::new("/embedded"), Path::new(&resource.source))?;
            let content = capability_resources
                .get(resource.source.as_str())
                .ok_or_else(|| EngineError::Policy {
                    message: format!(
                        "embedded capability {id} has no resource {}",
                        resource.source
                    ),
                })?;
            let destination = expand_placeholders(&resource.destination, variables)?;
            safe_join(Path::new("/render-root"), Path::new(&destination))?;
            let file = RenderedFile {
                path: destination.clone(),
                content: expand_placeholders(content, variables)?,
                ownership: resource.ownership,
            };
            if let Some(existing) = rendered.get(&destination)
                && existing != &file
            {
                return Err(EngineError::Policy {
                    message: format!("capabilities render conflicting destination {destination}"),
                });
            }
            rendered.insert(destination, file);
        }
        apply_capability_patches(&mut rendered, &manifest.patches, variables)?;
    }
    Ok(rendered.into_values().collect())
}

fn apply_capability_patches(
    rendered: &mut BTreeMap<String, RenderedFile>,
    patches: &[CapabilityPatch],
    variables: &BTreeMap<String, String>,
) -> Result<(), EngineError> {
    for patch in patches {
        let destination = expand_placeholders(&patch.destination, variables)?;
        safe_join(Path::new("/render-root"), Path::new(&destination))?;
        let expanded = expand_toml_value(&patch.data, variables)?;
        let target = rendered
            .get_mut(&destination)
            .ok_or_else(|| EngineError::Policy {
                message: format!("capability patch target is not rendered: {destination}"),
            })?;
        target.content = match patch.format {
            DocumentFormat::Toml => {
                let mut document: TomlValue = toml::from_str(&target.content).map_err(|error| {
                    EngineError::Serialization {
                        message: format!("parse TOML patch target {destination}: {error}"),
                    }
                })?;
                merge_toml(&mut document, &expanded)?;
                terminate_line(toml::to_string_pretty(&document).map_err(|error| {
                    EngineError::Serialization {
                        message: format!("render TOML patch target {destination}: {error}"),
                    }
                })?)
            }
            DocumentFormat::Json => {
                let mut document: JsonValue =
                    serde_json::from_str(&target.content).map_err(|error| {
                        EngineError::Serialization {
                            message: format!("parse JSON patch target {destination}: {error}"),
                        }
                    })?;
                let patch_document =
                    serde_json::to_value(expanded).map_err(|error| EngineError::Serialization {
                        message: format!("convert JSON patch for {destination}: {error}"),
                    })?;
                merge_json(&mut document, &patch_document)?;
                terminate_line(serde_json::to_string_pretty(&document).map_err(|error| {
                    EngineError::Serialization {
                        message: format!("render JSON patch target {destination}: {error}"),
                    }
                })?)
            }
        };
    }
    Ok(())
}

fn expand_toml_value(
    value: &TomlValue,
    variables: &BTreeMap<String, String>,
) -> Result<TomlValue, EngineError> {
    match value {
        TomlValue::String(value) => Ok(TomlValue::String(expand_placeholders(value, variables)?)),
        TomlValue::Array(values) => values
            .iter()
            .map(|value| expand_toml_value(value, variables))
            .collect::<Result<Vec<_>, _>>()
            .map(TomlValue::Array),
        TomlValue::Table(values) => {
            let mut expanded = toml::map::Map::new();
            for (key, value) in values {
                let key = expand_placeholders(key, variables)?;
                if expanded
                    .insert(key.clone(), expand_toml_value(value, variables)?)
                    .is_some()
                {
                    return Err(EngineError::Policy {
                        message: format!("capability patch expands duplicate key {key}"),
                    });
                }
            }
            Ok(TomlValue::Table(expanded))
        }
        scalar => Ok(scalar.clone()),
    }
}

fn terminate_line(mut content: String) -> String {
    if !content.ends_with('\n') {
        content.push('\n');
    }
    content
}

/// Expand only declared `{{ variable }}` placeholders.
///
/// # Errors
///
/// Returns an error for unknown, empty, nested, or unclosed placeholders.
pub fn expand_placeholders(
    template: &str,
    variables: &BTreeMap<String, String>,
) -> Result<String, EngineError> {
    let mut output = String::with_capacity(template.len());
    let mut remainder = template;
    while let Some(start) = remainder.find("{{") {
        output.push_str(&remainder[..start]);
        let after_start = &remainder[start + 2..];
        let end = after_start.find("}}").ok_or_else(|| EngineError::Policy {
            message: "unclosed template placeholder".to_owned(),
        })?;
        let name = after_start[..end].trim();
        if name.is_empty() || name.contains(['{', '}']) {
            return Err(EngineError::Policy {
                message: format!("invalid template placeholder {name:?}"),
            });
        }
        let value = variables.get(name).ok_or_else(|| EngineError::Policy {
            message: format!("unknown template placeholder {name:?}"),
        })?;
        output.push_str(value);
        remainder = &after_start[end + 2..];
    }
    if remainder.contains("}}") {
        return Err(EngineError::Policy {
            message: "template contains a closing delimiter without an opening delimiter"
                .to_owned(),
        });
    }
    output.push_str(remainder);
    Ok(output)
}

fn load_capability(root: &Path) -> Result<LoadedCapability, EngineError> {
    let path = root.join("capability.toml");
    let content = fs::read_to_string(&path)
        .map_err(|error| io_error("read capability manifest", &path, error))?;
    let manifest: CapabilityManifest =
        toml::from_str(&content).map_err(|error| EngineError::Serialization {
            message: format!("{}: {error}", path.display()),
        })?;
    let directory_id = root
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| EngineError::Policy {
            message: format!("capability directory is not UTF-8: {}", root.display()),
        })?;
    validate_manifest_identity(&manifest, directory_id)?;
    for file in &manifest.files {
        safe_join(root, Path::new(&file.source))?;
        safe_join(Path::new("/render-root"), Path::new(&file.destination))?;
    }
    for patch in &manifest.patches {
        safe_join(Path::new("/render-root"), Path::new(&patch.destination))?;
        if !patch.data.is_table() {
            return Err(EngineError::Policy {
                message: format!("capability patch for {} must be a table", patch.destination),
            });
        }
    }
    Ok(LoadedCapability {
        manifest,
        root: root.to_path_buf(),
    })
}

fn validate_manifest_identity(
    manifest: &CapabilityManifest,
    expected_id: &str,
) -> Result<(), EngineError> {
    if manifest.schema != "kernform.capability/v1"
        || manifest.id != expected_id
        || !manifest.version.pre.is_empty()
    {
        return Err(EngineError::Policy {
            message: format!("invalid capability identity for {expected_id}"),
        });
    }
    for file in &manifest.files {
        safe_join(Path::new("/capability"), Path::new(&file.source))?;
        safe_join(Path::new("/render-root"), Path::new(&file.destination))?;
    }
    for patch in &manifest.patches {
        safe_join(Path::new("/render-root"), Path::new(&patch.destination))?;
        if !patch.data.is_table() {
            return Err(EngineError::Policy {
                message: format!("capability patch for {} must be a table", patch.destination),
            });
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::io::Write as _;

    use tempfile::tempdir;

    use super::*;

    fn write_capability(root: &Path, manifest: &str, resource: &str) {
        fs::create_dir_all(root.join("resources")).unwrap();
        fs::write(root.join("capability.toml"), manifest).unwrap();
        fs::write(root.join("resources/file.txt"), resource).unwrap();
    }

    #[test]
    fn renders_static_resources_deterministically() {
        let directory = tempdir().unwrap();
        let root = directory.path().join("base");
        write_capability(
            &root,
            r#"
schema = "kernform.capability/v1"
id = "base"
version = "1.0.0"
tests = ["fast"]
conformance = ["KF-ARCH-001"]

[[files]]
source = "resources/file.txt"
destination = "src/{{ module_name }}/value.txt"
ownership = "generated"
"#,
            "project={{ project_name }}\n",
        );
        let variables = BTreeMap::from([
            ("module_name".to_owned(), "example".to_owned()),
            ("project_name".to_owned(), "example-project".to_owned()),
        ]);
        let first = render_capabilities(
            directory.path(),
            &BTreeSet::from(["base".to_owned()]),
            &variables,
        )
        .unwrap();
        let second = render_capabilities(
            directory.path(),
            &BTreeSet::from(["base".to_owned()]),
            &variables,
        )
        .unwrap();
        assert_eq!(first, second);
        assert_eq!(first[0].path, "src/example/value.txt");
    }

    #[test]
    fn composes_structured_patches_with_placeholder_expansion() {
        let directory = tempdir().unwrap();
        let base = directory.path().join("base");
        write_capability(
            &base,
            r#"
schema = "kernform.capability/v1"
id = "base"
version = "1.0.0"

[[files]]
source = "resources/file.txt"
destination = "pyproject.toml"
ownership = "managed"
"#,
            "[project]\nname = 'example'\nrequires-python = '>=3.14'\n",
        );
        let extension = directory.path().join("extension");
        fs::create_dir_all(&extension).unwrap();
        fs::write(
            extension.join("capability.toml"),
            r#"
schema = "kernform.capability/v1"
id = "extension"
version = "1.0.0"
requires = ["base"]

[[patches]]
destination = "pyproject.toml"
format = "toml"

[patches.data.project.scripts]
"{{ project_name }}" = "{{ module_name }}.cli:main"
"#,
        )
        .unwrap();
        let variables = BTreeMap::from([
            ("module_name".to_owned(), "example_package".to_owned()),
            ("project_name".to_owned(), "example-package".to_owned()),
        ]);

        let rendered = render_capabilities(
            directory.path(),
            &BTreeSet::from(["extension".to_owned()]),
            &variables,
        )
        .unwrap();
        let document: TomlValue = toml::from_str(&rendered[0].content).unwrap();
        assert_eq!(document["project"]["name"].as_str(), Some("example"));
        assert_eq!(
            document["project"]["scripts"]["example-package"].as_str(),
            Some("example_package.cli:main")
        );
    }

    #[test]
    fn rejects_path_escape_unknown_placeholder_and_script_field() {
        let directory = tempdir().unwrap();
        let escape = directory.path().join("escape");
        write_capability(
            &escape,
            r#"
schema = "kernform.capability/v1"
id = "escape"
version = "1.0.0"
script = "rm -rf"
"#,
            "value",
        );
        assert!(load_capabilities(directory.path()).is_err());
        assert!(expand_placeholders("{{ unknown }}", &BTreeMap::new()).is_err());

        let traversal = directory.path().join("traversal");
        fs::create_dir_all(&traversal).unwrap();
        let mut manifest = fs::File::create(traversal.join("capability.toml")).unwrap();
        writeln!(
            manifest,
            "schema = \"kernform.capability/v1\"\nid = \"traversal\"\nversion = \"1.0.0\"\n[[files]]\nsource = \"../secret\"\ndestination = \"file\"\nownership = \"generated\""
        )
        .unwrap();
        assert!(load_capabilities(directory.path()).is_err());
    }

    #[test]
    fn checked_in_capability_manifests_are_closed_and_safe() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../capabilities");
        let capabilities = load_capabilities(&root).unwrap();
        assert_eq!(
            capabilities.keys().map(String::as_str).collect::<Vec<_>>(),
            vec![
                "api",
                "ci",
                "cli",
                "locks-api",
                "locks-base",
                "nushell-agent",
                "nushell-human",
                "podman",
                "pyo3-bindings",
                "python-package",
                "release",
                "rust-core",
                "testing",
                "web-server",
            ]
        );
        assert!(
            capabilities
                .values()
                .all(|capability| capability.manifest.version.pre.is_empty())
        );
    }
}
