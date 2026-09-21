import pytest

from scripts.evaluation_auth import can_access_attempt, can_administer, can_review, hash_password, verify_password


def test_password_records_are_salted_and_verifiable():
    first = hash_password("correct horse")
    second = hash_password("correct horse")
    assert first != second
    assert verify_password("correct horse", first)
    assert not verify_password("wrong horse", first)
    assert not verify_password("correct horse", "not-a-password-record")


def test_roles_control_reviewer_and_assignment_access():
    assert can_review("reviewer")
    assert can_administer("administrator")
    assert can_access_attempt("reviewer", assigned=True)
    assert not can_access_attempt("reviewer", assigned=False)
    assert can_access_attempt("administrator", assigned=False)
    with pytest.raises(ValueError):
        can_review("unknown")
