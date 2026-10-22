"""SQLite-based persistence for feature stores.

Replaces in-memory dicts in api.py with SQLite tables so webhook configs,
analytics data, API keys, RBAC roles/users, and other feature data survive
service restarts.

Uses the same database connection as memory.py (hub.db) to avoid managing
a separate database file.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse the same database as memory.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_DB_PATH = _DATA_DIR / "hub.db"

# Thread-local storage for database connections
_local = threading.local()

# Global lock for schema initialization
_schema_lock = threading.Lock()


def _get_db_path() -> Path:
    """Get database path, respecting HUB_DB_PATH env var for testing."""
    path = os.environ.get("HUB_DB_PATH")
    if path:
        return Path(path)
    return _DB_PATH


def _get_connection() -> sqlite3.Connection:
    """Get a thread-local database connection, creating it if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        max_retries = 5
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(str(db_path), timeout=10.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.row_factory = sqlite3.Row
                _ensure_schema(conn)
                _local.conn = conn
                break
            except sqlite3.OperationalError:
                if conn is not None:
                    conn.close()
                if attempt == max_retries - 1:
                    raise
                time.sleep(0.1 * (attempt + 1))
    return _local.conn


def _add_column_if_not_exists(cursor: sqlite3.Cursor, table: str, column: str, col_type: str) -> None:
    """Add a column to a table if it doesn't already exist."""
    cursor.execute(f"PRAGMA table_info({table})")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if column not in existing_cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create feature store tables if they don't exist."""
    with _schema_lock:
        cursor = conn.cursor()

        # --- Webhooks ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhooks (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                events TEXT NOT NULL DEFAULT '[]',
                secret TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # --- Webhook delivery log ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id TEXT PRIMARY KEY,
                webhook_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                response_code INTEGER,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                FOREIGN KEY (webhook_id) REFERENCES webhooks(id) ON DELETE CASCADE
            )
        """)

        # --- Notification channels ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        # --- Analytics ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analytics_api_calls (
                endpoint TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 1,
                last_updated TEXT NOT NULL,
                PRIMARY KEY (endpoint)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analytics_task_durations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analytics_daily_stats (
                date TEXT NOT NULL,
                service TEXT NOT NULL,
                calls INTEGER NOT NULL DEFAULT 0,
                tasks INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (date, service)
            )
        """)

        # --- API keys ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                permissions TEXT NOT NULL DEFAULT '[]',
                expires_at TEXT,
                last_used_at TEXT,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)

        # --- Service health history ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                status TEXT NOT NULL,
                response_time_ms REAL,
                error TEXT,
                checked_at TEXT NOT NULL
            )
        """)

        # --- Scheduled pipelines ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_pipelines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cron_expr TEXT NOT NULL,
                steps TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                next_run_at TEXT,
                run_count INTEGER NOT NULL DEFAULT 0,
                last_result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # --- Rate limits ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                api_key TEXT PRIMARY KEY,
                requests_per_minute INTEGER NOT NULL DEFAULT 60,
                created_at TEXT NOT NULL
            )
        """)

        # --- Audit log ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                resource_id TEXT,
                actor TEXT,
                details TEXT,
                ip_address TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # --- Templates ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'pipeline',
                content TEXT NOT NULL DEFAULT '{}',
                variables TEXT NOT NULL DEFAULT '[]',
                tags TEXT NOT NULL DEFAULT '[]',
                description TEXT DEFAULT '',
                usage_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # --- Approval workflows ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS approval_policies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                patterns TEXT NOT NULL DEFAULT '[]',
                auto_approve INTEGER NOT NULL DEFAULT 0,
                timeout_minutes INTEGER NOT NULL DEFAULT 30,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS approval_requests (
                id TEXT PRIMARY KEY,
                policy_id TEXT,
                request_data TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                requested_by TEXT,
                decided_by TEXT,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                expires_at TEXT,
                FOREIGN KEY (policy_id) REFERENCES approval_policies(id) ON DELETE SET NULL
            )
        """)

        # --- RBAC roles ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rbac_roles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                permissions TEXT NOT NULL DEFAULT '[]',
                description TEXT DEFAULT '',
                built_in INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        # --- RBAC users ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rbac_users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                role_id TEXT NOT NULL,
                email TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (role_id) REFERENCES rbac_roles(id) ON DELETE RESTRICT
            )
        """)

        # --- Background jobs ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS background_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                error TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            )
        """)

        # --- Response cache ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS response_cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0
            )
        """)

        # --- Message bus ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_bus (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_subscriptions (
                id TEXT PRIMARY KEY,
                topic_pattern TEXT NOT NULL,
                webhook_url TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # --- Feature flags ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feature_flags (
                flag_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                description TEXT DEFAULT '',
                targeting_rules TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # --- Deployments ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deployments (
                id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                commit TEXT,
                branch TEXT,
                deployer TEXT,
                status TEXT NOT NULL DEFAULT 'in_progress',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                duration_seconds REAL
            )
        """)

        # --- Circuit breaker ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS circuit_breaker (
                service TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'closed',
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_failure_at TEXT,
                last_state_change_at TEXT NOT NULL
            )
        """)

        # --- API versions ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_versions (
                version TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'active',
                deprecated_at TEXT,
                sunset_at TEXT,
                migration_path TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # --- DAG tasks ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dag_definitions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tasks TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)

        # --- Multi-tenancy ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                max_agents INTEGER NOT NULL DEFAULT 10,
                max_runs INTEGER NOT NULL DEFAULT 100,
                max_api_keys INTEGER NOT NULL DEFAULT 5,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenant_resources (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
            )
        """)

        # --- Scheduled reports ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_reports (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                report_type TEXT NOT NULL,
                schedule TEXT NOT NULL,
                recipients TEXT NOT NULL DEFAULT '[]',
                config TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # --- File storage metadata ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_storage (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                run_id TEXT,
                size_bytes INTEGER NOT NULL,
                content_type TEXT,
                uploaded_by TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # --- Webhook configs (GitHub/GitLab) ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_configs (
                platform TEXT PRIMARY KEY,
                secret TEXT NOT NULL DEFAULT '',
                pipelines TEXT NOT NULL DEFAULT '[]'
            )
        """)

        # --- Auth users (browser sessions) ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auth_users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                email TEXT DEFAULT '',
                display_name TEXT DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login TEXT
            )
        """)

        # --- Auth sessions ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                expires_at_ts REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                revoked_at TEXT,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES auth_users(id) ON DELETE CASCADE
            )
        """)

        # --- Indexes ---
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhooks_enabled ON webhooks(enabled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries(webhook_id, status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_created ON webhook_deliveries(created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notification_channels_enabled ON notification_channels(enabled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_task_durations_created ON analytics_task_durations(created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analytics_daily_stats_date ON analytics_daily_stats(date DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(active)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_health_service ON service_health(service, checked_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_pipelines_enabled ON scheduled_pipelines(enabled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_templates_type ON templates(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rbac_users_role ON rbac_users(role_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_background_jobs_status ON background_jobs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_response_cache_created ON response_cache(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_bus_topic ON message_bus(topic, created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_deployments_started ON deployments(started_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenant_resources_tenant ON tenant_resources(tenant_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_storage_run ON file_storage(run_id)")

        conn.commit()


# ===================== Webhooks =====================

def init_webhooks() -> Dict[str, Dict[str, Any]]:
    """Load all webhooks from the database into a dict for in-memory caching."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM webhooks"):
        wh = dict(row)
        wh["events"] = json.loads(wh["events"]) if wh["events"] else []
        result[wh["id"]] = wh
    return result


def save_webhook(wh: Dict[str, Any]) -> None:
    """Insert or update a webhook."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    wh["events"] = json.dumps(wh.get("events", []))
    conn.execute(
        """INSERT INTO webhooks (id, url, events, secret, enabled, description, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               url=excluded.url, events=excluded.events, secret=excluded.secret,
               enabled=excluded.enabled, description=excluded.description, updated_at=excluded.updated_at""",
        (wh["id"], wh["url"], wh["events"], wh.get("secret"),
         wh.get("enabled", 1), wh.get("description", ""),
         wh.get("created_at", now), now)
    )
    conn.commit()


def delete_webhook(webhook_id: str) -> None:
    """Delete a webhook by ID."""
    conn = _get_connection()
    conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
    conn.commit()


def log_webhook_delivery(delivery: Dict[str, Any]) -> None:
    """Log a webhook delivery attempt."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO webhook_deliveries
           (id, webhook_id, event_type, payload, status, response_code, error, attempts, created_at, delivered_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (delivery.get("id", str(uuid.uuid4())), delivery["webhook_id"],
         delivery["event_type"], json.dumps(delivery.get("payload", {})),
         delivery.get("status", "pending"), delivery.get("response_code"),
         delivery.get("error"), delivery.get("attempts", 0),
         delivery.get("created_at", now), delivery.get("delivered_at"))
    )
    conn.commit()


def get_webhook_deliveries(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent webhook deliveries."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM webhook_deliveries ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        result.append(d)
    return result


# ===================== Notification Channels =====================

def init_notification_channels() -> Dict[str, Dict[str, Any]]:
    """Load all notification channels from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM notification_channels"):
        ch = dict(row)
        ch["config"] = json.loads(ch["config"]) if ch["config"] else {}
        result[ch["id"]] = ch
    return result


def save_notification_channel(ch: Dict[str, Any]) -> None:
    """Insert or update a notification channel."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    ch["config"] = json.dumps(ch.get("config", {}))
    conn.execute(
        """INSERT INTO notification_channels (id, name, type, config, enabled, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, type=excluded.type, config=excluded.config,
               enabled=excluded.enabled""",
        (ch["id"], ch["name"], ch["type"], ch["config"],
         ch.get("enabled", 1), ch.get("created_at", now))
    )
    conn.commit()


def delete_notification_channel(channel_id: str) -> None:
    """Delete a notification channel by ID."""
    conn = _get_connection()
    conn.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))
    conn.commit()


# ===================== Analytics =====================

def init_analytics() -> Dict[str, Any]:
    """Load analytics data from the database."""
    conn = _get_connection()

    api_calls = {}
    for row in conn.execute("SELECT endpoint, count FROM analytics_api_calls"):
        api_calls[row["endpoint"]] = row["count"]

    task_durations = []
    for row in conn.execute(
        "SELECT service, duration_ms, status FROM analytics_task_durations ORDER BY created_at DESC LIMIT 1000"
    ):
        task_durations.append((row["service"], row["duration_ms"], row["status"]))

    daily_stats = {}
    for row in conn.execute("SELECT date, service, calls, tasks, errors FROM analytics_daily_stats"):
        key = f"{row['date']}_{row['service']}"
        daily_stats[key] = {"calls": row["calls"], "tasks": row["tasks"], "errors": row["errors"]}

    return {
        "api_calls": api_calls,
        "task_durations": task_durations,
        "daily_stats": daily_stats,
    }


def track_api_call(endpoint: str) -> None:
    """Increment the API call counter for an endpoint."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO analytics_api_calls (endpoint, count, last_updated)
           VALUES (?, 1, ?)
           ON CONFLICT(endpoint) DO UPDATE SET
               count=count+1, last_updated=excluded.last_updated""",
        (endpoint, now)
    )
    conn.commit()


def track_task_duration(service: str, duration_ms: float, status: str) -> None:
    """Record a task duration."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO analytics_task_durations (service, duration_ms, status, created_at) VALUES (?, ?, ?, ?)",
        (service, duration_ms, status, now)
    )
    # Keep only last 1000 entries
    conn.execute(
        """DELETE FROM analytics_task_durations WHERE id NOT IN
           (SELECT id FROM analytics_task_durations ORDER BY created_at DESC LIMIT 1000)"""
    )
    conn.commit()


def update_daily_stats(date: str, service: str, calls: int = 0, tasks: int = 0, errors: int = 0) -> None:
    """Update daily aggregated stats."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO analytics_daily_stats (date, service, calls, tasks, errors)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(date, service) DO UPDATE SET
               calls=calls+excluded.calls, tasks=tasks+excluded.tasks, errors=errors+excluded.errors""",
        (date, service, calls, tasks, errors)
    )
    conn.commit()


# ===================== API Keys =====================

def init_api_keys() -> Dict[str, Dict[str, Any]]:
    """Load all API keys from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM api_keys"):
        key = dict(row)
        key["permissions"] = json.loads(key["permissions"]) if key["permissions"] else []
        result[key["key"]] = key
    return result


def save_api_key(api_key_data: Dict[str, Any]) -> None:
    """Insert or update an API key."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    api_key_data["permissions"] = json.dumps(api_key_data.get("permissions", []))
    conn.execute(
        """INSERT INTO api_keys (key, name, permissions, expires_at, last_used_at, created_at, active)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET
               name=excluded.name, permissions=excluded.permissions,
               expires_at=excluded.expires_at, last_used_at=excluded.last_used_at,
               active=excluded.active""",
        (api_key_data["key"], api_key_data["name"], api_key_data["permissions"],
         api_key_data.get("expires_at"), api_key_data.get("last_used_at"),
         api_key_data.get("created_at", now), api_key_data.get("active", 1))
    )
    conn.commit()


def delete_api_key(key: str) -> None:
    """Delete an API key."""
    conn = _get_connection()
    conn.execute("DELETE FROM api_keys WHERE key = ?", (key,))
    conn.commit()


def get_active_api_keys() -> Dict[str, Dict[str, Any]]:
    """Get all active (non-expired) API keys."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    result = {}
    for row in conn.execute(
        "SELECT * FROM api_keys WHERE active = 1 AND (expires_at IS NULL OR expires_at > ?)", (now,)
    ):
        key = dict(row)
        key["permissions"] = json.loads(key["permissions"]) if key["permissions"] else []
        result[key["key"]] = key
    return result


# ===================== Service Health =====================

def record_service_health(service: str, status: str, response_time_ms: Optional[float] = None,
                          error: Optional[str] = None) -> None:
    """Record a service health check result."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO service_health (service, status, response_time_ms, error, checked_at) VALUES (?, ?, ?, ?, ?)",
        (service, status, response_time_ms, error, now)
    )
    # Keep only last 100 entries per service
    conn.execute(
        """DELETE FROM service_health WHERE id NOT IN
           (SELECT id FROM service_health WHERE service = ? ORDER BY checked_at DESC LIMIT 100)""",
        (service,)
    )
    conn.commit()


def get_service_health(service: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent health checks for a service."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM service_health WHERE service = ? ORDER BY checked_at DESC LIMIT ?",
        (service, limit)
    ).fetchall()
    return [dict(row) for row in rows]


# ===================== Scheduled Pipelines =====================

def init_scheduled_pipelines() -> Dict[str, Dict[str, Any]]:
    """Load all scheduled pipelines from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM scheduled_pipelines"):
        sp = dict(row)
        sp["steps"] = json.loads(sp["steps"]) if sp["steps"] else []
        sp["last_result"] = json.loads(sp["last_result"]) if sp.get("last_result") else None
        result[sp["id"]] = sp
    return result


def save_scheduled_pipeline(sp: Dict[str, Any]) -> None:
    """Insert or update a scheduled pipeline."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    sp["steps"] = json.dumps(sp.get("steps", []))
    sp["last_result"] = json.dumps(sp.get("last_result")) if sp.get("last_result") is not None else None
    conn.execute(
        """INSERT INTO scheduled_pipelines
           (id, name, cron_expr, steps, enabled, last_run_at, next_run_at, run_count, last_result, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, cron_expr=excluded.cron_expr, steps=excluded.steps,
               enabled=excluded.enabled, last_run_at=excluded.last_run_at,
               next_run_at=excluded.next_run_at, run_count=excluded.run_count,
               last_result=excluded.last_result, updated_at=excluded.updated_at""",
        (sp["id"], sp["name"], sp["cron_expr"], sp["steps"],
         sp.get("enabled", 1), sp.get("last_run_at"), sp.get("next_run_at"),
         sp.get("run_count", 0), sp["last_result"],
         sp.get("created_at", now), now)
    )
    conn.commit()


def delete_scheduled_pipeline(pipeline_id: str) -> None:
    """Delete a scheduled pipeline."""
    conn = _get_connection()
    conn.execute("DELETE FROM scheduled_pipelines WHERE id = ?", (pipeline_id,))
    conn.commit()


def update_scheduled_pipeline_run(sp_id: str, last_run_at: str, next_run_at: Optional[str],
                                   run_count: int, last_result: Optional[Dict]) -> None:
    """Update the run metadata for a scheduled pipeline."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    last_result_json = json.dumps(last_result) if last_result is not None else None
    conn.execute(
        """UPDATE scheduled_pipelines SET last_run_at=?, next_run_at=?, run_count=?,
           last_result=?, updated_at=? WHERE id=?""",
        (last_run_at, next_run_at, run_count, last_result_json, now, sp_id)
    )
    conn.commit()


# ===================== Rate Limits =====================

def init_rate_limits() -> Dict[str, int]:
    """Load rate limit configs from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT api_key, requests_per_minute FROM rate_limits"):
        result[row["api_key"]] = row["requests_per_minute"]
    return result


def save_rate_limit(api_key: str, requests_per_minute: int) -> None:
    """Set a custom rate limit for an API key."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO rate_limits (api_key, requests_per_minute, created_at)
           VALUES (?, ?, ?)
           ON CONFLICT(api_key) DO UPDATE SET requests_per_minute=excluded.requests_per_minute""",
        (api_key, requests_per_minute, now)
    )
    conn.commit()


# ===================== Audit Log =====================

def log_audit(action: str, resource: str, resource_id: Optional[str] = None,
              actor: Optional[str] = None, details: Optional[str] = None,
              ip_address: Optional[str] = None) -> None:
    """Add an entry to the audit log."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO audit_log (action, resource, resource_id, actor, details, ip_address, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (action, resource, resource_id, actor, details, ip_address, now)
    )
    # Keep only last 5000 entries
    conn.execute(
        """DELETE FROM audit_log WHERE id NOT IN
           (SELECT id FROM audit_log ORDER BY created_at DESC LIMIT 5000)"""
    )
    conn.commit()


def get_audit_log(limit: int = 100, action: Optional[str] = None,
                  actor: Optional[str] = None, resource: Optional[str] = None) -> List[Dict[str, Any]]:
    """Query the audit log with optional filters."""
    conn = _get_connection()
    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    if action:
        query += " AND action = ?"
        params.append(action)
    if actor:
        query += " AND actor = ?"
        params.append(actor)
    if resource:
        query += " AND resource = ?"
        params.append(resource)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


# ===================== Templates =====================

def init_templates() -> Dict[str, Dict[str, Any]]:
    """Load all templates from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM templates"):
        t = dict(row)
        t["content"] = json.loads(t["content"]) if t["content"] else {}
        t["variables"] = json.loads(t["variables"]) if t["variables"] else []
        t["tags"] = json.loads(t["tags"]) if t["tags"] else []
        result[t["id"]] = t
    return result


def save_template(template: Dict[str, Any]) -> None:
    """Insert or update a template."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    template["content"] = json.dumps(template.get("content", {}))
    template["variables"] = json.dumps(template.get("variables", []))
    template["tags"] = json.dumps(template.get("tags", []))
    conn.execute(
        """INSERT INTO templates (id, name, type, content, variables, tags, description, usage_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, type=excluded.type, content=excluded.content,
               variables=excluded.variables, tags=excluded.tags, description=excluded.description,
               usage_count=excluded.usage_count, updated_at=excluded.updated_at""",
        (template["id"], template["name"], template.get("type", "pipeline"),
         template["content"], template["variables"], template["tags"],
         template.get("description", ""), template.get("usage_count", 0),
         template.get("created_at", now), now)
    )
    conn.commit()


def delete_template(template_id: str) -> None:
    """Delete a template."""
    conn = _get_connection()
    conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    conn.commit()


def increment_template_usage(template_id: str) -> None:
    """Increment the usage counter for a template."""
    conn = _get_connection()
    conn.execute("UPDATE templates SET usage_count = usage_count + 1 WHERE id = ?", (template_id,))
    conn.commit()


# ===================== Approval Workflows =====================

def init_approval_policies() -> Dict[str, Dict[str, Any]]:
    """Load approval policies from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM approval_policies"):
        p = dict(row)
        p["patterns"] = json.loads(p["patterns"]) if p["patterns"] else []
        result[p["id"]] = p
    return result


def save_approval_policy(policy: Dict[str, Any]) -> None:
    """Insert or update an approval policy."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    policy["patterns"] = json.dumps(policy.get("patterns", []))
    conn.execute(
        """INSERT INTO approval_policies (id, name, patterns, auto_approve, timeout_minutes, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, patterns=excluded.patterns,
               auto_approve=excluded.auto_approve, timeout_minutes=excluded.timeout_minutes""",
        (policy["id"], policy["name"], policy["patterns"],
         policy.get("auto_approve", 0), policy.get("timeout_minutes", 30),
         policy.get("created_at", now))
    )
    conn.commit()


def init_approval_requests() -> Dict[str, Dict[str, Any]]:
    """Load approval requests from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM approval_requests"):
        r = dict(row)
        r["request_data"] = json.loads(r["request_data"]) if r["request_data"] else {}
        result[r["id"]] = r
    return result


def save_approval_request(req: Dict[str, Any]) -> None:
    """Insert or update an approval request."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    req["request_data"] = json.dumps(req.get("request_data", {}))
    conn.execute(
        """INSERT INTO approval_requests
           (id, policy_id, request_data, status, requested_by, decided_by, created_at, decided_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, decided_by=excluded.decided_by,
               decided_at=excluded.decided_at""",
        (req["id"], req.get("policy_id"), req["request_data"],
         req.get("status", "pending"), req.get("requested_by"),
         req.get("decided_by"), req.get("created_at", now),
         req.get("decided_at"), req.get("expires_at"))
    )
    conn.commit()


# ===================== RBAC =====================

def init_rbac_roles() -> Dict[str, Dict[str, Any]]:
    """Load RBAC roles from the database, seeding built-in roles if empty."""
    conn = _get_connection()
    result = {}
    count = conn.execute("SELECT COUNT(*) as c FROM rbac_roles").fetchone()["c"]
    if count == 0:
        # Seed built-in roles
        now = datetime.now(timezone.utc).isoformat()
        builtin_roles = [
            {"id": "admin", "name": "Admin", "permissions": ["*"], "description": "Full access"},
            {"id": "developer", "name": "Developer", "permissions": ["agents:*", "runs:*", "pipelines:*", "schedules:*", "search", "health"],
             "description": "Can manage agents and runs"},
            {"id": "viewer", "name": "Viewer", "permissions": ["agents:read", "runs:read", "health"],
             "description": "Read-only access"},
        ]
        for role in builtin_roles:
            conn.execute(
                "INSERT INTO rbac_roles (id, name, permissions, description, built_in, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (role["id"], role["name"], json.dumps(role["permissions"]),
                 role["description"], now)
            )
        conn.commit()

    for row in conn.execute("SELECT * FROM rbac_roles"):
        r = dict(row)
        r["permissions"] = json.loads(r["permissions"]) if r["permissions"] else []
        result[r["id"]] = r
    return result


def save_rbac_role(role: Dict[str, Any]) -> None:
    """Insert or update an RBAC role."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    role["permissions"] = json.dumps(role.get("permissions", []))
    conn.execute(
        """INSERT INTO rbac_roles (id, name, permissions, description, built_in, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, permissions=excluded.permissions,
               description=excluded.description""",
        (role["id"], role["name"], role["permissions"],
         role.get("description", ""), role.get("built_in", 0),
         role.get("created_at", now))
    )
    conn.commit()


def delete_rbac_role(role_id: str) -> None:
    """Delete a non-built-in RBAC role."""
    conn = _get_connection()
    conn.execute("DELETE FROM rbac_roles WHERE id = ? AND built_in = 0", (role_id,))
    conn.commit()


def init_rbac_users() -> Dict[str, Dict[str, Any]]:
    """Load RBAC users from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM rbac_users"):
        result[row["id"]] = dict(row)
    return result


def save_rbac_user(user: Dict[str, Any]) -> None:
    """Insert or update an RBAC user."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO rbac_users (id, username, role_id, email, active, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               username=excluded.username, role_id=excluded.role_id,
               email=excluded.email, active=excluded.active""",
        (user["id"], user["username"], user["role_id"],
         user.get("email"), user.get("active", 1),
         user.get("created_at", now))
    )
    conn.commit()


def delete_rbac_user(user_id: str) -> None:
    """Delete an RBAC user."""
    conn = _get_connection()
    conn.execute("DELETE FROM rbac_users WHERE id = ?", (user_id,))
    conn.commit()


# ===================== Background Jobs =====================

def init_background_jobs() -> Dict[str, Dict[str, Any]]:
    """Load active background jobs from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM background_jobs WHERE status IN ('pending', 'running')"):
        job = dict(row)
        job["payload"] = json.loads(job["payload"]) if job["payload"] else {}
        job["result"] = json.loads(job["result"]) if job.get("result") else None
        result[job["id"]] = job
    return result


def save_background_job(job: Dict[str, Any]) -> None:
    """Insert or update a background job."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    job["payload"] = json.dumps(job.get("payload", {}))
    job["result"] = json.dumps(job.get("result")) if job.get("result") is not None else None
    conn.execute(
        """INSERT INTO background_jobs
           (id, type, payload, status, result, error, attempts, max_attempts, created_at, started_at, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, result=excluded.result, error=excluded.error,
               attempts=excluded.attempts, started_at=excluded.started_at,
               completed_at=excluded.completed_at""",
        (job["id"], job["type"], job["payload"], job.get("status", "pending"),
         job["result"], job.get("error"), job.get("attempts", 0),
         job.get("max_attempts", 3), job.get("created_at", now),
         job.get("started_at"), job.get("completed_at"))
    )
    conn.commit()


def get_dead_letter_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """Get failed jobs that exceeded max attempts."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM background_jobs WHERE status = 'failed' ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    result = []
    for row in rows:
        j = dict(row)
        j["payload"] = json.loads(j["payload"]) if j["payload"] else {}
        j["result"] = json.loads(j["result"]) if j.get("result") else None
        result.append(j)
    return result


# ===================== Response Cache =====================

def get_cached(key: str, ttl_seconds: int) -> Optional[str]:
    """Get a cached value if it exists and hasn't expired."""
    conn = _get_connection()
    row = conn.execute("SELECT * FROM response_cache WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    row = dict(row)
    created = datetime.fromisoformat(row["created_at"])
    now = datetime.now(timezone.utc)
    if (now - created).total_seconds() > ttl_seconds:
        conn.execute("DELETE FROM response_cache WHERE key = ?", (key,))
        conn.commit()
        return None
    # Increment hit counter
    conn.execute("UPDATE response_cache SET hits = hits + 1 WHERE key = ?", (key,))
    conn.commit()
    return row["value"]


def set_cached(key: str, value: str, ttl_seconds: int) -> None:
    """Store a value in the cache."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO response_cache (key, value, ttl_seconds, created_at, hits)
           VALUES (?, ?, ?, ?, 0)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, ttl_seconds=excluded.ttl_seconds,
               created_at=excluded.created_at, hits=0""",
        (key, value, ttl_seconds, now)
    )
    # Evict oldest entries if over 500
    conn.execute(
        """DELETE FROM response_cache WHERE id NOT IN
           (SELECT id FROM response_cache ORDER BY created_at DESC LIMIT 500)"""
    )
    conn.commit()


def clear_cache() -> None:
    """Clear all cached entries."""
    conn = _get_connection()
    conn.execute("DELETE FROM response_cache")
    conn.commit()


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    conn = _get_connection()
    total = conn.execute("SELECT COUNT(*) as c FROM response_cache").fetchone()["c"]
    hits = conn.execute("SELECT COALESCE(SUM(hits), 0) as h FROM response_cache").fetchone()["h"]
    return {"total_entries": total, "total_hits": hits}


# ===================== Message Bus =====================

def publish_message(topic: str, payload: Dict[str, Any]) -> str:
    """Publish a message to a topic."""
    conn = _get_connection()
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO message_bus (id, topic, payload, created_at) VALUES (?, ?, ?, ?)",
        (msg_id, topic, json.dumps(payload), now)
    )
    # Keep only last 500 messages per topic
    conn.execute(
        """DELETE FROM message_bus WHERE id NOT IN
           (SELECT id FROM message_bus WHERE topic = ? ORDER BY created_at DESC LIMIT 500)""",
        (topic,)
    )
    conn.commit()
    return msg_id


def get_messages(topic: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent messages for a topic."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM message_bus WHERE topic = ? ORDER BY created_at DESC LIMIT ?",
        (topic, limit)
    ).fetchall()
    result = []
    for row in rows:
        m = dict(row)
        m["payload"] = json.loads(m["payload"]) if m["payload"] else {}
        result.append(m)
    return result


def init_message_subscriptions() -> Dict[str, Dict[str, Any]]:
    """Load message bus subscriptions from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM message_subscriptions"):
        result[row["id"]] = dict(row)
    return result


def save_message_subscription(sub: Dict[str, Any]) -> None:
    """Insert or update a message subscription."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO message_subscriptions (id, topic_pattern, webhook_url, created_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               topic_pattern=excluded.topic_pattern, webhook_url=excluded.webhook_url""",
        (sub["id"], sub["topic_pattern"], sub.get("webhook_url"),
         sub.get("created_at", now))
    )
    conn.commit()


def delete_message_subscription(sub_id: str) -> None:
    """Delete a message subscription."""
    conn = _get_connection()
    conn.execute("DELETE FROM message_subscriptions WHERE id = ?", (sub_id,))
    conn.commit()


# ===================== Feature Flags =====================

def init_feature_flags() -> Dict[str, Dict[str, Any]]:
    """Load feature flags from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM feature_flags"):
        f = dict(row)
        f["targeting_rules"] = json.loads(f["targeting_rules"]) if f["targeting_rules"] else {}
        result[f["flag_key"]] = f
    return result


def save_feature_flag(flag: Dict[str, Any]) -> None:
    """Insert or update a feature flag."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    flag["targeting_rules"] = json.dumps(flag.get("targeting_rules", {}))
    conn.execute(
        """INSERT INTO feature_flags (flag_key, name, enabled, description, targeting_rules, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(flag_key) DO UPDATE SET
               name=excluded.name, enabled=excluded.enabled, description=excluded.description,
               targeting_rules=excluded.targeting_rules, updated_at=excluded.updated_at""",
        (flag["flag_key"], flag["name"], flag.get("enabled", 0),
         flag.get("description", ""), flag["targeting_rules"],
         flag.get("created_at", now), now)
    )
    conn.commit()


def delete_feature_flag(flag_key: str) -> None:
    """Delete a feature flag."""
    conn = _get_connection()
    conn.execute("DELETE FROM feature_flags WHERE flag_key = ?", (flag_key,))
    conn.commit()


# ===================== Deployments =====================

def save_deployment(dep: Dict[str, Any]) -> None:
    """Insert or update a deployment."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO deployments
           (id, version, commit, branch, deployer, status, started_at, completed_at, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, completed_at=excluded.completed_at,
               duration_seconds=excluded.duration_seconds""",
        (dep["id"], dep["version"], dep.get("commit"), dep.get("branch"),
         dep.get("deployer"), dep.get("status", "in_progress"),
         dep.get("started_at", now), dep.get("completed_at"),
         dep.get("duration_seconds"))
    )
    conn.commit()


def get_deployments(limit: int = 20) -> List[Dict[str, Any]]:
    """Get recent deployments."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM deployments ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


# ===================== Circuit Breaker =====================

def init_circuit_breakers() -> Dict[str, Dict[str, Any]]:
    """Load circuit breaker states from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM circuit_breaker"):
        result[row["service"]] = dict(row)
    return result


def save_circuit_breaker(service: str, state: str, failure_count: int,
                          last_failure_at: Optional[str] = None) -> None:
    """Update circuit breaker state for a service."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO circuit_breaker (service, state, failure_count, last_failure_at, last_state_change_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(service) DO UPDATE SET
               state=excluded.state, failure_count=excluded.failure_count,
               last_failure_at=excluded.last_failure_at, last_state_change_at=excluded.last_state_change_at""",
        (service, state, failure_count, last_failure_at, now)
    )
    conn.commit()


# ===================== API Versions =====================

def init_api_versions() -> Dict[str, Dict[str, Any]]:
    """Load API versions from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM api_versions"):
        result[row["version"]] = dict(row)
    return result


def save_api_version(version: Dict[str, Any]) -> None:
    """Insert or update an API version."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO api_versions (version, status, deprecated_at, sunset_at, migration_path, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(version) DO UPDATE SET
               status=excluded.status, deprecated_at=excluded.deprecated_at,
               sunset_at=excluded.sunset_at, migration_path=excluded.migration_path""",
        (version["version"], version.get("status", "active"),
         version.get("deprecated_at"), version.get("sunset_at"),
         version.get("migration_path"), version.get("created_at", now))
    )
    conn.commit()


# ===================== DAG Definitions =====================

def init_dag_definitions() -> Dict[str, Dict[str, Any]]:
    """Load DAG task definitions from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM dag_definitions"):
        d = dict(row)
        d["tasks"] = json.loads(d["tasks"]) if d["tasks"] else {}
        result[d["id"]] = d
    return result


def save_dag_definition(dag: Dict[str, Any]) -> None:
    """Insert or update a DAG definition."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    dag["tasks"] = json.dumps(dag.get("tasks", {}))
    conn.execute(
        """INSERT INTO dag_definitions (id, name, tasks, created_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, tasks=excluded.tasks""",
        (dag["id"], dag["name"], dag["tasks"], dag.get("created_at", now))
    )
    conn.commit()


def delete_dag_definition(dag_id: str) -> None:
    """Delete a DAG definition."""
    conn = _get_connection()
    conn.execute("DELETE FROM dag_definitions WHERE id = ?", (dag_id,))
    conn.commit()


# ===================== Multi-Tenancy =====================

def init_tenants() -> Dict[str, Dict[str, Any]]:
    """Load tenants from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM tenants"):
        result[row["id"]] = dict(row)
    return result


def save_tenant(tenant: Dict[str, Any]) -> None:
    """Insert or update a tenant."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO tenants (id, name, max_agents, max_runs, max_api_keys, active, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, max_agents=excluded.max_agents,
               max_runs=excluded.max_runs, max_api_keys=excluded.max_api_keys,
               active=excluded.active""",
        (tenant["id"], tenant["name"], tenant.get("max_agents", 10),
         tenant.get("max_runs", 100), tenant.get("max_api_keys", 5),
         tenant.get("active", 1), tenant.get("created_at", now))
    )
    conn.commit()


def delete_tenant(tenant_id: str) -> None:
    """Delete a tenant."""
    conn = _get_connection()
    conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
    conn.commit()


def init_tenant_resources() -> Dict[str, List[Dict[str, Any]]]:
    """Load tenant resource assignments from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM tenant_resources"):
        r = dict(row)
        tenant_id = r["tenant_id"]
        if tenant_id not in result:
            result[tenant_id] = []
        result[tenant_id].append(r)
    return result


def save_tenant_resource(resource: Dict[str, Any]) -> None:
    """Assign a resource to a tenant."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO tenant_resources (id, tenant_id, resource_type, resource_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (resource["id"], resource["tenant_id"], resource["resource_type"],
         resource["resource_id"], now)
    )
    conn.commit()


def delete_tenant_resource(resource_id: str) -> None:
    """Remove a resource from a tenant."""
    conn = _get_connection()
    conn.execute("DELETE FROM tenant_resources WHERE id = ?", (resource_id,))
    conn.commit()


# ===================== Scheduled Reports =====================

def init_scheduled_reports() -> Dict[str, Dict[str, Any]]:
    """Load scheduled reports from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM scheduled_reports"):
        r = dict(row)
        r["recipients"] = json.loads(r["recipients"]) if r["recipients"] else []
        r["config"] = json.loads(r["config"]) if r["config"] else {}
        result[r["id"]] = r
    return result


def save_scheduled_report(report: Dict[str, Any]) -> None:
    """Insert or update a scheduled report."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    report["recipients"] = json.dumps(report.get("recipients", []))
    report["config"] = json.dumps(report.get("config", {}))
    conn.execute(
        """INSERT INTO scheduled_reports
           (id, name, report_type, schedule, recipients, config, enabled, last_run_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, report_type=excluded.report_type,
               schedule=excluded.schedule, recipients=excluded.recipients,
               config=excluded.config, enabled=excluded.enabled,
               last_run_at=excluded.last_run_at""",
        (report["id"], report["name"], report["report_type"], report["schedule"],
         report["recipients"], report["config"], report.get("enabled", 1),
         report.get("last_run_at"), report.get("created_at", now))
    )
    conn.commit()


def delete_scheduled_report(report_id: str) -> None:
    """Delete a scheduled report."""
    conn = _get_connection()
    conn.execute("DELETE FROM scheduled_reports WHERE id = ?", (report_id,))
    conn.commit()


# ===================== File Storage Metadata =====================

def save_file_metadata(file_info: Dict[str, Any]) -> None:
    """Store file upload metadata."""
    conn = _get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO file_storage (id, filename, run_id, size_bytes, content_type, uploaded_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (file_info["id"], file_info["filename"], file_info.get("run_id"),
         file_info["size_bytes"], file_info.get("content_type"),
         file_info.get("uploaded_by"), now)
    )
    conn.commit()


def get_file_metadata(file_id: str) -> Optional[Dict[str, Any]]:
    """Get file metadata by ID."""
    conn = _get_connection()
    row = conn.execute("SELECT * FROM file_storage WHERE id = ?", (file_id,)).fetchone()
    if row:
        return dict(row)
    return None


def list_files(run_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List files, optionally filtered by run_id."""
    conn = _get_connection()
    if run_id:
        rows = conn.execute(
            "SELECT * FROM file_storage WHERE run_id = ? ORDER BY created_at DESC LIMIT ?",
            (run_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM file_storage ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def delete_file_metadata(file_id: str) -> None:
    """Delete file metadata."""
    conn = _get_connection()
    conn.execute("DELETE FROM file_storage WHERE id = ?", (file_id,))
    conn.commit()


# ===================== Webhook Configs (GitHub/GitLab) =====================

def init_webhook_configs() -> Dict[str, Dict[str, Any]]:
    """Load webhook configurations from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM webhook_configs"):
        r = dict(row)
        r["pipelines"] = json.loads(r["pipelines"]) if r["pipelines"] else []
        result[r["platform"]] = r
    return result


def save_webhook_config(config: Dict[str, Any]) -> None:
    """Insert or update a webhook configuration."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO webhook_configs (platform, secret, pipelines)
           VALUES (?, ?, ?)
           ON CONFLICT(platform) DO UPDATE SET
               secret=excluded.secret, pipelines=excluded.pipelines""",
        (config["id"], config.get("secret", ""),
         json.dumps(config.get("pipelines", [])))
    )
    conn.commit()


def delete_webhook_config(platform: str) -> None:
    """Delete a webhook configuration."""
    conn = _get_connection()
    conn.execute("DELETE FROM webhook_configs WHERE platform = ?", (platform,))
    conn.commit()


# ===================== Initialization Helper =====================

def init_audit_log() -> List[Dict[str, Any]]:
    """Load audit log entries from the database."""
    conn = _get_connection()
    result = []
    for row in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 5000"):
        r = dict(row)
        r["metadata"] = json.loads(r["metadata"]) if r["metadata"] else {}
        result.append(r)
    return result


def init_file_storage() -> Dict[str, Any]:
    """Load file storage metadata from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM file_storage"):
        r = dict(row)
        result[r["id"]] = r
    return result


def init_response_cache() -> Dict[str, Any]:
    """Load response cache entries from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM response_cache"):
        r = dict(row)
        r["value"] = json.loads(r["value"])
        result[r["key"]] = r
    return result


def init_deployments() -> Dict[str, Any]:
    """Load deployments from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM deployments"):
        r = dict(row)
        r["metadata"] = json.loads(r["metadata"]) if r["metadata"] else {}
        result[r["id"]] = r
    return result


def init_message_bus() -> Dict[str, List[Dict[str, Any]]]:
    """Load message bus messages from the database."""
    conn = _get_connection()
    result: Dict[str, List[Dict[str, Any]]] = {}
    for row in conn.execute("SELECT * FROM message_bus ORDER BY created_at DESC"):
        r = dict(row)
        r["payload"] = json.loads(r["payload"])
        topic = r["topic"]
        if topic not in result:
            result[topic] = []
        result[topic].append(r)
    return result


# ===================== Auth Users =====================

def init_auth_users() -> Dict[str, Dict[str, Any]]:
    """Load auth users from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM auth_users"):
        r = dict(row)
        r["is_active"] = bool(r["is_active"])
        result[r["username"]] = r
    return result


def save_auth_user(user: Dict[str, Any]) -> None:
    """Insert or update an auth user."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO auth_users (id, username, password_hash, role, email, display_name,
                                    is_active, created_at, updated_at, last_login)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(username) DO UPDATE SET
               password_hash=excluded.password_hash, role=excluded.role,
               email=excluded.email, display_name=excluded.display_name,
               is_active=excluded.is_active, updated_at=excluded.updated_at,
               last_login=excluded.last_login""",
        (user["id"], user["username"], user["password_hash"], user.get("role", "user"),
         user.get("email", ""), user.get("display_name", ""),
         1 if user.get("is_active", True) else 0,
         user.get("created_at", datetime.now(timezone.utc).isoformat()),
         user.get("updated_at", datetime.now(timezone.utc).isoformat()),
         user.get("last_login")),
    )
    conn.commit()


def delete_auth_user(username: str) -> None:
    """Delete an auth user."""
    conn = _get_connection()
    conn.execute("DELETE FROM auth_users WHERE username = ?", (username,))
    conn.commit()


# ===================== Auth Sessions =====================

def init_auth_sessions() -> Dict[str, Dict[str, Any]]:
    """Load auth sessions from the database."""
    conn = _get_connection()
    result = {}
    for row in conn.execute("SELECT * FROM auth_sessions"):
        r = dict(row)
        r["revoked"] = bool(r["revoked"])
        result[r["session_id"]] = r
    return result


def save_auth_session(session: Dict[str, Any]) -> None:
    """Insert or update an auth session."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO auth_sessions (session_id, user_id, username, created_at,
                                      expires_at, expires_at_ts, revoked, revoked_at,
                                      ip_address, user_agent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET
               revoked=excluded.revoked, revoked_at=excluded.revoked_at,
               ip_address=excluded.ip_address, user_agent=excluded.user_agent""",
        (session["session_id"], session["user_id"], session["username"],
         session["created_at"], session["expires_at"], session["expires_at_ts"],
         1 if session.get("revoked") else 0, session.get("revoked_at"),
         session.get("ip_address"), session.get("user_agent")),
    )
    conn.commit()


def delete_auth_session(session_id: str) -> None:
    """Delete an auth session."""
    conn = _get_connection()
    conn.execute("DELETE FROM auth_sessions WHERE session_id = ?", (session_id,))
    conn.commit()


def cleanup_auth_sessions() -> int:
    """Remove expired and revoked sessions from the database."""
    import time
    now = time.time()
    conn = _get_connection()
    cursor = conn.execute(
        "DELETE FROM auth_sessions WHERE expires_at_ts < ? OR revoked = 1",
        (now,)
    )
    count = cursor.rowcount
    conn.commit()
    return count


def init_all() -> Dict[str, Any]:
    """Initialize all feature stores from the database.

    Returns a dict with all store data for api.py to use on startup.
    """
    return {
        "webhooks": init_webhooks(),
        "notification_channels": init_notification_channels(),
        "analytics": init_analytics(),
        "api_keys": init_api_keys(),
        "scheduled_pipelines": init_scheduled_pipelines(),
        "rate_limits": init_rate_limits(),
        "templates": init_templates(),
        "approval_policies": init_approval_policies(),
        "approval_requests": init_approval_requests(),
        "rbac_roles": init_rbac_roles(),
        "rbac_users": init_rbac_users(),
        "background_jobs": init_background_jobs(),
        "message_subscriptions": init_message_subscriptions(),
        "feature_flags": init_feature_flags(),
        "circuit_breakers": init_circuit_breakers(),
        "api_versions": init_api_versions(),
        "dag_definitions": init_dag_definitions(),
        "tenants": init_tenants(),
        "tenant_resources": init_tenant_resources(),
        "scheduled_reports": init_scheduled_reports(),
        "webhook_configs": init_webhook_configs(),
        "audit_log": init_audit_log(),
        "file_storage": init_file_storage(),
        "response_cache": init_response_cache(),
        "deployments": init_deployments(),
        "message_bus": init_message_bus(),
        "auth_users": init_auth_users(),
        "auth_sessions": init_auth_sessions(),
    }
