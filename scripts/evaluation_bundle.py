"""Portable evaluation-batch export and trusted import."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Mapping, Sequence

BUNDLE_VERSION = 1
MANIFEST_NAME = "manifest.json"


class BundleError(ValueError):
    """The bundle is malformed, unsupported, or failed integrity checks."""


def _safe_case_id(case_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", case_id).strip("._")
    return value or hashlib.sha256(case_id.encode()).hexdigest()[:16]


def _json_value(value):
    if isinstance(value, (bytes, bytearray)):
        raise BundleError("binary data must be represented as a bundle file")
    return value


def _normalise_file(file: Mapping[str, object]) -> tuple[dict, bytes]:
    data = file.get("bytes", b"")
    if isinstance(data, str):
        data = data.encode()
    if not isinstance(data, (bytes, bytearray)):
        raise BundleError("file bytes must be bytes")
    raw = bytes(data)
    metadata = {
        "role": str(file.get("role", "other")),
        "filename": str(file.get("filename", "uploaded")),
        "mime_type": str(file.get("mime_type", "application/octet-stream")),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "captured_at": str(file.get("captured_at", "")),
    }
    return metadata, raw


def export_evaluation_bundle(
    snapshots: Sequence[Mapping[str, object]], destination: str | Path,
    metadata: Mapping[str, object] | None = None,
) -> Path:
    """Write a self-contained, versioned zip without secrets."""
    cases = []
    entries = []
    for snapshot in snapshots:
        case_id = str(snapshot.get("case_id", "")).strip()
        if not case_id:
            raise BundleError("each snapshot requires case_id")
        directory = f"cases/{_safe_case_id(case_id)}"
        files = []
        for file in snapshot.get("files", ()):
            file_meta, raw = _normalise_file(file)
            name = Path(file_meta["filename"]).name or "uploaded"
            path = f"{directory}/{name}"
            if path in entries:
                raise BundleError(f"duplicate bundle path: {path}")
            entries.append(path)
            files.append({**file_meta, "path": path})
        result = {key: _json_value(value) for key, value in snapshot.items() if key != "files"}
        result_path = f"{directory}/result.json"
        if result_path in entries:
            raise BundleError(f"duplicate case: {case_id}")
        entries.append(result_path)
        cases.append({"case_id": case_id, "directory": directory, "result_path": result_path, "files": files})
    manifest = {"format": "ecn-evaluation-bundle", "version": BUNDLE_VERSION, "metadata": dict(metadata or {}), "cases": cases}
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))
        for snapshot, case in zip(snapshots, cases):
            result = {key: _json_value(value) for key, value in snapshot.items() if key != "files"}
            archive.writestr(case["result_path"], json.dumps(result, sort_keys=True, default=str))
            for file, file_meta in zip(snapshot.get("files", ()), case["files"]):
                data = file.get("bytes", b"")
                if isinstance(data, str):
                    data = data.encode()
                archive.writestr(file_meta["path"], bytes(data))
    return output


def _read_and_validate(bundle: str | Path):
    try:
        archive = zipfile.ZipFile(bundle)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BundleError("invalid zip bundle") from exc
    with archive:
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (KeyError, json.JSONDecodeError) as exc:
            raise BundleError("manifest.json is required and must be JSON") from exc
        if manifest.get("format") != "ecn-evaluation-bundle" or manifest.get("version") != BUNDLE_VERSION:
            raise BundleError("unsupported bundle format or version")
        imported = []
        seen = set()
        for case in manifest.get("cases", []):
            case_id = case.get("case_id")
            result_path = case.get("result_path")
            if not isinstance(case_id, str) or not isinstance(result_path, str) or case_id in seen:
                raise BundleError("invalid or duplicate case manifest")
            seen.add(case_id)
            try:
                result = json.loads(archive.read(result_path))
            except (KeyError, json.JSONDecodeError) as exc:
                raise BundleError(f"missing or invalid result for {case_id}") from exc
            files = []
            for file in case.get("files", []):
                path = file.get("path")
                try:
                    raw = archive.read(path)
                except KeyError as exc:
                    raise BundleError(f"missing file {path}") from exc
                actual = hashlib.sha256(raw).hexdigest()
                if actual != file.get("sha256") or len(raw) != file.get("size_bytes"):
                    raise BundleError(f"hash or size mismatch for {path}")
                files.append({**file, "bytes": raw})
            result["case_id"] = case_id
            imported.append((result, files))
        return manifest, imported


def import_evaluation_bundle(bundle: str | Path, destination) -> list[object]:
    """Verify all content, then import atomically through a store seam.

    ``destination`` may be an in-memory/test store exposing ``import_snapshot``
    or a DB connection exposing the same method via an adapter. No destination
    method is called until the entire zip has passed validation.
    """
    manifest, snapshots = _read_and_validate(bundle)
    importer = getattr(destination, "import_snapshot", None)
    if importer is None:
        raise TypeError("destination must expose import_snapshot(snapshot, files)")
    bundle_id = _bundle_id(manifest)
    imported_ids = getattr(destination, "_evaluation_bundle_ids", None)
    if imported_ids is None:
        imported_ids = set()
        try:
            setattr(destination, "_evaluation_bundle_ids", imported_ids)
        except Exception:
            imported_ids = None
    if imported_ids is not None and bundle_id in imported_ids:
        return []
    results = []
    try:
        for snapshot, files in snapshots:
            try:
                result = importer(snapshot, files, bundle_id=bundle_id)
            except TypeError:
                result = importer(snapshot, files)
            if result is not None:
                results.append(result)
        if imported_ids is not None:
            imported_ids.add(bundle_id)
        return results
    except Exception:
        # The destination owns its transaction/rollback. Do not mark a bundle
        # imported when any case failed.
        raise


def _bundle_id(manifest: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
