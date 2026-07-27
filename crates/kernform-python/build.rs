use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

fn main() {
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("manifest dir"));
    let catalog = manifest_dir.join("../../capabilities");
    println!("cargo:rerun-if-changed={}", catalog.display());
    let mut directories = fs::read_dir(&catalog)
        .expect("read capability catalog")
        .collect::<Result<Vec<_>, _>>()
        .expect("read capability entries");
    directories.sort_by_key(std::fs::DirEntry::file_name);

    let mut generated = String::from(
        "use kernform_engine::EmbeddedCapability;\n\npub static BUILTIN_CAPABILITIES: &[EmbeddedCapability] = &[\n",
    );
    for directory in directories {
        if !directory.file_type().expect("capability type").is_dir() {
            continue;
        }
        let root = directory.path();
        let manifest = root.join("capability.toml");
        if !manifest.is_file() {
            continue;
        }
        let id = directory.file_name().to_string_lossy().into_owned();
        generated.push_str("    EmbeddedCapability {\n");
        writeln!(generated, "        id: {id:?},").expect("write generated source");
        writeln!(
            generated,
            "        manifest: include_str!({:?}),",
            manifest.display().to_string()
        )
        .expect("write generated source");
        generated.push_str("        resources: &[\n");
        for resource in collect_files(&root) {
            if resource == manifest {
                continue;
            }
            let relative = resource
                .strip_prefix(&root)
                .expect("resource under capability")
                .to_string_lossy()
                .replace('\\', "/");
            writeln!(
                generated,
                "            ({relative:?}, include_str!({:?})),",
                resource.display().to_string()
            )
            .expect("write generated source");
        }
        generated.push_str("        ],\n    },\n");
    }
    generated.push_str("];\n");
    let output =
        PathBuf::from(std::env::var("OUT_DIR").expect("out dir")).join("builtin_capabilities.rs");
    fs::write(output, generated).expect("write embedded capability catalog");

    let signatures = manifest_dir.join("../../signatures");
    println!("cargo:rerun-if-changed={}", signatures.display());
    let mut directories = fs::read_dir(&signatures)
        .expect("read signature catalog")
        .collect::<Result<Vec<_>, _>>()
        .expect("read signature entries");
    directories.sort_by_key(std::fs::DirEntry::file_name);
    let mut generated = String::from(
        "use kernform_engine::EmbeddedSignature;\n\npub static BUILTIN_SIGNATURES: &[EmbeddedSignature] = &[\n",
    );
    for directory in directories {
        if !directory.file_type().expect("signature type").is_dir() {
            continue;
        }
        let manifest = directory.path().join("signature.toml");
        if !manifest.is_file() {
            continue;
        }
        let id = directory.file_name().to_string_lossy().into_owned();
        generated.push_str("    EmbeddedSignature {\n");
        writeln!(generated, "        id: {id:?},").expect("write generated source");
        writeln!(
            generated,
            "        manifest: include_str!({:?}),",
            manifest.display().to_string()
        )
        .expect("write generated source");
        generated.push_str("    },\n");
    }
    generated.push_str("];\n");
    let output =
        PathBuf::from(std::env::var("OUT_DIR").expect("out dir")).join("builtin_signatures.rs");
    fs::write(output, generated).expect("write embedded signature catalog");
}

fn collect_files(root: &Path) -> Vec<PathBuf> {
    let mut entries = fs::read_dir(root)
        .expect("read capability resources")
        .collect::<Result<Vec<_>, _>>()
        .expect("read capability resource entries");
    entries.sort_by_key(std::fs::DirEntry::file_name);
    let mut files = Vec::new();
    for entry in entries {
        let path = entry.path();
        if entry.file_type().expect("resource type").is_dir() {
            files.extend(collect_files(&path));
        } else {
            files.push(path);
        }
    }
    files
}
