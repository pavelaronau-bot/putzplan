from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import CurrentActor, require
from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.db.schemas.auth import LoginRequest, MeResponse, PermissionOut, RefreshRequest, TokenResponse
from app.db.schemas.common import ErrorResponse, OkResponse
from app.domain.models import Actor
from app.security.csrf import new_csrf_token, verify_csrf
from app.services import auth_service

settings = get_settings()
router = APIRouter(tags=["auth"])

ERRORS: dict[int | str, dict[str, Any]] = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
          422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}}


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Refresh — в HttpOnly-cookie; рядом кладём читаемый CSRF-токен
    для схемы double-submit (его обязан вернуть клиент заголовком)."""
    secure = settings.secure_cookies
    response.set_cookie(
        key=settings.refresh_cookie_name, value=token, httponly=True,
        secure=secure, samesite="strict",
        max_age=settings.refresh_ttl_days * 86400, path="/api/v1/auth")
    csrf = new_csrf_token()
    response.set_cookie(
        key=settings.csrf_cookie_name, value=csrf, httponly=False,
        secure=secure, samesite="strict",
        max_age=settings.refresh_ttl_days * 86400, path="/")
    response.headers["x-csrf-token"] = csrf


@router.post("/auth/login", response_model=TokenResponse, responses=ERRORS,
             summary="Вход по e-mail и паролю")
async def login(payload: LoginRequest, request: Request, response: Response) -> TokenResponse:
    result = await auth_service.login(
        email=payload.email, password=payload.password,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"), request_id=request.state.request_id)
    if settings.use_refresh_cookie:
        _set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(access_token=result.access_token, expires_in=result.expires_in,
                         refresh_token=None if settings.use_refresh_cookie else result.refresh_token)


@router.post("/auth/refresh", response_model=TokenResponse, responses=ERRORS,
             summary="Ротация refresh-токена")
async def refresh(payload: RefreshRequest, request: Request, response: Response) -> TokenResponse:
    verify_csrf(request)
    raw = payload.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    if not raw:
        raise Unauthorized("Refresh-токен не передан", code="no_refresh")
    result = await auth_service.refresh(
        raw_token=raw, ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"), request_id=request.state.request_id)
    if settings.use_refresh_cookie:
        _set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(access_token=result.access_token, expires_in=result.expires_in,
                         refresh_token=None if settings.use_refresh_cookie else result.refresh_token)


@router.post("/auth/logout", response_model=OkResponse, summary="Выход из текущей сессии")
async def logout(payload: RefreshRequest, request: Request, response: Response) -> OkResponse:
    verify_csrf(request)
    raw = payload.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    actor = getattr(request.state, "actor", None)
    await auth_service.logout(raw_token=raw, actor=actor,
                              ip=request.client.host if request.client else None,
                              request_id=request.state.request_id)
    response.delete_cookie(settings.refresh_cookie_name, path="/api/v1/auth")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return OkResponse(status="logged_out")


@router.post("/auth/logout-all", response_model=OkResponse, responses=ERRORS,
             summary="Отозвать все сессии пользователя")
async def logout_all(request: Request, response: Response,
                     actor: Annotated[Actor, Depends(require("profile.security"))]) -> OkResponse:
    verify_csrf(request)
    revoked = await auth_service.logout_all(actor=actor,
                                            ip=request.client.host if request.client else None,
                                            request_id=request.state.request_id)
    response.delete_cookie(settings.refresh_cookie_name, path="/api/v1/auth")
    return OkResponse(status="all_sessions_revoked", details={"revoked": revoked})


@router.get("/me", response_model=MeResponse, responses=ERRORS,
            summary="Текущий пользователь и его права")
async def me(actor: CurrentActor) -> MeResponse:
    from app.db.session import tenant_session
    from app.repositories.user_repo import UserRepository
    async with tenant_session(actor.company_id) as session:
        user = await UserRepository(session).get_user(actor.user_id)
    if user is None:
        raise Unauthorized("Пользователь не найден", code="user_missing")
    return MeResponse(
        id=actor.user_id, company_id=actor.company_id, email=user["email"],
        full_name=user["full_name"], position=user["position"], status=user["status"],
        role=actor.role, last_login_at=user["last_login_at"],
        permissions=[PermissionOut(key=k, scope="company") for k in sorted(actor.permissions)])
