# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
from TCLIService.ttypes import TOperationState
from types import SimpleNamespace

from auto_ontology.catalog.extract import IncompleteCatalogExtractionError
from auto_ontology.connectors.connection_string_factory import (
    build_connection_string,
)
from auto_ontology.connectors.hive import (
    HiveDatabase,
    HiveQueryTimeout,
    _parse_connection_string,
)
from auto_ontology.connectors.registry import CONNECTOR_REGISTRY

HOST = "hive.example.com"


def _connection(**overrides: object) -> dict[str, object]:
    connection: dict[str, object] = {
        "type": "hive",
        "host": HOST,
        "user": "analyst",
        "password": "secret",
        "database": "sales",
    }
    connection.update(overrides)
    return connection


def _database(**overrides: object) -> HiveDatabase:
    return HiveDatabase(build_connection_string(_connection(**overrides)))


def _stub_execute(db: HiveDatabase, responses: dict[str, pd.DataFrame]) -> list[str]:
    """Route execute() to canned frames by SQL fragment, recording the SQL."""
    issued: list[str] = []

    def fake_execute(sql: str, parameters=None) -> pd.DataFrame:
        issued.append(sql)
        for fragment, frame in responses.items():
            if fragment in sql:
                return frame
        return pd.DataFrame()

    db.execute = fake_execute  # type: ignore[method-assign]
    return issued


# ----------------------------------------------------------------------
# Registration / connection string
# ----------------------------------------------------------------------


def test_hive_is_registered() -> None:
    assert CONNECTOR_REGISTRY["hive"] is HiveDatabase


def test_default_port_is_applied() -> None:
    assert urlparse(build_connection_string(_connection())).port == 10000


def test_a_password_selects_ldap_plain() -> None:
    settings = _parse_connection_string(build_connection_string(_connection()))
    assert settings["auth"] == "ldap"
    assert settings["username"] == "analyst"
    assert settings["password"] == "secret"


def test_no_password_defaults_to_none_and_anonymous_user() -> None:
    built = build_connection_string(_connection(user="", password="", database="raw"))
    settings = _parse_connection_string(built)
    assert settings["auth"] == "none"
    assert settings["username"] == "anonymous"
    # NONE must not fabricate a password segment.
    assert "@" not in built.split("://", 1)[1].split("/", 1)[0]


def test_credentials_with_reserved_characters_survive_the_round_trip() -> None:
    built = build_connection_string(_connection(password="p@ss/word#1"))
    assert _parse_connection_string(built)["password"] == "p@ss/word#1"


def test_database_is_required() -> None:
    with pytest.raises(ValueError, match="database"):
        _parse_connection_string("hive://analyst:secret@hive.example.com:10000")


def test_unsupported_auth_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported Hive auth"):
        _parse_connection_string(
            f"hive://analyst:secret@{HOST}:10000/sales?auth=KERBEROS"
        )


def test_truststore_implies_tls_and_is_carried() -> None:
    built = build_connection_string(
        _connection(truststore_file="AAAA", truststore_password="pw")
    )
    query = parse_qs(urlparse(built).query)
    assert query["ssl"] == ["true"]
    assert query["truststore_data"] == ["AAAA"]
    assert query["truststore_password"] == ["pw"]
    settings = _parse_connection_string(built)
    assert settings["use_ssl"] is True


def test_scheme_prefixed_host_is_normalised() -> None:
    built = build_connection_string(_connection(host=f"https://{HOST}"))
    assert urlparse(built).hostname == HOST


def test_identity_properties() -> None:
    db = _database()
    assert db.dialect == "hive"
    assert db.database_name == "sales"


# ----------------------------------------------------------------------
# Introspection
# ----------------------------------------------------------------------

# DESCRIBE output followed by a blank row and the partition section, both of
# which must be discarded.
DESCRIBED = pd.DataFrame(
    {
        "col_name": ["id", "amount", "", "# Partition Information", "dt"],
        "data_type": ["bigint", "decimal(10,2)", "", "# col_name", "string"],
        "comment": ["order primary key", "paid amount", None, None, "partition day"],
    }
)


