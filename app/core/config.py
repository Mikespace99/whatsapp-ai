import os
from dotenv import load_dotenv

# Load .env file only for local development if not in container/cloud
load_dotenv(override=False)

class Settings:
    @property
    def OPENAI_API_KEY(self) -> str:
        return os.environ.get("OPENAI_API_KEY", "").strip()
        
    @property
    def AI_MODEL(self) -> str:
        return os.environ.get("AI_MODEL", "gpt-4o-mini").strip()
        
    @property
    def GOOGLE_CLIENT_ID(self) -> str:
        return os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        
    @property
    def GOOGLE_CLIENT_SECRET(self) -> str:
        return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
        
    @property
    def GOOGLE_REDIRECT_URI(self) -> str:
        return os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback").strip()
        
    @property
    def VERIFY_TOKEN(self) -> str:
        return os.environ.get("VERIFY_TOKEN", "my-saas-verify-token").strip()
        
    @property
    def DATABASE_URL(self) -> str:
        return os.environ.get("DATABASE_URL", "sqlite:///./app.db").strip()
        
    @property
    def PORT(self) -> int:
        return int(os.environ.get("PORT", "8000"))

settings = Settings()
