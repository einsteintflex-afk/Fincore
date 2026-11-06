"""Structured JSON logging (one JSON object per line, ready for Loki/ELK/CloudWatch)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.context import request_id_var

_STD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_REDACT = {"password", "secret", "token", "authorization", "api_key", "pin", "otp", "code"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_"):
                data[k] = "***" if any(r in k.lower() for r in _REDACT) else v
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel("WARNING")
