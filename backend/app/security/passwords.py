"""Argon2id. Параметры по рекомендации OWASP: 19 МиБ, 2 итерации, параллелизм 1."""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

MIN_LENGTH = 12


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(stored: str | None, plain: str) -> bool:
    if not stored:
        return False
    try:
        return _hasher.verify(stored, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError, UnicodeEncodeError, ValueError):
        # Повреждённый или чужеродный хеш не должен ронять вход — это отказ, а не ошибка
        return False


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


def validate_policy(password: str) -> list[str]:
    """Возвращает список нарушений политики; пустой список — пароль подходит."""
    problems: list[str] = []
    if len(password or "") < MIN_LENGTH:
        problems.append(f"минимум {MIN_LENGTH} символов")
    if not any(c.isdigit() for c in password or ""):
        problems.append("нужна хотя бы одна цифра")
    if not any(c.isalpha() for c in password or ""):
        problems.append("нужна хотя бы одна буква")
    return problems
