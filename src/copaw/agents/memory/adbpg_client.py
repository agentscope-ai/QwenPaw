# -*- coding: utf-8 -*-
"""ADBPG Memory Client for CoPaw agents.

Provides configuration and database client for ADBPG
(AnalyticDB for PostgreSQL) memory storage, including
LLM and Embedding configuration.

Uses a process-global ``ThreadedConnectionPool`` shared across all
agents so that the total number of database connections stays bounded
regardless of how many agents are running.
"""
import ast
import json
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

try:
    import psycopg2
    import psycopg2.pool
except ImportError:
    psycopg2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass
class ADBPGConfig:
    """ADBPG connection and LLM/Embedding configuration."""

    # Database connection
    host: str
    port: int
    user: str
    password: str
    dbname: str
    # LLM configuration
    llm_model: str
    llm_api_key: str
    llm_base_url: str
    # Embedding configuration
    embedding_model: str
    embedding_api_key: str
    embedding_base_url: str
    embedding_dims: int
    # Optional configuration
    search_timeout: float = 10.0
    # Connection pool tuning
    pool_minconn: int = 2
    pool_maxconn: int = 10
    # Tool result compaction
    tool_compact_mode: str = "summarize"
    tool_compact_max_len: int = 500
    # Memory isolation
    memory_isolation: bool = False
    user_isolation: bool = False
    user_isolation_id: str = ""
    run_isolation: bool = False
    # Custom fact extraction prompt (SQL mode only)
    custom_fact_extraction_prompt: str = ""
    # REST API mode (alternative to SQL)
    api_mode: str = "sql"
    rest_api_key: str = ""
    rest_base_url: str = ""


# ---------------------------------------------------------------------------
# Process-global shared connection pool
# ---------------------------------------------------------------------------
# A single ``ThreadedConnectionPool`` is shared across all
# ``ADBPGMemoryClient`` instances in the process.  This keeps the
# total number of database connections bounded regardless of how many
# agents are running concurrently.
_global_pool: "psycopg2.pool.ThreadedConnectionPool | None" = None
_global_pool_lock = threading.Lock()
# Track which connections have been session-configured (by ``id(conn)``)
# so that ``adbpg_llm_memory.config()`` is called at most once per
# physical connection.
_configured_conns: set[int] = set()
_configured_conns_lock = threading.Lock()


def _get_shared_pool(
    conn_params: dict,
    minconn: int = 2,
    maxconn: int = 10,
) -> "psycopg2.pool.ThreadedConnectionPool":
    """Return (or create) the process-global ``ThreadedConnectionPool``.

    Thread-safe: uses a lock so that concurrent ``start()`` calls from
    multiple agents don't race.

    Args:
        conn_params: psycopg2 connection keyword arguments.
        minconn: Minimum connections kept open in the pool.
        maxconn: Maximum connections the pool will create.

    Returns:
        The shared ``ThreadedConnectionPool`` instance.
    """
    global _global_pool  # noqa: PLW0603
    if _global_pool is not None and not _global_pool.closed:
        return _global_pool
    with _global_pool_lock:
        # Double-check after acquiring lock
        if _global_pool is not None and not _global_pool.closed:
            return _global_pool
        _global_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            **conn_params,
        )
        logger.info(
            "Created shared ADBPG ThreadedConnectionPool " "(min=%d, max=%d).",
            minconn,
            maxconn,
        )
        return _global_pool


def close_shared_pool() -> None:
    """Close the process-global connection pool.

    Safe to call even if the pool was never created.
    """
    global _global_pool  # noqa: PLW0603
    with _global_pool_lock:
        if _global_pool is not None and not _global_pool.closed:
            _global_pool.closeall()
            logger.info("Shared ADBPG connection pool closed.")
        _global_pool = None
    with _configured_conns_lock:
        _configured_conns.clear()


def reset_configured_connections() -> None:
    """Clear the configured-connections cache.

    Forces all pooled connections to re-run
    ``adbpg_llm_memory.config()`` on their next use.  Call this
    after a configuration change (e.g. hot-reload) so that updated
    settings like ``custom_fact_extraction_prompt`` take effect
    without restarting the process.
    """
    with _configured_conns_lock:
        _configured_conns.clear()
    logger.debug("Cleared configured-connections cache.")


