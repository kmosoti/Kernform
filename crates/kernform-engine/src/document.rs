use serde_json::Value as JsonValue;
use toml::Value as TomlValue;

use crate::EngineError;

/// Recursively merge a JSON object patch without removing unrelated keys.
///
/// # Errors
///
/// Returns an error when the patch attempts to merge an object into a non-object target.
pub fn merge_json(target: &mut JsonValue, patch: &JsonValue) -> Result<(), EngineError> {
    match (target, patch) {
        (JsonValue::Object(target), JsonValue::Object(patch)) => {
            for (key, value) in patch {
                match target.get_mut(key) {
                    Some(existing) if value.is_object() => merge_json(existing, value)?,
                    Some(existing) => *existing = value.clone(),
                    None => {
                        target.insert(key.clone(), value.clone());
                    }
                }
            }
            Ok(())
        }
        _ => Err(EngineError::Policy {
            message: "JSON semantic patch root must be an object".to_owned(),
        }),
    }
}

/// Recursively merge a TOML table patch without removing unrelated keys.
///
/// # Errors
///
/// Returns an error when the patch attempts to merge a table into a non-table target.
pub fn merge_toml(target: &mut TomlValue, patch: &TomlValue) -> Result<(), EngineError> {
    match (target, patch) {
        (TomlValue::Table(target), TomlValue::Table(patch)) => {
            for (key, value) in patch {
                match target.get_mut(key) {
                    Some(existing) if value.is_table() => merge_toml(existing, value)?,
                    Some(existing) => *existing = value.clone(),
                    None => {
                        target.insert(key.clone(), value.clone());
                    }
                }
            }
            Ok(())
        }
        _ => Err(EngineError::Policy {
            message: "TOML semantic patch root must be a table".to_owned(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn json_merge_preserves_unrelated_values() {
        let mut target = json!({"project": {"name": "example", "private": true}});
        merge_json(&mut target, &json!({"project": {"version": "1.0.0"}})).unwrap();
        assert_eq!(target["project"]["name"], "example");
        assert_eq!(target["project"]["version"], "1.0.0");
    }

    #[test]
    fn toml_merge_preserves_unrelated_values() {
        let mut target: TomlValue = toml::from_str("[project]\nname = 'example'\n").unwrap();
        let patch: TomlValue = toml::from_str("[project]\nversion = '1.0.0'\n").unwrap();
        merge_toml(&mut target, &patch).unwrap();
        assert_eq!(target["project"]["name"].as_str(), Some("example"));
        assert_eq!(target["project"]["version"].as_str(), Some("1.0.0"));
    }
}
