"""Run the existing ECN pipeline for ECN/BOM files matched by filename ID."""

from __future__ import annotations

import argparse
import mimetypes
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.batch_intake import build_batch_from_paths
from scripts.batch_orchestration import BatchCase, run_batch
from scripts.evaluation_bundle import export_evaluation_bundle


def _paths(values: list[str], directories: list[str]) -> list[Path]:
    return [Path(value) for value in [*values, *directories]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run independent ECN checks matched by seven-digit filename identifiers"
    )
    parser.add_argument("--ecn", action="append", default=[], help="ECN file; repeat as needed")
    parser.add_argument("--ecn-dir", action="append", default=[], help="Folder containing ECN files")
    parser.add_argument("--bom", action="append", default=[], help="BOM file; repeat as needed")
    parser.add_argument("--bom-dir", action="append", default=[], help="Folder containing BOM files")
    parser.add_argument("--engineer-email", default="engineer@company.com")
    parser.add_argument("--ce-email", default="chief.engineer@company.com")
    parser.add_argument("--tester-email", default="tester@example.com")
    parser.add_argument("--export-bundle", type=Path, help="write an offline evaluation bundle")
    return parser.parse_args()


def _executor_factory(args: argparse.Namespace):
    from scripts import run_hybrid

    def execute(case: BatchCase):
        ecn_path = case.logical_ecn.metadata["source_file"]
        bom_path = case.bom.metadata["source_file"] if case.bom else None
        suffix_value = case.case_id.replace(":", "_")
        suffix = "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", suffix_value)
        pipeline_args = argparse.Namespace(
            ecn=str(ecn_path),
            bom=[str(bom_path)] if bom_path else [],
            engineer_email=args.engineer_email,
            ce_email=args.ce_email,
        )
        packet = run_hybrid.run_pipeline(pipeline_args, output_suffix=suffix)
        return {"decision": packet["gate"]["decision"], "packet": packet}

    return execute


def _snapshot(case: BatchCase) -> dict[str, object]:
    files = []
    for role, value in (("ecn", case.logical_ecn.metadata.get("source_file")), ("bom", case.bom.metadata.get("source_file") if case.bom else None)):
        if not value:
            continue
        path = Path(str(value))
        if path.exists():
            files.append({
                "role": role,
                "filename": path.name,
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "bytes": path.read_bytes(),
            })
    result = dict(case.result or {})
    return {
        "case_id": case.case_id,
        "decision": case.status if case.status in {"PASS", "FAIL"} else None,
        "status": case.status,
        "error": case.error,
        "started_at": case.started_at.isoformat() if case.started_at else None,
        "completed_at": case.completed_at.isoformat() if case.completed_at else None,
        "logical_ecn": dict(case.logical_ecn.payload),
        "bom": dict(case.bom.payload) if case.bom else None,
        "result": result,
        "packet": result.get("packet"),
        "files": files,
    }


def _postgres_sink(args: argparse.Namespace):
    if not os.environ.get("ECN_DB_PASSWORD"):
        return None, None
    from scripts.evaluation_store import connect_evaluation_db, initialise_schema, create_session, persist_evaluation_snapshot
    try:
        connection = connect_evaluation_db()
        initialise_schema(connection)
        session_id = create_session(connection, args.tester_email)
    except Exception as exc:
        print(f"PERSISTENCE WARNING: direct PostgreSQL unavailable ({type(exc).__name__}); validation continues.")
        return None, None

    def sink(case: BatchCase):
        snapshot = _snapshot(case)
        if snapshot["decision"] is None:
            return
        persist_evaluation_snapshot(connection, session_id, snapshot, snapshot["files"])

    return sink, connection


def main() -> int:
    args = parse_args()
    prepared = build_batch_from_paths(
        _paths(args.ecn, args.ecn_dir),
        _paths(args.bom, args.bom_dir),
    )
    for error in prepared.errors:
        print(f"INTAKE ERROR [{error.role}] {error.path}: {error.message}")
    if prepared.errors:
        print("No validation was started because batch intake was not safe to execute.")
        return 2

    def report(progress):
        print(
            f"{progress.completed}/{progress.total} complete: "
            f"{progress.current_case_id} "
            f"{dict(progress.counts)}"
        )

    snapshots = []
    postgres_sink, connection = _postgres_sink(args)

    def save(case: BatchCase):
        snapshot = _snapshot(case)
        snapshots.append(snapshot)
        if postgres_sink is not None:
            try:
                postgres_sink(case)
            except Exception as exc:
                print(f"PERSISTENCE WARNING: {type(exc).__name__}; validation result remains available.")

    result = run_batch(prepared.batch, _executor_factory(args), report, result_sink=save)
    if connection is not None:
        connection.close()
    if args.export_bundle:
        export_evaluation_bundle(snapshots, args.export_bundle, {"tester_email": args.tester_email, "source": "run_batch"})
        print(f"OFFLINE BUNDLE: {args.export_bundle}")
    print(f"BATCH STATUS: {result.status}")
    print(f"RESULTS: {dict(result.metrics.latest_counts)}")
    return 1 if result.status == "COMPLETED_WITH_ERRORS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
