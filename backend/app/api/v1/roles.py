from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import require
from app.db.schemas.common import ErrorResponse
from app.db.schemas.roles import (
    PermissionCatalogItem,
    RoleCreate,
    RoleDetail,
    RoleOut,
    RolePermissionsUpdate,
    RoleUpdate,
)
from app.domain.models import Actor
from app.services import role_service

router = APIRouter(tags=["roles"])
ERRORS: dict[int | str, dict[str, Any]] = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
          404: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
          422: {"model": ErrorResponse}}


@router.get("/roles", response_model=list[RoleOut], responses=ERRORS, summary="Список ролей")
async def list_roles(actor: Annotated[Actor, Depends(require("roles.read"))]) -> list[RoleOut]:
    return [RoleOut(**r) for r in await role_service.list_roles(actor)]


@router.post("/roles", response_model=RoleDetail, status_code=status.HTTP_201_CREATED,
             responses=ERRORS, summary="Создание пользовательской роли")
async def create_role(payload: RoleCreate, request: Request,
                      actor: Annotated[Actor, Depends(require("roles.create"))]) -> RoleDetail:
    role = await role_service.create_role(actor, payload, request_id=request.state.request_id,
                                          ip=request.client.host if request.client else None)
    return RoleDetail(**role)


@router.get("/roles/{role_id}", response_model=RoleDetail, responses=ERRORS, summary="Роль и её права")
async def get_role(role_id: UUID,
                   actor: Annotated[Actor, Depends(require("roles.read"))]) -> RoleDetail:
    return RoleDetail(**await role_service.get_role(actor, role_id))


@router.patch("/roles/{role_id}", response_model=RoleOut, responses=ERRORS,
              summary="Редактирование роли")
async def update_role(role_id: UUID, payload: RoleUpdate, request: Request,
                      actor: Annotated[Actor, Depends(require("roles.update"))]) -> RoleOut:
    role = await role_service.update_role(actor, role_id, payload,
                                          request_id=request.state.request_id,
                                          ip=request.client.host if request.client else None)
    return RoleOut(**role)


@router.put("/roles/{role_id}/permissions", response_model=RoleDetail, responses=ERRORS,
            summary="Назначение прав роли")
async def set_permissions(role_id: UUID, payload: RolePermissionsUpdate, request: Request,
                          actor: Annotated[Actor, Depends(require("roles.permissions.manage"))]
                          ) -> RoleDetail:
    role = await role_service.set_permissions(actor, role_id, payload.permissions,
                                              request_id=request.state.request_id,
                                              ip=request.client.host if request.client else None)
    return RoleDetail(**role)


@router.get("/permissions", response_model=list[PermissionCatalogItem], responses=ERRORS,
            summary="Каталог прав")
async def list_permissions(actor: Annotated[Actor, Depends(require("roles.read"))]
                           ) -> list[PermissionCatalogItem]:
    return [PermissionCatalogItem(**p) for p in await role_service.list_permissions(actor)]
