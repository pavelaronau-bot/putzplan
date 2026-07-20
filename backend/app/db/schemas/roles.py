from uuid import UUID

from pydantic import BaseModel, Field


class RoleOut(BaseModel):
    id: UUID
    key: str = Field(examples=["dispatcher"])
    name: str = Field(examples=["Dispatcher"])
    description: str | None
    is_system: bool
    permissions_count: int


class RoleDetail(RoleOut):
    permissions: list[str]


class RoleCreate(BaseModel):
    key: str = Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_]*$",
                     examples=["objektleiter"])
    name: str = Field(min_length=2, max_length=80, examples=["Objektleiter"])
    description: str | None = Field(default=None, max_length=300)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=300)


class RolePermissionsUpdate(BaseModel):
    permissions: list[str] = Field(examples=[["planning.view", "planning.edit"]])


class PermissionCatalogItem(BaseModel):
    key: str
    module: str
    action: str
    default_scope: str
    description: str | None
