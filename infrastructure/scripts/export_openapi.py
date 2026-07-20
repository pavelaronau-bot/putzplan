"""Выгрузка контракта OpenAPI 3.1 из работающего приложения."""
import json
from pathlib import Path

import yaml

from app.main import app

schema = app.openapi()
schema["openapi"] = "3.1.0"
out_dir = Path(__file__).resolve().parents[2] / "openapi"
out_dir.mkdir(exist_ok=True)
(out_dir / "openapi.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
(out_dir / "openapi.yaml").write_text(
    yaml.safe_dump(schema, allow_unicode=True, sort_keys=False), encoding="utf-8")
paths = len(schema["paths"])
print(f"OpenAPI {schema['openapi']}: {paths} путей → openapi/openapi.yaml, openapi/openapi.json")