class ADBPGMemoryClient:
    """Thread-safe ADBPG database client using a shared connection pool.

    All ``ADBPGMemoryClient`` instances within the same process share a
    single ``ThreadedConnectionPool``.  Connections are borrowed from
    the pool for each operation and returned immediately afterwards
    ("borrow-use-return" pattern), which keeps the pool effective and
    avoids connection leaks.

    Each borrowed connection is session-configured (via
    ``adbpg_llm_memory.config()``) at most once; the configured state
    is tracked by connection ``id()`` so that reconnected / new
    connections are automatically re-configured.
    """

    def __init__(self, config: ADBPGConfig):
        """Initialize the client.

        The underlying connection pool is created lazily on first use
        and shared across all client instances.

        When ``config.api_mode`` is ``"rest"``, no database connection
        is needed — all operations go through the ADBPG memory REST API.

        Args:
            config: ADBPG configuration object.

        Raises:
            ImportError: If psycopg2 is not installed (SQL mode only).
        """
        self._config = config
        self._is_rest = config.api_mode == "rest"

        if self._is_rest:
            import httpx  # noqa: F401 — validate availability

            self._rest_headers = {
                "X-Auth-Token": f"static:{config.rest_api_key}",
                "Content-Type": "application/json",
            }
            self._rest_timeout = config.search_timeout
            self._conn_params = {}
            self._pool_minconn = 0
            self._pool_maxconn = 0
        else:
            if psycopg2 is None:
                raise ImportError(
                    "psycopg2 is required for ADBPGMemoryClient. "
                    "Install it with: pip install psycopg2-binary",
                )
            self._conn_params = {
                "host": config.host,
                "port": config.port,
                "user": config.user,
                "password": config.password,
                "dbname": config.dbname,
            }
            self._pool_minconn = config.pool_minconn
            self._pool_maxconn = config.pool_maxconn

    # -- Logging helpers (unchanged) --

    def _log_sql(self, sql: str, params: tuple) -> None:
        """Log SQL statement with masked sensitive values."""

        def _mask_param(p):
            if not isinstance(p, str):
                return p
            try:
                obj = json.loads(p)
                return json.dumps(
                    _mask_dict(obj),
                    ensure_ascii=False,
                )
            except (json.JSONDecodeError, TypeError):
                pass
            return p

        def _mask_dict(d):
            if isinstance(d, dict):
                return {
                    k: (
                        _mask_val(v)
                        if k in ("api_key", "password")
                        else _mask_dict(v)
                    )
                    for k, v in d.items()
                }
            if isinstance(d, list):
                return [_mask_dict(i) for i in d]
            return d

        def _mask_val(v):
            s = str(v)
            return s[:4] + "***" if len(s) > 4 else "***"

        masked = tuple(_mask_param(p) for p in params)
        logger.debug(f"ADBPG SQL: {sql} | params: {masked}")

    def _log_result(self, label: str, result) -> None:
        """Log SQL result, truncating if too long."""
        text = str(result)
        if len(text) > 1000:
            text = text[:1000] + "...(truncated)"
        logger.debug(f"ADBPG {label} result: {text}")

    # -- Pool / connection management --

    def _get_pool(self) -> "psycopg2.pool.ThreadedConnectionPool":
        """Return the shared connection pool, creating it if needed."""
        return _get_shared_pool(
            self._conn_params,
            minconn=self._pool_minconn,
            maxconn=self._pool_maxconn,
        )

    @contextmanager
    def _borrow_connection(self):
        """Context manager: borrow a connection, yield it, then return it.

        On success the connection is committed and returned to the pool.
        On error the connection is rolled back and returned to the pool.
        If the connection is broken (closed), it is discarded via
        ``putconn(conn, close=True)`` so the pool can replace it.
        """
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            # Ensure session-level config on this connection
            self._ensure_configured(conn)
            yield conn
            conn.commit()
        except Exception:
            try:
                if conn and not conn.closed:
                    conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                if conn.closed:
                    pool.putconn(conn, close=True)
                    with _configured_conns_lock:
                        _configured_conns.discard(id(conn))
                else:
                    pool.putconn(conn)
            except Exception:
                pass

    def _ensure_configured(self, conn) -> None:
        """Run session-level ``adbpg_llm_memory.config()`` if needed."""
        conn_id = id(conn)
        with _configured_conns_lock:
            if conn_id in _configured_conns:
                return

        self._configure_connection(conn)

        with _configured_conns_lock:
            _configured_conns.add(conn_id)

    def _query_internal_port(
        self,
        conn,
        *,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> int:
        """Query the master internal port from gp_segment_configuration.

        Retries up to *max_retries* times on failure.  If all attempts
        fail, raises ``ConfigurationError`` so the caller can disable
        long-term memory gracefully.
        """
        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT port FROM gp_segment_configuration "
                        "WHERE content = -1 AND role = 'p'",
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        port = int(row[0])
                        logger.debug(
                            "Auto-detected ADBPG internal port: %d",
                            port,
                        )
                        return port
                raise ConfigurationError(
                    "gp_segment_configuration returned no master port row.",
                )
            except Exception as e:
                last_err = e
                logger.warning(
                    "Failed to query internal port (attempt %d/%d): %s",
                    attempt,
                    max_retries,
                    e,
                )
                try:
                    conn.rollback()
                except Exception:
                    pass
                if attempt < max_retries:
                    time.sleep(retry_delay)

        raise ConfigurationError(
            f"Unable to detect ADBPG internal port after "
            f"{max_retries} attempts: {last_err}",
        )

    def _configure_connection(self, conn) -> None:
        """Execute ``adbpg_llm_memory.config()`` on *conn*.

        The ``vector_store`` port is auto-detected by querying
        ``gp_segment_configuration`` for the master internal port.
        """
        vector_port = self._query_internal_port(conn)

        config_json = {
            "llm": {
                "provider": "qwen",
                "config": {
                    "model": self._config.llm_model,
                    "qwen_base_url": self._config.llm_base_url,
                    "api_key": self._config.llm_api_key,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": self._config.embedding_model,
                    "api_key": self._config.embedding_api_key,
                    "embedding_dims": str(self._config.embedding_dims),
                    "openai_base_url": self._config.embedding_base_url,
                },
            },
            "vector_store": {
                "provider": "adbpg",
                "config": {
                    "user": self._config.user,
                    "dbname": self._config.dbname,
                    "password": self._config.password,
                    "port": str(vector_port),
                    "embedding_model_dims": str(self._config.embedding_dims),
                },
            },
        }
        if self._config.custom_fact_extraction_prompt:
            config_json["custom_fact_extraction_prompt"] = (
                self._config.custom_fact_extraction_prompt
            )

        sql = "SELECT adbpg_llm_memory.config(%s::json)"
        params = (json.dumps(config_json),)
        self._log_sql(sql, params)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            self._log_result("config", row)
        conn.commit()
        logger.debug("ADBPG session configured on connection.")

    # -- Public convenience method (kept for backward compat) --

    def configure(self) -> None:
        """Eagerly configure one connection (validates connectivity).

        In REST mode this is a no-op — the remote ADBPG memory service
        is assumed to be configured externally.

        In SQL mode, borrows a connection from the pool and runs
        ``adbpg_llm_memory.config()`` (auto-configured on first use).
        """
        if self._is_rest:
            logger.debug(
                "REST mode: skipping configure (handled externally).",
            )
            return
        with self._borrow_connection():
            pass  # _ensure_configured runs inside the context manager

    # -- Core operations --

    def add_memory(
        self,
        messages: list[dict],
        user_id: str = "",
        run_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Store memories (synchronous, thread-safe).

        Dispatches to REST or SQL based on ``api_mode``.
        """
        if self._is_rest:
            self._rest_add_memory(
                messages,
                user_id,
                run_id,
                agent_id,
                metadata,
            )
            return
        try:
            with self._borrow_connection() as conn:
                sql = (
                    "SELECT adbpg_llm_memory.add("
                    "%s::json, %s, %s, %s, %s, %s, %s"
                    ")"
                )
                params = (
                    json.dumps(messages),
                    user_id or None,
                    run_id,
                    agent_id,
                    json.dumps(metadata) if metadata else None,
                    None,
                    None,
                )
                self._log_sql(sql, params)
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
                    self._log_result("add", row)
                logger.debug("Memory added to ADBPG successfully.")
        except Exception as e:
            logger.error(f"Failed to add memory to ADBPG: {e}")

    def search_memory(
        self,
        query: str,
        user_id: str = "",
        run_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 5,
        timeout: float | None = None,
    ) -> list[dict]:
        """Search memories (synchronous, thread-safe).

        Dispatches to REST or SQL based on ``api_mode``.
        """
        if self._is_rest:
            return self._rest_search_memory(
                query,
                user_id,
                agent_id,
                limit,
                timeout,
            )
        if timeout is None:
            timeout = self._config.search_timeout
        timeout_ms = int(timeout * 1000)

        try:
            with self._borrow_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SET statement_timeout = {timeout_ms}",
                    )
                    try:
                        sql = (
                            "SELECT adbpg_llm_memory.search("
                            "%s, %s, %s, %s, %s"
                            ")"
                        )
                        params = (
                            query,
                            user_id or None,
                            run_id,
                            agent_id,
                            None,
                        )
                        self._log_sql(sql, params)
                        cur.execute(sql, params)
                        result = cur.fetchone()
                        self._log_result("search", result)
                        if result and result[0]:
                            raw = result[0]
                            if isinstance(raw, str):
                                try:
                                    parsed = json.loads(raw)
                                except json.JSONDecodeError:
                                    parsed = ast.literal_eval(raw)
                                if isinstance(parsed, dict):
                                    return parsed.get("results", [])
                                return parsed
                            if isinstance(raw, dict):
                                return raw.get("results", [])
                            return raw
                        return []
                    finally:
                        try:
                            cur.execute("SET statement_timeout = 0")
                        except Exception:
                            pass
        except Exception as e:
            error_str = str(e).lower()
            if "timeout" in error_str or "cancel" in error_str:
                logger.warning(
                    f"Memory search timed out after {timeout}s "
                    f"for query: {query!r}",
                )
            else:
                logger.error(f"Memory search failed: {e}")
            return []

    def close(self) -> None:
        """No-op for individual clients (pool is shared).

        Call ``close_shared_pool()`` at process shutdown to release
        all connections.
        """
        logger.debug(
            "ADBPGMemoryClient.close() called — shared pool stays open.",
        )

    # -----------------------------------------------------------------
    # REST API helpers (used when api_mode == "rest")
    # -----------------------------------------------------------------

    def _rest_url(self, path: str) -> str:
        return f"{self._config.rest_base_url.rstrip('/')}{path}"

    def _log_rest_curl(self, method: str, url: str, body: dict) -> None:
        """Log an equivalent curl command for debugging REST calls."""
        header_parts = []
        for k, v in self._rest_headers.items():
            if k.lower() == "content-type":
                continue
            if k.lower() == "x-auth-token":
                header_parts.append(f"-H '{k}: {v[:12]}***'")
            else:
                header_parts.append(f"-H '{k}: {v}'")
        logger.debug(
            "curl -X %s '%s' -H 'Content-Type: application/json' %s -d '%s'",
            method,
            url,
            " ".join(header_parts),
            json.dumps(body, ensure_ascii=False)[:2000],
        )

    def _rest_identity(self, agent_id: str, user_id: str) -> dict:
        """Common identity fields for REST requests."""
        d: dict = {}
        if agent_id:
            d["agent_id"] = agent_id
        if user_id:
            d["user_id"] = user_id
        return d

    def _rest_add_memory(
        self,
        messages: list[dict],
        user_id: str = "",
        run_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """POST /mem/memories to store memories."""
        import httpx

        body: dict = {
            "messages": messages,
            **self._rest_identity(agent_id or "", user_id),
        }
        if run_id:
            body["run_id"] = run_id
        if metadata:
            body["metadata"] = metadata

        url = self._rest_url("/mem/memories")
        self._log_rest_curl("POST", url, body)
        try:
            with httpx.Client(
                timeout=max(self._rest_timeout, 30.0),
                follow_redirects=True,
            ) as client:
                resp = client.post(
                    url,
                    headers=self._rest_headers,
                    json=body,
                )
                resp.raise_for_status()
                logger.debug("REST add_memory result: %s", resp.text[:500])
        except Exception as e:
            logger.error("REST add_memory failed: %s", e)

    def _rest_search_memory(
        self,
        query: str,
        user_id: str = "",
        agent_id: str | None = None,
        limit: int = 5,
        timeout: float | None = None,
    ) -> list[dict]:
        """POST /mem/search to search memories."""
        import httpx

        body: dict = {
            "query": query,
            **self._rest_identity(agent_id or "", user_id),
        }

        url = self._rest_url("/mem/search")
        req_timeout = timeout or self._rest_timeout
        self._log_rest_curl("POST", url, body)
        try:
            with httpx.Client(
                timeout=req_timeout,
                follow_redirects=True,
            ) as client:
                resp = client.post(
                    url,
                    headers=self._rest_headers,
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    return data.get("results", [])
                if isinstance(data, list):
                    return data
                return []
        except Exception as e:
            error_str = str(e).lower()
            if "timeout" in error_str:
                logger.warning(
                    "REST memory search timed out for query: %r",
                    query,
                )
            else:
                logger.error("REST search_memory failed: %s", e)
            return []


def test_adbpg_connection(
    host: str,
    port: int,
    user: str,
    password: str,
    dbname: str,
) -> tuple[bool, str]:
    """Test connectivity to an ADBPG instance (synchronous, blocking).

    Returns:
        (success, message) tuple.
    """
    if psycopg2 is None:
        return False, "psycopg2 is not installed on the server."
    conn = None
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            connect_timeout=10,
        )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT port FROM gp_segment_configuration "
                "WHERE content = -1 AND role = 'p'",
            )
            row = cur.fetchone()
            if row and row[0]:
                return (
                    True,
                    f"Connection successful (internal port: {row[0]}).",
                )
            return False, (
                "Connected but gp_segment_configuration "
                "returned no master row."
            )
    except Exception as e:
        return False, str(e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
