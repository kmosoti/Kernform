use std::collections::{BTreeMap, BTreeSet};

use kernform_core::{
    CapabilitySpec, GitIntent, Ownership, Profile, ProjectIntent, RenderedFile, RepositorySnapshot,
    VersionCatalog, finalize_catalog, plan_initialization, resolve_capabilities,
};
use proptest::prelude::*;
use semver::Version;

fn spec(id: &str, requires: &[&str]) -> CapabilitySpec {
    CapabilitySpec {
        id: id.to_owned(),
        version: Version::new(1, 0, 0),
        requires: requires.iter().map(|item| (*item).to_owned()).collect(),
        conflicts: BTreeSet::new(),
    }
}

proptest! {
    #[test]
    fn requested_order_cannot_change_resolution(reverse in any::<bool>()) {
        let available = BTreeMap::from([
            ("base".to_owned(), spec("base", &[])),
            ("cli".to_owned(), spec("cli", &["base"])),
            ("api".to_owned(), spec("api", &["base"])),
        ]);
        let input = if reverse {
            vec!["api".to_owned(), "cli".to_owned()]
        } else {
            vec!["cli".to_owned(), "api".to_owned()]
        };
        let requested: BTreeSet<String> = input.into_iter().collect();
        prop_assert_eq!(
            resolve_capabilities(&requested, &available).unwrap(),
            vec!["base", "api", "cli"]
        );
    }

    #[test]
    fn rendered_file_order_cannot_change_plan(reverse in any::<bool>()) {
        let mut files = vec![
            RenderedFile {
                path: "src/lib.rs".to_owned(),
                content: "pub fn value() -> u8 { 1 }\n".to_owned(),
                ownership: Ownership::Generated,
            },
            RenderedFile {
                path: "README.md".to_owned(),
                content: "# Example\n".to_owned(),
                ownership: Ownership::Seeded,
            },
        ];
        if reverse {
            files.reverse();
        }
        let catalog = finalize_catalog(VersionCatalog {
            id: "property".to_owned(),
            hash: String::new(),
            resolved_at: "2026-07-18T05:00:04Z".to_owned(),
            source: "fixture".to_owned(),
            versions: BTreeMap::from([("python".to_owned(), "3.14.6".to_owned())]),
            images: BTreeMap::new(),
        }).unwrap();
        let plan = plan_initialization(
            ProjectIntent {
                name: "example".to_owned(),
                profile: Profile::Library,
                capabilities: BTreeSet::new(),
                git: GitIntent::default(),
            },
            &RepositorySnapshot::default(),
            catalog,
            files,
        ).unwrap();
        let expected_ids = vec![
            "directory:src",
            "git:init",
            "write:README.md",
            "write:src/lib.rs",
        ];
        prop_assert_eq!(
            plan.operations
                .iter()
                .map(kernform_core::Operation::id)
                .collect::<Vec<_>>(),
            expected_ids
        );
    }
}
