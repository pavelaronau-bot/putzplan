"""Структурные JSON-логи с request_id. Секреты и персональные данные не пишутся."""
import json
import logging
import sys
from datetime import UTC, datetime

SENSITIVE = {"password", "old_password", "new_password", "refresh_token", "access_token",
             "token", "secret", "password_hash", "pin", "authorization", "cookie"}


def redact(payload: dict) -> dict:
    """Удаляет секреты из полезной нагрузки перед записью в лог или журнал."""
    clean: dict = {}
    for key, value in (payload or {}).items():
        if key.lower() in SENSITIVE:
            continue
        clean[key] = redact(value) if isinstance(value, dict) else value
    return clean


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in ("request_id", "method", "path", "status", "duration_ms",
                      "company_id", "user_id", "event"):
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).handlers = [handler]
        logging.getLogger(noisy).propagate = False
