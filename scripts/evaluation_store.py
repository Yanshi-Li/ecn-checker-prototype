"""Persistence primitives for identified ECN evaluation sessions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

import psycopg


_SCHEMA_PATH = Path(__file__).with_name("evaluation_schema.sql")


def connect_evaluation_db(environ: Mapping[str, str] | None = None):
    """Open the local evaluation database using environment configuration."""
    environment = environ if environ is not None else os.environ
    password = environment.get("ECN_DB_PASSWORD")
    if not password:
        raise RuntimeError("ECN_DB_PASSWORD must be configured")

    return psycopg.connect(
        host=environment.get("ECN_DB_HOST", "localhost"),
        port=int(environment.get("ECN_DB_PORT", "5432")),
        dbname=environment.get(
            "ECN_DB_NAME", "ecn_prechecker_evaluation"
        ),
        user=environment.get("ECN_DB_USER", "ecn_app"),
        password=password,
    )


def initialise_schema(connection) -> None:
    """Create the evaluation tables if they do not already exist."""
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    with connection.transaction():
        connection.execute(schema)
