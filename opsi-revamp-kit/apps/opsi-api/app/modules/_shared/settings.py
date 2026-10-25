"""Settings for the revamp modules, read from environment variables (see .env.example).

Kept separate from the existing Opsi settings object on purpose: the modules
can be grafted into the existing app without touching its configuration code.
Secrets (tokens, keys) are excluded from ``repr`` and never logged.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from pydantic import BaseModel, Field, field_validator


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")


def _json(name: str, default):
    raw = _env(name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON") from exc


class ApiSettings(BaseModel):
    env: str = "dev"  # dev | lab | staging | prod

    # --- identity
    auth_mode: str = "oidc"  # oidc | existing | dev
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: tuple[str, ...] = ("RS256", "ES256")
    oidc_leeway_seconds: int = 60
    oidc_user_claim: str = "sub"
    oidc_tenant_claim: str = ""  # empty -> single-tenant: default_tenant_id
    oidc_roles_claim: str = "groups"
    default_tenant_id: str = "default"
    group_role_map: dict[str, list[str]] = Field(default_factory=dict)  # IdP group -> Opsi roles
    role_service_scope: dict[str, list[str]] = Field(default_factory=dict)  # role -> service ids ("*" = all)
    dev_user: str = "dev-user"
    dev_roles: tuple[str, ...] = ("investigator",)

    # --- database
    database_url: str = Field(default="", repr=False)
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_statement_timeout_ms: int = 15_000
    db_set_role: str = ""  # e.g. opsi_app when the login user is broader than needed

    # --- attachments
    attachments_bucket: str = ""
    attachments_prefix: str = "chat-attachments"
    attachments_kms_key_id: str = ""
    attachments_max_bytes: int = 10 * 1024 * 1024
    attachments_allowed_mime: tuple[str, ...] = (
        "text/plain", "text/csv", "application/json", "application/pdf", "image/png", "image/jpeg",
    )
    attachments_upload_ttl_s: int = 300
    attachments_download_ttl_s: int = 60
    attachments_scan_mode: str = "guardduty"  # guardduty | none-lab
    aws_region: str = "us-west-2"

    # --- LLM (Portkey -> Bedrock)
    portkey_api_key: str = Field(default="", repr=False)
    portkey_base_url: str = ""  # self-hosted gateway URL; empty -> Portkey SaaS default
    portkey_provider: str = ""  # Model Catalog provider slug, e.g. "@bedrock-prod"
    portkey_config: str = ""  # alternative: a Portkey config id (cf-...)
    llm_model: str = ""  # Bedrock model / inference profile id as configured in Portkey
    llm_max_output_tokens: int = 2048
    llm_temperature: float = 0.1
    llm_request_timeout_s: int = 120
    llm_stream_usage: bool = True  # send stream_options.include_usage (disable if your gateway rejects it)
    embedding_model: str = ""

    # --- agent budgets
    agent_max_tool_calls: int = 8
    agent_max_cost_units: float = 50.0
    agent_max_seconds: int = 120
    agent_max_llm_turns: int = 6

    # --- retrieval backends
    elastic_url: str = ""
    elastic_api_key: str = Field(default="", repr=False)
    elastic_ca_certs: str = ""
    elastic_index_allowlist: tuple[str, ...] = ("logs-*",)
    elastic_tenant_index_map: dict[str, list[str]] = Field(default_factory=dict)
    elastic_timestamp_field: str = "@timestamp"
    elastic_service_field: str = "service.name"
    elastic_message_field: str = "message"
    elastic_source_fields: tuple[str, ...] = ("@timestamp", "message", "log.level", "service.name", "host.name", "trace.id")
    opensearch_url: str = ""
    opensearch_index: str = "opsi-incidents"
    opensearch_username: str = ""
    opensearch_password: str = Field(default="", repr=False)
    openmetadata_url: str = ""
    openmetadata_token: str = Field(default="", repr=False)  # bot JWT; read-only bot recommended
    openmetadata_ca_certs: str = ""

    # --- features
    vector_enabled: bool = False
    voice_enabled: bool = False
    copilot_agent_ids: tuple[str, ...] = ("opsi-investigator",)

    @field_validator("auth_mode")
    @classmethod
    def _auth_mode(cls, value: str) -> str:
        if value not in ("oidc", "existing", "dev"):
            raise ValueError("OPSI_AUTH_MODE must be oidc, existing or dev")
        return value

    def assert_safe_for_env(self) -> None:
        """Refuse insecure combinations outside dev. Call once at startup."""
        if self.env not in ("dev", "lab") and self.auth_mode == "dev":
            raise RuntimeError("OPSI_AUTH_MODE=dev is only allowed when OPSI_ENV is dev or lab")
        if self.env == "prod" and self.attachments_scan_mode != "guardduty":
            raise RuntimeError("attachment malware scanning must be enabled in prod")
        if self.auth_mode == "oidc" and not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
            raise RuntimeError("OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL are required for OPSI_AUTH_MODE=oidc")


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _env(name)
    return tuple(p.strip() for p in raw.split(",") if p.strip()) if raw else default


@lru_cache(maxsize=1)
def get_settings() -> ApiSettings:
    d = ApiSettings()
    return ApiSettings(
        env=_env("OPSI_ENV", d.env),
        auth_mode=_env("OPSI_AUTH_MODE", d.auth_mode),
        oidc_issuer=_env("OIDC_ISSUER"),
        oidc_audience=_env("OIDC_AUDIENCE"),
        oidc_jwks_url=_env("OIDC_JWKS_URL"),
        oidc_algorithms=_csv("OIDC_ALGORITHMS", d.oidc_algorithms),
        oidc_leeway_seconds=int(_env("OIDC_LEEWAY_SECONDS", "60")),
        oidc_user_claim=_env("OIDC_USER_CLAIM", d.oidc_user_claim),
        oidc_tenant_claim=_env("OIDC_TENANT_CLAIM"),
        oidc_roles_claim=_env("OIDC_ROLES_CLAIM", d.oidc_roles_claim),
        default_tenant_id=_env("OPSI_DEFAULT_TENANT_ID", d.default_tenant_id),
        group_role_map=_json("OPSI_GROUP_ROLE_MAP_JSON", {}),
        role_service_scope=_json("OPSI_ROLE_SERVICE_SCOPE_JSON", {}),
        dev_user=_env("OPSI_DEV_USER", d.dev_user),
        dev_roles=_csv("OPSI_DEV_ROLES", d.dev_roles),
        database_url=_env("OPSI_API_DATABASE_URL"),
        db_pool_min=int(_env("OPSI_DB_POOL_MIN", "1")),
        db_pool_max=int(_env("OPSI_DB_POOL_MAX", "10")),
        db_statement_timeout_ms=int(_env("OPSI_DB_STATEMENT_TIMEOUT_MS", "15000")),
        db_set_role=_env("OPSI_DB_SET_ROLE"),
        attachments_bucket=_env("OPSI_ATTACHMENTS_BUCKET"),
        attachments_prefix=_env("OPSI_ATTACHMENTS_PREFIX", d.attachments_prefix),
        attachments_kms_key_id=_env("OPSI_ATTACHMENTS_KMS_KEY_ID"),
        attachments_max_bytes=int(_env("OPSI_ATTACHMENTS_MAX_BYTES", str(d.attachments_max_bytes))),
        attachments_allowed_mime=_csv("OPSI_ATTACHMENTS_ALLOWED_MIME", d.attachments_allowed_mime),
        attachments_upload_ttl_s=int(_env("OPSI_ATTACHMENTS_UPLOAD_TTL_S", "300")),
        attachments_download_ttl_s=int(_env("OPSI_ATTACHMENTS_DOWNLOAD_TTL_S", "60")),
        attachments_scan_mode=_env("OPSI_ATTACHMENTS_SCAN_MODE", d.attachments_scan_mode),
        aws_region=_env("AWS_REGION", d.aws_region),
        portkey_api_key=_env("PORTKEY_API_KEY"),
        portkey_base_url=_env("PORTKEY_BASE_URL"),
        portkey_provider=_env("PORTKEY_PROVIDER"),
        portkey_config=_env("PORTKEY_CONFIG"),
        llm_model=_env("LLM_MODEL"),
        llm_max_output_tokens=int(_env("LLM_MAX_OUTPUT_TOKENS", "2048")),
        llm_temperature=float(_env("LLM_TEMPERATURE", "0.1")),
        llm_request_timeout_s=int(_env("LLM_REQUEST_TIMEOUT_S", "120")),
        llm_stream_usage=_bool("LLM_STREAM_USAGE", True),
        embedding_model=_env("EMBEDDING_MODEL"),
        agent_max_tool_calls=int(_env("AGENT_MAX_TOOL_CALLS", "8")),
        agent_max_cost_units=float(_env("AGENT_MAX_COST_UNITS", "50")),
        agent_max_seconds=int(_env("AGENT_MAX_SECONDS", "120")),
        agent_max_llm_turns=int(_env("AGENT_MAX_LLM_TURNS", "6")),
        elastic_url=_env("SEARCH_ELASTIC_URL"),
        elastic_api_key=_env("SEARCH_ELASTIC_API_KEY"),
        elastic_ca_certs=_env("SEARCH_ELASTIC_CA_CERTS"),
        elastic_index_allowlist=_csv("SEARCH_ELASTIC_INDEX_ALLOWLIST", d.elastic_index_allowlist),
        elastic_tenant_index_map=_json("SEARCH_ELASTIC_TENANT_INDEX_MAP_JSON", {}),
        elastic_timestamp_field=_env("SEARCH_ELASTIC_TIMESTAMP_FIELD", d.elastic_timestamp_field),
        elastic_service_field=_env("SEARCH_ELASTIC_SERVICE_FIELD", d.elastic_service_field),
        elastic_message_field=_env("SEARCH_ELASTIC_MESSAGE_FIELD", d.elastic_message_field),
        elastic_source_fields=_csv("SEARCH_ELASTIC_SOURCE_FIELDS", d.elastic_source_fields),
        opensearch_url=_env("SEARCH_OPENSEARCH_URL"),
        opensearch_index=_env("SEARCH_OPENSEARCH_INDEX", d.opensearch_index),
        opensearch_username=_env("SEARCH_OPENSEARCH_USERNAME"),
        opensearch_password=_env("SEARCH_OPENSEARCH_PASSWORD"),
        openmetadata_url=_env("OPENMETADATA_URL").rstrip("/"),
        openmetadata_token=_env("OPENMETADATA_BOT_TOKEN"),
        openmetadata_ca_certs=_env("OPENMETADATA_CA_CERTS"),
        vector_enabled=_bool("OPSI_VECTOR_ENABLED", False),
        voice_enabled=_bool("OPSI_VOICE_ENABLED", False),
        copilot_agent_ids=_csv("OPSI_COPILOT_AGENT_IDS", d.copilot_agent_ids),
    )
