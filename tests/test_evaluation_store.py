"""Tests for evaluation database configuration and schema setup."""

import pytest

import scripts.evaluation_store as evaluation_store


class _FakeConnection:
    def __init__(self):
        self.executed = []
        self.committed = False

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

    def execute(self, statement):
        self.executed.append(statement)


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
    schema = connection.executed[0]
    assert "CREATE TABLE IF NOT EXISTS evaluation_sessions" in schema
    assert "CREATE TABLE IF NOT EXISTS precheck_attempts" in schema
    assert "CREATE TABLE IF NOT EXISTS tester_judgements" in schema
    assert "CREATE TABLE IF NOT EXISTS notification_attempts" in schema
