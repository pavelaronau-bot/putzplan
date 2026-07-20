"""Конфигурация из переменных окружения. Секретов в коде нет."""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "PUTZPLAN API"
    app_version: str = "0.1.0"
    port: int = 8000

    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "putzplan_dev"
    db_runtime_user: str = "putzplan_runtime"
    db_runtime_password: str = "test_runtime"  # noqa: S105 — значение для локальной разработки, в production из окружения
    db_audit_user: str = "putzplan_audit"
    db_audit_password: str = "test_audit"  # noqa: S105 — то же самое: заменяется переменной окружения
    db_pool_size: int = 10
    db_pool_max_overflow: int = 5

    jwt_secret: str = Field(default="dev-only-change-me", min_length=8)
    jwt_algorithm: Literal["HS256", "HS384", "HS512", "RS256", "ES256"] = "HS256"
    access_ttl_seconds: int = 900
    refresh_ttl_days: int = 30

    max_failed_attempts: int = 5
    lock_minutes: int = 15
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 900

    cors_origins: str = "http://localhost:5173"
    trusted_hosts: str = "localhost,127.0.0.1,api,testserver"
    refresh_cookie_name: str = "putzplan_refresh"
    csrf_cookie_name: str = "putzplan_csrf"
    use_refresh_cookie: bool = True
    # Secure-cookie обязательна вне разработки: по http браузер её не отправит.
    # Отдельная настройка, а не вывод из app_env, чтобы staging мог работать
    # за TLS-терминатором, а тесты — по http без ослабления production.
    cookie_secure: bool | None = None
    request_id_max_length: int = 64

    redis_url: str = "redis://127.0.0.1:6379/0"
    rate_limit_backend: Literal["memory", "redis"] = "memory"

    @property
    def runtime_dsn(self) -> str:
        return (f"postgresql+asyncpg://{self.db_runtime_user}:{self.db_runtime_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}")

    @property
    def audit_dsn(self) -> str:
        return (f"postgresql+asyncpg://{self.db_audit_user}:{self.db_audit_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}")

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env not in ("development", "test")


def _secret_entropy_bits(secret: str) -> float:
    """Оценка энтропии по Шеннону на символ, умноженная на длину.

    Считается по фактическому распределению символов, поэтому строка вида
    'aaaa…' получает почти нулевую оценку и не проходит проверку, тогда как
    случайные 32 hex-символа дают около 128 бит.
    """
    import math
    from collections import Counter
    if not secret:
        return 0.0
    counts = Counter(secret)
    length = len(secret)
    per_symbol = -sum((n / length) * math.log2(n / length) for n in counts.values())
    return per_symbol * length


MIN_SECRET_LENGTH = 32          # 32 символа ≈ 256 бит при base64/hex
MIN_SECRET_ENTROPY_BITS = 110   # 32 hex-символа дают ~125 бит по Шеннону
MIN_DISTINCT_CHARS = 12
WEAK_SECRETS = {"dev-only-change-me", "change_me", "secret", "changeme", "password"}


def validate_production_secrets(s: "Settings") -> None:
    """fail-closed: слабый секрет в production останавливает запуск."""
    if not s.is_production:
        return
    problems: list[str] = []
    if s.jwt_secret in WEAK_SECRETS:
        problems.append("JWT_SECRET имеет значение по умолчанию")
    if len(set(s.jwt_secret)) < MIN_DISTINCT_CHARS:
        problems.append(f"в JWT_SECRET только {len(set(s.jwt_secret))} различных символов, "
                        f"требуется {MIN_DISTINCT_CHARS}")
    if len(s.jwt_secret) < MIN_SECRET_LENGTH:
        problems.append(f"JWT_SECRET короче {MIN_SECRET_LENGTH} символов "
                        f"(сейчас {len(s.jwt_secret)})")
    entropy = _secret_entropy_bits(s.jwt_secret)
    if entropy < MIN_SECRET_ENTROPY_BITS:
        problems.append(f"энтропия JWT_SECRET около {entropy:.0f} бит, "
                        f"требуется {MIN_SECRET_ENTROPY_BITS}")
    if not s.secure_cookies:
        problems.append("COOKIE_SECURE отключён: cookie уйдут по незащищённому каналу")
    for name, value in (("DB_RUNTIME_PASSWORD", s.db_runtime_password),
                        ("DB_AUDIT_PASSWORD", s.db_audit_password)):
        if value.startswith("test_") or value.startswith("change_me"):
            problems.append(f"{name} имеет значение по умолчанию")
    if problems:
        raise RuntimeError("Небезопасная конфигурация production: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    validate_production_secrets(s)
    return s
