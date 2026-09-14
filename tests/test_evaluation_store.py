"""Tests for evaluation database configuration and schema setup."""

import pytest

import scripts.evaluation_store as evaluation_store


class _FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, rows=()):
        self.executed = []
        self.committed = False
        self.rows = iter(rows)

    class _Transaction:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.connection.committed = exc_type is None
            return False

    def transaction(self):
        return self._Transaction(self)

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if "RETURNING id" in statement:
            return _FakeCursor(next(self.rows))
        return _FakeCursor((1,))


def test_connect_uses_dedicated_local_database_configuration(monkeypatch):
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(evaluation_store.psycopg, "connect", fake_connect)

    result = evaluation_store.connect_evaluation_db(
        {"ECN_DB_PASSWORD": "not-shared", "ECN_DB_PORT": "5544"}
    )

    assert result is not None
    assert captured == {
        "host": "localhost",
        "port": 5544,
        "dbname": "ecn_prechecker_evaluation",
        "user": "ecn_app",
        "password": "not-shared",
    }


def test_connect_requires_a_database_password():
    with pytest.raises(RuntimeError, match="ECN_DB_PASSWORD"):
        evaluation_store.connect_evaluation_db({})


def test_initialise_schema_executes_schema_in_one_transaction():
    connection = _FakeConnection()

    evaluation_store.initialise_schema(connection)

    assert connection.committed
    assert len(connection.executed) == 1
    schema = connection.executed[0][0]

    assert "CREATE TABLE IF NOT EXISTS evaluation_sessions" in schema
    assert "CREATE TABLE IF NOT EXISTS precheck_attempts" in schema
    assert "CREATE TABLE IF NOT EXISTS tester_judgements" in schema
    assert "CREATE TABLE IF NOT EXISTS notification_attempts" in schema
    assert "CREATE TABLE IF NOT EXISTS evaluation_batches" in schema
    assert "CREATE TABLE IF NOT EXISTS logical_ecns" in schema
    assert "CREATE TABLE IF NOT EXISTS bom_inputs" in schema
    assert "CREATE TABLE IF NOT EXISTS precheck_cases" in schema


def test_create_batch_and_inputs_preserves_batch_relationships():
    connection = _FakeConnection(rows=[(11,), (21,), (31,), (31,)])

    batch_id = evaluation_store.create_evaluation_batch(connection, 7)
    ecn_id = evaluation_store.create_logical_ecn(
        connection, batch_id, "ECN-001", {"source_file": "ecn.csv"}
    )
    bom_id = evaluation_store.create_bom_input(
        connection, batch_id, "BOM-001", "PRESENT", {"source_file": "bom.csv"}
    )
    evaluation_store.assign_bom_input(connection, bom_id, ecn_id)

    assert (batch_id, ecn_id, bom_id) == (11, 21, 31)
    statements = [statement for statement, _ in connection.executed]
    assert any("INSERT INTO evaluation_batches" in statement for statement in statements)
    assert any("INSERT INTO logical_ecns" in statement for statement in statements)
    assert any("INSERT INTO bom_inputs" in statement for statement in statements)
    assert any("UPDATE bom_inputs" in statement for statement in statements)


def test_create_bom_input_rejects_unknown_bom_state():
    with pytest.raises(ValueError, match="bom_state"):
        evaluation_store.create_bom_input(object(), 1, "BOM-001", "MISSING")

# End of evaluation store tests.










