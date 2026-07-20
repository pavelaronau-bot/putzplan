"""Единая схема ошибки: code, message, request_id, details."""
from typing import Any

from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str,
                 details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.details = details or []


class Unauthorized(AppError):
    def __init__(self, message: str = "Требуется аутентификация", code: str = "unauthenticated") -> None:
        super().__init__(401, code, message)


class Forbidden(AppError):
    def __init__(self, message: str = "Недостаточно прав", code: str = "forbidden",
                 details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(403, code, message, details)


class NotFound(AppError):
    def __init__(self, message: str = "Не найдено") -> None:
        super().__init__(404, "not_found", message)


class Conflict(AppError):
    def __init__(self, message: str, code: str = "conflict") -> None:
        super().__init__(409, code, message)


class UnprocessableEntity(AppError):
    def __init__(self, message: str, code: str = "unprocessable",
                 details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(422, code, message, details)


class TooManyRequests(AppError):
    def __init__(self, message: str = "Слишком много запросов", retry_after: int = 900) -> None:
        super().__init__(429, "rate_limited", message)
        self.retry_after = retry_after


class Locked(AppError):
    def __init__(self, message: str = "Учётная запись временно заблокирована") -> None:
        super().__init__(423, "account_locked", message)
