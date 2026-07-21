"""Сценарии работы с проектами: CRUD, статусы, контакты, документы, финансы."""
from datetime import date
from uuid import UUID

from app.core.errors import Conflict, Forbidden, NotFound, UnprocessableEntity
from app.db.session import tenant_session
from app.domain.models import Actor
from app.observability import metrics
from app.repositories.project_repo import ProjectRepository
from app.services import audit_service

# Переходы статусов: из архива и завершения возврат только через владельца
ALLOWED_TRANSITIONS = {
    "planned": {"active", "on_hold", "archived"},
    "active": {"on_hold", "completed", "archived"},
    "on_hold": {"active", "completed", "archived"},
    "completed": {"archived", "active"},
    "archived": {"planned"},
}


async def list_projects(actor: Actor, **filters):
    async with tenant_session(actor.company_id) as session:
        return await ProjectRepository(session).list_projects(**filters)


async def list_statuses(actor: Actor) -> list[dict]:
    async with tenant_session(actor.company_id) as session:
        return await ProjectRepository(session).list_statuses()


async def get_project(actor: Actor, project_id: UUID, *, with_finance: bool) -> dict:
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        project = await repo.get_project(project_id)
        if not project:
            raise NotFound("Проект не найден")
        if with_finance:
            project["finance"] = await repo.finance(project_id)
    return project


async def create_project(actor: Actor, payload, *, request_id: str, ip: str | None) -> dict:
    data = payload.model_dump()
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        if await repo.number_exists(actor.company_id, data["number"]):
            raise Conflict("Проект с таким номером уже существует", code="project_number_exists")
        try:
            project = await repo.create_project(company_id=actor.company_id, payload=data,
                                                created_by=actor.user_id)
        except Exception as exc:  # noqa: BLE001
            if "23503" in str(exc):
                raise UnprocessableEntity("Заказчик или руководитель не найден в вашей компании",
                                          code="reference_not_found") from exc
            raise
        await repo.change_status(project["id"], "planned", "создание проекта",
                                 actor.user_id, actor.company_id)
    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="PROJECT_CREATED", entity="project",
                               entity_id=project["id"],
                               after={"number": data["number"], "name": data["name"]},
                               ip=ip, http_status=201, request_id=request_id)
    metrics.inc("projects.created")
    return project


async def update_project(actor: Actor, project_id: UUID, payload, *, request_id: str,
                         ip: str | None) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    finance_fields = {"budget", "planned_labor_cost", "planned_material_cost",
                      "actual_labor_cost", "actual_material_cost"}
    if finance_fields.intersection(fields) and not actor.can("projects.finance.read"):
        raise Forbidden("Изменение финансовых полей требует права projects.finance.read",
                        code="forbidden")

    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        before = await repo.get_project(project_id)
        if not before:
            raise NotFound("Проект не найден")
        updated = await repo.update_project(project_id, fields, actor.user_id)
        if not updated:
            raise NotFound("Проект не найден")

    changed = {k: str(fields[k]) for k in fields if str(before.get(k)) != str(fields[k])}
    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="PROJECT_UPDATED", entity="project",
                               entity_id=project_id, after=changed or None, ip=ip,
                               http_status=200, request_id=request_id)
    metrics.inc("projects.updated")
    return updated


async def change_status(actor: Actor, project_id: UUID, payload, *, request_id: str,
                        ip: str | None) -> dict:
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        project = await repo.get_project(project_id)
        if not project:
            raise NotFound("Проект не найден")
        if not await repo.status_exists(payload.status):
            raise UnprocessableEntity("Неизвестный статус", code="unknown_status",
                                      details=[{"field": "status", "message": payload.status}])
        current = project["status"]
        if payload.status == current:
            raise Conflict("Проект уже находится в этом статусе", code="status_unchanged")
        if payload.status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise UnprocessableEntity(
                f"Переход {current} → {payload.status} не разрешён", code="invalid_transition",
                details=[{"field": "status",
                          "message": "допустимо: " + ", ".join(sorted(ALLOWED_TRANSITIONS.get(current, [])))}])
        if payload.status in ("completed", "archived"):
            active = await repo.active_assignments_count(project_id)
            if active:
                raise Conflict(f"На проекте остаются активные назначения: {active}",
                               code="active_assignments")
        result = await repo.change_status(project_id, payload.status, payload.reason,
                                          actor.user_id, actor.company_id)

    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="PROJECT_STATUS_CHANGED",
                               entity="project", entity_id=project_id,
                               before={"status": result["from_status"]},
                               after={"status": result["to_status"]}, reason=payload.reason,
                               ip=ip, http_status=200, request_id=request_id)
    metrics.inc("projects.status_changed")
    return {"status": result["to_status"], "previous": result["from_status"]}


async def delete_project(actor: Actor, project_id: UUID, reason: str, *, request_id: str,
                         ip: str | None) -> None:
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        project = await repo.get_project(project_id)
        if not project:
            raise NotFound("Проект не найден")
        active = await repo.active_assignments_count(project_id)
        if active:
            raise Conflict(f"Нельзя удалить проект с активными назначениями: {active}",
                           code="active_assignments")
        await repo.soft_delete(project_id, actor.user_id)

    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="PROJECT_DELETED", entity="project",
                               entity_id=project_id, before={"number": project["number"]},
                               reason=reason, ip=ip, http_status=200, request_id=request_id)
    metrics.inc("projects.deleted")


async def status_history(actor: Actor, project_id: UUID) -> list[dict]:
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        if not await repo.get_project(project_id):
            raise NotFound("Проект не найден")
        return await repo.status_history(project_id)


async def add_contact(actor: Actor, project_id: UUID, payload, *, request_id: str,
                      ip: str | None) -> dict:
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        if not await repo.get_project(project_id):
            raise NotFound("Проект не найден")
        contact = await repo.add_contact(actor.company_id, project_id, payload.model_dump())
    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="PROJECT_CONTACT_ADDED",
                               entity="project", entity_id=project_id,
                               after={"name": payload.name}, ip=ip, http_status=201,
                               request_id=request_id)
    return contact


async def list_contacts(actor: Actor, project_id: UUID) -> list[dict]:
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        if not await repo.get_project(project_id):
            raise NotFound("Проект не найден")
        return await repo.list_contacts(project_id)


async def add_document(actor: Actor, project_id: UUID, payload, *, request_id: str,
                       ip: str | None) -> dict:
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        if not await repo.get_project(project_id):
            raise NotFound("Проект не найден")
        try:
            document = await repo.add_document(actor.company_id, project_id,
                                               payload.model_dump(), actor.user_id)
        except Exception as exc:  # noqa: BLE001
            if "23505" in str(exc):
                raise Conflict("Документ с таким ключом уже загружен", code="document_exists") from exc
            raise
    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="PROJECT_DOCUMENT_UPLOADED",
                               entity="project", entity_id=project_id,
                               after={"kind": payload.kind, "title": payload.title},
                               ip=ip, http_status=201, request_id=request_id)
    metrics.inc("projects.documents_uploaded")
    return document


async def list_documents(actor: Actor, project_id: UUID) -> list[dict]:
    async with tenant_session(actor.company_id) as session:
        repo = ProjectRepository(session)
        if not await repo.get_project(project_id):
            raise NotFound("Проект не найден")
        return await repo.list_documents(project_id)
