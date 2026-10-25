"""JSON-lines logging to stdout (journald/CloudWatch friendly) with a redaction filter.

Every record passes through ``scrub_for_log`` so an exception message that
happens to include a URL with credentials or a token is masked before output.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from .redaction import scrub_for_log


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": scrub_for_log(record.getMessage()),
        }
        audit = getattr(record, "audit", None)
        if isinstance(audit, dict):
            payload.update({k: v for k, v in audit.items()})
        if record.exc_info:
            payload["exception"] = scrub_for_log(self.formatException(record.exc_info))[-4000:]
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # third-party clients can log request URLs/headers at DEBUG; keep them quiet
    for noisy in ("urllib3", "botocore", "boto3", "s3transfer", "elastic_transport", "elasticsearch"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
