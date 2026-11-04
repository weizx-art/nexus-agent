from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，从环境变量 / .env 读取"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 应用 ----
    APP_NAME: str = "nexus-agent"
    API_PREFIX: str = "/api"

    # ---- CORS 跨域 ----
    CORS_ORIGINS: str = "*"  # 逗号分隔的允许域名，如 "http://localhost:3000,https://example.com"

    # ---- 数据库（PostgreSQL）----
    DATABASE_URI: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nexus_agent"
    DB_ECHO: bool = False

    # ---- JWT ----
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30

    # ---- MinIO / S3 对象存储 ----
    MINIO_ENDPOINT_URL: str = "http://localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "nexus-agent"

    # ---- Weaviate 向量数据库 ----
    WEAVIATE_URL: str = "http://localhost:8080"
    WEAVIATE_API_KEY: str = ""

    # ---- Redis（embedding 向量缓存）----
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # ---- Embedding 模型 ----
    EMBEDDING_MODEL_NAME: str = "Alibaba-NLP/gte-multilingual-base"

    # ---- LLM 大语言模型（兼容 OpenAI API 格式）----
    LLM_API_KEY: str = ""
    LLM_API_BASE: str = "https://api.deepseek.com"
    LLM_MODEL_NAME: str = "deepseek-v4-flash"

    @property
    def cors_origins_list(self) -> list[str]:
        """解析 CORS_ORIGINS 为列表"""
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