def test_get_tables_and_columns_parse_show_and_describe() -> None:
    db = _database()
    issued = _stub_execute(
        db,
        {
            "SHOW TABLES": pd.DataFrame({"tab_name": ["orders", "customers"]}),
            "DESCRIBE": DESCRIBED,
        },
    )

    tables = db.get_tables()
    columns = db.get_columns()

    assert list(tables["table_name"]) == ["orders", "customers"]
    assert set(tables["table_schema"]) == {"sales"}
    assert set(tables["table_type"]) == {"base table"}

    orders = columns[columns["table_name"] == "orders"]
    assert list(orders["column_name"]) == ["id", "amount"]
    assert list(orders["data_type"]) == ["bigint", "decimal(10,2)"]
    assert list(orders["ordinal_position"]) == [1, 2]
    # DESCRIBE's third column is the Hive column comment; it must survive into
    # the catalog frame as the column description.
    assert list(orders["description"]) == ["order primary key", "paid amount"]
    # DESCRIBE reports no nullability: the connector sends NULL, not a string.
    assert orders["is_nullable"].isna().all()
    assert list(columns.columns) == [
        "table_schema",
        "table_name",
        "column_name",
        "data_type",
        "description",
        "is_nullable",
        "ordinal_position",
    ]

    assert any(sql.startswith("SHOW TABLES IN `sales`") for sql in issued)
    assert "DESCRIBE `sales`.`orders`" in issued


def test_introspection_is_cached() -> None:
    db = _database()
    issued = _stub_execute(
        db,
        {
            "SHOW TABLES": pd.DataFrame({"tab_name": ["orders"]}),
            "DESCRIBE": DESCRIBED,
        },
    )
    db.get_tables()
    db.get_columns()
    db.get_tables()
    assert sum("SHOW TABLES" in sql for sql in issued) == 1
    assert sum(sql.startswith("DESCRIBE") for sql in issued) == 1


def test_describe_without_a_comment_column_yields_null_descriptions() -> None:
    """Some HiveServer2-compatible engines return only col_name/data_type."""
    db = _database()
    described = pd.DataFrame(
        {
            "col_name": ["id", "amount"],
            "data_type": ["bigint", "decimal(10,2)"],
        }
    )
    _stub_execute(
        db,
        {
            "SHOW TABLES": pd.DataFrame({"tab_name": ["orders"]}),
            "DESCRIBE": described,
        },
    )

    columns = db.get_columns()
    orders = columns[columns["table_name"] == "orders"]
    assert list(orders["description"]) == [None, None]


def test_blank_comments_become_none() -> None:
    db = _database()
    described = pd.DataFrame(
        {
            "col_name": ["id", "note"],
            "data_type": ["bigint", "string"],
            "comment": ["  ", ""],
        }
    )
    _stub_execute(
        db,
        {
            "SHOW TABLES": pd.DataFrame({"tab_name": ["orders"]}),
            "DESCRIBE": described,
        },
    )

    columns = db.get_columns()
    orders = columns[columns["table_name"] == "orders"]
    assert list(orders["description"]) == [None, None]


def test_an_undescribable_table_is_dropped_from_both_frames() -> None:
    db = _database()

    def fake_execute(sql: str, parameters=None) -> pd.DataFrame:
        if "SHOW TABLES" in sql:
            return pd.DataFrame({"tab_name": ["good", "broken"]})
        if "DESCRIBE" in sql:
            if "`broken`" in sql:
                raise RuntimeError("HiveException: permission denied")
            return DESCRIBED
        return pd.DataFrame()

    db.execute = fake_execute  # type: ignore[method-assign]

    tables = db.get_tables()
    columns = db.get_columns()
    assert list(tables["table_name"]) == ["good"]
    assert set(columns["table_name"]) == {"good"}


def test_describing_nothing_at_all_raises() -> None:
    db = _database()

    def fake_execute(sql: str, parameters=None) -> pd.DataFrame:
        if "SHOW TABLES" in sql:
            return pd.DataFrame({"tab_name": ["a", "b"]})
        if "DESCRIBE" in sql:
            raise RuntimeError("HiveException: metaexception")
        return pd.DataFrame()

    db.execute = fake_execute  # type: ignore[method-assign]
    with pytest.raises(IncompleteCatalogExtractionError, match="could not describe"):
        db.get_tables()


def test_empty_database_lists_nothing() -> None:
    db = _database()
    _stub_execute(db, {"SHOW TABLES": pd.DataFrame({"tab_name": []})})
    tables = db.get_tables()
    columns = db.get_columns()
    assert tables.empty and columns.empty


def test_unsupported_metadata_frames_have_the_contract_columns() -> None:
    db = _database()
    assert list(db.get_pks().columns) == [
        "table_schema",
        "table_name",
        "column_name",
        "ordinal_position",
    ]
    assert list(db.get_fks().columns) == [
        "table_schema",
        "table_name",
        "column_name",
        "referenced_schema",
        "referenced_table",
        "referenced_column",
    ]
    assert list(db.get_views().columns) == [
        "table_schema",
        "table_name",
        "view_definition",
    ]
    assert list(db.get_queries().columns) == ["end_time", "query_text"]


