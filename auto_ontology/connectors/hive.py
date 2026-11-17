# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Apache Hive connector implementing Auto Ontology's SQLDatabase ABC.

HiveServer2 speaks the same HiveServer2 Thrift protocol as Kyuubi, so this
connector is reached with the same Hive client (``pyhive``) rather than an
ODBC/REST driver. The two differ in namespace shape, which drives most of the
implementation:

* Hive uses a **two-level** ``database.table`` namespace. A Hive "database" is
  the top-level schema (the ``table_schema`` the catalog records), so one
  connection binds one database and :meth:`HiveDatabase.qualify` is the base
  ``schema.table`` default -- no catalog is prepended the way Kyuubi needs.
* Hive has no ``information_schema``; metadata comes from ``SHOW TABLES IN`` and
  per-table ``DESCRIBE``. Hive reports no primary keys, foreign keys, or query
  history, and ``DESCRIBE`` does not report nullability.

Authentication is SASL PLAIN for ``LDAP``/``CUSTOM`` and an unauthenticated
transport for ``NONE``. Kerberos (GSSAPI) is intentionally out of scope for the
first version: ``pure-sasl`` cannot perform GSSAPI, so it would need a system
SASL install. ``pyhive`` builds a plaintext ``TSocket`` even against a TLS-only
endpoint (the connection then hangs rather than failing), so when TLS is wanted
the SASL transport is assembled here over an explicit ``TSSLSocket`` and passed
via ``thrift_transport`` -- the same workaround the Kyuubi connector uses.

Example
-------
::

    CONNECTION_STRINGS=hive://analyst:secret@hive.example.com:10000/sales?auth=LDAP
    CONNECTION_STRINGS=hive://hive.example.com:10000/raw?ssl=true&ca_bundle=/etc/ssl/hive_ca.pem
"""

from __future__ import annotations

import logging
import os
import ssl
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, Optional
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

from auto_ontology.catalog.constants import TableTypes
from auto_ontology.catalog.extract import IncompleteCatalogExtractionError
from auto_ontology.connectors.base import SQLDatabase, StatementTimeout
from auto_ontology.connectors.db_errors import is_session_lost

# Reuse the Kyuubi connector's JKS handling rather than carrying a second
# implementation of temp-file decode and the pyjks PEM conversion.
from auto_ontology.connectors.kyuubi import _jks_to_pem, _write_temp_jks
from auto_ontology.utils.sql_identifiers import quoted_identifier

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pyhive.hive import Connection

logger = logging.getLogger(__name__)

DEFAULT_PORT = 10000

# A blocking HiveServer2 call is bounded by the socket read timeout. Wide table
# scans legitimately run for minutes, so match the generous ceiling the Kyuubi
# connector uses rather than the driver's own default.
_SOCKET_TIMEOUT_SECONDS = 900

# SASL PLAIN covers LDAP and CUSTOM/PAM; they are identical on the wire.
_PLAIN_AUTH_MODES = frozenset({"ldap", "custom", "pam"})
_SUPPORTED_AUTH_MODES = frozenset({"none"} | _PLAIN_AUTH_MODES)

# ``DESCRIBE`` appends a blank row and ``# Partition Information`` /
# ``# Detailed Table Information`` sections after the column list. Only the
# leading block describes columns; partition columns would otherwise be
# duplicated into the catalog.
_DESCRIBE_TERMINATORS = ("#", "")

_COLUMN_SCHEMA = [
    "table_schema",
    "table_name",
    "column_name",
    "data_type",
    "is_nullable",
    "ordinal_position",
]

_PK_SCHEMA = ["table_schema", "table_name", "column_name", "ordinal_position"]

_FK_SCHEMA = [
    "table_schema",
    "table_name",
    "column_name",
    "referenced_schema",
    "referenced_table",
    "referenced_column",
]

# Polling cadence for an async statement: short first so a fast query is not
# held up, backed off so a long scan does not spin on the socket.
_POLL_INTERVAL_START_SECONDS = 0.2
_POLL_INTERVAL_MAX_SECONDS = 5.0


class HiveQueryTimeout(StatementTimeout):
    """A statement outlived the caller's ``timeout_s`` and was cancelled.

    It is deliberately not a transport error: the session is healthy, so
    reopening it and retrying would only spend the same time again.
    """


def _status_detail(status: Any) -> str:
    """Flatten everything the server said about a failed statement into one line."""
    parts = [
        getattr(status, "errorMessage", None),
        getattr(status, "sqlState", None),
        *(getattr(status, "infoMessages", None) or []),
    ]
    return " | ".join(str(part) for part in parts if part) or "no error detail reported"


def _first(query: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for *key*, URL-decoded, or ``None``."""
    value = query.get(key, [None])[0]
    return unquote(value) if value else None


