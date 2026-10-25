"""pytest fixtures for ingestion tests (helpers live in fakes.py)."""
from __future__ import annotations

import pytest
from opsi_ingest.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        tenant_id="tenant-a", archive_bucket="unit-test-bucket", local_archive_dir=str(tmp_path / "archive"),
        state_sqlite_path=str(tmp_path / "state.sqlite3"), window_minutes=5, lag_seconds=120,
        initial_lookback_minutes=15, max_windows_per_run=6, final_rescan_after_minutes=30, min_split_seconds=30,
        part_max_rows=2, http_max_retries=3,
        dynatrace_env_url="https://synthetic.live.dynatrace.example", dynatrace_api_token="dt0c01.SYNTHETICSYNTHETIC",
        dynatrace_platform_url="https://synthetic.apps.dynatrace.example", dynatrace_oauth_client_id="client",
        dynatrace_oauth_client_secret="secret", dynatrace_grail_max_records=5,
    )
