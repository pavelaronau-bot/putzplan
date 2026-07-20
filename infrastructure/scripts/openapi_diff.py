"""Проверка обратной совместимости контракта OpenAPI.

Ловит не только удалённые пути и методы, но и изменения схем:
исчезнувшие коды ответов, свойства, значения enum, а также превращение
необязательного поля в обязательное и смену типа.

    python openapi_diff.py base.json head.json      # код 1 при breaking change
"""
import json
import sys
from typing import Any

BREAKING: list[str] = []


def report(kind: str, where: str, detail: str = "") -> None:
    BREAKING.append(f"{kind}: {where}" + (f" — {detail}" if detail else ""))


def resolve(schema: dict[str, Any], root: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Разворачивает $ref, чтобы сравнивать фактические структуры."""
    if depth > 10 or not isinstance(schema, dict):
        return schema if isinstance(schema, dict) else {}
    ref = schema.get("$ref")
    if not ref or not ref.startswith("#/"):
        return schema
    node: Any = root
    for part in ref[2:].split("/"):
        node = node.get(part, {}) if isinstance(node, dict) else {}
    return resolve(node, root, depth + 1)


def compare_schema(base: dict, head: dict, base_root: dict, head_root: dict, where: str) -> None:
    base = resolve(base, base_root)
    head = resolve(head, head_root)
    if not isinstance(base, dict) or not isinstance(head, dict):
        return

    base_type, head_type = base.get("type"), head.get("type")
    if base_type and head_type and base_type != head_type:
        report("изменён тип", where, f"{base_type} → {head_type}")

    base_enum, head_enum = base.get("enum"), head.get("enum")
    if base_enum and head_enum:
        removed = [v for v in base_enum if v not in head_enum]
        if removed:
            report("удалены значения enum", where, ", ".join(map(str, removed)))

    base_props = base.get("properties") or {}
    head_props = head.get("properties") or {}
    for name in base_props:
        if name not in head_props:
            report("удалено свойство", f"{where}.{name}")
        else:
            compare_schema(base_props[name], head_props[name], base_root, head_root,
                           f"{where}.{name}")

    new_required = set(head.get("required") or []) - set(base.get("required") or [])
    # Обязательным можно делать только то, чего раньше не было
    tightened = [f for f in new_required if f in base_props]
    if tightened:
        report("поле стало обязательным", where, ", ".join(sorted(tightened)))


def compare(base: dict, head: dict) -> None:
    for path, methods in (base.get("paths") or {}).items():
        head_methods = (head.get("paths") or {}).get(path)
        if head_methods is None:
            report("удалён путь", path)
            continue
        for method, operation in methods.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            head_operation = head_methods.get(method)
            if head_operation is None:
                report("удалён метод", f"{method.upper()} {path}")
                continue

            for code in (operation.get("responses") or {}):
                if code not in (head_operation.get("responses") or {}):
                    report("удалён код ответа", f"{method.upper()} {path}", code)

            for code, response in (operation.get("responses") or {}).items():
                head_response = (head_operation.get("responses") or {}).get(code)
                if not head_response:
                    continue
                base_schema = ((response.get("content") or {}).get("application/json") or {}).get("schema")
                head_schema = ((head_response.get("content") or {}).get("application/json") or {}).get("schema")
                if base_schema and head_schema:
                    compare_schema(base_schema, head_schema, base, head,
                                   f"{method.upper()} {path} → {code}")

            base_body = (((operation.get("requestBody") or {}).get("content") or {})
                         .get("application/json") or {}).get("schema")
            head_body = (((head_operation.get("requestBody") or {}).get("content") or {})
                         .get("application/json") or {}).get("schema")
            if base_body and head_body:
                compare_schema(base_body, head_body, base, head,
                               f"{method.upper()} {path} ← запрос")

            base_params = {(p.get("name"), p.get("in")) for p in (operation.get("parameters") or [])}
            head_required = {(p.get("name"), p.get("in")) for p in (head_operation.get("parameters") or [])
                             if p.get("required")}
            base_required = {(p.get("name"), p.get("in")) for p in (operation.get("parameters") or [])
                             if p.get("required")}
            for param in head_required - base_required:
                if param in base_params:
                    report("параметр стал обязательным", f"{method.upper()} {path}", str(param))


def main() -> int:
    if len(sys.argv) != 3:
        print("использование: openapi_diff.py base.json head.json", file=sys.stderr)
        return 2
    base = json.load(open(sys.argv[1], encoding="utf-8"))
    head = json.load(open(sys.argv[2], encoding="utf-8"))
    compare(base, head)
    if BREAKING:
        print("Обнаружены несовместимые изменения контракта:")
        for item in BREAKING:
            print("  •", item)
        return 1
    print("Несовместимых изменений нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
