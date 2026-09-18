"""Behavioral tests for normalized batch pre-check orchestration."""

import pytest

from scripts.batch_orchestration import (
    BomInput,
    BatchMappingError,
    LogicalEcnInput,
    NormalizedBatch,
    run_batch,
)


def _batch(*, bom_inputs=(), confirmation=True):
    return NormalizedBatch(
        logical_ecns=(
            LogicalEcnInput("ECN-1", {"ecn": "one"}, {"source_file": "a.csv"}),
            LogicalEcnInput("ECN-2", {"ecn": "two"}, {"source_file": "b.csv"}),
        ),
        bom_inputs=tuple(bom_inputs),
        mapping_confirmed=confirmation,
    )


def test_creates_ec_only_and_one_case_per_mapped_bom_and_reports_progress():
    batch = _batch(
        bom_inputs=(
            BomInput("BOM-1", "PRESENT", {"rows": [1]}, {"source_file": "bom.csv"}, "ECN-1"),
        )
    )
    seen = []

    def execute(case):
        seen.append((case.logical_ecn.key, case.bom.key if case.bom else None))
        return {"decision": "PASS", "findings": []}

    result = run_batch(batch, execute, progress_callback=lambda progress: seen.append(progress))

    assert [(case.logical_ecn.key, case.bom.key if case.bom else None) for case in result.cases] == [
        ("ECN-1", "BOM-1"),
        ("ECN-2", None),
    ]
    executed = [item for item in seen if isinstance(item, tuple)]
    assert executed == [("ECN-1", "BOM-1"), ("ECN-2", None)]
    assert result.status == "COMPLETED"
    assert result.metrics.latest_counts == {"PASS": 2, "FAIL": 0, "ERROR": 0}
    assert result.progress.completed == 2


def test_suggests_mapping_from_matching_identifier_and_requires_confirmation_for_temporary_keys():
    batch = NormalizedBatch(
        logical_ecns=(LogicalEcnInput("", {}, {"source_file": "ecn.csv", "record_location": "row 1"}),),
        bom_inputs=(BomInput("BOM-42", "EMPTY", {}, {}, suggested_ecn_key=None),),
        mapping_confirmed=False,
    )

    with pytest.raises(BatchMappingError, match="confirmation"):
        run_batch(batch, lambda case: {"decision": "PASS"})

    confirmed = batch.with_mappings({"BOM-42": batch.logical_ecns[0].key}, confirmed=True)
    result = run_batch(confirmed, lambda case: {"decision": "FAIL"})
    assert result.cases[0].bom.state == "EMPTY"
    assert result.cases[0].status == "FAIL"


def test_rejects_reused_bom_and_more_than_four_boms_before_execution():
    reused = _batch(
        bom_inputs=(
            BomInput("BOM-1", "PRESENT", {}, {}, "ECN-1"),
            BomInput("BOM-1", "PRESENT", {}, {}, "ECN-2"),
        ),
    ).with_mappings({"BOM-1": "ECN-1"}, confirmed=True)
    with pytest.raises(BatchMappingError, match="one ECN"):
        run_batch(reused, lambda case: {"decision": "PASS"})

    too_many = _batch(
        bom_inputs=tuple(
            BomInput(f"BOM-{i}", "PRESENT", {}, {}, "ECN-1") for i in range(5)
        )
    )
    with pytest.raises(BatchMappingError, match="four"):
        run_batch(too_many, lambda case: {"decision": "PASS"})


def test_continues_after_executor_error_and_rejects_invalid_decisions():
    batch = _batch()
    calls = []

    def execute(case):
        calls.append(case.logical_ecn.key)
        if case.logical_ecn.key == "ECN-1":
            raise RuntimeError("parser failed")
        return {"decision": "FAIL", "findings": [{"rule_id": "H01"}]}

    result = run_batch(batch, execute)

    assert calls == ["ECN-1", "ECN-2"]
    assert [case.status for case in result.cases] == ["ERROR", "FAIL"]
    assert result.status == "COMPLETED_WITH_ERRORS"
    assert result.metrics.latest_counts == {"PASS": 0, "FAIL": 1, "ERROR": 1}
    assert "parser failed" in result.cases[0].error

    invalid = run_batch(_batch(), lambda case: {"decision": "UNKNOWN"})
    assert all(case.status == "ERROR" for case in invalid.cases)
    assert all("PASS or FAIL" in case.error for case in invalid.cases)


def test_rerun_is_a_new_attempt_and_metrics_use_latest_case_result():
    batch = _batch()
    first = run_batch(batch, lambda case: {"decision": "FAIL"})
    rerun = first.rerun("ECN-1:ECN_ONLY", lambda case: {"decision": "PASS"})

    assert len(rerun.attempts) == 3
    assert rerun.latest_cases["ECN-1:ECN_ONLY"].status == "PASS"
    assert rerun.metrics.latest_counts == {"PASS": 1, "FAIL": 1, "ERROR": 0}
    assert rerun.metrics.rerun_count == 1
    assert rerun.metrics.recovery_rate == 1.0
