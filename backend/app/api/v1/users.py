from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import require
from app.db.schemas.common import ErrorResponse, OkResponse, Page
from app.db.schemas.users import DeactivateRequest, SessionOut, UserCreate, UserOut, UserUpdate
from app.domain.models import Actor
from app.services import user_service

router = APIRouter(tags=["users"])
ERRORS: dict[int | str, dict[str, Any]] = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
          404: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
          422: {"model": ErrorResponse}}


@router.get("/users", response_model=Page[UserOut], responses=ERRORS,
            summary="Список пользователей компании")
async def list_users(
    request: Request,
    actor: Annotated[Actor, Depends(require("users.read"))],
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    role: str | None = None, search: str | None = Query(None, max_length=100),
    sort: str = Query("created_at"), order: str = Query("desc", pattern="^(asc|desc)$"),
) -> Page[UserOut]:
    rows, total = await user_service.list_users(actor, limit=limit, offset=offset,
                                                status=status_filter, role=role, search=search,
                                                sort=sort, order=order)
    next_offset = offset + limit if offset + limit < total else None
    return Page[UserOut](data=[UserOut(**r) for r in rows], total=total, limit=limit,
                         offset=offset, next_offset=next_offset)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             responses=ERRORS, summary="Создание пользователя")
async def create_user(payload: UserCreate, request: Request,
                      actor: Annotated[Actor, Depends(require("users.create"))]) -> UserOut:
    created = await user_service.create_user(
        actor, payload, request_id=request.state.request_id,
        ip=request.client.host if request.client else None)
    return UserOut(**created)


@router.get("/users/{user_id}", response_model=UserOut, responses=ERRORS,
            summary="Карточка пользователя")
async def get_user(user_id: UUID,
                   actor: Annotated[Actor, Depends(require("users.read"))]) -> UserOut:
    return UserOut(**await user_service.get_user(actor, user_id))


@router.patch("/users/{user_id}", response_model=UserOut, responses=ERRORS,
              summary="Редактирование пользователя")
async def update_user(user_id: UUID, payload: UserUpdate, request: Request,
                      actor: Annotated[Actor, Depends(require("users.update"))]) -> UserOut:
    updated = await user_service.update_user(
        actor, user_id, payload, request_id=request.state.request_id,
        ip=request.client.host if request.client else None)
    return UserOut(**updated)


@router.post("/users/{user_id}/deactivate", response_model=OkResponse, responses=ERRORS,
             summary="Деактивация пользователя")
async def deactivate_user(user_id: UUID, payload: DeactivateRequest, request: Request,
                          actor: Annotated[Actor, Depends(require("users.deactivate"))]) -> OkResponse:
    result = await user_service.deactivate_user(
        actor, user_id, payload.reason, request_id=request.state.request_id,
        ip=request.client.host if request.client else None)
    return OkResponse(status="deactivated", details=result)


@router.get("/users/{user_id}/sessions", response_model=list[SessionOut], responses=ERRORS,
            summary="Активные сессии пользователя")
async def list_sessions(user_id: UUID,
                        actor: Annotated[Actor, Depends(require("security.sessions.read"))]
                        ) -> list[SessionOut]:
    return [SessionOut(**s) for s in await user_service.list_sessions(actor, user_id)]


@router.delete("/users/{user_id}/sessions/{session_id}", response_model=OkResponse,
               responses=ERRORS, summary="Отзыв сессии пользователя")
async def revoke_session(user_id: UUID, session_id: UUID, request: Request,
                         actor: Annotated[Actor, Depends(require("security.sessions.revoke"))]
                         ) -> OkResponse:
    await user_service.revoke_session(actor, user_id, session_id,
                                      request_id=request.state.request_id,
                                      ip=request.client.host if request.client else None)
    return OkResponse(status="session_revoked")
