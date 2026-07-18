use std::collections::BTreeMap;

use kernform_core::VersionCatalog;

use crate::EngineError;

/// Injectable release and image provider boundary.
pub trait ReleaseProvider: Send + Sync {
    /// Return stable version candidates for one named tool or dependency.
    ///
    /// # Errors
    ///
    /// Returns an error when provider data is missing, stale, or unavailable.
    fn versions(&self, name: &str) -> Result<Vec<String>, EngineError>;

    /// Resolve an exact OCI digest for an image key.
    ///
    /// # Errors
    ///
    /// Returns an error when the digest is absent or invalid.
    fn image_digest(&self, name: &str) -> Result<String, EngineError>;
}

/// Versioned offline catalog provider with explicit staleness policy.
#[derive(Debug, Clone)]
pub struct OfflineReleaseProvider {
    catalog: VersionCatalog,
    age_days: u64,
    maximum_age_days: u64,
}

impl OfflineReleaseProvider {
    /// Construct an offline provider from already validated catalog data.
    #[must_use]
    pub const fn new(catalog: VersionCatalog, age_days: u64, maximum_age_days: u64) -> Self {
        Self {
            catalog,
            age_days,
            maximum_age_days,
        }
    }

    fn ensure_fresh(&self) -> Result<(), EngineError> {
        if self.age_days > self.maximum_age_days {
            return Err(EngineError::Policy {
                message: format!(
                    "offline catalog {} is stale: {} days exceeds {}",
                    self.catalog.id, self.age_days, self.maximum_age_days
                ),
            });
        }
        Ok(())
    }
}

impl ReleaseProvider for OfflineReleaseProvider {
    fn versions(&self, name: &str) -> Result<Vec<String>, EngineError> {
        self.ensure_fresh()?;
        self.catalog
            .versions
            .get(name)
            .cloned()
            .map(|version| vec![version])
            .ok_or_else(|| EngineError::Policy {
                message: format!("offline catalog has no version for {name}"),
            })
    }

    fn image_digest(&self, name: &str) -> Result<String, EngineError> {
        self.ensure_fresh()?;
        self.catalog
            .images
            .get(name)
            .cloned()
            .ok_or_else(|| EngineError::Policy {
                message: format!("offline catalog has no image digest for {name}"),
            })
    }
}

/// Convert provider pairs into a deterministically ordered map.
#[must_use]
pub fn ordered_values(
    values: impl IntoIterator<Item = (String, String)>,
) -> BTreeMap<String, String> {
    values.into_iter().collect()
}
