"""
Application Configuration
Loads settings from environment variables
"""
from pydantic_settings import BaseSettings
from pydantic import Field
import os
from pathlib import Path

class Settings(BaseSettings):
    """Application settings from environment variables"""
    
    
    # CrowdSec
    crowdsec_host: str = Field(default="https://localhost:8080", alias="CROWDSEC_HOST")
    crowdsec_tls_cert: str = Field(default="tls/client.crt", alias="CROWDSEC_TLS_CERT")
    crowdsec_tls_key: str = Field(default="tls/client.key", alias="CROWDSEC_TLS_KEY")
    crowdsec_tls_ca: str = Field(default="tls/ca.crt", alias="CROWDSEC_TLS_CA")
    
    # FastAPI
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    debug: bool = Field(default=False, alias="DEBUG")
    
    # Security
    secret_key: str = Field(default="change-me-in-production", alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # Redis
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")
    
    # CORS
    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    @property
    def redis_url(self) -> str:
        """Construct Redis connection URL"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
    
    @property
    def tls_cert_path(self) -> Path:
        """Get absolute path to TLS certificate"""
        path = Path(self.crowdsec_tls_cert)
        if not path.is_absolute():
            path = Path(__file__).parent.parent / path
        return path.resolve()
    
    @property
    def tls_key_path(self) -> Path:
        """Get absolute path to TLS key"""
        path = Path(self.crowdsec_tls_key)
        if not path.is_absolute():
            path = Path(__file__).parent.parent / path
        return path.resolve()
    
    @property
    def tls_ca_path(self) -> Path:
        """Get absolute path to TLS CA certificate"""
        path = Path(self.crowdsec_tls_ca)
        if not path.is_absolute():
            path = Path(__file__).parent.parent / path
        return path.resolve()
    
    def validate_tls_certificates(self):
        """Validate that TLS certificate files exist and are readable"""
        errors = []
        
        if not self.tls_cert_path.exists():
            errors.append(f"Certificate file not found: {self.tls_cert_path}")
        elif not os.access(self.tls_cert_path, os.R_OK):
            errors.append(f"Certificate file not readable: {self.tls_cert_path}")
        
        if not self.tls_key_path.exists():
            errors.append(f"Key file not found: {self.tls_key_path}")
        elif not os.access(self.tls_key_path, os.R_OK):
            errors.append(f"Key file not readable: {self.tls_key_path}")
        
        if not self.tls_ca_path.exists():
            errors.append(f"CA certificate file not found: {self.tls_ca_path}")
        elif not os.access(self.tls_ca_path, os.R_OK):
            errors.append(f"CA certificate file not readable: {self.tls_ca_path}")
        
        if errors:
            return False, "\n".join(errors)
        return True, "All TLS certificates are accessible"

# Load settings
settings = Settings()
