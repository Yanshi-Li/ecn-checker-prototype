import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from context_engine import check_part_status, check_historical_conflicts


MOCK_PARTS = {
    "AB-1001": {"status": "OBSOLETE", "lifecycle_state": "End-of-Life", "revision": "C",
                "description": "Cap 10uF", "part_number": "AB-1001"},
    "AB-1002": {"status": "ACTIVE", "lifecycle_state": "Production", "revision": "A",
                "description": "Cap 25V", "part_number": "AB-1002"},
}

MOCK_HISTORY = [
    {"ecn_id": "ECN-OLD-001", "part_number": "AB-1001",
     "change_type": "modify", "date": "2023-01-01", "status": "APPROVED"},
]


def test_obsolete_part_detected():
    result = check_part_status("AB-1001", MOCK_PARTS)
    assert result["status"] == "OBSOLETE"
    assert result["found"] is True


def test_active_part_ok():
    result = check_part_status("AB-1002", MOCK_PARTS)
    assert result["status"] == "ACTIVE"


def test_part_not_found():
    result = check_part_status("ZZ-9999", MOCK_PARTS)
    assert result["found"] is False
    assert result["status"] == "NOT_FOUND"


def test_historical_conflict_found():
    conflicts = check_historical_conflicts("ECN-NEW-002", "AB-1001", MOCK_HISTORY)
    assert len(conflicts) == 1
    assert conflicts[0]["conflicting_ecn_id"] == "ECN-OLD-001"


def test_no_conflict_same_ecn():
    # Same ECN ID should not conflict with itself
    conflicts = check_historical_conflicts("ECN-OLD-001", "AB-1001", MOCK_HISTORY)
    assert conflicts == []


def test_no_conflict_different_part():
    conflicts = check_historical_conflicts("ECN-NEW-002", "AB-1002", MOCK_HISTORY)
    assert conflicts == []