from pydantic_settings import BaseSettings
from functools import lru_cache
import copy
from typing import List, Optional
import os

class Settings(BaseSettings):
    """Application settings using Pydantic BaseSettings for validation"""
    
    # Application
    app_name: str = "Zendriver Browser Automation API"
    version: str = "3.0.0"
    debug: bool = False
    log_level: str = "INFO" 
    
    # Browser settings
    browser_headless: bool = False
    browser_executable_path: Optional[str] = None
    browser_args: List[str] = [
        "--enable-features=UseOzonePlatform",
        "--ozone-platform=wayland",
        "--disable-blink-features=AutomationControlled"
    ]
    
    # Paths
    data_dir: str = "/app/data"
    exports_dir: str = "/tmp/exports"
    
    # Database in /tmp (ephemeral, no permission issues)
    database_url: str = "sqlite:///tmp/research.db"
    
    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_delay: float = 2.0
    rate_limit_per_minute: int = 30
    
    # Caching
    cache_enabled: bool = True
    cache_ttl: int = 300  # 5 minutes
    redis_url: Optional[str] = None  # Use Redis if available
    
    # API settings
    cors_origins: List[str] = ["*"]
    api_prefix: str = "/api/v1"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    return Settings()

def get_cache_settings() -> Settings:
    """Get a copy of settings for cache service"""
    settings = copy.deepcopy(get_settings())
    if not settings.redis_url:
        settings.redis_url = os.getenv("REDIS_URL", "redis://redis-cache:6379")
    return settings
