"""Pure orchestration for independent, normalized ECN pre-check cases.

This module deliberately knows nothing about Streamlit, PostgreSQL, files, or
email.  Callers normalize intake first and provide the authoritative single-
case validator as an executor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Mapping, Sequence


BOM_STATES = frozenset({"ABSENT", "EMPTY", "PRESENT"})
CASE_STATUSES = frozenset({"PASS", "FAIL", "ERROR", "NOT_RUN"})


class BatchMappingError(ValueError):
    """Raised when a batch cannot be safely mapped before execution."""


def _temporary_key(prefix: str, metadata: Mapping[str, object]) -> str:
    source = str(metadata.get("source_file") or "source")
    location = str(metadata.get("source_location") or metadata.get("record_location") or "record")
    stable_source = f"{prefix}|{source}|{location}"
    digest = sha256(stable_source.encode("utf-8")).hexdigest()[:10]
    return f"TEMP-{prefix}-{source}#{location}-{digest}"


@dataclass(frozen=True)
class LogicalEcnInput:
    key: str
    payload: Mapping[str, object]
    metadata: Mapping[str, object]
    temporary: bool = False

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            object.__setattr__(self, "key", _temporary_key("ECN", self.metadata))
            object.__setattr__(self, "temporary", True)


@dataclass(frozen=True)
class BomInput:
    key: str
    state: str
    payload: Mapping[str, object]
    metadata: Mapping[str, object]
    suggested_ecn_key: str | None = None
    temporary: bool = False

    def __post_init__(self) -> None:
        state = self.state.strip().upper()
        if state not in BOM_STATES:
            raise ValueError("state must be ABSENT, EMPTY, or PRESENT")
        object.__setattr__(self, "state", state)
        if not self.key or not self.key.strip():
            object.__setattr__(self, "key", _temporary_key("BOM", self.metadata))
            object.__setattr__(self, "temporary", True)


@dataclass(frozen=True)
class NormalizedBatch:
    logical_ecns: Sequence[LogicalEcnInput]
    bom_inputs: Sequence[BomInput] = ()
    mappings: Mapping[str, str] | None = None
    mapping_confirmed: bool = False

    def with_mappings(self, mappings: Mapping[str, str], confirmed: bool = False) -> "NormalizedBatch":
        return replace(self, mappings=dict(mappings), mapping_confirmed=confirmed)


@dataclass(frozen=True)
class BatchCase:
    case_id: str
    logical_ecn: LogicalEcnInput
    bom: BomInput | None
    attempt_number: int = 1
    status: str = "NOT_RUN"
    result: Mapping[str, object] | None = None
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()


@dataclass(frozen=True)
class BatchProgress:
    total: int
    completed: int
    remaining: int
    current_case_id: str | None
    counts: Mapping[str, int]


@dataclass(frozen=True)
class BatchMetrics:
    latest_counts: Mapping[str, int]
    average_duration_seconds: float | None
    slowest_duration_seconds: float | None
    rerun_count: int
    recovery_rate: float | None


@dataclass(frozen=True)
class BatchResult:
    cases: tuple[BatchCase, ...]
    attempts: tuple[BatchCase, ...]
    status: str
    progress: BatchProgress
    metrics: BatchMetrics

    @property
    def latest_cases(self) -> dict[str, BatchCase]:
        latest: dict[str, BatchCase] = {}
        for case in self.attempts:
            latest[case.case_id] = case
        return latest

    def rerun(self, case_id: str, executor: Callable[[BatchCase], Mapping[str, object]]) -> "BatchResult":
        """Execute one existing case again while preserving the prior attempt."""
        prior = self.latest_cases.get(case_id)
        if prior is None:
            matches = [
                case for case in self.latest_cases.values()
                if case.logical_ecn.key == case_id
            ]
            if len(matches) == 1:
                prior = matches[0]
        if prior is None:
            raise KeyError(f"unknown case_id: {case_id}")
        rerun_case = _execute_case(
            replace(prior, attempt_number=prior.attempt_number + 1), executor
        )
        attempts = self.attempts + (rerun_case,)
        return _build_result(attempts)


def _mapping_for(batch: NormalizedBatch) -> dict[str, str]:
    if not batch.mapping_confirmed and (
        any(ecn.temporary for ecn in batch.logical_ecns)
        or any(bom.temporary for bom in batch.bom_inputs)
    ):
        raise BatchMappingError("temporary identifiers require mapping confirmation")

    ecns = {ecn.key: ecn for ecn in batch.logical_ecns}
    mappings: dict[str, str] = {}
    for bom in batch.bom_inputs:
        target = (batch.mappings or {}).get(bom.key, bom.suggested_ecn_key)
        if target:
            if target not in ecns:
                raise BatchMappingError(f"BOM {bom.key} maps to unknown ECN {target}")
            mappings[bom.key] = target
        elif bom.state != "ABSENT":
            if bom.temporary and not batch.mapping_confirmed:
                raise BatchMappingError("temporary identifiers require mapping confirmation")
            raise BatchMappingError(f"BOM {bom.key} has no ECN mapping")
    if len({bom.key for bom in batch.bom_inputs}) != len(batch.bom_inputs):
        raise BatchMappingError("a BOM input may be assigned to only one ECN")
    counts: dict[str, int] = {}
    for target in mappings.values():
        counts[target] = counts.get(target, 0) + 1
    if any(count > 4 for count in counts.values()):
        raise BatchMappingError("an ECN cannot have more than four BOM inputs")
    return mappings


def _make_cases(batch: NormalizedBatch) -> list[BatchCase]:
    mappings = _mapping_for(batch)
    cases: list[BatchCase] = []
    for ecn in batch.logical_ecns:
        assigned = [bom for bom in batch.bom_inputs if mappings.get(bom.key) == ecn.key]
        if not assigned:
            assigned = [None]
        for bom in assigned:
            suffix = bom.key if bom else "ECN_ONLY"
            cases.append(BatchCase(f"{ecn.key}:{suffix}", ecn, bom))
    return cases


def _execute_case(case: BatchCase, executor: Callable[[BatchCase], Mapping[str, object]]) -> BatchCase:
    started = datetime.now(timezone.utc)
    try:
        result = dict(executor(replace(case, started_at=started)))
        decision = str(result.get("decision", "")).strip().upper()
        if decision not in {"PASS", "FAIL"}:
            raise ValueError("executor decision must be PASS or FAIL")
        return replace(case, status=decision, result=result, started_at=started, completed_at=datetime.now(timezone.utc))
    except Exception as exc:
        return replace(case, status="ERROR", error=str(exc), started_at=started, completed_at=datetime.now(timezone.utc))


def _build_result(attempts: tuple[BatchCase, ...]) -> BatchResult:
    latest: dict[str, BatchCase] = {}
    for attempt in attempts:
        latest[attempt.case_id] = attempt
    counts = {status: sum(case.status == status for case in latest.values()) for status in ("PASS", "FAIL", "ERROR")}
    durations = [case.duration_seconds for case in attempts if case.duration_seconds is not None]
    rerun_count = sum(max(0, case.attempt_number - 1) for case in attempts)
    recoveries = sum(
        case.attempt_number > 1 and case.status == "PASS"
        and any(old.case_id == case.case_id and old.status == "FAIL" for old in attempts)
        for case in attempts
    )
    failed_before_rerun = sum(
        any(old.case_id == case_id and old.status == "FAIL" and old.attempt_number < latest_case.attempt_number for old in attempts)
        for case_id, latest_case in latest.items()
    )
    metrics = BatchMetrics(counts, sum(durations) / len(durations) if durations else None, max(durations) if durations else None, rerun_count, recoveries / failed_before_rerun if failed_before_rerun else None)
    completed = len(attempts)
    progress = BatchProgress(len(latest), completed, max(0, len(latest) - completed), None, counts)
    status = "COMPLETED_WITH_ERRORS" if counts["ERROR"] else "COMPLETED"
    return BatchResult(tuple(latest.values()), attempts, status, progress, metrics)


def run_batch(
    batch: NormalizedBatch,
    executor: Callable[[BatchCase], Mapping[str, object]],
    progress_callback: Callable[[BatchProgress], None] | None = None,
) -> BatchResult:
    """Validate mappings, execute independent cases, and continue after errors."""
    cases = _make_cases(batch)
    attempts: list[BatchCase] = []
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
    total = len(cases)
    for index, case in enumerate(cases, start=1):
        current = _execute_case(case, executor)
        attempts.append(current)
        counts[current.status] += 1
        if progress_callback:
            progress_callback(BatchProgress(total, index, total - index, current.case_id, dict(counts)))
    return _build_result(tuple(attempts))