def test_ping_lists_tables_in_the_bound_database() -> None:
    db = _database()
    issued = _stub_execute(db, {"SHOW TABLES": pd.DataFrame({"tab_name": []})})
    db.ping()
    assert issued == ["SHOW TABLES IN `sales`"]


# ----------------------------------------------------------------------
# Execution / transport
# ----------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple], description: list[tuple]) -> None:
        self._rows = rows
        self.description = description
        self.closed = False
        self.cancelled = False

    def execute(self, sql: str, parameters=None, async_: bool = False) -> None:
        self.sql = sql

    def poll(self) -> SimpleNamespace:
        return SimpleNamespace(
            operationState=TOperationState.FINISHED_STATE,
            errorMessage=None,
            sqlState=None,
            infoMessages=None,
        )

    def cancel(self) -> None:
        self.cancelled = True

    def fetchall(self) -> list[tuple]:
        return self._rows

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def test_execute_returns_rows_and_strips_table_prefixed_names() -> None:
    db = _database()
    cursor = _FakeCursor([(1, "a")], [("orders.id",), ("orders.name",)])
    db._connection = _FakeConnection(cursor)  # type: ignore[assignment]

    frame = db.execute("SELECT id, name FROM `sales`.`orders`")

    assert list(frame.columns) == ["id", "name"]
    assert frame.values.tolist() == [[1, "a"]]
    assert cursor.closed


def test_execute_reopens_a_lost_session_once() -> None:
    db = _database()
    good_cursor = _FakeCursor([(7,)], [("n",)])
    opened: list[bool] = []

    class StaleConnection(_FakeConnection):
        def cursor(self) -> _FakeCursor:
            raise RuntimeError("Invalid SessionHandle: server has no such session")

    db._connection = StaleConnection(_FakeCursor([], []))  # type: ignore[assignment]

    def fake_open() -> _FakeConnection:
        opened.append(True)
        return _FakeConnection(good_cursor)

    db._open = fake_open  # type: ignore[method-assign]

    frame = db.execute("SELECT 7 AS n")

    assert frame.values.tolist() == [[7]]
    assert len(opened) == 1


def test_a_real_sql_error_is_not_retried() -> None:
    db = _database()
    attempts = {"count": 0}

    class FailingConnection(_FakeConnection):
        def cursor(self) -> _FakeCursor:
            raise RuntimeError("Error while compiling statement: Table not found")

    db._connection = FailingConnection(_FakeCursor([], []))  # type: ignore[assignment]
    db._open = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("must not reopen for a SQL error")
    )

    with pytest.raises(RuntimeError, match="Table not found"):
        db.execute("SELECT * FROM `sales`.`missing`")
    assert attempts == {"count": 0}


def test_none_auth_builds_a_buffered_transport_without_sasl() -> None:
    db = _database(user="", password="", database="raw")
    transport = db._build_transport()
    # NONE uses plain buffered Thrift; LDAP/CUSTOM wraps a TSaslClientTransport.
    assert type(transport).__name__ == "TBufferedTransport"


def test_ldap_auth_builds_a_sasl_transport() -> None:
    db = _database()
    transport = db._build_transport()
    assert type(transport).__name__ == "TSaslClientTransport"


class _AlwaysRunningCursor(_FakeCursor):
    def poll(self) -> SimpleNamespace:
        return SimpleNamespace(
            operationState=TOperationState.RUNNING_STATE,
            errorMessage=None,
            sqlState=None,
            infoMessages=None,
        )


def test_a_statement_over_the_cap_is_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "auto_ontology.connectors.hive._POLL_INTERVAL_START_SECONDS", 0.005
    )
    monkeypatch.setattr(
        "auto_ontology.connectors.hive._POLL_INTERVAL_MAX_SECONDS", 0.005
    )
    db = _database()
    cursor = _AlwaysRunningCursor([], [])
    db._connection = _FakeConnection(cursor)  # type: ignore[assignment]

    with pytest.raises(HiveQueryTimeout, match="exceeded"):
        db.execute("SELECT count(*) FROM big_table", timeout_s=0.03)

    assert cursor.cancelled


class _FailedCursor(_FakeCursor):
    def poll(self) -> SimpleNamespace:
        return SimpleNamespace(
            operationState=TOperationState.ERROR_STATE,
            errorMessage="Error while compiling statement: boom",
            sqlState="42000",
            infoMessages=None,
        )


def test_a_failed_statement_is_raised_not_retried() -> None:
    db = _database()
    db._connection = _FakeConnection(_FailedCursor([], []))  # type: ignore[assignment]
    db._open = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("must not reopen after a SQL error")
    )

    with pytest.raises(RuntimeError, match="boom"):
        db.execute("SELECT * FROM missing")
