"""Environment-driven settings. Every variable is documented in the kit's ``.env.example``.

Secrets are read here and passed to adapters; they are never logged, and
``Settings.__repr__`` masks them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from datetime import timedelta
from pathlib import Path

from .errors import ConfigError

_SECRET_FIELD_HINTS = ("password", "token", "secret", "api_key")


def load_dotenv_if_present(path: Path | None = None) -> None:
    """Load ``.env`` without overriding variables already set (systemd/cron env wins)."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # optional dependency
        return
    candidate = path or Path(os.environ.get("OPSI_ENV_FILE", ".env"))
    if candidate.is_file():
        load_dotenv(candidate, override=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = _env(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true/false, got {raw!r}")


def _csv(name: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _env(name).split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    # identity / storage
    tenant_id: str = "default-lab"
    archive_bucket: str = ""
    archive_prefix: str = "raw"
    quarantine_prefix: str = "quarantine"
    aws_region: str = "us-west-2"
    kms_key_id: str = ""  # empty -> SSE-S3 (AES256); set -> SSE-KMS
    classification: str = "internal-confidential"
    local_archive_dir: str = ""  # dry-run / lab: write "S3" objects to a local folder instead

    # state
    state_backend: str = "sqlite"
    state_sqlite_path: str = ".state/opsi_ingest.sqlite3"
    state_database_url: str = ""

    # windows
    window_minutes: int = 5
    lag_seconds: int = 120
    initial_lookback_minutes: int = 30
    max_windows_per_run: int = 6
    final_rescan_after_minutes: int = 30
    min_split_seconds: int = 30
    part_max_rows: int = 5000
    message_max_chars: int = 4000
    payload_max_bytes: int = 65536
    redaction_level: str = "strict"

    # index stage
    index_max_attempts: int = 8
    database_url: str = ""
    curated_max_samples_per_signature: int = 3
    opensearch_url: str = ""
    opensearch_index: str = "opsi-incidents"
    opensearch_username: str = ""
    opensearch_password: str = field(default="", repr=False)
    opensearch_ca_certs: str = ""

    # elastic
    elastic_url: str = ""
    elastic_index_pattern: str = "logs-*"
    elastic_timestamp_field: str = "@timestamp"
    elastic_api_key: str = field(default="", repr=False)
    elastic_username: str = ""
    elastic_password: str = field(default="", repr=False)
    elastic_ca_certs: str = ""
    elastic_page_size: int = 1000
    elastic_max_docs_per_window: int = 200_000
    elastic_query_filter_json: str = ""
    elastic_source_includes: tuple[str, ...] = ()

    # dynatrace classic (Problems API v2)
    dynatrace_env_url: str = ""
    dynatrace_api_token: str = field(default="", repr=False)
    dynatrace_problems_page_size: int = 500
    dynatrace_problems_selector: str = ""
    dynatrace_problems_fields: str = ""

    # dynatrace platform (Grail)
    dynatrace_platform_url: str = ""
    dynatrace_auth_mode: str = "oauth"  # oauth | platform_token
    dynatrace_oauth_token_url: str = "https://sso.dynatrace.com/sso/oauth2/token"  # noqa: S105 - a URL, not a secret
    dynatrace_oauth_client_id: str = ""
    dynatrace_oauth_client_secret: str = field(default="", repr=False)
    dynatrace_oauth_scope: str = "storage:logs:read storage:buckets:read"
    dynatrace_oauth_resource: str = ""
    dynatrace_platform_token: str = field(default="", repr=False)
    dynatrace_grail_dql: str = 'fetch logs | filter in(loglevel, {"ERROR", "WARN", "SEVERE", "FATAL"})'
    dynatrace_grail_max_records: int = 50_000
    dynatrace_grail_poll_budget_seconds: int = 180
    dynatrace_grail_scan_limit_gbytes: int = 0  # 0 -> do not send (tenant default applies)

    # http
    http_timeout_seconds: int = 60
    http_max_retries: int = 5

    @property
    def window(self) -> timedelta:
        return timedelta(minutes=self.window_minutes)

    @property
    def lag(self) -> timedelta:
        return timedelta(seconds=self.lag_seconds)

    @property
    def initial_lookback(self) -> timedelta:
        return timedelta(minutes=self.initial_lookback_minutes)

    @property
    def final_rescan_after(self) -> timedelta:
        return timedelta(minutes=self.final_rescan_after_minutes)

    def __repr__(self) -> str:  # never print secrets, even by accident
        parts = []
        for f in fields(self):
            value = getattr(self, f.name)
            if any(hint in f.name for hint in _SECRET_FIELD_HINTS):
                value = "***" if value else ""
            parts.append(f"{f.name}={value!r}")
        return "Settings(" + ", ".join(parts) + ")"

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            env_names = ", ".join(n.upper() for n in missing)
            raise ConfigError(f"missing required settings: {env_names} (see .env.example)")


def from_env() -> Settings:
    """Build settings from the process environment (after optional ``.env`` load)."""
    load_dotenv_if_present()
    settings = Settings(
        tenant_id=_env("OPSI_TENANT_ID", "default-lab"),
        archive_bucket=_env("OPSI_ARCHIVE_BUCKET"),
        archive_prefix=_env("OPSI_ARCHIVE_PREFIX", "raw").strip("/"),
        quarantine_prefix=_env("OPSI_QUARANTINE_PREFIX", "quarantine").strip("/"),
        aws_region=_env("AWS_REGION", "us-west-2"),
        kms_key_id=_env("OPSI_KMS_KEY_ID"),
        classification=_env("INGEST_CLASSIFICATION", "internal-confidential"),
        local_archive_dir=_env("OPSI_LOCAL_ARCHIVE_DIR"),
        state_backend=_env("OPSI_STATE_BACKEND", "sqlite").lower(),
        state_sqlite_path=_env("WORKER_STATE_DB", ".state/opsi_ingest.sqlite3"),
        state_database_url=_env("OPSI_STATE_DATABASE_URL"),
        window_minutes=_int("INGEST_WINDOW_MINUTES", 5, minimum=1, maximum=60),
        lag_seconds=_int("INGEST_LAG_SECONDS", 120, minimum=0, maximum=3600),
        initial_lookback_minutes=_int("INGEST_INITIAL_LOOKBACK_MINUTES", 30, minimum=1),
        max_windows_per_run=_int("INGEST_MAX_WINDOWS_PER_RUN", 6, minimum=1, maximum=288),
        final_rescan_after_minutes=_int("INGEST_FINAL_RESCAN_AFTER_MINUTES", 30, minimum=0),
        min_split_seconds=_int("INGEST_MIN_SPLIT_SECONDS", 30, minimum=1),
        part_max_rows=_int("INGEST_PART_MAX_ROWS", 5000, minimum=1),
        message_max_chars=_int("INGEST_MESSAGE_MAX_CHARS", 4000, minimum=100),
        payload_max_bytes=_int("INGEST_PAYLOAD_MAX_BYTES", 65536, minimum=1024),
        redaction_level=_env("INGEST_REDACTION_LEVEL", "strict").lower(),
        index_max_attempts=_int("INDEX_MAX_ATTEMPTS", 8, minimum=1),
        database_url=_env("DATABASE_URL"),
        curated_max_samples_per_signature=_int("CURATED_MAX_SAMPLES_PER_SIGNATURE", 3, minimum=0, maximum=50),
        opensearch_url=_env("OPENSEARCH_URL"),
        opensearch_index=_env("OPENSEARCH_INDEX", "opsi-incidents"),
        opensearch_username=_env("OPENSEARCH_USERNAME"),
        opensearch_password=_env("OPENSEARCH_PASSWORD"),
        opensearch_ca_certs=_env("OPENSEARCH_CA_CERTS"),
        elastic_url=_env("ELASTIC_URL"),
        elastic_index_pattern=_env("ELASTIC_INDEX_PATTERN", "logs-*"),
        elastic_timestamp_field=_env("ELASTIC_TIMESTAMP_FIELD", "@timestamp"),
        elastic_api_key=_env("ELASTIC_API_KEY"),
        elastic_username=_env("ELASTIC_USERNAME"),
        elastic_password=_env("ELASTIC_PASSWORD"),
        elastic_ca_certs=_env("ELASTIC_CA_CERTS"),
        elastic_page_size=_int("ELASTIC_PAGE_SIZE", 1000, minimum=1, maximum=10_000),
        elastic_max_docs_per_window=_int("ELASTIC_MAX_DOCS_PER_WINDOW", 200_000, minimum=1),
        elastic_query_filter_json=_env("ELASTIC_QUERY_FILTER_JSON"),
        elastic_source_includes=_csv("ELASTIC_SOURCE_INCLUDES"),
        dynatrace_env_url=_env("DYNATRACE_ENV_URL").rstrip("/"),
        dynatrace_api_token=_env("DYNATRACE_API_TOKEN"),
        dynatrace_problems_page_size=_int("DYNATRACE_PROBLEMS_PAGE_SIZE", 500, minimum=1, maximum=500),
        dynatrace_problems_selector=_env("DYNATRACE_PROBLEMS_SELECTOR"),
        dynatrace_problems_fields=_env("DYNATRACE_PROBLEMS_FIELDS"),
        dynatrace_platform_url=_env("DYNATRACE_PLATFORM_URL").rstrip("/"),
        dynatrace_auth_mode=_env("DYNATRACE_AUTH_MODE", "oauth").lower(),
        dynatrace_oauth_token_url=_env("DYNATRACE_OAUTH_TOKEN_URL", "https://sso.dynatrace.com/sso/oauth2/token"),
        dynatrace_oauth_client_id=_env("DYNATRACE_OAUTH_CLIENT_ID"),
        dynatrace_oauth_client_secret=_env("DYNATRACE_OAUTH_CLIENT_SECRET"),
        dynatrace_oauth_scope=_env("DYNATRACE_OAUTH_SCOPE", "storage:logs:read storage:buckets:read"),
        dynatrace_oauth_resource=_env("DYNATRACE_OAUTH_RESOURCE"),
        dynatrace_platform_token=_env("DYNATRACE_PLATFORM_TOKEN"),
        dynatrace_grail_dql=_env(
            "DYNATRACE_GRAIL_DQL", 'fetch logs | filter in(loglevel, {"ERROR", "WARN", "SEVERE", "FATAL"})'
        ),
        dynatrace_grail_max_records=_int("DYNATRACE_GRAIL_MAX_RECORDS", 50_000, minimum=1),
        dynatrace_grail_poll_budget_seconds=_int("DYNATRACE_GRAIL_POLL_BUDGET_SECONDS", 180, minimum=5),
        dynatrace_grail_scan_limit_gbytes=_int("DYNATRACE_GRAIL_SCAN_LIMIT_GBYTES", 0, minimum=-1),
        http_timeout_seconds=_int("HTTP_TIMEOUT_SECONDS", 60, minimum=1),
        http_max_retries=_int("HTTP_MAX_RETRIES", 5, minimum=0, maximum=20),
    )
    validate(settings)
    return settings


def validate(settings: Settings) -> None:
    if settings.state_backend not in ("sqlite", "postgres"):
        raise ConfigError("OPSI_STATE_BACKEND must be sqlite or postgres")
    if settings.state_backend == "postgres" and not settings.state_database_url:
        raise ConfigError("OPSI_STATE_DATABASE_URL is required when OPSI_STATE_BACKEND=postgres")
    if settings.redaction_level not in ("strict", "standard"):
        raise ConfigError("INGEST_REDACTION_LEVEL must be strict or standard")
    if settings.dynatrace_auth_mode not in ("oauth", "platform_token"):
        raise ConfigError("DYNATRACE_AUTH_MODE must be oauth or platform_token")
    if settings.archive_bucket.startswith("replace-"):
        raise ConfigError("OPSI_ARCHIVE_BUCKET still holds the placeholder value")
    if (24 * 60) % settings.window_minutes != 0:
        raise ConfigError("INGEST_WINDOW_MINUTES must divide 1440 evenly (1,2,3,4,5,6,10,12,15,20,30,60)")
    for url_name in ("elastic_url", "opensearch_url", "dynatrace_env_url", "dynatrace_platform_url"):
        url = getattr(settings, url_name)
        if url and "@" in url.split("//", 1)[-1].split("/", 1)[0]:
            raise ConfigError(f"{url_name.upper()} must not embed credentials in the URL")
