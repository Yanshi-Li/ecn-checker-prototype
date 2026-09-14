"""Run the existing ECN pipeline for ECN/BOM files matched by filename ID."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.batch_intake import build_batch_from_paths
from scripts.batch_orchestration import BatchCase, run_batch


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

    result = run_batch(prepared.batch, _executor_factory(args), report)
    print(f"BATCH STATUS: {result.status}")
    print(f"RESULTS: {dict(result.metrics.latest_counts)}")
    return 1 if result.status == "COMPLETED_WITH_ERRORS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
