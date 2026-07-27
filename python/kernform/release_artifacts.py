"""Deterministic release bundle, checksum, SBOM, and provenance generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import cast

from kernform.container import container_context, container_operation
from kernform.process import run_checked

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def build_release_bundle(
    root: Path,
    *,
    version: str,
    source_commit: str,
    wheel_directory: Path,
    output_directory: Path,
) -> Path:
    """Build one byte-stable ZIP from an exact source commit and existing wheel."""
    canonical = root.resolve(strict=True)
    _validate_identity(version, source_commit)
    observed = run_checked(
        ("git", "rev-parse", "--verify", f"{source_commit}^{{commit}}"),
        cwd=canonical,
        timeout_seconds=30,
    ).stdout.strip()
    if observed != source_commit:
        raise ValueError("source commit does not resolve exactly")
    head = run_checked(
        ("git", "rev-parse", "--verify", "HEAD"),
        cwd=canonical,
        timeout_seconds=30,
    ).stdout.strip()
    if head != source_commit:
        raise ValueError("source commit is not the checked-out HEAD")
    tracked_status = run_checked(
        ("git", "status", "--porcelain=v1", "--untracked-files=no"),
        cwd=canonical,
        timeout_seconds=30,
    ).stdout.strip()
    if tracked_status:
        raise ValueError("release source contains uncommitted tracked changes")
    created = run_checked(
        ("git", "show", "-s", "--format=%cI", source_commit),
        cwd=canonical,
        timeout_seconds=30,
    ).stdout.strip()
    wheels = sorted(wheel_directory.resolve(strict=True).glob("kernform-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"expected exactly one Kernform wheel, found {len(wheels)}")
    if not wheels[0].name.startswith(f"kernform-{version}-"):
        raise ValueError("wheel version does not match the release version")
    source_distributions = sorted(wheel_directory.glob("kernform-*.tar.gz"))
    if len(source_distributions) != 1:
        raise ValueError(
            f"expected exactly one Kernform source distribution, found {len(source_distributions)}"
        )
    if source_distributions[0].name != f"kernform-{version}.tar.gz":
        raise ValueError("source distribution version does not match the release version")
    oci_archives = sorted(wheel_directory.glob("kernform-*-oci.tar"))
    if len(oci_archives) != 1:
        raise ValueError(f"expected exactly one Kernform OCI archive, found {len(oci_archives)}")
    if oci_archives[0].name != f"kernform-{version}-oci.tar":
        raise ValueError("OCI archive version does not match the release version")

    wheel_name = f"artifacts/{wheels[0].name}"
    payload: dict[str, bytes] = {
        wheel_name: wheels[0].read_bytes(),
        f"artifacts/{source_distributions[0].name}": source_distributions[0].read_bytes(),
        f"artifacts/{oci_archives[0].name}": oci_archives[0].read_bytes(),
        "locks/Cargo.lock": (canonical / "Cargo.lock").read_bytes(),
        "locks/uv.lock": (canonical / "uv.lock").read_bytes(),
        "catalog/stable-v1.json": (canonical / "fixtures/catalogs/stable-v1.json").read_bytes(),
    }
    catalog_value: object = json.loads(payload["catalog/stable-v1.json"])
    if not isinstance(catalog_value, dict):
        raise ValueError("catalog is not an object")
    catalog_document = cast(dict[str, object], catalog_value)
    catalog_value = catalog_document.get("catalog")
    if not isinstance(catalog_value, dict):
        raise ValueError("catalog has no catalog object")
    catalog = cast(dict[str, object], catalog_value)
    catalog_hash = catalog.get("hash")
    if not isinstance(catalog_hash, str):
        raise ValueError("catalog hash is missing")

    subjects = [
        {"name": name, "digest": {"sha256": _sha256(content)}}
        for name, content in sorted(payload.items())
    ]
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"kernform-{version}",
        "documentNamespace": (
            f"https://github.com/kmosoti/Kernform/releases/{version}/{source_commit}"
        ),
        "creationInfo": {
            "created": created,
            "creators": [f"Tool: kernform-{version}"],
        },
        "packages": [
            {
                "name": "kernform",
                "SPDXID": "SPDXRef-Package-kernform",
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": _sha256(payload[wheel_name]),
                    }
                ],
            }
        ],
    }
    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subjects,
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://github.com/kmosoti/Kernform/kernform.release/v1",
                "externalParameters": {"version": version},
                "internalParameters": {"catalog_hash": catalog_hash},
                "resolvedDependencies": [
                    {
                        "uri": "git+https://github.com/kmosoti/Kernform",
                        "digest": {"gitCommit": source_commit},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": "https://github.com/kmosoti/Kernform"},
                "metadata": {"invocationId": source_commit},
            },
        },
    }
    payload["metadata/sbom.spdx.json"] = _json_bytes(sbom)
    payload["metadata/provenance.intoto.json"] = _json_bytes(provenance)
    checksums = "".join(
        f"{_sha256(content)}  {name}\n" for name, content in sorted(payload.items())
    )
    payload["SHA256SUMS"] = checksums.encode()

    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"kernform-{version}.zip"
    timestamp = _zip_timestamp(created)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, content in sorted(payload.items()):
            info = zipfile.ZipInfo(name, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return destination


def verify_release_bundle(bundle: Path) -> dict[str, object]:
    """Verify safe names, uniqueness, and every declared bundle checksum."""
    with zipfile.ZipFile(bundle, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("release bundle contains duplicate entries")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"release bundle contains unsafe path: {name}")
        declared: dict[str, str] = {}
        for line in archive.read("SHA256SUMS").decode().splitlines():
            digest, name = line.split("  ", 1)
            declared[name] = digest
        observed = {name: _sha256(archive.read(name)) for name in names if name != "SHA256SUMS"}
    if declared != observed:
        raise ValueError("release bundle checksums do not match its content")
    return {
        "schema": "kernform.release-bundle/v1",
        "path": str(bundle),
        "sha256": _sha256(bundle.read_bytes()),
        "entries": sorted(names),
    }


def export_oci_image(root: Path, *, version: str, output_directory: Path) -> Path:
    """Build and export the exact runtime image once as an OCI archive."""
    if _VERSION.fullmatch(version) is None:
        raise ValueError("version must be an exact stable MAJOR.MINOR.PATCH value")
    canonical = root.resolve(strict=True)
    container_operation(canonical, "build")
    context = container_context(canonical)
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"kernform-{version}-oci.tar"
    run_checked(
        (
            "podman",
            "save",
            "--format",
            "oci-archive",
            "--output",
            str(destination),
            context.image,
        ),
        cwd=canonical,
        timeout_seconds=600,
    )
    return destination


def main() -> int:
    """Build or verify release artifacts from automation."""
    parser = argparse.ArgumentParser(prog="python -m kernform.release_artifacts")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--root", type=Path, default=Path.cwd())
    build.add_argument("--version", required=True)
    build.add_argument("--source-commit", required=True)
    build.add_argument("--wheel-directory", type=Path, required=True)
    build.add_argument("--output-directory", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    export_oci = commands.add_parser("export-oci")
    export_oci.add_argument("--root", type=Path, default=Path.cwd())
    export_oci.add_argument("--version", required=True)
    export_oci.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        bundle = build_release_bundle(
            args.root,
            version=args.version,
            source_commit=args.source_commit,
            wheel_directory=args.wheel_directory,
            output_directory=args.output_directory,
        )
        result = verify_release_bundle(bundle)
    elif args.command == "verify":
        result = verify_release_bundle(args.bundle)
    else:
        destination = export_oci_image(
            args.root,
            version=args.version,
            output_directory=args.output_directory,
        )
        result = {"schema": "kernform.oci-export/v1", "path": str(destination)}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _validate_identity(version: str, source_commit: str) -> None:
    if _VERSION.fullmatch(version) is None:
        raise ValueError("version must be an exact stable MAJOR.MINOR.PATCH value")
    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("source commit must be a full lowercase Git object ID")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _zip_timestamp(created: str) -> tuple[int, int, int, int, int, int]:
    value = datetime.fromisoformat(created.replace("Z", "+00:00"))
    return (value.year, value.month, value.day, value.hour, value.minute, value.second)


if __name__ == "__main__":
    raise SystemExit(main())
