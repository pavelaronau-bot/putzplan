"""Общие схемы ответа."""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    field: str | None = Field(default=None, examples=["email"])
    message: str = Field(examples=["Некорректный формат"])


class ErrorResponse(BaseModel):
    """Единая схема ошибки во всех эндпоинтах."""
    code: str = Field(examples=["forbidden"])
    message: str = Field(examples=["Недостаточно прав"])
    request_id: str = Field(examples=["req_8f21ac"])
    details: list[ErrorDetail] = Field(default_factory=list)


class Page(BaseModel, Generic[T]):
    data: list[T]
    total: int = Field(examples=[42])
    limit: int = Field(examples=[50])
    offset: int = Field(examples=[0])
    next_offset: int | None = Field(default=None, examples=[50])


class OkResponse(BaseModel):
    status: str = Field(examples=["ok"])
    details: dict[str, Any] = Field(default_factory=dict)
