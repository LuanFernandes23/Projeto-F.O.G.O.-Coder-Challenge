"""Configuração centralizada da aplicação (única fonte de variáveis de ambiente)."""

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "F.O.G.O. API"
    app_env: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    timezone: str = "America/Sao_Paulo"
    cors_origins: list[str] = Field(default_factory=list)

    database_url: str = "postgresql+psycopg://fogo:fogo@localhost:5544/fogo"
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    db_pool_recycle_seconds: int = Field(default=1800, gt=0)
    db_connect_timeout_seconds: int = Field(default=5, gt=0)
    db_statement_timeout_ms: int = Field(default=15000, gt=0)

    jwt_secret_key: SecretStr = SecretStr("troque-esta-chave-em-producao-com-32+-caracteres")
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=60, gt=0)

    http_timeout_seconds: float = Field(default=3.0, gt=0)
    viacep_base_url: str = "https://viacep.com.br"
    brasilapi_base_url: str = "https://brasilapi.com.br"
    cep_cache_ttl_seconds: int = Field(default=86400, gt=0)
    cep_cache_max_entries: int = Field(default=5000, gt=0)

    maintenance_due_soon_days: int = Field(default=7, ge=0)
    preventive_job_hour: int = Field(default=3, ge=0, le=23)
    job_timeout_seconds: float = Field(default=300.0, gt=0)

    iot_gateway_key: SecretStr = SecretStr("troque-esta-chave-do-gateway-iot")
    alert_sweep_interval_seconds: int = Field(default=60, ge=10)
    telemetry_retention_days: int = Field(default=90, ge=1)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)
    sse_queue_size: int = Field(default=500, ge=10)

    simulator_enabled: bool = True
    simulator_api_url: str = "http://api:8000"
    simulator_tick_seconds: float = Field(default=5.0, gt=0)
    simulator_heartbeat_seconds: float = Field(default=30.0, gt=0)
    simulator_mean_seconds_between_faults: float = Field(default=180.0, gt=0)
    simulator_seed: int = 2026

    # Parte 3 — previsões, base de conhecimento, IA (chave do usuário) e PROMETHEUS
    prediction_refresh_minutes: int = Field(default=5, ge=1)
    anomaly_scan_seconds: int = Field(default=60, ge=10)
    prometheus_cycle_seconds: int = Field(default=60, ge=10)
    prometheus_email: str = "prometheus@fogo.dev"
    # Chave Fernet que cifra a chave de API do modelo de IA no banco. Gere uma com:
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ai_encryption_key: SecretStr = SecretStr("")
    ai_timeout_seconds: float = Field(default=30.0, gt=0)
    embeddings_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embeddings_cache_dir: str | None = None
    knowledge_dir: str = "knowledge"

    first_admin_email: str = "admin@fogo.dev"
    first_admin_password: SecretStr = SecretStr("Fogo@2026")
    first_admin_name: str = "Administrador F.O.G.O."
    seed_demo_data: bool = False
    demo_users_password: SecretStr = SecretStr("Fogo@2026")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
