"""Выгрузка детерминированного контракта OpenAPI 3.1."""

import json
from pathlib import Path
from typing import Any

import yaml

from app.main import app


def normalize_schema(schema: dict[str, Any]) -> None:
    """Убирает различия OpenAPI между версиями Python."""

    # Название HTTP 422 отличается между Python 3.12 и Python 3.14.
    # Фиксируем одно значение, чтобы локальная генерация совпадала с CI.
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue

        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue

            responses = operation.get("responses")
            if not isinstance(responses, dict):
                continue

            response_422 = responses.get("422")
            if isinstance(response_422, dict):
                response_422["description"] = "Unprocessable Entity"


schema = app.openapi()
schema["openapi"] = "3.1.0"
normalize_schema(schema)

out_dir = Path(__file__).resolve().parents[2] / "openapi"
out_dir.mkdir(exist_ok=True)

(out_dir / "openapi.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

(out_dir / "openapi.yaml").write_text(
    yaml.safe_dump(schema, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)

paths = len(schema["paths"])
print(
    f"OpenAPI {schema['openapi']}: "
    f"{paths} путей → openapi/openapi.yaml, openapi/openapi.json"
)
