"""Проверка гейта совместимости контракта на подготовленных фикстурах."""
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
DIFF = Path(__file__).resolve().parents[2] / "infrastructure" / "scripts" / "openapi_diff.py"
BASE = FIXTURES / "openapi_base.json"


def run_diff(head_name: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(DIFF), str(BASE), str(FIXTURES / head_name)],
                          capture_output=True, text=True, check=False)


@pytest.mark.parametrize("fixture,expected_text", [
    ("openapi_removed_path.json", "удалён путь"),
    ("openapi_removed_method.json", "удалён метод"),
    ("openapi_removed_response_code.json", "удалён код ответа"),
    ("openapi_removed_property.json", "удалено свойство"),
    ("openapi_removed_enum.json", "удалены значения enum"),
    ("openapi_field_became_required.json", "поле стало обязательным"),
    ("openapi_changed_type.json", "изменён тип"),
])
def test_breaking_changes_are_detected(fixture, expected_text):
    result = run_diff(fixture)
    assert result.returncode == 1, f"гейт пропустил несовместимое изменение: {fixture}"
    assert expected_text in result.stdout, result.stdout


@pytest.mark.parametrize("fixture", ["openapi_added_path_ok.json", "openapi_added_property_ok.json"])
def test_compatible_changes_pass(fixture):
    result = run_diff(fixture)
    assert result.returncode == 0, f"гейт ложно сработал: {result.stdout}"


def test_identical_contract_passes():
    result = subprocess.run([sys.executable, str(DIFF), str(BASE), str(BASE)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
