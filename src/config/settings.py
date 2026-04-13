import json

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    @model_validator(mode="before")
    @classmethod
    def _coerce_empty_int_strings(cls, data: dict) -> dict:
        """Converte strings vazias para o valor padrão dos campos int.

        EasyPanel e alguns orquestradores passam variáveis não configuradas
        como string vazia ''. Pydantic não consegue coercir '' para int,
        portanto removemos a chave e deixamos o campo usar seu default.
        """
        int_fields = {
            "api_port", "postgres_port", "rabbitmq_port",
            "kommo_pipeline_id", "email_smtp_port", "jwt_expire_minutes",
        }
        for field in int_fields:
            if data.get(field) == "":
                del data[field]
        return data

    # Aplicacao
    app_name: str = "andreia-residere"
    app_env: str = "development"
    debug: bool = True

    # FastAPI
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "andreia_db"
    postgres_user: str = "andreia"
    postgres_password: str = "andreia_secret"

    @computed_field
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @computed_field
    @property
    def database_url_sync(self) -> str:
        """URL sincrona para Alembic migrations."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # RabbitMQ
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "andreia"
    rabbitmq_password: str = "andreia_secret"

    @computed_field
    @property
    def rabbitmq_url(self) -> str:
        return f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}@{self.rabbitmq_host}:{self.rabbitmq_port}/"

    # UAZAPI (WhatsApp)
    uazapi_base_url: str = ""
    uazapi_token: str = ""
    uazapi_instance_id: str = ""

    # Webhook
    webhook_secret: str = ""

    # LLM
    openai_api_key: str = ""

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "andreia-residere"

    # CRM genérico (legado)
    crm_base_url: str = ""
    crm_api_key: str = ""
    crm_pipeline_id: str = ""

    # KOMMO CRM
    kommo_subdomain: str = ""           # só o subdomínio, ex: "suaempresa"
    kommo_access_token: str = ""        # long-lived token das integrações do KOMMO
    kommo_pipeline_id: int = 0          # ID do pipeline no KOMMO
    # JSON mapeando stage interno → ID numérico do stage no KOMMO
    # ex: '{"lead_novo": 1000, "em_qualificacao": 1001, "oportunidade_quente": 1002}'
    kommo_stage_map: str = "{}"

    @computed_field
    @property
    def kommo_stage_map_dict(self) -> dict[str, int]:
        """Desserializa o JSON de mapeamento de stages KOMMO."""
        try:
            return json.loads(self.kommo_stage_map)
        except Exception:
            return {}

    # Email Marketing
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_smtp_user: str = ""
    email_smtp_password: str = ""
    email_from: str = ""
    email_from_name: str = "Residere Imoveis"

    # Emails de especialistas por fluxo
    email_especialista_lancamento: str = ""  # destinatário para leads quentes de lançamento
    email_corretor: str = ""  # destinatário para notificação de visita agendada (investidor)

    # Agendamento (Agenda Avaliador/Consultor/Especialista/Corretor)
    appointment_base_url: str = ""
    appointment_api_key: str = ""

    # Notificacoes para Corretores (WhatsApp)
    corretor_phones: str = ""  # separados por virgula: "5565999991111,5565999992222"

    # JWT Auth
    jwt_secret_key: str = "change-me-in-production-use-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 dias

    @computed_field
    @property
    def corretor_phones_list(self) -> list[str]:
        """Lista de telefones dos corretores para notificacoes."""
        if not self.corretor_phones:
            return []
        return [p.strip() for p in self.corretor_phones.split(",") if p.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