def _is_true(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_connection_string(connection_string: str) -> dict[str, Any]:
    """Parse a Hive URL into the settings this connector needs.

    Expected formats::

        hive://USER:PASSWORD@HOST:10000/DATABASE?auth=LDAP
        hive://HOST:10000/DATABASE            # auth=NONE
        hive://USER:PASSWORD@HOST:10000/DATABASE?ssl=true
    """
    parsed = urlparse(connection_string)
    if parsed.scheme.split("+", 1)[0].lower() != "hive":
        raise ValueError(f"Not a Hive URL: {connection_string}")
    if not parsed.hostname:
        raise ValueError(
            f"Invalid Hive connection string (missing host): {connection_string}"
        )

    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError(
            "Hive connection string requires a database, e.g. "
            "hive://hive.example.com:10000/sales"
        )

    query = parse_qs(parsed.query)

    password = unquote(parsed.password) if parsed.password is not None else ""
    auth = (_first(query, "auth") or ("ldap" if password else "none")).lower()
    if auth not in _SUPPORTED_AUTH_MODES:
        raise ValueError(
            f"Unsupported Hive auth mode: {auth!r} "
            "(use NONE, LDAP, or CUSTOM; Kerberos is not supported yet)"
        )

    has_trust_material = any(
        _first(query, key) for key in ("ca_bundle", "truststore", "truststore_data")
    )
    use_ssl = _is_true(_first(query, "ssl"), default=has_trust_material)

    return {
        "host": parsed.hostname,
        "port": parsed.port or DEFAULT_PORT,
        "database": database,
        "username": unquote(parsed.username or "") or "anonymous",
        "password": password,
        "auth": auth,
        "use_ssl": use_ssl,
        "verify_ssl": _is_true(_first(query, "verify_ssl"), default=True),
        "ca_bundle": _first(query, "ca_bundle"),
        "truststore": _first(query, "truststore"),
        "truststore_data": _first(query, "truststore_data"),
        "truststore_password": _first(query, "truststore_password"),
    }


class HiveDatabase(SQLDatabase):
    """Concrete :class:`SQLDatabase` backed by Apache Hive over HiveServer2.

    Parameters
    ----------
    connection_string:
        ``hive://user:password@host:10000/database?auth=LDAP``. The path is the
        single Hive database this connection ingests and queries; add a second
        connection to cover a second database.
    """

    # The cap is enforced by polling the async statement already in flight, so
    # it costs no extra session or round trip to ask for one.
    supports_statement_timeout = True

    def __init__(self, connection_string: str) -> None:
        self._settings = _parse_connection_string(connection_string)
        self._database = str(self._settings["database"])

        self._lock = threading.RLock()
        self._connection: "Connection | None" = None

        # Resolved PEM bundle for TLS, lazily converted from a JKS truststore.
        self._ca_pem: str | None = None
        self._ca_pem_is_temporary = False

    # ------------------------------------------------------------------
    # Transport / session
    # ------------------------------------------------------------------

    def _ca_certs(self) -> str | None:
        """Return a PEM CA path, converting an uploaded JKS truststore once."""
        if self._ca_pem is not None:
            return self._ca_pem

        ca_bundle = self._settings["ca_bundle"]
        if ca_bundle:
            self._ca_pem = ca_bundle
            return self._ca_pem

        truststore_data = self._settings["truststore_data"]
        truststore = self._settings["truststore"]
        password = self._settings["truststore_password"]
        if truststore_data:
            jks_path = _write_temp_jks(truststore_data)
            try:
                self._ca_pem = _jks_to_pem(jks_path, password)
            finally:
                try:
                    os.unlink(jks_path)
                except OSError:
                    logger.debug("Failed to remove %s", jks_path, exc_info=True)
            self._ca_pem_is_temporary = True
        elif truststore:
            self._ca_pem = _jks_to_pem(truststore, password)
            self._ca_pem_is_temporary = True
        return self._ca_pem

    def _build_transport(self) -> Any:
        """Assemble the Thrift transport, adding SASL PLAIN for password auth."""
        from thrift.transport.TSocket import TSocket

        host = str(self._settings["host"])
        port = int(self._settings["port"])

        if not self._settings["use_ssl"]:
            socket: Any = TSocket(host, port)
        else:
            # Build the context rather than handing ``ca_certs`` to TSSLSocket:
            # a ``None`` cafile falls back to the system trust store, while
            # TSSLSocket's own ``ca_certs`` path would leave no anchors when no
            # truststore is supplied and fail every handshake.
            from thrift.transport.TSSLSocket import TSSLSocket

            context = ssl.create_default_context(cafile=self._ca_certs())
            if not self._settings["verify_ssl"]:
                logger.warning(
                    "Hive TLS certificate verification disabled for %s:%s",
                    host,
                    port,
                )
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            socket = TSSLSocket(
                host=host,
                port=port,
                ssl_context=context,
                server_hostname=host,
            )
        socket.setTimeout(_SOCKET_TIMEOUT_SECONDS * 1000)

        if self._settings["auth"] in _PLAIN_AUTH_MODES:
            import thrift_sasl
            from pyhive.hive import get_installed_sasl

            username = str(self._settings["username"])
            password = str(self._settings["password"])
            return thrift_sasl.TSaslClientTransport(
                lambda: get_installed_sasl(
                    host=host,
                    sasl_auth="PLAIN",
                    service=None,
                    username=username,
                    password=password,
                ),
                "PLAIN",
                socket,
            )

        # auth=NONE: HiveServer2's unauthenticated transport is plain buffered
        # Thrift with no SASL layer (what pyhive itself does for auth=NONE).
        from thrift.transport.TTransport import TBufferedTransport

        return TBufferedTransport(socket)

    def _open(self) -> "Connection":
        from pyhive import hive

        transport = self._build_transport()
        connection = hive.Connection(
            thrift_transport=transport,
            username=str(self._settings["username"]),
            database=self._database,
        )
        logger.info(
            "Opened Hive session on %s:%s/%s (auth=%s, ssl=%s)",
            self._settings["host"],
            self._settings["port"],
            self._database,
            self._settings["auth"],
            self._settings["use_ssl"],
        )
        return connection

    def _reset_connection(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                logger.debug("Failed to close Hive session", exc_info=True)
            self._connection = None

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        """Yield a cursor on the shared, lock-serialised session."""
        with self._lock:
            if self._connection is None:
                self._connection = self._open()
            cursor = self._connection.cursor()
            try:
                yield cursor
            finally:
                try:
                    cursor.close()
                except Exception:
                    logger.debug("Failed to close Hive cursor", exc_info=True)

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def dialect(self) -> str:
        """Return this engine's sqlglot dialect name.

        Must be a member of ``sqlglot.dialects.DIALECTS`` -- callers pass it
        straight into sqlglot without translation. See ``CONNECTOR_REGISTRY``.
        """
        return "hive"

    @property
    def database_name(self) -> str:
        return self._database

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @staticmethod
    def _cancel(cursor: Any) -> None:
        """Ask the server to stop a statement we have given up on."""
        try:
            cursor.cancel()
        except Exception:
            logger.debug("Failed to cancel Hive statement", exc_info=True)

    def _await_completion(
        self, cursor: Any, started: float, timeout_s: float | None
    ) -> None:
        """Poll an async statement until HiveServer2 reports a terminal state.

        A synchronous ``execute`` holds the socket for the whole query, leaving
        the socket read timeout as the only ceiling and no way to tell queued
        from running. Polling makes the caller's cap enforceable.

        Raises:
            HiveQueryTimeout: the cap elapsed; the statement is cancelled.
            RuntimeError: the server ended the statement in a failed state.
        """
        from TCLIService.ttypes import TOperationState

        ceiling = _SOCKET_TIMEOUT_SECONDS if timeout_s is None else timeout_s
        pending = {
            TOperationState.INITIALIZED_STATE,
            TOperationState.PENDING_STATE,
            TOperationState.RUNNING_STATE,
        }
        names = TOperationState._VALUES_TO_NAMES
        interval = _POLL_INTERVAL_START_SECONDS
        while True:
            status = cursor.poll()
            state = status.operationState
            elapsed = time.perf_counter() - started
            if state == TOperationState.FINISHED_STATE:
                return
            if state not in pending:
                raise RuntimeError(
                    f"Hive statement ended in {names.get(state, state)}: "
                    f"{_status_detail(status)}"
                )
            if elapsed >= ceiling:
                self._cancel(cursor)
                raise HiveQueryTimeout(
                    ceiling,
                    f"Hive statement exceeded {ceiling:g}s in state "
                    f"{names.get(state, state)} and was cancelled",
                )
            time.sleep(interval)
            interval = min(interval * 2, _POLL_INTERVAL_MAX_SECONDS)

    def _execute_once(
        self,
        sql: str,
        parameters: Optional[list] = None,
        *,
        timeout_s: float | None = None,
    ) -> pd.DataFrame:
        label = " ".join(sql.split())[:110]
        with self._cursor() as cursor:
            started = time.perf_counter()
            if parameters:
                cursor.execute(sql, parameters, async_=True)
            else:
                cursor.execute(sql, async_=True)
            self._await_completion(cursor, started, timeout_s)
            if cursor.description is None:
                logger.info("hive: no rows — %s", label)
                return pd.DataFrame()
            # Defensive: some HiveServer2 builds report names as ``table.column``.
            columns = [str(desc[0]).split(".")[-1] for desc in cursor.description]
            rows = cursor.fetchall()
            logger.info("hive: %d row(s) — %s", len(rows), label)
            return pd.DataFrame(rows, columns=columns)

    def execute(
        self,
        sql: str,
        parameters: Optional[list] = None,
        *,
        timeout_s: float | None = None,
    ) -> pd.DataFrame:
        """Run *sql*, reopening the session once if an idle server dropped it.

        ``timeout_s`` caps how long the statement may stay pending before it is
        cancelled and :class:`HiveQueryTimeout` is raised. A timeout is never
        retried. A stale session (a dead socket or ``Invalid SessionHandle``)
        is rebuilt and retried once; an actual SQL error is raised unchanged.
        """
        with self._lock:
            try:
                return self._execute_once(sql, parameters, timeout_s=timeout_s)
            except HiveQueryTimeout:
                raise
            except Exception as exc:
                if not is_session_lost(exc, statement=sql):
                    raise
                logger.info("Hive session unusable; reconnecting once")
                self._reset_connection()
                self._connection = self._open()
                return self._execute_once(sql, parameters, timeout_s=timeout_s)

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def _table_names(self) -> list[str]:
        """Return every table/view name in the bound database."""
        frame = self.execute(
            f"SHOW TABLES IN {quoted_identifier(self._database, self.dialect)}"
        )
        if frame.empty:
            return []
        # Hive documents a single ``tab_name`` column; select positionally so
        # builds that additionally report a type column still work.
        return [str(name) for name in frame.iloc[:, 0].tolist() if str(name)]

    def _describe(self, table: str) -> list[tuple[str, str]]:
        """Return ``(column_name, data_type)`` pairs for one table.

        Hive has no queryable ``information_schema``, so each relation is
        described individually and the trailing partition/detailed sections are
        discarded.
        """
        qualified = self.qualify(self._database, table)
        try:
            frame = self.execute(f"DESCRIBE {qualified}")
        except Exception as exc:  # noqa: BLE001 - one bad table must not stop the sweep
            reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            logger.warning(
                "Cannot describe Hive table %s, skipping it: %s",
                qualified,
                reason[:300],
            )
            logger.debug("DESCRIBE failure detail for %s", qualified, exc_info=True)
            return []
        if frame.empty:
            return []

        columns: list[tuple[str, str]] = []
        for record in frame.itertuples(index=False):
            values = list(record)
            name = str(values[0] or "").strip()
            if not name or name.startswith(_DESCRIBE_TERMINATORS[0]):
                break
            data_type = str(values[1] or "").strip() if len(values) > 1 else ""
            if not data_type:
                continue
            columns.append((name, data_type))
        return columns

    def _introspect(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Describe every table once, returning the tables and columns frames.

        Tables that cannot be described are dropped from *both* frames rather
        than reported without columns: ingestion groups columns by the schemas
        in the tables frame, so a relation with no columns aborts the run. If
        tables were listed but not one could be described, that is raised rather
        than silently ingested as an empty catalog.

        Metadata is read once and cached: every DESCRIBE is a separate
        HiveServer2 round trip.
        """
        cached = getattr(self, "_introspection", None)
        if cached is not None:
            return cached

        table_rows: list[dict[str, str]] = []
        column_rows: list[dict[str, Any]] = []
        skipped: list[str] = []

        for table in self._table_names():
            columns = self._describe(table)
            if not columns:
                skipped.append(table)
                continue
            table_rows.append(
                {
                    "table_schema": self._database,
                    "table_name": table,
                    # v1 cannot cheaply distinguish a view from a table (Hive's
                    # SHOW TABLES does not say); views are ingested as tables and
                    # get_views reports none. See module docstring limitations.
                    "table_type": TableTypes.BASE_TABLE,
                }
            )
            for position, (name, data_type) in enumerate(columns, start=1):
                column_rows.append(
                    {
                        "table_schema": self._database,
                        "table_name": table,
                        "column_name": name,
                        "data_type": data_type,
                        # DESCRIBE reports no nullability; NULL means "unknown",
                        # which the catalog treats as nullable.
                        "is_nullable": None,
                        "ordinal_position": position,
                    }
                )

        if skipped and not table_rows:
            raise IncompleteCatalogExtractionError(
                f"Hive listed {len(skipped)} relation(s) in {self._database!r} and "
                f"could not describe any of them: {', '.join(skipped[:10])}"
                f"{'' if len(skipped) <= 10 else f' (+{len(skipped) - 10} more)'}. "
                "Refusing to ingest an empty catalog."
            )
        if skipped:
            logger.warning(
                "Skipped %d Hive table(s) whose columns could not be read: %s",
                len(skipped),
                ", ".join(skipped),
            )

        tables = (
            pd.DataFrame(table_rows)
            if table_rows
            else pd.DataFrame(columns=["table_schema", "table_name", "table_type"])
        )
        columns_frame = (
            pd.DataFrame(column_rows)
            if column_rows
            else pd.DataFrame(columns=_COLUMN_SCHEMA)
        )
        self._introspection = (tables, columns_frame)
        return self._introspection

    def get_tables(self) -> pd.DataFrame:
        return self._introspect()[0].copy()

    def get_columns(self) -> pd.DataFrame:
        return self._introspect()[1].copy()

    def get_views(self) -> pd.DataFrame:
        """v1 does not distinguish views; SHOW TABLES lists both without a type."""
        return pd.DataFrame(columns=["table_schema", "table_name", "view_definition"])

    def get_queries(self, hours: int = 24) -> pd.DataFrame:
        """Hive exposes no SQL query history through HiveServer2."""
        return pd.DataFrame(columns=["end_time", "query_text"])

    def get_pks(self) -> pd.DataFrame:
        """Hive tables carry no primary keys."""
        return pd.DataFrame(columns=_PK_SCHEMA)

    def get_fks(self) -> pd.DataFrame:
        """Hive tables carry no foreign keys."""
        return pd.DataFrame(columns=_FK_SCHEMA)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def ping(self) -> None:
        """Verify credentials, transport, and that the bound database is visible."""
        self.execute(
            f"SHOW TABLES IN {quoted_identifier(self._database, self.dialect)}"
        )

    def close(self) -> None:
        with self._lock:
            self._reset_connection()
            if self._ca_pem and self._ca_pem_is_temporary:
                try:
                    os.unlink(self._ca_pem)
                except OSError:
                    logger.debug("Failed to remove %s", self._ca_pem, exc_info=True)
                self._ca_pem = None
                self._ca_pem_is_temporary = False
