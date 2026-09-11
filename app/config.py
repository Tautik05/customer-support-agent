import os
import urllib.parse
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Customer Support Resolution System"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    PORT: int = int(os.getenv("PORT", 8000))
    
    # Database Settings
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    SYNC_DATABASE_URL: str = os.getenv("SYNC_DATABASE_URL", "")
    
    # Groq LLM Settings
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    PRIMARY_MODEL: str = os.getenv("PRIMARY_MODEL", "openai/gpt-oss-120b")
    FALLBACK_MODELS: str = os.getenv("FALLBACK_MODELS", "openai/gpt-oss-20b,qwen/qwen3.6-27b,groq/compound")

    
    @property
    def fallback_model_list(self) -> List[str]:
        return [m.strip() for m in self.FALLBACK_MODELS.split(",") if m.strip()]
    
    def get_async_db_url(self) -> str:
        raw_url = self.DATABASE_URL or os.getenv("POSTGRES_URL", "")
        if not raw_url:
            return "sqlite+aiosqlite:///./support_system.db"
        
        if raw_url.startswith("sqlite"):
            return raw_url

        # Parse and sanitize for asyncpg
        parsed = urllib.parse.urlparse(raw_url)
        qs = urllib.parse.parse_qs(parsed.query)
        new_query = {}
        
        # asyncpg requires ssl=require instead of sslmode=require and rejects channel_binding
        if "sslmode" in qs or "ssl" in qs or "neon.tech" in parsed.netloc:
            new_query["ssl"] = "require"
            
        cleaned_url = urllib.parse.urlunparse((
            "postgresql+asyncpg",
            parsed.netloc,
            parsed.path,
            parsed.params,
            urllib.parse.urlencode(new_query),
            parsed.fragment
        ))
        return cleaned_url

    def get_sync_db_url(self) -> str:
        raw_url = self.SYNC_DATABASE_URL or self.DATABASE_URL or os.getenv("POSTGRES_URL", "")
        if not raw_url:
            return "sqlite:///./support_system.db"
        if raw_url.startswith("sqlite"):
            return "sqlite:///./support_system.db"
            
        parsed = urllib.parse.urlparse(raw_url)
        cleaned_url = urllib.parse.urlunparse((
            "postgresql",
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
        return cleaned_url

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
