from __future__ import annotations
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    temporal_address: str = Field("temporal:7233", env="TEMPORAL_ADDRESS")
    temporal_namespace: str = Field("default", env="TEMPORAL_NAMESPACE")
    temporal_task_queue: str = Field("main", env="TEMPORAL_TASK_QUEUE")
    supabase_url: str = Field("http://host.docker.internal:54321", env="SUPABASE_URL")
    supabase_service_role_key: str = Field("dev-service-role-key", env="SUPABASE_SERVICE_ROLE_KEY")

    # --- AI document summarization (French -> English via Claude Sonnet 4.6 on Azure) ---
    # Feature flag so the intake poller can be disabled without removing the worker.
    ai_summarization_enabled: bool = Field(True, env="AI_SUMMARIZATION_ENABLED")
    # Azure AI Foundry inference endpoint serving Claude via the Anthropic Messages
    # API. Reuses the project-wide AZURE_AI_* env (see .env.example). Secret key is
    # injected via env only -- never committed.
    azure_ai_inference_endpoint: str = Field("", env="AZURE_AI_INFERENCE_ENDPOINT")
    azure_ai_api_key: str = Field("", env="AZURE_AI_API_KEY")
    azure_anthropic_api_version: str = Field("2025-04-01-preview", env="AZURE_ANTHROPIC_API_VERSION")
    # Claude *Sonnet 4.6* deployment used for summarization (configurable per project).
    azure_ai_summary_deployment: str = Field("claude-sonnet-4-6", env="AZURE_AI_SUMMARY_DEPLOYMENT")
    # Hard input cap (512 KB) and chunk threshold (128 KB) for summarization.
    summarization_max_input_bytes: int = Field(524288, env="SUMMARIZATION_MAX_INPUT_BYTES")
    summarization_chunk_threshold_bytes: int = Field(131072, env="SUMMARIZATION_CHUNK_THRESHOLD_BYTES")
    # Storage bucket holding uploaded documents.
    documents_bucket: str = Field("documents", env="DOCUMENTS_BUCKET")
    # How often the intake poller looks for newly uploaded requests.
    summary_poll_interval_seconds: float = Field(5.0, env="SUMMARY_POLL_INTERVAL_SECONDS")

    class Config:
        case_sensitive = False

settings = Settings()
